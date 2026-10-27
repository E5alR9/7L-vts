import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
lines = open("vts_7L_test.py", encoding="utf-8").readlines()
keys = ["for idx, c_dict in enumerate(chunks):",
        "first_chunk = False",
        "producer_task = asyncio.create_task(tts_producer_worker())"]
for i, l in enumerate(lines):
    for k in keys:
        if k in l and "director" not in l.lower():
            print(j := i + 1, ascii(l))
            break
