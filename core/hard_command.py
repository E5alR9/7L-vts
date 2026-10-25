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
import os
import re
from typing import Dict, Optional, Tuple

_TRAIL_JUNK = re.compile(r'[?？!！。，,、；;：:\s~～…]+$')
# 句尾語氣詞（可安全剝除：真實歌名幾乎不會以這些字結尾）
_TRAIL_MODAL = re.compile(r'(?:嗎|嘛|啊|吧|呢|喔|哦|呀|啦|嘿|哟|哈|唄|噢|喲|唷)+$')
# ⚠️ 體貌字（了/完/過）**常常就在歌名裡**（《沒離開過》《錯過》《散了》），
# 而且字面上無法和「唱晴天了」區分——一律不剝，避免把真歌名削壞。
# （2026-10-11 教訓：曾試剝句尾搭訕「給你看」，結果真歌名就叫《放個大招給你看》；
# CPU 無法區分搭訕和歌名，YT 模糊搜尋本來就容忍多餘字——寧可整串拿去搜，不要自作聰明削。）
# 例外只有「給我聽」這種聽眾補語（2026-10-24：「彈一首小星星給我聽」→ 應答念成「小星星給我聽交給我」）：
# 點歌句幾乎都這樣講；剝完不合格就退回原文，《唱歌給你聽》剝成「唱歌」是停用詞，照樣保留原名。
_TRAIL_LISTENER = re.compile(r'給(?:我|你|妳|您|大家|老爸|我們|你們|妳們)聽(?:聽|一下)?$')
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
# 「彈奏」要整個當關鍵字：只認「彈」的話「彈奏 小星星」會抽出「奏 小星星」（2026-10-24 實機）
_PIANO_KW = re.compile(r'(?:彈琴|彈鋼琴|彈奏|彈)')
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
    no_modal = _TRAIL_MODAL.sub('', base)
    no_listener = _TRAIL_JUNK.sub('', _TRAIL_LISTENER.sub('', no_modal))
    if not no_listener:
        return None  # 「唱給我聽」「彈琴給我聽」：只有聽眾補語、沒有歌名，交還主腦
    for cand in (no_listener, no_modal, base):
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


_ASK_DESKTOP_RE = re.compile(
    r'^\s*(?:請|幫我|幫|來|給我|替我|\s)*問(?:一下)?\s*gemini(?![A-Za-z0-9_])\s*[:：]?\s*(.+)$',
    re.IGNORECASE | re.DOTALL)

# —— 點播看片（2026-10-25）——
# 貼 YouTube 連結叫她看，主腦常只嘴上說「我這就去看」卻沒呼叫工具（實機），CPU 直接接。
# 要有連結＋「看／點播」才算：光貼連結不算，觀眾洗連結不會讓她一直下載影片。
_YT_URL_RE = re.compile(
    r'(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?\S*?v=|shorts/|live/|embed/)|youtu\.be/)'
    r'([A-Za-z0-9_\-]{11})[^\s，。！？、]*', re.IGNORECASE)
_WATCH_INTENT_RE = re.compile(r'看|點播')
# 「我剛看完 <連結>」「看過了」是在聊天；「幫我看完這部」才是要她看
_NEG_WATCH = re.compile(r'(?:不|別)(?:要|用)?(?:看|點播)|(?:剛|已經?|有)看(?:完|過)|看(?:過|完了|了)')


def extract_watch_url(text: Optional[str]) -> Optional[str]:
    """「幫我看這部 https://youtu.be/xxx」→ https://youtu.be/<ID>；沒有看片意圖或是否定句回 None。"""
    s = text or ""
    m = _YT_URL_RE.search(s)
    if not m:
        return None
    rest = s[:m.start()] + " " + s[m.end():]
    if _NEG_WATCH.search(rest) or not _WATCH_INTENT_RE.search(rest):
        return None
    # 統一成 youtu.be/<ID>：主腦常換個網址寫法再呼叫一次子智能體，寫法一樣去重才擋得住
    return f"https://youtu.be/{m.group(1)}"


