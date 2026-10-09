# -*- coding: utf-8 -*-
"""列出 vts_7L_test.py 所有 LLM 呼叫點與所屬函式（盤點誰在燒 Gemini）。"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = open(r"C:\Users\qiwai\vts_7L_test.py", encoding="utf-8").read().splitlines()


def enclosing(idx):
    for i in range(idx, -1, -1):
        m = re.match(r"\s*(async def|def)\s+(\w+)", src[i])
        if m:
            return m.group(2)
    return "?"


for label, pat in [
    ("generate_content", r"\.generate_content(_stream)?\("),
    ("fetch_ai_response", r"fetch_ai_response\("),
    ("groq_chat / GROQ", r"groq_chat\(|GROQ_CLIENTS|from core.groq_router"),
    ("Live connect", r"\.live\.connect\("),
]:
    print(f"== {label} ==")
    for i, line in enumerate(src):
        if re.search(pat, line) and "async def" not in line and "def fetch_ai_response" not in line:
            print(f"  {i+1:>5}  {enclosing(i)}()")
    print()
