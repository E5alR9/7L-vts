# -*- coding: utf-8 -*-
"""確認 vts_token_test.txt 是否真的是 token（只印形狀）。"""
import io, re, sys
sys.stdout.reconfigure(encoding="utf-8")
s = io.open("vts_token_test.txt", encoding="utf-8", errors="replace").read()
print("len:", len(s.strip()))
print("lines:", len(s.strip().splitlines()))
print("hexlike:", bool(re.fullmatch(r"[0-9a-fA-F\s]+", s.strip())))
