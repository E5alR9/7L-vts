# -*- coding: utf-8 -*-
"""
🎙️ STT 轉錄器 (PROVIDER: LOCAL faster-whisper；見 docs/AI_SOURCES.md)：看影片時把片段轉成文字（services/video_watch）。
    以前還有 Google 免費端點和 backend 切換，沒人用，2026-10-29 刪掉。

    STT_FWHISPER_MODEL = tiny|base|small|medium（預設 small；CPU int8）
"""
import os
import threading

_lock = threading.Lock()
import logging
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

_fw_model = None
_fw_model_name = ""
STT_FWHISPER_MODEL = "small"


def _get_fw_model():
    global _fw_model, _fw_model_name
    name = STT_FWHISPER_MODEL
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


