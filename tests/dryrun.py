# -*- coding: utf-8 -*-
"""乾跑 7L（2026-10-26）：不開 Live、不開鋼琴視窗、不合成語音、不碰麥克風和螢幕，
把主程式「輸入 → 分派 → 看板／紙條 → 主腦（Live 或 REST）→ 子智能體／舞台指令 → 說話佇列」這一串
從原始碼載進來跑，AI 和硬體換成假的，記下她說了什麼、遞了什麼紙條、派了什麼工具、記憶寫了什麼。

主程式太重不能 import（一載入就拉起 pyaudio、pygame、Firestore），所以照其他測試的做法用 AST 把需要的
函式和常數抽出來，放進一個準備好假零件的命名空間。主程式改了這一串的行為，情境測試會先紅。

用法（見 tests/test_scenarios.py）：
    async with DryRun(live=True) as d:
        await d.dad("彈小星星")
        await d.settle()
        assert d.tools == [...]
"""
import ast
import asyncio
import collections
import datetime
import glob
import os
import random
import re
import time
import types as pytypes
import typing
import unicodedata
from zoneinfo import ZoneInfo

from google.genai import types

import core.hard_command as hc
import core.input_sources as ins
import core.stage_state as stage
from core.prompts import TextCleanEngine, neutralize_viewer_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_SRC = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
_TREE = ast.parse(MAIN_SRC)

# 從主程式原樣載入的函式（這一串的真實行為）
MAIN_FUNCS = (
    "chat_processor_worker", "process_chat_message", "add_to_streamer_mind_board", "is_piano_song_request",
    "background_tool_executor", "run_stage_commands", "_hard_cmd_seen_recently", "_song_ack", "_dispatch_in_background",
    "send_brain_slip", "_unpack_slip", "_owner_text_slip", "_slip_is_dupe", "_slip_forget",
    "_note_brain_origin", "_brain_requester", "_her_words_before", "_brain_replaying_old_request",
    "is_live_brain_active", "live_brain_down_for", "use_rest_brain",
    "rest_slip_worker", "_rest_answer_slip", "_rest_speak", "_run_subagent_task",
    "execute_actions", "normalize_silence_token", "_brain_text_for_memory", "_start_marker_tools",
    "_vision_report_recent", "_start_mirror", "_likely_needs_tools",
    "streamer_mind_loop_worker", "_format_board_batch", "_ping_short_circuit", "_is_bare_ping",
    "_split_fossil_batch",
)
# 從主程式原樣載入的常數
MAIN_CONSTS = (
    "AUDIENCE_STAGE_DECLINE", "UNASKED_STAGE_DECLINE", "_SUBAGENT_VISION_TASK_RE", "_SUBAGENT_MIRROR_TASK_RE",
    "_SUBAGENT_TOTAL_TIMEOUT", "_SONG_ACK_LINES", "_PIANO_ACK_LINES", "_HARD_CMD_DEDUPE_SEC",
    "_SLIP_DEDUPE_SEC", "_SLIP_LEDGER_MAX", "LIVE_FALLBACK_AFTER_SEC", "VISION_REPORT_QUIET_SEC",
    "_BARE_PING_NAMES", "_PING_COOLDOWN_SEC", "_PING_QUIET_SEC", "_DESKTOP_TOOL_HINTS",
)


def _main_nodes(names):
    names = set(names)
    found = [n for n in _TREE.body
             if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names)
             or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets))]
    got = {n.name if hasattr(n, "name") else n.targets[0].id for n in found}
    missing = names - got
    assert not missing, f"主程式找不到：{missing}"
    return found


class FakeBrain:
    """假的 REST 大腦（rest_chat）：照劇本回。劇本是 [(文字, [(工具名, 參數)])]，用完就一直回最後一個。
    每次呼叫記在 calls：(system, user, 有沒有給工具)。"""

    def __init__(self, *script):
        self.script = list(script) or [("好喔～", [])]
        self.calls = []

    async def __call__(self, system_text, user_text, **k):
        self.calls.append((system_text, user_text, bool(k.get("tools"))))
        text, calls = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        return pytypes.SimpleNamespace(text=text, calls=list(calls), model="fake")


