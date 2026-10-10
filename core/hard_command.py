# -*- coding: utf-8 -*-
"""CPU 硬指令拆解（B 架構專用）：純正則、零 API、零幻覺、零成本。

只負責把「唱歌」「彈琴」兩類**明確祈使句**拆成 (工具名, 參數)；
拆不出來就回 (None, {})，交還 A 架構（Live 主腦 → invoke_subagent → NV 解讀）。
搜尋類指令刻意不在這裡處理（資訊型工具結果無處可去，只能燒 API）。

2026-10-09 修正直播誤觸（兩個真實案例）：
  觀眾「你可以唱歌了？」   → 舊正則抽出歌名「歌了？」，真的啟動 YT-DLP 搜尋
  老爸「? 又我唱了????」  → 抽出「了????」，也真的開跑
三道閘門（**寧可漏判，不可誤觸**：漏判只是交回主腦，誤觸會白燒 GPU＋YouTube）：
  A. 句首門：關鍵字前面只允許祈使前綴（請/幫我/來/你…）；「他彈琴比我還快」
     這種第三人稱陳述句一律不攔
  B. 動詞粘連：關鍵字後「沒有分隔符」且緊接著 歌/了/完/得/過/出…＝動詞句，不攔
  C. 候選歌名切在 ？！。， 之前，並清洗尾部標點與語氣詞；仍須 ≥2 字、
     非停用詞、非泛指量詞片語（一首歌/個歌…）、且含中英數字
"""
import re
from typing import Dict, Optional, Tuple

_TRAIL_JUNK = re.compile(r'[?？!！。，,、；;：:\s~～…]+$')
# 句尾語氣詞（可安全剝除：真實歌名幾乎不會以這些字結尾）
_TRAIL_MODAL = re.compile(r'(?:嗎|嘛|啊|吧|呢|喔|哦|呀|啦|嘿|哟|哈|唄|噢|喲|唷)+$')
# ⚠️ 體貌字（了/完/過）**常常就在歌名裡**（《沒離開過》《錯過》《散了》），
# 而且字面上無法和「唱晴天了」區分——一律不剝，避免把真歌名削壞。
# （2026-10-11 教訓：曾試剝句尾搭訕「給你看」，結果真歌名就叫《放個大招給你看》；
# CPU 無法區分搭訕和歌名，YT 模糊搜尋本來就容忍多餘字——寧可整串拿去搜，不要自作聰明削。）
_LEAD_QUANTITY = re.compile(r'^(?:一首|兩首|三首|點一首|來一首)')
_LEAD_MEASURE = re.compile(r'^[:：\s]+')

# 關鍵字前允許夾雜的分隔符（空白/標點），不含錨點以便嵌進 _LEAD_OK
_LEAD_SEP = r'[\s，,。.！!？?、；;：:~…\-—]*'

# 「唱」後緊接著這些字＝動詞/補語（唱歌、唱了、唱得…），不是「唱＋歌名」
_VERB_TAIL = "歌了完得過出起好著到見"

# 停用詞：抽出來也不像歌名/曲名
_INVALID = {
    "", "歌", "一首", "一首歌", "什麼", "啥", "首歌", "些什麼", "點什麼",
    "歌嗎", "歌啊", "琴", "鋼琴", "一首曲子", "曲子", "琴嗎", "琴啊", "一下",
    "點", "的", "歌了", "彈", "彈琴", "唱歌", "個歌",
}

# 泛指量詞片語（一首歌給大家聽 / 個歌 / 哪首歌…）：沒有具體曲名，交還主腦
_GENERIC = re.compile(
    r'^(?:一|個|一些|那|這|哪|幾|什麼|啥|點|首|兩|三)(?:首|個|些)?歌'
)

# 疑問起頭：幾/什/哪/誰/怎麼…抽出來必然是疑問句殘片
_BAD_START = re.compile(
    r'^(?:幾|什|啥|哪|誰|怎|為何|是否|嗎|呢|了|完|得|過|的|著|吧|啊|呀|嘿|喂|欸|喔)'
)

