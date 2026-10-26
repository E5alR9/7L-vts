import os
import sys
import io
import time
import asyncio
import numpy as np
import soundfile as sf
import re
import unicodedata

os.environ["WANDB_DISABLED"] = "true"
os.environ["WANDB_SILENT"] = "true"

# 確保 Windows 終端輸出中日文字元不崩潰
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys, '__stdout__') and hasattr(sys.__stdout__, 'reconfigure'):
    try:
        sys.__stdout__.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

#  路徑改為「環境變數優先、退回使用者家目錄」，不再寫死原作者電腦
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # 專案根目錄（單獨跑本檔時 import core 用）
from core.paths import GPT_SOVITS_DIR, FINETUNE_DATA_DIR, REF_VOICE_ZH, REF_VOICE_JA
from core.lang import KANA_RE, HAN_RE, is_japanese_sentence

BASE_DIR = GPT_SOVITS_DIR
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)
    sys.path.append(os.path.join(BASE_DIR, "GPT_SoVITS"))

import threading
from contextlib import contextmanager

# SoVITS 切分策略（2026-10-11：cut5 把短句切成 N 小片，某一片會整片靜音且等長，
# 時長守衛看不出來；直播都 ≤60 字，整段一坨最穩）。
# 2026-10-25 起長句由 _split_for_tts 在句末標點切段、每段自己檢查重抽；模型內部仍是 cut0。
XIAOYI_SPLIT_METHOD = "cut0"
XIAOYI_HALF = False   # 精度（2026-10-11：同 RVC，fp32 拉滿；改 True 切回半精度。代價：idle VRAM +1~2GB、每句慢幾秒）

