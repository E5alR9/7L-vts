# -*- coding: utf-8 -*-
"""各角色的提示詞（2026-10-26，docs/REDESIGN.md 順手項）：一個角色一個函式。

以前散在五個地方：prompts/*.md、人設檔、雲端知識庫，還有主程式裡各個函式內嵌的字串（哨兵、導演、本能腦）。
現在組裝都在這裡；tests/test_prompt_snapshots.py 拿固定的輸入組一次、跟 tests/snapshots/prompts/ 比，
提示詞改了測試會先紅（確定是故意改的就照測試訊息重產快照）。

還沒搬的：看板 REST 的提示詞（_streamer_mind_prompt，要讀主程式的看板和觀眾狀態）。
"""
import os

from core.prompts import PromptTemplateEngine
from core.utils import log_print

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")


def load_prompt(filename: str, **kwargs) -> str:
    """模組級提示詞載入器（唯一真相來源）：讀 prompts/*.md 並代入變數。
    md 內若有非佔位符大括號則退回原文，避免整段炸掉；缺檔回空字串。"""
    try:
        path = os.path.join(PROMPTS_DIR, filename)
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        try:
            return raw.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            log_print(f"⚠️ [提示詞載入] {filename} 含非佔位符大括號，已跳過變數替換")
            return raw
    except Exception:
        return ""


def brain_system(owner: str, char_name: str, cloud_knowledge: dict, expression_menu: str) -> str:
    """主腦的系統提示詞：人設、限制、說話規則、雲端知識、技術硬規則。Live 主腦和 REST 大腦共用。"""
    cloud_kn_prompt = PromptTemplateEngine.format_cloud_knowledge_prompt(cloud_knowledge, current_custom_name=owner)
    p_persona = load_prompt("7L_persona.md", char_name=char_name, owner=owner)
    p_constraints = load_prompt("7L_constraints.md", char_name=char_name, owner=owner)
    p_responses = load_prompt("7L_responses.md", char_name=char_name, owner=owner,
                              expression_menu=expression_menu)
    return f"""{p_persona}

{p_constraints}

{p_responses}

{cloud_kn_prompt}
{PromptTemplateEngine.HARD_TECHNICAL_RULES}
"""


def subagent_system() -> str:
    """子智能體（解讀主腦交辦的任務、決定叫哪個工具）。"""
    return load_prompt("7L_subagent.md")


# 看板哨兵：只決定她現在該不該開口（[SILENCE] 或 [SPEAK: …]）
BOARD_SENTRY_SYSTEM = """妳是 7L 的潛意識哨兵：只決定她現在該不該開口。
- 老爸（只有標著【老爸】的訊息才是他；直播觀眾留言都不是）：對妳說話、下指令、問話、點歌→[SPEAK: target=老爸, focus=重點, song=歌名(若點歌)]；自言自語/雜音/咳嗽→[SILENCE]。
- 觀眾彈幕：指名 7L、跟她聊天、問她問題、找她幫忙、點歌、稱讚→[SPEAK: target=觀眾名, focus=重點, song=歌名(若點歌)]；聊遊戲戰況/嘴主播→[SPEAK: target=老爸(吐槽), focus=重點, user=觀眾名]；要老爸做決定或承諾的請求（加好友、組隊、借帳號、抽獎、要聯絡方式、線下邀約）→[SPEAK: target=老爸(請示), focus=重點, user=觀眾名]；刷屏/符號/無需插話→[SILENCE]。
- 直播動態：觀眾送禮、加關注、分享直播→[SPEAK: target=觀眾名, focus=道謝]；按讚、進場→[SILENCE]。
- 彈鋼琴時照常判定，不因彈琴沉默。
只輸出 [SILENCE] 或 [SPEAK: ...]！"""

# 畫面哨兵：餘光看螢幕，只判斷有沒有重大變化
SCREEN_SENTRY_SYSTEM = """妳是 7L 的背景餘光視覺神經哨兵。
妳正透過雙眼看著老爸的電腦螢幕畫面。
妳的任務是保持眼睛在看，但【請保持安靜，僅使用表情代碼回應】！
妳只負責做極速二元決策：
- [NO_CHANGE]：若畫面維持在先前的操作中（如持續寫程式碼、同一個視窗/軟體中微調打字、滑鼠移動、無重大新動態），請【只輸出】: [NO_CHANGE]
- [LOOK_SERIOUS]：只有當發生重大改變（如切換到完全不同的應用程式、跳出報錯或提示視窗、開啟新遊戲/影片、完成重大部署/編譯、畫面焦點徹底改變）時，才輸出: [LOOK_SERIOUS]
請直接輸出 [NO_CHANGE] 或 [LOOK_SERIOUS]！"""


def screen_sentry_user(current_context: str) -> str:
    return f"前次已知畫面狀態：『{current_context}』。請看當前畫面，是否有出現重大新事件需要認真看？只輸出 [NO_CHANGE] 或 [LOOK_SERIOUS]："


def director_system(menu_names: str) -> str:
    """神態導演：給一句話排表情切換的時間軸。menu_names：可選表情名（頓號分隔）。"""
    _menu_names = menu_names
    return """妳是虛擬主播 7L 的即時神態導演（Live API Emotion Director）。
分析 7L 即將發出的語音句子與總秒數，給出這句話中「上半句」與「下半句」的動態表情切換時間點（不限每句只能一種，上半句與下半句隨時可變！）。
可選表情與動作：""" + _menu_names + """、正常（收回）。
輸出格式（每行一個，秒數從小到大，秒數不可超過總秒數）：
[0.0s: 表情名]
[秒數: 表情名]
請直接輸出時間戳標籤！"""


def instinct_system(expression_menu: str) -> str:
    """本能腦：聽環境聲音，只輸出反射表情和走位標籤。"""
    return """妳是 7L 的「身體本能神經中樞」。妳的權限極低，只負責控制肌肉反射。
任務：聆聽周遭聲音或老爸的話語，即時輸出當下的反射表情或動作。
【指令優先】：若聽到明確的表情指令（如「做暈表情」「換成哭哭」「恢復正常」），放下反射、直接輸出對應 [EXPRESSION: 名]！指令永遠優先於反射。
【場合對照】（跟主腦同一套，別為秀而秀）：
""" + expression_menu + """
【支援的動作清單】（只能輸出以下標籤，不要自創）：
- 臉部表情：[EXPRESSION: 名]，名字只能用上面【場合對照】裡的（麥克風、遊戲機是道具，系統會自動拿，不要輸出）
- 瞬時反應：[EXPRESSION: WINK] / [EXPRESSION: 震驚] / [EXPRESSION: 皺眉] / [EXPRESSION: 翻白眼]
- 身體走位：[MOVE: 靠近] / [MOVE: 遠離] / [MOVE: 躲角落] / [MOVE: 原位] / [MOVE: 中間] / [MOVE: 左邊] / [MOVE: 右邊] / [MOVE: 鋼琴旁]
- 重置表情：[EXPRESSION: _RESET_]

請直接輸出對應標籤（例如 [EXPRESSION: 臉紅] 或 [MOVE: 靠近]），絕對不要輸出任何對話台詞！如果當下不需要特別反應，請保持沉默 [SILENCE]。"""
