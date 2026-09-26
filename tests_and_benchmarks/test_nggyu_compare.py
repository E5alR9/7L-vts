import os
import sys
import time
import asyncio
import subprocess
import edge_tts
import soundfile as sf
import torch
import librosa

sys.path.append(os.path.join(os.path.dirname(__file__), "services", "rvc"))

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
print(f"🚀 初始化 Never Gonna Give You Up 測試引擎 (設備: {device})...")

hubert_model = load_hubert_model(device, is_half=False)

def convert_rvc_model(vocal_clip, inst_clip, out_mp3, model_name, key=12, index_rate=0.75):
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
    
    audio, sr = librosa.load(vocal_clip, sr=16000)
    times = [0, 0, 0]
    sid = 0
    audio_opt = pipeline.pipeline(
        hubert_model,
        net_g,
        sid,
        audio,
        times,
        key,
        "pm",
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
    
    # 混音伴奏
    cmd_mix = [
        FFMPEG, "-y",
        "-i", temp_voc,
        "-i", inst_clip,
        "-filter_complex", "[0:a]volume=1.28[v];[1:a]volume=0.92[i];[v][i]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-b:a", "320k",
        out_mp3
    ]
    subprocess.run(cmd_mix, capture_output=True)
    if os.path.exists(temp_voc):
        os.remove(temp_voc)
    print(f"✨ 已生成 RVC 翻唱: {out_mp3} ({model_name}, key={key:+d}, 耗時: {time.time()-t0:.2f}s)")

async def generate_original_xiaoyi_tts(out_mp3: str):
    print("🎙️ 正在生成原版 Xiaoyi TTS 語音對照音訊...")
    text = (
        "老爸～這是我平時說話的原版 Xiaoyi 聲線喔！"
        "Never gonna give you up, never gonna let you down, "
        "never gonna run around and desert you! "
        "老爸聽聽看，哪一個 RVC 歌聲聽起來最舒服自然？"
    )
    communicate = edge_tts.Communicate(text, "zh-CN-XiaoyiNeural", rate="+0%", pitch="+0Hz")
    await communicate.save(out_mp3)
    print(f"✅ 原版 Xiaoyi TTS 對照音訊已生成: {out_mp3}")

async def main():
    # 1. 生成原版 Xiaoyi TTS 聲線
    tts_out = "songs_library/TTS_Xiaoyi_original_compare.mp3"
    await generate_original_xiaoyi_tts(tts_out)
    
    # 2. Never Gonna Give You Up 經典副歌 (42s ~ 64s, 22秒)
    vocal_clip = "songs_library/test_ai_cover/nggyu_voc_42_64.wav"
    inst_clip = "songs_library/test_ai_cover/nggyu_inst_42_64.wav"
    
    print("\n=== 生成《Never Gonna Give You Up》純 RVC 女聲翻唱版本 ===")
    # 方案 1: 可可 Keke (甜美可愛少女音, +12 半音)
    convert_rvc_model(vocal_clip, inst_clip, "songs_library/7L_RVC_NGGYU_Keke_KeyPlus12.mp3", "keke", key=12)
    
    # 方案 2: 雲兒青春 Yuner (青春活力少女音, +12 半音)
    convert_rvc_model(vocal_clip, inst_clip, "songs_library/7L_RVC_NGGYU_Yuner_KeyPlus12.mp3", "yuner", key=12)
    
    # 方案 3: 婉心 Wanxin (溫柔甜美女聲, +12 半音)
    convert_rvc_model(vocal_clip, inst_clip, "songs_library/7L_RVC_NGGYU_Wanxin_KeyPlus12.mp3", "wanxin", key=12)
    
    # 方案 4: 草莓 Caomei (軟萌治癒甜妹音, +12 半音)
    convert_rvc_model(vocal_clip, inst_clip, "songs_library/7L_RVC_NGGYU_Caomei_KeyPlus12.mp3", "caomei", key=12)
    
    # 方案 5: 學姐 Xuejie (清澈靈動音, +12 半音)
    convert_rvc_model(vocal_clip, inst_clip, "songs_library/7L_RVC_NGGYU_Xuejie_KeyPlus12.mp3", "xuejie", key=12)
    
    # 方案 6: 可可 Keke (原調 0 半音，不升八度)
    convert_rvc_model(vocal_clip, inst_clip, "songs_library/7L_RVC_NGGYU_Keke_Key0.mp3", "keke", key=0)

if __name__ == "__main__":
    asyncio.run(main())
