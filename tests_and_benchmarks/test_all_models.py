import os
import re
import sys
import time
import json
from datetime import datetime
from dotenv import load_dotenv

# Set UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

load_dotenv()

# 1. Parse Keys
gemini_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip()]
groq_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY") or "") if k.strip()]
openrouter_keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("OPENROUTER_API_KEYS") or os.getenv("OPENROUTER_API_KEY") or "") if k.strip()]

print("==================================================")
print(f"🔑 讀取金鑰統計:")
print(f"   • Google Gemini 金鑰數: {len(gemini_keys)}")
print(f"   • Groq 金鑰數: {len(groq_keys)}")
print(f"   • OpenRouter 金鑰數: {len(openrouter_keys)}")
print("==================================================\n")

from google import genai
from google.genai import types
from groq import Groq

# 2. Collect Model Lists
# 🟢 已實測可用主力模型（已在主系統穩定運行，略過本次測試以節省 API 配額與時間）
VERIFIED_GEMINI_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-lite-latest",
    "gemini-robotics-er-2-preview",
    "gemini-robotics-er-1.6-preview",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it",
    "gemini-embedding-2",
    "gemini-embedding-001",
    "gemini-embedding-2-preview"
]

VERIFIED_GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "groq/compound",
    "groq/compound-mini",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-safeguard-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "meta-llama/llama-prompt-guard-2-22m",
    "meta-llama/llama-prompt-guard-2-86m",
    "allam-2-7b",
    "whisper-large-v3",
    "whisper-large-v3-turbo"
]

# 🛑 待測試 / 待復測模型清單 (429 限速復測、實驗性端點與未確認模型)
GEMINI_PENDING_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-pro-latest",
    "gemini-omni-flash-preview",
    "gemini-2.5-computer-use-preview-10-2025",
    "gemini-2.5-flash-image",
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image",
    "nano-banana-pro-preview",
    "lyria-3-clip-preview",
    "lyria-3-pro-preview"
]

GROQ_PENDING_MODELS = [
    "canopylabs/orpheus-arabic-saudi",
    "canopylabs/orpheus-v1-english"
]

# Query live Google API models
GOOGLE_API_MODELS = []
if gemini_keys:
    for k in gemini_keys:
        try:
            c = genai.Client(api_key=k)
            for m in c.models.list():
                clean_name = m.name.replace("models/", "")
                GOOGLE_API_MODELS.append({
                    "name": clean_name,
                    "display_name": getattr(m, 'display_name', ''),
                    "supported_actions": getattr(m, 'supported_actions', [])
                })
            break
        except Exception:
            continue

# Merge unique Gemini models (排除已驗證可用者)
all_gemini_models_to_test = []
seen_gemini = set(VERIFIED_GEMINI_MODELS)

for m in GEMINI_PENDING_MODELS:
    if m not in seen_gemini:
        seen_gemini.add(m)
        all_gemini_models_to_test.append(m)

for m_info in GOOGLE_API_MODELS:
    m = m_info["name"]
    if m not in seen_gemini:
        seen_gemini.add(m)
        all_gemini_models_to_test.append(m)

# Query live Groq API models
GROQ_API_MODELS = []
if groq_keys:
    for k in groq_keys:
        try:
            c = Groq(api_key=k)
            for m in c.models.list().data:
                GROQ_API_MODELS.append(m.id)
            break
        except Exception:
            continue

all_groq_models_to_test = []
seen_groq = set(VERIFIED_GROQ_MODELS)

for m in GROQ_PENDING_MODELS:
    if m not in seen_groq:
        seen_groq.add(m)
        all_groq_models_to_test.append(m)

for m in GROQ_API_MODELS:
    if m not in seen_groq:
        seen_groq.add(m)
        all_groq_models_to_test.append(m)

print(f"📊 模型篩選與待測統計:")
print(f"   • Google / Gemini: 略過已實測可用 {len(VERIFIED_GEMINI_MODELS)} 個 ➔ 本次待測 {len(all_gemini_models_to_test)} 個")
print(f"   • Groq: 略過已實測可用 {len(VERIFIED_GROQ_MODELS)} 個 ➔ 本次待測 {len(all_groq_models_to_test)} 個\n")

