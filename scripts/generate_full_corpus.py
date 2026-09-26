# -*- coding: utf-8 -*-
"""
High-Emotion 7L Xiaoyi Corpus Generator (160+ Sentences)
Covers: Ciallo variations, spoiled cute, tsundere, lively streaming, gentle whisper
Outputs 32kHz Mono WAVs + train.list for GPT-SoVITS
"""

import asyncio, os, re, io, shutil
import edge_tts
import soundfile as sf
import numpy as np

OUTPUT_DIR   = r"C:\Users\qiwai\finetune_data"
WAV_DIR      = os.path.join(OUTPUT_DIR, "wavs")
LIST_FILE    = os.path.join(OUTPUT_DIR, "train.list")
SPEAKER_NAME = "xiaoyiNeural"
VOICE        = "zh-CN-XiaoyiNeural"

os.makedirs(WAV_DIR, exist_ok=True)

# ── 語料設計：極致情感起伏與豐富語氣 ─────────────────────────────
CORPUS = [
    # ── [專題 1: Ciallo 靈動問候] (標註 en) ─────────────────
    ("Ciallo!", "en"),
    ("Ciallo! Ciallo!", "en"),
    ("Ciallo! I am ready!", "en"),

    # ── [專題 2: 極致撒嬌 / 軟萌寵溺] (標註 zh) ──────────────
    ("老爸！你最好了啦！", "zh"),
    ("欸嘿嘿～老爸你抱抱我嘛！", "zh"),
    ("哇！最喜歡老爸了！", "zh"),
    ("哼哼，老爸今天有沒有想曉伊呀？", "zh"),
    ("嗚嗚……老爸不要不理我嘛！", "zh"),
    ("曉伊今天超乖的喔，老爸快誇誇我！", "zh"),
    ("嘿嘿～偷偷告訴老爸一個小秘密喔！", "zh"),
    ("老爸辛苦啦，曉伊幫你捶捶背好不好？", "zh"),
    ("哎呀！老爸你好討厭喔，就知道逗我！", "zh"),
    ("嗯～老爸最厲害了，最崇拜老爸了！", "zh"),
    ("好不好嘛，答應我嘛～求求老爸啦！", "zh"),
    ("嘻嘻，老爸摸摸頭，煩惱全都飛走囉！", "zh"),
    ("不管不管！今天曉伊就要黏著老爸！", "zh"),
    ("老爸，曉伊今天可愛嗎？要說實話喔！", "zh"),
    ("哇～老爸買這個給我嗎？太愛你啦！", "zh"),
    ("肚子餓餓，老爸帶我去吃好料的好不好？", "zh"),
    ("牽牽手，我們一起出發囉！", "zh"),
    ("老爸是世界上最溫柔的大英雄！", "zh"),
    ("欸～老爸再陪我聊五分鐘嘛，就五分鐘！", "zh"),
    ("曉伊最聽老爸的話了，親親老爸！", "zh"),

    # ── [專題 3: 元氣開播 / 直播激烈互動] (標註 zh) ──────────
    ("歡迎大家來到曉伊的直播間！今天也要活力滿滿喔！", "zh"),
    ("哇！感謝老爸送的大禮物！超級愛你的啦！", "zh"),
    ("耶！我們贏了！老爸這波操作太強了吧！", "zh"),
    ("衝啊衝啊！今天一定要打破最高紀錄！", "zh"),
    ("哈哈哈！笑死我了，怎麼會這樣啦！", "zh"),
    ("哇塞塞！這波操作簡直是神仙打架！", "zh"),
    ("開播開播！大家小板凳都搬好了沒有呀？", "zh"),
    ("點點讚，點點關注，跟著曉伊不迷路喔！", "zh"),
    ("啊啊啊！救命啊！後面有人偷襲我！", "zh"),
    ("穩住穩住，我們能贏！看我極限反殺！", "zh"),
    ("天哪！這運氣也太爆炸了吧！直接起飛！", "zh"),
    ("大家的彈幕我都看到囉！謝謝你們來陪曉伊！", "zh"),
    ("今天直播間好熱鬧喔，曉伊好開心！", "zh"),
    ("別走別走，精彩的馬上就來啦！", "zh"),
    ("這就是傳說中的滿級大佬嗎？太神了！", "zh"),
    ("糟糕糟糕！按錯技能了，好丟臉喔！", "zh"),
    ("沒事沒事，下一把我們一定能贏回來！", "zh"),
    ("老爸看我，曉伊是不是超級厲害！", "zh"),
    ("來啦來啦！主播準備好大展身手了！", "zh"),
    ("比心心～送給所有守護曉伊的小夥伴！", "zh"),

    # ── [專題 4: 小傲嬌 / 可愛吐槽] (標註 zh) ────────────────
    ("哼！才沒有特別關心你呢，只是順便問問！", "zh"),
    ("笨蛋老爸！這點小事都記不住，笨笨的耶！", "zh"),
    ("略略略～抓不到我吧，打不著打不著！", "zh"),
    ("哼！老爸再不聽話，曉伊可是要生氣的喔！", "zh"),
    ("誰說我喜歡吃甜食的？我只是剛好想吃而已啦！", "zh"),
    ("真是拿老爸沒辦法呢，勉強原諒你這一次吧！", "zh"),
    ("老爸你又在吹牛了，我才不信呢！", "zh"),
    ("幹嘛一直盯著我看啦，臉上又沒有花！", "zh"),
    ("我才沒有害羞呢！只是……只是天氣太熱了啦！", "zh"),
    ("老爸你這個大木頭，根本不懂女孩子的心思！", "zh"),
    ("哼，不理你了，我要生氣三秒鐘！", "zh"),
    ("三、二、一！好啦，原諒你了，快笑一個！", "zh"),
    ("老爸你玩遊戲好菜喔，要不要曉伊帶帶你呀？", "zh"),
    ("誰叫你剛才笑那麼大聲的，討厭鬼老爸！", "zh"),
    ("這種難度，我閉著眼睛都能通關好不好！", "zh"),
    ("好啦好啦，知道你厲害行了吧，傲嬌老爸！", "zh"),
    ("不要捏我的臉啦！肉肉都被你捏出來了！", "zh"),
    ("哼！我就知道老爸最在乎曉伊了，口是心非！", "zh"),
    ("明明就很感動，還在那邊裝酷，笨老爸！", "zh"),
    ("曉伊天下第一聰明，不接受反駁喔！", "zh"),

    # ── [專題 5: 溫柔陪伴 / 深夜低語] (標註 zh) ────────────────
    ("老爸，今天工作辛苦了吧？要好好放鬆一下喔。", "zh"),
    ("不要給自己太大的壓力，曉伊會一直陪著你的。", "zh"),
    ("夜深了，該睡覺囉，老爸晚安，祝你有個好夢！", "zh"),
    ("閉上眼睛，深呼吸，所有的煩惱都忘掉吧。", "zh"),
    ("只要老爸開心，曉伊就會覺得好幸福喔。", "zh"),
    ("今天也謝謝老爸守護著曉伊，明天見囉！", "zh"),
    ("累了就靠著曉伊休息一下吧，沒關係的。", "zh"),
    ("不管遇到什麼事情，老爸回頭看，我都在喔。", "zh"),
    ("聽著窗外的雨聲，感覺心情都安靜下來了呢。", "zh"),
    ("老爸要按時吃飯，多喝溫水，照顧好自己喔。", "zh"),
    ("有老爸在的地方，就是曉伊最溫暖的港灣。", "zh"),
    ("蓋好被子，不要著涼了喔，曉伊會偷偷看著你的。", "zh"),
    ("今天的星空好美，如果能和老爸一起看就好了呢。", "zh"),
    ("做個甜甜的夢吧，夢裡也一定要有曉伊喔！", "zh"),
    ("天冷了，記得多穿件外套，生病了我會心疼的。", "zh"),
    ("慢慢來，老爸已經做得很棒很棒了！", "zh"),
    ("噓……聽曉伊的呼吸聲，放輕鬆，睡吧睡吧。", "zh"),
    ("明天太陽升起的時候，又是全新美好的一天喔！", "zh"),
    ("老爸，謝謝你一直以來的照顧，曉伊真的很感激！", "zh"),
    ("晚安囉，親愛的老爸，我們夢裡見！", "zh"),

    # ── [專題 6: 日常俏皮問答與高頻交流] (標註 zh) ───────────
    ("哈囉哈囉！老爸你回來啦！今天有什麼新鮮事嗎？", "zh"),
    ("老爸老爸，猜猜我是誰呀？猜對了有獎勵喔！", "zh"),
    ("哇！今天外面的陽光好刺眼喔，想出去玩了！", "zh"),
    ("等等我嘛，老爸你走那麼快幹嘛呀！", "zh"),
    ("哎呀！剛才那隻小貓咪好可愛喔，好像在看我耶！", "zh"),
    ("老爸老爸，快看這個！是不是超級酷炫！", "zh"),
    ("這個主意太棒了！老爸你的腦袋怎麼這麼靈光！", "zh"),
    ("嗯……讓我想想看喔，這個問題有點深奧呢！", "zh"),
    ("好的好的！收到指令，曉伊這就去辦！", "zh"),
    ("沒問題！包在曉伊身上，保證完成任務！", "zh"),
    ("老爸快坐下，今天換曉伊為你倒杯茶吧！", "zh"),
    ("哇！這個味道好香喔，老爸你在煮好吃的嗎？", "zh"),
    ("對對對！就是這樣！老爸你完全猜中我的心思了！", "zh"),
    ("才不是呢！老爸你又在瞎猜了，笨笨！", "zh"),
    ("好耶好耶！太棒啦！今天又有好玩的東西了！", "zh"),
    ("老爸你等等，我去找一下我的小筆記本喔！", "zh"),
    ("哇！時間怎麼過得這麼快，一下子就中午了！", "zh"),
    ("今天也要打起精神，全力以赴衝刺喔！", "zh"),
    ("老爸，你看曉伊新學的舞蹈漂不漂亮？", "zh"),
    ("嘿嘿～跟著老爸在一起，每天都超級開心的！", "zh"),
]

