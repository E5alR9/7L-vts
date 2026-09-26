import os
import re
import sys
import time
import json
import base64
import io
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageDraw

# Set UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

load_dotenv()

# 1. 讀取金鑰矩陣
gemini_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip()]
groq_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY") or "") if k.strip()]
openrouter_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("OPENROUTER_API_KEYS") or os.getenv("OPENROUTER_API_KEY") or "") if k.strip()]

print("=" * 85)
print("⚡ 【全環境 API & 全模型全方法 100% 全併發思考與響應時間急速基準測試】")
print(f"   • Google Gemini 金鑰數: {len(gemini_keys)} 把 (輪詢併發)")
print(f"   • Groq 金鑰數: {len(groq_keys)} 把 (輪詢併發)")
print(f"   • OpenRouter 金鑰數: {len(openrouter_keys)} 把")
print("=" * 85 + "\n")

from google import genai
from google.genai import types
from groq import AsyncGroq

# 2. 生成測試用圖片
def generate_test_image(text_label: str, bg_color=(40, 44, 52), fg_color=(255, 255, 255), width=640, height=360) -> bytes:
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width-20, height-20], outline=(100, 149, 237), width=3)
    draw.rectangle([50, 50, 250, 180], fill=(70, 130, 180), outline=(255, 255, 255), width=2)
    draw.ellipse([width-220, 80, width-60, 240], fill=(219, 112, 147), outline=(255, 255, 255), width=2)
    draw.text((60, 280), f"7L Multi-Modal Test: {text_label}", fill=fg_color)
    draw.text((60, 310), f"Timestamp: {time.strftime('%H:%M:%S')}", fill=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

TEST_IMG_1 = generate_test_image("Single View Capture", bg_color=(35, 45, 60))
TEST_IMG_5_LIST = [
    generate_test_image(f"View {i+1}/5 - Angle {i*72} deg", bg_color=(30 + i*15, 40 + i*10, 60 + i*20))
    for i in range(5)
]

SAMPLE_TOOL = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="trigger_vts_expression",
        description="切換 7L (Live2D 模型) 的臉部表情",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "expression_name": types.Schema(
                    type=types.Type.STRING,
                    description="要切換的表情名稱，例如 '星星眼', '臉紅', '生氣'"
                )
            },
            required=["expression_name"]
        )
    )
])

# 3. 測試模型清單
GEMINI_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it"
]

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "groq/compound",
    "groq/compound-mini",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant"
]

all_results = []
lock = asyncio.Lock()

# 4. 非同步測試 Worker：Gemini
async def async_test_gemini(model_name: str, method_name: str, contents, key_index: int, config=None):
    if not gemini_keys:
        return
    key = gemini_keys[key_index % len(gemini_keys)]
    client = genai.Client(api_key=key)
    
    start_time = time.time()
    try:
        if config:
            resp = await client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
        else:
            resp = await client.aio.models.generate_content(
                model=model_name,
                contents=contents
            )
        latency = time.time() - start_time
        
        out_text = getattr(resp, 'text', '') or ''
        fn_calls = getattr(resp, 'function_calls', []) or []
        summary = (out_text.strip()[:65].replace("\n", " ") if out_text else (f"[Tool: {fn_calls[0].name}]" if fn_calls else ""))
        
        res = {
            "provider": "Google",
            "model": model_name,
            "method": method_name,
            "status": "SUCCESS",
            "latency": round(latency, 3),
            "output": summary,
            "key_used": f"Key#{key_index % len(gemini_keys) + 1}",
            "error": None
        }
    except Exception as e:
        latency = time.time() - start_time
        err_msg = str(e)
        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            status = "429_LIMIT"
        elif "503" in err_msg:
            status = "503_HIGH_DEMAND"
        elif "404" in err_msg:
            status = "404_NOT_FOUND"
        elif "400" in err_msg:
            status = "400_BAD_REQ"
        else:
            status = "ERROR"
            
        res = {
            "provider": "Google",
            "model": model_name,
            "method": method_name,
            "status": status,
            "latency": round(latency, 3),
            "output": "",
            "key_used": f"Key#{key_index % len(gemini_keys) + 1}",
            "error": err_msg[:100]
        }

    async with lock:
        all_results.append(res)
        sym = "✅" if res["status"] == "SUCCESS" else ("⚠️" if "429" in res["status"] or "503" in res["status"] else "❌")
        desc = res["output"] if res["status"] == "SUCCESS" else res["error"]
        print(f"[{res['provider']:<6}] {res['model']:<24} | {res['method']:<18} | ⏱️ {res['latency']:<6.2f}s | {sym} {res['status']:<15} | {desc[:60]}")

