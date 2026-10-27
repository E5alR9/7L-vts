import ast, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = "vts_7L_test.py"
src = open(path, encoding="utf-8").read()
tree = ast.parse(src)
lines = src.splitlines(keepends=True)

names = ["fetch_fast_text_reply", "save_local_audio_clip",
         "get_recent_local_audio_clips", "load_audio_clip_base64",
         "save_user_profile", "search_internet", "is_too_similar_to_recent",
         "strip_all_emojis", "capture_system_audio_chunk",
         "transcribe_audio_bytes", "gemini_system_audio_live_transcribe",
         "live_code_tool_task", "background_system_task",
         "check_requires_deep_gemini"]
found = {}
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names:
        found[n.name] = (n.lineno, n.end_lineno)

# 檢查每個目標區間內有無被其他 live 代碼引用（字串名也不行）
import re
for name in names:
    if name not in found:
        print("NOT FOUND:", name)
for name, (s, e) in sorted(found.items(), key=lambda x: x[1]):
    print(f"{s}-{e} {name}")

# 輸出刪除腳本用的區間（1-based 閉區間，含函數前空行由腳本處理）
with open("scratch/excise_list.txt", "w", encoding="utf-8") as f:
    for name, (s, e) in sorted(found.items(), key=lambda x: x[1]):
        f.write(f"{s} {e} {name}\n")
print("wrote scratch/excise_list.txt")