def extract_ask_desktop(text: Optional[str]) -> Optional[str]:
    """桌機助手關鍵字（B 架構，2026-10-11）：問Gemini＋問題，回問題文本。
    錨定句首（「唱一首問Gemini的歌」這種不搶唱歌的）。零 API，純正則。"""
    if not text:
        return None
    m = _ASK_DESKTOP_RE.match(text.strip())
    if not m:
        return None
    q = m.group(1).strip().strip('？?！!。，,、；;：:～~…')
    if len(q) < 2 or not _has_content_char(q):
        return None
    return q


def extract_piano_song(text: Optional[str]) -> Optional[str]:
    """從純文字抽出彈琴曲名；不是明確彈琴祈使句就回 None。"""
    return _scan(text or "", _PIANO_KW, _NEG_PIANO)


# 混用連接詞（彈X加唱Y / 唱X再彈Y）：兩邊都必須是乾淨歌名，否則退回單句拆解。
# 主腦轉述時會寫「彈鋼琴 X 並唱歌 Y」：舊規則不認「並」，單句拆解把「X 並唱歌 Y」整串當曲名
# 上網搜譜，蓋掉彈唱同步用的譜（2026-10-25 實機）。所以動詞後的「鋼琴／琴／奏」「歌」也要吃掉。
_MIXED_SEP = r'\s*(?:並且|並|然後|同時|順便|接著|加|和|跟|與|再|還有|、|＋|\+|;|；)\s*'
_MIXED_PIANO = r'彈(?:鋼琴|琴|奏)?\s*'
_MIXED_SING = r'唱(?:歌(?=[\s「『《"“]))?\s*'
_MIXED_PATTERNS = [
    (re.compile(_MIXED_PIANO + r'(.+?)' + _MIXED_SEP + _MIXED_SING + r'(.+)', re.DOTALL),
     ("pe.play_virtual_piano", "auto_sing_song")),
    (re.compile(_MIXED_SING + r'(.+?)' + _MIXED_SEP + _MIXED_PIANO + r'(.+)', re.DOTALL),
     ("auto_sing_song", "pe.play_virtual_piano")),
]
# 同一首邊彈邊唱：「自彈自唱 X」「邊彈邊唱 X」「一邊彈琴一邊唱 X」「彈唱 X」
# 「彈唱」後面要隔開才算（「彈唱歌手很厲害」是在聊天）
_MIXED_SAME = re.compile(r'(?:自彈自唱|邊彈邊唱|一邊彈(?:鋼琴|琴)?一邊唱(?:歌)?|彈唱(?=[\s:：「『《"“]))\s*(.+)', re.DOTALL)


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
    m = _MIXED_SAME.search(s)
    if m and _LEAD_OK.match(s[:m.start()]):
        t = _clean_title(_take_candidate(m.group(1)))
        if t:
            return [("pe.play_virtual_piano", {"song_name": t}), ("auto_sing_song", {"song_name": t})]
    return []


# —— 自創曲音軌庫（Lyria 桌面版手動生成，存檔視窗直存這裡）——
ORIGINALS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "songs_library", "originals")
_ORIG_PREFIX_RE = re.compile(r'^(自創曲|原創)\s*[:：、，,]?\s*(.+)$', re.DOTALL)


def _norm_name(t: str) -> str:
    """檔名歸一化：只留字母數字（My_Favorite_Mod == My Favorite Mod）。"""
    return "".join(ch.lower() for ch in (t or "") if ch.isalnum())


def find_original_song_file(title: str) -> str:
    """在 originals/ 找 MP3/WAV（檔名歸一化比對）。回絕對路徑或 ""。純檔案系統操作，零 API。"""
    try:
        os.makedirs(ORIGINALS_DIR, exist_ok=True)
        want = _norm_name(title)
        if not want:
            return ""
        for f in os.listdir(ORIGINALS_DIR):
            if not f.lower().endswith((".mp3", ".wav")):
                continue
            if _norm_name(os.path.splitext(f)[0]) == want:
                return os.path.join(ORIGINALS_DIR, f)
    except Exception:
        pass
    return ""