class _WebLogStream:
    """攔截終端輸出並轉發至 Web Dashboard 後台，避免在主終端洗畫面，並即時解析生成進度"""
    def __init__(self, prefix="[GPT-SoVITS] "):
        self.prefix = prefix
        self._pending = ""   # 還沒湊滿一行的輸出（別叫 buffer：那是標準輸出的二進位通道名）
        self.total_bert_steps = 1
        self.current_bert_step = 0
        self._owner = None  # 進入 capture 的線程 id：只解析主人的輸出（2026-10-11）
        self._real_out = None  # 原 stdout：別的線程（如 RVC）原樣放行，不攔截
        self._last_progress = ("", 0.0)   # 上次推給後台的進度（階段, 時間）：同一階段最多 0.3 秒推一次

    def _attr(self, name):
        """自己的屬性一律從 __dict__ 拿：讀不到就當沒設，不要經 __getattr__ 丟出只寫名字的錯誤
        （2026-10-26 子智能體執行時冒出「_owner」，就是這裡）。"""
        return self.__dict__.get(name)

    def _dispatch_progress(self, line: str):
        try:
            import services.web_dashboard as web_dash
            # 解析 GPT-SoVITS 關鍵階段
            stage = ""
            pct = None
            detail = ""

            if "切分" in line or "cut" in line.lower():
                stage = "切分文字中"
                pct = 15
                detail = line
            elif "实际输入的目标文本" in line or "實際輸入的目標文本" in line:
                stage = "文本切句分析"
                pct = 25
            elif "Bert" in line or "BERT" in line or "bert" in line:
                stage = "提取文字 BERT 特徵"
                pct = 40
            elif "%|" in line:
                # tqdm 進度條匹配 e.g. 100%|████████| 1/1 [00:00<00:00, 42.73it/s]
                import re
                m = re.search(r'(\d+)%', line)
                if m:
                    tqdm_pct = int(m.group(1))
                    pct = 40 + int(tqdm_pct * 0.25)  # 40% ~ 65%
                    # 2026-10-11：這裡只會收到主人（SoVITS）線程的輸出，
                    # RVC 的 tqdm 連線程門都過不了。舊碼用 _IS_PRODUCING_COVER
                    # 把 SoVITS 自己的 BERT 條硬標成 RVC，已刪除。
                    stage = "提取 BERT 特徵進度"
                    detail = line
            elif "前端处理后的文本" in line or "前端處理後的文本" in line:
                stage = "音素音律對齊"
                pct = 70
                detail = line
            elif "预测语义" in line or "預測語意" in line or "Token" in line:
                stage = "預測語意 Token (T2S)"
                pct = 85
            elif "合成音频" in line or "合成音頻" in line or "并行合成" in line or "並行合成" in line:
                stage = "聲學模型推理合成 (VITS)"
                pct = 95
            elif "推理" in line:
                stage = "神經網路推理中"
                pct = 75

            last_stage, last_t = self._attr("_last_progress") or ("", 0.0)
            if stage and (stage != last_stage or time.time() - last_t >= 0.3):
                # 2026-10-26 實測一句話推二十幾則進度、加上日誌每秒 8 則以上，後台處理不完，畫面跟不上
                self.__dict__["_last_progress"] = (stage, time.time())
                web_dash.broadcast_event("tts_progress", {
                    "active": True,
                    "stage": stage,
                    "percent": pct,
                    "detail": detail or line,
                    "text": line
                })
        except Exception:
            pass

    def write(self, s):
        if not s:
            return
        #  2026-10-11：sys.stdout 是全進程共享的，RVC 在別的線程的 tqdm 也會寫進來。
        #  非主人的輸出原樣放行到真終端，不解析、不廣播（否則 RVC 進度污染粉色 TTS 框）。
        owner = self._attr("_owner")
        if owner is not None and threading.get_ident() != owner:
            try:
                (self._attr("_real_out") or sys.__stdout__).write(s)
            except Exception:
                pass
            return
        self._pending += s
        while "\n" in self._pending or "\r" in self._pending:
            split_idx = min([i for i in [self._pending.find("\n"), self._pending.find("\r")] if i != -1])
            line = self._pending[:split_idx].strip()
            self._pending = self._pending[split_idx+1:]
            if line:
                if "%|" not in line:   # tqdm 進度條只拿來算進度，不推進後台日誌（一句話會推幾十行）
                    try:
                        import services.web_dashboard as web_dash
                        web_dash.broadcast_event("tts_log", {"text": f"{self.prefix}{line}"})
                    except Exception:
                        pass
                self._dispatch_progress(line)

    def __getattr__(self, name):
        # 其他屬性（encoding、buffer、isatty、fileno…）交給真正的終端：sys.stdout 是全進程共用的，
        # 別的執行緒、套件拿 sys.stdout.buffer 之類的不能因為 TTS 正在攔截就炸掉（2026-10-25 狀態列崩潰）
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._attr("_real_out") or sys.__stdout__, name)

    def flush(self):
        owner = self._attr("_owner")
        if owner is not None and threading.get_ident() != owner:
            try:
                (self._attr("_real_out") or sys.__stdout__).flush()   # 別人的 flush 不能搶走 TTS 還沒寫完的那一行
            except Exception:
                pass
            return
        line = (self._attr("_pending") or "").strip()
        self._pending = ""
        if line:
            if "%|" not in line:
                try:
                    import services.web_dashboard as web_dash
                    web_dash.broadcast_event("tts_log", {"text": f"{self.prefix}{line}"})
                except Exception:
                    pass
            self._dispatch_progress(line)

class _ThreadRoutedStream:
    """裝上 sys.stdout／sys.stderr 之後就不再拔掉：登記在 _CAPTURES 的執行緒寫到它的 _WebLogStream，其他照常寫真終端。

    2026-10-27 直播崩潰（0xC0000005，一晚 14 次）的真兇：以前 capture_tts_output 每段合成都把全域 sys.stdout
    換掉再換回。Python 3.12 的 print 拿 sys.stdout 不加參照，主執行緒狀態列 print 寫終端時會放開 GIL，
    曉伊執行緒這時換回原本的 stdout，暫時物件就被釋放，print 回來用到已釋放的記憶體，整個 python 崩掉。
    輸出導到檔案時寫入太快碰不到，只有開真終端（V7.bat）才會崩；在真終端用小腳本 20 秒內就能重現。"""

    def __init__(self, real):
        self._real = real

    def _target(self):
        return _CAPTURES.get(threading.get_ident()) or self._real

    def write(self, s):
        return self._target().write(s)

    def flush(self):
        return self._target().flush()

    def __getattr__(self, name):
        # encoding、buffer、isatty、fileno… 都交給真終端
        return getattr(self._real, name)


