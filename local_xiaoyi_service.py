import os
import sys
import io
import time
import asyncio
import numpy as np
import soundfile as sf

os.environ["WANDB_DISABLED"] = "true"
os.environ["WANDB_SILENT"] = "true"

# 確保 Windows 終端輸出中日文字元不崩潰
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys, '__stdout__') and hasattr(sys.__stdout__, 'reconfigure'):
    try:
        sys.__stdout__.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = r"C:\Users\qiwai\GPT-SoVITS"
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)
    sys.path.append(os.path.join(BASE_DIR, "GPT_SoVITS"))

import threading
from contextlib import contextmanager

class _WebLogStream:
    """攔截終端輸出並轉發至 Web Dashboard 後台，避免在主終端洗畫面，並即時解析生成進度"""
    def __init__(self, prefix="[GPT-SoVITS] "):
        self.prefix = prefix
        self.buffer = ""
        self.total_bert_steps = 1
        self.current_bert_step = 0

    def _dispatch_progress(self, line: str):
        try:
            import services.web_dashboard as web_dash
            # 解析 GPT-SoVITS 關鍵階段
            stage = ""
            pct = None
            detail = ""

            if "切分" in line or "cut" in line.lower():
                stage = "切分文字中"
                pct = 15
                detail = line
            elif "实际输入的目标文本" in line or "實際輸入的目標文本" in line:
                stage = "文本切句分析"
                pct = 25
            elif "Bert" in line or "BERT" in line or "bert" in line:
                stage = "提取文字 BERT 特徵"
                pct = 40
            elif "%|" in line:
                # tqdm 進度條匹配 e.g. 100%|████████| 1/1 [00:00<00:00, 42.73it/s]
                import re
                m = re.search(r'(\d+)%', line)
                if m:
                    tqdm_pct = int(m.group(1))
                    pct = 40 + int(tqdm_pct * 0.25)  # 40% ~ 65%
                    stage = "提取 BERT 特徵進度"
                    detail = line
            elif "前端处理后的文本" in line or "前端處理後的文本" in line:
                stage = "音素音律對齊"
                pct = 70
                detail = line
            elif "预测语义" in line or "預測語意" in line or "Token" in line:
                stage = "預測語意 Token (T2S)"
                pct = 85
            elif "合成音频" in line or "合成音頻" in line or "并行合成" in line or "並行合成" in line:
                stage = "聲學模型推理合成 (VITS)"
                pct = 95
            elif "推理" in line:
                stage = "神經網路推理中"
                pct = 75

            if stage:
                web_dash.broadcast_event("tts_progress", {
                    "active": True,
                    "stage": stage,
                    "percent": pct,
                    "detail": detail or line,
                    "text": line
                })
        except Exception:
            pass

    def write(self, s):
        if not s:
            return
        self.buffer += s
        while "\n" in self.buffer or "\r" in self.buffer:
            split_idx = min([i for i in [self.buffer.find("\n"), self.buffer.find("\r")] if i != -1])
            line = self.buffer[:split_idx].strip()
            self.buffer = self.buffer[split_idx+1:]
            if line:
                try:
                    import services.web_dashboard as web_dash
                    web_dash.broadcast_event("tts_log", {"text": f"{self.prefix}{line}"})
                except Exception:
                    pass
                self._dispatch_progress(line)

    def flush(self):
        line = self.buffer.strip()
        self.buffer = ""
        if line:
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("tts_log", {"text": f"{self.prefix}{line}"})
            except Exception:
                pass
            self._dispatch_progress(line)

@contextmanager
def capture_tts_output():
    """將區塊內的 print/tqdm 導向 Web 後台，不印在控制台"""
    old_out = sys.stdout
    old_err = sys.stderr
    redir = _WebLogStream()
    sys.stdout = redir
    sys.stderr = redir
    try:
        yield
    finally:
        try:
            redir.flush()
        except Exception:
            pass
        sys.stdout = old_out
        sys.stderr = old_err

