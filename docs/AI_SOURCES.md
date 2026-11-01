# AI_SOURCES — 7L 用到的 AI 與外部服務

> 2026-11-01 照程式重新清點（之前那版停在 10-29）。程式內呼叫 AI 的地方多半有 `PROVIDER:` 標記，`grep -rn PROVIDER --include=*.py .` 可全覽。
> 模型名稱唯一出處：`core/llm_engine.py` 開頭那段（Google 下架或改名只改那裡）。
> 金鑰（2026-11-01）：Gemini 32 把、Groq 29 把、NVIDIA 3 把、Tavily 10 把，都放在家目錄的 `.env`／`6.env`。

## Gemini Live（主力；不吃 REST 每日額度，老爸說可一直用，只守每把 key 同時連線數）

| 用途 | 模型 | 頻率 | 程式 |
|---|---|---|---|
| 主腦：聽老爸講話（麥克風原生音訊）、聊天、決定開不開口（say 閘） | gemini-3.8-live → 3.1-flash-live-preview | 常駐 | `vts_7L_test.continuous_live_worker`（`LIVE_MAIN_MODELS`） |
| 本能腦：邊聽邊做小表情、小動作 | 3.8-live | 常駐 | `instinct_live_worker` |
| 神態導演：幫每句話排表情時間軸 | 3.8-live | 每句話（常駐連線） | `_director_ensure_session` |
| 副意識群：查核、記憶、情緒、話題、分寸 | 查核／記憶用 3.8-live-extended-thinking（low），其他 3.8-live | 每輪對話 | `services/subminds.py`（`ResidentAdvisor`） |
| 說完又想到：回完話背後再想，有錯或補充就遞紙條 | 3.8-live-extended-thinking（low） | 每輪對話 | `_afterthought` |
| 視線副腦：看畫了 8x6 網格的截圖挑要看哪格／滑鼠／鏡頭 | 3.8-live（單次連線） | 約每 3 秒 | `workers/gaze_brain.py` → `live_one_shot` |
| 畫面哨兵：餘光判斷畫面有沒有重大變化 | 3.8-live（單次連線） | 餘光視覺時 | `check_screen_change_via_live_api` → `live_one_shot` |
| 看板哨兵：觀眾留言要不要回（Groq 備援） | 3.8-live（單次連線） | 有留言時 | `judge_should_speak` → `live_one_shot` |
| YT 伴看：一直聽影片聲音，每 18 秒把 3 張畫面＋問題同一則訊息送、寫筆記 | 3.8-live | 開 YouTube 並同意陪看時 | `services/yt_companion_service.py` |

**看圖一律「圖跟問題同一則訊息＋`MEDIA_RESOLUTION_HIGH`」**（2026-11-01）：以前圖走即時影像串流（`send_realtime_input(video=…)`），紅點網格測試 6 次只答 2 次、差 4～6 格，串流加高解析度也 6 次答不出來；改後 8 次 7 次全對，每次慢 0.5～1 秒。`live_one_shot(image_as_stream=True)` 只留給對照測試。

**Live 不能／不用調的**：只回文字（`response_modalities=[TEXT]`）三個 Live 模型都回 1007 不支援，所以照舊生成語音、只取逐字稿（只浪費額度，不會播出來）；`gemini-3.8-live` 不支援 `thinking_level`（設了連不上）；講完判斷（`silence_duration_ms`）調短沒變快、調長擋不住停頓插話，維持預設。

## Gemini REST（吃每日額度：旗艦 RPD 約 20／天／key，lite RPM 15／RPD 500）

