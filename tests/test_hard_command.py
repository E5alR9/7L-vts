# -*- coding: utf-8 -*-
"""core.hard_command — CPU 硬指令拆解精度（2026-10-09 直播誤觸回歸）"""
from conftest import ROOT  # noqa: F401
from core.hard_command import (
    extract_sing_song, extract_piano_song, parse_hard_command, parse_mixed_command,
    build_slip_text,
    display_requester, parse_slip_for_song, rescue_claim, _RESCUED_SONG_TS,
    strip_blob_noise, sanitize_search_query,
)

# --- 真實直播誤觸案例：一律不得攔截 ---
FALSE_POSITIVES = [
    "你可以唱歌了？",            # 觀眾疑問句 → 舊版抽出「歌了？」並真的開跑
    "? 又我唱了????",           # 老爸疑問句 → 舊版抽出「了????」
    "送出了 1 個 Treasure Clover！請向他熱情道謝並給予即時互動！",
    "他唱歌很好聽耶",
    "我今天不想唱歌",
    "你會唱幾首？",
    "唱一首歌給大家聽就好",      # 泛指，無具體歌名 → 交還主腦
    "別唱了啦",
    "不要唱那首",
    "他彈琴比我還快",
    "你可以彈琴了？",
    "唱首歌",
    "唱",
    "點歌",
]


def test_false_positives_never_fire():
    for t in FALSE_POSITIVES:
        tool, args = parse_hard_command(t)
        assert tool is None, f"誤觸：{t!r} → {tool}{args}"


# --- 合法點歌/點曲：必須照常命中 ---
TRUE_POSITIVES = [
    ("唱 Distrion - Alibi (ft. Heleen)", "auto_sing_song", "Distrion - Alibi (ft. Heleen)"),
    ("唱 晴天", "auto_sing_song", "晴天"),
    ("點歌 晴天", "auto_sing_song", "晴天"),
    ("點歌：加州旅館", "auto_sing_song", "加州旅館"),
    ("幫我唱 七里香", "auto_sing_song", "七里香"),
    ("唱「夜曲」", "auto_sing_song", "夜曲"),
    ("唱一首 向天再借五百年", "auto_sing_song", "向天再借五百年"),
    # 體貌字結尾的真歌名：絕不能被剝成「沒離開」「錯」「散」
    ("彈 沒離開過", "pe.play_virtual_piano", "沒離開過"),
    ("點歌 錯過", "auto_sing_song", "錯過"),
    ("唱 散了", "auto_sing_song", "散了"),
    # 句尾語氣詞則要剝乾淨
    ("點歌 晴天吧", "auto_sing_song", "晴天"),
    ("現在唱 晴天", "auto_sing_song", "晴天"),
    ("彈一首 夢中的婚禮", "pe.play_virtual_piano", "夢中的婚禮"),
    ("彈鋼琴 月光奏鳴曲", "pe.play_virtual_piano", "月光奏鳴曲"),
    ("點歌 Never Gonna Give You Up", "auto_sing_song", "Never Gonna Give You Up"),
    # 歌名含半形冒號：斷句集不可切它（2026-10-09 直播漏判「唱 5:20am」）
    ("唱 5:20am", "auto_sing_song", "5:20am"),
    ("點歌 10:35", "auto_sing_song", "10:35"),
    # 全形冒號是中文解說分隔符：取冒號前
    ("唱 晴天：超好聽", "auto_sing_song", "晴天"),
]


def test_true_positives_still_hit():
    for text, want_tool, want_song in TRUE_POSITIVES:
        tool, args = parse_hard_command(text)
        assert tool == want_tool, f"漏判：{text!r} → {tool}{args}"
        assert args.get("song_name") == want_song, f"歌名錯：{text!r} → {args}"


def test_piano_and_sing_are_independent():
    assert extract_sing_song("彈夢中的婚禮") is None
    assert extract_piano_song("彈夢中的婚禮") == "夢中的婚禮"


