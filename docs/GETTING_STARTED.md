# 新手引導（5 步開播）

> 讀完本頁約 10 分鐘。先看意外狀況請跳第 5 步。

## 0. 這是什麼

兩個模式、同一套大腦（`MODE=` 切換）：

| | 💗 伴侶 companion | 📺 主播 vtuber（預設） |
|---|---|---|
| 聊天對象 | 只有你（1 對 1） | 只有觀眾（不理電腦前的人） |
| 輸入 | 麥克風／鍵盤／Web 打字 | TikTok／Twitch／YouTube 聊天室 |
| 你怎麼插話 | 直接說話 | 控制台「公開插話」（觀眾都聽到） |
| 記憶／RAG | `*_companion.json`／`knowledge_companion` | `*_vtuber.json`／`knowledge_vtuber` |
| 休眠／看螢幕 | 有 | 無（7x24 不打烊） |

## 1. 安裝

```bash
python -m pip install -r requirements.txt
python -m pytest tests/ -q   # 看到全綠再往下
```

## 2. 填 key（`.env`，絕不進 git）

```bash
copy .env.example .env   # 若無範例檔，直接新建 .env
```

| key | 必填？ | 說明 |
|---|---|---|
| `GEMINI_API_KEYS` | 是（多模態） | 逗號分隔；視覺＋Live 全雙工＋旗艦推理 |
| `GROQ_API_KEYS` | 是（純文字快線） | 逗號分隔；秒回／哨兵／摘要 |
| `MODE` | 否（預設 vtuber） | `companion` 或 `vtuber` |
| `OWNER_NAME`／`CHARACTER_NAME` | 否（預設 老爸／7L） | 稱謂可改 |
| `TWITCH_CHANNELS` | 主播用 | 小寫頻道名，逗號分隔 |
| `YOUTUBE_CHANNEL` | 主播用 | `@handle`，自動跟播 |
| `SIGN_API_KEY` | TikTok 用 | Euler 簽章 |
| `FIREBASE_ENABLED` | 否（預設 0＝純本地） | 多機同步才開＋`FIREBASE_CRED_JSON` |

控制台（http://localhost:7860 → 系統設定）可白名單直改，機密只寫不讀。

## 3. 啟動

```bash
V7.bat            # CosyVoice → 主程式 → 看門狗（一鍵）
# 或：python vts_7L_test.py
# 開播前先開 VTube Studio（8001 埠），再開 OBS 抓窗
```

看到 `🎭 [運行模式] MODE=...` 即裝配成功。主播模式看到兩行 `ℹ️ 未設定 …`＝頻道沒填（正常，先填再重啟）。

## 4. 驗證（開播前 1 分鐘）

1. `python -m pytest tests/ -q` 全綠
2. 控制台「直播間」看到三家狀態（🟡 等待＝頻道未填；🔴＝live；⚪＝停用）
3. 伴侶：對麥說話有回；主播：用觀眾帳號發一條留言，看心智看板有沒有吃進去
4. 點歌：說「彈卡農」→ MIDI 樂隊開演；點片：貼 YT 網址 → 點播隊列消化播報

## 5. 常見狀況

| 現象 | 查什麼 |
|---|---|
| Gemini Live 集體 Timeout | 網路→googleapis 通不通；key 有效性；急用開 `GROQ_ONLY=1` 降級撐直播 |
| Tavily 額度爆 | 等重置或加 key；已自動退 Google 爬蟲 |
| onnxruntime CUDA 報錯 | 缺 cuDNN／CUDA 12，自動退 CPU（慢，不致命） |
| 聊天室沒動靜 | `.env` 頻道空（看開機 log 兩行 ℹ️） |
| 主播理電腦前的人 | `MODE` 必須是 vtuber（強制關操作者通道）；插話走「公開插話」 |
| 記憶混了 | 檢查檔名後綴 `_companion`／`_vtuber`；舊無後綴檔已廢棄 |

進階：`docs/AI_SOURCES.md`（全部 AI 來源＋配額）、`modes/workers.py`（裝配宣告）。
