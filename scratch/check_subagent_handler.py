# -*- coding: utf-8 -*-
"""靜檢 _handle_invoke_subagent：自由變數必須全是 closure( session/ws_send_lock) 或模組全域。"""
import ast, io, sys
sys.stdout.reconfigure(encoding="utf-8")

src = io.open("vts_7L_test.py", encoding="utf-8").read()
tree = ast.parse(src)

# 收集模組級 def/async def 名稱
mod_names = set()
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        mod_names.add(node.name)
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                mod_names.add(t.id)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        for a in node.names:
            mod_names.add((a.asname or a.name).split(".")[0])

# 找到嵌套的 _handle_invoke_subagent
target = None
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_invoke_subagent":
        target = node
        break
assert target is not None, "function not found"

# 其外層 receive_from_live 的區域變數（closure 來源）
outer = None
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef) and node.name == "receive_from_live":
        outer = node
        break
closure_ok = {"session", "ws_send_lock"}

# 自由變數分析
class V(ast.NodeVisitor):
    def __init__(self):
        self.loaded = set()
        self.stored = set()
    def visit_Name(self, node):
        (self.stored if isinstance(node.ctx, ast.Store) else self.loaded).add(node.id)
    def visit_ExceptHandler(self, node):
        if node.name:
            self.stored.add(node.name)
        for s in node.body:
            self.visit(s)

v = V()
for stmt in target.body:
    v.visit(stmt)
params = {a.arg for a in target.args.args}
free = v.loaded - v.stored - params - set(dir(__builtins__))
# 例外：方法呼叫的屬性基底、f-string 內已含；log_print 等應在模組層
bad = {n for n in free if n not in mod_names and n not in closure_ok}
print("closure:", sorted(closure_ok))
print("free vars:", sorted(free))
print("UNRESOLVED:", sorted(bad) if bad else "none")
assert not bad, bad

# 呼叫點：確認 background create_task + 追蹤 set 都在
call_site = src[src.find("來幾個跑幾個"):]
assert "_handle_invoke_subagent(" in call_site
assert "_RUNNING_SUBAGENT_TASKS.add(_sub_t)" in src
assert "_sub_t.add_done_callback(_RUNNING_SUBAGENT_TASKS.discard)" in src
print("CALL SITE OK")
