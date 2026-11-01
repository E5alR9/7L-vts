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

# Tavily 沒餘額／失敗時改問桌面版 Gemini（它自己會上網查，免費；老爸指定 2026-10-27），再不行才 DuckDuckGo
DESKTOP_SEARCH_FALLBACK = True
DESKTOP_SEARCH_TIMEOUT_SEC = 25.0


def _desktop_search(query: str) -> str:
    """請桌面版 Gemini 上網查，回「- 重點」幾行；沒開、卡住、沒答回空字串。"""
    if not DESKTOP_SEARCH_FALLBACK:
        return ""
    try:
        from services import desktop_helper as dh
        ans = dh.get_answer(query, DESKTOP_SEARCH_TIMEOUT_SEC)   # 直接問（規矩一多反而讓它陷入幻覺，老爸 2026-10-27）
    except Exception as e:
        log_print(f"⚠️ [網路搜尋] 桌面版 Gemini 也沒查成（{str(e)[:60]}），改用 DuckDuckGo")
        return ""
    lines = [ln.strip().lstrip("-•*").strip() for ln in (ans or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    log_print(f"📱 [網路搜尋] Tavily 不行，桌面版 Gemini 查到 {len(lines)} 行")
    return "\n".join(f"- {ln}" for ln in lines[:6])


def search_google(query: str, depth: str = "basic", allow_desktop: bool = True) -> str:
    """使用 Google / 網路搜尋引擎查詢最新的即時資訊、天氣、時事新聞或未知知識。
    
    Args:
        query: 要搜尋的關鍵字或問題描述
        depth: Tavily 搜尋深度。預設 basic（2026-11-01 實測沒快取的新問題：basic 中位數約 1.5 秒、advanced 約 3.4 秒，
               摘要出來的答案一樣好，basic 還只扣一半額度；fast／ultra-fast 更常查不到，不用）
    """
    log_print(f"\n🔍 [Tool 調用] 7L 正在使用 Google / 網路搜尋: 「{query}」")
    # 問天氣先拿預報數字（Open-Meteo，約 0.8 秒、帶日期）；以前網路搜尋拿到 4 月的舊新聞（2026-11-01）。查不到才往下搜
    try:
        from services.weather import forecast_text
        w = forecast_text(query)
        if w:
            return w
    except Exception:
        log_swallowed()
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
                log_print(f"⚠️ [網路搜尋] Tavily 失敗，改問桌面版 Gemini：{str(err)[:120]}")

        desk = _desktop_search(query) if allow_desktop else ""
        if desk:
            return desk

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

# ── 猜到要查就先查（speculative tool calling，2026-11-01）──
# 語意分流判定老爸這句是要查資料，紙條還在送主腦時就先用老爸的原句搜；她交辦的子智能體任務跟這句講同一件事，
# 就直接拿這份結果，不用再等工具判定（約 1.8 秒）和搜尋（約 1.5 秒）。只留最近一份，放太久、講的不是同件事就不用。
PREFETCH_MAX_AGE = 30.0
PREFETCH_WAIT_SEC = 8.0
_PREFETCH = {"text": "", "ts": 0.0, "future": None}
_PREFETCH_POOL = None
# 句首的客套、叫她查的字（只拿句首的：「申請」「檢查」「好看」裡的字不能砍，Fable 審查）
_LEAD = ("7L", "七L", "，", ",", "、", " ", "幫我", "幫老爸", "幫忙", "請", "麻煩", "上網查", "上網", "搜尋", "搜", "查查看", "查一下",
         "查查", "查詢", "查", "看一下", "看看", "一下", "告訴我", "跟我說", "給我")
_OTHER_JOB = re.compile(r"提醒|計時|鬧鐘|分鐘後|秒後|小時後|記住|記下|唱|彈")   # 還夾著別件事：不先查、也不拿
_WHEN = re.compile(r"今天|明天|後天|大後天|昨天|前天|今晚|明晚|週末|這週|下週|上週|本週|這個月|下個月|今年|去年|明年|現在")
_PAST = re.compile(r"上次|之前|以前|記得|說過|講過|問過")   # 問過去的事：要查的是記憶（search_knowledge），不是網路


def _prefetch_query(text: str, now=None) -> str:
    """老爸原句 → 搜尋字串：拿掉句首「幫我查一下」這些；「今年、去年、最近」換成真的年月——子智能體的工具判定會這樣寫，
    先查不經過它，原句「今年金馬獎」搜到的是去年的（2026-11-01 模擬版：答成去年得獎的《大濛》）。"""
    from datetime import datetime
    now = now or datetime.now()
    q = (text or "").strip()
    changed = True
    while changed:
        changed = False
        for w in _LEAD:
            if q.startswith(w):
                q, changed = q[len(w):], True
    q = q.strip(" ，,。？?！!") or (text or "").strip()
    q = q.replace("今年", f"{now.year}年").replace("去年", f"{now.year - 1}年")
    if re.search(r"最近|最新|近期|新上映|這週|本週|這個月", q) and str(now.year) not in q:
        q += f" {now.year}年{now.month}月"
    return q


def _same_question(a: str, b: str) -> bool:
    """兩句是不是問同一件事：數字、英文要一模一樣；中文的相鄰兩字（「台中」「台北」）兩邊重疊要七成五以上。
    以前只看單字有沒有出現：「明天台北會不會下雨」對「明天台中會不會下雨」算一樣，拿台中的預報當台北講（Fable 審查）。"""
    qa, qb = _prefetch_query(a), _prefetch_query(b)
    if set(re.findall(r"[A-Za-z0-9]+", qa.lower())) != set(re.findall(r"[A-Za-z0-9]+", qb.lower())):
        return False
    if set(_WHEN.findall(qa)) != set(_WHEN.findall(qb)):   # 明天／後天只差一個字，重疊照樣很高
        return False

    def grams(q):
        out = set()
        for run in re.findall(r"[\u4e00-\u9fff]+", q):
            out.update(run[i:i + 2] for i in range(len(run) - 1))
        return out
    ga, gb = grams(qa), grams(qb)
    return bool(ga and gb) and len(ga & gb) / len(ga | gb) >= 0.75


def prefetch(text: str) -> None:
    """語意分流判定要查資料時呼叫：背景開始搜（不叫桌面版：它很慢、會搶走主腦自己要用的桌面版）。
    夾著別件事、問過去的事的句子不先查。"""
    global _PREFETCH_POOL
    if not text or _OTHER_JOB.search(text) or _PAST.search(text):
        return
    import time
    from concurrent.futures import ThreadPoolExecutor
    if _PREFETCH_POOL is None:
        _PREFETCH_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="search_prefetch")
    q = _prefetch_query(text)
    _PREFETCH.update(text=text, ts=time.time(), future=_PREFETCH_POOL.submit(search_google, q, allow_desktop=False))
    log_print(f"🏃 [先查] 老爸像要查資料，先搜：「{q}」")


def take_prefetch(task: str, now: float = None):
    """子智能體拿到任務時問：有剛先搜好（或正在搜）的、問的是同一件事，就回那個 future（呼叫端 await），不然回 None。"""
    import time
    fut = _PREFETCH.get("future")
    now = time.time() if now is None else now
    if (fut is None or now - _PREFETCH["ts"] > PREFETCH_MAX_AGE or _OTHER_JOB.search(task or "")
            or _PAST.search(task or "") or not _same_question(task, _PREFETCH["text"])):
        return None
    _PREFETCH.update(text="", ts=0.0, future=None)   # 用一次就清掉
    return fut


# 摘要提示詞：數字帶單位和方向、舊資料講日期、沒答案不猜（2026-11-01 模擬版：她把「1 台幣換 4.85 日圓」講成「日幣對台幣 4.8」）。
# 12 題真的搜尋結果、各摘 3 次、Groq 當裁判對照原始資料：舊提示詞 temp 0.75 沒講錯 26/36 → 這版 temp 0.3 34/36
#（只改提示詞不降溫 31/36；錯的多是換算方向反了、把別天的事講成這週、資料裡沒有的歸因）。
_SUMMARY_SYSTEM = ("妳是虛擬主播 7L，負責把搜尋原始資料轉成自然口語。請將清單或網頁標題轉換為重點說明，並使用純文字對話。\n"
                   "數字一定照資料講，帶單位和方向（匯率講成「1 台幣換 4.85 日圓」或「1 美元換 32.6 台幣」，不要只說「日幣對台幣 4.8」）；"
                   "資料裡的日期跟問的不一樣（舊新聞、別天的預報）要講出是哪天的；資料裡沒有答案就老實說沒查到，不要猜。")


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
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": f"查詢：{query}\n\n搜尋原始資料：\n{clean_search}\n\n請以親切隨性的口吻，用 1~3 句俐落短句（40~80 字以內）對{_prompt_who}提煉並說明重點。"},
            ],
            temperature=0.3, max_tokens=500, timeout=4.5,
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
