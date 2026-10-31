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
    # 預設一定擋；只有明確設 SIM_ALLOW_SCREEN=1（老爸同意的看圖測試，例如視線副腦）才不擋（2026-10-31）
    gate = next(n for n in tree.body if isinstance(n, ast.If) and "SIM_ALLOW_SCREEN" in ast.unparse(n.test))
    assert ast.unparse(gate.test) == "os.environ.get('SIM_ALLOW_SCREEN') == '1'"
    patched = {ast.unparse(t): n.lineno for n in gate.orelse if isinstance(n, ast.Assign) for t in n.targets}
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


def test_tests_never_talk_to_the_real_7l():
    """2026-10-31：老爸開著正式的 7L，測試包裝拒絕啟動，測試照跑：打字、主持插話、走位、計時器全送進正式的 7L。
    現在送任何動作前先確定 7870 控制埠（只有測試包裝有）在；啟動被拒整串停。"""
    src = open(os.path.join(ROOT, "tools", "sim", "ft.py"), encoding="utf-8").read()
    act = src[src.index("def act("):src.index("def step(")]
    assert "ensure_sim()" in act and src.index("ensure_sim()", src.index('if __name__ == "__main__":')) > 0
    up = open(os.path.join(ROOT, "tools", "sim", "live_up.sh"), encoding="utf-8").read()
    assert 'grep -aq "測試版不開"' in up and "exit 1" in up
