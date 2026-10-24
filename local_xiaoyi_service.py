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

# SoVITS 切分策略（2026-10-11：cut5 把短句切成 N 小片，某一片會整片靜音且等長，
# 時長守衛看不出來；直播都 ≤60 字，整段一坨最穩；XIAOYI_SPLIT 環境變數可調回）。
# 2026-10-25 起長句由 _split_for_tts 在句末標點切段、每段自己檢查重抽；模型內部仍是 cut0。
XIAOYI_SPLIT_METHOD = os.getenv("XIAOYI_SPLIT", "cut0")

class _WebLogStream:
    """攔截終端輸出並轉發至 Web Dashboard 後台，避免在主終端洗畫面，並即時解析生成進度"""
    def __init__(self, prefix="[GPT-SoVITS] "):
        self.prefix = prefix
        self.buffer = ""
        self.total_bert_steps = 1
        self.current_bert_step = 0
        self._owner = None  # 進入 capture 的線程 id：只解析主人的輸出（2026-10-11）
        self._real_out = None  # 原 stdout：別的線程（如 RVC）原樣放行，不攔截

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
                    # 2026-10-11：這裡只會收到主人（SoVITS）線程的輸出，
                    # RVC 的 tqdm 連線程門都過不了。舊碼用 _IS_PRODUCING_COVER
                    # 把 SoVITS 自己的 BERT 條硬標成 RVC，已刪除。
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
        #  2026-10-11：sys.stdout 是全進程共享的，RVC 在別的線程的 tqdm 也會寫進來。
        #  非主人的輸出原樣放行到真終端，不解析、不廣播（否則 RVC 進度污染粉色 TTS 框）。
        if self._owner is not None and threading.get_ident() != self._owner:
            try:
                (self._real_out or sys.__stdout__).write(s)
            except Exception:
                pass
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
    """將區塊內的 print/tqdm 導向 Web 後台，不印在控制台。
    2026-10-11：只認進入時的線程，別線程（RVC 背景任務）原樣放行真終端。"""
    old_out = sys.stdout
    old_err = sys.stderr
    redir = _WebLogStream()
    redir._owner = threading.get_ident()
    redir._real_out = old_out
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
_REF_ZH = None   # 實際用的中文參考音（停頓壓短版，見 _tight_ref）
_REF_JA = None   # 日文同理：實測失敗率 4/12 → 1/12


# top_p 必須是 1.0（不做核心取樣）：0.8 時念到停頓處，「靜音」單位的機率就佔滿那 80%，候選裡只剩靜音，
# 「結束」和「繼續說話」都被排除，於是空白一路生成到長度上限＝念一半就停。這是 TTS 失敗的根本原因：
# 2026-10-25 實測一次只改一個參數，top_p 0.8→1.0 失敗 15%→0/16；只升溫度 12%、只降 top_k 反而 38%。
_TOP_P = float(os.getenv("XIAOYI_TOP_P", "1.0"))
_SEGMENT_CHARS = int(os.getenv("XIAOYI_SEGMENT_CHARS", "22"))   # 整句不合格時的備援切段長度；0 = 不切段
_SEGMENT_TRIES = 3


def _split_for_tts(text: str, limit: int = None) -> list:
    """長句在句末標點（。！？）切成短段，單句還太長就再從逗號切；太短的段併回前一段。不超過 limit 字就不切。

    為什麼是 22 字：曉伊的 GPT 微調資料 179 段最長 7.9 秒、28 字（中位數 14 字）。超過這長度的句子
    模型沒看過，常念完第一句就停住、後面全是空白到長度上限（2026-10-25 實測長句整句合成約 1/3 失敗）。"""
    limit = _SEGMENT_CHARS if limit is None else limit
    if limit <= 0 or len(text) <= limit:
        return [text]
    parts = []
    for p in re.split(r"(?<=[。！？!?])", text):
        if not p.strip():
            continue
        if len(p) <= limit:
            parts.append(p)
        else:
            parts += [q for q in re.split(r"(?<=[，、；,;])", p) if q.strip()]
    out = []
    for p in parts:
        if out and len(out[-1]) + len(p) <= limit:
            out[-1] += p
        else:
            out.append(p)
    return out or [text]


