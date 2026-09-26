# -*- coding: utf-8 -*-
"""
2. 💻 Open Interpreter 智能體 (OS Computer Use Agent)
讓 AI 能在電腦上自由執行 Python, PowerShell, Shell, 操作系統檔案與應用程式
"""

import os
from dotenv import load_dotenv

load_dotenv()

def run_interpreter_task(task_description: str):
    try:
        import interpreter
        interpreter.auto_run = True  # 自動執行，不需每次手動按 y
        
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS", "").split(",")[0]
        openai_key = os.getenv("OPENAI_API_KEY")
        
        if gemini_key:
            interpreter.llm.model = "gemini/gemini-1.5-flash"
            interpreter.llm.api_key = gemini_key
        elif openai_key:
            interpreter.llm.model = "gpt-4o"
            interpreter.llm.api_key = openai_key
            
        print(f"🚀 [Open Interpreter] 正在執行電腦操作: {task_description}")
        interpreter.chat(task_description)
    except Exception as e:
        print(f"[❌ 錯誤] Open Interpreter 執行失敗: {e}")

if __name__ == "__main__":
    import sys
    task = sys.argv[1] if len(sys.argv) > 1 else "檢查當前系統規格，列出桌面上的所有檔案，並在桌面上建立一個 7L_greeting.txt 寫入一段可愛的問候！"
    run_interpreter_task(task)
