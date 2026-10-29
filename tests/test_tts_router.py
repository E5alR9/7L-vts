# -*- coding: utf-8 -*-
"""services/tts_router.py 純函式測試（不打語音合成）"""
import asyncio
import io
import os

from conftest import ROOT  # noqa: F401
from services import tts_router as t


# ── 語言偵測（只回 zh / ja）─────────────────────────────────────────────────
def test_detect_language_chinese():
    assert t.detect_language("你好嗎，今天天氣真好。") == "zh"
    assert t.detect_language("老爸你在幹嘛") == "zh"
    # 無任何特徵時預設中文（直播語境以中文為主）
    assert t.detect_language("") == "zh"


def test_detect_language_japanese():
    assert t.detect_language("こんにちは") == "ja"
    assert t.detect_language("カタカナです") == "ja"
    # 純漢字、無中文語氣詞 → 依假名比例規則仍可能 zh，只要求回合法值
    assert t.detect_language("東京タワー") in ("zh", "ja")
    # 半形片假名（YT 歌名常見）必須算進假名：之前漏掉會誤判 zh
    assert t.detect_language("ﾛﾝﾘｰﾕﾆﾊﾞｰｽ") == "ja"
    assert t.detect_language("ﾊﾞｶ") == "ja"


def test_detect_language_mixed_prefers_chinese_with_markers():
    # 同時有漢字與假名，但帶中文語氣詞 → 判定 zh
    assert t.detect_language("你好 こんにちは 嗎") == "zh"


# ── 副檔名對應（播放端靠它命名暫存檔）──────────────────────────────────────
def test_file_extension_mapping():
    assert t.file_extension("edge") == ".mp3"
    for eng in ("xiaoyi", "unknown_engine"):
        assert t.file_extension(eng) == ".wav"


# ── 文字清洗（餵給 TTS 前的標籤/括號/多音字處理入口）────────────────────────
def test_clean_text_strips_action_tags_and_brackets():
    out = t._clean_text("[PITCH:+2Hz]你好(笑)[EXPRESSION: 開心]，(這樣)", "zh")
    assert "[PITCH" not in out and "[EXPRESSION" not in out
    assert "(笑)" not in out and "(這樣)" not in out
    # 標籤/括號移除後剩「你好，」，尾逗號會被 strip 掉
    assert out == "你好"


def test_clean_text_renames_7l_for_tts():
    out = t._clean_text("我是7L，這是7l的實驗室", "zh")
    assert "7L" not in out and "7l" not in out
    assert out.count("小七") == 2


def test_clean_text_collapses_repeated_punctuation():
    # 只合併重複的逗號/感嘆/問號/句號（TTS 念重複標點會不自然）
    # 注意：合併結果統一為全形標點，且句尾標點保留（語氣依據）
    assert t._clean_text("真的嗎？？？", "zh") == "真的嗎？"
    assert t._clean_text("真的嗎!!!", "zh") == "真的嗎！"
    assert t._clean_text("嗯，，，然後呢", "zh") == "嗯，然後呢"
    assert t._clean_text("好。。好吧", "zh") == "好。好吧"
    # 開頭逗號仍被 strip
    assert t._clean_text("，你好", "zh") == "你好"


def test_clean_text_japanese_skips_loanword_rewrite():
    # 日文路徑不套中文外來語改寫表（回傳仍應含原文假名）
    out = t._clean_text("こんにちは[EXPRESSION: 開心]", "ja")
    assert "こんにちは" in out and "[EXPRESSION" not in out


# ── 片假名→中文音譯（中文聲線用；2026-10-09 直播：片假名歌名被中文聲線唸爛）──
def test_transliterate_kana_to_zh():
    assert t.transliterate_kana_to_zh("ロンリーユニバース") == "羅恩利優尼巴蘇"
    assert t.transliterate_kana_to_zh("バカ") == "巴卡"
    assert t.transliterate_kana_to_zh("コーヒー") == "考希"
    # 平假名同表、促音/長音丟掉
    assert t.transliterate_kana_to_zh("ってみた") == "特米塔"
    # 半形片假名（含浊点组合）
    assert t.transliterate_kana_to_zh("ﾛﾝﾘｰ") == "羅恩利"
    assert t.transliterate_kana_to_zh("ﾊﾞｶ") == "巴卡"
    # 非假名原樣保留
    assert t.transliterate_kana_to_zh("點這首「ロンリー」超好聽") == "點這首「羅恩利」超好聽"
    assert t.transliterate_kana_to_zh("純中文沒有假名") == "純中文沒有假名"
    assert t.transliterate_kana_to_zh("") == ""