_tts_pipeline = None
_thread_lock = threading.Lock()
# 🛡️ 初始化單例門：同一時間只允許一個線程做 TTS(config) 重型初始化，
# 其他線程等待結果（多線程並發 init 會把 transformers 權重撕成 meta tensor 全滅）
_INIT_LOCK = threading.Lock()
_INIT_DONE = threading.Event()
_INIT_FAIL_TIME = 0.0
_INIT_FAIL_COOLDOWN = 60.0


def ensure_tts_ready(timeout: float = 150.0) -> bool:
    """線程安全取得 pipeline：已就緒秒回；初始化中則等待；剛失敗過就快速失敗不硬碰。
    所有调用入口（預熱/合成/預合成）一律走這扇門，嚴禁直調 init_gpt_sovits。"""
    global _INIT_FAIL_TIME
    if _tts_pipeline is not None:
        return True
    try:
        if time.time() - _INIT_FAIL_TIME < _INIT_FAIL_COOLDOWN:
            return False
    except Exception:
        pass
    # 別的線程正在初始化 → 等它做完（而不是自己再開一輪互踩）
    if _INIT_DONE.is_set():
        pass
    else:
        got_lock = _INIT_LOCK.acquire(blocking=False)
        if not got_lock:
            ok = _INIT_DONE.wait(timeout=min(timeout, 150.0))
            return bool(ok and _tts_pipeline is not None)
        try:
            if _tts_pipeline is None:
                init_gpt_sovits()
                if _tts_pipeline is None:
                    try:
                        _INIT_FAIL_TIME = time.time()
                    except Exception:
                        pass
                else:
                    _INIT_DONE.set()
        finally:
            _INIT_LOCK.release()
    return _tts_pipeline is not None

