"""
🎵 7L AI 全網動態唱歌引擎 (7L AI Dynamic Lyrics & Singing Engine)
支援：
1. Google / Tavily 全網不限定網站自動搜尋任何歌曲歌詞
2. Gemini 智慧旋律音高調校 (Prosody Tuning)
3. Xiaoyi 專屬歌聲即時合成與本地快取
4. 毫秒級點唱播放與 Live2D 舞台連動
"""

import os
import sys
import time
import asyncio
import random
import re
import json
import edge_tts
import pygame
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

sys.stdout.reconfigure(encoding='utf-8')

SONGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "songs_library")
os.makedirs(SONGS_DIR, exist_ok=True)

# 讀取 .env 中的 API 金鑰
raw_gemini = os.getenv("GEMINI_API_KEY", "") or os.getenv("GEMINI_KEYS", "")
GEMINI_KEYS = [k.strip() for k in re.split(r'[\s,;]+', raw_gemini) if k.strip()]
raw_tavily = os.getenv("TAVILY_KEYS", "") or os.getenv("TAVILY_API_KEY", "")
TAVILY_KEYS = [k.strip() for k in re.split(r'[\s,;]+', raw_tavily) if k.strip()]

try:
    from tavily import TavilyClient
    tavily_client = TavilyClient(api_key=TAVILY_KEYS[0]) if TAVILY_KEYS else None
except Exception:
    tavily_client = None

def search_lyrics_from_web(song_name: str) -> str:
    """使用 Google / Tavily 向全網搜尋真實歌詞（不限定任何網站）"""
    print(f"🌐 [7L 歌詞大腦] 正在全網自由搜尋《{song_name}》的歌詞...")
    query = f"{song_name} 完整歌詞 lyrics"
    
    # 1. 優先使用 Tavily 全網搜尋
    if tavily_client:
        try:
            res = tavily_client.search(query=query, search_depth="advanced")
            if isinstance(res, dict) and "results" in res:
                snippets = []
                for item in res["results"][:5]:
                    title = item.get("title", "")
                    content = item.get("content", "")
                    snippets.append(f"【來源: {title}】\n{content}")
                if snippets:
                    return "\n\n".join(snippets)
        except Exception as e:
            print(f"⚠️ [Tavily 歌詞搜尋異常]: {e}")

    # 2. 備用 DuckDuckGo 全網搜尋
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if results:
                snippets = [f"【{r.get('title', '')}】\n{r.get('body', '')}" for r in results]
                return "\n\n".join(snippets)
    except Exception as e:
        print(f"⚠️ [DDG 歌詞搜尋異常]: {e}")
        
    return ""

async def fetch_song_notes_with_ai(song_name: str) -> list:
    """使用 Gemini 從全網搜尋結果中提取精華歌詞並標註演唱音高旋律（溫柔自然女聲，絕不刺耳尖銳）"""
    web_lyrics_content = await asyncio.to_thread(search_lyrics_from_web, song_name)
    
    prompt = f"""請為歌曲《{song_name}》提取最經典動聽的主歌與副歌歌詞（約 6 到 8 句），並為每一句歌詞標註適合自然甜美少女歌唱的音高（pitch，範圍保持在 -5Hz 到 +10Hz 之間，絕不可過高尖銳）與語速（rate，+0% 到 +8%）。

【全網搜尋到的歌詞參考】：
{web_lyrics_content[:3000]}

請務必嚴格輸出為 JSON 陣列格式，不可輸出任何額外 Markdown 標籤或解釋，格式範例如下：
[
  {{"line": "第一句主歌歌詞", "pitch": "+0Hz", "rate": "+0%"}},
  {{"line": "第二句主歌歌詞", "pitch": "+4Hz", "rate": "+2%"}},
  {{"line": "副歌高潮歌詞", "pitch": "+8Hz", "rate": "+5%"}},
  {{"line": "結尾溫柔歌詞", "pitch": "+2Hz", "rate": "+0%"}}
]"""

    if not GEMINI_KEYS:
        return [
            {"line": f"為老爸獻上一首動聽的{song_name}", "pitch": "+0Hz", "rate": "+0%"},
            {"line": "音符在空中輕輕飄揚", "pitch": "+4Hz", "rate": "+2%"},
            {"line": "每一句旋律都充滿了希望", "pitch": "+8Hz", "rate": "+5%"},
            {"line": "希望大家都能感受到這份溫暖～", "pitch": "+2Hz", "rate": "+0%"}
        ]

    for g_key in GEMINI_KEYS[:3]:
        try:
            client = genai.Client(api_key=g_key)
            resp = await client.aio.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json"
                )
            )
            if resp.text:
                data = json.loads(resp.text.strip())
                if isinstance(data, list) and len(data) > 0:
                    print(f"🧠 [Gemini 旋律調校] 成功為《{song_name}》生成 {len(data)} 句自然溫柔演唱曲譜！")
                    return data
        except Exception as e:
            print(f"⚠️ [Gemini 歌詞提取重試]: {e}")
            continue

    return [
        {"line": f"帶來老爸最喜歡的《{song_name}》", "pitch": "+2Hz", "rate": "+0%"},
        {"line": "隨音樂節奏一起搖擺", "pitch": "+6Hz", "rate": "+4%"},
        {"line": "唱出最美的心情～", "pitch": "+8Hz", "rate": "+2%"}
    ]

