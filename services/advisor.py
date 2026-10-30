# -*- coding: utf-8 -*-
"""軍師（2026-10-29 老爸：3.8 think 放去當 Live 主腦的常駐子代理，一直在旁邊聽、給主腦建議）。

以前「說完又想到」每次另開一條 3.8 think 單次連線，只看得到「這句人話＋她剛才的回答」，不記得前面講過什麼、
也看不到她交辦查到的結果。現在常駐一條連線：每輪把「誰說了什麼、她回了什麼、交辦結果」送進去，它記得前面的事，
她講錯（跟查到的不一致、記錯前面的話）、漏了重要的、或有明顯更好的接法時回一句「建議：…」，其他回 [SILENCE]。
建議由主程式遞紙條給主腦，講不講、怎麼講由她決定（軍師自己不出聲）。

實測（同一條連線連問 4 輪，thinking_level=low）：每輪 0.5～1 秒；記錯天氣、忘了週三降溫、
記錯老爸剛剛問什麼，三題都抓到，打招呼那輪 [SILENCE]。medium 每輪 6～9 秒、沒有比較準。
Live 只能回音訊，回答從音訊轉寫拿；15 分鐘換線、斷線都帶續接 handle 重連，不失憶。
"""
import asyncio
import random
import re
import time
from typing import Callable, List, Optional

from google import genai
from google.genai import types

from core import usage
from core.llm_engine import (DEEP_THINK_LIVE_MODEL, GEMINI_KEYS, held_live_connect, key_cooling, pick_live_key,
                              report_gemini_key_error)
from core.utils import log_print, log_swallowed, spawn

THINKING_LEVEL = "low"
ASK_TIMEOUT_SEC = 15.0     # 一輪最多等這麼久（實測 1 秒內）
NOTE_KEEP = 6              # 下一輪一起帶上的背景（交辦結果）最多幾則


