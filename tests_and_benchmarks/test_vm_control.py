# -*- coding: utf-8 -*-
import json
from vm_agent.client import VMAgentClient

client = VMAgentClient(host="172.22.212.232")

print("=== 1. 測試連線 (Ping) ===")
is_online = client.ping()
print("7L 虛擬機在線狀態:", is_online)

if is_online:
    print("\n=== 2. 獲取虛擬機狀態 (Status) ===")
    status = client.get_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))

    print("\n=== 3. 測試在虛擬機內執行指令 (Exec) ===")
    res = client.exec("hostname; Get-Date; Write-Output 'Hello from 7L dedicated VM!'")
    print("執行成功:", res.get("success"))
    print("輸出內容:\n", res.get("stdout"))

    print("\n=== 4. 測試截圖功能 (Screenshot) ===")
    screen_info = client.get_screenshot(as_base64=True, max_width=640)
    print("截圖成功！解析度:", screen_info.get("width"), "x", screen_info.get("height"))
    print("Base64 長度:", len(screen_info.get("base64", "")))

    print("\n=== 5. 列出虛擬機可視視窗 (Windows) ===")
    windows = client.list_windows()
    for w in windows[:8]:
        print(f"- [PID {w.get('pid')}] {w.get('title')}")
