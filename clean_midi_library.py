import os
import sys
import json
import shutil
import re
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

from google import genai
from google.genai import types

MIDI_DIR = os.path.join(os.getcwd(), "midi_sheets")
REMOVED_DIR = os.path.join(MIDI_DIR, "removed_non_songs")
CATALOG_FILE = os.path.join(MIDI_DIR, "midi_catalog.json")

def get_gemini_client():
    raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
    keys = [k.strip() for k in re.split(r'[\s,;]+', raw_keys) if k.strip()]
    if not keys:
        raise ValueError("No GEMINI_API_KEYS found in .env")
    return genai.Client(api_key=keys[0])

def scan_and_clean():
    if not os.path.exists(MIDI_DIR):
        print("❌ midi_sheets folder does not exist!")
        return

    os.makedirs(REMOVED_DIR, exist_ok=True)
    
    # 取得所有 .mid 檔案
    all_files = [
        f for f in os.listdir(MIDI_DIR)
        if f.lower().endswith(('.mid', '.midi')) and os.path.isfile(os.path.join(MIDI_DIR, f))
    ]
    
    print(f"🎵 目前曲庫中共有 {len(all_files)} 首 MIDI 檔案。正在召喚 Gemini AI 進行智能品控審查...")

    client = get_gemini_client()

    prompt = f"""你是一個精通全球音樂、ACG動漫、流行歌曲、古典樂曲與網路迷因音樂的資深音樂庫審核員。
以下是本地鋼琴曲庫中的所有 MIDI 檔案名稱列表（共 {len(all_files)} 個）：

{json.dumps(all_files, ensure_ascii=False, indent=2)}

【任務說明】：
請嚴格審查以上檔名，辨別哪些是「真正/正常的音樂歌曲」，哪些是「顯然不是正常歌曲的雜質檔案」。

【應移除 (REMOVE) 的雜質特徵】：
1. 影片 ID 或爬蟲暫存代碼：例如 `yt_0H4rq0L9OSw.mid`, `yt_xxxx.mid`。
2. 社群農場標題、影片說明或長句灌水：例如 `此影片由ai創作.mid`, `Sister Bao 零AI 全家逼傅老大读MBA...`, `2025328 呂智豪第二節不乖、亂打老師...`。
3. 測試隨手彈奏、網站預設文字或調侃雜音：例如 `OnlineSequencer.net is an online...`, `something i made while pressing random keys...`, `test_local_huahai.mid`, `this sucks.mid`, `DO NOT PRESS y,y,d,p ON THe PIANO.mid`。
4. 日常對話、系統指令或單一字母無意義檔名：例如 `你拿出鋼琴了.mid`, `稱呼.mid`, `還記得我嗎？.mid`, `s.mid`, `曲.1.mid`。

【應保留 (KEEP) 的正常音樂】：
1. 古典名曲（如貝多芬、蕭邦、李斯特、帕海貝爾卡農、德布西、拉赫曼尼諾夫等）。
2. 流行歌曲（如宇多田光 First Love、周杰倫、蔡依林、Coldplay、Taylor Swift、Yoasobi、Ado等）。
3. 動漫/遊戲配樂/V家/東方Project（如 Bad Apple, 千本櫻, JoJo, Undertale, Deltarune, 碧藍檔案, MyGO等）。
4. 著名網路迷因曲/鋼琴練習曲（如 Rush E, 少女A, 俄羅斯搖籃曲, 大悲咒, 天上太陽紅彤彤等）。

請以繁體中文與 JSON 格式輸出，格式必須嚴格符合：
```json
{{
  "remove_files": [
    {{
      "filename": "檔名.mid",
      "reason": "移除原因說明"
    }}
  ],
  "keep_summary": "保留了多少首正常歌曲的簡要說明"
}}
```
"""

    resp = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json"
        )
    )

    try:
        data = json.loads(resp.text)
    except Exception as e:
        # 去除 markdown 標籤再試一次
        clean_text = re.sub(r'^```json\s*', '', resp.text.strip())
        clean_text = re.sub(r'\s*```$', '', clean_text)
        data = json.loads(clean_text)

    remove_list = data.get("remove_files", [])
    keep_summary = data.get("keep_summary", "")

    print(f"\n🧠 [Gemini 審查完畢] 總共辨識出 {len(remove_list)} 個非正常歌曲的雜質檔案！")
    print(f"📊 {keep_summary}\n")

    removed_count = 0
    for item in remove_list:
        fname = item.get("filename")
        reason = item.get("reason", "")
        src = os.path.join(MIDI_DIR, fname)
        dst = os.path.join(REMOVED_DIR, fname)
        if os.path.exists(src):
            shutil.move(src, dst)
            print(f"🗑️ [已移除] {fname} ➔ 原因: {reason}")
            removed_count += 1

    # 同步清理 midi_catalog.json
    if os.path.exists(CATALOG_FILE):
        try:
            with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                cat = json.load(f)
            new_cat = {}
            for k, v in cat.items():
                base_v = os.path.basename(v)
                if os.path.exists(os.path.join(MIDI_DIR, base_v)):
                    new_cat[k] = v
            with open(CATALOG_FILE, "w", encoding="utf-8") as f:
                json.dump(new_cat, f, ensure_ascii=False, indent=2)
            print(f"\n✨ [索引庫同步] midi_catalog.json 已同步清理完畢！")
        except Exception as e:
            print(f"⚠️ 更新 catalog 異常: {e}")

    remaining = [
        f for f in os.listdir(MIDI_DIR)
        if f.lower().endswith(('.mid', '.midi')) and os.path.isfile(os.path.join(MIDI_DIR, f))
    ]
    print(f"\n🎉 清理完成！成功移除了 {removed_count} 個雜音/非正常檔案，已移至 '{REMOVED_DIR}' 備存。")
    print(f"🎹 當前曲庫保留純淨正常曲目共 {len(remaining)} 首！")

if __name__ == "__main__":
    scan_and_clean()
