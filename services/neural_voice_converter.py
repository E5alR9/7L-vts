"""
🎙️ 7L 神經聲線特徵置換引擎 (Neural Voice Timbre Converter)
以 RTX 3080 Ti 顯卡加速，將歌曲原唱聲線置換為 7L (Xiaoyi) 少女專屬音色
"""

import os
import sys
import time
import traceback
import numpy as np
import soundfile as sf
import torch
import librosa

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RVC_ROOT = os.path.join(BASE_DIR, "services", "rvc")
if RVC_ROOT in sys.path:
    sys.path.remove(RVC_ROOT)
sys.path.insert(0, RVC_ROOT)

# 🛡️ 命名空間衝突防禦：若 GPT-SoVITS 的 tools 已先佔用 sys.modules['tools']，直接注入 cuda_graph 模組
try:
    import importlib.util
    _cg_file = os.path.join(RVC_ROOT, "tools", "cuda_graph.py")
    if os.path.exists(_cg_file):
        _spec = importlib.util.spec_from_file_location("tools.cuda_graph", _cg_file)
        _cg_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_cg_mod)
        sys.modules["tools.cuda_graph"] = _cg_mod
        if "tools" in sys.modules:
            setattr(sys.modules["tools"], "cuda_graph", _cg_mod)
except Exception as _e:
    pass

from infer.module.models import SynthesizerTrnMs768NSFsid
from infer.hubert import load_hubert_model
from infer.vc.pipeline import Pipeline

class RVCConfig:
    def __init__(self, device="cuda:0", is_half=False):
        self.device = device
        self.is_half = is_half
        self.x_pad = 1
        self.x_query = 4
        self.x_center = 20
        self.x_max = 25

_HUBERT_MODEL = None
_NET_G_CACHE = {}
_DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

def get_hubert():
    global _HUBERT_MODEL
    if _HUBERT_MODEL is None:
        print(f"📦 [神經語音引擎] 載入 HuBERT 聲學特徵模型 ({_DEVICE})...")
        _HUBERT_MODEL = load_hubert_model(_DEVICE, is_half=False)
    return _HUBERT_MODEL

def get_net_g(model_pth: str):
    global _NET_G_CACHE
    if model_pth not in _NET_G_CACHE:
        print(f"📦 [神經語音引擎] 載入合成器網絡權重: {os.path.basename(model_pth)}...")
        cpt = torch.load(model_pth, map_location="cpu")
        config = cpt["config"]
        tgt_sr = config[-1]
        config[-3] = cpt["weight"]["emb_g.weight"].shape[0]
        
        net_g = SynthesizerTrnMs768NSFsid(*config, is_half=False)
        net_g.load_state_dict(cpt["weight"], strict=False)
        net_g.eval().to(_DEVICE)
        _NET_G_CACHE[model_pth] = (net_g, cpt, tgt_sr)
    return _NET_G_CACHE[model_pth]

