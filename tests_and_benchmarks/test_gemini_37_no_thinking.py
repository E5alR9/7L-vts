import os
import re
import sys
import time
import json
import io
from dotenv import load_dotenv
from PIL import Image, ImageDraw

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

load_dotenv()

gemini_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip()]

print("=" * 85)
print(f"👑 【Gemini 3.7 Flash 深度專項測試：關閉深度思考 (Budget = 0) vs 預設深度思考】")
print(f"   • 總計可用 Gemini 金鑰池: {len(gemini_keys)} 把 (自動容錯輪詢)")
print("=" * 85 + "\n")

from google import genai
from google.genai import types

def generate_test_image(text_label: str, bg_color=(40, 44, 52), width=640, height=360) -> bytes:
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width-20, height-20], outline=(100, 149, 237), width=3)
    draw.rectangle([50, 50, 250, 180], fill=(70, 130, 180), outline=(255, 255, 255), width=2)
    draw.ellipse([width-220, 80, width-60, 240], fill=(219, 112, 147), outline=(255, 255, 255), width=2)
    draw.text((60, 280), f"Gemini 3.7 Test: {text_label}", fill=(255, 255, 255))
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

# 智能呼叫函數：遍歷金鑰池直到成功
def call_gemini_37_with_pool(contents, thinking_budget=0, tools=None):
    cfg_kwargs = {"temperature": 0.7}
    if thinking_budget is not None and thinking_budget >= 0:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
    if tools:
        cfg_kwargs["tools"] = tools
        cfg_kwargs["temperature"] = 0.2
        
    config = types.GenerateContentConfig(**cfg_kwargs)
    
    last_err = ""
    for idx, key in enumerate(gemini_keys):
        client = genai.Client(api_key=key)
        start_t = time.time()
        try:
            resp = client.models.generate_content(
                model="gemini-3.7-flash",
                contents=contents,
                config=config
            )
            lat = time.time() - start_t
            txt = getattr(resp, 'text', '') or ''
            fc = getattr(resp, 'function_calls', []) or []
            
            usage = getattr(resp, 'usage_metadata', None)
            c_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0
            
            fn_s = f"[Tool: {fc[0].name}]" if fc else ""
            summary = (txt.strip()[:65].replace("\n", " ") if txt else fn_s)
            
            return {
                "status": "SUCCESS",
                "latency": round(lat, 3),
                "output": summary,
                "tokens": c_tokens,
                "key_used": f"Key#{idx+1}",
                "error": None
            }
        except Exception as e:
            err_s = str(e)
            last_err = err_s
            # 若為 429 或 503，換下一把 key
            if "429" in err_s or "503" in err_s or "RESOURCE_EXHAUSTED" in err_s or "UNAVAILABLE" in err_s:
                continue
            else:
                # 其它參數錯誤
                break
                
    return {
        "status": "FAILED",
        "latency": 0.0,
        "output": "",
        "tokens": 0,
        "key_used": "None",
        "error": last_err[:80] if last_err else "All keys failed"
    }

# 建立 5 圖內容
img5_contents = []
for idx, img_b in enumerate(TEST_IMG_5_LIST):
    img5_contents.append(f"\n【視角 {idx+1}/5】：")
    img5_contents.append(types.Part.from_bytes(data=img_b, mime_type="image/jpeg"))
img5_contents.append("請簡短評估這 5 個連續視角的特徵。")

# 建立 1 圖內容
img1_contents = [
    types.Part.from_bytes(data=TEST_IMG_1, mime_type="image/jpeg"),
    "請簡短描述畫面中的幾何元素。"
]

test_items = [
    # 🌟 1. 關閉深度思考 (Thinking Budget = 0) - 極速秒回模式
    ("純文字 (Text Only)", ["請用一句話簡短介紹你是誰與你的核心特長。"], 0, None),
    ("單圖視覺 (1 Image)", img1_contents, 0, None),
    ("5圖多視角 (5 Images)", img5_contents, 0, None),
    ("工具調用 (Tool Call)", ["請把 7L 的表情切換為星星眼。"], 0, [SAMPLE_TOOL]),
    
    # ⚖️ 2. 輕度思考 (Thinking Budget = 1024)
    ("純文字 (思考 1024 tokens)", ["請用一句話簡短介紹你是誰與你的核心特長。"], 1024, None),
    ("單圖視覺 (思考 1024 tokens)", img1_contents, 1024, None),
    
    # 🧠 3. 預設深度思考 (Default Thinking / Auto)
    ("純文字 (預設深度思考)", ["請用一句話簡短介紹你是誰與你的核心特長。"], None, None),
    ("單圖視覺 (預設深度思考)", img1_contents, None, None),
    ("5圖多視角 (預設深度思考)", img5_contents, None, None),
]

print(f"{'測試維度 / 方法':<25} | {'思考設定 (Thinking)':<22} | {'耗時(秒)':<8} | {'狀態':<8} | {'金鑰':<7} | {'輸出摘要'}")
print("=" * 115)

all_results = []
for m_label, contents, budget, tools in test_items:
    b_label = "0 (關閉思考 ⚡)" if budget == 0 else (f"{budget} (輕度思考)" if budget else "Auto (預設深度思考 🧠)")
    res = call_gemini_37_with_pool(contents, thinking_budget=budget, tools=tools)
    all_results.append({"method": m_label, "thinking_setting": b_label, **res})
    
    sym = "✅" if res["status"] == "SUCCESS" else "❌"
    desc = res["output"] if res["status"] == "SUCCESS" else res["error"]
    print(f"{m_label:<25} | {b_label:<22} | ⏱️ {res['latency']:<6.2f}s | {sym} {res['status']:<6} | {res['key_used']:<7} | {desc}")
    time.sleep(0.5)

print("=" * 115)

with open("gemini_37_benchmark_summary.json", "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)

print("\n🎉 Gemini 3.7 Flash 專項測試已完成！結果已儲存至 gemini_37_benchmark_summary.json")
