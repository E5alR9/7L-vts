# -*- coding: utf-8 -*-
"""音訊分析小工具（2026-10-25 從主程式搬出來）：嘴型包絡、一次解碼拿時長＋包絡、回音比對。

extract_audio_mouth_envelope：pygame Sound → 每格（fps）0~1 的嘴巴開合，主程式說話和翻唱都用。
load_sound_with_envelope：同一個 Sound 拿時長＋包絡（不 decode 兩次），讀不了就用字數估時長。
normalize_text_for_echo／check_is_echo_by_waveform：判斷麥克風收到的是不是她自己或電腦的聲音。
"""
import re
import unicodedata

import pygame


def extract_audio_mouth_envelope(sound_obj, fps=25) -> list:
    """從 MP3/音訊波形中以 25fps (每 40ms) 精確提取口型開合振幅包絡 (0.0~1.0)，包含動態增益與噪聲門限"""
    try:
        import pygame.sndarray
        import numpy as np
        arr = pygame.sndarray.array(sound_obj)
        if arr.size == 0:
            return []
        if arr.ndim > 1:
            arr = np.mean(arr, axis=1)  # 雙聲道轉單聲道
        
        freq = pygame.mixer.get_init()[0] if pygame.mixer.get_init() else 44100
        frame_len = max(1, int(freq / fps))
        envelope = []
        for i in range(0, len(arr), frame_len):
            chunk = arr[i:i+frame_len].astype(np.float32)
            if len(chunk) > 0:
                rms = float(np.sqrt(np.mean(chunk**2)))
                envelope.append(rms)
        
        if not envelope:
            return []
            
        max_rms = max(envelope)
        if max_rms <= 10.0:
            return [0.0] * len(envelope)
            
        # 噪聲門限 (小於 10% 最大音量或絕對 RMS < 200 直接歸零閉嘴，確保子音、句逗、吸氣與微量伴奏殘留自然閉口)
        gate = max(200.0, max_rms * 0.10)
        target_span = max(1.0, max_rms * 0.65)
        
        norm_env = []
        for r in envelope:
            if r < gate:
                norm_env.append(0.0)
            else:
                val = min(1.0, (r - gate) / target_span)
                norm_env.append(round(val, 3))
        return norm_env
    except Exception:
        return []


def load_sound_with_envelope(part_file: str, text: str = ""):
    """播音單次解碼（2026-10-11）：同一個 Sound 物件同時拿時長＋口型包絡＋播音，
    不再 decode 兩次（舊碼 3767/3801 各 load 一次，磁碟＋解碼雙倍開銷）。
    回 (snd_obj_or_None, dur, env)。"""
    try:
        snd_obj = pygame.mixer.Sound(part_file)
        part_dur = snd_obj.get_length()
        part_env = extract_audio_mouth_envelope(snd_obj, fps=25)
        return snd_obj, part_dur, part_env
    except Exception:
        return None, max(0.5, len(text or "") * 0.22), []


def normalize_text_for_echo(t: str) -> str:
    if not t: return ""
    t_norm = unicodedata.normalize('NFKC', str(t))
    clean = re.sub(r'[^\w\u4e00-\u9fa5]', '', t_norm).strip().lower()
    clean = clean.replace("爸爸", "老爸").replace("阿爸", "老爸").replace("拔拔", "老爸").replace("老爹", "老爸")
    clean = clean.replace("妳", "你")
    return clean


def check_is_echo_by_waveform(mic_wav_bytes: bytes, sys_wav_bytes: bytes, threshold: float = 0.15) -> bool:
    """純本地數學波形對比 (Cross-Correlation)：
    直接比較麥克風與電腦系統音訊的原始 .wav，完美過濾喇叭回音，無需經過 STT，絕不產生幻覺。"""
    if not mic_wav_bytes or not sys_wav_bytes:
        return False
    try:
        import numpy as np
        import scipy.signal
        import wave
        import io
        
        with wave.open(io.BytesIO(mic_wav_bytes), 'rb') as wf:
            mic_pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)
        with wave.open(io.BytesIO(sys_wav_bytes), 'rb') as wf:
            sys_pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)
            
        if len(mic_pcm) < 4000 or len(sys_pcm) < 4000:
            return False
            
        # 取麥克風最後 2 秒 (約 32000 點) 與系統音訊最後 3 秒 (約 48000 點)
        mic_len = min(len(mic_pcm), 32000)
        sys_len = min(len(sys_pcm), 48000)
        mic_sig = mic_pcm[-mic_len:]
        sys_sig = sys_pcm[-sys_len:]
        
        # 改為「能量包絡線 (Energy Envelope) 對比」
        # 喇叭播放再由麥克風收音，會產生嚴重相位偏移(Phase Shift)與失真，直接對比原始波形會失敗
        # 透過每 10ms (160 samples) 取一次絕對值平均，抽取出音量起伏的特徵(包絡線)，完美抵抗相位偏移！
        window_size = 160
        mic_env = np.mean(np.abs(mic_sig)[:(len(mic_sig)//window_size)*window_size].reshape(-1, window_size), axis=1)
        sys_env = np.mean(np.abs(sys_sig)[:(len(sys_sig)//window_size)*window_size].reshape(-1, window_size), axis=1)
        
        # 去除直流分量 (Zero-mean) 以便計算 Pearson 相關係數
        mic_env -= np.mean(mic_env)
        sys_env -= np.mean(sys_env)
        
        mic_norm = np.linalg.norm(mic_env)
        sys_norm = np.linalg.norm(sys_env)
        if mic_norm < 1e-4 or sys_norm < 1e-4:
            return False
            
        mic_env /= mic_norm
        sys_env /= sys_norm
        
        # 互相關計算 (此時點數已降至原來的 1/160，計算極快)
        corr = scipy.signal.correlate(sys_env, mic_env, mode='valid')
        max_corr = np.max(corr)
        
        print(f"🔍 [AEC 除錯] 音量包絡線重合度 (Correlation): {max_corr:.3f} (門檻: {threshold})")
        return float(max_corr) > threshold
    except Exception as e:
        print(f"⚠️ [AEC 錯誤] {e}")
        return False