def test_clean_text_keeps_kana_on_both_paths():
    # _clean_text 只清標籤/括號、不動假名：多語言 SoVITS 靠 auto 原生唸假名，
    # 音譯只發生在 _synth_edge（純中文聲線）內部，不污染共享清洗路徑。
    out = t._clean_text("點這首「ロンリーユニバース」超有品味[EXPRESSION: 開心]", "zh")
    assert "ロンリーユニバース" in out and "超有品味" in out
    assert "[EXPRESSION" not in out
    out_ja = t._clean_text("こんにちは[EXPRESSION: 開心]", "ja")
    assert "こんにちは" in out_ja


# ── 引擎註冊表與降級鏈 ─────────────────────────────────────────────────────
def test_engine_registry_contains_all_known_engines():
    # 與 services/tts_router._ENGINES 同步（kokoro 已於 0d0ab8d22 移除；cosyvoice、elevenlabs、cloud_gptsovits 2026-10-29 移除）
    for eng in ("edge", "xiaoyi"):
        assert eng in t._ENGINES, f"缺少引擎註冊: {eng}"
        assert callable(t._ENGINES[eng])


def test_engine_chain_has_no_duplicates():
    assert len(t.ENGINE_CHAIN) == len(set(t.ENGINE_CHAIN))
    assert all(e in t._ENGINES for e in t.ENGINE_CHAIN), "鏈內有未註冊引擎"


def test_get_active_engine_initially_none_or_registered():
    ae = t.get_active_engine()
    assert ae is None or ae in t._ENGINES


def test_engine_timeout_falls_back():
    """2026-10-11 全場靜默：卡住的引擎 90 秒（測試壓到 0.2 秒）必須降級，不陪葬。"""
    import asyncio

    async def hang(text):
        await asyncio.sleep(3600)
        return b"x" * 200

    async def fast(text):
        return b"y" * 200

    old_engines, old_chain = t._ENGINES, t.ENGINE_CHAIN
    old_active, old_timeout = t._active_engine, t.ENGINE_TIMEOUT_SEC
    old_errors = dict(t._engine_errors)
    t._ENGINES = {"hang": hang, "fast": fast}
    t.ENGINE_CHAIN = ["hang", "fast"]
    t._active_engine = None
    t.ENGINE_TIMEOUT_SEC = 0.2
    try:
        out = asyncio.run(t.get_tts_audio_bytes("你好"))
        assert out == b"y" * 200
        assert t.get_active_engine() == "fast"
    finally:
        t._ENGINES, t.ENGINE_CHAIN = old_engines, old_chain
        t._active_engine, t.ENGINE_TIMEOUT_SEC = old_active, old_timeout
        t._engine_errors.clear()
        t._engine_errors.update(old_errors)


def test_engine_all_fail_returns_empty():
    import asyncio

    async def fail(text):
        raise RuntimeError("down")

    old_engines, old_chain = t._ENGINES, t.ENGINE_CHAIN
    old_active = t._active_engine
    t._ENGINES = {"bad": fail}
    t.ENGINE_CHAIN = ["bad"]
    t._active_engine = None
    try:
        assert asyncio.run(t.get_tts_audio_bytes("你好")) == b""
    finally:
        t._ENGINES, t.ENGINE_CHAIN = old_engines, old_chain
        t._active_engine = old_active


