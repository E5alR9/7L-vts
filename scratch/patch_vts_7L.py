import re
import os

def patch_file():
    filepath = r"C:\Users\qiwai\vts_7L_test.py"
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update fetch_ai_response definition
    pattern1 = r'async def fetch_ai_response\(messages, image_base64=None, audio_base64=None, is_proactive=False, request_start_time:\s*Optional\[float\]\s*=\s*None\):'
    repl1 = r'async def fetch_ai_response(messages, image_base64=None, audio_base64=None, is_proactive=False, request_start_time: Optional[float] = None, is_mouth_stream=False):'
    content = re.sub(pattern1, repl1, content)
    
    # 2. Disable tools if is_mouth_stream
    pattern2 = r'(active_tools\s*=\s*GENAI_PROACTIVE_TOOLS\s*if\s*is_proactive\s*else\s*GENAI_TOOLS)'
    repl2 = r'active_tools = [] if is_mouth_stream else (GENAI_PROACTIVE_TOOLS if is_proactive else GENAI_TOOLS)'
    content = re.sub(pattern2, repl2, content)
    
    # 3. Add stream generation to fetch_ai_response
    pattern3 = r'(response\s*=\s*await\s+asyncio\.wait_for\(\s*temp_google_client\.aio\.models\.generate_content\(\s*model=g_model,\s*contents=chat_contents,\s*config=gen_config\s*\),\s*timeout=120\.0\s*\))'
    repl3 = """
            if is_mouth_stream:
                return temp_google_client.aio.models.generate_content_stream(
                    model=g_model,
                    contents=chat_contents,
                    config=gen_config
                )
            else:
                response = await asyncio.wait_for(
                    temp_google_client.aio.models.generate_content(
                        model=g_model,
                        contents=chat_contents,
                        config=gen_config
                    ),
                    timeout=120.0
                )
"""
    content = re.sub(pattern3, repl3.strip("\n"), content)
    
    # 4. Modify process_chat_message
    pattern4 = r'(raw_spoken_text\s*=\s*await\s+fetch_ai_response\(\s*messages,\s*image_base64=current_screen_snapshot,\s*audio_base64=effective_audio_b64,\s*request_start_time=req_start\s*\)\s*if my_session_id != CURRENT_CHAT_SESSION_ID:\s*return\s*log_print\(f"🤖 原始大腦輸出: \{raw_spoken_text\} \(\{current_model_tag\}\)"\)\s*bot_reply = re\.sub\(r\'\[SKIP\]\|\[SILENCE\]\', \'\', raw_spoken_text, flags=re\.IGNORECASE\)\.strip\(\)\s*spoken = await execute_actions\(vts, bot_reply, input_queue, user_input_ctx=user_input, caller_target="dad", caller_user=current_custom_name\)\s*clean_spoken = spoken\.strip\(" \*\\\'\\"-.,!\?。，！？\\n\\r"\) if spoken else ""\s*if clean_spoken and my_session_id == CURRENT_CHAT_SESSION_ID:\s*await asyncio\.to_thread\(update_subtitle, clean_spoken\)\s*record_bot_message\(clean_spoken\)\s*log_print\(f"💬 7L \(主腦回覆\): \{clean_spoken\} \(\{current_model_tag\}\)"\)\s*await speech_queue\.put\(\{"text": clean_spoken, "target": "dad", "raw_text": bot_reply,\s*"private": not str\(source\)\.startswith\("tiktok"\)\}\)\s*#  寫入全集中記憶中樞（確保主播看板與所有 API Key 即時掌握）\s*append_to_unified_memory\(speaker="7L", target=current_custom_name, content=clean_spoken, role="assistant", source="tts"\))'

    new_block = """
        # --- 影子平行大腦架構 ---
        shadow_prompt = f"【影子大腦任務】老爸剛剛說：{user_input}\\n請評估是否需要查資料、彈鋼琴、改編MIDI或切換表情等工具。若需要，直接呼叫對應Tool。不需要則輸出 [PASS]。絕對不要輸出任何對話台詞！"
        shadow_msgs = [{"role": "system", "content": system_prompt}] + effective_history + [{"role": "user", "content": shadow_prompt}]
        async def run_shadow_brain():
            try:
                await fetch_ai_response(shadow_msgs, image_base64=current_screen_snapshot, is_proactive=True, request_start_time=req_start)
            except Exception as e:
                pass
        asyncio.create_task(run_shadow_brain())
        
        # 嘴巴神經（極速串流，無Tool負擔）
        stream_iter = await fetch_ai_response(
            messages, 
            image_base64=current_screen_snapshot, 
            audio_base64=effective_audio_b64, 
            request_start_time=req_start,
            is_mouth_stream=True
        )
        
        if my_session_id != CURRENT_CHAT_SESSION_ID:
            return
            
        full_raw = ""
        full_clean = ""
        buffer = ""
        
        async def process_sentence(sentence):
            if not sentence.strip(): return
            bot_reply = re.sub(r'\\[SKIP\\]|\\[SILENCE\\]', '', sentence, flags=re.IGNORECASE).strip()
            if not bot_reply: return
            
            spoken = await execute_actions(vts, bot_reply, input_queue, user_input_ctx=user_input, caller_target="dad", caller_user=current_custom_name)
            clean_spoken = spoken.strip(" *'\\"-.,!?。，！？\\n\\r") if spoken else ""
            
            if clean_spoken and my_session_id == CURRENT_CHAT_SESSION_ID:
                await asyncio.to_thread(update_subtitle, clean_spoken)
                await speech_queue.put({"text": clean_spoken, "target": "dad", "raw_text": bot_reply,
                                        "private": not str(source).startswith("tiktok")})
                return clean_spoken
            return ""

        async for chunk in stream_iter:
            if chunk.text:
                buffer += chunk.text
                full_raw += chunk.text
                parts = re.split(r'([。，！？\\n]+)', buffer)
                if len(parts) > 1:
                    for i in range(0, len(parts)-1, 2):
                        phrase = parts[i] + parts[i+1]
                        c = await process_sentence(phrase)
                        if c: full_clean += c + " "
                    buffer = parts[-1]
                    
        if buffer.strip():
            c = await process_sentence(buffer)
            if c: full_clean += c + " "
            
        log_print(f"🤖 原始大腦輸出: {full_raw} ({current_model_tag})")
        
        if full_clean.strip() and my_session_id == CURRENT_CHAT_SESSION_ID:
            record_bot_message(full_clean.strip())
            log_print(f"💬 7L (主腦回覆): {full_clean.strip()} ({current_model_tag})")
            append_to_unified_memory(speaker="7L", target=current_custom_name, content=full_clean.strip(), role="assistant", source="tts")
            
        raw_spoken_text = full_raw
        clean_spoken = full_clean.strip()
"""
    
    # We use a more robust search for pattern4 since regex might fail on exact matches with whitespace.
    # Instead, we find the index of "raw_spoken_text = await fetch_ai_response(" and "append_to_unified_memory"
    
    start_idx = content.find("raw_spoken_text = await fetch_ai_response(")
    end_idx = content.find("append_to_unified_memory(speaker=\"7L\", target=current_custom_name, content=clean_spoken, role=\"assistant\", source=\"tts\")")
    if start_idx != -1 and end_idx != -1:
        end_idx += len("append_to_unified_memory(speaker=\"7L\", target=current_custom_name, content=clean_spoken, role=\"assistant\", source=\"tts\")")
        content = content[:start_idx] + new_block.strip("\n") + content[end_idx:]
    else:
        print("Failed to find process_chat_message replacement block.")
        return

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print("Patch applied successfully.")

if __name__ == "__main__":
    patch_file()
