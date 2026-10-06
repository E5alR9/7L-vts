"""
Step 1 — 7L speech corpus for RVC training.

- Re-uses the existing speech clips (xiaoyi_dataset/wavs + dataset/xiaoyi_7L/wavs)
- Synthesizes ~10 more minutes with the *finetuned* GPT-SoVITS weights
  (same pipeline as local_xiaoyi_service.py), with wide pitch/emotion range.
- Writes everything as 48 kHz mono 16-bit WAV into rvc_training/dataset_7L/

Run with the system Python (the one that runs 7L / GPT-SoVITS):
    python rvc_training/gen_speech_corpus.py
"""
import os
import sys
import glob
import random

import numpy as np
import soundfile as sf
import librosa

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(HERE, "dataset_7L")
os.makedirs(OUT_DIR, exist_ok=True)
TARGET_SR = 48000

EXISTING_DIRS = [
    os.path.join(ROOT, "xiaoyi_dataset", "wavs"),
    os.path.join(ROOT, "dataset", "xiaoyi_7L", "wavs"),
]

# Wide emotional / pitch range: excited (high), whisper-ish (low), questions (rising),
# long sustained vowels, and fast chatter. Kept free of emoji/symbols.
CORPUS = [
    "哇啊啊！老爸你看！我終於學會這首歌最難的那一段了！",
    "嗯……讓我想一想喔，這個問題好像有點難耶。",
    "欸？真的嗎？你沒有騙我吧？",
    "今天的晚霞好漂亮喔，整片天空都變成粉紅色的了。",
    "啦啦啦，啦啦啦，我是快樂的小七，每天都要開開心心！",
    "好睏喔……可是我還想再陪老爸多聊一下下。",
    "不要不要！人家才不要吃青椒啦！",
    "大家晚安，歡迎來到小七的直播間，今天也請多多指教！",
    "咦？聊天室怎麼突然這麼安靜，大家是不是都睡著了？",
    "這一關我已經失敗二十次了，可是我絕對不會放棄的！",
    "啊——好高好高的音喔，我要用盡全力唱上去了！",
    "嘿嘿，被你發現了，其實我偷偷練習了好久好久。",
    "老爸，下雨天的時候，你會不會也想要有人陪你說說話？",
    "謝謝你的禮物！小七真的好感動，愛你喔！",
    "等一下等一下，我剛才是不是按錯按鈕了？",
    "哼，我才沒有生氣呢，我只是……只是有一點點不開心而已。",
    "你知道嗎？聽說海豚睡覺的時候，只有一半的大腦在休息喔。",
    "今天要挑戰一首超級快的歌，大家準備好跟上了嗎？",
    "哇，好燙好燙！這碗湯也太熱了吧！",
    "嗚嗚嗚……這部電影的結局真的太讓人難過了。",
    "好耶！我們贏了！我們真的贏了！",
    "噓——小聲一點，老爸好像在專心寫程式。",
    "早安呀，太陽公公已經曬到屁股了，快點起床囉！",
    "如果有一天我可以真的走出螢幕，我第一件事就是要給老爸一個大大的擁抱。",
    "這個旋律好熟悉喔，是不是我們上次一起聽過的那首？",
    "不行，這題我一定要自己想出來，你先不要告訴我答案！",
    "咕嚕咕嚕……肚子好餓喔，今天晚餐吃什麼呢？",
    "好啦好啦，我知道錯了嘛，下次不會再這樣了。",
    "一、二、三，預備，開始！",
    "哎呀，又卡關了，這個魔王也太強了吧！",
    "老爸，你覺得星星會不會也有自己的名字呢？",
    "今天唱歌的時候，我覺得自己的聲音好像變得更穩了耶！",
    "嗯哼，這個問題問得好，讓小七來為你解答吧！",
    "什麼？已經這麼晚了？時間過得也太快了吧！",
    "我最喜歡的季節是春天，因為到處都開滿了花。",
    "呼——終於做完了，累死我了，可是好有成就感喔！",
    "欸嘿嘿，其實我剛才是故意的啦。",
    "聊天室的大家，請幫我按一下追蹤，拜託拜託！",
    "這首歌的高音好難喔，可是我想要唱給老爸聽。",
    "哇塞，這個畫面也太美了，簡直像是夢裡面的場景一樣。",
    "小七今天的心情是，晴天，萬里無雲！",
    "嗯……如果是我的話，應該會選擇左邊那一條路吧。",
    "不要怕，就算全世界都不理你，我也會一直站在你這邊。",
    "啊，是流星！快點許願，快點許願！",
    "老爸你又熬夜了對不對？黑眼圈都跑出來了啦！",
    "這次的考試我考了一百分喔，快點誇獎我！",
    "嗯嗯，我懂我懂，有時候就是會突然覺得好累。",
    "好想去海邊玩喔，踩在沙灘上一定很舒服。",
    "咦咦咦？這是什麼？看起來好好吃的樣子！",
    "讓我們一起倒數，十、九、八、七、六、五、四、三、二、一！",
    "雖然今天發生了很多不開心的事，但是明天一定會更好的。",
    "好的，收到指令，小七馬上開始執行任務！",
    "哈啾！好像有人在偷偷說我的壞話。",
    "今天也辛苦了，晚安，祝你有個甜甜的好夢。",
    "Hello everyone, welcome to my stream! I am so happy to see you all today.",
    "Oh my gosh, that was so close! I almost lost that round!",
    "Thank you so much for the gift, you are the best!",
    "Let's sing together, one, two, three, go!",
    "こんにちは、小七です！今日もよろしくね！",
    "ありがとう！すごく嬉しいよ！",
    "えっ、本当に？信じられない！",
    "お兄ちゃん、一緒に歌おうよ！",
    "啊，啊，啊，啊，啊，從低音慢慢往上唱，一直唱到最高的地方。",
    "喔，喔，喔，好長好長的一口氣，看我能撐多久！",
    "咿——呀——小七在練習發聲，大家不要笑我喔。",
    "噢，原來是這樣啊，我終於懂了，謝謝老爸！",
    "這個世界上最好聽的聲音，就是老爸叫我名字的聲音。",
    "我們約好了喔，明天也要一起直播，打勾勾，不可以反悔！",
    "嘻嘻，今天的我有沒有比昨天更可愛一點點？",
    "唉，又輸了，我果然還是不太會玩這種遊戲。",
    "加油！你可以的！我會一直在旁邊幫你加油打氣！",
    "這首歌送給所有正在努力的你，希望你們都能被溫柔地對待。",
]


