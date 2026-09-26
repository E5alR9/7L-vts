# -*- coding: utf-8 -*-
"""
🎙️ 7L 專屬聲紋辨識與老爸身份驗證中樞 (Voiceprint Verifier)
- 採用 WeSpeaker ResNet34 中文聲紋神經網路 (25MB ONNX 輕量模型)
- 毫秒級聲紋特徵向量 (Speaker Embedding) 提取與餘弦相似度比對
- 建立老爸專屬聲紋特徵錨點 (Anchor Profile)，杜絕 7L 自身回音、電視背景音與旁人插話
- 支援 7x24 全雙工免關麥即時插話 (Barge-in) 判定
"""

import os
import io
import wave
import base64
import time
import urllib.request
from typing import Optional, Tuple, List, Union
import numpy as np

try:
    import sherpa_onnx
    HAS_SHERPA = True
except ImportError:
    HAS_SHERPA = False

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
MODEL_FILENAME = "wespeaker_zh_cnceleb_resnet34.onnx"
MODEL_PATH = os.path.join(MODEL_DIR, MODEL_FILENAME)
MODEL_DOWNLOAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_zh_cnceleb_resnet34.onnx"

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
VOICEPRINT_FILE = os.path.join(DATA_DIR, "dad_voiceprint.npy")
VOICEPRINT_7L_FILE = os.path.join(DATA_DIR, "7l_voiceprint.npy")


def safe_print(msg: str):
    """安全控制台輸出，防止 Windows CP950/GBK 終端機遇到 Emoji 拋出 UnicodeEncodeError"""
    try:
        print(msg)
    except Exception:
        try:
            clean = msg.encode("ascii", errors="replace").decode("ascii")
            print(clean)
        except Exception:
            pass