| 用途 | 模型 | 程式 |
|---|---|---|
| 餘光視覺（看螢幕寫描述，含歷史幀） | 3.5／3.1-flash-lite → 3.6 → 3.8（`GEMINI_MODELS`） | `peripheral_vision_worker`、`get_lightweight_gemini_vision` |
| 看畫面、照鏡子（她自己叫的）、看片抽幀 | 同上 | `describe_images`（`live_vision_tool_task`、`live_mirror_tool_task`、`services/video_watch.py`） |
| 系統聲音辨識（電腦在放什麼） | 3.1-flash-lite（`AUDIO_MODEL`） | `workers/system_audio.py` |
| REST 大腦：Live 主腦斷線時接手回話（Groq 先試） | 3.6 → 3.8 → 3.5-flash-lite（`REST_BRAIN_MODELS`） | `core/rest_brain.py`、`_rest_answer_slip` |
| 子智能體：工具判定（只用 Gemini）＋深度思考（跟 NVIDIA 一起想、誰先好用誰） | `GEMINI_MODELS` 系，3.6-flash 思考 minimal | `_gemini_tool_pass`、`_gemini_think_pass` |
| 看板發話（回觀眾留言） | `STREAMER_MIND_MODELS` | `streamer_mind_loop_worker` |
| 點歌判斷、AI 作曲（Groq 全滅才用） | `HIGH_IQ_GEMINI_MODELS`（3.8 → 3.6 → lite） | `services/piano_engine.py` |
| 文字嵌入備援 | gemini-embedding-001 | `services/embedder.py`（平常用本機 bge） |
| 生圖 | Nano Banana 系 | `generate_ai_image`（⚠️ 額度 0，用不了） |

## Groq（純文字快線；`core/groq_router.py`）

梯隊 qwen/qwen3.8-27b → openai/gpt-oss-120b → openai/gpt-oss-20b，一律串流（送出 3 秒沒回應、吐字後卡 2 秒就換下一把／下一個模型），每分鐘上限 `GROQ_REQUESTS_PER_MINUTE`。

| 用途 | 程式 |
|---|---|
| 點歌／彈琴意圖判斷（Gemini 兜底）、彈琴過場碎念、AI 作曲先試 | `services/piano_engine.py` |
| 翻唱快取比對（這首做過沒） | `auto_cover_pipeline.ai_match_cached_song` |
| 唱／彈／停的指令判斷 | `_judge_stage_request` |
| 看板哨兵備援 | `judge_should_speak` |
| REST 大腦第一棒 | `core/rest_brain._groq_once` |
| 搜尋結果整理成口語 | `services/web_search.summarize_search_to_speech` |
| 記憶濃縮、看片摘要 | `services/rag_store.fold_summary`（`video_watch` 也用） |
| 做夢日記（閒著時整理成當天日記） | `core/dream.merge_into_diary` |
| 計時器到期提醒話 | `workers/timer_sensor.py` |
| 快睡著的一句話 | `_doze_one_liner` |

**參數**（2026-11-01 實測）：gpt-oss 帶 `reasoning_effort=low`；qwen 預設就不思考（設 `none` 差距在誤差內，沒設）；`include_reasoning=false` 不會變快；`service_tier`（auto／flex）這個帳號不能用（付費才有）；重複懲罰、logprobs 等 Groq 標示沒有模型支援。

## NVIDIA（`integrate.api.nvidia.com`）

| 用途 | 模型 | 備註 |
|---|---|---|
| 子智能體的深度思考：跟 Gemini 一起想、誰先想好用誰；**不做工具判定**（計時、搜尋、表情只給 Gemini）（老爸 2026-11-01：輝達不要用來計時，負責高智商任務；`core/subagent_router`） | nvidia/nemotron-3-ultra-550b-a55b（`_NV_SUBAGENT_MODEL`） | 深思限時 25 秒（`SUBAGENT_BRAIN=nv` 時才會用工具判定，限時 12 秒）；404 停用 10 分鐘，401/403 冷卻 1 小時，429 冷卻 1 分鐘 |

額度：不用點數，只有速率限制，帳號頁（build.nvidia.com 右上角）寫「Up to 40 rpm」（2026-11-01 老爸截圖）；3 把 key 是 3 個不同帳號，合計每分鐘 120 次；沒有試用期限、不用等重置。回應標頭沒有額度資訊，也沒有查額度的 API。
2026-11-01 實測：免費端點工具判定中位數 3～4 秒，最慢 37 秒、常回 500；單獨當子智能體 6 題 3 題卡 12 秒逾時（同題 Gemini 6/6）；單獨深思 6 題只成 2 題（其餘逾時或 503），所以只並排、不當主力；關思考（`chat_template_kwargs.enable_thinking=false`）看不出變快；`reasoning_budget` 每次都 500，不能用。

