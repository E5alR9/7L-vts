# -*- coding: utf-8 -*-
"""
1. 🌐 Browser-Use 智能體 (100% 免費 API 專用版)
讓 AI 能自主操作 Chrome/Chromium 瀏覽器，使用 OpenRouter Free Tier (DeepSeek R1 / Llama 3.3) 驅動！
"""

import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

try:
    from browser_use import Agent
    from browser_use.browser.browser import Browser, BrowserConfig
    from langchain_openai import ChatOpenAI
    HAS_BROWSER_USE = True
except ImportError:
    HAS_BROWSER_USE = False

async def run_browser_task(task_description: str, headless: bool = False):
    if not HAS_BROWSER_USE:
        print("[❌ 錯誤] 請先安裝 browser-use: pip install browser-use playwright && playwright install")
        return

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    github_token = os.getenv("GITHUB_TOKEN")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")

    if openrouter_key:
        llm = ChatOpenAI(
            model="deepseek/deepseek-r1:free",
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1"
        )
    elif github_token:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=github_token,
            base_url="https://models.inference.ai.azure.com"
        )
    elif deepseek_key:
        llm = ChatOpenAI(
            model="deepseek-chat",
            api_key=deepseek_key,
            base_url="https://api.deepseek.com"
        )
    else:
        print("[⚠️ 警告] 請在 C:\\AI_Agents\\.env 設定 OPENROUTER_API_KEY 或 GITHUB_TOKEN")
        return

    browser = Browser(config=BrowserConfig(headless=headless))
    agent = Agent(
        task=task_description,
        llm=llm,
        browser=browser
    )

    print(f"🚀 [Browser Agent 免費版] 正在執行任務: {task_description}")
    history = await agent.run(max_steps=25)
    print("🎉 [Browser Agent] 任務完成！")
    return history

if __name__ == "__main__":
    import sys
    task = sys.argv[1] if len(sys.argv) > 1 else "打開 Google 搜尋 'Hello from 7L AI Free Agent' 並在畫面上停留 5 秒"
    asyncio.run(run_browser_task(task, headless=False))
