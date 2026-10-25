# -*- coding: utf-8 -*-
"""給模型看的工具宣告（2026-10-25 從主程式搬出來）。

INTERACTIONS_TOOLS：專案格式的函式工具清單（主腦 REST、Groq、NV 共用；core.groq_router 會轉成 OpenAI 格式）。
build_genai_declarations：轉成 Gemini FunctionDeclaration；GENAI_TOOLS 是轉好的（子智能體用）。
LIVE_API_TOOLS：Live 主腦只拿一個 invoke_subagent（非阻塞），實際操作交給子智能體。
工具的執行在主程式的 execute_tool_dispatch。
"""
from google.genai import types

INTERACTIONS_TOOLS = [
    {
        "type": "function",
        "name": "trigger_vts_expression",
        "description": "切換 VTube Studio Live2D 虛擬主播表情",
        "parameters": {
            "type": "object",
            "properties": {
                "expression_name": {"type": "string", "description": "表情/動作名稱：愛心, 星星眼, 臉紅, 哭哭, 生氣, 黑臉, 黑化, 暈暈, 流汗, 著急, 花花, 問號, 話筒(麥克風), 打遊戲, 雙馬尾, 右抬手, 左抬手, 比心, wink, 皺眉, 震驚, 白眼"}
            },
            "required": ["expression_name"]
        }
    },
    {
        "type": "function",
        "name": "search_google",
        "description": "使用 Google 搜尋即時聯網資訊與時事",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜尋關鍵字"}
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "search_knowledge",
        "description": "檢索 7L 本地 RAG 記憶庫（過往對話、觀眾檔案、外部知識文件），回答涉及過去發生過的事或既有資料時優先使用",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要檢索的中文關鍵句（例如：老爸的鍵盤型號、某觀眾的關係）"}
            },
            "required": ["query"]
        }
    },
    {
        # 2026-10-24 補上：派發器一直有 set_timer，但工具清單沒宣告，模型看不到，
        # 「明天提醒我帶傘」會被子智能體亂丟給 search_knowledge，提醒從沒設成
        "type": "function",
        "name": "set_timer",
        "description": "設定提醒或倒數計時：「10 分鐘後叫我」「一小時後提醒我喝水」「明天提醒我帶傘」都用這個。時間到 7L 會主動開口提醒",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "距離現在幾秒後提醒（10 分鐘=600、1 小時=3600、明天同一時間=86400）"},
                "message": {"type": "string", "description": "到時候要提醒的內容，例如「記得帶傘」"}
            },
            "required": ["seconds", "message"]
        }
    },
    {
        "type": "function",
        "name": "generate_ai_image",
        "description": "繪製 AI 圖片",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "繪圖提示詞 (英文佳)"}
            },
            "required": ["prompt"]
        }
    },
    {
        "type": "function",
        "name": "move_spatial_position",
        "description": "控制 7L 的 Live2D 模型在畫布內平滑走位、相對微調或縮放大小。支援命名位置（如：'正中間', '鋼琴旁', '靠近', '躲角落', '左側', '右側', '原位'）以及相對微調（如：'往右+10', '往左-15', '往上+5', '往下-10', '放大+10', '縮小-5'）或直接指定 delta_x / delta_y / delta_size。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_position": {"type": "string", "description": "目標位置名稱或微調指令：例如 '正中間', '鋼琴旁', '靠近', '躲角落', '左邊', '右邊', '原位', '往右+10', '往左-15', '往上+5', '往下-10', '放大+10', '縮小-5', '自由漫遊'"},
                "delta_x": {"type": "number", "description": "X 軸相對平移量（例如: +10 代表向右微調, -10 代表向左微調）"},
                "delta_y": {"type": "number", "description": "Y 軸相對平移量（例如: +10 代表向上微調, -10 代表向下微調）"},
                "delta_size": {"type": "number", "description": "尺寸相對縮放量（例如: +5 代表放大, -5 代表縮小）"},
                "scale_factor": {"type": "number", "description": "整體等比例縮放倍率（例如: 1.2 放大 20%, 0.8 縮小 20%）"}
            },
            "required": ["target_position"]
        }
    },
    {
        "type": "function",
        "name": "open_virtual_piano",
        "description": "拿出 88 鍵鋼琴介面在桌面上就位待命。當老爸說『拿出鋼琴』、『打開鋼琴』、『把鋼琴拿出來』時調用（不自動彈奏曲目，供老爸練習、彈奏或點歌）。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "pe.play_virtual_piano",
        "description": "7L 坐到鋼琴前演奏 88 鍵平台鋼琴曲目。【調用時機】：只有當老爸或觀眾明確要求『彈鋼琴』、『彈琴』、『彈一首...』或『youtuber查...然後彈』時才可調用！如果是要求『唱』、『唱歌』，請改用 auto_sing_song！",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {"type": "string", "description": "鋼琴曲名稱、關鍵字或 YouTube 搜尋詞 (如：鐘, 幻想即興曲, 愛之夢, 給愛麗絲, 卡農, 敘事曲, 神隱少女, 殘酷天使, 千本櫻等)"},
                "force_online": {"type": "boolean", "description": "當使用者指定「用 YouTube 查」、「youtuber 查」、「線上搜」、「yt 查」等關鍵字時【務必設為 True】，系統將強制跳過本地樂譜，直接向 YouTube/線上即時抓取最新演奏版本開彈。"},
                "auto_radio_mode": {"type": "boolean", "description": "當說『接著一直隨便彈吧』、『隨便彈』、『隨機一直彈』、『連續彈』、『開啟鋼琴電台』時設為 True，進入無限隨機接曲模式。"},
                "custom_sheet": {"type": "string", "description": "可選自訂虛擬鋼琴樂譜字串"}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "pe.play_midi_band",
        "description": " MIDI 樂隊演奏：多軌 MIDI 保留原通道＋音色同時發聲（小提琴拉主旋律＋鋼琴伴奏＋貝斯＋鼓組一次到位）。當老爸或觀眾說『樂隊演奏』、『多種樂器一起』、『小提琴加鋼琴』、『完整編制』時調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "midi_file": {"type": "string", "description": "本地 .mid 檔案路徑（midi_sheets/ 下）"},
                "band_preset": {"type": "string", "description": "配器預設：piano_trio／violin_lead／guitar_band／strings／rock_band／jazz_trio／brass_band／folk_band／synth_band／orchestra"},
                "layers": {"type": "string", "description": "疊層合奏（可選）：更多 .mid 路徑逗號分隔，同時合奏"},
                "title": {"type": "string", "description": "曲名（播報用）"}
            },
            "required": ["midi_file"]
        }
    },
    {
        "type": "function",
        "name": "pe.compose_and_play_original_piano",
        "description": "7L 現場自主即興作曲並親自演奏原創 88 鍵鋼琴曲。當老爸或觀眾說『妳自己寫一首歌來彈』、『現場自創一首』、『即興彈一首』、『自己創作一首鋼琴曲』、『來首妳自己原創的曲子』時調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "theme_or_title": {"type": "string", "description": "想要創作的曲目主題或名稱 (如：'星空漫步', '午後微風', '給老爸的歌')"},
                "mood_or_style": {"type": "string", "description": "音樂風格與情緒氛圍 (如：'治癒抒情', '日系ACG', '輕快俏皮', '溫柔憂傷')"}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "video.request_watch",
        "description": " 觀眾點播看全片：把 YouTube 網址排入點播隊列，7L 後台看完播報（字幕→音軌轉錄→抽幀看圖→摘要）。當觀眾說『看這個』、『點播』、『幫我看這部片』並貼網址時調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube 影片網址或 11 碼 ID"}
            },
            "required": ["url"]
        }
    },
    {
        "type": "function",
        "name": "music.generate_song",
        "description": " AI 作曲（ACE-Step 本地服務）：文字→完整歌曲（含人聲編曲，慢任務）。當老爸或觀眾說『寫一首歌』、『AI 作曲』、『生成一首歌』時調用！（需 ACESTEP_ENABLED=1，否則安全跳過）",
        "parameters": {
            "type": "object",
            "properties": {
                "caption": {"type": "string", "description": "風格描述（如：溫柔抒情流行歌、鋼琴+弦樂、128BPM）"},
                "lyrics": {"type": "string", "description": "歌詞（可空，空＝純音樂）"},
                "duration": {"type": "integer", "description": "時長秒數（10-600，預設 120）"},
                "style": {"type": "string", "description": "補充風格標籤"}
            },
            "required": ["caption"]
        }
    },
    {
        "type": "function",
        "name": "midi.inspect",
        "description": " 讀譜：看 MIDI 檔的軌數／音符數／時長／各軌音色音域。改編前先看結構時調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "midi_sheets/ 下檔名或完整路徑"}
            },
            "required": ["path"]
        }
    },
    {
        "type": "function",
        "name": "midi.edit",
        "description": " 改譜：移調／力度／量化／換音色／加音符／刪音區（二選一動作 op）。當老爸或觀眾說『升調』、『對齊拍子』、『小聲點』、『換小提琴』、『加一段』時調用！改完自動進曲庫，可直接 pe.play_midi_band 演奏。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "midi_sheets/ 下檔名或完整路徑"},
                "op": {"type": "string", "description": "transpose（需 semitones）／velocity（需 scale）／quantize（grid 4/8/16/32）／program（需 channel＋program）／add（需 notes JSON 陣列）／delrange（需 lo＋hi）"},
                "semitones": {"type": "integer", "description": "移調半音數"},
                "scale": {"type": "number", "description": "力度倍率 0.1-2.0"},
                "grid": {"type": "string", "description": "量化網格"},
                "channel": {"type": "integer", "description": "通道 0-15（鼓 9 拒絕）"},
                "program": {"type": "integer", "description": "音色 0-127"},
                "notes": {"type": "string", "description": "加音符 JSON 陣列 [{pitch,start_beat,duration_beats,velocity,channel}]"},
                "lo": {"type": "integer", "description": "刪音區下限"},
                "hi": {"type": "integer", "description": "刪音區上限"}
            },
            "required": ["path", "op"]
        }
    },
    {
        "type": "function",
        "name": "music.transcribe_song",
        "description": " 逆向譜面：YT 下載音檔→人聲分離→旋律轉 MIDI＋和弦辨識→進曲庫。當老爸或觀眾說『把這首歌扒下來』、『轉成譜』、『學這首歌』並貼網址時調用！（慢任務，後台跑）",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube 網址或 11 碼 ID"},
                "title": {"type": "string", "description": "存檔曲名（可空）"}
            },
            "required": ["url"]
        }
    },
    {
        "type": "function",
        "name": "music.stem_pack",
        "description": " 扒帶包：一鍵產出分軌（人聲/鼓/貝斯/吉他/鋼琴/其他）＋去人聲卡拉＋75%降速＋和弦進行＋旋律MIDI。當老爸或觀眾說『扒這首歌』、『要伴奏』、『分軌』並貼網址時調用！（慢任務，十幾分鐘）",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube 網址或 11 碼 ID"}
            },
            "required": ["url"]
        }
    },
    {
        "type": "function",
        "name": "pe.mashup_virtual_piano",
        "description": "7L 將多首高難度鋼琴曲同時並發演奏 (無數量限制！可同時彈 2首、3首、4首甚至更多，多軌多色瀑布流極限演奏)。當老爸或觀眾說『把A跟B混在一起彈』、『同時彈A、B、C』、『A x B x C 合體』、『A + B + C 多曲合奏』、『把多首練習曲雜在一起彈』時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name1": {"type": "string", "description": "第一首鋼琴曲名稱或包含多首曲目的字串 (例如：'冬風', '鐘', '月光第三樂章', 'Rush E', '冬風 x 月光 x 鐘')"},
                "song_name2": {"type": "string", "description": "第二首鋼琴曲名稱 (可選)"}
            },
            "required": ["song_name1"]
        }
    },
    {
        "type": "function",
        "name": "pe.insert_virtual_piano",
        "description": " 僅在老爸或觀眾明確說『混彈』、『插歌』、『一起彈』、『合體』、『同時演奏』、『再加一首XX一起彈』等字眼時才可調用！若只是單純點播新歌（例如只說『Rush E』、『彈月光』），請調用 pe.play_virtual_piano 進行排隊！",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {"type": "string", "description": "要插入/追加的鋼琴曲名稱 (如：鐘, 幻想即興曲, 冬風, 少女的祈禱)"}
            },
            "required": ["song_name"]
        }
    },
    {
        "type": "function",
        "name": "pe.pause_virtual_piano",
        "description": "暫停當前正在演奏的 88 鍵鋼琴曲目。當老爸或觀眾說『暫停彈琴』、『鋼琴先暫停』、『暫停一下』時調用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "pe.resume_virtual_piano",
        "description": "繼續播放剛才暫停的 88 鍵鋼琴曲目。當老爸或觀眾說『繼續彈』、『鋼琴繼續』、『恢復演奏』時調用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "pe.stop_virtual_piano",
        "description": " 僅在老爸明確說出『收起鋼琴』、『關閉鋼琴』、『把鋼琴收起來』、『別彈鋼琴了』時才可調用！收起 88 鍵鋼琴並讓 7L 回到原本位置。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "stop_singing",
        "description": "停止 7L 正在唱的歌（老爸說『停止唱歌』『別唱了』『不要唱了』『歌停一下』時用）。這不是點歌：不要把『停止』『暫停』當成歌名去呼叫 auto_sing_song。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "list_piano_sheets",
        "description": "【只有當老爸或觀眾明確要求『列出所有曲庫/查看歌單』時才調用】列出所有內建鋼琴曲目清單。注意：若只是問『這首是什麼歌』，直接回答當前曲名即可，無需列出全部曲庫。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "auto_sing_song",
        "description": "7L 進行全自動 AI 翻唱演唱（支援全網 YouTube 點歌、伴奏分離、少女音色轉換與立體聲母帶混音）。當老爸或觀眾說『唱歌』、『唱一首...』、『翻唱...』、『唱 Never Gonna Give You Up』、『點歌：...（唱歌）』時調用！注意：若是彈鋼琴請調用 pe.play_virtual_piano，若是唱歌/翻唱請調用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {"type": "string", "description": "想要 7L 翻唱的歌曲名稱或關鍵字。【保持歌名原貌】：請「一字不漏」地將老爸或觀眾輸入的原始字詞放進來，保留原始錯字與特殊拼寫！(如：Never Gonna Give You Up, 晴天, 刀醬 dadada)"}
            },
            "required": ["song_name"]
        }
    },
    {
        "type": "function",
        "name": "set_piano_volume",
        "description": "調整 88 鍵平台鋼琴的演奏音量 (0 ~ 200)。只有當老爸或觀眾明確說『鋼琴小聲點』、『鋼琴大聲點』、『音量設為...』時才調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "volume": {"type": "integer", "description": "音量數值，範圍 0 到 200（0 為靜音，100 為預設標準音量，200 為雙倍增益音量）"}
            },
            "required": ["volume"]
        }
    },
    {
        "type": "function",
        "name": "set_piano_speed",
        "description": "調整 88 鍵平台鋼琴的演奏倍速 (0.05x ~ 50.0x / 支援任意自訂倍速數字)。當老爸或觀眾說『鋼琴放慢一點』、『鋼琴快一點』、『鋼琴1.5倍速』、『2倍速彈鋼琴』、『4倍速』、『10倍速』、『原速彈』時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {"type": "number", "description": "播放倍速，支援任意自訂數值（例如 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.5, 4.0, 5.0, 10.0 等，範圍 0.05 到 50.0）"}
            },
            "required": ["speed"]
        }
    },
    {
        "type": "function",
        "name": "set_piano_instrument",
        "description": "切換 88 鍵鋼琴/鍵盤的演奏發聲音色。當老爸說『換成弦樂音色』、『換成吉他』、『切換成電鋼琴』、『用小提琴彈』、『換成管風琴』、『音色換成木琴』時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string", "description": "想要切換的音色名稱，如：'鋼琴'、'明亮鋼琴'、'電鋼琴'、'大鍵琴'、'木琴'、'管風琴'、'手風琴'、'吉他'、'電吉他'、'小提琴'、'大提琴'、'豎琴'、'弦樂'、'人聲合唱'、'小號'、'薩克斯風'、'長笛'、'合成器'、'古箏'、'卡林巴'"}
            },
            "required": ["instrument"]
        }
    },
    {
        "type": "function",
        "name": "control_microphone",
        "description": " 僅在老爸明確說出『關閉麥克風』或『開啟麥克風』時才可調用！開啟(True)或關閉(False)麥克風收音。",
        "parameters": {
            "type": "object",
            "properties": {
                "is_enabled": {"type": "boolean", "description": "True 為開啟收音，False 為靜音"}
            },
            "required": ["is_enabled"]
        }
    },
    {
        "type": "function",
        "name": "clear_all_memories",
        "description": "清空 7L 的雲端與本地記憶",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "update_cloud_knowledge",
        "description": "7L 自主更新或記憶雲端大腦認知庫與提示詞（Firestore 永久大腦）。當學到新梗、新知識、老爸習慣、或想調整世界觀/說話風格/案例/心智規範時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "提示詞/認知類別：'persona_core'（核心世界觀/自我認知）、'conversation_style'（講話風格/語調）、'memes'（流行語與梗）、'facts'（學會的事實/偏好）、'rules'（心智規範）、'streamer_bio'（直播人設）、'proactive_guide'（主動發話引導）、'banned_phrases'（禁忌詞）"
                },
                "content": {
                    "type": "string",
                    "description": "要寫入或記憶的內容描述（例如：'笑死（極度好笑）' 或 '老爸喜歡深夜寫 Python' 或 '極致俐落搞笑'）"
                }
            },
            "required": ["category", "content"]
        }
    }
]


