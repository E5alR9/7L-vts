# Groq 小型轉發器（Vercel Serverless）

把 28 把 Groq 金鑰收在 Vercel 環境變數裡，對外只暴露一個入口 token。
多台機器 / 多支 bot 共用同一批金鑰，金鑰本體不外流。

## 端點（OpenAI 相容）

| 方法 | 路徑 | 說明 |
|---|---|---|
| POST | `/v1/chat/completions` | 聊天（支援 `stream:true`） |
| GET | `/v1/models` | 模型清單 |
| GET | `/api/health` | 冒煙測試（只回統計，不回金鑰） |

## 路由邏輯

1. **金鑰 round-robin** — 輪流使用 `GROQ_KEYS`
2. **逐金鑰冷卻** — `429`→60s、`401/403`→10min、`5xx`→30s
3. **模型梯隊** — 主模型 404 時自動降級：
   `qwen/qwen3.8-27b → openai/gpt-oss-120b → openai/gpt-oss-20b → allam-2-7b`
   （可用 `MODEL_LADDER` 環境變數覆寫）
4. **回應標頭** — `x-router-model` / `x-router-key-index` 方便追蹤

## 本地測試

```bash
node local-test.js          # 非串流
node local-test.js stream   # 串流
```

會從 `../.env` 讀 `GROQ_API_KEYS`，打真實 Groq 請求並印出延遲。

## 部署

```bash
cd vercel-router

# 1) 綁定專案（第一次會問 scope/project，選新建）
vercel link

# 2) 設定環境變數（production）
#    GROQ_KEYS     ← .env 裡 GROQ_API_KEYS 的整串（28 把）
#    ROUTER_TOKEN  ← 自己生一串隨機 token
echo "<28把金鑰整串>" | vercel env add GROQ_KEYS production
echo "<隨機token>"    | vercel env add ROUTER_TOKEN production

# 3) 部署
vercel deploy --prod
```

**區域**：到 Vercel Dashboard → 專案 → Settings → Functions → Regions，
選 `hkg1`（香港）或 `sin1`（新加坡），離台灣最近。

## 呼叫端用法

```python
from openai import OpenAI
client = OpenAI(base_url="https://<你的專案>.vercel.app/v1",
                api_key="<ROUTER_TOKEN>")
r = client.chat.completions.create(model="qwen/qwen3.8-27b", messages=[...])
```

## 注意

- **冷啟動**：serverless 冰封喚醒約 +200~500ms；直播對嘴那條路仍走本機 `core/groq_router.py`（0.28s、無額外跳數），這個轉發器是給「多機共用 / 金鑰不外流」場景用。
- `.vercel/` 與 `.env.local` 已在 `.gitignore` 排除。
