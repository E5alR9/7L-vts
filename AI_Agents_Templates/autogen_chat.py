# -*- coding: utf-8 -*-
"""
4. 🤖 Microsoft AutoGen 多智能體對話 (100% 免費 API 專用版)
使用 OpenRouter Free Tier (DeepSeek R1 / Qwen Coder / Llama 3.3) 驅動！
"""

import os
from dotenv import load_dotenv

load_dotenv()

try:
    import autogen
    HAS_AUTOGEN = True
except ImportError:
    HAS_AUTOGEN = False

def run_autogen_session(task: str):
    if not HAS_AUTOGEN:
        print("[❌ 錯誤] 請先安裝 autogen: pip install pyautogen")
        return

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    github_token = os.getenv("GITHUB_TOKEN")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")

    config_list = []
    if openrouter_key:
        config_list.append({
            "model": "deepseek/deepseek-r1:free",
            "api_key": openrouter_key,
            "base_url": "https://openrouter.ai/api/v1"
        })
    elif github_token:
        config_list.append({
            "model": "DeepSeek-R1",
            "api_key": github_token,
            "base_url": "https://models.inference.ai.azure.com"
        })
    elif deepseek_key:
        config_list.append({
            "model": "deepseek-chat",
            "api_key": deepseek_key,
            "base_url": "https://api.deepseek.com"
        })
    else:
        print("[⚠️ 提示] 請在 C:\\AI_Agents\\.env 填入 OPENROUTER_API_KEY 或 GITHUB_TOKEN")
        return

    llm_config = {"config_list": config_list, "cache_seed": 42}

    assistant = autogen.AssistantAgent(
        name="7L_AI_Assistant",
        llm_config=llm_config,
        system_message="妳是 7L 的 AI 程式助手（運行於 100% 免費 API 模式）。當寫完代碼後，請等待 UserProxy 執行回報結果。當任務徹底完成時輸出 TERMINATE。"
    )

    user_proxy = autogen.UserProxyAgent(
        name="7L_Executor_Proxy",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=8,
        is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE"),
        code_execution_config={
            "work_dir": "C:\\AI_Agents\\workspace",
            "use_docker": False
        }
    )

    print(f"🚀 [AutoGen 免費協同啟動] 正在執行自主任務: {task}")
    user_proxy.initiate_chat(assistant, message=task)

if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "寫一個 Python 腳本，繪製一個 ASCII 愛心圖案，並輸出當前系統時間與 7L 專屬簽名！"
    run_autogen_session(t)
