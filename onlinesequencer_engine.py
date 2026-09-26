"""
OnlineSequencer.net MIDI 搜尋與下載引擎
=========================================
使用 Chrome CDP + 可見瀏覽器視窗自動繞過 Cloudflare 保護，
搜尋 onlinesequencer.net 並下載 MIDI 檔案。

策略：
1. 以「非無頭模式」啟動 Chrome（Cloudflare 可見不封鎖）
2. Session cookie 持久化於 oseq_chrome_profile 目錄
3. 首次執行若遭遇 Cloudflare 挑戰，等待用戶點擊通過後繼續自動下載
4. MIDI 直連 URL: https://onlinesequencer.net/app/midi.php?id=<seq_id>

修正說明（v2）：
- OnlineSequencer 搜尋結果的 <a href="/ID"></a> 標題永遠為空（JS 動態渲染）
- 改用 JS querySelectorAll('div.preview a[href]') 輪詢等待 DOM 渲染後再抓 ID
- 標題無法從靜態 HTML 取得時，以搜尋詞作為檔名
"""

import os, re, time, json, subprocess, urllib.parse, sys, base64
import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

load_dotenv(r"c:\Users\qiwai\.env")
try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None
from typing import Optional, List, Dict

BASE_URL = "https://onlinesequencer.net"
MIDI_DOWNLOAD_URL = "https://onlinesequencer.net/app/midi.php?id={seq_id}"
SEARCH_URL = "https://onlinesequencer.net/sequences?search={query}"
CDP_PORT = 9224

# 持久化 session profile（讓 Cloudflare clearance cookie 跨次保留）
OSEQ_PROFILE_DIR = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "oseq_chrome_profile")

_chrome_proc = None


def _find_chrome() -> Optional[str]:
    for path in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]:
        if os.path.exists(path):
            return path
    return None