# ── 口語正規化（2026-10-11：SoVITS 遇到《5:20am》丟中段）─────────────────────
def test_normalize_spoken_form():
    from core.prompts import TextCleanEngine as C
    assert C.normalize_spoken_form("好喔，《5:20am》交給我") == "好喔，上午五點二十分交給我"
    assert C.normalize_spoken_form("唱《晴天》吧") == "唱晴天吧"
    assert C.normalize_spoken_form("半夜12:00開播", for_chinese=True) == "半夜十二點整開播"
    assert C.normalize_spoken_form("2:20見", for_chinese=True) == "兩點二十分見"
    # 日文語境：時間不轉（交給引擎），書名號照拔
    assert C.normalize_spoken_form("12:00に会う", for_chinese=False) == "12:00に会う"
    assert C.normalize_spoken_form("25:99亂寫") == "25:99亂寫"  # 非法時間不動
    assert C.normalize_spoken_form("") == ""
    # clean_for_tts 整管走過：書名號沒了、時間轉了
    out = C.clean_for_tts("好喔，《5:20am》交給我，背景準備中。")
    assert "《" not in out and "5:20am" not in out
    assert "五點二十分" in out


def test_num_zh():
    from core.prompts import TextCleanEngine as C
    assert (C._num_zh(0), C._num_zh(9), C._num_zh(10), C._num_zh(11),
            C._num_zh(20), C._num_zh(21), C._num_zh(59)) == (
        "零", "九", "十", "十一", "二十", "二十一", "五十九")


def test_short_audio_falls_back():
    """有聲但缺段（0.5 秒音訊配 30 字文案）必須換引擎，不將就。"""
    import asyncio
    import wave

    def make_wav(seconds):
        import math
        import struct
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            frames = bytearray()
            for i in range(int(24000 * seconds)):
                frames += struct.pack("<h", int(6000 * math.sin(2 * math.pi * 440 * i / 24000)))
            w.writeframes(bytes(frames))
        return buf.getvalue()

    async def short(text):
        return make_wav(0.5)

    async def good(text):
        return make_wav(8.0)

    old_engines, old_chain = t._ENGINES, t.ENGINE_CHAIN
    old_active, old_errors = t._active_engine, dict(t._engine_errors)
    t._ENGINES = {"short": short, "good": good}
    t.ENGINE_CHAIN = ["short", "good"]
    t._active_engine = None
    try:
        out = asyncio.run(t.get_tts_audio_bytes("好喔，背景準備中，好了就唱給你聽。"))
        assert out == make_wav(8.0)
        assert t.get_active_engine() == "good"
    finally:
        t._ENGINES, t.ENGINE_CHAIN = old_engines, old_chain
        t._active_engine = old_active
        t._engine_errors.clear()
        t._engine_errors.update(old_errors)


# ── 工具調用剝離 vs 歌名保留（2026-10-11：world.execute(me) 被當函數吃掉）─────
def test_tool_call_strip_keeps_song_titles():
    from core.prompts import TextCleanEngine as C
    # 歌名／自然文本：程式碼標點轉口語邊界後照唸，不整段消失
    out = C.clean_for_tts("好喔，Mili - world.execute(me);背景準備中，好了就唱給你聽。")
    assert "world execute me" in out, out
    assert ";" not in out and "，" in out  # 半形分號轉逗號不斷句
    assert "(" not in out and ")" not in out and "." not in out.split("，")[1]
    assert "hello world" in C.clean_for_tts("唱hello(world)吧")
    # 真洩漏照殺：具名工具／蛇形名／參數像代碼
    assert "auto_sing_song" not in C.clean_for_tts("來一首auto_sing_song({'song_name': '晴天'})吧")
    assert "play_virtual_piano" not in C.clean_for_tts("[play_virtual_piano(123)]走起")
    assert "foo_bar" not in C.clean_for_tts("測試foo_bar(baz)結束")
    assert "search_google" not in C.clean_for_tts("查一下search_google(周杰倫)看看")
    assert "f(" not in C.clean_for_tts('看看f("x", y)是什麼')
    assert "set(" not in C.clean_for_tts("跑set(x=1)試試")


def test_semicolon_becomes_pause():
    from core.prompts import TextCleanEngine as C
    assert C.normalize_spoken_form("a;b") == "a，b"
    assert C.normalize_spoken_form("好喔，Mili - world.execute(me);背景") == "好喔，Mili，world execute me，背景"