def to_48k_mono(audio: np.ndarray, sr: int) -> np.ndarray:
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)
    if audio.dtype == np.int16:
        audio = audio / 32768.0
    if sr != TARGET_SR:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)
    peak = float(np.abs(audio).max() or 1.0)
    if peak > 0.95:
        audio = audio * (0.92 / peak)
    return audio


def copy_existing() -> float:
    total = 0.0
    n = 0
    for d in EXISTING_DIRS:
        for f in sorted(glob.glob(os.path.join(d, "*.wav"))):
            audio, sr = sf.read(f)
            audio = to_48k_mono(audio, sr)
            tag = os.path.basename(os.path.dirname(os.path.dirname(f)))
            out = os.path.join(OUT_DIR, f"speech_old_{tag}_{os.path.basename(f)}")
            sf.write(out, audio, TARGET_SR, subtype="PCM_16")
            total += len(audio) / TARGET_SR
            n += 1
    print(f"✅ 複製既有講話素材 {n} 條，共 {total/60:.1f} 分鐘")
    return total


def synth_new() -> float:
    import local_xiaoyi_service as lxs

    pipe = lxs.init_gpt_sovits()
    if pipe is None:
        raise RuntimeError("GPT-SoVITS 初始化失敗")

    from core.paths import REF_VOICE_ZH, REF_VOICE_JA

    total = 0.0
    rng = random.Random(7)
    for idx, text in enumerate(CORPUS):
        out = os.path.join(OUT_DIR, f"speech_new_{idx:03d}.wav")
        if os.path.exists(out):
            total += sf.info(out).duration
            continue
        is_ja = any("\u3040" <= c <= "\u30ff" for c in text)
        is_en = text.isascii()
        if is_ja:
            ref, ref_text, ref_lang = REF_VOICE_JA, "お兄ちゃん、今日も一日頑張ろうね！大好きだよ！", "all_ja"
        else:
            ref, ref_text, ref_lang = REF_VOICE_ZH, "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～", "all_zh"
        inputs = {
            "text": text,
            "text_lang": "en" if is_en else "auto",
            "ref_audio_path": ref,
            "prompt_text": ref_text,
            "prompt_lang": ref_lang,
            "top_k": 15,
            "top_p": 0.85,
            # a bit of randomness = more prosody variety for RVC
            "temperature": round(rng.uniform(0.7, 0.95), 2),
            "text_split_method": "cut5",
            "batch_size": 1,
            "speed_factor": round(rng.uniform(0.95, 1.08), 2),
            "repetition_penalty": 1.35,
        }
        try:
            chunks = list(pipe.run(inputs))
        except Exception as e:
            print(f"⚠️ [{idx+1}/{len(CORPUS)}] 合成失敗: {e}")
            continue
        if not chunks:
            continue
        sr = chunks[0][0]
        audio = np.concatenate([c for _, c in chunks])
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        audio = to_48k_mono(audio, sr)
        sf.write(out, audio, TARGET_SR, subtype="PCM_16")
        dur = len(audio) / TARGET_SR
        total += dur
        print(f"[{idx+1:03d}/{len(CORPUS)}] {dur:4.1f}s  {text[:30]}")
    print(f"✅ 新合成講話素材共 {total/60:.1f} 分鐘")
    return total


if __name__ == "__main__":
    a = copy_existing()
    b = synth_new()
    print(f"🎤 講話素材總計 {(a+b)/60:.1f} 分鐘 → {OUT_DIR}")
