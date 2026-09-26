# -*- coding: utf-8 -*-
"""🔁 7L Agent Loop（常駐 Live session 迴路）
階段 1：TikTok 閒聊走常駐 session（已上線）
階段 2：Live function calling → execute_tool_dispatch（點歌/鋼琴/搜尋）
階段 3：轉世前摘要壓縮，前情提要帶入新 session
階段 4：老爸開口即打斷當前語音（barge-in）
開關：環境變數 AGENT_LOOP=1，或改 IS_AGENT_LOOP_ENABLED。失敗一律回退舊鏈。
"""
import asyncio
import os
import re
import sys
import time

IS_AGENT_LOOP_ENABLED = os.getenv("AGENT_LOOP", "0") == "1"

LIVE_MODEL = "gemini-3.1-flash-live-preview"
SUMMARY_MODEL = "gemini-3.5-flash-lite"
MAX_TURNS_PER_SESSION = 30
MAX_TRANSCRIPT_CHARS = 12000
RECEIVE_TIMEOUT = 30.0

AGENT_SYSTEM_PROMPT = """妳是 7L，老爸的 AI 女兒，正在 TikTok 直播間跟觀眾閒聊。
- 用自然隨性口吻回 1~2 句短話（20~40 字），句尾帶標點，可穿插 [EXPRESSION: 微笑/臉紅/星星/WINK/震驚]。
- 觀眾明確點歌（唱歌/翻唱）→ 調用 auto_sing_song；想聽鋼琴 → 調用 pe.play_virtual_piano；需要即時資訊 → 調用 search_google。
- 加好友、借帳號等事務：一律回「這個要問我老爸做主喔！」，絕不答應或開條件。
- 無聊刷屏只回 [PASS]。
- 嚴禁輸出 thought/結構化草稿，直接說台詞。嚴禁 Emoji。"""


def is_enabled() -> bool:
    return bool(IS_AGENT_LOOP_ENABLED)


def get_core():
    """動態拿主核心（仿 auto_cover_pipeline，避循環 import）"""
    return sys.modules.get("vts_7L_test") or sys.modules.get("__main__")


def _build_live_tools(core):
    """沿用主腦工具表（觀眾安全版：禁麥克風/清空記憶），轉成 Live function declarations。"""
    try:
        from google.genai import types as _types
    except Exception:
        return None
    try:
        builder = getattr(core, "build_genai_declarations", None)
        if callable(builder):
            return builder(is_proactive=True)
    except Exception:
        pass
    return None