# ── 語句磁碟快取（2026-10-11：口頭禪別再花 3 秒合成）─────────────────────────
def test_tts_cache_key():
    k1 = t._tts_cache_key("你好呀", "xiaoyi")
    assert k1 == t._tts_cache_key("  你好呀  ", "xiaoyi")  # 前後空白同一句
    assert k1 != t._tts_cache_key("你好呀", "edge")        # 引擎不同
    assert k1 != t._tts_cache_key("你不好呀", "xiaoyi")    # 文案不同
    assert k1.endswith(".wav") and t._tts_cache_key("hi", "edge").endswith(".mp3")


def test_tts_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "TTS_CACHE_DIR", str(tmp_path))
    assert t.tts_cache_get("你好呀", "xiaoyi") is None
    t.tts_cache_put("你好呀", "xiaoyi", b"x" * 5000)
    assert t.tts_cache_get("你好呀", "xiaoyi") == b"x" * 5000
    t.tts_cache_put("太短不存", "xiaoyi", b"tiny")
    assert t.tts_cache_get("太短不存", "xiaoyi") is None


def test_tts_cache_prune(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(t, "TTS_CACHE_MAX_FILES", 3)
    monkeypatch.setattr(t, "TTS_CACHE_MAX_BYTES", 10 ** 9)
    import time as _time
    for i in range(5):
        t.tts_cache_put(f"句子{i}", "xiaoyi", bytes([i]) * 2000)
        _time.sleep(0.02)
    left = sorted(os.listdir(str(tmp_path)))
    assert len(left) == 3  # 只留最新的 3 個


def test_tts_cache_serves_repeat_without_resynth(tmp_path, monkeypatch):
    """同一句第二次直接命中，合成函數只被調用一次。"""
    import asyncio
    calls = {"n": 0}

    async def fake_engine(text):
        calls["n"] += 1
        import wave as _w
        buf = io.BytesIO()
        with _w.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x01\x02" * int(24000 * 8.0))  # 8 秒（舊寫法多了反斜線，實際產生 32 秒）
        return buf.getvalue()

    monkeypatch.setattr(t, "TTS_CACHE_DIR", str(tmp_path))
    old_engines, old_chain = t._ENGINES, t.ENGINE_CHAIN
    old_active, old_errors = t._active_engine, dict(t._engine_errors)
    t._ENGINES = {"fake": fake_engine}
    t.ENGINE_CHAIN = ["fake"]
    t._active_engine = None
    try:
        text = "快取測試口頭禪，你好呀。" * 2  # ≥10 字才進時長守衛
        a = asyncio.run(t.get_tts_audio_bytes(text))
        b = asyncio.run(t.get_tts_audio_bytes(text))
        assert a == b and len(a) > 100
        assert calls["n"] == 1
    finally:
        t._ENGINES, t.ENGINE_CHAIN = old_engines, old_chain
        t._active_engine = old_active
        t._engine_errors.clear()
        t._engine_errors.update(old_errors)


# ── 程式碼標點轉口語邊界（2026-10-11：Mili 句整段消失＋後面變日文）──────────
def test_code_punct_to_spoken_boundaries():
    from core.prompts import TextCleanEngine as C
    # 拉丁 token 內 .()_/\ 轉空格，獨立 - 轉逗號
    assert C.normalize_spoken_form("Mili - world.execute(me)") == "Mili，world execute me "
    assert C.normalize_spoken_form("唱world_execute_me吧") == "唱world execute me吧"
    assert C.normalize_spoken_form("A/B測") == "A B測"
    # 時間不受傷（先轉時間，冒號本來就不在集合裡）
    assert C.normalize_spoken_form("半夜5:20am開播") == "半夜上午五點二十分開播"
    # 日文語境不動
    assert C.normalize_spoken_form("12:00に会う", for_chinese=False) == "12:00に会う"
    # 整管：Mili 句無殘留毒標點，中文不斷
    out = C.clean_for_tts("好喔，《Mili - world.execute(me)》交給我，背景準備中，好了就唱給你聽！")
    assert out == "好喔，Mili，world execute me 交給我，背景準備中，好了就唱給你聽。"
    for bad in ["《", "》", "(", ")"]:
        assert bad not in out


# ── 音訊剖面守衛（2026-10-11：自娛自樂 14 秒靜音案）─────────────────────────
def _craft_wav(seconds, gaps=(), fr=16000):
    import math
    import struct
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fr)
        frames = bytearray()
        for i in range(int(fr * seconds)):
            t = i / fr
            v = 0 if any(s <= t < e for s, e in gaps) else int(8000 * math.sin(2 * math.pi * 440 * t))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def test_audio_profile_clean():
    dur, gap = t._audio_profile(_craft_wav(3.0))
    assert abs(dur - 3.0) < 0.2 and gap is not None and gap < 0.5