def split_original_request(title: str):
    """自創曲分流（2026-10-11 改：有檔＝意圖，不用前綴）。
    「唱X」＋ originals/X.mp3 存在 → 自創曲管線；沒檔 → YouTube 翻唱（舊行為）。
    「唱自創曲X」前綴保留：顯示乾淨＋缺檔時有專屬文案（請老爸丟檔）。
    回 (歌名, 音軌路徑或"", is_original)。無檔普通點歌穿透，絕不劫持。"""
    t = (title or "").strip().strip('「」『』《》')
    m = _ORIG_PREFIX_RE.match(t)
    if m:
        clean = m.group(2).strip().strip('「」『』《》')
        if not clean:
            return title, "", False
        return clean, find_original_song_file(clean), True
    if not t:
        return title, "", False
    src = find_original_song_file(t)
    return t, src, bool(src)


# —— 鋼琴控制：停止／暫停／繼續（2026-10-24）——
# 主腦常只嘴上說「停下囉」卻沒呼叫工具，副腦判定又要 5 秒；這幾句很固定，CPU 直接接。
# 整句去掉句尾語氣和標點後，結尾必須剛好是下面某一句、前面只能是祈使前綴（同句首門）：
# 「他說別彈了」「不要停止彈琴」「繼續彈小星星」一律不攔，交還主腦。
_PIANO_OBJ = r'(?:彈琴|彈鋼琴|鋼琴|演奏|彈奏)'
_PIANO_CONTROLS = (
    ("pe.stop_virtual_piano", re.compile(
        r'(?:(?:停止|停掉|關掉|收起|收掉)' + _PIANO_OBJ + r'|(?:別|不要|不用)再?彈了|鋼琴(?:停止|停掉|關掉|收起來))了?$')),
    ("pe.pause_virtual_piano", re.compile(r'(?:暫停' + _PIANO_OBJ + r'|鋼琴暫停)了?$')),
    ("pe.resume_virtual_piano", re.compile(r'(?:繼續(?:彈|' + _PIANO_OBJ + r')|鋼琴繼續)了?$')),
)
PIANO_CONTROL_TOOLS = frozenset(t for t, _ in _PIANO_CONTROLS)

# —— 翻唱控制：停止唱歌（2026-10-25）——
# 以前只有鋼琴有 CPU 直接接；「停止唱歌」沒人接，交給子智能體又被解讀成點一首叫《停止》的歌（實機）。
# 規則同鋼琴：句尾剛好是這幾句、前面只能是祈使前綴；「他說別唱了」「不要停止唱歌」不攔。
_SING_OBJ = r'(?:唱歌|翻唱|演唱|唱)'
_SING_CONTROLS = (
    ("stop_singing", re.compile(
        r'(?:(?:停止|停掉|先停|關掉)' + _SING_OBJ + r'|(?:別|不要|不用)再?唱了|不唱了|歌(?:先)?(?:停|停掉|停止)(?:一下|下來)?)了?$')),
)
SING_CONTROL_TOOLS = frozenset(t for t, _ in _SING_CONTROLS)
STAGE_CONTROL_TOOLS = PIANO_CONTROL_TOOLS | SING_CONTROL_TOOLS   # 只聽老爸的（觀眾一句「別唱了」不能把歌停掉）
# 副腦／派發器收到的工具名可能沒有 pe. 前綴、或是舊別名，比對前先統一
_STAGE_CONTROL_NAMES = frozenset(t.split(".")[-1] for t in STAGE_CONTROL_TOOLS) | {"stop_singing_song", "stop_cover"}


def is_stage_control(fn_name: Optional[str]) -> bool:
    """鋼琴停止／暫停／繼續、停止唱歌（含 pe. 前綴、大小寫、舊別名）→ True。"""
    return (fn_name or "").strip().lower().split(".")[-1] in _STAGE_CONTROL_NAMES


def extract_piano_control(text: Optional[str], controls=_PIANO_CONTROLS) -> Optional[str]:
    """停止／暫停／繼續鋼琴的祈使句 → 工具名；其他回 None。controls 換成 _SING_CONTROLS 就是翻唱控制。"""
    s = (text or "").strip()
    for _ in range(2):  # 「別彈了啦！」：標點和語氣詞可能交錯
        s = _TRAIL_MODAL.sub('', _TRAIL_JUNK.sub('', s))
    if not s:
        return None
    for tool, pat in controls:
        m = pat.search(s)
        if m and _LEAD_OK.match(s[:m.start()]):
            return tool
    return None