_CAPTURES = {}   # 執行緒 id → 這條執行緒正在用的 _WebLogStream
_ROUTER_LOCK = threading.Lock()


def _install_routers():
    with _ROUTER_LOCK:
        if not isinstance(sys.stdout, _ThreadRoutedStream):
            sys.stdout = _ThreadRoutedStream(sys.stdout)
        if not isinstance(sys.stderr, _ThreadRoutedStream):
            sys.stderr = _ThreadRoutedStream(sys.stderr)


@contextmanager
def capture_tts_output():
    """將區塊內這條執行緒的 print/tqdm 導向 Web 後台，不印在控制台；別的執行緒（狀態列、RVC 背景任務）照常印。
    全域 sys.stdout 只在第一次換成分流物件，之後不再換（換回會讓別的執行緒的 print 用到已釋放的物件，見 _ThreadRoutedStream）。"""
    _install_routers()
    tid = threading.get_ident()
    redir = _WebLogStream()
    redir._owner = tid
    redir._real_out = getattr(sys.stdout, "_real", None) or sys.__stdout__
    prev = _CAPTURES.get(tid)
    _CAPTURES[tid] = redir
    try:
        yield
    finally:
        try:
            redir.flush()
        except Exception:
            pass
        if prev is None:
            _CAPTURES.pop(tid, None)
        else:
            _CAPTURES[tid] = prev

_tts_pipeline = None
# 可重入：synthesize_xiaoyi_bytes 拿著鎖時，模型還沒載好會再呼叫 init_gpt_sovits（它也要拿這把鎖）。
# 以前是一般 Lock，那一刻就永遠鎖死，之後每次合成都多卡一條背景執行緒，卡滿後連後台首頁都打不開（2026-10-27 長測抓到）
_thread_lock = threading.RLock()
_REF_ZH = None   # 實際用的中文參考音（停頓壓短版，見 _tight_ref）
_REF_JA = None   # 日文同理：實測失敗率 4/12 → 1/12


# top_p 必須是 1.0（不做核心取樣）：0.8 時念到停頓處，「靜音」單位的機率就佔滿那 80%，候選裡只剩靜音，
# 「結束」和「繼續說話」都被排除，於是空白一路生成到長度上限＝念一半就停。這是 TTS 失敗的根本原因：
# 2026-10-25 實測一次只改一個參數，top_p 0.8→1.0 失敗 15%→0/16；只升溫度 12%、只降 top_k 反而 38%。
_TOP_P = 1.0
_SEGMENT_CHARS = 22   # 整句不合格時的備援切段長度；0 = 不切段
_USE_TIGHT_REF = True  # 參考音用句間停頓壓短版（見 _tight_ref）；False = 用原檔
_SEGMENT_TRIES = 3


def _split_for_tts(text: str, limit: int = None) -> list:
    """長句在句末標點（。！？）切成短段，單句還太長就再從逗號切；太短的段併回前一段。不超過 limit 字就不切。

    為什麼是 22 字：曉伊的 GPT 微調資料 179 段最長 7.9 秒、28 字（中位數 14 字）。超過這長度的句子
    模型沒看過，常念完第一句就停住、後面全是空白到長度上限（2026-10-25 實測長句整句合成約 1/3 失敗）。"""
    limit = _SEGMENT_CHARS if limit is None else limit
    if limit <= 0 or len(text) <= limit:
        return [text]
    parts = []
    for p in re.split(r"(?<=[。！？!?])", text):
        if not p.strip():
            continue
        if len(p) <= limit:
            parts.append(p)
        else:
            parts += [q for q in re.split(r"(?<=[，、；,;])", p) if q.strip()]
    out = []
    for p in parts:
        if out and len(out[-1]) + len(p) <= limit:
            out[-1] += p
        else:
            out.append(p)
    return out or [text]


