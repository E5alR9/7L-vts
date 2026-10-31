"""說話的語氣：語速、音高、大小聲（老爸 2026-10-31）。"""
import asyncio

from core import prosody as P
from core.prompts import TextCleanEngine as T
import services.tts_router as R


def _ct(s):
    return T.clean_for_tts(T.clean_speech_text(s), apply_phonetics=True)


def _chunks(raw):
    return P.build_chunks(raw, _ct, T.clean_speech_text, R.split_for_streaming)


def test_expression_sets_the_tone_until_the_next_expression():
    out = _chunks("[EXPRESSION: 生氣] 你怎麼可以偷吃我的布丁！[EXPRESSION: 臉紅] 好啦，下次要分我一半喔～")
    assert [t for t, _ in out] == ["你怎麼可以偷吃我的布丁。", "好啦，下次要分我一半喔～"]
    angry, shy = out[0][1], out[1][1]
    assert angry["speed"] > 1.05 and angry["pitch"] < 0 and angry["gain_db"] > 2    # 快、低、大聲（加！再大聲一點）
    assert shy["speed"] < 0.95 and shy["pitch"] > 0 and shy["gain_db"] < 0          # 慢、高、小聲


def test_her_own_tag_only_covers_what_follows_and_splits_the_segment():
    """以前「過來一下。[悄悄話] 我跟你說」併成同一段，整段都變悄悄話。"""
    out = _chunks("老爸過來一下。[悄悄話] 我跟你說一個秘密…")
    assert out[0] == ("老爸過來一下。", P.NEUTRAL)
    assert out[1][1]["gain_db"] <= -10 and out[1][1]["speed"] < 1.0


def test_plain_sentences_keep_the_old_voice_and_cache_key():
    assert all(P.is_neutral(p) for _, p in _chunks("今天天氣不錯，我們出去走走吧。"))
    assert R._prosody_cache_text("你好", 1.0, 0.0, 0.0) == "你好"                       # 舊快取照用
    assert R._prosody_cache_text("你好", 1.1, -1.0, 3.0) != "你好"


def test_limits_and_aliases():
    p = P._combine((1.5, 5.0, 20.0), (1.5, 5.0, 20.0))
    assert p["speed"] == P.SPEED_RANGE[1] and p["pitch"] == P.PITCH_RANGE[1] and p["gain_db"] == P.GAIN_RANGE[1]
    assert P.emotion_of("害羞") == P.EMOTION_PROSODY["臉紅"] and P.emotion_of("不存在的表情") is None
    assert P.describe({"speed": 1.1, "pitch": -1.0, "gain_db": 3.0}) == "語速 1.10x、低 1 半音、大聲 3dB"


def test_prosody_tags_are_not_spoken_or_remembered():
    assert T.clean_speech_text("[小聲] 老爸過來一下") == "老爸過來一下"
    from conftest import MAIN_SRC
    assert "t = prosody.TAG_RE.sub('', t)" in MAIN_SRC
    assert "tts_router.get_tts_audio_bytes(c_dict[\"text\"], **_pros)" in MAIN_SRC


def test_edge_fallback_gets_the_same_tone():
    assert R._edge_prosody(1.1, -1.0, 3.0) == {"rate": "+10%", "pitch": "-15Hz", "volume": "+41%"}
    assert R._edge_prosody() == {"rate": "+0%", "pitch": "+0Hz", "volume": "+0%"}


def test_router_passes_the_tone_to_the_engine_and_caches_it_separately(monkeypatch, tmp_path):
    seen = []

    async def engine(text, speed=1.0, pitch=0.0, gain_db=0.0):
        seen.append((text, speed, pitch, gain_db))
        return b"x" * 500
    monkeypatch.setattr(R, "_ENGINES", {"xiaoyi": engine})
    monkeypatch.setattr(R, "ENGINE_CHAIN", ["xiaoyi"])
    monkeypatch.setattr(R, "_active_engine", None)
    monkeypatch.setattr(R, "_quality_problem", lambda t, d: "")
    monkeypatch.setattr(R, "TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(R, "TTS_CACHE_DISABLE", False)
    asyncio.run(R.get_tts_audio_bytes("你好喔", speed=1.1, pitch=-1.0, gain_db=3.0))
    asyncio.run(R.get_tts_audio_bytes("你好喔"))                       # 原本的語氣不能拿到調過的快取
    assert seen == [("你好喔", 1.1, -1.0, 3.0), ("你好喔", 1.0, 0.0, 0.0)]


def test_xiaoyi_pitch_and_volume_post_processing():
    import numpy as np
    from services.local_xiaoyi_service import apply_voice_prosody
    sr = 32000
    t = np.arange(sr) / sr
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    louder = apply_voice_prosody(tone, sr, gain_db=6.0)
    quieter = apply_voice_prosody(tone, sr, gain_db=-6.0)
    assert np.abs(louder).max() <= 1.0 and np.abs(louder).mean() > np.abs(tone).mean() > np.abs(quieter).mean()
    assert apply_voice_prosody(tone, sr).dtype == np.float32


def test_louder_is_still_louder_after_the_peak_guard():
    """Fable 審查：以前 tanh 限幅後峰值到 1.2，接著「峰值超過 0.95 整段縮回 0.92」把大聲抵銷掉。"""
    import numpy as np
    from services.local_xiaoyi_service import apply_voice_prosody
    sr = 32000
    t = np.arange(sr) / sr
    voice = (0.85 * np.sin(2 * np.pi * 220 * t) * (0.3 + 0.7 * np.abs(np.sin(2 * np.pi * 3 * t)))).astype(np.float32)

    def after_guard(a):
        peak = np.abs(a).max()
        return a * (0.92 / peak) if peak > 0.95 else a

    def rms_db(a):
        return 20 * np.log10(np.sqrt(np.mean(np.square(a))))
    loud = apply_voice_prosody(voice, sr, gain_db=4.0)
    assert np.abs(loud).max() <= 0.95 + 1e-6                          # 不會再被整段縮回去
    assert rms_db(after_guard(loud)) - rms_db(after_guard(voice)) > 2.0
    quiet = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)   # 小聲的地方照放大，不多給
    assert abs(rms_db(apply_voice_prosody(quiet, sr, gain_db=3.0)) - rms_db(quiet) - 3.0) < 0.1


def test_tiny_expression_bits_join_the_neighbour_instead_of_being_their_own_segment():
    out = _chunks("[EXPRESSION: 笑] 嗯 [EXPRESSION: 臉紅] 好啦，下次再一起去吃吧")
    assert len(out) == 1 and "嗯" in out[0][0] and "好啦" in out[0][0]


def test_thought_brackets_split_by_a_tag_are_still_removed():
    raw = "（心想：老爸今天 [EXPRESSION: 笑] 好像很累）好啦，我陪你喔"
    out = P.build_chunks(raw, _ct, T.clean_speech_text, R.split_for_streaming, strip_spans=T.strip_cross_tag_spans)
    spoken = "".join(t for t, _ in out)
    assert "老爸今天" not in spoken and "好像很累" not in spoken and "我陪你" in spoken
