# -*- coding: utf-8 -*-
"""網路搜尋（2026-10-25 從主程式搬出來）：Tavily 多金鑰輪替＋DuckDuckGo 備援，搜尋結果用 Groq 提煉成口語。

PROVIDER: TAVILY（主）／DuckDuckGo（備援）／GROQ（摘要）。
TAVILY_KEYS 讀 .env 的 TAVILY_KEYS／TAVILY_API_KEYS／TAVILY_API_KEY；沒裝 tavily 套件就用純 Python 版打 REST。
"""
import os
import re

from core.utils import log_print, log_swallowed

try:
    from tavily import TavilyClient
except (ImportError, Exception):
    TavilyClient = None

TAVILY_KEYS = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("TAVILY_KEYS") or os.getenv("TAVILY_API_KEYS") or os.getenv("TAVILY_API_KEY") or "") if k.strip()]

class PurePythonTavilyClient:
    """純 Python Tavily 輕量搜尋客戶端（0 C/DLL 依賴，徹底避免 Windows AppLocker 或 tiktoken.pyd 崩潰）"""
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, search_depth: str = "advanced", topic: str = "general", **kwargs) -> dict:
        import urllib.request, json
        try:
            payload = {
                "api_key": self.api_key,
                "query": query,
                "search_depth": search_depth,
                "topic": topic,
                **kwargs
            }
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}

class MultiKeyTavilyClient:
    """支援多把金鑰自動故障轉移（Failover）與輪替的 Tavily 搜尋客戶端"""
    def __init__(self, api_keys: list):
        self.api_keys = [k.strip() for k in api_keys if k and k.strip()]
        self._current_idx = 0
        self._clients = []
        for k in self.api_keys:
            c = None
            if TavilyClient is not None:
                try:
                    c = TavilyClient(api_key=k)
                except Exception:
                    c = None
            if c is None:
                c = PurePythonTavilyClient(api_key=k)
            self._clients.append(c)

    def search(self, query: str, search_depth: str = "advanced", topic: str = "general", **kwargs) -> dict:
        if not self._clients:
            return {"error": "No Tavily API keys configured"}
        num_keys = len(self._clients)
        last_err = ""
        for attempt in range(num_keys):
            idx = (self._current_idx + attempt) % num_keys
            c = self._clients[idx]
            try:
                res = c.search(query=query, search_depth=search_depth, topic=topic, **kwargs)
                if isinstance(res, dict):
                    err_msg = str(res.get("error") or res.get("detail") or res.get("message") or "")
                    if any(w in err_msg.lower() for w in ["limit", "exceed", "quota", "403", "429", "unauthorized"]):
                        last_err = err_msg
                        continue
                    if "results" in res:
                        self._current_idx = idx
                        return res
                elif res:
                    self._current_idx = idx
                    return res
            except Exception as e:
                err_str = str(e)
                last_err = err_str
                if any(w in err_str.lower() for w in ["limit", "exceed", "quota", "403", "429"]):
                    continue
                continue
        return {"error": last_err or "All Tavily keys failed or exceeded quota"}

if TAVILY_KEYS:
    tavily_client = MultiKeyTavilyClient(TAVILY_KEYS)
else:
    tavily_client = None

