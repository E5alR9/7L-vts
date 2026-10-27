import io

p = ".gitignore"
raw = open(p, "rb").read()
# 截掉最後一次 Add-Content 寫入的 GBK 段（從最後一個 *.bin 行尾之後全砍）
i = raw.rfind(b"*.bin")
if i < 0:
    raise SystemExit("anchor not found")
end = raw.find(b"\n", i)
head = raw[:end + 1]
tail = "\r\n# --- 運行時記憶/狀態資料（本機狀態，不上版控、不進 GitHub 鏡像）---\r\ndata/*.json\r\n"
open(p, "wb").write(head + tail.encode("utf-8"))
# 驗證整檔 utf-8 可解
open(p, encoding="utf-8").read()
print("fixed, utf-8 ok")