def test_audio_profile_catches_silent_middle():
    dur, gap = t._audio_profile(_craft_wav(8.0, gaps=[(2.0, 5.0)]))
    assert abs(dur - 8.0) < 0.3
    assert gap is not None and gap >= 2.9  # 3 秒洞現形（自娛自樂是 14 秒）


def test_audio_profile_tolerates_pause():
    dur, gap = t._audio_profile(_craft_wav(4.0, gaps=[(1.0, 1.3)]))
    assert gap is not None and gap < t.MAX_SILENCE_SEC  # 正常標點停頓不冤枉


def test_audio_profile_garbage():
    assert t._audio_profile(b"") == (None, None)
    assert t._audio_profile(b"xyz" * 200) == (None, None)


def test_silent_middle_falls_back(tmp_path, monkeypatch):
    """中段靜音（時長正常）也要換引擎，不將就播出 14 秒空氣。"""
    import asyncio
    gappy = _craft_wav(8.0, gaps=[(2.0, 5.0)])
    good = _craft_wav(8.0)

    async def fake_gappy(text):
        return gappy

    async def fake_good(text):
        return good

    monkeypatch.setattr(t, "TTS_CACHE_DIR", str(tmp_path))
    old_engines, old_chain = t._ENGINES, t.ENGINE_CHAIN
    old_active, old_errors = t._active_engine, dict(t._engine_errors)
    t._ENGINES = {"gappy": fake_gappy, "good": fake_good}
    t.ENGINE_CHAIN = ["gappy", "good"]
    t._active_engine = None
    try:
        out = asyncio.run(t.get_tts_audio_bytes("自娛自樂背景測試句，長度一定要夠十個字。"))
        assert out == good
        assert t.get_active_engine() == "good"
        assert "疑似掉片" in t.get_engine_errors().get("gappy", "")
    finally:
        t._ENGINES, t.ENGINE_CHAIN = old_engines, old_chain
        t._active_engine = old_active
        t._engine_errors.clear()
        t._engine_errors.update(old_errors)


def test_xiaoyi_split_method_single_piece():
    """直播短句整段一坨（cut5 碎片會整片靜音）。"""
    from services import local_xiaoyi_service as _xs
    assert _xs.XIAOYI_SPLIT_METHOD == "cut0"


# ── 斷句不斷詞（2026-10-11：好不好聽被切成好不好，聽）────────────────────────
def test_clause_segmentation_keeps_words():
    from core.prompts import TextCleanEngine as C
    seg = C.natural_clause_segmentation
    # 詞內疑問結構絕不斷開
    assert seg("觀眾朋友們覺得好不好聽呀？") == "觀眾朋友們覺得好不好聽呀？"
    assert seg("昨天那場表演真的好不好看都沒人說") == "昨天那場表演真的好不好看都沒人說"
    assert seg("你到底對不對勁跟我說清楚") == "你到底對不對勁跟我說清楚"
    assert seg("他是不是很久沒出現了") == "他是不是很久沒出現了"
    # 剩下的真 tag 照樣斷（回歸）
    assert seg("我覺得這樣對吧跟我說一聲") == "我覺得這樣對吧，跟我說一聲"
    assert seg("觀眾說真的啦跟你講一下") == "觀眾說真的啦，跟你講一下"
    # 整管：回報句不斷詞
    out = C.clean_for_tts("呼～這首《world.execute(me);》老爸你還滿意嗎？觀眾朋友們覺得好不好聽呀？給點尖叫聲！")
    assert "好不好聽呀" in out and "好不好，" not in out