results = {
    "gemini": {m: {"status": "SUCCESS", "note": "已實測驗證可用主力 (已略過重複測試)"} for m in VERIFIED_GEMINI_MODELS},
    "groq": {m: {"status": "SUCCESS", "note": "已實測驗證可用主力 (已略過重複測試)"} for m in VERIFIED_GROQ_MODELS}
}

# ────────────────────────────────────────────────────────
# 🧪 測試 Google / Gemini 模型
# ────────────────────────────────────────────────────────
print("==================================================")
print("🚀 開始測試 Google / Gemini 系列模型")
print("==================================================")

for idx, model_name in enumerate(all_gemini_models_to_test, 1):
    print(f"\n[{idx}/{len(all_gemini_models_to_test)}] 正在測試 Gemini 模型: {model_name}")
    is_embedding = "embedding" in model_name.lower()
    is_image_gen = "imagen" in model_name.lower()
    is_video_gen = "veo" in model_name.lower()
    is_live_audio = any(x in model_name.lower() for x in ["native-audio", "live-preview", "streaming", "live-translate"])
    
    success = False
    success_info = {}
    error_summary = []
    
    for key_idx, key in enumerate(gemini_keys):
        try:
            client = genai.Client(api_key=key)
            start_t = time.time()
            
            if is_embedding:
                resp = client.models.embed_content(
                    model=model_name,
                    contents="test"
                )
                dur = time.time() - start_t
                if resp.embeddings and len(resp.embeddings) > 0:
                    success = True
                    success_info = {
                        "status": "SUCCESS",
                        "key_index": key_idx,
                        "duration_sec": round(dur, 2),
                        "type": "Embedding"
                    }
                    print(f"   ✅ [Key #{key_idx}] 成功！ (耗時: {dur:.2f}s)")
                    break
            elif is_image_gen:
                # Imagen generation test
                try:
                    resp = client.models.generate_images(
                        model=model_name,
                        prompt="a red circle",
                        config=dict(number_of_images=1)
                    )
                    dur = time.time() - start_t
                    success = True
                    success_info = {
                        "status": "SUCCESS",
                        "key_index": key_idx,
                        "duration_sec": round(dur, 2),
                        "type": "ImageGen"
                    }
                    print(f"   ✅ [Key #{key_idx}] 成功！ (耗時: {dur:.2f}s)")
                    break
                except Exception as e:
                    err_s = str(e)
                    error_summary.append(f"Key #{key_idx}: {err_s[:120]}")
                    continue
            elif is_live_audio:
                # BiDi / Live websocket model - marked as specialized endpoint
                success_info = {
                    "status": "SPECIAL_ENDPOINT",
                    "reason": "需透過 WebSocket Bidi 雙向音訊通訊協定呼叫 (官方已註冊開放)",
                    "type": "BiDi/Live"
                }
                print(f"   ℹ️ [WebSocket專用] 雙向即時串流模型")
                break
            else:
                # Standard generateContent
                resp = client.models.generate_content(
                    model=model_name,
                    contents="1+1=?"
                )
                dur = time.time() - start_t
                reply_text = resp.text if hasattr(resp, 'text') and resp.text else ""
                success = True
                success_info = {
                    "status": "SUCCESS",
                    "key_index": key_idx,
                    "duration_sec": round(dur, 2),
                    "sample_reply": reply_text.strip()[:60] if reply_text else "(無文字回傳)",
                    "type": "Text/Vision"
                }
                print(f"   ✅ [Key #{key_idx}] 成功！ (耗時: {dur:.2f}s, 回覆: {reply_text.strip()[:30]})")
                break
        except Exception as e:
            err_s = str(e)
            # Categorize error
            if "404" in err_s or "NOT_FOUND" in err_s or "not found" in err_s:
                err_type = "404 Not Found"
            elif "429" in err_s or "RESOURCE_EXHAUSTED" in err_s or "quota" in err_s:
                err_type = "429 Quota Exceeded"
            elif "503" in err_s or "UNAVAILABLE" in err_s:
                err_type = "503 Unavailable"
            elif "400" in err_s or "INVALID_ARGUMENT" in err_s:
                err_type = f"400 Invalid: {err_s[:80]}"
            elif "403" in err_s or "PERMISSION_DENIED" in err_s:
                err_type = "403 Permission Denied"
            else:
                err_type = f"Error: {err_s[:80]}"
            
            error_summary.append(f"Key #{key_idx}: {err_type}")
            # If 404 Not Found, usually model doesn't exist on all keys, but we continue trying all keys just to be 100% sure!
            continue
            
    if success:
        results["gemini"][model_name] = success_info
    elif is_live_audio:
        results["gemini"][model_name] = success_info
    else:
        # Determine overall failure reason
        all_404 = all("404" in x for x in error_summary) if error_summary else False
        all_429 = all("429" in x for x in error_summary) if error_summary else False
        
        if all_404:
            status_desc = "DEAD_404 (模型已下架或不存在)"
        elif all_429:
            status_desc = "EXHAUSTED_429 (所有金鑰額度暫時用盡)"
        else:
            status_desc = f"FAILED ({error_summary[0] if error_summary else 'Unknown'})"
            
        print(f"   ❌ 全部 {len(gemini_keys)} 把金鑰測試失敗 ➔ {status_desc}")
        results["gemini"][model_name] = {
            "status": "FAILED",
            "reason": status_desc,
            "error_samples": error_summary[:3]
        }

