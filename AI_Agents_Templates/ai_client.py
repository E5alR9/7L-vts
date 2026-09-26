# -*- coding: utf-8 -*-
"""
🌟 7L 專屬電腦 - Google Gemini 嚴選旗艦大腦中樞
嚴格限定只調用以下四大模型，絕不佔用或調用其他任何模型：
  1. 👑 gemini-3.7-flash (3.7 頂配旗艦大腦)
  2. 👑 gemini-3.6-flash (3.6 最新高智商主力大腦)
  3. 🧠 gemini-3.1-pro-preview (3.1 Pro 超高智商深度推理)
  4. 🥈 gemini-3.5-flash (3.5 高智商穩定主力)
"""

import os
import random
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv("C:\\AI_Agents\\.env")
load_dotenv()

# 嚴選允許調用的 4 大模型
ALLOWED_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash"
]

def get_gemini_client(task_type: str = "general"):
    """
    獲取 Google Gemini 客戶端與模型名稱
    - 'reasoning': 優先使用 gemini-3.1-pro-preview (3.1 Pro)
    - 'coding': 優先使用 gemini-3.7-flash (3.7)
    - 'general': 優先使用 gemini-3.6-flash (3.6)
    - 'fast': 優先使用 gemini-3.5-flash (3.5)
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        keys_str = os.getenv("GEMINI_API_KEYS", "")
        if keys_str:
            gemini_key = keys_str.split(",")[0].strip()

    if not gemini_key:
        print("[⚠️ 提示] 未在 C:\\AI_Agents\\.env 找到 GEMINI_API_KEY！")
        return None, None

    if task_type == "reasoning":
        model_name = "gemini-3.1-pro-preview"
    elif task_type == "coding":
        model_name = "gemini-3.7-flash"
    elif task_type == "general":
        model_name = "gemini-3.6-flash"
    else:
        model_name = "gemini-3.5-flash"

    # 確保嚴格在四者之內
    if model_name not in ALLOWED_MODELS:
        model_name = "gemini-3.6-flash"

    client = OpenAI(
        api_key=gemini_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    return client, model_name
