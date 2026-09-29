# -*- coding: utf-8 -*-
"""
🎙️ STT 轉錄器 (PROVIDER: GOOGLE-WEB-SPEECH 為主／LOCAL faster-whisper 為備；見 docs/AI_SOURCES.md)

    STT_BACKEND=auto    預設：Google 免費端點先，失敗退本地 faster-whisper
    STT_BACKEND=google  只用 Google（舊行為）
    STT_BACKEND=faster  只用本地（離線、零額度、中文用 small 模型兼顧品質）
    STT_FWHISPER_MODEL=tiny|base|small|medium（預設 small；CPU int8）
"""
import io
import os
import threading

_lock = threading.Lock()
_fw_model = None
_fw_model_name = ""


def backend() -> str:
    return (os.getenv("STT_BACKEND") or "auto").strip().lower()


def _transcribe_google(wav_bytes: bytes) -> str:
    import speech_recognition as sr
    r = sr.Recognizer()
    buf = io.BytesIO(wav_bytes)
    with sr.AudioFile(buf) as source:
        audio = r.record(source)
    return (r.recognize_google(audio, language="zh-TW") or "").strip()


def _get_fw_model():
    global _fw_model, _fw_model_name
    name = (os.getenv("STT_FWHISPER_MODEL") or "small").strip().lower()
    if _fw_model is not None and _fw_model_name == name:
        return _fw_model
    from faster_whisper import WhisperModel
    _fw_model = WhisperModel(name, device="cpu", compute_type="int8")
    _fw_model_name = name
    return _fw_model


def _transcribe_faster(wav_bytes: bytes) -> str:
    import tempfile
    with _lock:
        model = _get_fw_model()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            path = f.name
        try:
            segments, _ = model.transcribe(path, language="zh", beam_size=1, vad_filter=True)
            return "".join(s.text for s in segments).strip()
        finally:
            try:
                os.remove(path)
            except Exception:
                pass


def transcribe_wav(wav_bytes: bytes) -> str:
    """記憶體內 WAV → 中文文字（失敗回空字串，絕不拋錯）。"""
    if not wav_bytes:
        return ""
    b = backend()
    if b in ("auto", "google"):
        try:
            t = _transcribe_google(wav_bytes)
            if t:
                return t
        except Exception:
            pass
        if b == "google":
            return ""
    if b in ("auto", "faster"):
        try:
            return _transcribe_faster(wav_bytes)
        except Exception:
            pass
    return ""