def build_genai_declarations(is_proactive=False):
    decls = []
    for tool in INTERACTIONS_TOOLS:
        if is_proactive and tool["name"] in ["control_microphone", "clear_all_memories"]:
            continue
        props = {}
        for p_name, p_spec in tool.get("parameters", {}).get("properties", {}).items():
            p_type = p_spec.get("type", "string").upper()
            if p_type == "BOOLEAN": p_type = "BOOLEAN"
            elif p_type in ["NUMBER", "INTEGER", "FLOAT"]: p_type = "NUMBER"
            else: p_type = "STRING"
            props[p_name] = types.Schema(
                type=p_type,
                description=p_spec.get("description", "")
            )
        decl = types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=types.Schema(
                type="OBJECT",
                properties=props,
                required=tool.get("parameters", {}).get("required", [])
            )
        )
        decls.append(decl)
    
    # 2026-10-24 拿掉 google_search：這個帳號的金鑰全部沒有 Google 搜尋額度（31 把、Live 與 REST 實測都回
    # 「exceeded your current quota」），帶著它的觀眾回覆／看板大腦／主動發話 Gemini 呼叫每次都失敗，
    # 還會被誤判成當日額度用完、把金鑰冷卻到午夜。搜尋改由 search_google 函式工具（Tavily）負責。
    return [types.Tool(function_declarations=decls)]


