import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "tests/test_tts_router.py"
src = open(p, encoding="utf-8").read()
assert "test_spoken_form" not in src
block = '''

# ── 口語正規化（2026-10-11：SoVITS 遇到《5:20am》丟中段）─────────────────────
def test_normalize_spoken_form():
    from core.prompts import TextCleanEngine as C
    assert C.normalize_spoken_form("好喔，《5:20am》交給我") == "好喔，上午五點二十分交給我"
    assert C.normalize_spoken_form("唱《晴天》吧") == "唱晴天吧"
    assert C.normalize_spoken_form("半夜12:00開播", for_chinese=True) == "半夜中午十二點整開播"
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
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\\x00\\x00" * int(24000 * seconds))
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
'''
open(p, "w", encoding="utf-8", newline="").write(src + block)
print("appended")