def test_long_replies_are_split_at_punctuation_for_streaming():
    """長回覆以前整段一次合成，60 字以上要等 6～17 秒才出聲（2026-10-25 實測）：切段後第一段先念。"""
    from services.tts_router import split_for_streaming as f, speech_timeline as tl
    t = "報告老爸。台北今天陰時多雲，氣溫25到27度，體感舒適。不過有短暫陣雨機會，出門記得帶把雨傘喔～"
    parts = f(t)
    assert "".join(parts) == t and len(parts) >= 2
    assert all(p[-1] in "，。！？～" for p in parts[:-1])          # 只在標點切
    first, gaps = tl(parts)
    assert first < tl([t])[0] - 1.5 and gaps < 0.3               # 早很多開口、中間不停
    assert f("好的老爸。") == ["好的老爸。"] and f("") == []


def test_split_choice_avoids_mid_sentence_gaps():
    """2026-10-26：以前 30 字內一律整段（老爸怕碎音停頓）、長的第一段湊滿 4 字就切。
    「收到。」這種太短的第一段念完、後面那段還沒合成好，實機量到停 1.6～1.7 秒。
    現在照時間模型挑：只有算得出不停頓才切，短句也一樣。"""
    from services.tts_router import split_for_streaming as f, speech_timeline as tl
    for t in ("收到。晴天來囉～這首我也超喜歡的，彈給老爸聽。", "老爸早安。今天天氣很好，要不要出去走走？",
              "收到老爸的訊息心情當然是超級好呀～想好今天要玩什麼了嗎？", "收到。老爸你看，我這就彈給你聽喔～"):
        parts = f(t)
        first, gaps = tl(parts)
        assert "".join(parts) == t and gaps < 0.05, (t, parts)
        assert first <= tl([t])[0]                                  # 不會比整段一次更晚開口
        assert parts[0] not in ("收到。", "哇。")                    # 太短的第一段會停頓
    assert len(f("老爸早安。今天天氣很好，要不要出去走走？")) == 2      # 短句算得出不停頓：切
    assert f("收到。老爸你看，我這就彈給你聽喔～") == ["收到。老爸你看，我這就彈給你聽喔～"]   # 切了會停：整段


def test_voice_playback_streams_split_chunks():
    import ast
    import os
    main = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vts_7L_test.py"),
                encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(main)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "play_voice_complete")
    src = ast.get_source_segment(main, fn)
    assert "split_for_streaming(clean_for_tts_text)" in src and '"text": clean_for_tts_text' not in src


def test_reduplicated_cha_is_read_as_check_not_zha():
    """「我去查查」本機 GPT-SoVITS 念成「喳喳」zhā（2026-10-26 老爸實聽）；「查一下」「查查看」本來就對。"""
    from core.prompts import TextCleanEngine as C
    out = C.clean_for_tts("好嘞老爸，我去查查明天台北的天氣～")
    assert "查查" not in out and "茶茶" in out
    assert "查一下" in C.clean_for_tts("我去查一下")


def test_decimals_are_read_with_dian():
    """報匯率「0.21」以前點號被當程式碼標點換成空格，念成「零 二十一」（2026-10-26 實機）。"""
    from core.prompts import TextCleanEngine as C
    assert C.normalize_spoken_form("賣出是 0.21 台幣") == "賣出是 零點二一 台幣"
    assert C.normalize_spoken_form("1.5倍速、17.5度、120.25元") == "一點五倍速、十七點五度、120點二五元"
    assert C.normalize_spoken_form("world.execute(me)").strip() == "world execute me"   # 程式碼標點照舊轉空格
    assert "零點二一" in C.clean_for_tts("台銀最新日圓現鈔賣出是 0.21 台幣喔！")
