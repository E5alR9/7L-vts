import os
import sys
import time
import subprocess
import soundfile as sf
import torch
import librosa
import numpy as np

# 設定 RVC 路徑與環境變數
sys.path.append(os.path.join(os.path.dirname(__file__), "services", "rvc"))
os.environ["rmvpe_root"] = os.path.abspath("models/rvc")

from infer.module.models import SynthesizerTrnMs768NSFsid
from infer.hubert import load_hubert_model
from infer.vc.pipeline import Pipeline

class DummyConfig:
    def __init__(self, device="cuda:0", is_half=False):
        self.device = device
        self.is_half = is_half
        self.x_pad = 3
        self.x_query = 10
        self.x_center = 60
        self.x_max = 65

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
device = "cuda:0" if torch.cuda.is_available() else "cpu"
print(f"🚀 初始化 RVC RMVPE 轉音引擎 (設備: {device})...")

hubert_model = load_hubert_model(device, is_half=False)

def find_target_dir(keyword):
    base = "songs_library/cover_cache/htdemucs"
    for d in os.listdir(base):
        if keyword in d:
            return os.path.join(base, d)
    return None

ado_dir = find_target_dir("Ado")
if not ado_dir:
    # 嘗試找包含 Ado 的目錄
    for d in os.listdir("songs_library/cover_cache/htdemucs"):
        print("Folder:", d)
print("Ado dir:", ado_dir)

vocal_path = os.path.join(ado_dir, "vocals.wav")
inst_path = os.path.join(ado_dir, "no_vocals.wav")

# 先剪輯 50s ~ 80s (30秒副歌) 作為測試片段
clip_voc = "songs_library/cover_cache/ado_voc_chorus.wav"
clip_inst = "songs_library/cover_cache/ado_inst_chorus.wav"

subprocess.run([
    FFMPEG, "-y",
    "-ss", "50", "-t", "30",
    "-i", vocal_path,
    "-ar", "16000", clip_voc
], capture_output=True)

subprocess.run([
    FFMPEG, "-y",
    "-ss", "50", "-t", "30",
    "-i", inst_path,
    "-ar", "44100", clip_inst
], capture_output=True)

print("✅ 副歌片段音訊準備完成")

def convert_rvc(vocal_in, inst_in, out_mp3, model_name, key=0, index_rate=0.85):
    t0 = time.time()
    model_path = f"models/rvc/weights/{model_name}.pth"
    index_path = f"models/rvc/indices/{model_name}.index"
    
    cpt = torch.load(model_path, map_location="cpu")
    config = cpt["config"]
    tgt_sr = config[-1]
    config[-3] = cpt["weight"]["emb_g.weight"].shape[0]
    
    net_g = SynthesizerTrnMs768NSFsid(*config, is_half=False)
    net_g.load_state_dict(cpt["weight"], strict=False)
    net_g.eval().to(device)
    
    cfg = DummyConfig(device=device, is_half=False)
    pipeline = Pipeline(tgt_sr, cfg)
    
    audio, sr = librosa.load(vocal_in, sr=16000)
    times = [0, 0, 0]
    sid = 0
    
    print(f"⚡ 正在進行 RVC 變聲: 模型={model_name}, key={key}, f0=rmvpe, index_rate={index_rate}...")
    audio_opt = pipeline.pipeline(
        hubert_model,
        net_g,
        sid,
        audio,
        times,
        key,
        "rmvpe",
        index_path if os.path.exists(index_path) else "",
        index_rate,
        cpt.get("f0", 1),
        tgt_sr,
        tgt_sr,
        0.25,
        "v2",
        0.33,
    )
    
    temp_voc = out_mp3 + ".temp.wav"
    sf.write(temp_voc, audio_opt, tgt_sr)
    
    # 專業母帶混音
    cmd_mix = [
        FFMPEG, "-y",
        "-i", temp_voc,
        "-i", inst_in,
        "-filter_complex", "[0:a]volume=1.28,equalizer=f=3200:t=q:w=1.2:g=1.8[v];[1:a]volume=0.92[i];[v][i]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-b:a", "320k",
        out_mp3
    ]
    subprocess.run(cmd_mix, capture_output=True)
    if os.path.exists(temp_voc):
        os.remove(temp_voc)
    print(f"🎉 RVC 翻唱生成完畢: {out_mp3} (耗時: {time.time()-t0:.2f}s, 大小: {os.path.getsize(out_mp3)} bytes)")

# 測試 5 款最具代表性的 7L 少女音色（原調 key=0，完全不扭曲音高，只換少女音色！）
models_to_test = [
    ("keke", "可可_甜美少女音"),
    ("yuner", "雲兒_青春元氣少女音"),
    ("wanxin", "婉心_溫柔清甜女聲"),
    ("caomei", "草莓_軟萌治癒音"),
    ("xuejie", "學姐_清澈靈動音"),
]

for m_key, m_desc in models_to_test:
    out_file = f"songs_library/7L_RVC_千本櫻_{m_desc}_Chorus.mp3"
    if not os.path.exists(out_file):
        convert_rvc(clip_voc, clip_inst, out_file, m_key, key=0, index_rate=0.88)

# 生成完整版 可可 翻唱 (千本櫻整首 3分15秒)
full_keke = "songs_library/7L_cover_千本櫻_7L可可音色版.mp3"
if not os.path.exists(full_keke):
    print("🌟 開始製作 7L 可可 完整版《千本櫻》...")
    convert_rvc(vocal_path, inst_path, full_keke, "keke", key=0, index_rate=0.88)

