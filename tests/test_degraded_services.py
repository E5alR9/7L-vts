"""外部服務掛掉時的退化（2026-11-01 故障演練）。"""
import asyncio

import services.piano_engine as pe


def test_direct_song_name_found_locally_does_not_wait_for_gemini_when_groq_is_down(monkeypatch):
    """Groq 掛掉時「彈小星星」以前等 Gemini 12 秒（3.8 想太久、3.6 回 503）才照曲名找。"""
    import core.groq_router as gr

    async def down(*a, **k):
        raise RuntimeError("429 rate limit exceeded")
    monkeypatch.setattr(gr, "groq_chat", down)
    monkeypatch.setattr(pe, "get_piano_gemini_keys", lambda: (_ for _ in ()).throw(AssertionError("不該問 Gemini")))
    files = ["小星星.mid", "晴天 周杰倫.mid", "卡農.mid"]
    r = asyncio.run(pe.resolve_piano_intent_by_ai("小星星", files, is_direct_song_name=True))
    assert r["is_song_request"] and r["matched_files"] == ["小星星.mid"] and r["_provider"] == "local"
    r = asyncio.run(pe.resolve_piano_intent_by_ai("晴天", files, current_playing_title="小星星",
                                                  current_playing_file="小星星.mid", is_direct_song_name=True))
    assert r["matched_files"] == ["晴天 周杰倫.mid"]                       # 正在彈別首照樣直接換


def test_fast_path_only_takes_exact_titles_from_the_real_library(monkeypatch):
    """2026-11-01 Fable 用真曲庫驗出：寬鬆防呆拿來挑檔，「小星星」挑到核心名是空的東方曲、「stop」「換一首」也對得到檔。"""
    import glob
    import os
    files = [os.path.basename(f) for f in glob.glob(os.path.join(pe.MIDI_SHEETS_DIR, "*.mid"))]
    files += ["(touhou 9beatmario) [ ナイト・オブ・ナイツ  Night of knights ].mid", "Don't Stop Me Now.mid",
              "周杰倫- 稻香.mid", "周杰倫 愛在西元前 piano midi.mid", "Coldplay - Viva La Vida.mid",
              "Coldplay - Viva La Vida (100% accurate piano).mid", "小星星.mid"]

    def pick(q):
        k = pe._title_key(q)
        return sorted({f for f in files if len(k) >= 2 and k in pe._title_keys(f)})
    assert pick("小星星") == ["小星星.mid"] and pick("稻香") == ["周杰倫- 稻香.mid"]
    assert pick("愛在西元前") == ["周杰倫 愛在西元前 piano midi.mid"] and len(pick("Viva La Vida")) == 2
    for q in ("stop", "換一首", "下一首", "重播", "月光奏鳴曲", "BGM", "主題曲", "(隨便)", "那首"):
        assert pick(q) == [], q

    import core.groq_router as gr

    async def down(*a, **k):
        raise RuntimeError("429")
    asked = []
    monkeypatch.setattr(gr, "groq_chat", down)
    monkeypatch.setattr(pe, "get_piano_gemini_keys", lambda: asked.append(1) or [])
    asyncio.run(pe.resolve_piano_intent_by_ai("周杰倫", ["周杰倫- 稻香.mid", "周杰倫 愛在西元前 piano midi.mid"],
                                              is_direct_song_name=True))
    assert asked == [1]                                                     # 歌手名對到好幾首不同的歌：交給 AI


def test_same_song_as_playing_or_not_a_direct_name_still_asks_the_ai(monkeypatch):
    import core.groq_router as gr

    async def down(*a, **k):
        raise RuntimeError("429")
    asked = []
    monkeypatch.setattr(gr, "groq_chat", down)
    monkeypatch.setattr(pe, "get_piano_gemini_keys", lambda: asked.append(1) or [])
    files = ["小星星.mid"]
    asyncio.run(pe.resolve_piano_intent_by_ai("小星星", files, current_playing_title="小星星",
                                              current_playing_file="小星星.mid", is_direct_song_name=True))
    asyncio.run(pe.resolve_piano_intent_by_ai("可以彈小星星嗎", files))
    assert len(asked) == 2


def test_voice_only_ever_uses_gpt_sovits_and_edge(monkeypatch):
    """老爸 2026-11-01：備用不要用 Google TTS，GPT-SoVITS 跟 edge 兩個就好。"""
    import importlib
    import services.tts_router as R
    assert set(R._ENGINES) == {"xiaoyi", "edge"} and R.ENGINE_CHAIN == ["xiaoyi", "edge"]
    monkeypatch.setenv("TTS_ENGINE", "gemini,xiaoyi")
    monkeypatch.setenv("TTS_FALLBACK", "google,edge")
    try:
        assert importlib.reload(R).ENGINE_CHAIN == ["xiaoyi", "edge"]   # 設定檔寫了別的也不理
    finally:
        monkeypatch.delenv("TTS_ENGINE")
        monkeypatch.delenv("TTS_FALLBACK")
        importlib.reload(R)