def test_negation_guards():
    assert extract_sing_song("不唱晴天") is None
    assert extract_piano_song("別彈這首") is None


def test_slip_states_7l_is_the_performer():
    """紙條必須講清楚唱歌的是 7L，不是點歌的人（防「我老爸有唱一首」誤答）。"""
    s = build_slip_text("auto_sing_song", {"song_name": "晴天"}, "老爸")
    assert "演唱者是妳 7L 本人" in s
    assert "老爸只是開口點歌" in s
    assert "並沒有親自演唱" in s
    assert "他並沒有" not in s  # 不預設點歌人性別

    p = build_slip_text("pe.play_virtual_piano", {"song_name": "月光"}, "日光謙也✨")
    assert "彈琴的是妳 7L 本人" in p
    assert "日光謙也✨只是點曲" in p

    other = build_slip_text("search_google", {"query": "x"}, "老爸")
    assert "search_google" in other


def test_slip_neutral_when_requester_unknown():
    """點歌人不一定是老爸（可能是觀眾）：未知時走中性文案，絕不預設成老爸。"""
    s = build_slip_text("auto_sing_song", {"song_name": "晴天"}, "")
    assert "老爸" not in s
    assert "演唱者是妳 7L 本人" in s
    assert "不是點歌的人" in s

    p = build_slip_text("pe.play_virtual_piano", {"song_name": "月光"}, None)
    assert "老爸" not in p
    assert "彈琴的是妳 7L 本人" in p
    assert "不是點曲的人" in p

    g = build_slip_text("search_google", {"query": "x"}, "")
    assert "老爸" not in g
    assert "search_google" in g


def test_empty_and_none_safe():
    assert parse_hard_command("") == (None, {})
    assert parse_hard_command(None) == (None, {})


def test_display_requester_never_defaults_to_dad():
    """有誰寫誰；未知走中性，絕不預設成老爸（點歌人不一定是老爸）。"""
    # 具名透傳（含老爸本人真的點歌時）
    assert display_requester("老爸", "dad") == "老爸"
    assert display_requester("日光謙也✨", "audience") == "日光謙也✨"
    assert display_requester("  7L媽  ", "dad") == "7L媽"
    # 未知／空 → 中性
    assert display_requester("", "dad") == "點播的人"
    assert display_requester(None, "dad") == "點播的人"
    assert display_requester("   ", "audience") == "大家"
    assert display_requester(None, "audience") == "大家"
    # 通用稱呼不算具名：audience 頻道一律收斂成大家
    assert display_requester("點播的人", "audience") == "大家"
    assert display_requester("大家", "dad") == "點播的人"


def test_parse_slip_for_song_rescues_missed_requests():
    """斷線救援：紙條送達後 session 死亡，主腦沒看到——重連後從紙條還原點歌。
    2026-10-09 真實事故：「唱 5:20am」紙條送達→G3 斷線→歌沒了。"""
    tool, args = parse_slip_for_song("[文字輸入] 老爸 (在直播間留言)：唱 5:20am")
    assert tool == "auto_sing_song"
    assert args == {"song_name": "5:20am"}

    tool, args = parse_slip_for_song("[黑板同步] TikTok 觀眾 RC_全台小刀第42名 對妳說：唱 不再曼波")
    assert tool == "auto_sing_song"
    assert args == {"song_name": "不再曼波"}

    # 系統紙條（CPU 命中／謝幕／失敗通知）一律不認：點歌動詞都在非祈使位置
    assert parse_slip_for_song(
        build_slip_text("auto_sing_song", {"song_name": "晴天"}, "老爸")) == (None, {})
    assert parse_slip_for_song(
        "[系統提示：妳剛才演唱完畢了歌曲《晴天》，請自然地向老爸與觀眾謝幕！]"
    ) == (None, {})
    assert parse_slip_for_song(
        "[系統提示：剛才點的《晴天》背景準備失敗，請自然地跟大家說這首先跳過！]"
    ) == (None, {})
    # 環境／閒聊紙條不認
    assert parse_slip_for_song("[環境動態] 電腦畫面剛剛發生變化：右下角跳出通知") == (None, {})
    assert parse_slip_for_song("") == (None, {})
    assert parse_slip_for_song(None) == (None, {})
    # 彈琴不救（只救點歌；鋼琴短、腦通常當場反應）
    assert parse_slip_for_song("[文字輸入] 老爸：彈 月光") == (None, {})