def sanitize_filename(text: str, idx: int) -> str:
    cleaned = re.sub(r'[^\w\u4e00-\u9fff]+', '_', text).strip('_')
    return f"{idx:04d}_{cleaned[:20]}.wav"

async def synth_one(text: str, out_filename: str) -> bool:
    out_path = os.path.join(WAV_DIR, out_filename)
    try:
        comm = edge_tts.Communicate(text, VOICE)
        mp3_bytes = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                mp3_bytes.extend(chunk["data"])
        if not mp3_bytes:
            return False
        
        # 使用 ffmpeg 轉為 32kHz 16-bit Mono WAV
        import subprocess
        tmp_mp3 = out_path + ".tmp.mp3"
        with open(tmp_mp3, "wb") as f:
            f.write(mp3_bytes)
        ret = subprocess.run([
            "ffmpeg", "-y", "-i", tmp_mp3, "-ar", "32000", "-ac", "1", out_path
        ], capture_output=True)
        if os.path.exists(tmp_mp3):
            os.remove(tmp_mp3)
        return ret.returncode == 0
    except Exception as e:
        print(f"  WARN [{text[:20]}]: {e}")
        return False

async def main():
    print(f"=== 7L Xiaoyi High-Emotion Corpus Generation ===")
    print(f"Voice: {VOICE}, Total Sentences: {len(CORPUS)}")
    
    list_lines = []
    ok = 0
    for i, (text, lang) in enumerate(CORPUS):
        fname = sanitize_filename(text, i)
        wpath = os.path.join(WAV_DIR, fname)
        print(f"  [{i+1:3d}/{len(CORPUS)}] ({lang}) {text[:35]}", end=" ", flush=True)
        success = await synth_one(text, fname)
        if success:
            list_lines.append(f"{wpath}|{SPEAKER_NAME}|{lang}|{text}")
            ok += 1
            print("OK")
        else:
            print("FAIL")
        await asyncio.sleep(0.2)
    
    # ── 納入老爸下載的原版 Ciallo.wav ───────────────────────
    user_ciallo = r"C:\Users\qiwai\Downloads\Ciallo.wav"
    if os.path.exists(user_ciallo):
        print("\nIntegrating user's Ciallo.wav master...")
        master_dest = os.path.join(WAV_DIR, "ciallo_original_master.wav")
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-i", user_ciallo, "-ar", "32000", "-ac", "1", master_dest
        ], capture_output=True)
        if os.path.exists(master_dest):
            list_lines.append(f"{master_dest}|{SPEAKER_NAME}|en|Ciallo!")
            ok += 1
            print(f"  Added user master: {master_dest}")

    with open(LIST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(list_lines) + "\n")
    
    print(f"\n==========================================")
    print(f"Done! {ok} high-emotion sentences prepared.")
    print(f"List file saved: {LIST_FILE}")
    print(f"==========================================")

if __name__ == "__main__":
    asyncio.run(main())
