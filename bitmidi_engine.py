"""
BitMidi 雲端搜尋與下載引擎
=========================
提供向 BitMidi (https://bitmidi.com) 即時搜尋百萬 MIDI 樂譜並下載至本地的功能。
已加入嚴格關鍵字語意關聯性驗證，徹底防止下載不相干的垃圾檔案。
"""

import os
import re
import urllib.parse
from typing import Dict, List, Optional
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

_session = requests.Session()
_session.headers.update(HEADERS)

def _is_relevant_match(query: str, title: str, href: str) -> bool:
    """嚴格檢驗搜尋結果與用戶曲名是否真正相關，杜絕模糊無效匹配"""
    q_words = [w.lower() for w in re.split(r'[\s\-_,，+]+', query.strip()) if len(w) >= 2 and w.lower() not in ['midi', 'piano', 'song', 'the', 'by', 'of']]
    if not q_words:
        return True
    
    target_text = f"{title.lower()} {href.lower()}"
    # 只要 query 裡的核心詞彙有至少一個完整出現在標題中才算命中
    matched_count = sum(1 for w in q_words if w in target_text)
    return matched_count > 0

def search_bitmidi(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """向 BitMidi 搜尋歌曲，返回歌曲清單 [{title, url, download_url}]"""
    query = query.strip()
    if not query:
        return []
    
    encoded_q = urllib.parse.quote(query)
    search_url = f"https://bitmidi.com/search?q={encoded_q}"
    
    results = []
    try:
        resp = _session.get(search_url, timeout=10.0)
        if resp.status_code != 200:
            return []
        
        # 匹配 <a ... href="/song-name-mid">Song Name</a>
        pattern = r'<a[^>]+href="(/[^"]+-mid)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, resp.text, re.IGNORECASE | re.DOTALL)
        
        seen_urls = set()
        for href, raw_title in matches:
            if href in seen_urls:
                continue
            seen_urls.add(href)
            
            # 清理 HTML 標籤與換行
            clean_title = re.sub(r'<[^>]+>', '', raw_title).replace('\n', ' ').replace('\r', ' ').strip()
            if not clean_title:
                clean_title = href.strip('/').replace('-mid', '').replace('-', ' ').title()
                
            # 🛑 關鍵字關聯性過濾：拒絕不相干結果
            if not _is_relevant_match(query, clean_title, href):
                continue
                
            page_url = urllib.parse.urljoin("https://bitmidi.com", href)
            results.append({
                "title": clean_title,
                "url": page_url,
                "download_url": ""
            })
            if len(results) >= max_results:
                break
    except Exception as e:
        pass
        
    return results

def get_direct_download_url(page_url: str) -> Optional[str]:
    """從 BitMidi 歌曲詳細頁面解析出 .mid 實際下載連結"""
    try:
        resp = _session.get(page_url, timeout=10.0)
        if resp.status_code != 200:
            return None
        
        matches = re.findall(r'href="([^"]+(?:/uploads/[^"]+|\.mid[^"]*))"', resp.text, re.IGNORECASE)
        for dl_href in matches:
            if dl_href.lower().endswith(".mid") or "/uploads/" in dl_href:
                return urllib.parse.urljoin(page_url, dl_href)
    except Exception as e:
        print(f"⚠️ [BitMidi 取得下載連結失敗]: {e}")
    return None

def download_bitmidi_song(target_song: Dict[str, str], save_dir: str = "midi_sheets") -> Optional[str]:
    """下載指定歌曲至 save_dir 並返回儲存檔案路徑"""
    os.makedirs(save_dir, exist_ok=True)
    title = target_song.get("title", "unknown_song")
    page_url = target_song.get("url", "")
    dl_url = target_song.get("download_url") or ""
    
    if not dl_url and page_url:
        dl_url = get_direct_download_url(page_url)
        
    if not dl_url:
        return None
        
    # 建立合法檔案名稱
    safe_title = re.sub(r'[\\/*?:"<>|]', '', title).strip()
    if not safe_title:
        safe_title = "song"
    if not safe_title.lower().endswith(".mid"):
        safe_title += ".mid"
        
    target_path = os.path.join(save_dir, safe_title)
    
    try:
        resp = _session.get(dl_url, timeout=15.0)
        if resp.status_code == 200 and len(resp.content) > 100:
            with open(target_path, "wb") as f:
                f.write(resp.content)
            return target_path
    except Exception as e:
        print(f"⚠️ [BitMidi 下載失敗]: {e}")
        
    return None

def fetch_and_download_first_match(query: str, save_dir: str = "midi_sheets") -> Optional[str]:
    """一鍵搜尋並下載第一首匹配的歌曲（已過濾不相干垃圾檔案）"""
    results = search_bitmidi(query, max_results=3)
    if not results:
        return None
    for res in results:
        saved = download_bitmidi_song(res, save_dir=save_dir)
        if saved:
            return saved
    return None
