# -*- coding: utf-8 -*-
"""桌機代答分流閘（2026-10-11）：有工具味走 API 老路，純閒聊走免費桌面。
寧可誤判去 API（現狀），不誤判去桌面（功能靜默丟失）。
主檔太重不直接 import，用 AST 抽出來跑。"""
import ast
import os


def _load():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    ns = {}
    funcs = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "_DESKTOP_TOOL_HINTS":
                    ns[t.id] = ast.literal_eval(n.value)
        if isinstance(n, ast.FunctionDef) and n.name == "_likely_needs_tools":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_likely_needs_tools":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    return funcs


def test_tool_hints_go_api():
    f = _load()["_likely_needs_tools"]
    for s in ["唱晴天", "來首點歌", "彈鋼琴", "搜一下天氣", "記住我愛吃麵",
              "開麥", "關麥", "設個鬧鐘", "查一下股票", "畫一隻貓",
              "播剛才那首", "翻譯這句", "幾點了", "睡覺", "換個表情", ""]:
        assert f(s) is True, s


def test_chatter_goes_desktop():
    f = _load()["_likely_needs_tools"]
    for s in ["今天好累", "哈哈哈", "晚安", "這個好吃", "嗯嗯",
              "我好開心", "剛才那部電影不錯", "在幹嘛"]:
        assert f(s) is False, s
