import os
import sys
import subprocess
import shutil

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
CACHE_DIR = "songs_library/cover_cache"
SONGS_DIR = "songs_library"

def produce_god_tier_cover(video_id: str, song_label: str):
    print(f"🚀 [神級音軌下載] 下載 {song_label} (ID: {video_id})...")
    raw_wav = os.path.join(CACHE_DIR, f"{song_label}_raw.wav")
    
    cmd_dl = [
        "yt-dlp", f"https://www.youtube.com/watch?v={video_id}",
        "-x", "--audio-format", "wav",
        "--audio-quality", "0",
        "--postprocessor-args", "ffmpeg:-ar 44100 -ac 2",
        "-o", raw_wav,
        "--no-playlist"
    ]
    subprocess.run(cmd_dl, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"✅ 下載完成: {raw_wav} (大小: {os.path.getsize(raw_wav)} bytes)")
    
    print(f"⚡ [GPU 分離] 啟用 Demucs 分離伴奏與神級歌聲...")
    cmd_demucs = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", "htdemucs",
        "-d", "cuda",
        "-o", CACHE_DIR,
        raw_wav
    ]
    subprocess.run(cmd_demucs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    demucs_dir = os.path.join(CACHE_DIR, "htdemucs", f"{song_label}_raw")
    voc = os.path.join(demucs_dir, "vocals.wav")
    inst = os.path.join(demucs_dir, "no_vocals.wav")
    
    out_mp3 = os.path.join(SONGS_DIR, f"7L_cover_{song_label}.mp3")
    out_chorus = os.path.join(SONGS_DIR, f"7L_cover_{song_label}_Chorus.mp3")
    
    print(f"🎛️ [母帶混音] 進行立體聲動態母帶平衡混音 (無失真原聲輸出)...")
    filter_mix = (
        "[0:a]volume=1.22,equalizer=f=3000:t=q:w=1.2:g=1.8,equalizer=f=8000:t=q:w=1.0:g=1.2[voc];"
        "[1:a]volume=0.95[inst];"
        "[voc][inst]amix=inputs=2:duration=first:dropout_transition=2[out]"
    )
    cmd_mix = [
        FFMPEG, "-y",
        "-i", voc,
        "-i", inst,
        "-filter_complex", filter_mix,
        "-map", "[out]",
        "-b:a", "320k",
        "-ar", "44100",
        out_mp3
    ]
    subprocess.run(cmd_mix, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 剪輯 30 秒高潮副歌
    cmd_clip = [
        FFMPEG, "-y",
        "-ss", "50", "-t", "30",
        "-i", out_mp3,
        "-b:a", "320k",
        out_chorus
    ]
    subprocess.run(cmd_clip, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"🎉 生成完畢: {out_mp3} 與副歌 {out_chorus} (大小: {os.path.getsize(out_mp3)} bytes)")

if __name__ == "__main__":
    # 1. Ado 神級唱功版千本櫻
    produce_god_tier_cover("3tPBEjxqEc4", "千本櫻_Ado神級唱腔版")
    
    # 2. 和樂器樂團 (鈴華優子) 經典百萬版千本櫻
    produce_god_tier_cover("K_xTet06SUo", "千本櫻_和樂器樂團神級版")
