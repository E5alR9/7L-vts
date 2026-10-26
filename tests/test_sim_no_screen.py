# -*- coding: utf-8 -*-
"""實機測試絕不能看老爸的螢幕（2026-10-26）：tools/sim/sim_run.py 在主程式啟動前擋掉所有截圖入口。
程式裡的截圖方式只准有那幾個；新增別的截圖路徑，這裡會先紅，提醒包裝也要擋。"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_sim_run_blocks_every_screenshot_entry_before_starting_7l():
    src = open(os.path.join(ROOT, "tools", "sim", "sim_run.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    start = next(n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "runpy.run_path")
    patched = {ast.unparse(t): n.lineno for n in tree.body if isinstance(n, ast.Assign) for t in n.targets}
    for entry in ("_sc.grab_screen", "_sc.gdi_capture_screen", "_ig.grab"):
        assert entry in patched and patched[entry] < start, entry


def test_no_other_screenshot_paths():
    """截圖只准經 services/screen_capture.py（dxcam、GDI）和 PIL.ImageGrab.grab（YT 伴看）；包裝擋的就是這些。"""
    allowed = {os.path.join("services", "screen_capture.py"), os.path.join("services", "yt_companion_service.py")}
    pat = re.compile(r"pyautogui\.screenshot|ImageGrab\.grab|\bmss\b|dxcam\.create|BitBlt|PrintWindow|pyscreeze")
    bad = []
    files = ["vts_7L_test.py"] + [os.path.join(d, f) for d in ("core", "services", "workers")
                                  if os.path.isdir(os.path.join(ROOT, d))
                                  for f in os.listdir(os.path.join(ROOT, d)) if f.endswith(".py")]
    for rel in files:
        if rel in allowed:
            continue
        for i, line in enumerate(open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace"), 1):
            if pat.search(line) and not line.lstrip().startswith("#"):
                bad.append(f"{rel}:{i}: {line.strip()[:80]}")
    assert bad == []
