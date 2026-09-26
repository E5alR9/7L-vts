# -*- coding: utf-8 -*-
"""
==============================================================================
 🧪 DeepSeek 智慧體測試與閉環執行框架 (DeepSeek Agent & Eval Harness)
 專為 7L 虛擬機打造 · 自主推導、自動生成測試、自執行、自我修復 (Self-Correction Loop)
==============================================================================
"""

import os
import sys
import time
import json
import subprocess
from dotenv import load_dotenv

ENV_FILE = "C:\\AI_Agents\\.env"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE)
else:
    load_dotenv()

# Rich 介面美化
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    console = Console()
except ImportError:
    class DummyConsole:
        def print(self, *args, **kwargs): print(*args)
    console = DummyConsole()

WORKSPACE_DIR = "C:\\AI_Agents\\harness_workspace"
os.makedirs(WORKSPACE_DIR, exist_ok=True)

def get_deepseek_client():
    from openai import OpenAI
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    github_token = os.getenv("GITHUB_TOKEN", "").strip()

    if deepseek_key:
        return OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com"), "deepseek-reasoner", "DeepSeek 官方 API"
    elif openrouter_key:
        return OpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"HTTP-Referer": "https://github.com/7L", "X-Title": "7L DeepSeek Harness"}
        ), "deepseek/deepseek-r1:free", "OpenRouter Free Tier (DeepSeek R1 :free)"
    elif github_token:
        return OpenAI(
            api_key=github_token,
            base_url="https://models.inference.ai.azure.com"
        ), "DeepSeek-R1", "GitHub Models (DeepSeek R1)"
    return None, None, None

def run_in_sandbox(script_path: str, timeout: int = 30) -> dict:
    """在隔離沙盒中執行代碼並收集 stdout, stderr, returncode, 執行時間"""
    start_t = time.time()
    try:
        res = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=WORKSPACE_DIR,
            encoding="utf-8",
            errors="replace"
        )
        dur = time.time() - start_t
        return {
            "success": res.returncode == 0,
            "returncode": res.returncode,
            "stdout": res.stdout.strip(),
            "stderr": res.stderr.strip(),
            "duration": round(dur, 3)
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"執行逾時 (超過 {timeout} 秒)",
            "duration": timeout
        }
    except Exception as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"執行異常: {e}",
            "duration": round(time.time() - start_t, 3)
        }