def _invoke_subagent_declaration(non_blocking: bool) -> types.FunctionDeclaration:
    """主腦唯一的工具。Live 主腦用非阻塞版；REST 大腦（沒有 Live 時）用一般版，同一份說明。"""
    # 非阻塞：主腦不用等子智能體跑完才說話（阻塞版實機查匯率靜默 17 秒、想點子 33 秒，2026-10-24）。
    # 實測她呼叫時幾乎不開口，改由 _handle_invoke_subagent 先回中間回應請她答應。
    # 描述不叫她「先答應」：那樣她更常只嘴上說「停下囉」卻沒呼叫（停止彈琴 0/3）
    decl = types.FunctionDeclaration(
        name="invoke_subagent",
        description="當老爸明確要求進行操作（例如點歌、唱歌、彈琴、停止或暫停鋼琴、計時、查資料）時，呼叫此工具。將任務交給背景的子智能體處理。只有呼叫才會真的執行，光說「好了」不算；結果回來系統會告訴妳。注意：若只是純聊天，請不要呼叫此工具！看螢幕畫面不要用這個工具（子智能體看不到畫面），請照規則說 [TOOL:VISION]。舞台動作（彈琴、唱歌、邊彈邊唱、停止唱歌、收起／暫停／繼續鋼琴、看 YouTube 影片）請同時填 action 和歌名或網址，系統會直接照做；其他事 action 填 other。",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "task_instruction": types.Schema(
                    type="STRING",
                    description="要交給子智能體執行的任務，例如「幫我點歌 晴天」、「查現在台北天氣」"
                ),
                # 2026-10-25：舞台動作直接給結構化欄位，CPU 照欄位執行，不再用正則猜她轉述的說法
                "action": types.Schema(
                    type="STRING",
                    enum=["play_piano", "sing", "play_and_sing", "stop_singing",
                          "stop_piano", "pause_piano", "resume_piano", "watch_video", "other"],
                    description="play_piano 彈琴／sing 唱歌／play_and_sing 邊彈邊唱／stop_singing 停止唱歌／"
                                "stop_piano 收起鋼琴／pause_piano 暫停鋼琴／resume_piano 繼續彈／"
                                "watch_video 看 YouTube 影片／other 其他（查資料、計時、作曲…）"
                ),
                "song": types.Schema(type="STRING", description="歌名或曲名（彈琴、唱歌、邊彈邊唱時填，只填歌名）"),
                "song2": types.Schema(type="STRING", description="邊彈邊唱但彈和唱不同首時，要唱的那首"),
                "url": types.Schema(type="STRING", description="看影片時的 YouTube 網址"),
            },
            required=["task_instruction"]
        )
    )
    if non_blocking:
        decl.behavior = types.Behavior.NON_BLOCKING
    return decl