# —— 主腦填的結構化舞台動作（2026-10-25）——
# 主腦以前只能丟一句自由文字給子智能體，CPU 再用正則猜她轉述的說法：
# 「唱歌 Faded」「背景彈唱 Faded」「彈鋼琴 Faded 並唱歌 Faded」都得一條條補正則，猜不到就交 AI 重新解讀
# （較慢，也曾把〈安靜〉判成收鋼琴）。現在她呼叫時直接填 action＋歌名／網址，這裡照欄位轉成工具，不再解析。
STAGE_ACTIONS = ("play_piano", "sing", "play_and_sing", "stop_singing",
                 "stop_piano", "pause_piano", "resume_piano", "watch_video")


def _clean_brain_title(t) -> str:
    t = str(t or "").strip().strip("《》「」『』\"'“”〈〉 ")
    return t if t and len(t) <= 80 and _has_content_char(t) else ""


def structured_stage_command(action: str = "", song: str = "", song2: str = "", url: str = "", **_) -> list:
    """主腦填的結構化動作 → [(工具名, 參數), ...]；不是舞台動作或缺必要欄位回 []（照舊走文字流程）。"""
    a = (action or "").strip().lower()
    t1 = _clean_brain_title(song)
    t2 = _clean_brain_title(song2) or t1
    if a == "play_piano" and t1:
        return [("pe.play_virtual_piano", {"song_name": t1})]
    if a == "sing" and t1:
        return [("auto_sing_song", {"song_name": t1})]
    if a == "play_and_sing" and t1:
        return [("pe.play_virtual_piano", {"song_name": t1}), ("auto_sing_song", {"song_name": t2})]
    if a == "stop_singing":
        return [("stop_singing", {})]
    if a in ("stop_piano", "pause_piano", "resume_piano"):
        return [(f"pe.{a.split('_')[0]}_virtual_piano", {})]
    if a == "watch_video":
        m = _YT_URL_RE.search(str(url or ""))
        if m:
            return [("video.request_watch", {"url": f"https://youtu.be/{m.group(1)}"})]
    return []


# —— 主腦自己要彈／唱時，剛才那句話得真的有在點歌（2026-10-26）——
# Live 續接的對話裡留著以前的點歌：老爸說「7L 醒醒」她去彈小星星，觀眾問「還醒著嗎」她唱晴天。
PLAY_TOOLS = frozenset({"pe.play_virtual_piano", "play_virtual_piano", "auto_sing_song", "sing_song"})
_MUSIC_INTENT_RE = re.compile(r"彈|弹|唱|歌|琴|曲|音樂|音乐|演奏|表演|才藝|才艺|來一首|来一首|再來|再来|安可|想聽|想听"
                              r"|piano|sing|song|music|encore", re.I)
_AGREE_RE = re.compile(r"好|可以|要|嗯|對|对|來|来|行|沒問題|没问题|當然|当然|隨便|随便|你決定|妳決定|ok|yes|sure|go", re.I)


def stage_request_unasked(said: str, songs=(), her_last: str = "") -> bool:
    """剛才那句話沒人點歌 → True（主腦是翻舊帳，不要執行）。
    said：觸發這輪的人話（老爸打字／說話、觀眾留言）；看不到（空字串）就放行。
    her_last：她在那句話之前講的話——她問「要不要我彈小星星？」老爸回「好啊」也算點了。"""
    s = (said or "").strip()
    if not s:
        return False
    if _MUSIC_INTENT_RE.search(s):
        return False
    ns = _norm_name(s)
    if any(_norm_name(t) and _norm_name(t) in ns for t in songs or ()):
        return False
    if len(s) <= 15 and _AGREE_RE.search(s) and _MUSIC_INTENT_RE.search(her_last or ""):
        return False
    return True