def convert_vocal_to_xiaoyi(
    input_wav: str,
    output_wav: str,
    key: float = 0.0,
    index_rate: float = 0.88,
    model_name: str = "xiaoyi",
    model_pth: str = None,
    index_file: str = None,
    auto_pitch: bool = True,
) -> bool:
    """
    使用 7L 官方專屬之曉伊（Xiaoyi）甜美少女歌聲神經模型進行人聲置換
    - key: 音高微調偏移行 (例如 +1.0, -1.0)
    - auto_pitch: 是否啟用樂句級男女聲基頻自動識別 (男聲自動+12半音升八度，女聲維持原調，男女混唱自適應)
    - model_name: 預設 xiaoyi (7L 專屬原聲模型)
    - f0_method: rmvpe (高精度神經音高追蹤)
    """
    os.environ["rmvpe_root"] = os.path.join(BASE_DIR, "models", "rvc")

    if model_pth is None:
        model_pth = os.path.join(BASE_DIR, "models", "rvc", "weights", f"{model_name}.pth")
        if not os.path.exists(model_pth) and model_name == "xiaoyi":
            # 兼容回退草莓備援
            fallback_pth = os.path.join(BASE_DIR, "models", "rvc", "weights", "caomei.pth")
            if os.path.exists(fallback_pth):
                model_pth = fallback_pth

    if index_file is None:
        index_file = os.path.join(BASE_DIR, "models", "rvc", "indices", f"{model_name}.index")
        if not os.path.exists(index_file) and model_name == "xiaoyi":
            idx_backup = os.path.join(BASE_DIR, "dataset", "xiaoyi_7L", "xiaoyi_7L.index")
            if os.path.exists(idx_backup):
                index_file = idx_backup

    if not os.path.exists(model_pth):
        print(f"⚠️ 找不到模型權重: {model_pth}，跳過神經轉換")
        return False

    valid_index = ""
    if os.path.exists(index_file):
        try:
            import faiss
            _idx = faiss.read_index(index_file)
            if _idx.d == 768:
                valid_index = index_file
        except:
            pass

    t0 = time.time()
    try:
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("tts_progress", {
                "active": True,
                "mode": "rvc",
                "stage": "載入 HuBERT 聲學模型",
                "percent": 20,
                "detail": f"正在準備 RVC 模型 ({model_name})..."
            })
        except Exception:
            pass

        hubert = get_hubert()
        net_g, cpt, tgt_sr = get_net_g(model_pth)
        
        cfg = RVCConfig(device=_DEVICE, is_half=False)
        pipeline = Pipeline(tgt_sr, cfg)
        
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("tts_progress", {
                "active": True,
                "mode": "rvc",
                "stage": "讀取原唱音軌特徵",
                "percent": 45,
                "detail": os.path.basename(input_wav)
            })
        except Exception:
            pass

        audio, sr = librosa.load(input_wav, sr=16000)
        times = [0, 0, 0]
        sid = 0
        resample_sr = tgt_sr
        rms_mix_rate = 0.25
        version = cpt.get("version", "v2")
        protect = 0.33
        if_f0 = cpt.get("f0", 1)
        
        if auto_pitch:
            rvc_key = f"auto{key:+0.1f}" if key != 0.0 else "auto"
            pitch_mode_str = f"自適應男女聲智慧辨識" + (f" (偏移: {key:+0.1f})" if key != 0.0 else "")
        else:
            rvc_key = key
            pitch_mode_str = f"固定 key={key:+0.1f}"

        print(f"🎤 [7L 專屬聲線置換中] 正在透過 7L 專屬音色模型置換原唱 (模型={model_name}, 音高模式={pitch_mode_str}, rmvpe)...")
        
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("tts_progress", {
                "active": True,
                "mode": "rvc",
                "stage": "RMVPE 音高預測 & 音色置換 (V2)",
                "percent": 75,
                "detail": f"{pitch_mode_str} | {model_name}"
            })
        except Exception:
            pass

        audio_opt = pipeline.pipeline(
            hubert,
            net_g,
            sid,
            audio,
            times,
            rvc_key,
            "rmvpe",
            valid_index,
            index_rate if valid_index else 0.0,
            if_f0,
            tgt_sr,
            resample_sr,
            rms_mix_rate,
            version,
            protect,
        )
        
        sf.write(output_wav, audio_opt, tgt_sr)
        print(f"🎉 [7L 聲線置換完成] 已生成 7L 專屬翻唱歌聲音軌！(耗時: {time.time()-t0:.2f}s)")
        
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("tts_progress", {
                "active": False,
                "mode": "rvc",
                "stage": f"7L 歌聲置換完成 ({time.time()-t0:.1f}s)",
                "percent": 100,
                "detail": os.path.basename(output_wav)
            })
        except Exception:
            pass

        return True
    except Exception as e:
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("tts_progress", {
                "active": False,
                "mode": "rvc",
                "stage": f"RVC 異常: {e}",
                "percent": 0
            })
        except Exception:
            pass
        print(f"❌ [7L 聲線置換失敗]: {e}")
        traceback.print_exc()
        return False
