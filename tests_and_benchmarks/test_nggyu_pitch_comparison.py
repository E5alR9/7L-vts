import os
import subprocess

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
vocal_in = "songs_library/cover_cache/htdemucs/Never_Gonna_Give_You_Up_raw/vocals.wav"
inst_in = "songs_library/cover_cache/htdemucs/Never_Gonna_Give_You_Up_raw/no_vocals.wav"

clip_start = "42"
clip_dur = "25"

test_cases = [
    ("Key0", 0.0, "equalizer=f=3200:t=q:w=1.2:g=1.8,equalizer=f=8000:t=q:w=1.0:g=1.2", "原調 0 半音 (完全不調高，100% 自然舒服不怪)"),
    ("Key1.5_ParamA", 1.5, "equalizer=f=3200:t=q:w=1.2:g=2.2,equalizer=f=400:t=q:w=1.0:g=-1.5,equalizer=f=8000:t=q:w=1.0:g=1.5", "微調 +1.5 半音 (老爸之前認證「A 聽起來正常」之黃金參數)"),
    ("Key2.5_ParamB", 2.5, "equalizer=f=3400:t=q:w=1.2:g=3.0,equalizer=f=380:t=q:w=1.0:g=-2.0,equalizer=f=8500:t=q:w=1.0:g=2.5", "微調 +2.5 半音 (稍微清脆)"),
    ("Key4.0", 4.0, "equalizer=f=3500:t=q:w=1.2:g=3.0,equalizer=f=350:t=q:w=1.0:g=-2.5,equalizer=f=8500:t=q:w=1.0:g=2.0", "微調 +4.0 半音 (微高音)")
]

temp_inst = "songs_library/test_ai_cover/temp_inst_clip.wav"
subprocess.run([
    FFMPEG, "-y",
    "-ss", clip_start, "-t", clip_dur,
    "-i", inst_in,
    "-ar", "44100", temp_inst
], capture_output=True)

for label, semitones, eq_filter, desc in test_cases:
    out_mp3 = f"songs_library/7L_NGGYU_{label}.mp3"
    temp_voc = f"songs_library/test_ai_cover/temp_voc_{label}.wav"
    
    if semitones == 0:
        filter_str = f"{eq_filter},aresample=44100"
    else:
        freq_factor = 2.0 ** (semitones / 12.0)
        new_rate = int(44100 * freq_factor)
        tempo_factor = 1.0 / freq_factor
        filter_str = f"asetrate={new_rate},atempo={tempo_factor:.4f},{eq_filter},aresample=44100"
        
    cmd_v = [
        FFMPEG, "-y",
        "-ss", clip_start, "-t", clip_dur,
        "-i", vocal_in,
        "-af", filter_str,
        "-ar", "44100", temp_voc
    ]
    subprocess.run(cmd_v, capture_output=True)
    
    cmd_m = [
        FFMPEG, "-y",
        "-i", temp_voc,
        "-i", temp_inst,
        "-filter_complex", "[0:a]volume=1.25[v];[1:a]volume=0.92[i];[v][i]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-b:a", "320k",
        out_mp3
    ]
    subprocess.run(cmd_m, capture_output=True)
    print(f"✅ 生成 {label}: {out_mp3} ({desc}) 大小: {os.path.getsize(out_mp3)} bytes")