def parse_hard_command(text: Optional[str]) -> Tuple[Optional[str], Dict]:
    """B 架構入口：把純文字拆成 (工具名, 參數)。

    只認點歌（唱歌/彈琴）、鋼琴的停止／暫停／繼續、停止唱歌、貼 YouTube 連結點播看片。表情不歸 CPU（交還主腦/A 架構，避免誤觸搶戲）。
    混用句（彈X加唱Y）走 parse_mixed_command，不在這裡處理。
    桌機助手（問Gemini）最優先判定：顯式問句不跟唱歌搶。
    回 (None, {}) 代表無硬指令，交還 A 架構（Live 主腦 → invoke_subagent → NV 解讀）。
    """
    ask = extract_ask_desktop(text)
    if ask:
        return "ask_desktop", {"question": ask}
    url = extract_watch_url(text)
    if url:
        return "video.request_watch", {"url": url}
    control = extract_piano_control(text) or extract_piano_control(text, _SING_CONTROLS)
    if control:
        return control, {}
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
        if (args.get("origin") or "") == "original":
            # 自創曲：紙條帶【自創曲】標記（主腦才會說「原創」不說「點歌」；
            # 斷線救援認這個標記撿回，不走 YouTube）。檔沒到就直說，別排程。
            if not (args.get("source_mp3") or ""):
                return (f"[系統底層：有人點自創曲《{song}》，但 MP3 還沒丟進 songs_library/originals。"
                        f"請妳直接跟大家說這首還沒生好、請老爸生好丟進來再點，不要說排程了。]")
            if who:
                return (f"[系統底層：收到{who}的自創曲請求，7L 已在背景排程演唱自創曲《{song}》。"
                        f"【演唱者是妳 7L 本人】{who}只是開口點歌、並沒有親自演唱。"
                        f"台上若有歌會自動排隊接唱、背景準備照做不間斷；"
                        f"請妳現在只需要負責口頭答應（記得說這是自創曲／原創）、順著話題接話即可。]")
            return (f"[系統底層：收到自創曲請求，7L 已在背景排程演唱自創曲《{song}》。"
                    f"【演唱者是妳 7L 本人，不是點歌的人】"
                    f"台上若有歌會自動排隊接唱、背景準備照做不間斷；"
                    f"請妳現在只需要負責口頭答應（記得說這是自創曲／原創）、順著話題接話即可。]")
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
    if fn_name == "video.request_watch":
        # 不寫連結：主腦會把網址一個字一個字念出來
        return (f"[系統底層：{who or '有人'}點播的影片已排進看片隊列，7L 會在背景看完再說內容。"
                f"請妳口頭答應一聲就好，還沒看完之前不要猜影片在講什麼。]")
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
    # 不寫原始工具名和參數字典（主腦可能照念出 pe.play_virtual_piano {'song_name': …}），改寫中文
    label = _TOOL_LABELS.get(fn_name, "處理交代的事")
    detail = "、".join(str(v).strip() for v in args.values()
                      if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip())[:60]
    detail = f"（{detail}）" if detail else ""
    if who:
        return (f"[系統底層：已成功{via}幫{who}{label}{detail}。"
                f"請妳現在只需要負責口頭答應、順著話題接話即可，程式指令已在背景執行。]")
    return (f"[系統底層：已{via}{label}{detail}。"
            f"請妳現在只需要負責口頭答應、順著話題接話即可，程式指令已在背景執行。]")


_TOOL_LABELS = {
    "search_google": "上網搜尋",
    "search_knowledge": "查知識庫",
    "set_timer": "設定計時提醒",
    "generate_ai_image": "畫圖",
    "move_spatial_position": "移動位置",
    "open_virtual_piano": "打開鋼琴",
    "pe.play_midi_band": "樂團演奏",
    "pe.compose_and_play_original_piano": "即興作曲彈奏",
    "video.request_watch": "看影片",
    "music.generate_song": "生成歌曲",
    "midi.inspect": "查看樂譜",
    "midi.edit": "修改樂譜",
    "music.transcribe_song": "扒譜",
    "music.stem_pack": "分離音軌",
    "pe.mashup_virtual_piano": "鋼琴串燒",
    "pe.insert_virtual_piano": "插播鋼琴曲",
    "pe.pause_virtual_piano": "暫停鋼琴",
    "pe.resume_virtual_piano": "繼續彈鋼琴",
    "pe.stop_virtual_piano": "停止鋼琴",
    "stop_singing": "停止唱歌",
    "list_piano_sheets": "列出鋼琴曲目",
    "set_piano_volume": "調整鋼琴音量",
    "set_piano_speed": "調整鋼琴速度",
    "set_piano_instrument": "換鋼琴音色",
    "control_microphone": "控制麥克風",
    "clear_all_memories": "清除記憶",
    "update_cloud_knowledge": "更新雲端知識",
}