def test_parse_slip_rejects_multiline_sentry_slips():
    """2026-10-11 救援死亡循環：哨兵紙條夾帶多行 board_context，
    曾抽出「3aя\\n請妳綜合上述留言」這種垃圾歌，失敗丟棄後無限重救（G0→G7）。"""
    sentry = ("[系統提示：背景潛意識哨兵偵測到直播間最新動態！目標：Johnny，事件焦點：唱歌請求。"
              "剛才收到的觀眾留言：\n"
              "- [17:22:00] 【TikTok 直播觀眾「Johnny」】：唱3aя\n"
              "請妳綜合上述留言，直接用語音開口回應！]")
    assert parse_slip_for_song(sentry) == (None, {})
    # 單行真點歌照救
    assert parse_slip_for_song("[文字輸入] 老爸：唱3aя") == (
        "auto_sing_song", {"song_name": "3aя"})


def test_rescue_claim_blocks_repeat_loops():
    """同首 120 秒內只救一次：失敗丟棄也不重救，斷線風暴不再循環。"""
    _RESCUED_SONG_TS.clear()
    try:
        assert rescue_claim("3aя", now=1000.0) is True
        assert rescue_claim("3aя", now=1050.0) is False
        assert rescue_claim("3aя ", now=1050.0) is False  # 空白視為同首
        assert rescue_claim("晴天", now=1050.0) is True  # 別首不受影響
        assert rescue_claim("3aя", now=1000.0 + 121.0) is True  # 過窗口可再救
        assert rescue_claim("", now=1000.0) is False
    finally:
        _RESCUED_SONG_TS.clear()


def test_cpu_ignores_expression_only_songs():
    """CPU 只認點歌：表情一律放行交還主腦/A 架構（NV 接）。"""
    assert parse_hard_command("做暈表情") == (None, {})
    assert parse_hard_command("換成哭哭") == (None, {})
    assert parse_hard_command("重置表情") == (None, {})
    # 點歌照攔
    assert parse_hard_command("唱晴天")[0] == "auto_sing_song"


def test_japanese_titles_hit():
    """2026-10-10 直播事故：全片假名歌名被判無內容而漏接。"""
    tool, args = parse_hard_command("唱 インフェルノシティ")
    assert tool == "auto_sing_song"
    assert args == {"song_name": "インフェルノシティ"}
    assert parse_hard_command("唱 ロンリーユニバース") == (
        "auto_sing_song", {"song_name": "ロンリーユニバース"})
    assert parse_hard_command("唱 幽霊東京") == (
        "auto_sing_song", {"song_name": "幽霊東京"})
    assert parse_hard_command("唱pretender") == (
        "auto_sing_song", {"song_name": "pretender"})
    # 全語言：韓文/俄文/泰文/阿拉伯文都攔，純標點才放行
    assert parse_hard_command("唱 Dynamite") == (
        "auto_sing_song", {"song_name": "Dynamite"})
    assert parse_hard_command("唱 blueseoul") == (
        "auto_sing_song", {"song_name": "blueseoul"})
    tool, args = parse_hard_command("唱 Катюша")
    assert tool == "auto_sing_song" and args["song_name"] == "Катюша"
    tool, args = parse_hard_command("唱 봄날")
    assert tool == "auto_sing_song" and args["song_name"] == "봄날"