def _has_content_char(t: str) -> bool:
    """候選歌名含任一 Unicode 字母或數字即算實字。
    2026-10-10：不再逐區段列舉（中日韓泰俄阿…全支援），純標點/空白才算無內容。
    """
    return any(ch.isalpha() or ch.isdigit() for ch in t)

# 通用／非具名稱呼：這些不算「具體的某個人」，下游看到它們必須繼續當未知處理，
# 絕不能拿來覆寫掉已知的真名（見 piano_engine 隊列去重邏輯）。
GENERIC_REQUESTERS = frozenset({
    "", "大家", "直播間觀眾", "觀眾", "點播的人", "點歌的人",
})


def display_requester(name: Optional[str], target: str = "dad") -> str:
    """回傳可安全顯示的點播者稱呼。

    - 有誰寫誰：具名（老爸／觀眾暱稱／自訂稱呼）原樣透傳，絕不改寫。
    - 未知／通用稱呼：走中性（audience 頻道→「大家」，其餘→「點播的人」），
      絕不預設成老爸——點歌人不一定是老爸，也可能是觀眾。
    """
    n = (name or "").strip()
    if n and n not in GENERIC_REQUESTERS:
        return n
    if target == "audience":
        return "大家"
    return "點播的人"

# 句首門：關鍵字前只允許這些祈使前綴（否則＝陳述句/疑問句，交還主腦）。
# 刻意不含「老爸/大家」等第三人稱，也不含「不要/別」（否定句見 _NEG_*）。
_LEAD_TOKENS = (
    "我要聽|我想聽|我想要|幫老爸|替老爸|為老爸|幫忙|幫我|麻煩|給我|讓我|"
    "現在|馬上|立刻|接著|對了|順便|我要|我想|妳們|你們|可以|能夠|"
    r"7L|阿七|唱|彈|點歌|請|來|再|不然|就|先|好|嗯|啊|喔|哦|你|妳|聽|"
    r"[A-Za-z0-9_]+"
)
_LEAD_OK = re.compile(
    r'^(?:' + _LEAD_SEP + r'(?:' + _LEAD_TOKENS + r'))*' + _LEAD_SEP + r'$'
)

_SING_KW = re.compile(r'(?:點歌|唱)')
_PIANO_KW = re.compile(r'(?:彈琴|彈鋼琴|彈)')
_SEP = re.compile(r'^[:：\s]')
_NEG_SING = re.compile(r'(?:不|別)唱')
_NEG_PIANO = re.compile(r'(?:不|別)彈')


def _take_candidate(rest: str) -> Optional[str]:
    """從關鍵字後方的文字取出候選歌名（支援「唱：《X》」引號式與純文字式）。"""
    s = _LEAD_MEASURE.sub('', rest)
    if not s:
        return None
    if s[0] in '「『"\'“':
        for i, ch in enumerate(s[1:], 1):
            if ch in '」』"\'”':
                return s[1:i]
        s = s[1:]
    m = re.match(r'([^，。！？!?、；;：\]]+)', s)
    # ⚠️ 斷句集刻意不含半形冒號：歌名常有冒號（5:20am、Relation），切掉會把歌名切爛；
    # 全形：保留（中文解說分隔符，如「唱 晴天：超好聽」取冒號前）。
    return m.group(1) if m else None


def _title_ok(t: str) -> bool:
    """候選歌名的最終驗證。"""
    if len(t) < 2:
        return False
    if t in _INVALID:
        return False
    if _BAD_START.search(t):
        return False
    if not _has_content_char(t):
        return False
    return True


def _clean_title(raw: Optional[str]) -> Optional[str]:
    """清洗並驗證候選歌名；不合格回 None。

    順序很重要：先剝句尾語氣詞（《晴天嗎》→晴天），驗證失敗才退回原文
    （《沒離開過》必須原樣保留，絕不能被剝成「沒離開」）。
    """
    if not raw:
        return None
    t0 = _TRAIL_JUNK.sub('', raw.strip())
    if _GENERIC.search(t0):
        return None
    base = _LEAD_QUANTITY.sub('', t0).strip()
    for cand in (_TRAIL_MODAL.sub('', base), base):
        if cand and _title_ok(cand):
            return cand
    return None


