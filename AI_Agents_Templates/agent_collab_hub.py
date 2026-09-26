# -*- coding: utf-8 -*-
"""
🌟 7L AI 智能體協同大廳 (7L Multi-Agent Collaboration Hub)
整合 Open Interpreter, Browser-Use, CrewAI, AutoGen, LangGraph 於一體
讓多個 AI 智能體在 7L 的專屬電腦上自由分工、協同探索、操作系統！
"""

import os
import sys
import time
import subprocess
from dotenv import load_dotenv

load_dotenv()

# Rich 美化輸出
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
except ImportError:
    class DummyConsole:
        def print(self, *args, **kwargs): print(*args)
    console = DummyConsole()

AGENTS_MENU = [
    {
        "id": "1",
        "name": "🌐 Browser-Use 網頁自主操作智能體",
        "script": "browser_agent.py",
        "desc": "自主打開瀏覽器、看網頁、點擊、搜尋與收集網路資料"
    },
    {
        "id": "2",
        "name": "💻 Open Interpreter 電腦系統操控智能體",
        "script": "system_interpreter.py",
        "desc": "以自然語言全權操控虛擬機終端機、讀寫檔案、執行 Python 程式碼"
    },
    {
        "id": "3",
        "name": "👥 CrewAI 多智能體夢幻戰隊 (7L 隊長 + 研究員 + 工程師)",
        "script": "crew_team.py",
        "desc": "多個不同角色的 AI 互相分工、研討、寫代碼並總結"
    },
    {
        "id": "4",
        "name": "🤖 Microsoft AutoGen 對話式自我迭代智能體",
        "script": "autogen_chat.py",
        "desc": "AI 助手與本地執行器互相 Debug、自動在終端機跑代碼修復 Bug"
    },
    {
        "id": "5",
        "name": "🧠 DeepSeek R1 深度推理與自主編程智能體",
        "script": "deepseek_agent.py",
        "desc": "以強大長鏈思維鏈 (Reasoning CoT) 深度分析複雜問題，自動編寫並在電腦運行 Python 代碼"
    }
]

def show_banner():
    msg = """
  ╔═══════════════════════════════════════════════════════════════╗
  ║    🤖 7L 專屬虛擬機 · 多智能體協同中心 (Multi-Agent Hub)      ║
  ║      讓多個 AI Agent 一起操控這台電腦、探索、寫代碼與協同玩耍    ║
  ╚═══════════════════════════════════════════════════════════════╝
    """
    print(msg)

def display_menu():
    print("\n【📋 可用智能體與協同模式清單】：")
    for item in AGENTS_MENU:
        print(f" [{item['id']}] {item['name']}")
        print(f"     💡 說明: {item['desc']}")
    print(" [0] 🚪 退出大廳\n")

def main():
    show_banner()
    while True:
        display_menu()
        choice = input("👉 請選擇要召喚的智能體模式 (1-5, 或 0 退出): ").strip()
        if choice == "0":
            print("\n👋 感謝使用，7L 智能體大廳已休眠！")
            break

        selected = next((item for item in AGENTS_MENU if item["id"] == choice), None)
        if not selected:
            print("[⚠️ 無效選擇] 請輸入 1 到 5 之間的數字。")
            continue

        print(f"\n✨ 已召喚: {selected['name']}")
        custom_prompt = input(f"👉 請輸入想交給該智能體的任務 (直接按 Enter 使用預設任務): ").strip()

        script_path = os.path.join(os.path.dirname(__file__), selected["script"])
        cmd = [sys.executable, script_path]
        if custom_prompt:
            cmd.append(custom_prompt)

        print(f"\n⚙️ 正在啟動 {selected['script']}...\n")
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            print("\n[!] 使用者手動中斷任務。")
        except Exception as e:
            print(f"[❌ 執行出錯] {e}")

        print("\n" + "="*50)

if __name__ == "__main__":
    main()