def test_mixed_play_sing():
    """
    2026-10-11 直播事故：「彈晴天加唱晴天」被當成一首爛歌名拿去搜譜全滅。"""
    mx = parse_mixed_command("彈晴天加唱晴天")
    assert mx == [("pe.play_virtual_piano", {"song_name": "晴天"}),
                  ("auto_sing_song", {"song_name": "晴天"})]
    mx = parse_mixed_command("唱晴天加彈月光")
    assert mx == [("auto_sing_song", {"song_name": "晴天"}),
                  ("pe.play_virtual_piano", {"song_name": "月光"})]
    # 非混用退回空（調用方走單句）
    assert parse_mixed_command("彈 Hungarian Rhapsody No.2") == []
    assert parse_mixed_command("唱晴天") == []
    assert parse_mixed_command("他彈晴天加唱月光") == []  # 第三人稱不碰
    assert parse_mixed_command("別彈晴天加唱月光") == []  # 否定不碰
    assert parse_mixed_command("彈歌加唱舞") == []  # 兩邊有一邊不是歌名就整單退回
    # 救援只救唱歌那路
    assert parse_slip_for_song("[文字輸入] 老爸：彈晴天加唱晴天") == (
        "auto_sing_song", {"song_name": "晴天"})
    tool, args = parse_hard_command("唱 ชีวิต")
    assert tool == "auto_sing_song" and args["song_name"] == "ชีวิต"
    assert parse_hard_command("唱 ？！") == (None, {})
    assert parse_hard_command("唱 。。。") == (None, {})
    # 句尾搭訕剝離（2026-10-11：唱放個大招給你看→放個大招）
    assert parse_hard_command("唱放個大招給你看") == (
        "auto_sing_song", {"song_name": "放個大招"})
    assert parse_hard_command("唱晴天聽聽看") == (
        "auto_sing_song", {"song_name": "晴天"})
    assert parse_hard_command("彈月光給我聽") == (
        "pe.play_virtual_piano", {"song_name": "月光"})
    assert parse_hard_command("唱放個大招給你看看吧") == (
        "auto_sing_song", {"song_name": "放個大招"})


# --- 表情不歸 CPU（紙條分支保留給 A 架構 NV 用）---
def test_expression_slip_forbids_repeat():
    s = build_slip_text("trigger_vts_expression", {"expression_name": "暈"}, "老爸")
    assert "做表情的是妳 7L 本人" in s
    assert "不要重複下達" in s
    s2 = build_slip_text("trigger_vts_expression", {"expression_name": "_RESET_"}, "")
    assert "重置為自然狀態" in s2
    assert "老爸" not in s2


# --- 搜尋消毒（2026-10-10：幾 MB base64 被當關鍵字）---
def test_strip_blob_noise():
    blob = "A" * 500
    assert strip_blob_noise(f"查一下{blob}天氣") == "查一下天氣"
    uri = "data:audio/wav;base64," + "B" * 500
    assert strip_blob_noise(f"語法{uri}結束") == "語法結束"
    # 正常文字一字不動
    assert strip_blob_noise("台北天氣如何？") == "台北天氣如何？"
    assert strip_blob_noise("") == ""


def test_sanitize_search_query():
    assert sanitize_search_query("台北天氣") == "台北天氣"
    assert sanitize_search_query("暈表情 " + "C" * 500) == "暈表情"
    assert len(sanitize_search_query("x" * 500)) <= 120
    assert sanitize_search_query("") == ""
    assert sanitize_search_query("  ") == ""
    assert sanitize_search_query("嗎") == ""


def test_incident_20261010_search_query_with_audio_blob():
    """真實事故字串：腦吐 [TOOL:SEARCH] 暈表情 語法<audio src="data:...,base64,...">…"""
    blob = "UklGRmAGAAB" * 300  # ~3KB wav base64
    raw = f'暈表情 語法<audio src="data:audio/wav;base64,{blob}">'
    q = sanitize_search_query(raw)
    assert "base64" not in q and "audio" not in q and len(q) <= 120
    assert q.startswith("暈表情")
    # 殘殼標籤也不留
    assert "<" not in q and ">" not in q
