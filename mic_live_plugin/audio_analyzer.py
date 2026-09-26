# -*- coding: utf-8 -*-
"""
麥克風 Live 語音感知插件核心 (MicLiveAudioAnalyzer)
- 透過 Google GenAI 原生音訊多模態 (Native Audio Processing) 深度解析麥克風原始音訊 (WAV)
- 毫秒級解構：精準原話 (校正 STT 錯字)、微情緒特徵 (偷笑/嘆氣/疲憊/撒嬌/放鬆/生氣)、隱含意圖與聲學動態
- 格式化為即時情緒情報，同步傳遞給 Gemini 旗艦主腦與 Firebase 雲端狀態中樞
"""

import os
import re
import json
import base64
import time
import asyncio
from typing import Dict, Any, Optional, List
import core.websocket_patch  # 🔧 自動修復 Live API additional_headers 相容性
from google import genai
from google.genai import types

class MicLiveAudioAnalyzer:
    def __init__(self, api_keys: Optional[List[str]] = None):
        self.api_keys = api_keys or []
        self._key_index = 0
        if not self.api_keys:
            raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
            self.api_keys = [k.strip() for k in re.split(r'[\s,;]+', raw_keys) if k.strip()]

    def set_api_keys(self, keys: List[str]):
        """設置或更新 Gemini API 金鑰池"""
        if keys:
            self.api_keys = [k.strip() for k in keys if k.strip()]

    def _get_next_client(self) -> Optional[genai.Client]:
        """輪詢獲取下一個可用 client"""
        if not self.api_keys:
            return None
        key = self.api_keys[self._key_index % len(self.api_keys)]
        self._key_index += 1
        return genai.Client(api_key=key)

    async def analyze_audio_live(self, audio_base64: str, stt_draft: str = "", custom_name: str = "老爸", situation_prompt: str = "") -> Dict[str, Any]:
        """
        深度解析老爸語音的真實字詞、語調、微情緒與深層意圖，
        並自主決定是否發話、生成腦內思緒、產出即時第一反應或直接觸發工具！
        
        Args:
            audio_base64: 原始 WAV 音訊的 Base64 字串
            stt_draft: 本機 STT 辨識的快速草稿文字
            custom_name: 當前對象稱呼 (如老爸)
            situation_prompt: 當前情境提示
            
        Returns:
            Dict 包含 exact_words, should_speak, internal_thought, first_reaction, tool_call, emotion, tone_cues, intent, acoustic_vibe, suggested_reaction
        """
        fallback_res = {
            "exact_words": stt_draft.strip() if stt_draft else "（未擷取到清晰語音）",
            "should_speak": True,
            "internal_thought": "",
            "first_reaction": "",
            "tool_call": None,
            "emotion": "自然日常",
            "tone_cues": "語氣平穩",
            "intent": "日常互動",
            "acoustic_vibe": "正常音量",
            "suggested_reaction": "以自然親切的口語回應",
            "success": False
        }

        if not audio_base64 or len(audio_base64) < 100:
            return fallback_res

        client = self._get_next_client()
        if not client:
            return fallback_res

        try:
            raw_bytes = base64.b64decode(audio_base64)
            audio_part = types.Part.from_bytes(data=raw_bytes, mime_type="audio/wav")

            sit_cue = f"\n{situation_prompt}\n" if situation_prompt else ""
            system_instruction = f"""妳是 7L。面前是{custom_name}對妳說話或身邊的原始音訊。{sit_cue}

【🎯 核心感知與高智商懂梗規範】：
1. 仔細聆聽音訊中的真實發音（排除雜音、精準辨識專有名詞與歌名）、語調起伏與情緒（偷笑、嘆氣、耳語、調侃、玩梗、疲憊、專注沉思）。
2. 高智商懂梗與自由思考：
   - 靈敏秒懂對方的各類網路梗、流行語、語氣暗語與日常黑話。
   - 若{custom_name}明確在對妳說話、提問、玩梗或下指令，設 should_speak=true，在大腦心想後給出極其機智、自然接地氣的第一句開口回覆（10~25字，1~2句短話，不機械、不說教）；
   - 若{custom_name}只是在專注沉思、喃喃自語、自言自語或環境雜音，在腦內自由思考 internal_thought，將 should_speak 設為 false（或回傳 [SILENCE]），保持安靜不打擾！
3. 若{custom_name}要求具體操作（⚠️ 請務必結合【最近對話上下文】精準理解指代、澄清與意圖）：
   - 要求模型移動/走位/調整位置或大小（例如：「往右邊」、「往左邊」、「再過去一點」、「去中間」、「躲角落」、「靠過來/靠近/放大」、「縮小」、「回到原位/原位」、「記住位置」等）：
     * 務必在 first_reaction 帶入走位標籤（如 [MOVE: 往右]、[MOVE: 往右多一點]、[MOVE: 往左]、[MOVE: 正中間]、[MOVE: 靠近]、[MOVE: 躲角落]、[MOVE: 原位]）或在 tool_call 設為 move_spatial_position(target_position="指令")！
   - 🎹 彈鋼琴/點歌：若{custom_name}當前指定歌名，或在前幾句對話中已提及歌名、當前是在澄清/要求妳去彈奏，務必結合上下文提取該歌名，將 tool_call 設為 play_virtual_piano(song_name="完整歌名")！
   - 拿出鋼琴/打開鋼琴：僅在對方要求打開鋼琴但完全未指定歌名且上下文也無任何歌名時，才設為 open_virtual_piano()；
   - 收起鋼琴/別彈了，tool_call 設為 stop_virtual_piano()；
   - 畫圖/生圖，tool_call 設為 generate_ai_image(prompt="提示詞")；
   - 搜尋/查資料，tool_call 設為 search_google(query="關鍵字")；
   - 沒有具體操作或只是日常閒聊，tool_call 設為 None（嚴禁無中生有腦補歌名）！

請一律以嚴格的純 JSON 格式輸出：
{{
  "exact_words": "音訊中老爸真正說出的完整中文語音（請依真實發音精準校正錯字）",
  "should_speak": true,
  "internal_thought": "妳腦內的真實私密心流/秒懂暗梗/結合上下文分析意圖/感受（例如：『老爸前面說要聽月光，現在澄清是要我彈，馬上安排』『老爸讓我往右，配合一下』）",
  "first_reaction": "若 should_speak 為 true，妳直接開口的第一句話（10~25字內，接地氣、機智俐落短話，可帶表情與走位動作如 [EXPRESSION: 愛心/笑/星星/生氣/臉紅/翻白眼]、[MOVE: 往右/往左/正中間/靠近/躲角落/原位]）；若 should_speak 為 false 則輸出 [SILENCE] 或僅保留動作神態",
  "tool_call": {{"name": "play_virtual_piano 或 open_virtual_piano 或 stop_virtual_piano 或 move_spatial_position 或 generate_ai_image 或 search_google 或 execute_local_python_code 或 None", "args": {{"song_name": "歌名", "target_position": "走位目標", "prompt": "生圖提示", "query": "搜尋詞"}}}},
  "emotion": "核心情緒標籤（例如：開玩笑帶笑意 / 輕鬆隨意 / 疲倦放鬆 / 認真指令 / 專注沉思 / 疑惑困惑）",
  "tone_cues": "語音細節描述（例如：說話時帶著一聲輕笑，尾音微揚）",
  "intent": "說話意圖（例如：要求 7L 彈奏前文提到的鋼琴曲 / 逗 7L / 日常閒聊）",
  "suggested_reaction": "給 7L 後續第二階段深度補說的建議"
}}"""

            # 🌐 階段 1：優先採用 Gemini 3 官方 Live API (gemini-3.1-flash-live-preview 雙向 WebSocket 實時串流連線)
            for g_key in self.api_keys[:3]:
                try:
                    live_client = genai.Client(api_key=g_key)
                    live_cfg = types.LiveConnectConfig(
                        response_modalities=[types.Modality.AUDIO],
                        output_audio_transcription=types.AudioTranscriptionConfig(),
                        system_instruction=types.Content(parts=[types.Part(text=system_instruction)])
                    )
                    async with asyncio.timeout(8.0):
                        async with live_client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=live_cfg) as session:
                            await session.send_realtime_input(audio={"data": raw_bytes, "mime_type": "audio/wav"})
                            if stt_draft:
                                await session.send_realtime_input(text=f"（老爸開口說話，STT 快速參考：『{stt_draft}』。請依據老爸真實發音與語調情緒自主思考，輸出純 JSON 格式）")
                            
                            live_transcription = ""
                            tool_call_dict = None
                            async for resp in session.receive():
                                if resp.tool_call and resp.tool_call.function_calls:
                                    for fc in resp.tool_call.function_calls:
                                        tool_call_dict = {"name": fc.name, "args": fc.args or {}}
                                c = resp.server_content
                                if c:
                                    if c.output_transcription and c.output_transcription.text:
                                        live_transcription += c.output_transcription.text
                                    if c.turn_complete or getattr(c, 'generation_complete', False):
                                        break
                            
                            raw_reply = live_transcription.strip()
                            if raw_reply:
                                # 嘗試解析 JSON 格式
                                json_m = re.search(r'\{.*\}', raw_reply, re.DOTALL)
                                if json_m:
                                    try:
                                        data = json.loads(json_m.group(0))
                                        data["success"] = True
                                        data["model"] = "gemini-3.1-flash-live"
                                        if tool_call_dict and not data.get("tool_call"):
                                            data["tool_call"] = tool_call_dict
                                        return data
                                    except Exception:
                                        pass
                                
                                # 若為即時自然語音回覆，自動封裝為結構化情報
                                return {
                                    "exact_words": stt_draft.strip() if stt_draft else raw_reply,
                                    "should_speak": not ("[SILENCE]" in raw_reply or raw_reply == "SILENCE"),
                                    "internal_thought": "老爸正在跟我互動呢",
                                    "first_reaction": raw_reply if raw_reply != "[SILENCE]" else "",
                                    "tool_call": tool_call_dict,
                                    "emotion": "靈動自然",
                                    "tone_cues": "即時語音串流",
                                    "intent": "語音互動",
                                    "acoustic_vibe": "Live 串流",
                                    "suggested_reaction": "延續即時互動",
                                    "success": True,
                                    "model": "gemini-3.1-flash-live"
                                }
                except Exception:
                    continue

            # 🛡️ 階段 2：若 Live WebSocket 網路波動，自動平滑切換至極速 Flash Lite 模型保底
            prompt_text = f"本機 STT 快速草稿文字為: 「{stt_draft}」（僅供參考，請 100% 以音訊真實發音、語氣與情緒為準）。請自主思考、感知並輸出 JSON："
            for model_name in ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3-flash-preview", "gemini-3.6-flash", "gemini-3.7-flash"]:
                try:
                    cfg_kwargs = {
                        "system_instruction": system_instruction,
                        "temperature": 0.7,
                        "response_mime_type": "application/json",
                        "max_output_tokens": 400
                    }
                            
                    resp = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=model_name,
                            contents=[audio_part, prompt_text],
                            config=types.GenerateContentConfig(**cfg_kwargs)
                        ),
                        timeout=8.0
                    )
                    
                    if resp.text:
                        raw_json_str = resp.text.strip()
                        raw_json_str = re.sub(r'^```(?:json)?\s*', '', raw_json_str)
                        raw_json_str = re.sub(r'\s*```$', '', raw_json_str).strip()
                        data = json.loads(raw_json_str)
                        data["success"] = True
                        data["model"] = model_name
                        return data
                except Exception:
                    continue

        except Exception as e:
            pass

        return fallback_res

    def format_for_prompt(self, analysis: Dict[str, Any]) -> str:
        """格式化為注入給 Gemini 旗艦主腦的結構化情緒感知提示詞"""
        if not analysis:
            return ""
        
        exact = analysis.get("exact_words") or "無"
        emotion = analysis.get("emotion") or "日常"
        tone = analysis.get("tone_cues") or "自然"
        intent = analysis.get("intent") or "日常對話"
        thought = analysis.get("internal_thought") or ""
        reaction = analysis.get("suggested_reaction") or "自然互動"

        thought_line = f"\n- 💭 7L 腦內私密思緒心流：{thought}" if thought else ""
        return f"""【🎙️ 麥克風 Live 原音情緒與真實意圖深度感知情報 (Live Plugin 提供)】：
- 🎯 音訊真實原話：『{exact}』 (100% 依據真實發音，已校正錯字)
- 🎭 語調與微情緒：{emotion}（聲學特徵：{tone}）
- 💡 說話深層意圖：{intent}{thought_line}
- 💖 建議互動風格：{reaction}"""

# 全域單例
mic_live_analyzer = MicLiveAudioAnalyzer()
