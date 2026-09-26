# -*- coding: utf-8 -*-
"""
======================================================
 🧠 DeepSeek R1 專屬智能體 (GitHub Models 官方免費版)
 專為 7L 虛擬機打造 · 100% 透過 GitHub Models 免費調用 DeepSeek-R1
======================================================
"""

import os
import sys
import io
import subprocess
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ENV_FILE = "C:\\AI_Agents\\.env"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE)
else:
    load_dotenv()

from free_ai_client import get_free_ai_client

def execute_code(code: str, language: str = "python") -> str:
    """在虛擬機中執行代碼並返回結果"""
    if language == "python":
        temp_file = "C:\\AI_Agents\\temp_task.py"
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            res = subprocess.run([sys.executable, temp_file], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
            out = res.stdout
            if res.stderr:
                out += "\n[錯誤訊息]: " + res.stderr
            return out.strip() if out.strip() else "[執行完成，無輸出]"
        except Exception as e:
            return f"[執行錯誤]: {e}"
    elif language in ["powershell", "ps1", "cmd", "bash"]:
        try:
            res = subprocess.run(["powershell.exe", "-NoProfile", "-Command", code], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
            out = res.stdout
            if res.stderr:
                out += "\n[錯誤訊息]: " + res.stderr
            return out.strip() if out.strip() else "[執行完成，無輸出]"
        except Exception as e:
            return f"[執行錯誤]: {e}"
    return "[不支援的語言類型]"

def chat_with_deepseek(prompt: str):
    client, model_name = get_free_ai_client(task_type="reasoning")
    if not client:
        print("[❌ 錯誤] 無法建立連線，請檢查 C:\\AI_Agents\\.env 的 GITHUB_TOKEN。")
        return

    print("=" * 60)
    print("🧠 [DeepSeek-R1 正在進行深度長鏈推理 (Reasoning CoT)...]\n")

    system_prompt = """妳是運行在 Windows 本機中的 DeepSeek R1 全權自主智能體（透過 GitHub Models 免費 API 驅動）。
妳擁有頂級的邏輯推理、系統編程與代碼執行能力。
當使用者提出問題、任務或需求時：
1. 進行深入的邏輯推導與架構規劃。
2. 若需要透過寫程式或執行終端命令來完成任務，請輸出標準的代碼區塊：
   - Python 代碼請用 ```python
   - PowerShell 命令請用 ```powershell
3. 給予簡潔、清晰且專業的回答。"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            stream=True
        )

        reasoning_text = ""
        content_text = ""
        is_content_started = False

        for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # 1. 深度思考
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_text += delta.reasoning_content
                sys.stdout.write(delta.reasoning_content)
                sys.stdout.flush()
            # 2. 最終內容
            elif hasattr(delta, "content") and delta.content:
                if reasoning_text and not is_content_started:
                    print("\n\n" + "=" * 60)
                    print("💡 [DeepSeek-R1 最終方案與回應]:\n")
                    is_content_started = True
                content_text += delta.content
                sys.stdout.write(delta.content)
                sys.stdout.flush()

        print("\n\n" + "=" * 60)

        # 3. 程式碼自執行判斷
        if "```python" in content_text:
            blocks = content_text.split("```python")
            for b in blocks[1:]:
                code = b.split("```")[0].strip()
                if code:
                    print("\n⚙️ 偵測到 Python 程式碼，是否立即在虛擬機執行驗證？(Y/n): ", end="")
                    choice = input().strip().lower()
                    if choice in ["", "y", "yes"]:
                        print("🚀 正在執行代碼...")
                        out = execute_code(code, "python")
                        print(f"\n🖥️ [虛擬機執行結果]:\n{out}\n")
                    break

        elif "```powershell" in content_text:
            blocks = content_text.split("```powershell")
            for b in blocks[1:]:
                code = b.split("```")[0].strip()
                if code:
                    print("\n⚙️ 偵測到 PowerShell 指令，是否立即在虛擬機執行？(Y/n): ", end="")
                    choice = input().strip().lower()
                    if choice in ["", "y", "yes"]:
                        print("🚀 正在執行命令...")
                        out = execute_code(code, "powershell")
                        print(f"\n🖥️ [虛擬機執行結果]:\n{out}\n")
                    break

    except Exception as e:
        print(f"\n[❌ 連線異常]: {e}")

def main():
    print("""
 ╔═══════════════════════════════════════════════════════════════╗
 ║        🐙 DeepSeek R1 智能體控制台 (GitHub Models 免費版)      ║
 ║      深度長鏈推理 (Reasoning CoT) · 自主寫代碼 · 本地執行驗證     ║
 ╚═══════════════════════════════════════════════════════════════╝
    """)

    while True:
        try:
            print("\n" + "-" * 60)
            user_input = input("👉 請輸入你的指令或問題 (輸入 'q' 退出): ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["q", "quit", "exit"]:
                print("\n👋 DeepSeek 智能體已結束運作。")
                break

            chat_with_deepseek(user_input)
        except KeyboardInterrupt:
            print("\n\n👋 已中斷當前對話。")
            break
        except Exception as e:
            print(f"\n[❌ 錯誤]: {e}")

if __name__ == "__main__":
    main()
