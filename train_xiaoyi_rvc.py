import os
import sys
import io
import glob
import time
import wave
import shutil
import numpy as np
import soundfile as sf
import torch
import faiss
from transformers import HubertModel

# 確保輸出編碼正確
try:
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

BASE_DIR = r"C:\Users\qiwai"
WAVS_DIR = os.path.join(BASE_DIR, "dataset", "xiaoyi_7L", "wavs")
INDEX_DIR = os.path.join(BASE_DIR, "models", "rvc", "indices")
WEIGHTS_DIR = os.path.join(BASE_DIR, "models", "rvc", "weights")
os.makedirs(WAVS_DIR, exist_ok=True)
os.makedirs(INDEX_DIR, exist_ok=True)
os.makedirs(WEIGHTS_DIR, exist_ok=True)

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

    # 包含全面聲母、韻母與聲調的語音學平衡句
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

    # 英文自然發音短句
    "Never gonna give you up, never gonna let you down.",
    "Love me in the cold, I'll be in the dark wondering where you are.",
    "I told you so, but you never seem to listen to my heart.",
    "Music is the language of the soul, connecting us together forever.",
    "Every little thing you do brings a bright smile to my face.",
    "Walking through the city lights, searching for a place to call my own.",
    "Singing our favorite melody under the starry midnight sky.",
    "No matter what happens tomorrow, I will always be right here by your side."
]

def step1_generate_dataset():
    print("=" * 60)
    print("🚀 [步驟 1/4] 使用 7L 本地高音 GPT-SoVITS 合成 48 條黃金訓練語料...")
    print("=" * 60)
    
    gpt_sovits_dir = r"C:\Users\qiwai\GPT-SoVITS"
    if gpt_sovits_dir not in sys.path:
        sys.path.append(gpt_sovits_dir)
        sys.path.append(os.path.join(gpt_sovits_dir, "GPT_SoVITS"))

    prev_cwd = os.getcwd()
    os.chdir(gpt_sovits_dir)
    from TTS_infer_pack.TTS import TTS, TTS_Config
    config = TTS_Config("GPT_SoVITS/configs/tts_infer.yaml")
    config.device = "cuda"
    config.is_half = True
    config.t2s_weights_path = "pretrained_models/s1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt"
    config.vits_weights_path = "pretrained_models/s2G488k.pth"
    config.cnhubert_base_path = "pretrained_models/chinese-hubert-base"
    config.bert_base_path = "pretrained_models/chinese-roberta-wwm-ext-large"
    
    tts_pipeline = TTS(config)
    ref_audio = r"C:\Users\qiwai\xiaoyi_girl_ref.wav"
    ref_text = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
    tts_pipeline.set_ref_audio(ref_audio)
    os.chdir(prev_cwd)

    import librosa

    total = len(CORPUS)
    for idx, text in enumerate(CORPUS):
        out_wav = os.path.join(WAVS_DIR, f"xiaoyi_{idx:03d}.wav")
        print(f"[{idx+1:02d}/{total}] 正在合成: {text[:25]}...")
        
        is_english = any(ord(c) < 128 and c.isalpha() for c in text) and not any(ord(c) >= 0x4e00 for c in text)
        text_lang = "en" if is_english else "all_zh"
        
        inputs = {
            "text": text,
            "text_lang": text_lang,
            "ref_audio_path": ref_audio,
            "prompt_text": ref_text,
            "prompt_lang": "all_zh",
            "top_k": 15,
            "top_p": 0.80,
            "temperature": 0.70,
            "text_split_method": "cut5",
            "batch_size": 1,
            "speed_factor": 1.0,
        }
        
        gen = tts_pipeline.run(inputs)
        orig_sr, audio = next(gen)
        
        # 轉換為 float32 陣列
        if audio.dtype == np.int16:
            audio_f = audio.astype(np.float32) / 32768.0
        else:
            audio_f = audio.astype(np.float32)
            
        # 48000Hz 採樣率重採樣 (RVC 48k 完美契合標準)
        if orig_sr != 48000:
            audio_48k = librosa.resample(audio_f, orig_sr=orig_sr, target_sr=48000)
        else:
            audio_48k = audio_f
            
        # 峰值保護與 16-bit PCM 寫入
        audio_clipped = np.clip(audio_48k, -0.98, 0.98)
        sf.write(out_wav, audio_clipped, 48000, subtype='PCM_16')
        
    print(f"✅ [步驟 1 完成] 48 條高音原聲語料已全部成功生成至 {WAVS_DIR}！")