class DryRun:
    def __init__(self, live: bool = True, brain: FakeBrain = None, subagent=("miss", ""), sentry=None,
                 owner_uids=("dad_uid",)):
        """live：Live 主腦在線（紙條留在佇列給它，測試看 slips）；False＝斷線很久（紙條由 REST 大腦接）。
        subagent：子智能體解讀的結果 (kind, text)。sentry：看板哨兵的決定（預設要回）。"""
        self.live = live
        self.brain = brain or FakeBrain()
        self.subagent = subagent
        self.sentry = sentry or {"should_speak": True, "target": "", "focus": "回應", "raw": "[SPEAK]"}
        self.owner_uids = set(owner_uids)
        self.tools, self.memory, self.logs, self.errors, self.acks = [], [], [], [], []
        self.subagent_tasks, self.saved_position, self.vision = [], [], []
        self._tasks, self._workers = set(), []
        self.ns = self._build()

    # ── 假零件 ────────────────────────────────────────────────────────
    def _build(self):
        d = self
        stage.AI_STATE = "IDLE"
        stage.IS_MP3_PLAYING = False

        def spawn(coro, label=None):
            t = asyncio.ensure_future(coro)
            d._tasks.add(t)
            t.add_done_callback(d._tasks.discard)
            return t

        def log_swallowed():
            import sys
            if sys.exc_info()[0] is not None:
                d.errors.append(repr(sys.exc_info()[1]))

        async def execute_tool_dispatch(fn_name, fn_args, caller_target="", caller_user=""):
            d.tools.append((fn_name, dict(fn_args or {}), caller_target, caller_user))
            return ""

        async def mixed_piano_run(*a, **k):
            d.tools.append(("mixed_piano_run", a, "", ""))

        async def nv_interpret_task(task_ins, target="dad", requester_name=""):
            d.subagent_tasks.append((task_ins, target, requester_name))
            return d.subagent

        async def sentry(memory_context, board_desc):
            return dict(d.sentry)

        async def anoop(*a, **k):
            return None

        async def fetch_hist(*a, **k):
            return []

        async def streamer_prompt(board_context, users, has_dad, target, focus):
            return f"（看板提示詞：{target}）", board_context

        async def build_system(owner, char_name):
            return "（主腦系統提示詞）"

        def memory(**k):
            d.memory.append(k)

        pe = pytypes.SimpleNamespace(
            is_piano_active=False, current_piano_song_title="", current_piano_midi_file="",
            GLOBAL_PIANO_REALTIME_STATE={}, MIDI_SHEETS_DIR=os.path.join(ROOT, "midi_sheets"),
            get_piano_realtime_prompt=lambda: "（鋼琴狀態）", is_piano_performing=lambda: False)
        ns = {
            # 標準函式庫、core（真的）
            "asyncio": asyncio, "time": time, "re": re, "os": os, "random": random, "glob": glob,
            "datetime": datetime.datetime, "ZoneInfo": ZoneInfo, "unicodedata": unicodedata, "types": types,
            "Optional": typing.Optional, "deque": collections.deque, "collections": collections,
            "stage": stage, "TextCleanEngine": TextCleanEngine, "neutralize_viewer_text": neutralize_viewer_text,
            "parse_input_item": ins.parse_input_item, "classify": ins.classify, "is_operator": ins.is_operator,
            "sleep_wake_decision": ins.sleep_wake_decision, "VIEWER_SOURCES": ins.VIEWER_SOURCES,
            "WAKE_WORDS": ins.WAKE_WORDS,
            **{n: getattr(hc, n) for n in ("parse_hard_command", "build_slip_text", "structured_stage_command",
                                            "stage_request_unasked", "is_stage_control", "PLAY_TOOLS",
                                            "PIANO_CONTROL_TOOLS", "split_original_request", "display_requester",
                                            "asks_to_remember_model_position", "strip_blob_noise",
                                            "sanitize_search_query")},
            # 主程式的狀態
            "IS_SLEEPING": False, "CURRENT_SPEAKING_TARGET": "none", "current_dad_task": None,
            "CURRENT_PROCESSING_USER_INPUT": "", "last_interaction_time": 0.0, "LAST_TTS_END_TIME": 0.0,
            "LIVE_SESSION_ACTIVE": self.live, "_LIVE_DOWN_SINCE": time.time() - (0 if self.live else 3600),
            "_BRAIN_INPUT_ORIGIN": {"who": "dad", "ts": 0.0, "said": "", "human": False, "name": ""},
            "_HARD_CMD_RECENT": {}, "_SLIP_LAST_TS": {}, "_LIVE_SLIP_RETRY": collections.deque(),
            "_VISION_STATE": {"report_ts": 0.0, "mirror_ts": 0.0}, "_PING_LAST_TS": {}, "_SONG_ACK_IDX": 0,
            "_DESKTOP_DOWN_UNTIL": float("inf"),   # 桌機代答關掉
            "STREAMER_MIND_BOARD": [], "STREAMER_MIND_MODELS": ["m"], "REST_BRAIN_MODELS": ["m"],
            "REST_BRAIN_TOOLS": ["invoke_subagent"],
            "speech_queue": asyncio.Queue(), "LIVE_API_SYSTEM_PROMPT_QUEUE": asyncio.Queue(),
            # 假零件
            "log_print": lambda m, *a, **k: d.logs.append(str(m)), "log_swallowed": log_swallowed, "spawn": spawn,
            "pe": pe, "execute_tool_dispatch": execute_tool_dispatch, "_mixed_piano_run": mixed_piano_run,
            "_song_ack_missing_original": anoop, "nv_interpret_task": nv_interpret_task, "rest_chat": self.brain,
            "build_brain_system_prompt": build_system, "get_unified_memory_context": lambda **k: "",
            "judge_subconscious_intent_via_live_api": sentry, "get_recent_100_memory_context": lambda: "",
            "_streamer_mind_prompt": streamer_prompt, "append_to_unified_memory": memory,
            "fetch_from_long_term_memory": fetch_hist, "save_to_long_term_memory": anoop,
            "save_viewer_profile": anoop, "record_bot_message": lambda *a: None, "update_subtitle": lambda *a: None,
            "check_immediate_shutdown": lambda t: False, "execute_punish_action": anoop,
            "execute_reward_action": anoop, "set_sleep_mode": anoop, "operator_input_enabled": lambda: True,
            "is_owner_account": lambda uid: uid in d.owner_uids, "touch_interaction": lambda: None,
            "tk_listener": pytypes.SimpleNamespace(current_tiktok_status_str=""),
            "web_dash": pytypes.SimpleNamespace(broadcast_event=lambda *a, **k: None),
            "live_timer_hub": pytypes.SimpleNamespace(detect_timer_intent=lambda t: None),
            "_desktop_dad_reply": anoop, "_save_model_position": lambda: d.saved_position.append(1),
            "set_timer": anoop, "interrupt_current_speech": anoop, "execute_speech_visual_actions": anoop,
            "is_singing_active": lambda: False, "save_local_audio_clip": lambda *a: "",
            "live_vision_tool_task": lambda: d._record_vision("vision"),
            "live_mirror_tool_task": lambda: d._record_vision("mirror"),
            "live_search_tool_task": lambda q: d._record_vision("search"),
            "_owner_name": lambda: "老爸", "_SUBAGENT_GEMINI_TOOL_TIMEOUT": 5.0,
        }
        for node in _main_nodes(MAIN_CONSTS + MAIN_FUNCS):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "vts_7L_test.py", "exec"), ns)
        return ns

    async def _record_vision(self, kind):
        self.vision.append(kind)

    # ── 開關 ────────────────────────────────────────────────────────
    async def __aenter__(self):
        self.input_queue = asyncio.Queue()
        for coro in (self.ns["chat_processor_worker"](None, self.input_queue),
                     self.ns["streamer_mind_loop_worker"](None, self.input_queue),
                     self.ns["rest_slip_worker"](None, self.input_queue)):
            self._workers.append(asyncio.ensure_future(coro))
        return self

    async def __aexit__(self, *exc):
        for t in self._workers + list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._workers, *self._tasks, return_exceptions=True)
        stage.AI_STATE = "IDLE"

    # ── 輸入 ────────────────────────────────────────────────────────
    async def dad(self, text, source="text_file"):
        """老爸打字（text_file／web_console）。"""
        await self.input_queue.put({"text": text, "timestamp": time.time(), "source": source})

    async def viewer(self, user, text, uid="", source="tiktok"):
        """直播觀眾留言（監聽器的格式：text 給日誌看，viewer／content 給分派器用）。"""
        await self.input_queue.put({"text": f"【TikTok 直播觀眾 {user} 留言】：{text}", "timestamp": time.time(),
                                    "source": source, "platform_uid": uid, "viewer": user, "content": text})

    def slip(self, text, origin="", said="", name=""):
        """直接遞一張紙條（系統通知、謝幕之類）。"""
        self.ns["send_brain_slip"](text, origin=origin, said=said, name=name)

    async def settle(self, seconds: float = 2.0):
        """跑一段時間讓背景的分派、看板、紙條、子智能體都做完。"""
        t_end = time.time() + seconds
        while time.time() < t_end:
            await asyncio.sleep(0.05)

    # ── 觀察 ────────────────────────────────────────────────────────
    @property
    def slips(self):
        """還在佇列裡、要給 Live 主腦的紙條：[(文字, origin, said, name)]（讀了不拿走）。"""
        q = self.ns["LIVE_API_SYSTEM_PROMPT_QUEUE"]
        return [self.ns["_unpack_slip"](x) for x in list(q._queue)]

    @property
    def problems(self):
        """被吞掉的異常和寫進日誌的錯誤：情境跑完應該是空的。"""
        bad = re.compile(r"異常|Traceback|Error")
        return self.errors + [l for l in self.logs if bad.search(l)]

    @property
    def speech(self):
        """排進說話佇列的話（讀了不拿走）。"""
        return list(self.ns["speech_queue"]._queue)
