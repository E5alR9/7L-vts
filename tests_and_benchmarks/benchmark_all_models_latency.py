import os
import re
import sys
import time
import json
import base64
import io
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# Set UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

load_dotenv()

# 1. 讀取與解析所有金鑰
gemini_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip()]
groq_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY") or "") if k.strip()]
openrouter_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("OPENROUTER_API_KEYS") or os.getenv("OPENROUTER_API_KEY") or "") if k.strip()]

print("=" * 70)
print("🚀 【全環境 API & 全模型全方法思考與響應時間全面基準測試】")
print(f"   • Google Gemini 金鑰數: {len(gemini_keys)}")
print(f"   • Groq 金鑰數: {len(groq_keys)}")
print(f"   • OpenRouter 金鑰數: {len(openrouter_keys)}")
print("=" * 70 + "\n")

from google import genai
from google.genai import types
from groq import Groq

# 2. 生成測試用圖片 (單圖與 5 視角圖)
def generate_test_image(text_label: str, bg_color=(40, 44, 52), fg_color=(255, 255, 255), width=640, height=360) -> bytes:
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # 畫一些幾何圖形模擬畫面
    draw.rectangle([20, 20, width-20, height-20], outline=(100, 149, 237), width=3)
    draw.rectangle([50, 50, 250, 180], fill=(70, 130, 180), outline=(255, 255, 255), width=2)
    draw.ellipse([width-220, 80, width-60, 240], fill=(219, 112, 147), outline=(255, 255, 255), width=2)
    
    # 標籤文字
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

# 工具調用定義
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

# 3. 獲取 Google 與 Groq 模型清單
PRIMARY_GEMINI_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it"
]

PRIMARY_GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "groq/compound",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant"
]

# 擴充線上模型
live_gemini_models = []
if gemini_keys:
    for k in gemini_keys:
        try:
            c = genai.Client(api_key=k)
            for m in c.models.list():
                c_name = m.name.replace("models/", "")
                if "gemini" in c_name or "gemma" in c_name:
                    if not any(x in c_name for x in ["embed", "audio", "imagen", "robotics", "computer-use"]):
                        live_gemini_models.append(c_name)
            break
        except Exception:
            continue

live_groq_models = []
if groq_keys:
    for k in groq_keys:
        try:
            gc = Groq(api_key=k)
            for gm in gc.models.list().data:
                if not any(x in gm.id for x in ["whisper", "guard", "orpheus"]):
                    live_groq_models.append(gm.id)
            break
        except Exception:
            continue

# 合併去重
all_gemini_to_test = list(dict.fromkeys(PRIMARY_GEMINI_MODELS + live_gemini_models))
all_groq_to_test = list(dict.fromkeys(PRIMARY_GROQ_MODELS + live_groq_models))

print(f"📋 準備測試的 Gemini 模型數量: {len(all_gemini_to_test)}")
print(f"📋 準備測試的 Groq 模型數量: {len(all_groq_to_test)}\n")

results = []

# 輔助測試函數：Gemini 呼叫
def run_gemini_test(model_name: str, test_type: str, contents, config=None, client_key_idx=0):
    if not gemini_keys:
        return {"status": "NO_KEY", "latency": 0, "error": "無可用 Gemini 金鑰"}
    
    key = gemini_keys[client_key_idx % len(gemini_keys)]
    client = genai.Client(api_key=key)
    
    start_time = time.time()
    try:
        if config:
            resp = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
        else:
            resp = client.models.generate_content(
                model=model_name,
                contents=contents
            )
        latency = time.time() - start_time
        
        # 檢查輸出
        out_text = getattr(resp, 'text', '') or ''
        fn_calls = getattr(resp, 'function_calls', []) or []
        
        # 檢查思考 token 或 usage
        usage = getattr(resp, 'usage_metadata', None)
        prompt_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
        candidates_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0
        
        fn_str = f"[Tool: {fn_calls[0].name}]" if fn_calls else ""
        summary = (out_text.strip()[:60] if out_text else fn_str)
        
        return {
            "status": "SUCCESS",
            "latency": round(latency, 3),
            "output": summary,
            "prompt_tokens": prompt_tokens,
            "output_tokens": candidates_tokens,
            "error": None
        }
    except Exception as e:
        latency = time.time() - start_time
        err_msg = str(e)
        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            status = "429_LIMIT"
        elif "404" in err_msg or "NOT_FOUND" in err_msg:
            status = "404_NOT_FOUND"
        elif "400" in err_msg:
            status = "400_BAD_REQUEST"
        else:
            status = "ERROR"
        return {
            "status": status,
            "latency": round(latency, 3),
            "output": "",
            "prompt_tokens": 0,
            "output_tokens": 0,
            "error": err_msg[:120]
        }

