import ast, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

src = open("vts_7L_test.py", encoding="utf-8").read()
tree = ast.parse(src)  # 語法先過
ns = {"re": __import__("re"), "_TOOL_TAG_RE": __import__("re").compile(r'\[TOOL:[^\]]*\]')}
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_clean_result_for_brain":
        exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
f = ns["_clean_result_for_brain"]
assert f("[TOOL:SEARCH] 台北天氣") == " 台北天氣"
assert f("正常文字") == "正常文字"
assert f("[TOOL:VISION]失敗了[TOOL:MIRROR]看看") == "失敗了看看"
assert f("") == "" and f(None) == ""
print("cleaner ok")

# 看板回滾片段存在且語法正確（AST 已驗）
assert 'm["status"] = "unread"' in src
print("board rollback present")
print("ALL OK")