def _synth_segments(inputs: dict, segs: list, tries: int):
    """逐段合成，每段最多 tries 次（不合格才重抽）。回 (取樣率, 各段音訊, 是否每段都合格)。
    每段不合格到最後就用第一次的結果，交給整句檢查（tts_router）再把關。呼叫端要持有 _thread_lock。"""
    sr = None
    pieces = []
    all_ok = True
    for seg in segs:
        seg_inputs = dict(inputs, text=seg)
        first = None
        seg_ok = False
        # 生成長度上限跟著字數走：卡在靜音循環時早點停（模型預設 54 秒／1500 步，卡一次白等 10~20 秒）
        _tts_pipeline.configs.max_sec = _segment_max_sec(len(seg))
        for _attempt in range(tries):
            with capture_tts_output():
                chunks = list(_tts_pipeline.run(seg_inputs))
            if not chunks:
                continue
            sr = chunks[0][0]
            seg_audio = chunks[0][1] if len(chunks) == 1 else np.concatenate([c for _, c in chunks])
            if _segment_ok(seg_audio, sr, len(seg)):
                first, seg_ok = seg_audio, True
                break
            if first is None:
                first = seg_audio
        all_ok = all_ok and seg_ok
        if first is not None:
            pieces.append(first)
    return sr, pieces, all_ok


def _segment_max_sec(n_chars: int) -> int:
    """這段最多讓模型生成幾秒：預期長度的 3 倍、至少 8 秒。正常念完遠低於此，卡在靜音循環才會撞到。"""
    return int(max(8.0, n_chars * 0.22 * 3))


def _segment_ok(audio, sr: int, n_chars: int) -> bool:
    """一段合成結果像不像念完了：總長沒爆、有聲時間夠、中間沒有長空白。"""
    a = audio.astype(np.float32)
    if audio.dtype == np.int16:
        a /= 32768.0
    win = max(1, int(sr * 0.05))
    k = len(a) // win
    if k == 0:
        return False
    rms = np.sqrt(np.mean(a[: k * win].reshape(k, win) ** 2, axis=1))
    voiced = rms > max(0.01, float(rms.max()) * 0.05)
    idx = np.flatnonzero(voiced)
    if len(idx) == 0:
        return False
    expect = max(1.0, n_chars * 0.22)
    total = len(a) / sr
    gap = float(np.max(np.diff(idx)) - 1) * 0.05 if len(idx) > 1 else 0.0
    return total <= max(6.0, expect * 2.5) and voiced.sum() * 0.05 >= expect * 0.3 and gap <= 2.0


def _tight_ref(path: str) -> str:
    """回傳句間停頓壓到 0.25 秒的參考音（第一次用 ffmpeg 產生在原檔旁邊）；做不出來就用原檔。

    原參考音 7.3 秒裡有一半是句間停頓，模型會學著「念一兩個字就停住、後面全是靜音」：
    實測 12 次失敗 7 次；只壓停頓、音色不變，0/12 失敗，合成也從平均 10 秒變 2.5 秒（2026-10-25）。
    XIAOYI_TIGHT_REF=0 可關掉，改回原檔。"""
    if os.getenv("XIAOYI_TIGHT_REF", "1") == "0" or not path or not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    out = f"{root}_tight{ext or '.wav'}"
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
        return out
    try:
        import subprocess
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-i", path, "-af",
                        "silenceremove=stop_periods=-1:stop_duration=0.25:stop_threshold=-40dB", out],
                       check=True, timeout=30)
        return out if os.path.exists(out) else path
    except Exception as e:
        print(f"⚠️ [GPT-SoVITS] 參考音停頓壓短失敗，改用原檔：{e}")
        return path

