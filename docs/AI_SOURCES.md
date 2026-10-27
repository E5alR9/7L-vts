# AI_SOURCES — 全棧 AI／轉錄來源對照表

> 程式內凡調用 AI 皆有 `PROVIDER:` 標記指向本表。`grep -rn PROVIDER --include=*.py .` 即全覽。
> 配額為 2026-09-29 用戶控制台值（28 天用量全 0；Timeout 屬網路非配額）。

## 對話大腦

| 用途 | PROVIDER | 模型／後端 | key／env | 配額 | 備註 |
|---|---|---|---|---|---|
| 純文字快線（秒回／哨兵／審查／提煉／摘要） | GROQ | qwen3.8-27b → gpt-oss-120b → gpt-oss-20b（`core/groq_router.py` 梯隊；gpt-oss 帶 reasoning_effort=low，allam-2-7b 2026-10-27 拿掉） | `GROQ_API_KEYS`×30，`GROQ_REQUESTS_PER_MINUTE=20` | ITPM ~7000／org／model | 第一梯隊；`fetch_fast_text_reply` 主力 |
| 背景純文字（定時提醒／搜尋提煉／鋼琴過場碎念） | GROQ | 同上梯隊（一律 `groq_chat`） | 同上 | 同上 | **2026-10-09 起全程零 Gemini**；失敗走本地離線摘要器／固定備援句／安靜不說話 |
| 主腦深度推理 | GEMINI | REST 梯隊 3.5-flash-lite → 3.1-flash-lite → 3.6-flash → 3.8-flash；高 IQ 梯隊 3.8 → 3.6 → lite 系（`core/llm_engine.py`；3.5-flash／3.7-flash 已棄用、自動導向 3.6／3.8，不直接打；pro 系列、gemini-4-argon 額度 0；2.5 系列已下架，2026-10-27 實測） | `GEMINI_API_KEYS`×35，分池（觀眾／心流／視覺／主腦） | 旗艦 RPD 20／天／key；lite RPM 15／RPD 500 | 高頻一律 lite |
| Live 全雙工（觀眾回覆／心流串流） | GEMINI-LIVE | **gemini-3.8-live**（舊 3.1-preview 已遷移，表上消失） | 同上（動態跨池備援） | RPM／RPD Unlimited，TPM 65K | 7x24 成立 |
| Live 子智能體（工具判定＋深度思考） | GEMINI＋NVIDIA | 兩棒都 Gemini 先、NV 備援（`core/subagent_router.SUBAGENT_BRAIN`=auto 預設；可改 nv／gemini）；NV 模型 Nemotron-3-Ultra-550B（`_NV_SUBAGENT_MODEL`），回 404 停用 10 分鐘 | `NV_API_KEYS`×3／GEMINI keys | NV 推理模型深思要 60 秒，只當備援；舊的 Super-120B 已 404 | 2026-10-24 |
| 視覺看圖（餘光／截圖／抽幀） | GEMINI-VISION | 3.1-flash-lite → 3.6-flash（`get_lightweight_gemini_vision`） | KEYS_VISION（keys 12:18） | lite RPD 500 | 黑屏檢測防幻覺 |
| 生圖 | GEMINI-IMAGE | Nano Banana 系（2.5-image → 3.1-image → pro-image） | 同上 | ⚠️ 全系 0／0／0，現降級中 | 有配額前不可用 |
| 本地第四條腿（規劃） | GEMMA | Ollama gemma3:4b（視覺＋128K）／3n E4B（影音圖文， transformers 路） | 無 key，本地 GPU | 無 | 伴侶隱私模式＋視覺初篩 |

## 語音（STT／TTS）

| 用途 | PROVIDER | 後端 | env | 配額 | 備註 |
|---|---|---|---|---|---|
| mic 快覽＋系統音轉錄（現行） | GOOGLE-WEB-SPEECH | `recognize_google(zh-TW)` 非官方免費端點（`listen_once_fast`／`transcribe_audio_bytes`） | 無 | 非官方，無配額概念（隨時可死） | 將遷 3.5-transcribe |
| 官方 STT（規劃） | GEMINI-TRANSCRIBE | gemini-3.5-transcribe（說話人分離＋詞戳＋自訂詞表） | 同 Gemini keys | RPM 3／RPD 25 | 常駐轉錄仍走本地 faster-whisper（已在 requirements，未接線） |
| TTS 主力 | LOCAL＋CLOUD | `TTS_ENGINE` 預設 cloud_gptsovits，備援 `TTS_FALLBACK` 預設曉伊 GPT-SoVITS；cosyvoice／edge／elevenlabs 選配（`services/tts_router.py` 引擎鏈） | `TTS_ENGINE`／`TTS_FALLBACK`／`COSYVOICE_URL` | 無 | 120 秒自動升級回鏈首 |
| TTS 備援 | CLOUD | edge-tts（微軟）／elevenlabs（月 10K 字元守衛） | `ELEVENLABS_API_KEY` | RPD 10（Gemini TTS 系同） | Gemini 3.8-flash-tts 系可追加進鏈 |
| mic 快覽 | GOOGLE-WEB-SPEECH | `recognize_google(zh-TW)`（`listen_once_fast`） | 無 | 非官方 | 深層理解走 Gemini Live audio_b64 |
| 系統音／轉錄備援 | LOCAL-faster-whisper | `services/stt.py`（`STT_BACKEND = "auto"`，small／CPU int8） | 無 | 無 | Google 失敗自動退本地 |

