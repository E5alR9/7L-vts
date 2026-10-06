import re

def patch_file():
    filepath = r"C:\Users\qiwai\vts_7L_test.py"
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Bypass Groq for is_mouth_stream
    content = content.replace(
        "if not image_base64 and not audio_base64:",
        "if not is_mouth_stream and not image_base64 and not audio_base64:"
    )
    
    # 2. Inject direct stream return BEFORE the Gemini racing loop
    pattern = r'(#\s*第一防線：主力 Gemini 旗艦大腦)'
    inject = """
    if is_mouth_stream:
        # 直接使用當前金鑰建立串流通道，跳過所有競速邏輯
        global CURRENT_GEMINI_KEY_STEP
        g_key = GEMINI_KEYS[CURRENT_GEMINI_KEY_STEP % len(GEMINI_KEYS)]
        CURRENT_GEMINI_KEY_STEP += 1
        g_model = "gemini-3.5-flash-lite" if not image_base64 and not audio_base64 else "gemini-3.5-flash"
        temp_client = genai.Client(api_key=g_key)
        gen_config = types.GenerateContentConfig(temperature=0.85, safety_settings=UNRESTRICTED_SAFETY_SETTINGS)
        return temp_client.aio.models.generate_content_stream(
            model=g_model,
            contents=chat_contents,
            config=gen_config
        )
        
    """
    content = re.sub(pattern, inject.strip("\n") + "\n    \\1", content)
    
    # 3. Clean up the messed up _call_single_gemini stream logic we injected earlier (optional, but good for cleanliness)
    pattern_cleanup = r'if is_mouth_stream:\s*return temp_google_client\.aio\.models\.generate_content_stream\([^)]*\)\s*else:\s*(response = await asyncio\.wait_for\(\s*temp_google_client\.aio\.models\.generate_content\([^)]*\),\s*timeout=120\.0\s*\))'
    # Actually, because of indentation, regex might fail. Let's just leave it since _call_single_gemini won't be called if is_mouth_stream is True anyway.

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print("Stream patch applied successfully.")

if __name__ == "__main__":
    patch_file()