class ResidentAdvisor:
    def __init__(self, system_fn: Callable[[], str], keys: Optional[List[str]] = None,
                 model: str = DEEP_THINK_LIVE_MODEL, connect=None, thinking_level: Optional[str] = THINKING_LEVEL,
                 label: str = "軍師"):
        """system_fn() → 系統提示詞（連線時才拿）；connect(key, model, config) → live.connect 的 async context manager（測試換假的）。"""
        self.system_fn = system_fn
        self.keys = keys if keys is not None else GEMINI_KEYS
        self.model = model
        # 一般 3.8 Live 帶思考設定會直接被拒（2026-10-30 實測 minimal、low 都連不上），傳 None 就不帶
        self.thinking_level = thinking_level
        self.label = label   # 日誌和用量表上的名字（副意識群裡每個各有分工）
        self._connect = connect or held_live_connect   # 連線期間把 key 記成佔用中，別條 Live 會避開
        self._lock = asyncio.Lock()
        self._cm = self._session = None
        self._key = ""
        self._handle = None        # 續接 handle：換線、斷線後接回同一段對話
        self._reconnect = False    # 伺服器預告換線：這輪問完就換
        self._notes: List[str] = []

    def note(self, text: str) -> None:
        """不用回的背景（交辦結果）：下一輪問的時候一起帶上。"""
        if text:
            self._notes = (self._notes + [text.strip()[:500]])[-NOTE_KEEP:]

    async def ask(self, text: str) -> str:
        """送一輪對話、等它回完；它沒建議（[SILENCE]）、連不上、逾時都回空字串。斷線會換一條重問一次。"""
        async with self._lock:
            body = "\n".join(self._notes + [text])
            self._notes = []
            for attempt in range(2):
                t0 = time.perf_counter()
                opening = False   # 只有「連線本身」失敗才算 handle 有問題；連上之後這輪出錯不算（Fable 審查）
                try:
                    if self._session is None:
                        opening = True
                        await self._open()
                        opening = False
                    out = await asyncio.wait_for(self._turn(body), timeout=ASK_TIMEOUT_SEC)
                    usage.note(self.model, True, role=self.label, ms=(time.perf_counter() - t0) * 1000)
                    if self._reconnect:
                        await self._close()
                    return out
                except Exception as e:
                    usage.note(self.model, False, role=self.label, rate_limited=usage.is_rate_limited(e),
                               ms=(time.perf_counter() - t0) * 1000)
                    if self._key:
                        report_gemini_key_error(self._key, e, self.model)
                    log_print(f"⚠️ [{self.label}] 連線出錯（{type(e).__name__}），{'換一條重問' if attempt == 0 else '這輪放棄'}")
                    await self._close()
                    if isinstance(e, asyncio.TimeoutError) or opening:
                        # 卡住的那段對話不接回去；連線一開就失敗也多半是 handle 過期或不屬於這把 key，
                        # 以前留著，之後每次都拿同一個壞 handle 連、整場軍師都回空的（2026-10-30 健檢）
                        self._handle = None
                except asyncio.CancelledError:
                    # 呼叫端不等了，這一輪還在常駐連線上沒讀完：留著下一輪會先讀到它的尾巴。丟掉，下一輪重連接回
                    cm, self._cm, self._session = self._cm, None, None
                    if cm is not None:
                        spawn(cm.__aexit__(None, None, None), f"{self.label}連線收掉")
                    raise
            return ""

    async def _open(self) -> None:
        pool = [k for k in self.keys if not key_cooling(k, self.model)] or list(self.keys)
        # 續接 handle 綁在原本那把 key 上（主腦也是這樣）：換別把接不回去。
        # 換 key 時挑沒被別條 Live（主腦、導演、哨兵…）佔著的（2026-10-30 老爸：不要用同一把 key 開）
        if not (self._handle and self._key in pool):
            self._key = pick_live_key(pool, self.model)
        cfg = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part.from_text(text=self.system_fn())]),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(handle=self._handle),
            context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        )
        if self.thinking_level:
            cfg.thinking_config = types.ThinkingConfig(thinking_level=self.thinking_level)
        self._cm = self._connect(self._key, self.model, cfg)
        self._session = await self._cm.__aenter__()
        self._reconnect = False
        log_print(f"🧭 [{self.label}] 常駐連線好了（{self.model}{'，接回前面的對話' if self._handle else ''}）")

    async def _close(self) -> None:
        cm, self._cm, self._session = self._cm, None, None
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                log_swallowed()

    async def _turn(self, body: str) -> str:
        s = self._session
        await s.send_client_content(turns=[types.Content(role="user", parts=[types.Part(text=body)])], turn_complete=True)
        out = ""
        async for r in s.receive():
            ru = getattr(r, "session_resumption_update", None)
            if ru and getattr(ru, "resumable", False) and getattr(ru, "new_handle", None):
                self._handle = ru.new_handle
            if getattr(r, "go_away", None):
                self._reconnect = True
            c = r.server_content
            if c and c.output_transcription and c.output_transcription.text:
                out += c.output_transcription.text
            if c and c.turn_complete:   # 只認 turn_complete：在 generation_complete 就停，剩下那則會被下一輪當成「回完了」
                break
        return clean_reply(out)


_TRANSCRIPT_NOISE = re.compile(r"<[^<>]{0,40}>|\{[^{}]{0,40}\}")


def clean_reply(out: str) -> str:
    """Live 只回音訊，回答是音訊轉寫：沒講話時偶爾轉出 <no speech>、{pause} 這種雜訊（2026-10-30 實測一般 3.8
    回了「<no speech>{pause}」，差點被當成建議遞給她）。清掉雜訊；剩下空的或 [SILENCE] 就當沒話說。"""
    out = _TRANSCRIPT_NOISE.sub("", out or "").strip()
    return "" if not out or "[SILENCE]" in out.upper() else out