## 記憶／檢索／搜尋

| 用途 | PROVIDER | 後端 | 備註 |
|---|---|---|---|
| RAG 向量庫 | LOCAL | chromadb（`data/rag/chroma`，collection 按模式切開：`knowledge_companion`／`knowledge_vtuber`，重建不相容舊） | `scripts/ingest_rag.py --reset` 重建 |
| 文字嵌入 | LOCAL-fastembed／GEMINI-備援 | bge-small-zh-v1.5（130MB 離線）／`gemini-embedding-001`（`services/embedder.EMBED_BACKEND` 可切） | 圖影音幀走 `embedding-2-preview`（100 RPM／1K RPD） |
| 上下文組裝（規劃） | LOCAL | 對標 groq-router：fold 摘要＋recent-2＋向量 top-k（0.15＋60％門檻、上限 4 段、時間序）＋ITPM 收斂器 | 解 Groq 7K ITPM |
| 點播看全片 | LOCAL＋GEMINI-VISION＋GROQ | `services/video_watch.py`（captions→音軌轉錄→抽幀看圖→Groq 摘要→記憶＋看板，source=`video_watch`） | 單片上限 `VIDEO_WATCH_MAX_MIN`（模組常數，30 分） |
| 聯網搜尋 | TAVILY／LOCAL-SCRAPE | `tavily`×10 key（⚠️ 額度已爆）／`search_google` 無 API 爬蟲 | Tavily 爆時自動退爬蟲 |
| 每日日記濃縮 | GROQ | 只剩舊 `7L.py` 機器人有（主程式那份從沒被呼叫，2026-10-25 刪除） | 2026-10-25 |
| 點歌意圖 JSON 解析 | GROQ-primary | `pe.resolve_piano_intent_by_ai` 走 `groq_chat`（temp 0.1）；Gemini 高 IQ 梯隊僅 Groq 全滅時兜底 | 2026-10-09 |
| 雲同步（刪除候選） | FIRESTORE | `core/db.py`，全呼叫點 `if db is not None`＋本地 JSON 備援 | 拔掉只失多機同步；且 db.py 吃 google-auth |

## 直播輸入（零 AI，純通道）

| 平台 | 後端 | key | 備註 |
|---|---|---|---|
| TikTok | EulerStream＋簽章 | `SIGN_API_KEY` | 禮物／點讚事件 |
| Twitch | IRC 匿名 justinfan | 無 | `services/twitch_listener.py` |
| YouTube | InnerTube 免 key 輪詢 | 無 | 頻道模式跟播＋去重退避 |

## 已刪除（審計）

| 項目 | 原因 | 日期 |
|---|---|---|
| `get_embedding_vector`＋日記向量欄位 | 寫而不用（全倉零讀取） | 2026-09-29 |
| `scratch/correct_chunk.py`（3144 行） | 舊碼墳場，零引用 | 2026-09-29 |
| `gemini-3.1-pro-preview`（4 處梯隊） | 配額 0／0／0 | 2026-09-29 |
| `gemini-3.1-flash-live-preview`（11 處） | Legacy，配額表消失 → `gemini-3.8-live` | 2026-09-29 |
| 日記濃縮的 Gemini fallback | 背景記憶不佔 Gemini 額度 → Groq 專責，失敗跳過 | 2026-10-09 |
| 搜尋提煉的 Gemini Flash Lite 層 | 純文字提煉 → Groq 梯隊 → 本機離線摘要器 | 2026-10-09 |
| 定時提醒口語的 `fetch_ai_response` | 背景純文字 → `groq_chat`，失敗走固定備援句 | 2026-10-09 |
| 鋼琴過場碎念的 Gemini 呼叫 | 背景純文字 → `groq_chat`，失敗就安靜 | 2026-10-09 |
