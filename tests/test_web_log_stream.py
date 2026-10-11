# -*- coding: utf-8 -*-
"""SoVITS stdout 攔截器：只認主人的輸出，RVC 在別線程的 tqdm 原樣放行。
（2026-10-11：RVC 進度污染粉色 TTS 框，網站 TTS 寫成 RVC。）
local_xiaoyi_service 可直接 import（頂部無 torch，加載安全）。"""
import io
import threading

from conftest import ROOT  # noqa: F401
import local_xiaoyi_service as xs
import services.web_dashboard as web_dash


def test_owner_lines_parsed_and_broadcast(monkeypatch):
    events = []
    monkeypatch.setattr(web_dash, "broadcast_event",
                        lambda et, data: events.append((et, dict(data))))
    s = xs._WebLogStream()
    s._owner = threading.get_ident()
    s._real_out = io.StringIO()
    s.write("50%|████  | 5/10 [00:01<00:01, 5.0it/s]\n")
    prog = [e for e in events if e[0] == "tts_progress"]
    assert len(prog) == 1
    assert prog[0][1]["stage"] == "提取 BERT 特徵進度"  # 不再硬標 RVC
    assert "RVC" not in prog[0][1]["stage"]


def test_other_thread_passthrough_no_broadcast(monkeypatch):
    events = []
    monkeypatch.setattr(web_dash, "broadcast_event",
                        lambda et, data: events.append((et, dict(data))))
    real = io.StringIO()
    s = xs._WebLogStream()
    s._owner = threading.get_ident()  # 主人＝主線程
    s._real_out = real

    def _rvc_thread():
        s.write("18%|#8 | 275/1500 [00:04<00:20, 58.81it/s]\n")

    th = threading.Thread(target=_rvc_thread)
    th.start()
    th.join()
    assert events == []  # 一個廣播都沒有
    assert "275/1500" in real.getvalue()  # 原樣去了真終端
    assert s.buffer == ""  # 沒污染解析緩衝


def test_capture_sets_owner():
    with xs.capture_tts_output() as _:
        pass
    import sys
    assert not isinstance(sys.stdout, xs._WebLogStream)  # 還原了