def init_gpt_sovits():
    global _tts_pipeline, _REF_ZH, _REF_JA
    with _thread_lock:
        if _tts_pipeline is not None:
            return _tts_pipeline
            
        prev_cwd = os.getcwd()
        try:
            os.chdir(BASE_DIR)
            from TTS_infer_pack.TTS import TTS, TTS_Config
            config = TTS_Config("GPT_SoVITS/configs/tts_infer.yaml")
            config.device = "cuda"
            # 精度開關（2026-10-11：同 RVC，fp32 拉滿；XIAOYI_HALF=1 切回半精度。
            # 代價：idle VRAM +1~2GB、每句慢幾秒——已和老爸確認收下。）
            config.is_half = os.getenv("XIAOYI_HALF", "0") == "1"
            config.t2s_weights_path = os.path.join(GPT_SOVITS_DIR, "GPT_weights_v2", "xiaoyi_finetune-e4.ckpt")
            config.vits_weights_path = os.path.join(FINETUNE_DATA_DIR, "opt", "xiaoyi_finetune", "xiaoyi_sovits_inference.pth")
            config.cnhubert_base_path = "pretrained_models/chinese-hubert-base"
            config.bert_base_path = "pretrained_models/chinese-roberta-wwm-ext-large"
            
            _tts_pipeline = TTS(config)
            
            #  核心預熱與常駐快取：初始化時即完成參考音與文字 BERT 萃取，使後續所有合成省去 80% 時間！
            _REF_ZH = _tight_ref(REF_VOICE_ZH)
            _REF_JA = _tight_ref(REF_VOICE_JA)
            try:
                ref_audio = _REF_ZH
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
    同步推論函數，回傳音訊 bytes（lameenc 在就 MP3，否則 WAV——別信舊註解說的 WAV）。
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
            # 半形片假名（U+FF61–FF9F，YT 歌名常見）也算假名——之前漏掉會誤鎖 zh
            num_kana = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\uFF61-\uFF9F]', text))
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
                ref_audio = _REF_JA or REF_VOICE_JA
                ref_text = "お兄ちゃん、今日も一日頑張ろうね！大好きだよ！"
                ref_lang = "all_ja"
                text_lang = "ja" if num_hanzi == 0 else "auto"
                top_k = 15
                top_p = _TOP_P
                temp = 0.65
                speed = 1.0
            else:
                #  中文主體模式：
                # 採用中文參考音訊，若為純中文則鎖定 'zh' 避免被誤判為日文，若有日文夾雜則交由 'auto'
                ref_audio = _REF_ZH or REF_VOICE_ZH
                ref_text = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
                ref_lang = "all_zh"
                has_english = bool(re.search(r'[a-zA-Z]', text))
                text_lang = "zh" if (num_kana == 0 and not has_english) else "auto"
                top_k = 15
                top_p = _TOP_P
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
                "text_split_method": XIAOYI_SPLIT_METHOD,
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

            # 先整句合成（快、語氣自然）；不合格才把長句切段、每段自己檢查重抽（備援）。
            # top_p 改 1.0 後整句 0/120 失敗、平均 2.6 秒；分段版一樣 0 失敗但平均 3.0、最慢 11.8 秒（2026-10-25）
            plans = [[text]]
            if _SEGMENT_CHARS > 0 and len(text) > _SEGMENT_CHARS:
                plans.append(_split_for_tts(text))
            sr = None
            pieces = []
            _orig_max_sec = _tts_pipeline.configs.max_sec
            try:
                for plan_idx, segs in enumerate(plans):
                    tries = 1 if plan_idx < len(plans) - 1 else _SEGMENT_TRIES   # 還有備援就只試一次整句
                    sr, pieces, all_ok = _synth_segments(inputs, segs, tries)
                    if all_ok:
                        break
                    print(f"⚠️ [GPT-SoVITS] 合成不完整，{'改切段重來' if plan_idx < len(plans) - 1 else '重抽後仍不合格'}：{text[:20]}")
            finally:
                _tts_pipeline.configs.max_sec = _orig_max_sec
            if not pieces:
                try:
                    import services.web_dashboard as web_dash
                    web_dash.broadcast_event("tts_progress", {"active": False, "stage": "完成", "percent": 100})
                except Exception:
                    pass
                return b""
            if len(pieces) == 1:
                audio = pieces[0]
            else:
                pause = np.zeros(int(sr * 0.08), dtype=pieces[0].dtype)   # 段與段之間留一點換氣
                audio = np.concatenate([x for i, p in enumerate(pieces) for x in ((pause, p) if i else (p,))])
            
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
