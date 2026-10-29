# -*- coding: utf-8 -*-
"""ACE-Step 作曲腿純函式測試（組請求、讀結果、服務沒開安全跳過）。照 ACE-Step 1.5 官方 API（docs/en/API.md）。"""
import asyncio
import json

from conftest import ROOT  # noqa: F401
import services.acestep_music as am


def test_build_request_uses_the_official_field_names():
    r = am.build_request("抒情歌", lyrics="啦啦", duration=90, style="鋼琴")
    assert "鋼琴" in r["prompt"] and r["lyrics"] == "啦啦" and r["audio_duration"] == 90
    assert r["model"] == am.ACESTEP_MODEL and r["vocal_language"] == "zh" and r["batch_size"] == 1
    r2 = am.build_request("", duration=9999)
    assert r2["lyrics"] == "[Instrumental]" and r2["audio_duration"] == 600 and r2["vocal_language"] == "en"
    assert am.build_request("x", duration=1)["audio_duration"] == 10
    assert am.build_request("x", lyrics="さくら")["vocal_language"] == "ja"


def test_parse_result_reads_the_json_string_result():
    ok = {"task_id": "t", "status": 1, "result": json.dumps([{"file": "/v1/audio?path=%2Ftmp%2Fa.mp3", "status": 1}])}
    assert am.parse_result(ok) == (1, "/v1/audio?path=%2Ftmp%2Fa.mp3")
    assert am.parse_result({"task_id": "t", "status": 0, "result": None}) == (0, "")
    st, err = am.parse_result({"task_id": "t", "status": 2, "result": json.dumps({"error": "CUDA OOM"})})
    assert st == 2 and "OOM" in err


def test_service_down_skips(monkeypatch):
    monkeypatch.setattr(am, "ACESTEP_URL", "http://127.0.0.1:9")    # 沒有服務的埠
    r = asyncio.run(am.generate_song("test"))
    assert r["ok"] is False and "沒開" in r["error"]
    assert am.status()["alive"] is False and am.is_enabled() is False