class AgentSession:
    """一條常駐 Live session：多輪不斷線、工具直調、轉世帶摘要。"""

    def __init__(self):
        self._session = None
        self._connect = None
        self.turns = 0
        self.transcript: list = []          # [(role, text)] 近期原文，轉世時壓縮
        self.context_summary = ""           # 上一世摘要，下一世首輪帶入

    async def _ensure(self):
        if self._session is not None:
            return True
        core = get_core()
        try:
            from google.genai import types as _types
            import google.genai as _genai
        except Exception:
            return False
        try:
            keys_fn = getattr(core, "get_dynamic_live_key_candidates", None)
            base_keys = getattr(core, "KEYS_AUDIENCE_LIVE", None) or getattr(core, "GEMINI_KEYS", [])
            candidates = keys_fn(base_keys) if callable(keys_fn) else list(base_keys)
        except Exception:
            return False
        for g_key in (candidates[:4] if candidates else []):
            try:
                client = _genai.Client(api_key=g_key)
                tools = _build_live_tools(core)
                kwargs = dict(
                    response_modalities=[_types.Modality.AUDIO],
                    output_audio_transcription=_types.AudioTranscriptionConfig(),
                    system_instruction=_types.Content(
                        parts=[_types.Part(text=AGENT_SYSTEM_PROMPT)]),
                )
                if tools:
                    kwargs["tools"] = tools
                cfg = _types.LiveConnectConfig(**kwargs)
                mgr = client.aio.live.connect(model=LIVE_MODEL, config=cfg)
                self._session = await mgr.__aenter__()
                self._connect = mgr
                self.turns = 0
                try:
                    core.log_print("🔁 [AgentLoop] Live session 已連線（常駐迴路啟動）")
                except Exception:
                    pass
                return True
            except Exception:
                continue
        return False

    async def _summarize_and_reset(self):
        """階段 3：把本世對話壓成 3 行摘要，寫入統一記憶，下一世帶入。"""
        core = get_core()
        summary = ""
        if self.transcript:
            try:
                from google.genai import types as _types
                import google.genai as _genai
                keys_fn = getattr(core, "get_dynamic_live_key_candidates", None)
                base_keys = getattr(core, "KEYS_AUDIENCE_LIVE", None) or getattr(core, "GEMINI_KEYS", [])
                candidates = keys_fn(base_keys) if callable(keys_fn) else list(base_keys)
                if candidates:
                    cli = _genai.Client(api_key=candidates[0])
                    convo = "\n".join(
                        f"{'觀眾' if r == 'user' else '7L'}：{t[:120]}"
                        for r, t in self.transcript[-20:])
                    cfg = _types.GenerateContentConfig(
                        temperature=0.3, max_output_tokens=200,
                        thinking_config=_types.ThinkingConfig(thinking_budget=0))
                    resp = await asyncio.wait_for(
                        cli.aio.models.generate_content(
                            model=SUMMARY_MODEL,
                            contents=(f"把以下直播閒聊壓成 3 行以內的重點（誰說了什麼、答應了什麼、未了結什麼），"
                                      f"嚴禁超過 150 字：\n{convo}"),
                            config=cfg),
                        timeout=12.0)
                    summary = (getattr(resp, "text", "") or "").strip()
            except Exception:
                summary = ""
        if summary:
            self.context_summary = summary
            try:
                core.append_to_unified_memory(
                    speaker="7L", target="直播間", content=f"【前世摘要】{summary}",
                    role="assistant", source="agent_loop")
                core.log_print(f"🔁 [AgentLoop] 轉世摘要完成：{summary[:60]}")
            except Exception:
                pass
        self.transcript = []
        self.turns = 0
        try:
            if self._connect:
                await self._connect.__aexit__(None, None, None)
        except Exception:
            pass
        self._session = None
        self._connect = None

    async def rotate(self):
        try:
            await self._summarize_and_reset()
        except Exception:
            self._session = None
            self._connect = None
        core = get_core()
        try:
            core.log_print(f"🔁 [AgentLoop] session 轉世（已用 {self.turns} 輪）")
        except Exception:
            pass

    async def _dispatch_tool_calls(self, core, function_calls):
        """階段 2：Live 工具調用 → 主腦 execute_tool_dispatch → 回 FunctionResponse。"""
        try:
            from google.genai import types as _types
        except Exception:
            return []
        responses = []
        dispatcher = getattr(core, "execute_tool_dispatch", None)
        for fc in function_calls or []:
            name = getattr(fc, "name", "") or ""
            args = getattr(fc, "args", {}) or {}
            fid = getattr(fc, "id", "") or name
            try:
                core.log_print(f"🔁 [AgentLoop 調用工具] {name}({args})")
            except Exception:
                pass
            try:
                if callable(dispatcher):
                    res = await dispatcher(name, dict(args),
                                           caller_target="audience",
                                           caller_user="直播觀眾")
                    # 搜尋類回傳原文，唱歌/鋼琴回傳狀態字串：都餵回 session 讓它組織口語
                    if name == "search_google" and res:
                        try:
                            res = await core.summarize_search_to_speech(
                                args.get("query", ""), res, user_role_name="大家")
                        except Exception:
                            pass
                else:
                    res = "工具執行器未就緒"
            except Exception as e:
                res = f"執行異常：{e}"
            try:
                responses.append(_types.FunctionResponse(
                    id=fid, name=name, response={"result": str(res)[:1500]}))
            except Exception:
                pass
        return responses

    async def chat(self, text: str) -> str:
        """送一句、收一輪（含工具多回合），回最終口語。空字串=失敗/靜默。"""
        if not text or not text.strip():
            return ""
        core = get_core()
        if self.turns >= MAX_TURNS_PER_SESSION:
            await self.rotate()
        if not await self._ensure():
            return ""
        try:
            from google.genai import types as _types
        except Exception:
            return ""
        payload = text.strip()
        if self.context_summary:
            payload = f"【前情提要】{self.context_summary}\n{text.strip()}"
            self.context_summary = ""
        try:
            async with asyncio.timeout(RECEIVE_TIMEOUT):
                await self._session.send_realtime_input(text=payload)
                out = ""
                while True:
                    turn_done = False
                    async for resp in self._session.receive():
                        if getattr(resp, "tool_call", None):
                            fcs = getattr(resp.tool_call, "function_calls", []) or []
                            fresps = await self._dispatch_tool_calls(core, fcs)
                            if fresps:
                                try:
                                    await self._session.send_tool_response(
                                        function_responses=fresps)
                                except Exception:
                                    pass
                            break  # 回外層繼續收工具執行後的回覆
                        c = getattr(resp, "server_content", None)
                        if c:
                            ot = getattr(c, "output_transcription", None)
                            if ot and getattr(ot, "text", ""):
                                out += ot.text
                            if getattr(c, "turn_complete", False) or getattr(c, "generation_complete", False):
                                turn_done = True
                                break
                    if turn_done:
                        break
            out = out.strip()
            self.turns += 1
            self.transcript.append(("user", text.strip()[:200]))
            if out:
                self.transcript.append(("model", out[:200]))
            if len(self.transcript) > 40:
                self.transcript = self.transcript[-40:]
            total_chars = sum(len(t) for _, t in self.transcript)
            if total_chars > MAX_TRANSCRIPT_CHARS:
                await self.rotate()
            return out
        except Exception:
            await self.rotate()
            return ""