class VoiceprintVerifier:
    def __init__(
        self,
        model_path: str = MODEL_PATH,
        voiceprint_file: str = VOICEPRINT_FILE,
        voiceprint_7l_file: str = VOICEPRINT_7L_FILE,
        threshold: float = 0.65,
        threshold_7l: float = 0.58
    ):
        self.model_path = model_path
        self.voiceprint_file = voiceprint_file
        self.voiceprint_7l_file = voiceprint_7l_file
        env_th = os.getenv("DAD_VOICEPRINT_THRESHOLD")
        self.threshold = float(env_th) if env_th else threshold
        self.threshold_7l = threshold_7l
        self.extractor = None
        self.manager = None
        self.is_initialized = False
        self.anchor_embeddings: List[np.ndarray] = []
        self.anchor_7l_embeddings: List[np.ndarray] = []
        self._last_loaded_mtime = 0.0
        self._last_loaded_7l_mtime = 0.0
        
        self._init_engine()

    def _ensure_model_exists(self) -> bool:
        """確保 ONNX 模型存在，若無則自動下載"""
        if os.path.exists(self.model_path) and os.path.getsize(self.model_path) > 1000000:
            return True
        try:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            safe_print(f"📥 [聲紋引擎] 正在下載 WeSpeaker 中文聲紋模型至 {self.model_path}...")
            urllib.request.urlretrieve(MODEL_DOWNLOAD_URL, self.model_path)
            return os.path.exists(self.model_path)
        except Exception as e:
            safe_print(f"⚠️ [聲紋引擎] 下載聲紋模型失敗: {e}")
            return False

    def _init_engine(self):
        """初始化 sherpa-onnx 特徵提取器與比對管理器"""
        if not HAS_SHERPA:
            safe_print("⚠️ [聲紋引擎] 未安裝 sherpa-onnx，聲紋驗證將處於旁路模式。")
            return

        if not self._ensure_model_exists():
            safe_print("⚠️ [聲紋引擎] 找不到聲紋模型檔案，聲紋驗證將處於旁路模式。")
            return

        try:
            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=self.model_path,
                num_threads=2,
                debug=False,
                provider="cpu"
            )
            self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            self.manager = sherpa_onnx.SpeakerEmbeddingManager(self.extractor.dim)
            self.is_initialized = True
            
            # 載入或自動校準老爸聲紋
            self._load_or_auto_calibrate()
            # 載入或自動從本地 TTS 基準音檔提煉 7L 專屬聲紋（防自聲誤記與回音）
            self._load_or_auto_calibrate_7l()
        except Exception as e:
            safe_print(f"❌ [聲紋引擎] 初始化失敗: {e}")
            self.is_initialized = False

    def _extract_pcm_and_sr(self, audio_input: Union[str, bytes]) -> Tuple[Optional[np.ndarray], int]:
        """從檔案路徑、WAV 二進制或 Base64 字串解碼出單聲道 float32 PCM 與取樣率"""
        try:
            raw_bytes = None
            if isinstance(audio_input, str):
                if os.path.isfile(audio_input):
                    with open(audio_input, "rb") as f:
                        raw_bytes = f.read()
                else:
                    # 嘗試 base64 解碼
                    try:
                        raw_bytes = base64.b64decode(audio_input)
                    except Exception:
                        return None, 0
            elif isinstance(audio_input, (bytes, bytearray)):
                raw_bytes = bytes(audio_input)

            if not raw_bytes or len(raw_bytes) < 44:
                return None, 0

            with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
                sr = wf.getframerate()
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                n_frames = wf.getnframes()
                data = wf.readframes(n_frames)

            if sampwidth == 2:
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            elif sampwidth == 4:
                samples = np.frombuffer(data, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                samples = np.frombuffer(data, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0

            if n_channels > 1:
                # 轉單聲道
                samples = samples.reshape(-1, n_channels).mean(axis=1)

            return samples, sr
        except Exception:
            return None, 0

    def compute_embedding(self, audio_input: Union[str, bytes]) -> Optional[np.ndarray]:
        """計算單段音訊的 256 維聲紋特徵向量"""
        if not self.is_initialized or self.extractor is None:
            return None

        samples, sr = self._extract_pcm_and_sr(audio_input)
        if samples is None or len(samples) < sr * 0.3:  # 至少需 0.3 秒有效聲音
            return None

        # 🌟 先行重取樣至 16kHz：徹底消除 sherpa-onnx 底層 C++ 噴出 resampler 除錯日誌
        if sr != 16000 and len(samples) > 0:
            try:
                import scipy.signal
                num_target = int(len(samples) * 16000 / sr)
                samples = scipy.signal.resample(samples, num_target).astype(np.float32)
                sr = 16000
            except Exception:
                pass

        try:
            stream = self.extractor.create_stream()
            stream.accept_waveform(sample_rate=float(sr), waveform=samples)
            stream.input_finished()
            if self.extractor.is_ready(stream):
                emb = np.array(self.extractor.compute(stream), dtype=np.float32)
                # L2 正規化
                norm = np.linalg.norm(emb)
                if norm > 1e-6:
                    emb = emb / norm
                return emb
        except Exception:
            pass
        return None

    def _load_or_auto_calibrate(self):
        """若已有保存的聲紋檔則載入，否則自動從最近錄音中提取基準聲紋"""
        if os.path.exists(self.voiceprint_file):
            try:
                self._last_loaded_mtime = os.path.getmtime(self.voiceprint_file)
                embs = np.load(self.voiceprint_file)
                if embs.ndim == 1:
                    embs = [embs]
                self.anchor_embeddings = [np.array(e, dtype=np.float32) for e in embs]
                self._register_anchor_to_manager()
                safe_print(f"🔐 [聲紋鎖就緒] 已載入老爸聲紋基準檔 ({len(self.anchor_embeddings)} 筆特徵向量)！")
                return
            except Exception as e:
                safe_print(f"⚠️ [聲紋鎖] 載入老爸聲紋檔失敗: {e}，將自動重新校準。")

        # 自動從 data/recent_audio 校準
        recent_dir = os.path.join(DATA_DIR, "recent_audio")
        self.calibrate_from_directory(recent_dir)

    def reload_voiceprint(self):
        """重新載入最新保存的聲紋檔（熱更新）"""
        if os.path.exists(self.voiceprint_file):
            self._last_loaded_mtime = os.path.getmtime(self.voiceprint_file)
        if os.path.exists(self.voiceprint_7l_file):
            self._last_loaded_7l_mtime = os.path.getmtime(self.voiceprint_7l_file)
        self._load_or_auto_calibrate()
        self._load_or_auto_calibrate_7l()

    def _register_anchor_to_manager(self):
        """將老爸 anchor 註冊進 sherpa-onnx SpeakerEmbeddingManager"""
        if not self.manager or not self.anchor_embeddings:
            return
        try:
            if "dad" in self.manager:
                self.manager.remove("dad")
            # 支援傳入多筆特徵列表
            self.manager.add("dad", [e.tolist() for e in self.anchor_embeddings])
        except Exception as e:
            safe_print(f"⚠️ [聲紋鎖] 老爸特徵註冊至比對器異常: {e}")

    def _register_anchor_7l_to_manager(self):
        """將 7L 自聲 anchor 註冊進 sherpa-onnx SpeakerEmbeddingManager"""
        if not self.manager or not self.anchor_7l_embeddings:
            return
        try:
            if "7l" in self.manager:
                self.manager.remove("7l")
            self.manager.add("7l", [e.tolist() for e in self.anchor_7l_embeddings])
        except Exception as e:
            safe_print(f"⚠️ [聲紋鎖] 7L 自聲特徵註冊至比對器異常: {e}")

    def _load_or_auto_calibrate_7l(self):
        """載入 7L 自身聲紋特徵庫，若無則從本地 TTS 參考音檔與快取中自動提煉"""
        if os.path.exists(self.voiceprint_7l_file):
            try:
                self._last_loaded_7l_mtime = os.path.getmtime(self.voiceprint_7l_file)
                embs = np.load(self.voiceprint_7l_file)
                if embs.ndim == 1:
                    embs = [embs]
                self.anchor_7l_embeddings = [np.array(e, dtype=np.float32) for e in embs]
                self._register_anchor_7l_to_manager()
                safe_print(f"👧 [7L 聲紋就緒] 已載入 7L 自身聲紋基準檔 ({len(self.anchor_7l_embeddings)} 筆特徵向量)！")
                return
            except Exception as e:
                safe_print(f"⚠️ [聲紋鎖] 載入 7L 聲紋檔失敗: {e}，將自動重新校準。")

        # 自動從本地 TTS 參考音檔與音訊校準
        self.train_or_calibrate_7l_from_tts()

    def calibrate_from_directory(self, audio_dir: str, max_samples: int = 8) -> bool:
        """從指定目錄下挑選優質錄音建立基準聲紋"""
        if not os.path.exists(audio_dir):
            return False

        import glob
        wav_files = sorted(glob.glob(os.path.join(audio_dir, "mic_*.wav")), reverse=True)
        valid_embs = []

        safe_print("🔍 [聲紋校準] 正在掃描本機歷史錄音，建立老爸專屬聲紋特徵庫...")
        for wf in wav_files:
            # 篩選檔案大小適中 (200KB ~ 5MB，約 2~30 秒) 的有效發音檔
            size = os.path.getsize(wf)
            if 150000 <= size <= 6000000:
                emb = self.compute_embedding(wf)
                if emb is not None:
                    valid_embs.append(emb)
                    if len(valid_embs) >= max_samples:
                        break

        if valid_embs:
            self.anchor_embeddings = valid_embs
            os.makedirs(os.path.dirname(self.voiceprint_file), exist_ok=True)
            np.save(self.voiceprint_file, np.array(valid_embs))
            self._register_anchor_to_manager()
            safe_print(f"✅ [聲紋校準成功] 已成功提煉 {len(valid_embs)} 組老爸真實發音特徵，保存至 {self.voiceprint_file}！")
            return True
        else:
            safe_print("⚠️ [聲紋校準] 尚未找到足夠長度的清晰發音檔案，聲紋鎖將在收到首批語音時自動學習。")
            return False

    def verify_is_dad(
        self,
        audio_input: Union[str, bytes],
        threshold: Optional[float] = None
    ) -> Tuple[bool, float]:
        """
        驗證傳入之音訊是否為老爸本人說話
        
        Returns:
            Tuple[bool, float]: (是否為老爸, 相似度得分 0.0 ~ 1.0)
        """
        # 自動偵測聲紋特徵檔更新（免重啟即時熱重載）
        if os.path.exists(self.voiceprint_file):
            try:
                cur_m = os.path.getmtime(self.voiceprint_file)
                if cur_m > getattr(self, '_last_loaded_mtime', 0.0) + 0.1:
                    self._last_loaded_mtime = cur_m
                    self._load_or_auto_calibrate()
            except Exception:
                pass

        if not self.is_initialized or not self.anchor_embeddings:
            # 引擎未就緒或尚未有聲紋時，採取放行策略（相容模式）
            return True, 1.0

        th = threshold if threshold is not None else self.threshold
        emb = self.compute_embedding(audio_input)
        if emb is None:
            # 音訊過短或無有效人聲
            return False, 0.0

        try:
            scores = [float(np.dot(emb, anchor)) for anchor in self.anchor_embeddings]
            max_cosine = max(scores) if scores else 0.0
            if self.manager and "dad" in self.manager:
                manager_score = float(self.manager.score("dad", emb.tolist()))
                score = max(manager_score, max_cosine)
            else:
                score = max_cosine

            is_dad = (score >= th)
            return is_dad, score
        except Exception:
            return True, 1.0

    def add_verified_sample(self, audio_input: Union[str, bytes]):
        """若判定為極高信心度之老爸發音，動態融入特徵池提升長遠辨識率"""
        try:
            emb = self.compute_embedding(audio_input)
            if emb is not None:
                # 只有與現有特徵一致性高於 0.85 時才納入擴充，防止污染
                is_dad, score = self.verify_is_dad(audio_input, threshold=0.85)
                if is_dad and len(self.anchor_embeddings) < 20:
                    self.anchor_embeddings.append(emb)
                    np.save(self.voiceprint_file, np.array(self.anchor_embeddings))
                    self._register_anchor_to_manager()
        except Exception:
            pass

    def train_or_calibrate_7l_from_tts(
        self,
        ref_paths: Optional[List[str]] = None,
        max_samples: int = 15
    ) -> bool:
        """
        從本地 TTS 參考音檔與發音樣本中提取 7L 專屬聲紋特徵，建立 7L 自聲庫
        """
        valid_embs = []
        candidates = []

        if ref_paths:
            candidates.extend(ref_paths)

        # 預設本地標準 7L 參考音檔母帶
        default_refs = [
            r"C:\Users\qiwai\xiaoyi_girl_ref.wav",
            r"C:\Users\qiwai\xiaoyi_ref.wav",
            r"C:\Users\qiwai\xiaoyi_japanese_ref.wav"
        ]
        for dr in default_refs:
            if os.path.exists(dr) and dr not in candidates:
                candidates.append(dr)

        # 掃描專案中可能存在的 7L TTS 輸出音檔
        search_dirs = [
            os.path.join(DATA_DIR, "tts_cache"),
            os.path.join(DATA_DIR, "recent_audio"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"),
            r"C:\Users\qiwai\GPT-SoVITS\output"
        ]
        import glob
        for s_dir in search_dirs:
            if os.path.exists(s_dir):
                for wf in glob.glob(os.path.join(s_dir, "*.wav")):
                    if "xiaoyi" in os.path.basename(wf).lower() or "7l" in os.path.basename(wf).lower():
                        if wf not in candidates:
                            candidates.append(wf)

        safe_print(f"🔍 [7L 聲紋校準] 正在掃描 {len(candidates)} 個候選音檔，提煉 7L 專屬發音特徵庫...")
        for wf in candidates:
            if not os.path.exists(wf):
                continue
            size = os.path.getsize(wf)
            if size < 10000:
                continue
            emb = self.compute_embedding(wf)
            if emb is not None:
                valid_embs.append(emb)
                if len(valid_embs) >= max_samples:
                    break

        if valid_embs:
            self.anchor_7l_embeddings = valid_embs
            os.makedirs(os.path.dirname(self.voiceprint_7l_file), exist_ok=True)
            np.save(self.voiceprint_7l_file, np.array(valid_embs))
            self._register_anchor_7l_to_manager()
            safe_print(f"✅ [7L 聲紋校準成功] 已成功提煉 {len(valid_embs)} 組 7L 本地真實發音特徵，保存至 {self.voiceprint_7l_file}！")
            return True
        else:
            safe_print("⚠️ [7L 聲紋校準] 尚未找到足夠的 7L 語音音檔，將於獲得樣本時再行提煉。")
            return False

    def verify_is_7l(
        self,
        audio_input: Union[str, bytes],
        threshold: Optional[float] = None
    ) -> Tuple[bool, float]:
        """
        驗證傳入之音訊是否為 7L 自己的聲音（外放回音/自言自語/唱歌殘響）
        
        Returns:
            Tuple[bool, float]: (是否為 7L, 相似度得分 0.0 ~ 1.0)
        """
        # 自動偵測 7L 聲紋特徵檔更新（免重啟即時熱重載）
        if os.path.exists(self.voiceprint_7l_file):
            try:
                cur_m = os.path.getmtime(self.voiceprint_7l_file)
                if cur_m > getattr(self, '_last_loaded_7l_mtime', 0.0) + 0.1:
                    self._last_loaded_7l_mtime = cur_m
                    self._load_or_auto_calibrate_7l()
            except Exception:
                pass

        if not self.is_initialized or not self.anchor_7l_embeddings:
            return False, 0.0

        th = threshold if threshold is not None else self.threshold_7l
        emb = self.compute_embedding(audio_input)
        if emb is None:
            return False, 0.0

        try:
            scores = [float(np.dot(emb, anchor)) for anchor in self.anchor_7l_embeddings]
            max_cosine = max(scores) if scores else 0.0
            if self.manager and "7l" in self.manager:
                manager_score = float(self.manager.score("7l", emb.tolist()))
                score = max(manager_score, max_cosine)
            else:
                score = max_cosine

            is_7l = (score >= th)
            return is_7l, score
        except Exception:
            return False, 0.0


# 全域單例
voiceprint_verifier = VoiceprintVerifier()