## 其他外部服務

| 服務 | 用途 | 程式 |
|---|---|---|
| Open-Meteo（免金鑰） | 問天氣先拿預報數字（今天起三天，約 0.8 秒）；台灣地名用內建座標表 | `services/weather.py` |
| Tavily → DuckDuckGo | 網路搜尋（basic 深度，約 1.5 秒）、找線上琴譜（Tavily 額度爆了自動改 DuckDuckGo） | `services/web_search.py`、`services/onlinesequencer_engine.py` |
| edge-tts（微軟） | 說話備援聲音（曉伊掛了才用；套件要 7.3.1 以上） | `services/tts_router._synth_edge` |
| Google 免費語音辨識 | **只在 Live 主腦斷線時**聽麥克風（非官方端點，隨時可能失效） | `listen_once_fast` |
| Firestore | 記憶、觀眾檔、知識庫、事件紀錄的雲端備份（本機 JSON 是正本；`FIREBASE_ENABLED=0` 關掉） | `core/memory.py`、`core/db.py`、`core/eventlog.py` |
| EulerStream | TikTok 直播簽章（`SIGN_API_KEY`） | `services/tiktok_listener.py` |
| Twitch IRC、YouTube InnerTube | 讀直播留言（不用 key） | `services/twitch_listener.py`、`services/youtube_live_listener.py` |

**不用的**：Gemini TTS、Groq Whisper（老爸不要；Groq Whisper 會幻聽）、Google TTS（`services/tts_router.ALLOWED_ENGINES` 只允許 xiaoyi＋edge）。

## 本機（不用 API）

| 用途 | 後端 |
|---|---|
| 說話聲音 | GPT-SoVITS 曉伊（`TTS_ENGINE` 預設 xiaoyi） |
| 翻唱人聲分離 | Roformer → Demucs → ffmpeg 備援；可由筆電顯卡代跑（`REMOTE_GPU_URL`，`services/remote_gpu.py`、`services/gpu_split.py`） |
| 翻唱變聲 | RVC（`services/rvc/`） |
| 看片聽寫 | faster-whisper（`services/stt.py`） |
| 記憶向量庫 | chromadb（`data/rag/chroma`），嵌入用 bge-small-zh-v1.5（fastembed） |
| AI 作曲（音訊） | ACE-Step 1.5（`services/acestep_music.py`，服務開在 7865，沒開就跳過） |
| 鋼琴、扒譜 | mido、librosa、basic-pitch（`services/midi_editor.py`、`services/audio_to_score.py`） |

## 已刪除（審計）

| 項目 | 原因 | 日期 |
|---|---|---|
| `get_embedding_vector`＋日記向量欄位 | 寫而不用（全倉零讀取） | 2026-09-29 |
| `scratch/correct_chunk.py`（3144 行） | 舊碼墳場，零引用 | 2026-09-29 |
| `gemini-3.1-pro-preview`（4 處梯隊） | 配額 0／0／0 | 2026-09-29 |
| 日記濃縮的 Gemini fallback | 背景記憶不佔 Gemini 額度 → Groq 專責 | 2026-10-09 |
| 搜尋提煉的 Gemini Flash Lite 層 | 純文字提煉 → Groq 梯隊 → 本機離線摘要器 | 2026-10-09 |
| 定時提醒口語的 `fetch_ai_response` | 背景純文字 → `groq_chat`，失敗走固定備援句 | 2026-10-09 |
| 鋼琴過場碎念的 Gemini 呼叫 | 背景純文字 → `groq_chat`，失敗就安靜 | 2026-10-09 |
| allam-2-7b（Groq 梯隊） | 記憶濃縮整段重複、哨兵格式不對 | 2026-10-27 |
| Google TTS、Gemini TTS 引擎 | 老爸只留 GPT-SoVITS＋edge | 2026-11-01 |
| Live 看圖的即時影像串流（視線副腦、畫面哨兵、YT 伴看） | 低解析度串流 Live 幾乎看不清楚 → 圖跟問題同一則訊息＋高解析度 | 2026-11-01 |