# ── 中日混合句的語言分段修正 ──────────────────────────────────────────
# GPT-SoVITS 的 auto 模式靠 split-lang 分段，漢字中日共用，只能看鄰居猜，交界處常猜錯（2026-10-25 實測）：
#   「這首歌叫做夜に駆ける」→「夜」被分進中文念成 yè；「さすが老爸」→「老爸」被分進日文念成「ろう」。
# 在它分完之後補一層交界修正；整句仍是一次合成，語氣連貫。
# 漢字後面緊接這些假名，通常是助詞，前面的漢字屬於日文詞（夜に、歌を、空が、君の）
_JA_PARTICLE_START = set("にをがのはへでともやか")
# 中文才會出現在這種位置的字：看到就不搬進日文、或從日文切回中文
_ZH_ONLY_CHARS = set("爸媽們這那嗎呢吧啦喔囉哦嘛妳你您誰麼啊呀咧欸唷耶喲我他她的了是在叫做說唱彈聽跟和給把被讓很超也都就還")
_ZH_WORDS = ("老爸", "老媽", "大家", "各位", "觀眾", "朋友")
_LANG_REPAIR_ON = True


def _repair_lang_segments(segs: list, zh_main: bool = False) -> list:
    """修正 split-lang 在中日交界的分段：[{'lang','text'}...] → 同格式。只動 zh/ja 交界，其他原樣。
    zh_main：整句以中文為主。split-lang 只看漢字分不出中日，純中文段也常被判成日文
    （2026-10-25 實測：「感覺很有節奏感喔」「沒問題。」都被切成 ja，用日文發音念）；
    中文為主的句子裡，沒有假名的段一律算中文。"""
    segs = [dict(s) for s in segs]
    if zh_main:
        for s in segs:
            if s.get("lang") == "ja" and not KANA_RE.search(s.get("text", "")):
                s["lang"] = "zh"
    # 1. 中文段尾巴的漢字其實是後面日文詞的一部分（夜|に駆ける）：最多搬 2 個字，遇到中文才有的字就停
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if a.get("lang") != "zh" or b.get("lang") != "ja" or b["text"][:1] not in _JA_PARTICLE_START:
            continue
        keep, move = a["text"], ""
        while keep and len(move) < 2 and HAN_RE.match(keep[-1]) and keep[-1] not in _ZH_ONLY_CHARS:
            move, keep = keep[-1] + move, keep[:-1]
        if move and keep.strip():
            a["text"], b["text"] = keep, move + b["text"]
    # 2. 日文段尾巴接著中文詞（さすが老爸、ありがとう大家）：最後一個假名之後的漢字切回中文
    out = []
    for s in segs:
        if s.get("lang") == "ja":
            m = re.search(r"([一-鿿]+)([，,。！？!?、\s]*)$", s["text"])
            if m and KANA_RE.search(s["text"][:m.start()]) and (
                    set(m.group(1)) & _ZH_ONLY_CHARS or any(w in m.group(1) for w in _ZH_WORDS)):
                out.append({"lang": "ja", "text": s["text"][:m.start()]})
                out.append({"lang": "zh", "text": m.group(1) + m.group(2)})
                continue
        out.append(s)
    merged = []
    for s in out:
        if not s.get("text"):
            continue
        if merged and merged[-1].get("lang") == s.get("lang"):
            merged[-1]["text"] += s["text"]
        else:
            merged.append(s)
    return merged


def _install_lang_repair():
    """把 _repair_lang_segments 接到 GPT-SoVITS 的 auto 分段後面（只影響 auto，指定語言的不動）。"""
    try:
        from text.LangSegmenter import LangSegmenter
        if getattr(LangSegmenter, "_7l_lang_repair", False):
            return
        original = LangSegmenter.getTexts

        def _get_texts(text, default_lang=""):
            segs = original(text, default_lang)
            return segs if (default_lang or not _LANG_REPAIR_ON) else _repair_lang_segments(
                segs, zh_main=not is_japanese_sentence(text))

        LangSegmenter.getTexts = staticmethod(_get_texts)
        LangSegmenter._7l_lang_repair = True
    except Exception as e:
        print(f"⚠️ [GPT-SoVITS] 中日分段修正沒掛上（照原本分段）：{e}")


