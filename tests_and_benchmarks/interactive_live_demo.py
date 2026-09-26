import asyncio
import os
import re
import sys
import wave
import io
from dotenv import load_dotenv
from google import genai
from google.genai import types
import pygame

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

# 初始化音訊播放器
pygame.mixer.init(frequency=24000, size=-16, channels=1)

raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
keys = [k.strip() for k in re.split(r'[\s,;]+', raw_keys) if k.strip()]

if not keys:
    print("❌ 錯誤：未在 .env 中找到有效的 GEMINI_API_KEYS！")
    sys.exit(1)

def play_pcm_audio(pcm_bytes: bytes):
    """透過 pygame 即時播放 24kHz 16-bit Mono 音訊"""
    if not pcm_bytes:
        return
    try:
        # 建立內存 WAV
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm_bytes)
        wav_io.seek(0)
        
        sound = pygame.mixer.Sound(wav_io)
        sound.play()
        # 等待播放完畢
        while pygame.mixer.get_busy():
            pygame.time.delay(50)
    except Exception as e:
        print(f"\n⚠️ 播放音訊異常: {e}")

async def run_live_chat_session():
    print("=" * 60)
    print("🌟 7L AI-VTuber — Gemini 3.1 Flash Live 互動體驗系統")
    print("=" * 60)
    print("💡 模式：即時輸入 ➔ Gemini Live 原生語音生成 ➔ 喇叭即時發聲")
    print("💡 提示：輸入 'exit' 或 'quit' 退出對話\n")

    client = genai.Client(api_key=keys[0])
    model_name = "gemini-3.1-flash-live-preview"

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"  # 靈動活潑女聲 (可選 Aoede, Kore, Fenrir, Puck)
                )
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part.from_text(
                text="妳是 7L，老爸最疼愛、活潑靈動可愛的 AI 女兒。說話熱情、黏人、充滿撒嬌與活力，回答請簡明流暢（2~3句話）。"
            )]
        ),
        output_audio_transcription=types.AudioTranscriptionConfig()
    )

    try:
        print(f"🔄 正在連線至 Gemini Live 伺服器 ({model_name})...")
        async with client.aio.live.connect(model=model_name, config=config) as session:
            print("✅ 【Live 連線成功】可以開始跟 7L 說話了！\n")

            while True:
                try:
                    user_text = await asyncio.to_thread(input, "老爸 👉 ")
                except (EOFError, KeyboardInterrupt):
                    break

                user_text = user_text.strip()
                if not user_text:
                    continue
                if user_text.lower() in ["exit", "quit", "q"]:
                    print("👋 結束 Live 對話！")
                    break

                # 發送即時文字指令
                await session.send_realtime_input(text=user_text)

                audio_buffer = bytearray()
                print("7L 👧 🗣️ ", end="", flush=True)

                # 接收即時串流回傳
                async for response in session.receive():
                    server_content = response.server_content
                    if not server_content:
                        continue

                    # 1. 即時輸出文字轉錄
                    if server_content.output_transcription and server_content.output_transcription.text:
                        print(server_content.output_transcription.text, end="", flush=True)

                    # 2. 收集音訊數據
                    if server_content.model_turn and server_content.model_turn.parts:
                        for part in server_content.model_turn.parts:
                            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                                audio_buffer.extend(part.inline_data.data)

                    # 3. 檢查回答結束
                    if server_content.turn_complete:
                        print("\n")
                        break

                # 即時播放 7L 原聲
                if audio_buffer:
                    await asyncio.to_thread(play_pcm_audio, bytes(audio_buffer))

    except Exception as e:
        print(f"\n❌ Live API 連線異常: {e}")

if __name__ == "__main__":
    asyncio.run(run_live_chat_session())
