"""TTS 品質重抽（2026-10-24 實機）：GPT-SoVITS 偶爾生出中段 25 秒以上的靜音，router 會擋掉，
但預設引擎鏈只有 xiaoyi 一個，擋掉就整句靜音。現在同引擎重抽，取樣有隨機性，重抽通常就好。"""
import asyncio
import io
import wave

import services.tts_router as r


def _wav(speech_sec, silence_sec=0.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        loud = (b"\x00\x40" * int(rate * speech_sec / 2))
        w.writeframes(loud + b"\x00\x00" * int(rate * silence_sec) + loud)
    return buf.getvalue()


def _run(monkeypatch, outputs, retries=2):
    calls = []

    async def fake(text):
        calls.append(text)
        return outputs[min(len(calls) - 1, len(outputs) - 1)]

    monkeypatch.setitem(r._ENGINES, "xiaoyi", fake)
    monkeypatch.setattr(r, "ENGINE_CHAIN", ["xiaoyi"])
    monkeypatch.setattr(r, "_active_engine", None)
    monkeypatch.setattr(r, "QUALITY_RETRIES", retries)
    monkeypatch.setattr(r, "tts_cache_get", lambda *a: None)
    monkeypatch.setattr(r, "tts_cache_put", lambda *a: None)
    text = "老爸。30秒到囉。快快，記得喝水喔，別一直盯着螢幕看啦"
    return asyncio.run(r.get_tts_audio_bytes(text)), calls


def test_bad_then_good_is_retried(monkeypatch):
    good = _wav(3.0)
    out, calls = _run(monkeypatch, [_wav(1.0, silence_sec=26.0), good])
    assert out == good and len(calls) == 2


def test_gives_up_after_retries(monkeypatch):
    bad = _wav(1.0, silence_sec=26.0)
    out, calls = _run(monkeypatch, [bad], retries=2)
    assert out == b"" and len(calls) == 3


def test_good_first_time_no_retry(monkeypatch):
    good = _wav(3.0)
    out, calls = _run(monkeypatch, [good])
    assert out == good and len(calls) == 1