def run_agent_harness_loop(task_description: str, max_iterations: int = 4):
    """
    【DeepSeek Agent Harness 閉環迴圈】：
    1. DeepSeek R1 深度長鏈思考 (Reasoning)
    2. 生成包含單元測試與自我驗證的 Python 代碼
    3. Harness 沙盒執行並收集結果
    4. 若有錯誤，Harness 將報錯回傳給 DeepSeek 進行 Self-Correction 自我修復
    5. 直到 100% 測試通過或達到最大迭代次數！
    """
    client, model_name, provider_name = get_deepseek_client()
    if not client:
        print("[❌ 錯誤] 未找到 API Key，請檢查 C:\\AI_Agents\\.env。")
        return

    print("\n" + "=" * 70)
    print(f" 🧪 【DeepSeek Harness 閉環測試啟動】")
    print(f" 📡 通道: {provider_name} | 模型: {model_name}")
    print(f" 🎯 目標任務: {task_description}")
    print("=" * 70)

    system_prompt = """妳是運行在自動化評測環境 (Agent Harness) 中的 DeepSeek R1 頂級編程智能體。
妳的任務是針對使用者的需求，寫出【100% 可執行、具備自測斷言 (Assertions / Unit Tests) 的完整 Python 腳本】。
規則：
1. 進行嚴密的算法推導與架構規劃。
2. 在輸出代碼的最後，必須包含自我測試函式（例如 test_solution()）使用 assert 驗證邊界條件與案例。
3. 腳本在正常執行完畢時印出 '=== ALL TESTS PASSED ==='。
4. 輸出代碼請嚴格包裹在 ```python 與 ``` 之中。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"【任務目標】：\n{task_description}\n請給出完整可運行的實現與自測代碼。"}
    ]

    for iteration in range(1, max_iterations + 1):
        print(f"\n🔄 ═════════ 迭代輪次 [{iteration}/{max_iterations}] ═════════")
        print("🧠 [DeepSeek R1 正在進行深度推理思考 (Reasoning)...]\n")

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=True
            )

            full_reply = ""
            reasoning_text = ""
            is_content = False

            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_text += delta.reasoning_content
                    sys.stdout.write(delta.reasoning_content)
                    sys.stdout.flush()
                elif hasattr(delta, "content") and delta.content:
                    if reasoning_text and not is_content:
                        print("\n\n" + "-" * 50)
                        print("💡 [DeepSeek 產出代碼與解決方案]:\n")
                        is_content = True
                    full_reply += delta.content
                    sys.stdout.write(delta.content)
                    sys.stdout.flush()

            print("\n" + "-" * 50)

            # 提取 Python 代碼
            code = ""
            if "```python" in full_reply:
                blocks = full_reply.split("```python")
                code = blocks[1].split("```")[0].strip()
            elif "```" in full_reply:
                blocks = full_reply.split("```")
                code = blocks[1].strip()

            if not code:
                print("[⚠️ 警告] 未在回答中偵測到 Python 代碼區塊。")
                break

            # 寫入沙盒檔案
            script_path = os.path.join(WORKSPACE_DIR, f"solution_iter_{iteration}.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            print(f"\n⚙️ [Harness 沙盒執行中] 檔案: {script_path}")
            exec_result = run_in_sandbox(script_path)

            print(f"⏱️ 執行耗時: {exec_result['duration']}s | 狀態碼: {exec_result['returncode']}")
            if exec_result['stdout']:
                print(f"📋 STDOUT:\n{exec_result['stdout']}")

            # 判斷是否測試通過
            if exec_result['success'] and ("ALL TESTS PASSED" in exec_result['stdout'] or exec_result['returncode'] == 0):
                print("\n" + "=" * 70)
                print(f" 🎉 【Harness 測試全數通過！】在第 {iteration} 輪迭代達成完美閉環！")
                print(f" 📁 最終通過代碼已保存至: {script_path}")
                print("=" * 70)
                break
            else:
                print(f"\n❌ [測試未完全通過 / 報錯]:\n{exec_result['stderr']}")
                if iteration < max_iterations:
                    print("\n🔁 [觸發 Self-Correction] 將執行報錯與反饋回傳給 DeepSeek 進行自我修復...")
                    messages.append({"role": "assistant", "content": full_reply})
                    feedback = f"【Harness 執行報錯回饋 (第 {iteration} 輪)】：\nSTDOUT:\n{exec_result['stdout']}\nSTDERR:\n{exec_result['stderr']}\n請分析報錯原因並修復代碼，重新輸出完整的 ```python 代碼。"
                    messages.append({"role": "user", "content": feedback})

        except Exception as e:
            print(f"\n[❌ 呼叫異常]: {e}")
            break

def run_benchmark_eval():
    """內建微型基準測試評測模式 (Mini Coding Benchmark Harness)"""
    print("\n" + "=" * 70)
    print(" 📊 【DeepSeek 基準測試套件 (Benchmark Eval Harness)】")
    print("=" * 70)
    benchmark_tasks = [
        "實現 LRU Cache (最近最少使用快取機制)，包含 get 與 put 操作，時間複雜度必須為 O(1)，並附帶極限邊界測試案例。",
        "給定一個含有正負數的整數陣列，找出乘積最大的連續子陣列 (Maximum Product Subarray)，時間複雜度 O(n)，並包含多組極端測試。",
        "實現一個多線程安全 (Thread-Safe) 的生產者-消費者優先級任務隊列，並包含多線程併發測試斷言。"
    ]

    for i, t in enumerate(benchmark_tasks, start=1):
        print(f"\n>>> 進行基準測試題 [{i}/{len(benchmark_tasks)}]: {t[:40]}...")
        run_agent_harness_loop(t, max_iterations=3)
        time.sleep(2)

def main():
    print("""
 ╔═══════════════════════════════════════════════════════════════╗
 ║        🧪 DeepSeek Agent & Eval Harness (閉環測試框架)         ║
 ║    自動生成測試 · 沙盒執行 · 報錯自我修復 (Self-Correction Loop)    ║
 ╚═══════════════════════════════════════════════════════════════╝
    """)

    while True:
        print("\n【📋 Harness 模式選單】：")
        print(" [1] 🎯 自訂任務/演算法閉環求解 (Auto-Solve & Self-Correct)")
        print(" [2] 📊 執行標準程式基準評測 (Run Benchmark Suite)")
        print(" [0] 🚪 退出 Harness\n")

        choice = input("👉 請選擇功能 (1/2, 或 0 退出): ").strip()
        if choice == "0":
            break
        elif choice == "2":
            run_benchmark_eval()
        elif choice == "1":
            task = input("\n👉 請輸入你想交給 DeepSeek Harness 挑戰的演算法或任務: ").strip()
            if not task:
                task = "設計一個高並發快速排序演算法 (Parallel QuickSort)，並附帶 10 萬筆隨機數據的排序驗證自測斷言。"
            run_agent_harness_loop(task)

if __name__ == "__main__":
    main()
