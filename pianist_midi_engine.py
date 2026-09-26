# -*- coding: utf-8 -*-
"""
🎹 7L 全球鋼琴 MIDI 智慧抓取與下載引擎
=========================================
邏輯流程：
1. 🔗 若傳入 YouTube 網址 或 明確要求 YouTube：直接走 YouTube ➔ 下載 MP3 ➔ 線上 BearAudio/Ofoct MP3 to MIDI 轉檔
2. 🎼 預設一般點歌（第一優先）：OnlineSequencer 潔淨樂譜
   - 透過 Google / Tavily 搜尋 `<歌名> site:onlinesequencer.net`，抓取 Sequence ID 下載 100% 精準原版雙手 MIDI！
3. 🎵 預設第二優先：BitMidi 潔淨樂譜庫
4. 🎬 降級備用：若潔淨樂譜庫查無此曲，自動向 YouTube 搜尋演奏影片並調用線上 MP3 to MIDI 轉檔！
"""

import os
import sys
import re
import subprocess
import urllib.parse
import json
import requests
from typing import Optional, Tuple
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

load_dotenv(r"c:\Users\qiwai\.env")

import bitmidi_engine
import onlinesequencer_engine
import cloud_mp3_to_midi

def sanitize_filename(name: str) -> str:
    clean = re.sub(r'[\\/*?:"<>|]', '_', name).strip()
    return clean[:80]

def extract_youtube_video_id(url: str) -> Optional[str]:
    if not url: return None
    m = re.search(r'(?:v=|youtu\.be/|embed/|shorts/|watch\?.*?v=)([a-zA-Z0-9_\-]{11})', url)
    return m.group(1) if m else None

def clean_song_query(query: str) -> str:
    """清理點歌詞中的冗餘字詞，取得純淨歌名搜尋詞"""
    q = query.strip()
    clean_q = re.sub(r'^(彈|播放|放|來一首|請彈|幫我彈|聽|點歌)', '', q).strip()
    clean_q = re.sub(r'(钢琴演奏|鋼琴演奏|钢琴版|鋼琴版|BGM|bgm|彈的|版本)+$', '', clean_q).strip()
    clean_q = re.sub(r'[「」『』"\'《》\-—–]+', ' ', clean_q).strip()
    clean_q = re.sub(r'\s+', ' ', clean_q).strip()
    return clean_q or query

def is_title_relevant(search_q: str, result_title: str) -> bool:
    """過濾完全不相關的搜尋結果"""
    if not search_q or not result_title:
        return True
    sq_lower = search_q.lower()
    rt_lower = result_title.lower()
    
    tokens = [t for t in re.split(r'[\s_\-.,!?()（）\[\]/]+', sq_lower) if len(t) >= 2 and t not in ["piano", "midi", "bgm", "theme", "ost", "soundtrack", "fc", "任天堂"]]
    if not tokens:
        return True
    
    return any(t in rt_lower for t in tokens)

def convert_youtube_url_to_midi(url: str, output_dir: str = "midi_sheets", filename_hint: str = "") -> Optional[str]:
    """🎬 YouTube 直連轉檔：自 YouTube 下載 MP3 並透過線上 BearAudio 轉錄為 88 鍵 MIDI"""
    vid = extract_youtube_video_id(url)
    if not vid:
        return None
    canonical_url = f"https://www.youtube.com/watch?v={vid}"
    print(f"🎬 [YouTube 直連解析] 正在解析: {canonical_url}...")
    
    # 呼叫 cloud_mp3_to_midi 進行一鍵下載與線上轉檔
    midi_path = cloud_mp3_to_midi.download_yt_and_convert_to_midi(canonical_url, output_dir=output_dir, filename_hint=filename_hint)
    return midi_path