# 輔助測試函數：Groq 呼叫
def run_groq_test(model_name: str, messages, client_key_idx=0):
    if not groq_keys:
        return {"status": "NO_KEY", "latency": 0, "error": "無可用 Groq 金鑰"}
    
    key = groq_keys[client_key_idx % len(groq_keys)]
    client = Groq(api_key=key)
    
    start_time = time.time()
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        latency = time.time() - start_time
        choice = resp.choices[0] if resp.choices else None
        out_text = choice.message.content if choice and choice.message else ""
        usage = getattr(resp, 'usage', None)
        prompt_tokens = getattr(usage, 'prompt_tokens', 0) if usage else 0
        completion_tokens = getattr(usage, 'completion_tokens', 0) if usage else 0
        
        return {
            "status": "SUCCESS",
            "latency": round(latency, 3),
            "output": out_text.strip()[:60] if out_text else "",
            "prompt_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "error": None
        }
    except Exception as e:
        latency = time.time() - start_time
        err_msg = str(e)
        status = "429_LIMIT" if "429" in err_msg else "ERROR"
        return {
            "status": status,
            "latency": round(latency, 3),
            "output": "",
            "prompt_tokens": 0,
            "output_tokens": 0,
            "error": err_msg[:120]
        }

# ────────────────────────────────────────────────────────────
# 4. 開始執行各維度測試
# ────────────────────────────────────────────────────────────
key_rotator = 0

print("=" * 90)
print(f"{'模型名稱':<30} | {'測試方法':<18} | {'耗時(秒)':<8} | {'狀態':<10} | {'輸出摘要 / 錯誤訊息'}")
print("=" * 90)

