# -*- coding: utf-8 -*-
"""
🌟 100% GitHub Models 免費 API 專用中樞 (GitHub Models Free Provider)
專為 7L 虛擬機設計，以 GitHub 官方免費端點作為第一優先核心！
端點: https://models.inference.ai.azure.com
支援模型: DeepSeek-R1, gpt-4o-mini, gpt-4o, Meta-Llama-3.3-70B-Instruct, Phi-4
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv("C:\\AI_Agents\\.env")
load_dotenv()

# GitHub Models 官方端點
GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

def get_free_ai_client(task_type: str = "reasoning"):
    """
    以 GitHub Models 免費 API 為核心第一優先！
    task_type: 'reasoning' (DeepSeek-R1), 'coding' (gpt-4o-mini / DeepSeek-R1), 'general' (gpt-4o-mini)
    """
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_KEY")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")

    # 1. 🥇 第一優先：GitHub Models 官方免費 API
    if github_token:
        if task_type == "reasoning":
            model = "DeepSeek-R1"
        elif task_type == "coding":
            model = "DeepSeek-R1"
        else:
            model = "gpt-4o-mini"

        try:
            print(f"[GitHub Models] 正在調用: {model}")
        except Exception:
            pass
        return OpenAI(
            api_key=github_token,
            base_url=GITHUB_MODELS_ENDPOINT
        ), model

    # 2. 🥈 第二優先：OpenRouter API (支援 DeepSeek R1 / V3)
    openrouter_keys = os.getenv("OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEYS", "")
    if openrouter_keys:
        op_key = openrouter_keys.split(",")[0].strip().strip('"').strip("'")
        if op_key:
            model = "deepseek/deepseek-r1" if task_type == "reasoning" else "deepseek/deepseek-chat"
            try:
                print(f"[OpenRouter API] 正在調用: {model}")
            except Exception:
                pass
            return OpenAI(
                api_key=op_key,
                base_url="https://openrouter.ai/api/v1"
            ), model

    # 3. 🥉 第三優先：DeepSeek 官方 API
    if deepseek_key:
        model = "deepseek-reasoner" if task_type == "reasoning" else "deepseek-chat"
        try:
            print(f"[DeepSeek 官方 API] 正在調用: {model}")
        except Exception:
            pass
        return OpenAI(
            api_key=deepseek_key,
            base_url="https://api.deepseek.com"
        ), model

    # 4. 備用：Groq API
    groq_keys = os.getenv("GROQ_API_KEYS", "") or os.getenv("GROQ_API_KEY", "")
    if groq_keys:
        g_key = groq_keys.split(",")[0].strip().strip('"').strip("'")
        if g_key:
            model = "openai/gpt-oss-120b" if task_type == "reasoning" else "qwen/qwen3.6-27b"
            try:
                print(f"[Groq API] 正在調用: {model}")
            except Exception:
                pass
            return OpenAI(
                api_key=g_key,
                base_url="https://api.groq.com/openai/v1"
            ), model

    try:
        print("\n[提示] 未在 .env 找到有效金鑰！")
    except Exception:
        pass
    return None, None