def _scan(text: str, kw_re: re.Pattern, neg_re: re.Pattern) -> Optional[str]:
    """掃一輪關鍵字，回第一個合格的歌名/曲名。"""
    if not text or neg_re.search(text):
        return None
    for m in kw_re.finditer(text):
        # 閘門 A：句首門——關鍵字前只允許祈使前綴
        if not _LEAD_OK.match(text[:m.start()]):
            continue
        rest = text[m.end():]
        has_sep = bool(_SEP.match(rest))
        # 閘門 B：沒有分隔符卻緊接著動詞尾巴 → 這是動詞句（唱歌/唱了/唱得…）
        if not has_sep and rest and rest[0] in _VERB_TAIL:
            continue
        # 閘門 C：候選歌名清洗與驗證
        title = _clean_title(_take_candidate(rest))
        if title:
            return title
    return None


def extract_sing_song(text: Optional[str]) -> Optional[str]:
    """從純文字抽出點歌歌名；不是明確點歌祈使句就回 None。"""
    return _scan(text or "", _SING_KW, _NEG_SING)


def extract_piano_song(text: Optional[str]) -> Optional[str]:
    """從純文字抽出彈琴曲名；不是明確彈琴祈使句就回 None。"""
    return _scan(text or "", _PIANO_KW, _NEG_PIANO)


# 混用連接詞（彈X加唱Y / 唱X再彈Y）：兩邊都必須是乾淨歌名，否則退回單句拆解
_MIXED_SEP = r'(?:加|和|跟|與|再|還有|、|＋|\+|;|；)'
_MIXED_PATTERNS = [
    (re.compile(r'彈(.+?)' + _MIXED_SEP + r'唱(.+)', re.DOTALL),
     ("pe.play_virtual_piano", "auto_sing_song")),
    (re.compile(r'唱(.+?)' + _MIXED_SEP + r'彈(.+)', re.DOTALL),
     ("auto_sing_song", "pe.play_virtual_piano")),
]


def parse_mixed_command(text: Optional[str]) -> list:
    """混用點歌拆解：「彈晴天加唱晴天」→ [(彈琴, 晴天), (唱歌, 晴天)]。

    兩段都必須通過 _clean_title（寧可漏判不誤觸）；失敗回 []，調用方退回單句。
    不含否定句（別彈別唱一律不碰）。
    """
    s = (text or "").strip()
    if not s or _NEG_SING.search(s) or _NEG_PIANO.search(s):
        return []
    for pat, (tool1, tool2) in _MIXED_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        # 句首門：整句開頭必須是祈使（跟 _scan 同一套）
        if not _LEAD_OK.match(s[:m.start()]):
            continue
        t1 = _clean_title(_take_candidate(m.group(1)))
        t2 = _clean_title(_take_candidate(m.group(2)))
        if not t1 or not t2:
            continue
        key1 = "song_name"
        return [(tool1, {key1: t1}), (tool2, {key1: t2})]
    return []


def parse_hard_command(text: Optional[str]) -> Tuple[Optional[str], Dict]:
    """B 架構入口：把純文字拆成 (工具名, 參數)。

    只認點歌（唱歌/彈琴）。表情不歸 CPU（交還主腦/A 架構，避免誤觸搶戲）。
    混用句（彈X加唱Y）走 parse_mixed_command，不在這裡處理。
    回 (None, {}) 代表無硬指令，交還主腦（絕不在此呼叫任何 API）。
    """
    song = extract_sing_song(text)
    if song:
        return "auto_sing_song", {"song_name": song}
    song = extract_piano_song(text)
    if song:
        return "pe.play_virtual_piano", {"song_name": song}
    return None, {}