def _synth_segments(inputs: dict, segs: list, tries: int):
    """逐段合成，每段最多 tries 次（不合格才重抽）。回 (取樣率, 各段音訊, 是否每段都合格)。
    每段不合格到最後就用第一次的結果，交給整句檢查（tts_router）再把關。呼叫端要持有 _thread_lock。"""
    sr = None
    pieces = []
    all_ok = True
    for seg in segs:
        seg_inputs = dict(inputs, text=seg)
        first = None
        seg_ok = False
        # 生成長度上限跟著字數走：卡在靜音循環時早點停（模型預設 54 秒／1500 步，卡一次白等 10~20 秒）
        _tts_pipeline.configs.max_sec = _segment_max_sec(len(seg))
        for _attempt in range(tries):
            with capture_tts_output():
                chunks = list(_tts_pipeline.run(seg_inputs))
            if not chunks:
                continue
            sr = chunks[0][0]
            seg_audio = chunks[0][1] if len(chunks) == 1 else np.concatenate([c for _, c in chunks])
            if _segment_ok(seg_audio, sr, len(seg)):
                first, seg_ok = seg_audio, True
                break
            if first is None:
                first = seg_audio
        all_ok = all_ok and seg_ok
        if first is not None:
            pieces.append(first)
    return sr, pieces, all_ok


def _segment_max_sec(n_chars: int) -> int:
    """這段最多讓模型生成幾秒：預期長度的 3 倍、至少 8 秒。正常念完遠低於此，卡在靜音循環才會撞到。"""
    return int(max(8.0, n_chars * 0.22 * 3))


def _segment_ok(audio, sr: int, n_chars: int) -> bool:
    """一段合成結果像不像念完了：總長沒爆、有聲時間夠、中間沒有長空白。"""
    a = audio.astype(np.float32)
    if audio.dtype == np.int16:
        a /= 32768.0
    win = max(1, int(sr * 0.05))
    k = len(a) // win
    if k == 0:
        return False
    rms = np.sqrt(np.mean(a[: k * win].reshape(k, win) ** 2, axis=1))
    voiced = rms > max(0.01, float(rms.max()) * 0.05)
    idx = np.flatnonzero(voiced)
    if len(idx) == 0:
        return False
    expect = max(1.0, n_chars * 0.22)
    total = len(a) / sr
    gap = float(np.max(np.diff(idx)) - 1) * 0.05 if len(idx) > 1 else 0.0
    return total <= max(6.0, expect * 2.5) and voiced.sum() * 0.05 >= expect * 0.3 and gap <= 2.0


def _tight_ref(path: str) -> str:
    """回傳句間停頓壓到 0.25 秒的參考音（第一次用 ffmpeg 產生在原檔旁邊）；做不出來就用原檔。

    原參考音 7.3 秒裡有一半是句間停頓，模型會學著「念一兩個字就停住、後面全是靜音」：
    實測 12 次失敗 7 次；只壓停頓、音色不變，0/12 失敗，合成也從平均 10 秒變 2.5 秒（2026-10-25）。
    _USE_TIGHT_REF = False 可改回原檔（top_p 修好後兩者都穩定，差別只在句間停頓 0.32 vs 0.49 秒）。"""
    if not _USE_TIGHT_REF or not path or not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    out = f"{root}_tight{ext or '.wav'}"
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
        return out
    try:
        import subprocess
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-i", path, "-af",
                        "silenceremove=stop_periods=-1:stop_duration=0.25:stop_threshold=-40dB", out],
                       check=True, timeout=30)
        return out if os.path.exists(out) else path
    except Exception as e:
        print(f"⚠️ [GPT-SoVITS] 參考音停頓壓短失敗，改用原檔：{e}")
        return path

