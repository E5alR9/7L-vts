# -*- coding: utf-8 -*-
"""HUD 分流架構守衛（2026-10-11）：唱歌管線永遠走 rvc_progress（下層青藍 HUD），
說話 TTS 永遠走 tts_progress（上層粉 HUD）。兩邊搶同一個 HUD 會互相蓋掉，
Mili TTS 時網站寫 RVC 就是這麼來的。誰再往唱歌管線加 tts_progress，這裡會炸。"""
import os


def _src(name):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, name), encoding="utf-8") as f:
        return f.read()


def test_sing_pipeline_never_drives_tts_hud():
    for mod in ("services/auto_cover_pipeline.py",
                "services/neural_voice_converter.py"):
        src = _src(mod)
        assert '"tts_progress"' not in src, f"{mod} 還在餵 TTS HUD"
        assert src.count('"rvc_progress"') >= 1, f"{mod} 沒有 rvc 事件"


def test_tts_synth_stays_on_tts_hud():
    src = _src("local_xiaoyi_service.py")
    assert '"tts_progress"' in src
    assert '"rvc_progress"' not in src


def test_rvc_hud_dom_and_style_present():
    html = _src("web/index.html")
    for dom_id in ("rvcProgressHud", "rvcHudIcon", "rvcHudTitle", "rvcHudStage",
                   "rvcHudPct", "rvcHudBarFill", "rvcHudDetail"):
        assert f'id="{dom_id}"' in html, f"缺 DOM: {dom_id}"
    css = _src("web/dashboard.css")
    assert ".tts-progress-hud.rvc-below" in css
    js = _src("web/dashboard.js")
    assert "getElementById('rvcProgressHud')" in js