# A. 測試所有 Gemini 模型的 4 大方法
for m in all_gemini_to_test:
    # 1. 純文字對話測試 (Text Only)
    key_rotator += 1
    t_res = run_gemini_test(
        model_name=m,
        test_type="純文字 (Text)",
        contents=["請用一句話簡短介紹你是誰與你的核心特長。"],
        client_key_idx=key_rotator
    )
    results.append({
        "provider": "Google",
        "model": m,
        "method": "純文字 (Text)",
        **t_res
    })
    stat_sym = "✅" if t_res["status"] == "SUCCESS" else ("⚠️" if "429" in t_res["status"] else "❌")
    desc = t_res["output"] if t_res["status"] == "SUCCESS" else t_res["error"]
    print(f"{m:<30} | {'純文字 (Text)':<18} | {t_res['latency']:<8.2f} | {stat_sym} {t_res['status']:<7} | {desc}")
    
    # 若模型 404 (不存在)，則跳過後續圖形測試
    if t_res["status"] == "404_NOT_FOUND":
        continue
        
    time.sleep(0.3)

    # 2. 單張圖片多模態測試 (1 Image Vision)
    key_rotator += 1
    img1_contents = [
        types.Part.from_bytes(data=TEST_IMG_1, mime_type="image/jpeg"),
        "請簡短描述此畫面中的主要幾何元素與色彩。"
    ]
    i1_res = run_gemini_test(
        model_name=m,
        test_type="單圖視覺 (1 Image)",
        contents=img1_contents,
        client_key_idx=key_rotator
    )
    results.append({
        "provider": "Google",
        "model": m,
        "method": "單圖視覺 (1 Image)",
        **i1_res
    })
    stat_sym = "✅" if i1_res["status"] == "SUCCESS" else ("⚠️" if "429" in i1_res["status"] else "❌")
    desc = i1_res["output"] if i1_res["status"] == "SUCCESS" else i1_res["error"]
    print(f"{m:<30} | {'單圖視覺 (1 Image)':<18} | {i1_res['latency']:<8.2f} | {stat_sym} {i1_res['status']:<7} | {desc}")
    time.sleep(0.3)

    # 3. 五張圖片多視角測試 (5 Images Multi-View)
    key_rotator += 1
    img5_contents = []
    for idx, img_b in enumerate(TEST_IMG_5_LIST):
        img5_contents.append(f"\n【視角 {idx+1}/5】：")
        img5_contents.append(types.Part.from_bytes(data=img_b, mime_type="image/jpeg"))
    img5_contents.append("請綜合評估這 5 個連續視角的變化與核心特徵。")
    
    i5_res = run_gemini_test(
        model_name=m,
        test_type="5圖多視角 (5 Images)",
        contents=img5_contents,
        client_key_idx=key_rotator
    )
    results.append({
        "provider": "Google",
        "model": m,
        "method": "5圖多視角 (5 Images)",
        **i5_res
    })
    stat_sym = "✅" if i5_res["status"] == "SUCCESS" else ("⚠️" if "429" in i5_res["status"] else "❌")
    desc = i5_res["output"] if i5_res["status"] == "SUCCESS" else i5_res["error"]
    print(f"{m:<30} | {'5圖多視角 (5 Images)':<18} | {i5_res['latency']:<8.2f} | {stat_sym} {i5_res['status']:<7} | {desc}")
    time.sleep(0.3)

    # 4. 工具調用 / Function Calling 測試
    key_rotator += 1
    tool_cfg = types.GenerateContentConfig(
        tools=[SAMPLE_TOOL],
        temperature=0.2
    )
    fc_res = run_gemini_test(
        model_name=m,
        test_type="工具調用 (Tool Call)",
        contents=["請把 7L 的表情切換為星星眼。"],
        config=tool_cfg,
        client_key_idx=key_rotator
    )
    results.append({
        "provider": "Google",
        "model": m,
        "method": "工具調用 (Tool Call)",
        **fc_res
    })
    stat_sym = "✅" if fc_res["status"] == "SUCCESS" else ("⚠️" if "429" in fc_res["status"] else "❌")
    desc = fc_res["output"] if fc_res["status"] == "SUCCESS" else fc_res["error"]
    print(f"{m:<30} | {'工具調用 (Tool Call)':<18} | {fc_res['latency']:<8.2f} | {stat_sym} {fc_res['status']:<7} | {desc}")
    time.sleep(0.3)

    # 5. 思考預算優化測試 (Thinking Budget = 0 vs 1024) 對支援的模型
    if any(k in m for k in ["3.7-flash", "2.5-flash", "3.5-flash", "pro"]):
        try:
            key_rotator += 1
            tb0_cfg = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
            tb0_res = run_gemini_test(
                model_name=m,
                test_type="思考預算 0 (Fast 0s)",
                contents=["請用簡短一句話回答：1+1等於多少？"],
                config=tb0_cfg,
                client_key_idx=key_rotator
            )
            results.append({
                "provider": "Google",
                "model": m,
                "method": "思考預算 0 (Fast 0s)",
                **tb0_res
            })
            stat_sym = "✅" if tb0_res["status"] == "SUCCESS" else ("⚠️" if "429" in tb0_res["status"] else "❌")
            desc = tb0_res["output"] if tb0_res["status"] == "SUCCESS" else tb0_res["error"]
            print(f"{m:<30} | {'思考預算 0 (Fast 0s)':<18} | {tb0_res['latency']:<8.2f} | {stat_sym} {tb0_res['status']:<7} | {desc}")
        except Exception:
            pass

    print("-" * 90)

# B. 測試所有 Groq 模型
print("\n" + "=" * 90)
print("⚡ 【Groq 極速純文字模型基準測試】")
print("=" * 90)

for gm in all_groq_to_test:
    key_rotator += 1
    g_res = run_groq_test(
        model_name=gm,
        messages=[
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "請用一句話簡短介紹你是誰與你的核心特長。"}
        ],
        client_key_idx=key_rotator
    )
    results.append({
        "provider": "Groq",
        "model": gm,
        "method": "純文字 (Text)",
        **g_res
    })
    stat_sym = "✅" if g_res["status"] == "SUCCESS" else ("⚠️" if "429" in g_res["status"] else "❌")
    desc = g_res["output"] if g_res["status"] == "SUCCESS" else g_res["error"]
    print(f"{gm:<30} | {'純文字 (Text)':<18} | {g_res['latency']:<8.2f} | {stat_sym} {g_res['status']:<7} | {desc}")
    time.sleep(0.3)

# 5. 儲存結果 JSON 與 Markdown 報告
output_json = "benchmark_models_latency_result.json"
with open(output_json, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 70)
print(f"🎉 測試全部完成！結果已儲存至 {output_json}")
print("=" * 70)
