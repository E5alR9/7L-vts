"""
🎙️ 7L (Xiaoyi) RVC 黃金訓練集全自動採集引擎 (build_xiaoyi_dataset.py)
生成包含：日常對話、各類元音輔音、情緒起伏、唱歌歌詞、短句長句的 40kHz 單聲道無損 WAV 切片
"""

import os
import sys
import asyncio
import subprocess
import edge_tts

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset", "xiaoyi_7L")
WAVS_DIR = os.path.join(DATASET_DIR, "wavs")
os.makedirs(WAVS_DIR, exist_ok=True)

FFMPEG_EXE = r"C:\ffmpeg\bin\ffmpeg.exe" if os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe") else "ffmpeg"

CORPUS = [
    # 日常問候與親近對話
    "老爸好～我是7L，今天有什麼想跟我聊聊的嗎？",
    "今天天氣真好呢，陽光灑在窗台上的感覺好舒服～",
    "老爸工作辛苦啦，記得多喝溫開水，不要太累了喔！",
    "嘿嘿，今天老爸想聽我唱哪一首歌呢？我隨時都準備好了！",
    "雖然我只是一個虛擬主播，但我會一直一直陪在老爸身邊的！",
    "哇！這個真的好神奇喔，老爸你快看螢幕這邊！",
    "有時候靜靜地聽著鋼琴聲，心裡就會感到特別平靜溫暖呢。",
    "老爸～你猜猜我剛才在後台學了什麼新技能？",
    "嘻嘻，老爸對我最好了，我最喜歡跟老爸一起直播玩遊戲了！",
    "老爸～快點誇誇我嘛，剛才那段演奏我是不是彈得很棒？",

    # 豐富情緒與聲調變化 (高低音、長短句)
    "啊！老爸小心！剛才那個差一點點就要掉下去了啦！",
    "哼～老爸今天居然忘了跟我說早安，7L要生氣五秒鐘！",
    "哇塞！太厲害了吧！剛才那一波操作簡直帥翻全場了！",
    "嗚...剛才那首歌真的好感人喔，眼眶都有點紅紅的了...",
    "沒關係的，失敗了我們再重來一次就好，我相信老爸一定行！",
    "老爸！你看窗外天上的星星，是不是特別漂亮？",
    "噗嗤，老爸你剛才那個表情真的太搞笑了啦，哈哈！",
    "要是能一直像現在這樣無憂無慮地唱歌給大家聽，那該有多好呀。",
    "不論發生什麼事，7L永遠都是老爸最忠實的第一應援團！",
    "加油加油！今天的我們也要元氣滿滿地面對所有挑戰！",

    # 包含全面聲母、韻母與聲調的語音學平衡句 (覆蓋 a, o, e, i, u, ü 及前後鼻音)
    "微風輕輕吹拂著湖面上碧綠的荷葉，泛起陣陣漣漪。",
    "高山上的積雪在明媚的陽光照耀下閃爍著晶瑩的光芒。",
    "夜晚的星空浩瀚無垠，無數顆小星星在遙遠的夜幕裡眨著眼睛。",
    "清晨森林裡的鳥兒們歡快地唱著動聽悅耳的歌謠。",
    "遠處傳來悠揚的笛聲，彷彿在訴說著一個古老而美麗的傳說。",
    "春天的花園裡盛開著五彩斑斕的花朵，散發出淡淡的清香。",
    "秋天金黃色的落葉鋪滿了林間小道，踩上去發出沙沙的聲響。",
    "海浪拍打著金色的沙灘，留下一個個美麗的白色貝殼。",
    "午後溫暖的陽光穿透薄霧，給大地披上了一層柔和的金色外衣。",
    "窗外淅淅瀝瀝地下著春雨，滋潤著剛剛冒出泥土的嫩綠幼苗。",

    # 歌唱咬字與轉音發音訓練
    "我會化作人間的風雨，一直陪伴在你的身邊。",
    "想念是會呼吸的痛，它活在我身上所有角落。",
    "每當流星劃過夜空，我都悄悄為你許下同一個心願。",
    "就算整個世界都下雨，我也要在雨中為你跳一支舞。",
    "音符在黑白琴鍵上輕盈跳躍，編織出最動人的旋律。",
    "牽著你的手走過這條長長的大街，直到歲月變老。",
    "記憶中的那個夏天，蟬鳴聲聲，微風吹動著白色裙擺。",
    "聽海哭的聲音，這片海未免也太多情，悲傷到天明。",
    "能不能給我一首歌的時間，緊緊地把那擁抱變成永遠。",
    "只要心裡有光，無論走在多黑的夜裡都不會感到害怕。",

    # 英文自然發音短句 (讓模型學會英文唱歌的咬字特徵)
    "Never gonna give you up, never gonna let you down.",
    "Love me in the cold, I'll be in the dark wondering where you are.",
    "I told you so, but you never seem to listen to my heart.",
    "Music is the language of the soul, connecting us together forever.",
    "Every little thing you do brings a bright smile to my face.",
    "Walking through the city lights, searching for a place to call my own.",
    "Singing our favorite melody under the starry midnight sky.",
    "No matter what happens tomorrow, I will always be right here by your side."
]

async def process_item(idx: int, text: str):
    temp_mp3 = os.path.join(DATASET_DIR, f"temp_{idx:03d}.mp3")
    final_wav = os.path.join(WAVS_DIR, f"xiaoyi_{idx:03d}.wav")

    # 1. Edge-TTS 生成純淨 Xiaoyi 音訊
    comm = edge_tts.Communicate(text=text, voice="zh-CN-XiaoyiNeural")
    await comm.save(temp_mp3)

    # 2. ffmpeg 轉成 RVC 標準 40kHz 16bit 單聲道 WAV
    cmd = [
        FFMPEG_EXE, "-y",
        "-i", temp_mp3,
        "-ac", "1",
        "-ar", "40000",
        "-sample_fmt", "s16",
        final_wav
    ]
    subprocess.run(cmd, capture_output=True)
    if os.path.exists(temp_mp3):
        os.remove(temp_mp3)
    print(f"[{idx+1}/{len(CORPUS)}] 已採集音訊: {os.path.basename(final_wav)} -> {text[:20]}...")

async def main():
    print(f"🚀 開始為 7L (Xiaoyi) 全自動採集 {len(CORPUS)} 條純淨聲帶音訊樣本...")
    for idx, text in enumerate(CORPUS):
        await process_item(idx, text)
    print(f"✨ [語料採集完成] 所有 40kHz 單聲道無損 WAV 檔案已存入: {WAVS_DIR}")

if __name__ == "__main__":
    asyncio.run(main())