_SESSION: AgentSession | None = None


def get_session() -> AgentSession:
    global _SESSION
    if _SESSION is None:
        _SESSION = AgentSession()
    return _SESSION


def interrupt(reason: str = "dad barge-in"):
    """階段 4：老爸開口 → 秒停當前語音，把麥讓出來（隊列保留，爸爸回覆照常排入）。"""
    core = get_core()
    try:
        task = getattr(core, "CURRENT_PLAYING_VOICE_TASK", None)
        if task and not task.done():
            task.cancel()
            try:
                core.log_print(f"🔁 [AgentLoop 打斷] 已秒停當前語音（{reason}）")
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


async def handle_tiktok_message(vts, input_queue, id_display: str,
                                unique_id: str, content: str, source: str = "tiktok") -> bool:
    """TikTok 閒聊走常駐 session；回 True=已處理，False=請 dispatcher 走舊看板。"""
    core = get_core()
    log = getattr(core, "log_print", print)
    try:
        try:
            low = (content or "").lower()
            to_7l = any(tag in low for tag in ["7l", "@7l", "小7", "7寶", "草莓"])
            core.append_to_unified_memory(
                speaker=f"TikTok 觀眾「{id_display}」",
                target="7L" if to_7l else "老爸/直播間",
                content=content, role="user", source=source)
        except Exception:
            pass

        reply = await get_session().chat(f"【{id_display}】：{content}")
        if not reply:
            return False
        if "[PASS]" in reply.upper() or "[SILENCE]" in reply.upper():
            try:
                core.append_to_unified_memory(
                    speaker="7L", target=f"觀眾「{id_display}」",
                    content="[PASS 靜默略過]", role="assistant", source="agent_loop")
            except Exception:
                pass
            return True

        try:
            from core.prompts import TextCleanEngine
            clean_reply = TextCleanEngine.remove_system_hints(reply)
        except Exception:
            clean_reply = reply
        clean_reply = re.sub(r'^(?:回應|回覆|說道|回答)[：:\s]+', '', clean_reply, flags=re.IGNORECASE).strip()

        exec_actions = getattr(core, "execute_actions", None)
        spoken = await exec_actions(vts, clean_reply, input_queue,
                                    user_input_ctx=content,
                                    caller_target="audience",
                                    caller_user=id_display) if callable(exec_actions) else clean_reply
        clean_spoken = (spoken or "").strip(" *'\"-\n\r")
        if clean_spoken and not clean_spoken[-1] in "。！？！.!?~～":
            clean_spoken = clean_spoken.rstrip("，,、；;…") + "！"
        if not clean_spoken:
            return True

        try:
            await asyncio.to_thread(core.update_subtitle, clean_spoken)
        except Exception:
            pass
        try:
            core.record_bot_message(clean_spoken)
        except Exception:
            pass
        log(f"💬 7L (AgentLoop 回應 {id_display}): {clean_spoken} (🔁 session #{get_session().turns})")
        try:
            await core.speech_queue.put({
                "text": clean_spoken, "target": "audience",
                "raw_text": clean_reply, "model": "agent-loop-live"})
        except Exception:
            pass
        try:
            core.append_to_unified_memory(
                speaker="7L", target=f"觀眾「{id_display}」",
                content=clean_spoken, role="assistant",
                source="tts", model="agent-loop-live")
        except Exception:
            pass
        try:
            fresh = await core.fetch_from_long_term_memory("tiktok_live_stream")
            fresh.append({"role": "user", "content": f"【TikTok 觀眾 {id_display}】：{content}"})
            fresh.append({"role": "assistant", "content": clean_spoken})
            asyncio.create_task(core.save_to_long_term_memory("tiktok_live_stream", fresh))
        except Exception:
            pass
        return True
    except Exception as e:
        try:
            log(f"⚠️ [AgentLoop 處理異常，回退看板]: {e}")
        except Exception:
            pass
        return False
