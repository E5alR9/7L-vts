import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "tests/test_busy_expression.py"
src = open(p, encoding="utf-8").read()
assert "_grace_busy" not in src
block = '''

def test_grace_period_filters_short_tasks():
    """5 秒寬限：短活閃一下不掛臉，連忙滿 5 秒才算。"""
    import ast, os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tree = ast.parse(open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read())
    ns = {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_grace_busy":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
    g = ns["_grace_busy"]
    assert g(False, None, 100.0) == (False, None)
    assert g(True, None, 100.0) == (False, 100.0)   # 剛忙：計時，不算
    assert g(True, 100.0, 103.0) == (False, 100.0)  # 忙 3 秒：還不算
    assert g(True, 100.0, 105.0) == (True, 100.0)   # 忙滿 5 秒：算
    assert g(True, 100.0, 999.0) == (True, 100.0)
    assert g(False, 100.0, 999.0) == (False, None)  # 閒了：清零
'''
open(p, "w", encoding="utf-8", newline="").write(src + block)
print("appended")