def _is_cdp_alive() -> bool:
    try:
        r = requests.get(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _start_chrome() -> bool:
    """以可見模式啟動 Chrome（可通過 Cloudflare 挑戰）"""
    global _chrome_proc
    if _is_cdp_alive():
        return True

    chrome_path = _find_chrome()
    if not chrome_path:
        print("[OnlineSequencer] 找不到 Chrome！")
        return False

    os.makedirs(OSEQ_PROFILE_DIR, exist_ok=True)

    _chrome_proc = subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={OSEQ_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--remote-allow-origins=*",
        # 不用 --headless，讓視窗可見以通過 Cloudflare
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(15):
        time.sleep(1)
        if _is_cdp_alive():
            return True

    print("[OnlineSequencer] Chrome 啟動超時")
    return False


def _stop_chrome():
    global _chrome_proc
    if _chrome_proc:
        try:
            _chrome_proc.terminate()
        except Exception:
            pass
        _chrome_proc = None


def _get_ws_url() -> Optional[str]:
    try:
        r = requests.get(f"http://localhost:{CDP_PORT}/json", timeout=5)
        tabs = r.json()
        for tab in tabs:
            if tab.get("type") == "page":
                return tab.get("webSocketDebuggerUrl")
    except Exception:
        pass
    return None


def _cdp_eval(ws_url: str, js: str, timeout: float = 10.0) -> Optional[str]:
    import websocket
    ws = websocket.create_connection(ws_url, timeout=int(timeout))
    try:
        cmd = json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js, "returnByValue": True, "awaitPromise": True}})
        ws.send(cmd)
        ws.settimeout(timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data = json.loads(ws.recv())
                if data.get("id") == 1:
                    return data.get("result", {}).get("result", {}).get("value")
            except Exception:
                break
    finally:
        ws.close()
    return None


def _cdp_navigate(ws_url: str, url: str, wait_cf: float = 5.0):
    import websocket
    ws = websocket.create_connection(ws_url, timeout=15)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        time.sleep(wait_cf)  # Wait for CF challenge + page load
    finally:
        ws.close()


def _cdp_get_html(ws_url: str) -> str:
    result = _cdp_eval(ws_url, "document.documentElement.outerHTML", timeout=10.0)
    return result or ""



def _cdp_download_midi(ws_url: str, seq_id: str) -> Optional[bytes]:
    """
    在 Chrome 裡導航到曲目頁面，攔截 exportMidi() 產生的 Blob，直接讀取 MIDI bytes。
    完全在真實瀏覽器內執行，繞過所有 Cloudflare / CORS 限制。
    """
    import base64

    # 1. 導航到曲目頁面（等待完整載入）
    _cdp_navigate(ws_url, f"https://onlinesequencer.net/{seq_id}", wait_cf=7.0)

    # 2. 注入攔截器：覆蓋 URL.createObjectURL 截取 Blob bytes，並阻止真實下載
    intercept_js = """
(async () => {
    window.__midiCaptured = null;
    window.__midiError = null;

    // 覆蓋 URL.createObjectURL 攔截 Blob
    const _orig = URL.createObjectURL.bind(URL);
    URL.createObjectURL = function(blob) {
        try {
            const reader = new FileReader();
            reader.onload = function(e) {
                const ab = e.target.result;
                const bytes = new Uint8Array(ab);
                let bin = '';
                for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
                window.__midiCaptured = btoa(bin);
            };
            reader.onerror = function() { window.__midiError = 'FileReader error'; };
            reader.readAsArrayBuffer(blob);
        } catch(e) { window.__midiError = e.toString(); }
        // 回傳假 URL，阻止瀏覽器真實下載（避免彈出另存對話框）
        return 'blob:intercepted';
    };

    // 覆蓋 <a>.click 避免真實導航
    const _origClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function() {
        const href = this.getAttribute('href') || '';
        if (href === 'blob:intercepted' || href.startsWith('blob:')) return;
        return _origClick.apply(this, arguments);
    };

    // 呼叫 exportMidi()
    try {
        if (typeof exportMidi === 'function') {
            exportMidi();
        } else {
            window.__midiError = 'exportMidi not found';
        }
    } catch(e) { window.__midiError = e.toString(); }

    // 最多等 8 秒讓 FileReader 完成
    for (let i = 0; i < 80; i++) {
        if (window.__midiCaptured !== null || window.__midiError !== null) break;
        await new Promise(r => setTimeout(r, 100));
    }

    return JSON.stringify({
        midi: window.__midiCaptured,
        error: window.__midiError
    });
})()
"""
    result = _cdp_eval(ws_url, intercept_js, timeout=25.0)
    if not result:
        print(f"[OnlineSequencer] seq {seq_id}: JS 攔截器無回應")
        return None

    try:
        data = json.loads(result)
    except Exception:
        print(f"[OnlineSequencer] seq {seq_id}: JSON 解析失敗: {result[:100]}")
        return None

    if data.get("error"):
        print(f"[OnlineSequencer] seq {seq_id}: exportMidi 錯誤: {data['error']}")
        return None

    midi_b64 = data.get("midi")
    if not midi_b64:
        print(f"[OnlineSequencer] seq {seq_id}: 未截取到 MIDI blob")
        return None

    try:
        midi_bytes = base64.b64decode(midi_b64)
        if midi_bytes[:4] == b'MThd':
            return midi_bytes
        print(f"[OnlineSequencer] seq {seq_id}: 非有效 MIDI（前4 bytes: {midi_bytes[:4].hex()}）")
    except Exception as e:
        print(f"[OnlineSequencer] seq {seq_id}: base64 解碼失敗: {e}")
    return None



def _wait_for_cloudflare(ws_url: str, max_wait: float = 30.0) -> bool:
    """等待 Cloudflare 挑戰通過（最多等 max_wait 秒）"""
    deadline = time.time() + max_wait
    print(f"[OnlineSequencer] 等待 Cloudflare 驗證通過 (最多 {int(max_wait)}s)...")
    while time.time() < deadline:
        html = _cdp_get_html(ws_url)
        if html and "Just a moment" not in html and "challenge" not in html.lower()[:500]:
            return True
        time.sleep(1.5)
    return False



def search_onlinesequencer_via_google_tavily(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    """
    透過 Google 搜尋引擎精準搜尋：
    先搜尋 `<歌名> midi`，從 Google 搜尋結果中鎖定跳出來的 `onlinesequencer.net/<ID>` 頁面並抓取下載！
    """
    if not query or not query.strip():
        return []
    
    clean_q = query.strip()
    raw_tavily = os.getenv("TAVILY_KEYS") or os.getenv("TAVILY_API_KEYS") or os.getenv("TAVILY_API_KEY") or ""
    tavily_keys = [k.strip() for k in re.split(r'[\s,;]+', raw_tavily) if k.strip()]
    
    results = []
    seen = set()

    # 1. Google 搜尋詞候選 (優先搜尋 `<歌名> midi`，備選 `<歌名> onlinesequencer`)
    search_queries = [
        f"{clean_q} midi",
        f"{clean_q} onlinesequencer",
        f"{clean_q} site:onlinesequencer.net"
    ]

    if TavilyClient and tavily_keys:
        for sq in search_queries:
            for t_key in tavily_keys[:2]:
                try:
                    t_client = TavilyClient(api_key=t_key)
                    print(f"[OnlineSequencer] 🌐 透過 Google 搜尋: {sq}...")
                    t_resp = t_client.search(query=sq, search_depth="basic", max_results=max_results)
                    
                    for r in t_resp.get("results", []):
                        url = r.get("url", "")
                        raw_title = r.get("title", "")
                        m = re.search(r'onlinesequencer\.net/(\d+)', url)
                        if m:
                            seq_id = m.group(1)
                            if seq_id not in seen:
                                seen.add(seq_id)
                                clean_title = raw_title.replace(" - Online Sequencer", "").replace("Online Sequencer", "").strip()
                                clean_title = re.sub(r'https?://\S+', '', clean_title).strip() or clean_q
                                results.append({
                                    "title": clean_title,
                                    "seq_id": seq_id,
                                    "download_url": MIDI_DOWNLOAD_URL.format(seq_id=seq_id)
                                })
                    if results:
                        print(f"[OnlineSequencer] 🎯 Google 成功命中 OnlineSequencer 樂譜！首選: 《{results[0]['title']}》 (ID: {results[0]['seq_id']})")
                        return results
                except Exception as t_err:
                    print(f"[OnlineSequencer] Google 搜尋異常: {t_err}")

    # 2. 備用：DuckDuckGo Web HTML 抓取
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(clean_q + ' onlinesequencer midi')}"
        r = requests.get(ddg_url, headers=headers, timeout=5)
        matches = re.findall(r'onlinesequencer\.net/(\d+)', r.text)
        for seq_id in matches:
            if seq_id not in seen:
                seen.add(seq_id)
                results.append({
                    "title": clean_q,
                    "seq_id": seq_id,
                    "download_url": MIDI_DOWNLOAD_URL.format(seq_id=seq_id)
                })
        if results:
            print(f"[OnlineSequencer] 🎯 備用搜尋成功命中 {len(results)} 個 OnlineSequencer ID！")
            return results[:max_results]
    except Exception:
        pass

    return results


def search_onlinesequencer(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """搜尋 onlinesequencer.net，返回 [{title, seq_id, download_url}]

    注意：OnlineSequencer 的搜尋結果 <a href="/ID"></a> 標題永遠為空（由 JS 動態填入），
    因此改用 JS querySelectorAll 輪詢等待 DOM 渲染後再抓取 ID，標題以搜尋詞替代。
    """
    if not query or not query.strip():
        return []
    if not _start_chrome():
        return []

    ws_url = _get_ws_url()
    if not ws_url:
        return []

    try:
        # 先訪問主頁讓 CF cookie 生效
        _cdp_navigate(ws_url, BASE_URL, wait_cf=5.0)
        html_home = _cdp_get_html(ws_url)

        if "Just a moment" in html_home or "challenge" in html_home[:2000].lower():
            print("[OnlineSequencer] Cloudflare 挑戰中，請在彈出的 Chrome 視窗點擊確認...")
            if not _wait_for_cloudflare(ws_url, max_wait=60.0):
                print("[OnlineSequencer] Cloudflare 驗證逾時")
                return []

        # 前往搜尋頁
        encoded_q = urllib.parse.quote(query.strip())
        _cdp_navigate(ws_url, SEARCH_URL.format(query=encoded_q), wait_cf=5.0)

        # ── 用 JS 輪詢等待 div.preview 元素出現（解決 JS 動態渲染問題）──
        wait_js = """
(async () => {
    for (let i = 0; i < 20; i++) {
        const previews = document.querySelectorAll('div.preview a[href]');
        if (previews.length > 0) return previews.length;
        await new Promise(r => setTimeout(r, 500));
    }
    return 0;
})()
"""
        count = _cdp_eval(ws_url, wait_js, timeout=15.0)
        print(f"[OnlineSequencer] 搜尋結果數量: {count}")

        # ── 用 JS 直接從 DOM 抓取 seq_id（比 HTML regex 可靠得多）──
        extract_js = """
(() => {
    const results = [];
    const seen = new Set();
    document.querySelectorAll('div.preview a[href]').forEach(a => {
        const href = a.getAttribute('href') || '';
        const m = href.match(/^\\/([0-9]+)$/);
        if (!m) return;
        const seqId = m[1];
        if (seen.has(seqId)) return;
        seen.add(seqId);
        const title = (a.textContent || '').trim() ||
                      (a.getAttribute('title') || '').trim() ||
                      (a.closest('[data-title]') && a.closest('[data-title]').getAttribute('data-title')) || '';
        results.push({ seq_id: seqId, title: title });
    });
    return JSON.stringify(results);
})()
"""
        js_result = _cdp_eval(ws_url, extract_js, timeout=10.0)

        results = []
        seen = set()

        if js_result:
            try:
                items = json.loads(js_result)
                for item in items[:max_results]:
                    seq_id = str(item.get("seq_id", "")).strip()
                    if not seq_id or seq_id in seen:
                        continue
                    seen.add(seq_id)
                    # 標題通常為空，退而用搜尋詞作為檔名
                    title = item.get("title", "").strip() or query
                    results.append({
                        "title": title,
                        "seq_id": seq_id,
                        "download_url": MIDI_DOWNLOAD_URL.format(seq_id=seq_id)
                    })
            except Exception as parse_err:
                print(f"[OnlineSequencer] JS 結果解析錯誤: {parse_err}")

        # ── 備用：直接從 HTML regex 抓 ID（JS 萬一失敗的保險）──
        if not results:
            html = _cdp_get_html(ws_url)
            bare = re.findall(r"href=['\"]/([\d]{5,})['\"]", html)
            for seq_id in bare[:max_results]:
                if seq_id not in seen:
                    seen.add(seq_id)
                    results.append({
                        "title": query,
                        "seq_id": seq_id,
                        "download_url": MIDI_DOWNLOAD_URL.format(seq_id=seq_id)
                    })

        return results

    except Exception as e:
        print(f"[OnlineSequencer 搜尋錯誤]: {e}")
        return []


def fetch_and_download_first_match(query: str, save_dir: str = "midi_sheets") -> Optional[str]:
    """
    搜尋 onlinesequencer.net 並下載第一個匹配結果的 MIDI。
    使用 Chrome CDP（可見視窗）繞過 Cloudflare。失敗返回 None。
    """
    print(f"[OnlineSequencer] 搜尋: {query}...")

    if not _start_chrome():
        print("[OnlineSequencer] Chrome 無法啟動")
        return None

    # 🌟 策略 1：優先使用 Google / Tavily 智慧語意搜尋（精準定位曲名、別名與法文/德文特殊字元）
    results = search_onlinesequencer_via_google_tavily(query)
    
    # 🌟 策略 2：若 Google 搜尋無果，降級至 OnlineSequencer 站內 CDP 搜尋
    if not results:
        print(f"[OnlineSequencer] Google 索引未命中，改用站內 CDP 輪詢搜尋: {query}...")
        results = search_onlinesequencer(query)

    if not results:
        print(f"[OnlineSequencer] 找不到: {query}")
        _stop_chrome()
        return None

    # search 後重新取 ws_url（頁面已導航，確保用最新的 tab）
    ws_url = _get_ws_url()
    if not ws_url:
        _stop_chrome()
        return None

    os.makedirs(save_dir, exist_ok=True)
    for r in results:
        midi_bytes = _cdp_download_midi(ws_url, r["seq_id"])
        if midi_bytes:
            safe = re.sub(r'[\\/*?"<>|]', "", r["title"]).strip() or f"oseq_{r['seq_id']}"
            if not safe.lower().endswith(".mid"):
                safe += ".mid"
            out = os.path.join(save_dir, safe)
            with open(out, "wb") as f:
                f.write(midi_bytes)
            print(f"[OnlineSequencer] 成功下載: {r['title']} -> {out} ({len(midi_bytes)} bytes)")
            # 不立即停 Chrome，保留 CF cookie session 供下次快速重用
            return out

    print(f"[OnlineSequencer] {query} 所有結果下載失敗")
    _stop_chrome()
    return None


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "moonlight sonata"
    result = fetch_and_download_first_match(q, save_dir="midi_sheets_test")
    print(f"Result: {result}")