LIVE_API_TOOLS = [types.Tool(function_declarations=[_invoke_subagent_declaration(True)])]
REST_BRAIN_TOOLS = [types.Tool(function_declarations=[_invoke_subagent_declaration(False)])]

GENAI_TOOLS = build_genai_declarations(is_proactive=False)

DECLARED_TOOL_NAMES = frozenset(t["name"] for t in INTERACTIONS_TOOLS)
# 副腦偶爾回宣告裡沒有的工具名（2026-10-26 實機：查匯率回 search_query），常見的搜尋說法對回 search_google
_TOOL_NAME_ALIASES = {"search_query": "search_google", "web_search": "search_google", "google_search": "search_google",
                      "search_web": "search_google", "search": "search_google", "google": "search_google"}


def resolve_tool_name(name: str) -> str:
    """模型回的工具名 → 宣告裡的名字；不認得回空字串（呼叫端當作沒呼叫）。
    也認少了 pe.／video. 這類前綴、或把點寫成底線的。以前不認得的名字照樣派發，派發器不認得就默默沒做，
    主腦還收到「已經做了」。"""
    n = (name or "").strip()
    if n in DECLARED_TOOL_NAMES:
        return n
    if n in _TOOL_NAME_ALIASES:
        return _TOOL_NAME_ALIASES[n]
    for d in DECLARED_TOOL_NAMES:
        if n and (d.split(".")[-1] == n or d.replace(".", "_") == n):
            return d
    return ""
