import re

def patch_vts():
    file_path = r"C:\Users\qiwai\vts_7L_test.py"
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()

    # 1. Modify process_chat_message to trigger Shadow Brain
    shadow_brain_code = """
        # --- [平行大腦架構] 影子大腦平行執行 ---
        shadow_prompt = f"【隱藏大腦任務】老爸剛剛說：{user_input}\\n請評估是否需要查資料、彈鋼琴、切換表情或使用任何工具。若需要，直接呼叫對應Tool。不需要則輸出 [PASS]。絕對不要輸出任何對話台詞！"
        shadow_msgs = [{"role": "system", "content": system_prompt}] + effective_history + [{"role": "user", "content": shadow_prompt}]
        async def run_shadow_brain():
            try:
                await fetch_ai_response(shadow_msgs, image_base64=current_screen_snapshot, is_proactive=True, request_start_time=req_start)
            except Exception as e:
                log_print(f"⚠️ [影子大腦錯誤] {e}")
        asyncio.create_task(run_shadow_brain())
        # ----------------------------------------
        
        # 嘴巴神經（極速串流生成）
        raw_spoken_text = await fetch_ai_response(
"""
    
    # Replace the fetch_ai_response call in process_chat_message
    pattern_process = r'(raw_spoken_text\s*=\s*await\s+fetch_ai_response\(\s*messages,\s*image_base64=current_screen_snapshot,\s*audio_base64=effective_audio_b64,\s*request_start_time=req_start\s*\))'
    if not re.search(pattern_process, code):
        print("Could not find process_chat_message AI fetch call.")
    else:
        code = re.sub(pattern_process, shadow_brain_code.strip() + "\n            messages, \n            image_base64=current_screen_snapshot, \n            audio_base64=effective_audio_b64, \n            request_start_time=req_start, \n            is_mouth_stream=True\n        )", code)

    # 2. Modify fetch_ai_response to support is_mouth_stream=True
    pattern_fetch_def = r'async def fetch_ai_response\(messages, image_base64=None, audio_base64=None, is_proactive=False, request_start_time:\s*Optional\[float\]\s*=\s*None\):'
    replacement_fetch_def = r'async def fetch_ai_response(messages, image_base64=None, audio_base64=None, is_proactive=False, request_start_time: Optional[float] = None, is_mouth_stream=False):'
    code = re.sub(pattern_fetch_def, replacement_fetch_def, code)
    
    # Modify the config generation in fetch_ai_response to disable tools for Mouth
    pattern_tools = r'(active_tools\s*=\s*GENAI_PROACTIVE_TOOLS\s*if\s*is_proactive\s*else\s*GENAI_TOOLS)'
    replacement_tools = r'active_tools = [] if is_mouth_stream else (GENAI_PROACTIVE_TOOLS if is_proactive else GENAI_TOOLS)'
    code = re.sub(pattern_tools, replacement_tools, code)
    
    # 3. Add streaming block in fetch_ai_response
    pattern_generate = r'(response\s*=\s*await\s+asyncio\.wait_for\(\s*temp_google_client\.aio\.models\.generate_content\(\s*model=g_model,\s*contents=chat_contents,\s*config=gen_config\s*\),\s*timeout=120\.0\s*\))'
    streaming_replacement = """
            if is_mouth_stream:
                # 極速串流模式（不帶工具，純講話）
                stream_resp = await asyncio.wait_for(
                    temp_google_client.aio.models.generate_content_stream(
                        model=g_model,
                        contents=chat_contents,
                        config=gen_config
                    ),
                    timeout=10.0
                )
                full_text = ""
                async for chunk in stream_resp:
                    if chunk.text:
                        full_text += chunk.text
                        # TODO: 這裡原本應該實作即時 chunking 丟給 TTS，但因為 execute_actions 依賴全字串，
                        # 先把文字快速收齊回傳，仍能享受無工具負擔的快速生成！
                response = type('Obj', (object,), {'text': full_text, 'function_calls': None})()
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
    code = re.sub(pattern_generate, streaming_replacement.strip(), code)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
        
    print("Patch applied successfully.")

if __name__ == "__main__":
    patch_vts()
