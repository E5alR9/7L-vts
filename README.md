# 7L AI VTuber

7L 是跑在 VTube Studio 上的 AI 虛擬主播／陪伴角色：用 Gemini Live 當主腦即時對話，會唱歌（RVC 翻唱）、彈鋼琴、看畫面、接 TikTok／YouTube／Twitch 直播留言。

## 需要的軟體

- Windows 10／11
- Python 3.12
- [VTube Studio](https://denchisoft.com/)（開著，並在設定裡打開外掛 API）
- ffmpeg：放在 `C:\ffmpeg\bin\ffmpeg.exe`，或加進 PATH
- NVIDIA 顯示卡（翻唱的人聲分離和 RVC 要用；只聊天不用）
- 選用：Gemini 桌面版（深度思考、查資料的免費備援）

## 下載與安裝

```bash
git clone https://github.com/E5alR9/7L-vts.git
```

```bash
cd 7L-vts
```

```bash
python -m pip install -r requirements.txt
```

（第一次執行 `V7.bat` 也會自動安裝。）

## 一定要自己建的檔案

| 檔案 | 怎麼做 |
|---|---|
| `.env` | 複製 `.env.example` 改名成 `.env`，填上自己的金鑰。放在專案資料夾，或放在家目錄 `C:\Users\<你>\.env` 都可以（專案資料夾優先） |
| `6.env` | 只有要用 Discord 機器人（`bot.bat`）才需要：複製 `6.env.example` 改名 |

`.env`、`6.env` 都不會上傳到 GitHub。

## 要改成自己的設定

| 位置 | 改什麼 |
|---|---|
| `core/identity.py` 的 `OWNER_ACCOUNT_IDS` | 你自己在直播平台的帳號（認得出老爸／主人用） |
| `.env` 的 `TIKTOK_USERNAME` | 要監聽的 TikTok 直播帳號 |
| 後台（http://127.0.0.1:7860）的設定頁 | 模式（伴侶／直播）、稱謂、角色名、語音引擎等 |

## 不在 GitHub、要自己放的檔案

這些檔案太大或是個人資料，GitHub 上沒有；缺了的功能會自動跳過或降級，不會整個開不起來。

| 位置 | 用途 | 沒有的話 |
|---|---|---|
| `assets/voice/xiaoyi_girl_ref.wav`、`xiaoyi_ref.wav`、`xiaoyi_japanese_ref.wav` | 語音合成的聲線參考音 | 本地 GPT-SoVITS 聲線不能用，改走雲端／Edge 語音 |
| `models/rvc/weights/7L_v2.pth`、`models/rvc/indices/7L_v2_*.index` | 翻唱的 7L 歌聲模型 | 不能翻唱新歌（已有快取的照樣能唱） |
| `models/rvc/rmvpe.pt` | 翻唱音高偵測 | 同上 |
| `models/roformer/` | 翻唱人聲分離 | 第一次用會自動下載 |
| `models/fastembed/`、`models/wespeaker_zh_cnceleb_resnet34.onnx` | 記憶搜尋、聲紋辨識 | 第一次用會自動下載 |
| `midi_sheets/*.mid` | 鋼琴譜 | 點曲時會上網抓 MIDI 存進來 |
| `songs_library/` | 翻唱快取 | 自動產生 |
| `data/` | 記憶、觀眾資料、紀錄 | 自動產生 |
| `vts_token.txt` | VTube Studio 授權 | 第一次連線在 VTS 按允許後自動產生 |

外部工具（可選，裝在別的地方就好）：GPT-SoVITS（本地語音合成，預設找 `C:\Users\<你>\GPT-SoVITS`）、RVC-WebUI（重新訓練聲線用）。

## 啟動

- `V7.bat`：啟動 7L（掛掉會自動重啟；建立 `STOP_7L.flag` 可以停止重啟）
- 後台：http://127.0.0.1:7860
- `bot.bat`：Discord 機器人
- `7L.bat`／`7L.py`：Discord 那塊的舊入口

## 測試

```bash
python -m pytest tests
```

測試不會寫 `data/`。

## 文件

- `docs/AI_SOURCES.md`：每個功能用哪個 AI、哪把金鑰
- `knowledge/啟動與故障排除.md`：常見問題