# 唱歌/麥克風/話筒刻意排除：麥克風由翻唱管線自動管理，手動會打架
# （_RESET_NAMES 給 build_slip_text 表情紙條用；表情本體走主腦/A 架構，不歸 CPU）
_RESET_NAMES = {"正常", "重置", "預設", "恢復", "_RESET_"}


# —— 搜尋消毒（2026-10-10 直播事故：腦輸出幾 MB base64 音訊被當搜尋關鍵字）——
# 超過 200 字元的連續 base64 與 data: URI 在人類口語裡永遠不會合法出現。
_BLOB_URI_RE = re.compile(r'data:[^,]{0,120},(?:base64,)?[A-Za-z0-9+/=]{200,}')
_BLOB_RUN_RE = re.compile(r'[A-Za-z0-9+/=]{200,}')
_TAG_SHELL_RE = re.compile(r'<[^<>]{1,300}>')


def strip_blob_noise(text: Optional[str]) -> str:
    """拔掉 data: URI、超長 base64 串與 HTML 標籤殘骸；一般文字原樣返回。"""
    if not text:
        return ""
    s = _BLOB_URI_RE.sub('', text)
    s = _BLOB_RUN_RE.sub('', s)
    # 拔完 blob 常殘留 <audio src=""> 之類的殼；口語輸出永遠不會有合法標籤
    s = _TAG_SHELL_RE.sub('', s)
    return s


def sanitize_search_query(text: Optional[str], limit: int = 120) -> str:
    """搜尋關鍵字消毒：去 blob → 去首尾空白 → 截斷；太短回空字串（呼叫方直接跳過不搜）。"""
    s = strip_blob_noise(text).strip()
    if len(s) < 2:
        return ""
    return s[:limit].strip()


_SLIP_PREFIX_RE = re.compile(r'^\[[^\]]*\]\s*[^：:]*[：:]\s*')

# 🛟 救援認領簿：歌名 -> 認領時間。同首窗口內只救一次——失敗丟棄也不重救，
# 否則去重鍵消失後下次重連再救，斷線風暴時無限循環（2026-10-11「3aя\n請妳綜合上述留言」事件）。
RESCUE_SONG_WINDOW_SEC = 120.0
_RESCUED_SONG_TS = {}


def rescue_claim(song: str, now=None, window: float = RESCUE_SONG_WINDOW_SEC) -> bool:
    """救援認領：回 True 代表這次可以救（並記帳）；同首窗口內重複來直接擋掉。"""
    import time as _t
    now = now if now is not None else _t.time()
    k = (song or "").strip().lower()
    if not k:
        return False
    if now - _RESCUED_SONG_TS.get(k, 0.0) < window:
        return False
    _RESCUED_SONG_TS[k] = now
    return True

def parse_slip_for_song(prompt: Optional[str]):
    """從紙條還原點歌指令（斷線救援用）：剝掉紙條前綴後走 CPU 拆解。

    背景：紙條送達後 session 若立刻死亡，主腦永遠看不到它（佇列只重發
    「發送失敗」的，不重發「送達了但腦沒處理」的）。2026-10-09 直播事故：
    「唱 5:20am」的紙條就這樣丟了。
    只認點歌（回 (tool, args)），其餘一律 (None, {})——含剝不出原文的、
    系統紙條（CPU/謝幕/失敗通知，點歌動詞都在非祈使位置自然落榜）。
    """
    text = (prompt or "").strip()
    if not text:
        return None, {}
    msg = _SLIP_PREFIX_RE.sub('', text, count=1)
    if not msg or msg == text:
        return None, {}
    # 2026-10-11 救援死亡循環：哨兵紙條夾帶多行 board_context（觀眾原文＋「請妳綜合上述留言…」），
    # 剝一層後殘留換行，會抽出「歌名＋指令殘渣」這種垃圾歌（如「3aя\n請妳綜合上述留言」）；
    # 失敗丟棄後去重失效，下次重連再救→無限循環。救援只認單行，直覺上點歌都是一句話。
    if "\n" in msg or "\r" in msg:
        return None, {}
    tool, args = parse_hard_command(msg)
    if tool not in ("auto_sing_song", "sing_song"):
        # 混用句（彈X加唱Y）：只救唱歌那路，鋼琴爛名不碰
        for t, a in parse_mixed_command(msg):
            if t in ("auto_sing_song", "sing_song") and (a or {}).get("song_name"):
                return t, a
        return None, {}
    if not (args or {}).get("song_name"):
        return None, {}
    return tool, args