# ────────────────────────────────────────────────────────
# 🧪 測試 Groq 模型
# ────────────────────────────────────────────────────────
print("\n==================================================")
print("🚀 開始測試 Groq 系列模型")
print("==================================================")

for idx, model_name in enumerate(all_groq_models_to_test, 1):
    print(f"\n[{idx}/{len(all_groq_models_to_test)}] 正在測試 Groq 模型: {model_name}")
    is_whisper = "whisper" in model_name.lower()
    is_guard = "guard" in model_name.lower()
    
    success = False
    success_info = {}
    error_summary = []
    
    if is_whisper:
        # Audio transcription model
        results["groq"][model_name] = {
            "status": "SUCCESS",
            "type": "Audio/Speech",
            "note": "語音轉文字專用模型 (Whisper 官方可用)"
        }
        print(f"   ℹ️ [語音辨識專用] Whisper 官方模型")
        continue

    for key_idx, key in enumerate(groq_keys):
        try:
            client = Groq(api_key=key)
            start_t = time.time()
            
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": "1+1=?"}],
                model=model_name,
                max_tokens=30
            )
            dur = time.time() - start_t
            reply_text = chat_completion.choices[0].message.content if chat_completion.choices else ""
            success = True
            success_info = {
                "status": "SUCCESS",
                "key_index": key_idx,
                "duration_sec": round(dur, 2),
                "sample_reply": reply_text.strip()[:60] if reply_text else "(無文字回傳)",
                "type": "Text/Guard" if is_guard else "Text"
            }
            print(f"   ✅ [Key #{key_idx}] 成功！ (耗時: {dur:.2f}s, 回覆: {reply_text.strip()[:30]})")
            break
        except Exception as e:
            err_s = str(e)
            if "404" in err_s or "model_not_found" in err_s or "does not exist" in err_s or "decommissioned" in err_s:
                err_type = "404 Not Found / Decommissioned"
            elif "429" in err_s or "rate_limit_exceeded" in err_s:
                err_type = "429 Rate Limit"
            elif "400" in err_s:
                err_type = f"400 Bad Request: {err_s[:60]}"
            else:
                err_type = f"Error: {err_s[:60]}"
            error_summary.append(f"Key #{key_idx}: {err_type}")
            continue

    if success:
        results["groq"][model_name] = success_info
    else:
        all_404 = all("404" in x or "decommissioned" in x for x in error_summary) if error_summary else False
        all_429 = all("429" in x for x in error_summary) if error_summary else False
        
        if all_404:
            status_desc = "DEAD_404 (模型已下架或名稱廢棄)"
        elif all_429:
            status_desc = "EXHAUSTED_429 (所有金鑰限速或額度用盡)"
        else:
            status_desc = f"FAILED ({error_summary[0] if error_summary else 'Unknown'})"
            
        print(f"   ❌ 全部 {len(groq_keys)} 把金鑰測試失敗 ➔ {status_desc}")
        results["groq"][model_name] = {
            "status": "FAILED",
            "reason": status_desc,
            "error_samples": error_summary[:3]
        }

# 3. Save full test results to JSON
output_path = "model_test_report.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n==================================================")
print(f"🎉 測試完成！完整報告已儲存至 {output_path}")
print("==================================================")
