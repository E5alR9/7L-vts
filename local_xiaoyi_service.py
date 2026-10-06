import os
import sys
import io
import time
import asyncio
import numpy as np
import soundfile as sf
import re
import unicodedata

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

#  路徑改為「環境變數優先、退回使用者家目錄」，不再寫死原作者電腦
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.paths import GPT_SOVITS_DIR, FINETUNE_DATA_DIR, REF_VOICE_ZH, REF_VOICE_JA

BASE_DIR = GPT_SOVITS_DIR
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
                    
                    try:
                        import services.auto_cover_pipeline as acp
                        if getattr(acp, "_IS_PRODUCING_COVER", False):
                            stage = "提取 HuBERT/F0 特徵進度 (RVC)"
                    except Exception:
                        pass
                        
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

def init_gpt_sovits():
    global _tts_pipeline
    with _thread_lock:
        if _tts_pipeline is not None:
            return _tts_pipeline
            
        prev_cwd = os.getcwd()
        try:
            os.chdir(BASE_DIR)
            from TTS_infer_pack.TTS import TTS, TTS_Config
            config = TTS_Config("GPT_SoVITS/configs/tts_infer.yaml")
            config.device = "cuda"
            config.is_half = True
            config.t2s_weights_path = os.path.join(GPT_SOVITS_DIR, "GPT_weights_v2", "xiaoyi_finetune-e4.ckpt")
            config.vits_weights_path = os.path.join(FINETUNE_DATA_DIR, "opt", "xiaoyi_finetune", "xiaoyi_sovits_inference.pth")
            config.cnhubert_base_path = "pretrained_models/chinese-hubert-base"
            config.bert_base_path = "pretrained_models/chinese-roberta-wwm-ext-large"
            
            _tts_pipeline = TTS(config)
            
            #  核心預熱與常駐快取：初始化時即完成參考音與文字 BERT 萃取，使後續所有合成省去 80% 時間！
            try:
                ref_audio = REF_VOICE_ZH
                ref_text = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
                with capture_tts_output():
                    _tts_pipeline.set_ref_audio(ref_audio)
                    # 預熱一次
                    _dummy = next(_tts_pipeline.run({
                        "text": "哈囉",
                        "text_lang": "auto",
                        "ref_audio_path": ref_audio,
                        "prompt_text": ref_text,
                        "prompt_lang": "zh",
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
    global _tts_pipeline
    with _thread_lock:
        if _tts_pipeline is None:
            init_gpt_sovits()
        if _tts_pipeline is None:
            print("❌ [_tts_pipeline 為 None，無法合成]")
            return b""
            
        try:
            #  智能全自動語言邊界判定 (精準區分「正統日語」vs「中文夾雜日文梗/外來語」)
            import re
            num_kana = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF]', text))
            num_hanzi = len(re.findall(r'[\u4E00-\u9FFF]', text))
            has_chinese_markers = bool(re.search(r'[的了嗎吧呢這那是在說妳你我他們著啦喔呀嘛欸咦啥誰怎麼盧搞弄為什麼]', text))
            
            # 判斷是否為「正統日語句子」：
            # 1. 純日語假名（如 "こんにちは", "ありがとう", "だいすき"）
            # 2. 假名佔比豐富 (>= 35%) 且無典型中文獨有語氣助詞
            # 3. 若含有中文助詞（如 "想被罵バカ的話，去找老爸盧啦"），判定為中文語境！
            is_real_japanese = False
            if num_kana > 0:
                if num_hanzi == 0:
                    is_real_japanese = True
                elif not has_chinese_markers and (num_kana / (num_kana + num_hanzi) >= 0.35):
                    is_real_japanese = True
                elif has_chinese_markers and (num_kana / (num_kana + num_hanzi) >= 0.65):
                    is_real_japanese = True
            
            if is_real_japanese:
                #  正統日語模式：採用高音甜美版曉伊日語提示音（360Hz 少女高音）
                ref_audio = REF_VOICE_JA
                ref_text = "お兄ちゃん、今日も一日頑張ろうね！大好きだよ！"
                ref_lang = "all_ja"
                text_lang = "ja" if num_hanzi == 0 else "auto"
                top_k = 15
                top_p = 0.75
                temp = 0.65
                speed = 1.0
            else:
                #  中文主體模式：
                # 採用中文參考音訊，若為純中文則鎖定 'zh' 避免被誤判為日文，若有日文夾雜則交由 'auto'
                ref_audio = REF_VOICE_ZH
                ref_text = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
                ref_lang = "all_zh"
                has_english = bool(re.search(r'[a-zA-Z]', text))
                text_lang = "zh" if (num_kana == 0 and not has_english) else "auto"
                top_k = 15
                top_p = 0.80
                temp = 0.80
                speed = 1.05
            
            #  符號與專有名詞防卡頓處理：將數學字母/全形/特殊符號正規化為標準 ASCII (修復 KeyError)
            text = unicodedata.normalize('NFKC', text)
            # 過濾非發音顏文字 (如 ⌒☆ )，波浪號/符號轉為元氣感嘆號「！」
            text = re.sub(r'[∠・ω<>\-_]+', '', text) # 改為只針對特定顏文字常見特殊符號移除
            text = re.sub(r'[⌒☆★♪♡✧✦๑•̀ㅂ•́و✧~～]+', '！', text)
            text = text.replace("7L", "小七").replace("7l", "小七")
            text = re.sub(r'[，,]{2,}', '，', text)
            text = re.sub(r'[！!]{2,}', '！', text).strip(' ，,')

            inputs = {
                "text": text,
                "text_lang": text_lang,
                "ref_audio_path": ref_audio,
                "prompt_text": ref_text,
                "prompt_lang": ref_lang,
                "top_k": top_k,
                "top_p": top_p,
                "temperature": temp,
                "text_split_method": "cut5",
                "batch_size": 2, # 適度放大 batch_size 加速顯卡推理
                "speed_factor": speed,
                "repetition_penalty": 1.35,
            }
            
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("tts_progress", {
                    "active": True,
                    "stage": "啟動神經語音合成...",
                    "percent": 5,
                    "text": text[:35]
                })
            except Exception:
                pass

            with capture_tts_output():
                gen = _tts_pipeline.run(inputs)
                chunks = list(gen)
            if not chunks:
                try:
                    import services.web_dashboard as web_dash
                    web_dash.broadcast_event("tts_progress", {"active": False, "stage": "完成", "percent": 100})
                except Exception:
                    pass
                return b""
            sr = chunks[0][0]
            if len(chunks) == 1:
                audio = chunks[0][1]
            else:
                audio = np.concatenate([c for _, c in chunks])
            
            # 轉為 16-bit PCM numpy 陣列
            if audio.dtype != np.int16:
                if audio.dtype == np.float32 or audio.dtype == np.float64:
                    #  Peak Normalize：峰值超過 0.95 時整體等比縮放，絕對杜絕削波爆音
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

async def get_xiaoyi_audio_bytes(text: str) -> bytes:
    """
    非同步調用封裝，防止阻塞主線程
    """
    return await asyncio.to_thread(synthesize_xiaoyi_bytes, text)

if __name__ == "__main__":
    import asyncio
    async def test():
        b = await get_xiaoyi_audio_bytes("哈囉！老爸，我現在已經成功升級到本地顯卡運算囉！")
        print("合成音訊字節數:", len(b))
    asyncio.run(test())