def build_slip_text(fn_name: str, fn_args: Dict, requester_name: str,
                    via: str = "透過硬體直連") -> str:
    """給 Live 主腦的紙條（黑板同步）。

    ⚠️ 唱歌/彈琴的紙條必須寫明「演唱者/彈奏者是 7L 本人」，點歌人只是開口點歌。
    舊文案「已成功幫{老爸}執行了 auto_sing_song」曾讓主腦回觀眾「我老爸有唱一首」，
    其實整首都是 7L 唱的（2026-10-09 直播事故）。
    ⚠️ 點歌人不一定是老爸（可能是觀眾點的）：requester_name 有誰寫誰，
    沒給／未知就中性寫「點歌的人」，絕不預設成老爸；也不用「他」（點歌人可能是女生）。
    """
    args = fn_args or {}
    who = (requester_name or "").strip()
    if fn_name in ("auto_sing_song", "sing_song"):
        song = args.get("song_name", "")
        if who:
            return (f"[系統底層：收到{who}的點歌請求，7L 已在背景排程演唱《{song}》。"
                    f"【演唱者是妳 7L 本人】{who}只是開口點歌、並沒有親自演唱。"
                    f"台上若有歌會自動排隊接唱、背景準備照做不間斷；"
                    f"請妳現在只需要負責口頭答應、順著話題接話即可。]")
        return (f"[系統底層：收到點歌請求，7L 已在背景排程演唱《{song}》。"
                f"【演唱者是妳 7L 本人，不是點歌的人】"
                f"台上若有歌會自動排隊接唱、背景準備照做不間斷；"
                f"請妳現在只需要負責口頭答應、順著話題接話即可。]")
    if fn_name in ("pe.play_virtual_piano", "play_virtual_piano"):
        song = args.get("song_name", "")
        if who:
            return (f"[系統底層：收到{who}的點曲請求，7L 正在背景彈奏《{song}》。"
                    f"【彈琴的是妳 7L 本人】{who}只是點曲、並沒有親自彈奏。"
                    f"請妳現在只需要負責口頭答應、順著話題接話即可，鋼琴已在背景執行。]")
        return (f"[系統底層：收到點曲請求，7L 正在背景彈奏《{song}》。"
                f"【彈琴的是妳 7L 本人，不是點曲的人】"
                f"請妳現在只需要負責口頭答應、順著話題接話即可，鋼琴已在背景執行。]")
    if fn_name == "trigger_vts_expression":
        exp = (args.get("expression_name", "") or "").strip()
        done = "表情已重置為自然狀態" if exp in _RESET_NAMES or exp == "_RESET_" else f"表情已切換為{exp}"
        if who:
            return (f"[系統底層：收到{who}的表情請求，{done}。"
                    f"【做表情的是妳 7L 本人】請妳口頭答應一聲即可，"
                    f"絕對不要重複下達表情指令（重複會把剛開的表情關掉）。]")
        return (f"[系統底層：收到表情請求，{done}。"
                f"【做表情的是妳 7L 本人】請妳口頭答應一聲即可，"
                f"絕對不要重複下達表情指令（重複會把剛開的表情關掉）。]")
    if who:
        return (f"[系統底層：已成功幫{who}{via}執行了 {fn_name} 指令，參數：{args}。"
                f"請妳現在只需要負責口頭答應、順著話題接話即可，程式指令已在背景執行。]")
    return (f"[系統底層：已{via}執行了 {fn_name} 指令，參數：{args}。"
            f"請妳現在只需要負責口頭答應、順著話題接話即可，程式指令已在背景執行。]")
