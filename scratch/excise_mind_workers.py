import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
print("orig lines:", len(lines))

def check(lo, hi, head_mark, tail_mark):
    assert head_mark in lines[lo-1], f"head {lo}: {lines[lo-1][:60]}"
    assert tail_mark in lines[hi-1], f"tail {hi}: {lines[hi-1][:60]}"

# 從後往前刪，行號不漂移
# 1. 兩死 worker＋專用全域 (8782-9226)
check(8782, 9226, "PROACTIVE_LAST_FG_TITLE", "await asyncio.sleep(2)")
del lines[8781:9226]
# 2. process_chat_message 內兩行 mark (原 8397、8243)
assert "mark_recent_thoughts_as_read()" in lines[8397-1], lines[8397-1][:60]
del lines[8397-1]
assert "mark_recent_thoughts_as_read()" in lines[8243-1], lines[8243-1][:60]
del lines[8243-1]
# 3. 心流鏈 (原 3250-3362：分隔線起，mark 函數尾止)
assert "RECENT_STREAM_OF_CONSCIOUSNESS = []" in lines[3255-1], lines[3255-1][:60]
check(3250, 3362, "─", 'item["is_read"] = True')
del lines[3249:3362]
# 4. 心流金鑰冷卻全域 (原 2523)
assert "_MIND_LIVE_KEY_COOLDOWN" in lines[2523-1], lines[2523-1][:60]
del lines[2523-1]

open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("new lines:", len(lines))
