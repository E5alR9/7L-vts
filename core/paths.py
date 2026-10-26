"""
🧭 統一路徑解析 (Path Resolution)

🎯 目的：
   原始套件把所有資產路徑寫死在 `C:\\Users\\qiwai`（原作者的電腦），
   在任何其他機器上都會找不到檔案。這裡統一成「環境變數優先、
   退回目前使用者家目錄」的解析，讓整包可以隨處搬移。

優先順序：
   1. 環境變數（可寫進 .env）
   2. 目前使用者家目錄下的預期位置

用法：
    from core.paths import GPT_SOVITS_DIR, REF_VOICE_ZH, DATA_DIR
"""

import os



def _resolve(env_name: str, *candidates: str) -> str:
    """
    環境變數 > 已存在的候選路徑 > 第一個候選
    """
    val = os.getenv(env_name)
    if val:
        return os.path.expandvars(os.path.expanduser(val))

    existing = [c for c in candidates if c and os.path.exists(c)]
    if existing:
        return existing[0]
    if candidates and candidates[0]:
        return candidates[0]
    return ""


HOME: str = os.path.expanduser("~")
ROOT_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄（主程式所在）
DATA_DIR: str = os.path.join(ROOT_DIR, "data")   # 執行時資料：記憶、觀眾檔、聲紋、音訊快取（以前六個模組各自算一次）

# GPT-SoVITS 主安裝目錄（沒裝就是不存在，TTS 路由器會自動降級）
GPT_SOVITS_DIR: str = _resolve(
    "GPT_SOVITS_DIR",
    os.path.join(HOME, "GPT-SoVITS"),              # 本機（都不存在時採用這個）
)

# 微調語料 / 訓練輸出
FINETUNE_DATA_DIR: str = _resolve(
    "FINETUNE_DATA_DIR",
    os.path.join(HOME, "finetune_data"),
)

# 聲線參考音檔（優先本機家目錄，原作者機器上的檔案存在時也相容）
REF_VOICE_ZH: str = _resolve("TTS_REF_ZH", os.path.join(HOME, "xiaoyi_girl_ref.wav"))
REF_VOICE_ZH_ALT: str = _resolve("TTS_REF_ZH_ALT", os.path.join(HOME, "xiaoyi_ref.wav"))
REF_VOICE_JA: str = _resolve("TTS_REF_JA", os.path.join(HOME, "xiaoyi_japanese_ref.wav"))


def ref_voices() -> list:
    """回傳實際存在的參考音檔清單（不存在的直接過濾，避免下游讀檔崩潰）"""
    return [p for p in (REF_VOICE_ZH, REF_VOICE_ZH_ALT, REF_VOICE_JA) if p and os.path.exists(p)]


def ffmpeg_exe() -> str:
    """ffmpeg 執行檔：環境變數 FFMPEG_EXE > PATH 上的 ffmpeg > C:\\ffmpeg\\bin > 裸 "ffmpeg"（以前五個模組各寫一份、順序還不一樣）。"""
    import shutil
    fixed = r"C:\ffmpeg\bin\ffmpeg.exe"
    return os.getenv("FFMPEG_EXE") or shutil.which("ffmpeg") or (fixed if os.path.exists(fixed) else "ffmpeg")