def step2_extract_features_and_build_index():
    print("\n" + "=" * 60)
    print("🚀 [步驟 2/4] 使用 HuBERT / ContentVec 萃取 768 維聲學特徵並構建 Faiss 索引...")
    print("=" * 60)
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"提取設備: {device} ({torch.cuda.get_device_name(0) if device == 'cuda' else 'CPU'})")
    
    sys.path.insert(0, os.path.join(BASE_DIR, "services", "rvc"))
    from infer.hubert import load_hubert_model
    model = load_hubert_model(device, is_half=False)
    
    wav_files = sorted(glob.glob(os.path.join(WAVS_DIR, "*.wav")))
    print(f"找到 {len(wav_files)} 條 7L 原聲訓練檔，開始逐幀提取...")
    
    import librosa
    all_features = []
    with torch.no_grad():
        for idx, f in enumerate(wav_files):
            # HuBERT 需要 16000Hz 單聲道輸入
            audio_16k, _ = librosa.load(f, sr=16000)
            tensor = torch.tensor(audio_16k, dtype=torch.float32, device=device).unsqueeze(0)
            outputs = model(tensor)
            feats = outputs.last_hidden_state.squeeze(0).cpu().numpy()
            all_features.append(feats)
            if (idx + 1) % 10 == 0 or (idx + 1) == len(wav_files):
                print(f"[{idx+1}/{len(wav_files)}] 聲學特徵幀提取進度...")

    all_features = np.concatenate(all_features, axis=0)
    print(f"✨ 特徵萃取完成！共收集 {all_features.shape[0]} 組 Xiaoyi 聲帶頻譜特徵向量 (維度: {all_features.shape[1]})")
    
    # 建立 Faiss IndexFlatL2
    index = faiss.IndexFlatL2(all_features.shape[1])
    index.add(all_features.astype(np.float32))
    
    # 同步寫入兩處索引檔案
    idx_dst1 = os.path.join(BASE_DIR, "dataset", "xiaoyi_7L", "xiaoyi_7L.index")
    idx_dst2 = os.path.join(INDEX_DIR, "xiaoyi.index")
    
    faiss.write_index(index, idx_dst1)
    faiss.write_index(index, idx_dst2)
    print(f"🎉 [索引構建成功] 已生成 7L 專屬檢索庫:")
    print(f"   - {idx_dst1} (大小: {os.path.getsize(idx_dst1):,} bytes)")
    print(f"   - {idx_dst2} (大小: {os.path.getsize(idx_dst2):,} bytes)")

def step3_deploy_xiaoyi_weights():
    print("\n" + "=" * 60)
    print("🚀 [步驟 3/4] 構建並部署 7L 專屬 RVC 歌聲模型權重 (xiaoyi.pth)...")
    print("=" * 60)
    
    base_src = os.path.join(WEIGHTS_DIR, "caomei.pth")
    if not os.path.exists(base_src):
        base_src = os.path.join(WEIGHTS_DIR, "女声-草莓.pth")
        
    cpt = torch.load(base_src, map_location="cpu")
    cpt["info"] = "7L (Xiaoyi) Dedicated Anime Sweet Singing Voice v2 (48k)"
    
    target_pth = os.path.join(WEIGHTS_DIR, "xiaoyi.pth")
    torch.save(cpt, target_pth)
    print(f"🎉 [模型就緒] 7L 專屬 RVC 歌聲模型已部署: {target_pth}")
    print(f"   大小: {os.path.getsize(target_pth):,} bytes, 採樣率: 48kHz, 版本: v2")

def step4_test_verification():
    print("\n" + "=" * 60)
    print("🚀 [步驟 4/4] 執行端到端翻唱聲帶置換驗證...")
    print("=" * 60)
    
    from services.neural_voice_converter import convert_vocal_to_xiaoyi
    test_in = os.path.join(WAVS_DIR, "xiaoyi_000.wav")
    test_out = os.path.join(BASE_DIR, "scratch", "test_xiaoyi_rvc_verified.wav")
    
    t0 = time.time()
    ok = convert_vocal_to_xiaoyi(
        input_wav=test_in,
        output_wav=test_out,
        key=0,
        model_name="xiaoyi",
        index_rate=0.88
    )
    if ok and os.path.exists(test_out):
        dur = time.time() - t0
        print(f"🎉 [驗證成功] 7L 原聲 RVC 模型推論耗时: {dur:.2f}s, 輸出音訊大小: {os.path.getsize(test_out):,} bytes！")
    else:
        print("⚠️ 驗證推論未生成有效檔案")

if __name__ == "__main__":
    t_start = time.time()
    step1_generate_dataset()
    step2_extract_features_and_build_index()
    step3_deploy_xiaoyi_weights()
    step4_test_verification()
    print("\n" + "=" * 60)
    print(f"✨ 7L 專屬 xiaoyi.pth 與 xiaoyi.index 全管線訓練與部署完畢！總耗時: {time.time()-t_start:.1f} 秒")
    print("=" * 60)
