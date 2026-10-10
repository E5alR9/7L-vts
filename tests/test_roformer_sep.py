# -*- coding: utf-8 -*-
"""Roformer 三級分離鏈：純函數＋降級鏈（不碰 GPU/模型）。"""
import os
import shutil
import wave

from conftest import ROOT  # noqa: F401
import services.auto_cover_pipeline as acp
import services.roformer_sep as rs


def _tiny_wav(path, seconds=1.0):
    # 立體聲（真實歌曲ogg轉出來就是立體聲；ffmpeg兜底的 stereotools 只要立體聲）
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        n = int(44100 * seconds)
        w.writeframes(b"\x00\x01\x02\x03" * n)
    return path


# ── 百分比解析 ─────────────────────────────────────────────
def test_parse_percent():
    assert rs._parse_percent("") is None
    assert rs._parse_percent("no numbers here") is None
    assert rs._parse_percent(" 45%|####      | 36/79 [01:05<00:52]") == 45
    assert rs._parse_percent("9/79 [00:19<02:37,  2.25s/it]") == 11
    assert rs._parse_percent("79/79 [01:48<00:00]") == 100
    assert rs._parse_percent("100%|##########| 79/79") == 100


# ── stem 挑檔 ──────────────────────────────────────────────
def test_pick_stems_roformer_naming(tmp_path):
    d = str(tmp_path)
    v = os.path.join(d, "5_20am_raw_(Vocals)_model_bs_roformer_ep_317_sdr_12.wav")
    i = os.path.join(d, "5_20am_raw_(Instrumental)_model_bs_roformer_ep_317_sdr_12.wav")
    open(v, "wb").close()
    open(i, "wb").close()
    voc, ins = rs._pick_stems([os.path.basename(v), os.path.basename(i)], d)
    assert voc == v and ins == ins and ins == i


def test_pick_stems_no_vocals_not_vocals(tmp_path):
    d = str(tmp_path)
    nv = os.path.join(d, "no_vocals.wav")
    v = os.path.join(d, "vocals.wav")
    open(nv, "wb").close()
    open(v, "wb").close()
    voc, ins = rs._pick_stems(["no_vocals.wav", "vocals.wav"], d)
    assert voc == v and ins == nv


def test_pick_stems_missing_returns_none(tmp_path):
    assert rs._pick_stems(["ghost.wav"], str(tmp_path)) == (None, None)
    assert rs._pick_stems([], str(tmp_path)) == (None, None)


def test_separate_roformer_rejects_missing_input(tmp_path):
    assert rs.separate_roformer(
        os.path.join(str(tmp_path), "nope.wav"),
        os.path.join(str(tmp_path), "a.wav"),
        os.path.join(str(tmp_path), "b.wav")) is False


# ── 三級鏈（Tier1 成功直返）───────────────────────────────
def test_tier1_success_short_circuits(monkeypatch, tmp_path):
    song = "單元測試Roformer直通歌"
    safe = acp.get_safe_filename(song)
    voc_out = os.path.join(acp.CACHE_DIR, f"{safe}_vocals.wav")
    ins_out = os.path.join(acp.CACHE_DIR, f"{safe}_instrumental.wav")
    src = _tiny_wav(os.path.join(str(tmp_path), "in.wav"))

    def fake_roformer(input_wav, vocals_out, inst_out, song_name="", progress_cb=None):
        assert progress_cb is not None  # 管線必須給進度回調（不空轉契約）
        progress_cb(50)
        shutil.copy2(src, vocals_out)
        shutil.copy2(src, inst_out)
        return True

    monkeypatch.setattr(rs, "separate_roformer", fake_roformer)
    # separate_stems_gpu 內部 from-import 綁定調用時名字，連 acp 命名空間一起擋
    monkeypatch.setattr("services.roformer_sep.separate_roformer", fake_roformer)
    try:
        got = acp.separate_stems_gpu(src, song)
        assert got == (voc_out, ins_out)
        assert os.path.exists(voc_out) and os.path.exists(ins_out)
    finally:
        for f in (voc_out, ins_out):
            if os.path.exists(f):
                os.remove(f)


# ── 三級鏈（Tier1 掛→Tier2 Demucs 接住）───────────────────
def test_tier1_fail_falls_to_demucs(monkeypatch, tmp_path):
    import subprocess as _sp
    song = "單元測試Demucs接住歌"
    safe = acp.get_safe_filename(song)
    src = _tiny_wav(os.path.join(str(tmp_path), "in.wav"))
    base = os.path.splitext(os.path.basename(src))[0]
    d_dir = os.path.join(acp.CACHE_DIR, "htdemucs_ft", base)
    voc_out = os.path.join(acp.CACHE_DIR, f"{safe}_vocals.wav")
    ins_out = os.path.join(acp.CACHE_DIR, f"{safe}_instrumental.wav")

    monkeypatch.setattr("services.roformer_sep.separate_roformer", lambda *a, **k: False)

    real_run = _sp.run

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and len(cmd) > 2 and cmd[1] == "-m" and cmd[2] == "demucs":
            os.makedirs(d_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(d_dir, "vocals.wav"))
            shutil.copy2(src, os.path.join(d_dir, "no_vocals.wav"))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return real_run(cmd, **kw)

    monkeypatch.setattr(_sp, "run", fake_run)
    try:
        got = acp.separate_stems_gpu(src, song)
        assert got == (voc_out, ins_out)
        assert os.path.getsize(voc_out) > 1000
    finally:
        for f in (voc_out, ins_out):
            if os.path.exists(f):
                os.remove(f)
        shutil.rmtree(os.path.join(acp.CACHE_DIR, "htdemucs_ft"), ignore_errors=True)


# ── 三級鏈（Tier1+2 全掛→Tier3 ffmpeg 兜底）───────────────
def test_tier12_fail_falls_to_ffmpeg(monkeypatch, tmp_path):
    import subprocess as _sp
    song = "單元測試ffmpeg兜底歌"
    safe = acp.get_safe_filename(song)
    src = _tiny_wav(os.path.join(str(tmp_path), "in.wav"))
    voc_out = os.path.join(acp.CACHE_DIR, f"{safe}_vocals.wav")
    ins_out = os.path.join(acp.CACHE_DIR, f"{safe}_instrumental.wav")

    monkeypatch.setattr("services.roformer_sep.separate_roformer", lambda *a, **k: False)
    real_run = _sp.run

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and len(cmd) > 2 and cmd[1] == "-m" and cmd[2] == "demucs":
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        return real_run(cmd, **kw)

    monkeypatch.setattr(_sp, "run", fake_run)
    try:
        got = acp.separate_stems_gpu(src, song)
        assert got == (voc_out, ins_out)
        assert os.path.exists(voc_out) and os.path.exists(ins_out)
        assert os.path.getsize(voc_out) > 1000 and os.path.getsize(ins_out) > 1000
    finally:
        for f in (voc_out, ins_out):
            if os.path.exists(f):
                os.remove(f)