def search_google(query: str, depth: str = "advanced") -> str:
    """使用 Google / 網路搜尋引擎查詢最新的即時資訊、天氣、時事新聞或未知知識。
    
    Args:
        query: 要搜尋的關鍵字或問題描述
        depth: Tavily 搜尋深度（basic 省額度）
    """
    log_print(f"\n🔍 [Tool 調用] 7L 正在使用 Google / 網路搜尋: 「{query}」")
    try:
        is_news_query = any(k in query for k in ["新聞", "時事", "今天", "昨天", "最新", "發生什麼", "快訊", "熱搜", "熱門", "突發", "大事"])
        topic_mode = "news" if is_news_query else "general"

        if tavily_client:
            res = tavily_client.search(query=query, topic=topic_mode, search_depth=depth)
            if isinstance(res, dict) and "results" in res:
                snippets = []
                for item in res["results"][:4]:
                    title = item.get("title", "")
                    content = item.get("content", "")
                    snippets.append(f"- {title}: {content}")
                if snippets:
                    return "\n".join(snippets)
            else:
                # 金鑰全失敗（額度爆、401）：記一行、改走 DuckDuckGo（以前把錯誤字典當結果回給大腦）
                err = res.get("error") if isinstance(res, dict) else res
                log_print(f"⚠️ [網路搜尋] Tavily 失敗，改用 DuckDuckGo：{str(err)[:120]}")
        
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
                if results:
                    snippets = [f"- {r.get('title', '')}: {r.get('body', '')}" for r in results]
                    return "\n".join(snippets)
        except Exception as e_ddg:
            log_print(f"\n⚠️ [DuckDuckGo 搜尋失敗]: {e_ddg}")
        return "搜尋無結果。"
    except Exception as e:
        log_print(f"\n❌ [搜尋 Tool 異常]: {e}")
        return f"搜尋時發生錯誤: {e}"

async def summarize_search_to_speech(query: str, search_raw: str, user_role_name: str = "") -> str:
    """PROVIDER: GROQ（core.groq_router.groq_chat 純文字提煉；見 docs/AI_SOURCES.md）"""
    """將搜尋到的原始資料，以 7L 招牌自然口語（1~3 句，親切隨性）進行提煉整理。
    容災序（全程零 Gemini）：groq_chat 梯隊（模型×金鑰輪詢）-> 本機離線摘要器，絕不直接傾倒原文！"""
    # ⚠️ 收聽人不一定是老爸：未知走中性（有誰寫誰，沒人可寫就不加稱呼）
    _who = (user_role_name or "").strip()
    _voc = f"{_who}，" if _who else ""
    _prompt_who = _who or "大家"
    if not search_raw or "搜尋無結果" in search_raw:
        return f"{_voc}我幫你查了一下，但目前網路上沒有找到相關的資料耶。"

    # 清理搜尋字串，避免傳入過大 token
    clean_search = re.sub(r'https?://\S+', '', search_raw)
    clean_search = re.sub(r'\s{2,}', ' ', clean_search).strip()[:1500]

    #  第 1 防線：Groq 極速提煉（groq_chat 梯隊，實測 0.4s 級；失敗或無結果才交給本機摘要）
    try:
        from core.groq_router import groq_chat
        g_resp = await groq_chat(
            [
                {"role": "system", "content": "妳是虛擬主播 7L，負責把搜尋原始資料轉成自然口語。請將清單或網頁標題轉換為重點說明，並使用純文字對話。"},
                {"role": "user", "content": f"查詢：{query}\n\n搜尋原始資料：\n{clean_search}\n\n請以親切隨性的口吻，用 1~3 句俐落短句（40~80 字以內）對{_prompt_who}提煉並說明重點。"},
            ],
            temperature=0.75, max_tokens=500, timeout=4.5,
        )
        if g_resp and g_resp.text:
            ans = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', g_resp.text).strip()
            if ans and not ans.startswith("(") and len(ans) > 5:
                return ans
    except Exception:
        log_swallowed()

    # 2. 第二防線：純本地智慧摘要器（100% 離線可用，絕不傾倒條列與 URL）
    lines = [l.strip() for l in search_raw.split('\n') if l.strip()]
    snippets = []
    for l in lines:
        clean_l = re.sub(r'^[-\d.*#\s]+', '', l)
        if ':' in clean_l:
            clean_l = clean_l.split(':', 1)[1].strip()
        clean_l = re.sub(r'https?://\S+', '', clean_l).strip()
        if len(clean_l) > 15:
            snippets.append(clean_l)
        if len(snippets) >= 2:
            break

    if snippets:
        summary_core = "，".join(snippets)
        if len(summary_core) > 90:
            summary_core = summary_core[:85] + "等等"
        return f"{_voc}我幫你查到囉！大致上來說，{summary_core}。詳細內容我待會再幫你細看喔！"
    return f"{_voc}我剛剛幫你查了，但搜尋到的內容有點繁雜，我待會再仔細整理跟你說！"