def search_youtube_and_download_midi(song_name: str, output_dir: str = "midi_sheets") -> Optional[str]:
    """🔍 在 YouTube 搜尋鋼琴音訊並透過線上 BearAudio 轉錄為 MIDI"""
    clean_name = clean_song_query(song_name)
    search_query = f"{clean_name} piano"
    print(f"🔍 [YouTube 搜尋] 正在搜尋: {search_query}...")
    
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            f"ytsearch1:{search_query}",
            "--dump-json",
            "--no-playlist"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=25)
        for line in proc.stdout.split('\n'):
            if line.strip().startswith('{'):
                data = json.loads(line)
                v_title = data.get("title", "")
                v_url = data.get("webpage_url", "")
                
                print(f"✅ [YouTube 命中目標影片] 《{v_title}》\n🔗 {v_url}")
                return convert_youtube_url_to_midi(v_url, output_dir, filename_hint=clean_name)
    except Exception as e:
        print(f"⚠️ [YouTube 轉錄異常]: {e}")
        
    return None

def fetch_and_download_pianist_match(song_query: str, output_dir: str = "midi_sheets") -> Optional[str]:
    """🌟 【全球標準抓譜管線】：
    1. 🔗 若為 YouTube 網址 或 明確指定 YouTube：走 YouTube MP3 ➔ 線上 BearAudio 轉 MIDI
    2. 🎼 預設一般點歌（第一優先）：OnlineSequencer (先 Google 找 site:onlinesequencer.net 再下載純淨 88 鍵 MIDI)
    3. 🎵 第二優先：BitMidi 純淨樂譜庫
    4. 🎬 降級備用：若樂譜庫查無該曲，自動向 YouTube 搜尋鋼琴音訊並轉錄為 MIDI
    """
    if not song_query:
        return None
        
    os.makedirs(output_dir, exist_ok=True)
    raw_query = song_query.strip()
    
    # ── 🔗 判斷是否為明確要求 YouTube ──
    has_yt_url = bool("youtube.com" in raw_query or "youtu.be" in raw_query)
    is_explicit_yt = has_yt_url or any(k in raw_query.lower() for k in ["youtube", "yt", "轉midi", "mp3 to midi", "影片", "轉成midi"])
    
    if has_yt_url:
        url_match = re.search(r'https?://[^\s]+', raw_query)
        if url_match:
            yt_url = url_match.group(0)
            res_p = convert_youtube_url_to_midi(yt_url, output_dir)
            if res_p:
                return res_p

    clean_q = clean_song_query(raw_query)

    # ── 🎬 若明確要求 YouTube 管道 ──
    if is_explicit_yt:
        print(f"🎬 [YouTube 專屬指定] 正在自 YouTube 下載音訊 MP3 並調用線上 BearAudio 轉錄 MIDI...")
        yt_res = search_youtube_and_download_midi(clean_q, output_dir)
        if yt_res and os.path.exists(yt_res):
            return yt_res

    # ── 🎹 預設模式（第一優先：OnlineSequencer 經由 Google 搜尋） ──
    print(f"🎹 [OnlineSequencer 搜尋 - 第一優先] 正在 Google/OnlineSequencer 搜尋《{clean_q}》...")
    dl_p = onlinesequencer_engine.fetch_and_download_first_match(clean_q, output_dir)
    if dl_p and os.path.exists(dl_p):
        print(f"✨ [OnlineSequencer 命中成功] 《{os.path.basename(dl_p)}》！")
        return dl_p
            
    # ── 🎵 預設模式第二優先：BitMidi ──
    print(f"🎵 [BitMidi 搜尋 - 第二優先] 正在向 BitMidi 搜尋《{clean_q}》...")
    dl_p = bitmidi_engine.fetch_and_download_first_match(clean_q, output_dir)
    if dl_p and os.path.exists(dl_p):
        print(f"✨ [BitMidi 收錄成功] 《{os.path.basename(dl_p)}》！")
        return dl_p

    # ── 🎬 降級備用：若純淨樂譜庫皆查無，自動向 YouTube 轉錄 ──
    print(f"🌐 [樂譜庫查無結果] 自動向 YouTube 搜尋鋼琴演奏並調用線上 BearAudio 轉檔...")
    yt_res = search_youtube_and_download_midi(clean_q, output_dir)
    if yt_res and os.path.exists(yt_res):
        return yt_res

    return None

if __name__ == "__main__":
    test_q = "李斯特 鐘"
    print("Testing clean MIDI search pipeline:")
    res1 = fetch_and_download_pianist_match(test_q)
    print("Result 1:", res1)