def init_gpt_sovits():
    global _tts_pipeline, _REF_ZH, _REF_JA
    with _thread_lock:
        if _tts_pipeline is not None:
            return _tts_pipeline
            
        prev_cwd = os.getcwd()
        try:
            os.chdir(BASE_DIR)
            from TTS_infer_pack.TTS import TTS, TTS_Config
            config = TTS_Config("GPT_SoVITS/configs/tts_infer.yaml")
            config.device = "cuda"
            config.is_half = XIAOYI_HALF
            config.t2s_weights_path = os.path.join(GPT_SOVITS_DIR, "GPT_weights_v2", "xiaoyi_finetune-e4.ckpt")
            config.vits_weights_path = os.path.join(FINETUNE_DATA_DIR, "opt", "xiaoyi_finetune", "xiaoyi_sovits_inference.pth")
            config.cnhubert_base_path = "pretrained_models/chinese-hubert-base"
            config.bert_base_path = "pretrained_models/chinese-roberta-wwm-ext-large"
            
            _tts_pipeline = TTS(config)
            _install_lang_repair()
            
            #  核心預熱與常駐快取：初始化時即完成參考音與文字 BERT 萃取，使後續所有合成省去 80% 時間！
            _REF_ZH = _tight_ref(REF_VOICE_ZH)
            _REF_JA = _tight_ref(REF_VOICE_JA)
            try:
                ref_audio = _REF_ZH
                ref_text = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
                with capture_tts_output():
                    _tts_pipeline.set_ref_audio(ref_audio)
                    # 預熱一次
                    _dummy = next(_tts_pipeline.run({
                        "text": "哈囉",
                        "text_lang": "auto",
                        "ref_audio_path": ref_audio,
                        "prompt_text": ref_text,
                        "prompt_lang": "zh",
                        "batch_size": 1,
                        "speed_factor": 1.0,
                    }))
            except Exception:
                pass
                
            return _tts_pipeline
        except Exception as e:
            print(f"❌ [GPT-SoVITS 初始化異常]: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            os.chdir(prev_cwd)

def synthesize_xiaoyi_bytes(text: str) -> bytes:
    """
    同步推論函數，回傳音訊 bytes（lameenc 在就 MP3，否則 WAV——別信舊註解說的 WAV）。
    """
    global _tts_pipeline
    with _thread_lock:
        if _tts_pipeline is None:
            init_gpt_sovits()
        if _tts_pipeline is None:
            print("❌ [_tts_pipeline 為 None，無法合成]")
            return b""
            
        try:
            #  語言判定：整句是不是日文（規則見 core.lang，跟 tts_router 共用同一份）
            import re
            num_kana = len(KANA_RE.findall(text))
            num_hanzi = len(HAN_RE.findall(text))
            is_real_japanese = is_japanese_sentence(text)
            
            if is_real_japanese:
                #  正統日語模式：採用高音甜美版曉伊日語提示音（360Hz 少女高音）
                ref_audio = _REF_JA or REF_VOICE_JA
                ref_text = "お兄ちゃん、今日も一日頑張ろうね！大好きだよ！"
                ref_lang = "all_ja"
                text_lang = "ja" if num_hanzi == 0 else "auto"
                top_k = 15
                top_p = _TOP_P
                temp = 0.65
                speed = 1.0
            else:
                #  中文主體模式：
                # 採用中文參考音訊。沒有假名就用 'zh'（GPT-SoVITS 的「中英混合」：英文段念英文、其他照中文念）；
                # 舊碼有英文字母（連還沒換成「小七」的 7L 也算）就改 'auto'，auto 只看漢字分不出中日，
                # 純中文段常被判成日文、用日文發音念（2026-10-25 老爸回報）。有假名才需要 auto
                ref_audio = _REF_ZH or REF_VOICE_ZH
                ref_text = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
                ref_lang = "all_zh"
                text_lang = "zh" if num_kana == 0 else "auto"
                top_k = 15
                top_p = _TOP_P
                temp = 0.80
                speed = 1.05
            
            #  符號與專有名詞防卡頓處理：將數學字母/全形/特殊符號正規化為標準 ASCII (修復 KeyError)
            text = unicodedata.normalize('NFKC', text)
            # 過濾非發音顏文字 (如 ⌒☆ )，波浪號/符號轉為元氣感嘆號「！」
            text = re.sub(r'[∠・ω<>\-_]+', '', text) # 改為只針對特定顏文字常見特殊符號移除
            text = re.sub(r'[⌒☆★♪♡✧✦๑•̀ㅂ•́و✧~～]+', '！', text)
            text = text.replace("7L", "小七").replace("7l", "小七")
            text = re.sub(r'[，,]{2,}', '，', text)
            text = re.sub(r'[！!]{2,}', '！', text).strip(' ，,')

            inputs = {
                "text": text,
                "text_lang": text_lang,
                "ref_audio_path": ref_audio,
                "prompt_text": ref_text,
                "prompt_lang": ref_lang,
                "top_k": top_k,
                "top_p": top_p,
                "temperature": temp,
                "text_split_method": XIAOYI_SPLIT_METHOD,
                "batch_size": 2, # 適度放大 batch_size 加速顯卡推理
                "speed_factor": speed,
                "repetition_penalty": 1.35,
            }
            
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("tts_progress", {
                    "active": True,
                    "stage": "啟動神經語音合成...",
                    "percent": 5,
                    "text": text[:35]
                })
            except Exception:
                pass

            # 先整句合成（快、語氣自然）；不合格才把長句切段、每段自己檢查重抽（備援）。
            # top_p 改 1.0 後整句 0/120 失敗、平均 2.6 秒；分段版一樣 0 失敗但平均 3.0、最慢 11.8 秒（2026-10-25）
            plans = [[text]]
            if _SEGMENT_CHARS > 0 and len(text) > _SEGMENT_CHARS:
                plans.append(_split_for_tts(text))
            sr = None
            pieces = []
            _orig_max_sec = _tts_pipeline.configs.max_sec
            try:
                for plan_idx, segs in enumerate(plans):
                    tries = 1 if plan_idx < len(plans) - 1 else _SEGMENT_TRIES   # 還有備援就只試一次整句
                    sr, pieces, all_ok = _synth_segments(inputs, segs, tries)
                    if all_ok:
                        break
                    print(f"⚠️ [GPT-SoVITS] 合成不完整，{'改切段重來' if plan_idx < len(plans) - 1 else '重抽後仍不合格'}：{text[:20]}")
            finally:
                _tts_pipeline.configs.max_sec = _orig_max_sec
            if not pieces:
                try:
                    import services.web_dashboard as web_dash
                    web_dash.broadcast_event("tts_progress", {"active": False, "stage": "完成", "percent": 100})
                except Exception:
                    pass
                return b""
            if len(pieces) == 1:
                audio = pieces[0]
            else:
                pause = np.zeros(int(sr * 0.08), dtype=pieces[0].dtype)   # 段與段之間留一點換氣
                audio = np.concatenate([x for i, p in enumerate(pieces) for x in ((pause, p) if i else (p,))])
            
            # 轉為 16-bit PCM numpy 陣列
            if audio.dtype != np.int16:
                if audio.dtype == np.float32 or audio.dtype == np.float64:
                    #  Peak Normalize：峰值超過 0.95 時整體等比縮放，絕對杜絕削波爆音
                    peak = np.abs(audio).max()
                    if peak > 0.95:
                        audio = audio * (0.92 / peak)
                    audio_clipped = np.clip(audio, -1.0, 1.0)
                    pcm_data = (audio_clipped * 32767.0).astype(np.int16)
                else:
                    pcm_data = audio.astype(np.int16)
            else:
                pcm_data = audio
                
            # 確保是 bytes
            pcm_bytes = pcm_data.tobytes()
            
            # 廣播合成完成
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("tts_progress", {"active": False, "stage": "語音生成完畢", "percent": 100})
            except Exception:
                pass

            # 使用 lameenc 編碼為高清 192kbps MP3
            try:
                import lameenc
                encoder = lameenc.Encoder()
                encoder.set_bit_rate(192)
                encoder.set_in_sample_rate(sr)
                encoder.set_channels(1)
                encoder.set_quality(2)  # 2 = 高品質且相容性佳 (0 偶有爆音相容問題)
                mp3_data = encoder.encode(pcm_bytes)
                mp3_data += encoder.flush()
                return bytes(mp3_data)
            except Exception as e:
                # 若 lameenc 失敗則回傳標準 WAV
                buf = io.BytesIO()
                sf.write(buf, audio, sr, format='WAV')
                return buf.getvalue()
        except Exception as e:
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("tts_progress", {"active": False, "stage": f"合成異常: {e}", "percent": 0})
            except Exception:
                pass
            print(f"❌ [GPT-SoVITS 合成異常]: {e}")
            import traceback
            traceback.print_exc()
            return b""

async def get_xiaoyi_audio_bytes(text: str) -> bytes:
    """
    非同步調用封裝，防止阻塞主線程
    """
    return await asyncio.to_thread(synthesize_xiaoyi_bytes, text)

if __name__ == "__main__":
    import asyncio
    async def test():
        b = await get_xiaoyi_audio_bytes("哈囉！老爸，我現在已經成功升級到本地顯卡運算囉！")
        print("合成音訊字節數:", len(b))
    asyncio.run(test())