async def generate_song_vocal_dynamic(song_name: str) -> str:
    """全網抓取歌詞 ➔ 旋律調校 ➔ Xiaoyi 自然音色合成 ➔ 產出溫柔甜美歌聲"""
    safe_name = re.sub(r'[^\w\u4e00-\u9fa5]', '_', song_name).strip('_')
    out_file = os.path.join(SONGS_DIR, f"7L_sing_{safe_name}.mp3")
    
    # 若已下載/生成過快取，直接秒回
    if os.path.exists(out_file) and os.path.getsize(out_file) > 1000:
        print(f"💾 [7L 唱歌曲庫] 命中已收錄專屬歌聲快取: 《{song_name}》")
        return out_file
        
    print(f"🎙️ [7L 全網動態唱歌] 開始全自動生成《{song_name}》溫柔自然歌聲...")
    lyrics_notes = await fetch_song_notes_with_ai(song_name)
    
    temp_chunks = []
    for idx, item in enumerate(lyrics_notes):
        line = item.get("line", "").strip()
        raw_pitch = item.get("pitch", "+0Hz")
        rate = item.get("rate", "+0%")
        if not line:
            continue
            
        # 🛡️ 音高安全鉗制 (Clamp)：嚴格將 pitch 限制在 -8Hz ~ +10Hz 舒適區間，徹底消除尖銳刺耳聲！
        m_pitch = re.search(r'([+-]?\d+)', raw_pitch)
        if m_pitch:
            p_val = int(m_pitch.group(1))
            clamped_p = max(-8, min(10, p_val))
            safe_pitch = f"{clamped_p:+d}Hz"
        # 🌐 多語系歌聲支援 (韓文用 SunHi，日文經由小依無歧義發音引擎保留小依本尊)
        from core.prompts import TextCleanEngine
        has_hangul = re.search(r'[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]', line)
        if has_hangul:
            singing_voice = "ko-KR-SunHiNeural"
            singing_line = line
        else:
            singing_voice = "zh-CN-XiaoyiNeural"
            singing_line = TextCleanEngine.clean_for_tts(line, apply_phonetics=True)
            
        chunk_file = os.path.join(SONGS_DIR, f"temp_{safe_name}_{idx}.mp3")
        audio_written = False
        if singing_voice == "zh-CN-XiaoyiNeural":
            try:
                import local_xiaoyi_service
                local_b = await local_xiaoyi_service.get_xiaoyi_audio_bytes(singing_line)
                if local_b and len(local_b) > 0:
                    with open(chunk_file, "wb") as f_chunk:
                        f_chunk.write(local_b)
                    audio_written = True
            except Exception:
                pass
                
        if not audio_written:
            comm = edge_tts.Communicate(text=singing_line, voice=singing_voice, pitch=safe_pitch, rate=rate)
            await comm.save(chunk_file)
        temp_chunks.append(chunk_file)
        
    # 合併音訊
    with open(out_file, "wb") as outfile:
        for chunk in temp_chunks:
            if os.path.exists(chunk):
                with open(chunk, "rb") as infile:
                    outfile.write(infile.read())
                try:
                    os.remove(chunk)
                except Exception:
                    pass
                    
    print(f"✨ [7L 全網動態唱歌] 成功打造《{song_name}》專屬歌聲檔案: {out_file}")
    return out_file

async def play_singing_performance(song_name: str):
    """全網搜尋歌詞、即時合成並在直播間開口演唱"""
    if not song_name:
        song_name = "小幸運"
        
    vocal_path = await generate_song_vocal_dynamic(song_name)
    
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
            
        pygame.mixer.music.load(vocal_path)
        pygame.mixer.music.set_volume(1.0)
        pygame.mixer.music.play()
        
        print(f"🎤 [7L 舞台開唱] 正在演唱《{song_name}》...")
        
        # 播放直到結束（或前台控制）
        play_dur = 0.0
        while pygame.mixer.music.get_busy() and play_dur < 8.0:
            await asyncio.sleep(0.5)
            play_dur += 0.5
            
        pygame.mixer.music.stop()
        print(f"✨ [7L 舞台開唱] 《{song_name}》演唱完畢！")
        return f"謝謝大家～剛才為大家演唱的是《{song_name}》！希望大家喜歡！[EXPRESSION: 愛心]"
    except Exception as e:
        print(f"❌ [唱歌播放異常]: {e}")
        return f"剛才麥克風稍微卡了一下，下次再唱《{song_name}》給老爸聽！"

if __name__ == "__main__":
    async def test():
        print("=== 🌐 測試全網自由搜尋歌詞並即時演唱 ===")
        res = await play_singing_performance("六兆年與一夜物語")
        print("輸出結果:", res)
    asyncio.run(test())
