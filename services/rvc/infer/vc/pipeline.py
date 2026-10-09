import os
import traceback
import logging

logger = logging.getLogger(__name__)

from time import time as ttime

import faiss
import librosa
import numpy as np

import torch
import torch.nn.functional as F
from scipy import signal

from infer.hubert import extract_hubert_features
try:
    from tools.cuda_graph import cuda_graph_enabled, run_cuda_graph
except Exception:
    try:
        from services.rvc.tools.cuda_graph import cuda_graph_enabled, run_cuda_graph
    except Exception:
        def run_cuda_graph(model, name, func, *args):
            return func(*args)
        def cuda_graph_enabled(*args, **kwargs):
            return False

bh, ah = signal.butter(N=5, Wn=48, btype="high", fs=16000)


def change_rms(data1, sr1, data2, sr2, rate):  # 1是输入音频，2是输出音频,rate是2的占比
    # print(data1.max(),data2.max())
    rms1 = librosa.feature.rms(
        y=data1, frame_length=sr1 // 2 * 2, hop_length=sr1 // 2
    )  # 每半秒一个点
    rms2 = librosa.feature.rms(y=data2, frame_length=sr2 // 2 * 2, hop_length=sr2 // 2)
    rms1 = torch.from_numpy(rms1)
    rms1 = F.interpolate(
        rms1.unsqueeze(0), size=data2.shape[0], mode="linear"
    ).squeeze()
    rms2 = torch.from_numpy(rms2)
    rms2 = F.interpolate(
        rms2.unsqueeze(0), size=data2.shape[0], mode="linear"
    ).squeeze()
    rms2 = torch.max(rms2, torch.zeros_like(rms2) + 1e-6)
    data2 *= (
        torch.pow(rms1, torch.tensor(1 - rate))
        * torch.pow(rms2, torch.tensor(rate - 1))
    ).numpy()
    return data2


class Pipeline(object):
    def __init__(self, tgt_sr, config):
        self.x_pad, self.x_query, self.x_center, self.x_max, self.is_half = (
            config.x_pad,
            config.x_query,
            config.x_center,
            config.x_max,
            config.is_half,
        )
        self.sr = 16000  # hubert输入采样率
        self.window = 160  # 每帧点数
        self.t_pad = self.sr * self.x_pad  # 每条前后pad时间
        self.t_pad_tgt = tgt_sr * self.x_pad
        self.t_pad2 = self.t_pad * 2
        self.t_query = self.sr * self.x_query  # 查询切点前后查询时间
        self.t_center = self.sr * self.x_center  # 查询切点位置
        self.t_max = self.sr * self.x_max  # 免查询时长阈值
        self.device = config.device

    def get_f0(
        self,
        x,
        p_len,
        f0_up_key,
        f0_method,
    ):
        if f0_method not in ("rmvpe", "fcpe"):
            raise ValueError(f"Unsupported F0 method: {f0_method}")
        time_step = self.window / self.sr * 1000
        f0_min = 50
        f0_max = 1100
        f0_mel_min = 1127 * np.log(1 + f0_min / 700)
        f0_mel_max = 1127 * np.log(1 + f0_max / 700)
        if f0_method == "rmvpe":
            if not hasattr(self, "model_rmvpe"):
                from infer.rmvpe import RMVPE

                logger.info(
                    "Loading rmvpe model,%s" % "%s/rmvpe.pt" % os.environ["rmvpe_root"]
                )
                self.model_rmvpe = RMVPE(
                    "%s/rmvpe.pt" % os.environ["rmvpe_root"],
                    is_half=self.is_half,
                    device=self.device,
                )
            f0 = self.model_rmvpe.infer_from_audio(x, thred=0.03)

            if "privateuseone" in str(self.device):  # clean ortruntime memory
                del self.model_rmvpe.model
                del self.model_rmvpe
                logger.info("Cleaning ortruntime memory")
        elif f0_method == "fcpe":
            if not hasattr(self, "model_fcpe"):
                from infer.fcpe import FCPEInfer

                logger.info("Loading fcpe model")
                self.model_fcpe = FCPEInfer(self.device)
            f0 = self.model_fcpe.infer(
                torch.from_numpy(x).unsqueeze(0).float(),
                sr=self.sr,
                decoder_mode="local_argmax",
                threshold=0.006,
            ).squeeze().detach().cpu().numpy()

        try:
            uv = f0 == 0
            f0[uv] = np.interp(np.where(uv)[0], np.where(~uv)[0], f0[~uv])
        except Exception:
            traceback.print_exc()

        # 🎙️ 智慧音高與整首統一音域判決
        is_auto = False
        key_offset = 0.0
        if isinstance(f0_up_key, str) and "auto" in f0_up_key.lower():
            is_auto = True
            clean_k = f0_up_key.lower().replace("auto", "").strip()
            if clean_k:
                try:
                    key_offset = float(clean_k)
                except Exception:
                    pass
        elif f0_up_key is None:
            is_auto = True

        if is_auto:
            key_shifts = self.compute_adaptive_phrase_keys(f0, uv, base_offset=key_offset)
            f0 *= np.power(2.0, key_shifts / 12.0)
        elif isinstance(f0_up_key, np.ndarray):
            f0 *= np.power(2.0, f0_up_key / 12.0)
        else:
            f0 *= pow(2, float(f0_up_key) / 12.0)

        f0bak = f0.copy()
        f0_mel = 1127 * np.log(1 + f0 / 700)
        f0_mel[f0_mel > 0] = (f0_mel[f0_mel > 0] - f0_mel_min) * 254 / (
            f0_mel_max - f0_mel_min
        ) + 1
        f0_mel[f0_mel <= 1] = 1
        f0_mel[f0_mel > 255] = 255
        f0_coarse = np.rint(f0_mel).astype(np.int32)
        return f0_coarse, f0bak  # 1-0

    def compute_adaptive_phrase_keys(self, f0_interp, uv_mask, base_offset=0.0):
        """
        整首統一音域判決＋升八度（2026-10-09 修正直播事故）：
        - uv_mask: True 代表無聲/未發聲幀
        - 依據發聲連通區與短停頓切分演唱樂句 (Phrases)，先掃完全部樂句，
          以「發聲時長加權的低音占比」做整首統一判決（見 services/rvc_pitch.py）：
          * 整體偏低（低音時長占比 >= 50%）-> 全曲統一 +12 半音（進入 7L 甜美音域）
          * 整體偏高 -> 全曲維持原調 0 半音（連偏低的樂句也不動，絕不跳變）
        - 舊邏輯是逐句各自判決，混合音域的歌會在樂句邊界忽高忽低，已廢除。
        - 句間無聲空隙進行平滑過渡，保證單次神經網絡合成零縫隙雜音
        """
        try:
            from services.rvc_pitch import decide_song_key_shift
        except Exception:
            from rvc_pitch import decide_song_key_shift
        n_frames = len(f0_interp)
        key_shifts = np.zeros(n_frames, dtype=np.float32)

        is_voiced = ~uv_mask & (f0_interp > 50)
        if not np.any(is_voiced):
            return key_shifts + base_offset

        # 橋接短暫停頓 (< 0.25 秒 = 25 幀，每幀 10ms)
        kernel_size = 25
        padded = np.pad(is_voiced.astype(int), kernel_size // 2, mode="edge")
        dilated = np.convolve(padded, np.ones(kernel_size), mode="valid") > 0

        diff = np.diff(np.pad(dilated.astype(int), 1))
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0]

        male_phrases = 0
        female_phrases = 0

        # 第一段：只統計、不下判決（短於 5 幀的碎句不參與投票）
        phrase_stats = []
        for s, e in zip(starts, ends):
            phrase_voiced = is_voiced[s:e]
            if not np.any(phrase_voiced):
                continue
            phrase_f0 = f0_interp[s:e][phrase_voiced]
            if len(phrase_f0) < 5:
                continue
            med_f0 = float(np.median(phrase_f0))
            dur_sec = float(np.count_nonzero(phrase_voiced)) * 0.01
            phrase_stats.append((med_f0, dur_sec))
            if med_f0 < 195.0:
                male_phrases += 1
            else:
                female_phrases += 1

        # 第二段：整首統一判決，全曲同一個偏移
        song_shift, low_ratio = decide_song_key_shift(phrase_stats)
        for s, e in zip(starts, ends):
            key_shifts[s:e] = song_shift

        # 句間無聲間隔平滑銜接
        if starts.size > 0:
            key_shifts[:starts[0]] = key_shifts[starts[0]]
            key_shifts[ends[-1]:] = key_shifts[ends[-1] - 1]
            for i in range(len(ends) - 1):
                gap_s = ends[i]
                gap_e = starts[i + 1]
                if gap_s < gap_e:
                    mid = (gap_s + gap_e) // 2
                    key_shifts[gap_s:mid] = key_shifts[gap_s - 1]
                    key_shifts[mid:gap_e] = key_shifts[gap_e]

        print(
            f"🎵 [RVC 音高智能調度] 整體低音時長占比 {low_ratio:.0%} "
            f"({len(phrase_stats)}樂句：偏低{male_phrases}/偏高{female_phrases}) → "
            f"{'全曲統一+12半音升八度' if song_shift else '全曲維持原調'}"
            + (f" | 偏移: {base_offset:+0.1f}" if base_offset != 0 else "")
        )
        return key_shifts + base_offset

    def vc(
        self,
        model,
        net_g,
        sid,
        audio0,
        pitch,
        pitchf,
        times,
        index,
        index_vectors,
        index_rate,
        version,
        protect,
    ):
        feats = torch.from_numpy(audio0)
        if self.is_half:
            feats = feats.half()
        else:
            feats = feats.float()
        if feats.dim() == 2:  # double channels
            feats = feats.mean(-1)
        assert feats.dim() == 1, feats.dim()
        feats = feats.view(1, -1)
        padding_mask = torch.BoolTensor(feats.shape).to(self.device).fill_(False)

        t0 = ttime()
        with torch.no_grad():
            feats = extract_hubert_features(
                model,
                feats.to(self.device),
                version,
                padding_mask=padding_mask,
            )
        if protect < 0.5 and pitch is not None and pitchf is not None:
            feats0 = feats.clone()
        if (
            not isinstance(index, type(None))
            and not isinstance(index_vectors, type(None))
            and index_rate != 0
        ):
            npy = feats[0].cpu().numpy()
            if self.is_half:
                npy = npy.astype("float32")

            score, ix = index.search(npy, k=8)
            weight = np.square(1 / score)
            weight /= weight.sum(axis=1, keepdims=True)
            npy = np.sum(index_vectors[ix] * np.expand_dims(weight, axis=2), axis=1)

            if self.is_half:
                npy = npy.astype("float16")
            feats = (
                torch.from_numpy(npy).unsqueeze(0).to(self.device) * index_rate
                + (1 - index_rate) * feats
            )

        feats = F.interpolate(feats.permute(0, 2, 1), scale_factor=2).permute(0, 2, 1)
        if protect < 0.5 and pitch is not None and pitchf is not None:
            feats0 = F.interpolate(feats0.permute(0, 2, 1), scale_factor=2).permute(
                0, 2, 1
            )
        t1 = ttime()
        p_len = audio0.shape[0] // self.window
        if feats.shape[1] < p_len:
            p_len = feats.shape[1]
            if pitch is not None and pitchf is not None:
                pitch = pitch[:, :p_len]
                pitchf = pitchf[:, :p_len]

        if protect < 0.5 and pitch is not None and pitchf is not None:
            pitchff = pitchf.clone()
            pitchff[pitchf > 0] = 1
            pitchff[pitchf < 1] = protect
            pitchff = pitchff.unsqueeze(-1)
            feats = feats * pitchff + feats0 * (1 - pitchff)
            feats = feats.to(feats0.dtype)
        p_len = torch.tensor([p_len], device=self.device).long()
        with torch.no_grad():
            hasp = pitch is not None and pitchf is not None
            if hasp:
                synthesized = run_cuda_graph(
                    net_g,
                    "rvc-synth-f0",
                    lambda phone, lengths, coarse, continuous, speaker: net_g.infer(
                        phone, lengths, coarse, continuous, speaker
                    )[0],
                    feats,
                    p_len,
                    pitch,
                    pitchf,
                    sid,
                )
            else:
                synthesized = run_cuda_graph(
                    net_g,
                    "rvc-synth-no-f0",
                    lambda phone, lengths, speaker: net_g.infer(
                        phone, lengths, speaker
                    )[0],
                    feats,
                    p_len,
                    sid,
                )
            audio1 = synthesized[0, 0].data.cpu().float().numpy()
            del hasp, synthesized
        del feats, p_len, padding_mask
        if torch.cuda.is_available() and not cuda_graph_enabled(self.device):
            torch.cuda.empty_cache()
        t2 = ttime()
        times[0] += t1 - t0
        times[2] += t2 - t1
        return audio1

    def pipeline(
        self,
        model,
        net_g,
        sid,
        audio,
        times,
        f0_up_key,
        f0_method,
        file_index,
        index_rate,
        if_f0,
        tgt_sr,
        resample_sr,
        rms_mix_rate,
        version,
        protect,
    ):
        if (
            file_index != ""
            and os.path.exists(file_index)
            and index_rate != 0
        ):
            try:
                index = faiss.read_index(file_index)
                index_vectors = index.reconstruct_n(0, index.ntotal)
            except:
                traceback.print_exc()
                index = index_vectors = None
        else:
            index = index_vectors = None
        audio = signal.filtfilt(bh, ah, audio)
        audio_pad = np.pad(audio, (self.window // 2, self.window // 2), mode="reflect")
        opt_ts = []
        if audio_pad.shape[0] > self.t_max:
            audio_sum = np.zeros_like(audio)
            for i in range(self.window):
                audio_sum += np.abs(audio_pad[i : i - self.window])
            for t in range(self.t_center, audio.shape[0], self.t_center):
                opt_ts.append(
                    t
                    - self.t_query
                    + np.where(
                        audio_sum[t - self.t_query : t + self.t_query]
                        == audio_sum[t - self.t_query : t + self.t_query].min()
                    )[0][0]
                )
        s = 0
        audio_opt = []
        t = None
        t1 = ttime()
        audio_pad = np.pad(audio, (self.t_pad, self.t_pad), mode="reflect")
        p_len = audio_pad.shape[0] // self.window
        sid = torch.tensor(sid, device=self.device).unsqueeze(0).long()
        pitch, pitchf = None, None
        if if_f0 == 1:
            pitch, pitchf = self.get_f0(
                audio_pad,
                p_len,
                f0_up_key,
                f0_method,
            )
            pitch = pitch[:p_len]
            pitchf = pitchf[:p_len]
            pitchf = pitchf.astype(np.float32)
            pitch = torch.tensor(pitch, device=self.device).unsqueeze(0).long()
            pitchf = torch.tensor(pitchf, device=self.device).unsqueeze(0).float()
        t2 = ttime()
        times[1] += t2 - t1
        for t in opt_ts:
            t = t // self.window * self.window
            if if_f0 == 1:
                audio_opt.append(
                    self.vc(
                        model,
                        net_g,
                        sid,
                        audio_pad[s : t + self.t_pad2 + self.window],
                        pitch[:, s // self.window : (t + self.t_pad2) // self.window],
                        pitchf[:, s // self.window : (t + self.t_pad2) // self.window],
                        times,
                        index,
                        index_vectors,
                        index_rate,
                        version,
                        protect,
                    )[self.t_pad_tgt : -self.t_pad_tgt]
                )
            else:
                audio_opt.append(
                    self.vc(
                        model,
                        net_g,
                        sid,
                        audio_pad[s : t + self.t_pad2 + self.window],
                        None,
                        None,
                        times,
                        index,
                        index_vectors,
                        index_rate,
                        version,
                        protect,
                    )[self.t_pad_tgt : -self.t_pad_tgt]
                )
            s = t
        if if_f0 == 1:
            audio_opt.append(
                self.vc(
                    model,
                    net_g,
                    sid,
                    audio_pad[t:],
                    pitch[:, t // self.window :] if t is not None else pitch,
                    pitchf[:, t // self.window :] if t is not None else pitchf,
                    times,
                    index,
                    index_vectors,
                    index_rate,
                    version,
                    protect,
                )[self.t_pad_tgt : -self.t_pad_tgt]
            )
        else:
            audio_opt.append(
                self.vc(
                    model,
                    net_g,
                    sid,
                    audio_pad[t:],
                    None,
                    None,
                    times,
                    index,
                    index_vectors,
                    index_rate,
                    version,
                    protect,
                )[self.t_pad_tgt : -self.t_pad_tgt]
            )
        audio_opt = np.concatenate(audio_opt)
        if rms_mix_rate != 1:
            audio_opt = change_rms(audio, 16000, audio_opt, tgt_sr, rms_mix_rate)
        if tgt_sr != resample_sr >= 16000:
            audio_opt = librosa.resample(
                audio_opt, orig_sr=tgt_sr, target_sr=resample_sr
            )
        audio_max = np.abs(audio_opt).max() / 0.99
        max_int16 = 32768
        if audio_max > 1:
            max_int16 /= audio_max
        audio_opt = (audio_opt * max_int16).astype(np.int16)
        del pitch, pitchf, sid
        if torch.cuda.is_available() and not cuda_graph_enabled(self.device):
            torch.cuda.empty_cache()
        return audio_opt