def init_gpt_sovits():
    global _tts_pipeline
    if _tts_pipeline is not None:
        return _tts_pipeline
        
    prev_cwd = os.getcwd()
    try:
        os.chdir(BASE_DIR)
        from TTS_infer_pack.TTS import TTS, TTS_Config
        config = TTS_Config("GPT_SoVITS/configs/tts_infer.yaml")
        config.device = "cuda"
        config.is_half = True
        config.t2s_weights_path = r"C:\Users\qiwai\GPT-SoVITS\GPT_weights_v2\xiaoyi_finetune-e4.ckpt"
        config.vits_weights_path = r"C:\Users\qiwai\finetune_data\opt\xiaoyi_finetune\xiaoyi_sovits_inference.pth"
        config.cnhubert_base_path = "pretrained_models/chinese-hubert-base"
        config.bert_base_path = "pretrained_models/chinese-roberta-wwm-ext-large"
        
        _tts_pipeline = TTS(config)
        
        # ⚡ 核心預熱與常駐快取：初始化時即完成參考音與文字 BERT 萃取，使後續所有合成省去 80% 時間！
        try:
            ref_audio = r"C:\Users\qiwai\xiaoyi_girl_ref.wav"
            ref_text = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
            with capture_tts_output():
                _tts_pipeline.set_ref_audio(ref_audio)
                # 預熱一次
                _dummy = next(_tts_pipeline.run({
                    "text": "哈囉",
                    "text_lang": "all_zh",
                    "ref_audio_path": ref_audio,
                    "prompt_text": ref_text,
                    "prompt_lang": "all_zh",
                    "batch_size": 1,
                    "speed_factor": 1.0,
                }))
        except Exception:
            pass
            
        return _tts_pipeline
    except Exception as e:
        print(f"❌ [GPT-SoVITS 初始化異常]: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        os.chdir(prev_cwd)

def synthesize_xiaoyi_bytes(text: str) -> bytes:
    """
    同步推論函數，回傳 WAV 格式的 bytes
    """
    return synthesize_xiaoyi_bytes_with_emotion(text, emotion=None)


# 🎭 情緒專用參考音：檔名存在即自動啟用，不存在回退預設曉伊參考音（無需改碼）
# 錄製要求：每段 5~10 秒單人乾聲，對應 prompt_text 必須與音檔內容一字不差！
EMOTION_REF_VOICES = {
    "ask":     {"audio": r"C:\Users\qiwai\xiaoyi_ask_ref.wav",
                "text": "真的嗎？這樣也可以嗎？快告訴我嘛！"},
    "exclaim": {"audio": r"C:\Users\qiwai\xiaoyi_exclaim_ref.wav",
                "text": "哇！太厲害了吧！超級開心的啦！"},
    "soft":    {"audio": r"C:\Users\qiwai\xiaoyi_soft_ref.wav",
                "text": "嗯～好啦，陪你一下下就好喔，最喜歡你了。"},
    "sad":     {"audio": r"C:\Users\qiwai\xiaoyi_sad_ref.wav",
                "text": "嗚…對不起嘛，我不是故意的，原諒我好不好。"},
    "annoyed": {"audio": r"C:\Users\qiwai\xiaoyi_annoyed_ref.wav",
                "text": "哼！才不是那樣啦！笨蛋老爸！"},
}

def _resolve_emotion_ref(emo: str, default_audio: str, default_text: str):
    """有錄情緒參考音就用，沒錄就回退預設（只動中文分支）"""
    try:
        slot = EMOTION_REF_VOICES.get(emo or "default")
        if slot and os.path.exists(slot["audio"]) and os.path.getsize(slot["audio"]) > 5000:
            print(f"🎭 [情緒參考音] {emo} → 使用 {os.path.basename(slot['audio'])}")
            return slot["audio"], slot["text"]
    except Exception:
        pass
    return default_audio, default_text
EMOTION_PRESETS = {
    "default": {"speed": 1.05, "temp": 0.80, "top_p": 0.80},
    "ask":     {"speed": 1.12, "temp": 0.85, "top_p": 0.85},  # 疑問：稍快+發散，尾音自然上揚
    "exclaim": {"speed": 1.15, "temp": 0.85, "top_p": 0.85},  # 驚嘆/興奮：快而亢奮
    "soft":    {"speed": 0.92, "temp": 0.70, "top_p": 0.75},  # 溫柔/撒嬌：慢而收斂
    "sad":     {"speed": 0.90, "temp": 0.65, "top_p": 0.70},  # 難過/道歉：慢而低
    "annoyed": {"speed": 1.08, "temp": 0.75, "top_p": 0.80},  # 生氣/吐槽：快而脆
}

_EMOTION_ALIASES = {
    "疑問": "ask", "問": "ask", "反問": "ask", "好奇": "ask", "ask": "ask", "?": "ask", "？": "ask",
    "驚嘆": "exclaim", "驚訝": "exclaim", "興奮": "exclaim", "激動": "exclaim",
    "開心": "exclaim", "哈哈": "exclaim", "exclaim": "exclaim", "!": "exclaim", "！": "exclaim",
    "溫柔": "soft", "撒嬌": "soft", "害羞": "soft", "臉紅": "soft", "甜": "soft",
    "晚安": "soft", "soft": "soft",
    "難過": "sad", "委屈": "sad", "低落": "sad", "道歉": "sad", "對不起": "sad",
    "抱歉": "sad", "哭": "sad", "sad": "sad",
    "生氣": "annoyed", "吐槽": "annoyed", "傲嬌": "annoyed", "哼": "annoyed",
    "不滿": "annoyed", "annoyed": "annoyed",
}

def detect_emotion(text: str) -> str:
    """從子句尾標點/關鍵詞判定語氣（無 [EMOTION] 明示時用；大腦也可用標籤精確指定）"""
    import re as _re
    t = (text or "").strip()
    if not t:
        return "default"
    tail = t[-8:]
    if _re.search(r'[？?]\s*$', t):
        return "ask"
    if _re.search(r'[!！]\s*$', t):
        return "exclaim"
    if _re.search(r'[～~…。]\s*$', t) and any(k in t for k in ["晚安", "乖", "抱抱", "喜歡", "愛", "嘿嘿", "好夢"]):
        return "soft"
    if any(k in t for k in ["對不起", "抱歉", "嗚", "委屈", "難過", "原諒"]):
        return "sad"
    if any(k in t for k in ["才不", "笨蛋", "哼", "略", "打你"]):
        return "annoyed"
    if any(k in t for k in ["哈哈", "哇", "太棒", "好耶", "萬歲"]):
        return "exclaim"
    if _re.search(r'(嗎|呢|吧|嘛|是不是|對不對|好不好)\s*[，。]?\s*$', tail):
        return "ask"
    return "default"


def _split_by_script(text: str):
    """按假名/非假名切段，無語音字符的純標點併入前一段。回 [(段文字, 是否日語段)]
    - 假名數 >= 漢字數：整句視為正統日語（單段，避免「お兄ちゃん」被漢字切碎）。
    - 漢字主場（如中文夾 SRY•スリー）：只把假名段拆出走日語，其餘走中文。
    """
    import re as _re
    text = text or ""
    kana_n = len(_re.findall(r'[\u3040-\u309F\u30A0-\u30FF]', text))
    hanzi_n = len(_re.findall(r'[\u4E00-\u9FFF]', text))
    if kana_n > 0 and kana_n >= hanzi_n:
        return [(text.strip(), True)] if text.strip() else []
    raw_segs = _re.findall(r'[\u3040-\u309F\u30A0-\u30FF]+|[^\u3040-\u309F\u30A0-\u30FF]+', text)
    merged = []
    for seg in raw_segs:
        if not seg:
            continue
        has_voice = bool(_re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFFa-zA-Z0-9]', seg))
        if not has_voice and merged:
            merged[-1] = (merged[-1][0] + seg, merged[-1][1])
            continue
        is_ja = bool(_re.search(r'[\u3040-\u309F\u30A0-\u30FF]', seg))
        merged.append((seg, is_ja))
    # 短漢字夾在兩段假名之間（如教えて的教）：併入日語側，讀音才連貫
    fixed = []
    for i, (seg, is_ja) in enumerate(merged):
        s = seg.strip()
        if (not is_ja and 0 < len(s) <= 2 and _re.search(r'[\u4E00-\u9FFF]', s)
                and i > 0 and i < len(merged) - 1
                and merged[i - 1][1] and merged[i + 1][1]):
            fixed[-1] = (fixed[-1][0] + seg, True)
            continue
        fixed.append((seg, is_ja))
    # 全是標點的極端情況：當中文單段處理
    if not fixed and text.strip():
        fixed.append((text.strip(), False))
    # 相鄰同語段合併，少跑一次合成
    out = []
    for seg, is_ja in fixed:
        if out and out[-1][1] == is_ja:
            out[-1] = (out[-1][0] + seg, is_ja)
        else:
            out.append((seg, is_ja))
    return out


def _lang_params_for(seg_text: str, emo) -> dict:
    """單段語言參數：含假名→日語，其餘→中文（含情緒預設與情緒參考音）。"""
    import re as _re
    if _re.search(r'[\u3040-\u309F\u30A0-\u30FF]', seg_text):
        return {
            "text_lang": "all_ja",
            "ref_audio": r"C:\Users\qiwai\xiaoyi_japanese_ref.wav",
            "ref_text": "お兄ちゃん、今日も一日頑張ろうね！大好きだよ！",
            "ref_lang": "all_ja",
            "top_k": 15, "top_p": 0.75, "temp": 0.65, "speed": 1.0,
        }
    _preset = EMOTION_PRESETS.get(emo or "default", EMOTION_PRESETS["default"])
    ref_audio = r"C:\Users\qiwai\xiaoyi_girl_ref.wav"
    ref_text = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
    ref_audio, ref_text = _resolve_emotion_ref(emo, ref_audio, ref_text)
    return {
        "text_lang": "zh" if _re.search(r'[a-zA-Z]', seg_text) else "all_zh",
        "ref_audio": ref_audio,
        "ref_text": ref_text,
        "ref_lang": "all_zh",
        "top_k": 15,
        "top_p": _preset["top_p"], "temp": _preset["temp"], "speed": _preset["speed"],
    }


def _run_tts_inputs(inputs: dict, preview_text: str = ""):
    """跑一次管線，回 (sr, audio float)；失敗回 (0, None)。"""
    try:
        import services.web_dashboard as web_dash
        web_dash.broadcast_event("tts_progress", {
            "active": True,
            "stage": "啟動神經語音合成...",
            "percent": 5,
            "text": (preview_text or inputs.get("text", ""))[:35]
        })
    except Exception:
        pass
    try:
        import time as _t
        _t0 = _t.time()
        with capture_tts_output():
            gen = _tts_pipeline.run(inputs)
            chunks = list(gen)
        _t_run = _t.time() - _t0
        try:
            print(f"⏱️ [TTS 分段計時] 管線推理 {len(inputs.get('text',''))} 字耗時 {_t_run:.2f}s")
        except Exception:
            pass
        if not chunks:
            return 0, None
        sr = chunks[0][0]
        audio = chunks[0][1] if len(chunks) == 1 else np.concatenate([c for _, c in chunks])
        return sr, audio
    except Exception as e:
        print(f"❌ [分段合成異常]: {e}")
        return 0, None


def _resample_audio(audio, from_sr: int, to_sr: int):
    """段間取樣率不一致時的線性重取樣（正常不該觸發，保險用）。"""
    try:
        if from_sr == to_sr or len(audio) < 2:
            return audio
        import numpy as _np
        old_idx = _np.linspace(0.0, 1.0, num=len(audio))
        new_len = max(1, int(len(audio) * to_sr / from_sr))
        new_idx = _np.linspace(0.0, 1.0, num=new_len)
        return _np.interp(new_idx, old_idx, audio).astype(audio.dtype)
    except Exception:
        return audio


def synthesize_xiaoyi_bytes_with_emotion(text: str, emotion=None) -> bytes:
    global _tts_pipeline
    if not ensure_tts_ready():
        print("❌ [_tts_pipeline 未就緒（初始化中或冷卻中），本次跳過合成]")
        return b""
    with _thread_lock:
        if _tts_pipeline is None:
            print("❌ [_tts_pipeline 為 None，無法合成]")
            return b""
            
        try:
            # 🎭 語氣解析優先序：函數參數 > 文中 [EMOTION:x] > 標點關鍵詞自動判定（標籤絕不送進合成）
            import re
            emo = None
            if emotion:
                emo = _EMOTION_ALIASES.get(str(emotion).strip(), None)
            m_emo = re.search(r'\[EMOTION[：:]\s*([^\]]+)\]', text, flags=re.IGNORECASE)
            if m_emo and not emo:
                emo = _EMOTION_ALIASES.get(m_emo.group(1).strip(), None)
            text = re.sub(r'\[EMOTION[：:]\s*[^\]]+\]', '', text, flags=re.IGNORECASE)
            if not emo:
                emo = detect_emotion(text)
            # 🛡️ 符號與專有名詞防卡頓處理：過濾非發音顏文字 (如 (∠・ω<)⌒☆ )，波浪號/符號轉為元氣感嘆號「！」
            text = re.sub(r'[\(（][^\)）]*[\)）]', '', text)  # 移除括號表情如 (∠・ω<)
            text = re.sub(r'[⌒☆★♪♡♥✧✦๑•̀ㅂ•́و✧~～]+', '！', text)
            text = text.replace("7L", "小七").replace("7l", "小七")
            text = re.sub(r'[，,]{2,}', '，', text)
            text = re.sub(r'[！!]{2,}', '！', text)
            text = re.sub(r'[？?]{2,}', '？', text).strip(' ，,')
            if not text:
                return b""

            # 🌏 混血句按文字拆段：假名段走日語、漢字段走中文（舊邏輯「見假名就整句轉日語」是 SRY•スリー整句變日語的元兇）
            segments = _split_by_script(text)
            audios = []
            sr = 0
            for seg_text, seg_is_ja in segments:
                params = _lang_params_for(seg_text, emo)
                inputs = {
                    "text": seg_text,
                    "text_lang": params["text_lang"],
                    "ref_audio_path": params["ref_audio"],
                    "prompt_text": params["ref_text"],
                    "prompt_lang": params["ref_lang"],
                    "top_k": params["top_k"],
                    "top_p": params["top_p"],
                    "temperature": params["temp"],
                    "text_split_method": "cut5",
                    "batch_size": 2, # 適度放大 batch_size 加速顯卡推理
                    "speed_factor": params["speed"],
                    "repetition_penalty": 1.35,
                }
                seg_sr, seg_audio = _run_tts_inputs(inputs, preview_text=text[:35])
                if seg_audio is None:
                    continue
                if sr == 0:
                    sr = seg_sr
                elif seg_sr != sr:
                    seg_audio = _resample_audio(seg_audio, seg_sr, sr)
                audios.append(seg_audio)
            if not audios:
                try:
                    import services.web_dashboard as web_dash
                    web_dash.broadcast_event("tts_progress", {"active": False, "stage": "完成", "percent": 100})
                except Exception:
                    pass
                return b""
            audio = audios[0] if len(audios) == 1 else np.concatenate(audios)
            
            # （各段已在 _run_tts_inputs 內合成並拼接，sr 取自首段）
            
            # 轉為 16-bit PCM numpy 陣列
            if audio.dtype != np.int16:
                if audio.dtype == np.float32 or audio.dtype == np.float64:
                    # 🔊 RMS 響度對齊：各子句獨立合成音量不一，先對齊到同一響度再防削波，段落銜接不忽大忽小
                    try:
                        _rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float64)) + 1e-12)))
                        if _rms > 1e-4:
                            _gain = 0.12 / _rms
                            _gain = max(0.5, min(2.0, _gain))
                            audio = audio * _gain
                    except Exception:
                        pass
                    # 🔒 Peak Normalize：峰值超過 0.95 時整體等比縮放，絕對杜絕削波爆音
                    peak = np.abs(audio).max()
                    if peak > 0.95:
                        audio = audio * (0.92 / peak)
                    audio_clipped = np.clip(audio, -1.0, 1.0)
                    pcm_data = (audio_clipped * 32767.0).astype(np.int16)
                else:
                    pcm_data = audio.astype(np.int16)
            else:
                pcm_data = audio
                
            # 確保是 bytes
            pcm_bytes = pcm_data.tobytes()
            
            # 廣播合成完成
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("tts_progress", {"active": False, "stage": "語音生成完畢", "percent": 100})
            except Exception:
                pass

            # 使用 lameenc 編碼為高清 192kbps MP3
            try:
                import lameenc
                encoder = lameenc.Encoder()
                encoder.set_bit_rate(192)
                encoder.set_in_sample_rate(sr)
                encoder.set_channels(1)
                encoder.set_quality(2)  # 2 = 高品質且相容性佳 (0 偶有爆音相容問題)
                mp3_data = encoder.encode(pcm_bytes)
                mp3_data += encoder.flush()
                return bytes(mp3_data)
            except Exception as e:
                # 若 lameenc 失敗則回傳標準 WAV
                buf = io.BytesIO()
                sf.write(buf, audio, sr, format='WAV')
                return buf.getvalue()
        except Exception as e:
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("tts_progress", {"active": False, "stage": f"合成異常: {e}", "percent": 0})
            except Exception:
                pass
            print(f"❌ [GPT-SoVITS 合成異常]: {e}")
            import traceback
            traceback.print_exc()
            return b""

async def get_xiaoyi_audio_bytes(text: str, emotion=None) -> bytes:
    """
    非同步調用封裝，防止阻塞主線程
    emotion: None=自動判定，或指定 ask/exclaim/soft/sad/annoyed（大腦 [EMOTION] 標籤直通）
    """
    return await asyncio.to_thread(synthesize_xiaoyi_bytes_with_emotion, text, emotion)

if __name__ == "__main__":
    import asyncio
    async def test():
        b = await get_xiaoyi_audio_bytes("哈囉！老爸，我現在已經成功升級到本地顯卡運算囉！")
        print("合成音訊字節數:", len(b))
    asyncio.run(test())
