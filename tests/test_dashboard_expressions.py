# -*- coding: utf-8 -*-
"""後台表情盤（2026-10-29 老爸：後台只有寫死的 7 顆，模型新的表情都沒放上去）＋同一輪看後台抓到的小毛病。"""
from conftest import ROOT  # noqa: F401
import asyncio
import os
import re

import services.vts_client as v
from test_vts_reset import FakeVTS


class ListVTS(FakeVTS):
    """模型有哪些表情檔（含沒開的）；ExpressionStateRequest 回全部、標開著沒"""
    def __init__(self, model_files, active_files=()):
        super().__init__(active_files)
        self.model = list(model_files)

    async def request(self, payload):
        if payload.get("messageType") == "ExpressionStateRequest":
            return {"data": {"expressions": [{"file": f, "active": f in self.active} for f in self.model]}}
        return await super().request(payload)


MODEL = ["上.exp3.json", "话筒.exp3.json", "爱心.exp3.json", "水印.exp3.json", "生气.exp3.json", "红脸.exp3.json"]


def test_list_follows_model_and_hides_watermark():
    fake = ListVTS(MODEL, active_files=("爱心.exp3.json", "水印.exp3.json"))
    items = asyncio.run(v.list_expressions(fake))
    files = [it["file"] for it in items]
    assert "水印.exp3.json" not in files
    assert files[:4] == ["爱心.exp3.json", "红脸.exp3.json", "生气.exp3.json", "话筒.exp3.json"]   # 有中文名的照表排前面
    assert files[-1] == "上.exp3.json"                                                            # 模型新加、表裡沒有的也列，用檔名
    by = {it["file"]: it for it in items}
    assert by["爱心.exp3.json"]["name"] == "愛心" and by["爱心.exp3.json"]["active"]
    assert by["红脸.exp3.json"]["name"] == "臉紅" and not by["红脸.exp3.json"]["active"]
    assert by["话筒.exp3.json"]["prop"] and not by["爱心.exp3.json"]["prop"]
    assert by["上.exp3.json"]["name"] == "上"


def test_list_falls_back_without_vts():
    v.CURRENT_ACTIVE_EXPS = {"星星眼.exp3.json"}
    old = v.GLOBAL_VTS
    v.GLOBAL_VTS = None
    try:
        items = asyncio.run(v.list_expressions())
    finally:
        v.GLOBAL_VTS = old
        v.CURRENT_ACTIVE_EXPS = set()
    by = {it["file"]: it for it in items}
    assert "水印.exp3.json" not in by and "话筒.exp3.json" in by
    assert by["星星眼.exp3.json"]["active"]


def test_toggle_single_file_only_touches_that_one():
    v.CURRENT_ACTIVE_EXPS = {"爱心.exp3.json"}
    fake = ListVTS(MODEL, active_files=("爱心.exp3.json", "生气.exp3.json"))
    assert asyncio.run(v.set_expression_file("生气.exp3.json", False, fake))
    assert fake.deactivated == ["生气.exp3.json"] and "爱心.exp3.json" in fake.active
    assert asyncio.run(v.set_expression_file("红脸.exp3.json", True, fake))
    assert "红脸.exp3.json" in fake.active and "红脸.exp3.json" in v.CURRENT_ACTIVE_EXPS
    assert not asyncio.run(v.set_expression_file("水印.exp3.json", False, fake))   # 水印不給動
    assert "水印.exp3.json" not in fake.deactivated
    v.CURRENT_ACTIVE_EXPS = set()


def test_plural_expression_tag_is_recognised():
    """她偶爾寫成 [EXPRESSIONS: 吐舌]：兩個解析處都要認得"""
    for rel in (("services", "stage_actions.py"), ("vts_7L_test.py",)):
        src = open(os.path.join(ROOT, *rel), encoding="utf-8").read()
        pats = re.findall(r"re\.search\(r'(\\\[EXPRESSION[^']*)'", src)
        assert pats, rel
        for p in pats:
            assert re.search(p, "好啦 [EXPRESSIONS: 吐舌] 再一次", re.IGNORECASE), (rel, p)
            assert re.search(p, "[EXPRESSION: 開心] 好耶", re.IGNORECASE), (rel, p)


def test_dashboard_strips_all_control_tags():
    """後台對話框：大寫標籤一律拿掉（[VIEWER_UPDATE:…]、[EXPRESSIONS: …] 以前漏網）"""
    js = open(os.path.join(ROOT, "web", "dashboard.js"), encoding="utf-8").read()
    body = js[js.index("stripControlTags(text) {"):]
    assert r"/\[[A-Z_]+(?:[:：][^\]]*)?\]/g" in body[:600]


def test_stop_piano_when_not_out_does_not_reset_face():
    """唱歌前主腦順手叫收琴、琴其實沒拿出來：不重置表情（會連話筒一起關）、不記「鋼琴演奏結束並收起」"""
    import services.piano_engine as pe
    calls = []
    saved = (pe.is_piano_active, pe.current_piano_process, pe.current_piano_task, pe.is_piano_window_alive,
             pe._remember, pe.set_vts_expression)
    pe.is_piano_active, pe.current_piano_process, pe.current_piano_task = False, None, None
    pe.is_piano_window_alive = lambda: False
    pe._remember = lambda t: calls.append(("remember", t))

    async def fake_set(*a, **k):
        calls.append(("expression", a[1:]))
    pe.set_vts_expression = fake_set
    try:
        out = asyncio.run(pe.stop_virtual_piano(force=True))
    finally:
        (pe.is_piano_active, pe.current_piano_process, pe.current_piano_task, pe.is_piano_window_alive,
         pe._remember, pe.set_vts_expression) = saved
    assert "本來就沒拿出來" in out and "[EXPRESSION" not in out
    assert calls == []