# 5. 非同步測試 Worker：Groq
async def async_test_groq(model_name: str, method_name: str, messages, key_index: int):
    if not groq_keys:
        return
    key = groq_keys[key_index % len(groq_keys)]
    client = AsyncGroq(api_key=key)
    
    start_time = time.time()
    try:
        resp = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        latency = time.time() - start_time
        choice = resp.choices[0] if resp.choices else None
        out_text = choice.message.content if choice and choice.message else ""
        
        res = {
            "provider": "Groq",
            "model": model_name,
            "method": method_name,
            "status": "SUCCESS",
            "latency": round(latency, 3),
            "output": out_text.strip()[:65].replace("\n", " "),
            "key_used": f"GroqKey#{key_index % len(groq_keys) + 1}",
            "error": None
        }
    except Exception as e:
        latency = time.time() - start_time
        err_msg = str(e)
        status = "429_LIMIT" if "429" in err_msg else "ERROR"
        res = {
            "provider": "Groq",
            "model": model_name,
            "method": method_name,
            "status": status,
            "latency": round(latency, 3),
            "output": "",
            "key_used": f"GroqKey#{key_index % len(groq_keys) + 1}",
            "error": err_msg[:100]
        }

    async with lock:
        all_results.append(res)
        sym = "✅" if res["status"] == "SUCCESS" else ("⚠️" if "429" in res["status"] else "❌")
        desc = res["output"] if res["status"] == "SUCCESS" else res["error"]
        print(f"[{res['provider']:<6}] {res['model']:<24} | {res['method']:<18} | ⏱️ {res['latency']:<6.2f}s | {sym} {res['status']:<15} | {desc[:60]}")

# 6. 主協程：同時組裝並發起所有任務
async def main():
    tasks = []
    k_idx = 0
    
    # 準備 5 圖內容
    img5_contents = []
    for idx, img_b in enumerate(TEST_IMG_5_LIST):
        img5_contents.append(f"\n【視角 {idx+1}/5】：")
        img5_contents.append(types.Part.from_bytes(data=img_b, mime_type="image/jpeg"))
    img5_contents.append("請綜合評估這 5 個連續視角的變化與特徵。")
    
    # 準備 1 圖內容
    img1_contents = [
        types.Part.from_bytes(data=TEST_IMG_1, mime_type="image/jpeg"),
        "請簡短描述此畫面中的幾何元素與色彩。"
    ]
    
    tool_cfg = types.GenerateContentConfig(tools=[SAMPLE_TOOL], temperature=0.2)
    fast_thinking_cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0))

    print(f"🚀 開始向 Google Gemini & Groq 同時發起所有併發請求...\n")
    start_all = time.time()

    # A. Gemini 模型矩陣 (純文字、1圖、5圖、工具調用、0秒極速思考)
    for m in GEMINI_MODELS:
        # 1. 純文字
        k_idx += 1
        tasks.append(async_test_gemini(m, "純文字 (Text)", ["請用一句話簡短介紹你是誰與你的核心特長。"], k_idx))
        
        # 2. 1 圖視覺
        k_idx += 1
        tasks.append(async_test_gemini(m, "單圖視覺 (1 Image)", img1_contents, k_idx))
        
        # 3. 5 圖多視角
        k_idx += 1
        tasks.append(async_test_gemini(m, "5圖多視角 (5 Images)", img5_contents, k_idx))
        
        # 4. 工具調用
        k_idx += 1
        tasks.append(async_test_gemini(m, "工具調用 (Tool Call)", ["請把 7L 的表情切換為星星眼。"], k_idx, config=tool_cfg))
        
        # 5. 思考預算 0 秒 (適用 3.7, 3.5)
        if any(x in m for x in ["3.7", "3.5-flash"]):
            k_idx += 1
            tasks.append(async_test_gemini(m, "思考預算 0 (Fast 0s)", ["請回答 1+1 等於多少？"], k_idx, config=fast_thinking_cfg))

    # B. Groq 模型矩陣 (超高速純文字)
    for gm in GROQ_MODELS:
        k_idx += 1
        tasks.append(async_test_groq(
            gm, 
            "純文字 (Text)", 
            [{"role": "user", "content": "請用一句話簡短介紹你是誰與你的核心特長。"}], 
            k_idx
        ))

    print(f"📊 總計併發任務數: {len(tasks)} 個請求，分攤於 {len(gemini_keys)} 把 Gemini 與 {len(groq_keys)} 把 Groq 金鑰！")
    print("-" * 105)
    
    # 🌟 全面同時併發執行！
    await asyncio.gather(*tasks)
    
    total_elapsed = time.time() - start_all
    print("-" * 105)
    print(f"\n🎉 【所有 {len(tasks)} 個模型與方法測試已於 {total_elapsed:.2f} 秒內全部完成！】\n")

    # 7. 儲存結果 JSON
    with open("benchmark_concurrent_result.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
