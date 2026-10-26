# -*- coding: utf-8 -*-
"""SoVITS stdout 攔截器：只認主人的輸出，RVC 在別線程的 tqdm 原樣放行。
（2026-10-11：RVC 進度污染粉色 TTS 框，網站 TTS 寫成 RVC。）
local_xiaoyi_service 可直接 import（頂部無 torch，加載安全）。"""
import io
import threading

from conftest import ROOT  # noqa: F401
from services import local_xiaoyi_service as xs
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
    assert s._pending == ""  # 沒污染解析緩衝


def test_capture_sets_owner():
    with xs.capture_tts_output() as _:
        pass
    import sys
    assert not isinstance(sys.stdout, xs._WebLogStream)  # 還原了


def test_other_thread_flush_does_not_steal_pending_line(monkeypatch):
    """狀態列每 0.1 秒 print(flush=True)；別人的 flush 不能把 TTS 還沒寫完的那一行搶去解析（2026-10-25）。"""
    events = []
    monkeypatch.setattr(web_dash, "broadcast_event", lambda et, data: events.append((et, dict(data))))
    s = xs._WebLogStream()
    s._owner = threading.get_ident()
    s._real_out = io.StringIO()
    s.write("实际输入的目标文本")          # 主人寫了半行
    th = threading.Thread(target=s.flush)
    th.start()
    th.join()
    assert s._pending == "实际输入的目标文本" and events == []


def test_unknown_attributes_delegate_to_real_terminal():
    """sys.stdout 全進程共用：TTS 攔截期間別人拿 encoding／buffer／isatty 不能炸（2026-10-25 狀態列崩潰：
    '_WebLogStream' object has no attribute 'buffer'）。"""
    real = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    s = xs._WebLogStream()
    s._real_out = real
    assert s.encoding == "utf-8" and s.buffer is real.buffer and s.isatty() is False
    s._real_out = None                                    # 沒記到原終端就找 sys.__stdout__
    assert callable(s.fileno)
