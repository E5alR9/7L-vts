import os
import sys
import time
import subprocess
import soundfile as sf
import torch
import librosa

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
print(f"🚀 初始化【極致軟萌甜妹系列】渲染引擎 (設備: {device})...")

hubert_model = load_hubert_model(device, is_half=False)

def convert_sweet(vocal_in, inst_in, out_mp3, model_name, key=0, index_rate=0.75):
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
    
    import faiss
    valid_index = ""
    if os.path.exists(index_path):
        try:
            _idx = faiss.read_index(index_path)
            if _idx.d == 768:
                valid_index = index_path
        except:
            pass

    print(f"⚡ 正在進行轉換: {out_mp3} (模型={model_name}, index={bool(valid_index)})...")
    audio_opt = pipeline.pipeline(
        hubert_model,
        net_g,
        sid,
        audio,
        times,
        key,
        "rmvpe",
        valid_index,
        index_rate if valid_index else 0.0,
        cpt.get("f0", 1),
        tgt_sr,
        tgt_sr,
        0.25,
        "v2",
        0.33,
    )
    
    temp_voc = out_mp3 + ".temp.wav"
    sf.write(temp_voc, audio_opt, tgt_sr)
    
    cmd_mix = [
        FFMPEG, "-y",
        "-i", temp_voc,
        "-i", inst_in,
        "-filter_complex", "[0:a]volume=1.25,equalizer=f=3200:t=q:w=1.2:g=1.5[v];[1:a]volume=0.92[i];[v][i]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-b:a", "320k",
        out_mp3
    ]
    subprocess.run(cmd_mix, capture_output=True)
    if os.path.exists(temp_voc):
        os.remove(temp_voc)
    print(f"🎉 生成成功: {out_mp3} (耗時: {time.time()-t0:.2f}s, 大小: {os.path.getsize(out_mp3)} bytes)")

# 測試音源
cyndi_voc = "songs_library/cover_cache/cyndi_voc_chorus.wav"
cyndi_inst = "songs_library/cover_cache/cyndi_inst_chorus.wav"

nggyu_voc = "songs_library/cover_cache/cateek_voc_42_64.wav"
nggyu_inst = "songs_library/cover_cache/cateek_inst_42_64.wav"

sweet_models = [
    ("peipei", "Peipei", "佩佩（極致軟萌小蘿莉音，比草莓更軟）"),
    ("susu", "Susu", "蘇蘇（純淨動漫甜美女聲，治癒清甜）"),
    ("xiaoqiu", "Xiaoqiu", "小秋（甜美自然少女音，舒服清新）"),
    ("shiliu", "Shiliu", "石榴（靈動俏皮甜妹音，活潑討喜）"),
]

for m_key, m_en, m_desc in sweet_models:
    # 1. 產生《愛你》
    out_aini = f"songs_library/7L_Sweet_AiNi_{m_en}.mp3"
    convert_sweet(cyndi_voc, cyndi_inst, out_aini, m_key, key=0, index_rate=0.75)
    
    # 2. 產生 NGGYU
    out_nggyu = f"songs_library/7L_Sweet_NGGYU_{m_en}.mp3"
    convert_sweet(nggyu_voc, nggyu_inst, out_nggyu, m_key, key=0, index_rate=0.75)

print("🎉 全部【極致軟萌甜妹系列】音檔生成完畢！")
