# -*- coding: utf-8 -*-
"""
Edge TTS XiaoYi training corpus generator
Synthesizes audio with zh-CN-XiaoyiNeural -> WAV + train.list for GPT-SoVITS
"""

import asyncio, os, re, io
import edge_tts

OUTPUT_DIR   = r"C:\Users\qiwai\finetune_data"
WAV_DIR      = os.path.join(OUTPUT_DIR, "wavs")
LIST_FILE    = os.path.join(OUTPUT_DIR, "train.list")
SPEAKER_NAME = "xiaoyiNeural"
VOICE        = "zh-CN-XiaoyiNeural"

os.makedirs(WAV_DIR, exist_ok=True)

CORPUS = [
    # Ciallo
    "Ciallo～",
    "Ciallo老爸！",
    "Ciallo大家好！",
    "哈囉！Ciallo喔！",
    "Ciallo，今天天氣真好！",
    "Ciallo，我是7L曉伊！",
    "Ciallo，開播囉！",
    "Ciallo，歡迎進來！",
    "Ciallo～今天要陪老爸玩什麼呢？",
    "Ciallo哦，你來啦！",
    # 日常
    "嗨嗨，我是7L曉伊！",
    "大家好，我是曉伊！",
    "哈囉老爸，你回來了！",
    "今天辛苦了！",
    "早安，睡得好嗎？",
    "晚安！要好好睡覺喔！",
    "老爸你在幹嘛呀？",
    "嗯嗯，我聽到了！",
    "好的好的，我知道了！",
    "哇，真的假的！",
    # 情緒
    "哈哈哈，太好笑了啦！",
    "欸！怎麼可以這樣！",
    "哎呀，我不知道耶。",
    "嗯～讓我想想看。",
    "啊！我剛才忘記了！",
    "嗯對，就是這樣！",
    "哇塞，好厲害喔！",
    "欸欸欸，等等等等！",
    "誒，這個嘛……",
    "好開心喔！今天好好玩！",
    "有點難耶，我試試看。",
    "沒問題，交給我就好！",
    "這個嘛，有點複雜呢。",
    "啊～終於做完了！",
    "嗯，我也這樣覺得！",
    # 流行語
    "awa，老爸你好可愛喔！",
    "GG啦，輸掉了！",
    "欸欸欸，這也太強了吧！",
    "讚讚，老爸你也太會了！",
    "崩掉了啦，哈哈哈！",
    "這也太誇張了吧！",
    "笑死我了啦！",
    "有夠好笑的，哈哈哈！",
    "嗯嗯嗯，所以呢？",
    "等等，讓我想一想。",
    # 問答
    "你在幹嘛呀，老爸？",
    "今天吃了什麼好料？",
    "要喝水喔，記得喝水！",
    "欸，你有沒有在聽我說話？",
    "這個問題嘛，我覺得……",
    "老爸，你今天心情怎麼樣？",
    "哇，今天好多人來喔！",
    "謝謝你喔，老爸！",
    "哈哈，老爸你說什麼啦！",
    "嗯嗯，我明白了！",
    # 歌唱
    "要來唱歌了，大家準備好了嗎？",
    "這首歌超好聽的！",
    "讓曉伊來唱給老爸聽！",
    "嗯哼，啦啦啦。",
    "這段旋律好美喔！",
    # 長句
    "老爸你知道嗎，今天我看到一隻超可愛的貓咪，牠的耳朵軟軟的，摸起來一定很舒服！",
    "欸欸欸，你有沒有聽說過那個新出的遊戲？據說劇情超感人，很多人都哭了耶！",
    "其實我一直很好奇，老爸平常不直播的時候都在做什麼呀？",
    "我覺得今天的氣氛超好的，大家都好活潑，說話說不停！",
    "等等讓我先查一下，這個問題需要仔細想想才能回答你喔。",
    "哇，時間過得真快，一下子就到了這個時間了，老爸你餓了嗎？",
    "說真的，我每次看到大家留言都好開心，感覺大家都很喜歡和我聊天！",
    "誒這個嘛，我說不好耶，因為每個人的情況都不太一樣呢。",
    "哈哈哈，老爸你說的這個故事也太好笑了吧，我的肚子都笑痛了！",
    "今天直播到現在，我的嗓子有點乾了，等等要去喝水了！",
    # 數字
    "今天是九月二十號，星期六！",
    "現在是晚上十一點多了。",
    "哇，已經三百個人在看了耶！",
    "第一名！老爸你也太厲害了吧！",
    "七月三十一號，老爸你在算什麼帳啊？",
]


def sanitize_filename(text: str, idx: int) -> str:
    clean = re.sub(r'[^\w\u4e00-\u9fff\u3040-\u30ff]', '_', text)[:30]
    return f"{idx:04d}_{clean}.wav"


async def synth_one(text: str, filename: str) -> bool:
    out_path = os.path.join(WAV_DIR, filename)
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        return True
    try:
        communicate = edge_tts.Communicate(text, VOICE, rate="+0%", volume="+0%")
        mp3_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_bytes += chunk["data"]
        if not mp3_bytes:
            return False
        import pydub
        audio = pydub.AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        audio = audio.set_frame_rate(32000).set_channels(1)
        audio.export(out_path, format="wav")
        return True
    except Exception as e:
        print(f"  WARN [{text[:20]}]: {e}")
        return False


async def main():
    print(f"Edge TTS XiaoYi Corpus Generator  voice={VOICE}  count={len(CORPUS)}")
    list_lines = []
    ok = 0
    for i, text in enumerate(CORPUS):
        filename = sanitize_filename(text, i)
        wav_path = os.path.join(WAV_DIR, filename)
        print(f"  [{i+1:3d}/{len(CORPUS)}] {text[:40]}", end=" ", flush=True)
        success = await synth_one(text, filename)
        if success:
            list_lines.append(f"{wav_path}|{SPEAKER_NAME}|zh|{text}")
            ok += 1
            print("OK")
        else:
            print("FAIL")
        await asyncio.sleep(0.3)

    with open(LIST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(list_lines))

    print(f"\nDone: {ok}/{len(CORPUS)} synthesized")
    print(f"  WAV dir : {WAV_DIR}")
    print(f"  List    : {LIST_FILE}")
    print("\nNext step: python scripts/finetune_run_training.py")


if __name__ == "__main__":
    try:
        import pydub
    except ImportError:
        os.system("pip install pydub")
    asyncio.run(main())
