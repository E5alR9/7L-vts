"""Live 長連線的接收迴圈（2026-10-24 實機測試發現）：google-genai 的 session.receive()
收到 turn_complete 就結束迭代，只呼叫一次的話每講完一句整條連線就關掉重連。
常駐的 session（主 Live 大腦、本能大腦、YouTube 伴看）必須在外層包迴圈反覆呼叫。"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wrapped_receive_loops(path, func_name):
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name)
    found = []
    for n in ast.walk(fn):
        if isinstance(n, ast.AsyncFor) and "receive()" in ast.unparse(n.iter):
            found.append(n)
    wrapped = [n for n in ast.walk(fn) if isinstance(n, ast.While)
               and any(isinstance(b, ast.AsyncFor) and "receive()" in ast.unparse(b.iter) for b in n.body)]
    return found, wrapped


def test_main_live_brain_keeps_receiving_after_each_turn():
    found, wrapped = _wrapped_receive_loops("vts_7L_test.py", "receive_from_live")
    assert found and wrapped, "receive_from_live 的 session.receive() 必須包在 while 迴圈裡"


def test_instinct_brain_keeps_receiving():
    found, wrapped = _wrapped_receive_loops("vts_7L_test.py", "instinct_live_worker")
    assert found and wrapped


def test_yt_companion_keeps_receiving():
    found, wrapped = _wrapped_receive_loops("services/yt_companion_service.py", "_receive_worker")
    assert found and wrapped


def test_sdk_receive_still_stops_at_turn_complete():
    """守門：哪天 SDK 改成持續產出，這個測試會提醒我們外層迴圈可以拿掉。"""
    import inspect
    import google.genai.live as live
    src = inspect.getsource(live.AsyncSession.receive)
    assert "turn_complete" in src and "break" in src
