"""
🧭 統一路徑解析 (Path Resolution)

🎯 目的：
   原始套件把所有資產路徑寫死在 `C:\\Users\\qiwai`（原作者的電腦），
   在任何其他機器上都會找不到檔案。這裡統一成「環境變數優先、
   退回目前使用者家目錄」的解析，讓整包可以隨處搬移。

優先順序：
   1. 環境變數（可寫進 .env）
   2. 目前使用者家目錄下的預期位置
   3. 舊的 qiwai 路徑（維持原作者機器相容）

用法：
    from core.paths import GPT_SOVITS_DIR, REF_VOICE_ZH
"""

import os
from typing import Optional

# 原作者家目錄（僅作為最後 fallback，讓原機器行為不變）
_LEGACY_USER = r"C:\Users\qiwai"


def _resolve(env_name: str, *candidates: str) -> str:
    """
    環境變數 > 已存在的候選路徑 > 第一個候選（慣例：候選順序「本機優先、舊機器墊底」）
    """
    val = os.getenv(env_name)
    if val:
        return os.path.expandvars(os.path.expanduser(val))

    home = os.path.expanduser("~")
    existing = [c for c in candidates if c and os.path.exists(c)]
    if existing:
        return existing[0]
    if candidates and candidates[0]:
        return candidates[0]
    return _LEGACY_USER


HOME: str = os.path.expanduser("~")

# GPT-SoVITS 主安裝目錄（沒裝就是不存在，TTS 路由器會自動降級）
GPT_SOVITS_DIR: str = _resolve(
    "GPT_SOVITS_DIR",
    os.path.join(HOME, "GPT-SoVITS"),              # 本機（都不存在時採用這個）
    os.path.join(_LEGACY_USER, "GPT-SoVITS"),      # 原作者機器（存在時採用）
)

# 微調語料 / 訓練輸出
FINETUNE_DATA_DIR: str = _resolve(
    "FINETUNE_DATA_DIR",
    os.path.join(HOME, "finetune_data"),
    os.path.join(_LEGACY_USER, "finetune_data"),
)

# 聲線參考音檔（優先本機家目錄，原作者機器上的檔案存在時也相容）
REF_VOICE_ZH: str = _resolve("TTS_REF_ZH", os.path.join(HOME, "xiaoyi_girl_ref.wav"), os.path.join(_LEGACY_USER, "xiaoyi_girl_ref.wav"))
REF_VOICE_ZH_ALT: str = _resolve("TTS_REF_ZH_ALT", os.path.join(HOME, "xiaoyi_ref.wav"), os.path.join(_LEGACY_USER, "xiaoyi_ref.wav"))
REF_VOICE_JA: str = _resolve("TTS_REF_JA", os.path.join(HOME, "xiaoyi_japanese_ref.wav"), os.path.join(_LEGACY_USER, "xiaoyi_japanese_ref.wav"))


def ref_voices() -> list:
    """回傳實際存在的參考音檔清單（不存在的直接過濾，避免下游讀檔崩潰）"""
    return [p for p in (REF_VOICE_ZH, REF_VOICE_ZH_ALT, REF_VOICE_JA) if p and os.path.exists(p)]


def legacy_or_home(*rel_parts: str) -> str:
    """回報「舊路徑或本機家目錄路徑」中存在者；都不存在時回傳本機家目錄版本"""
    legacy = os.path.join(_LEGACY_USER, *rel_parts)
    if os.path.exists(legacy):
        return legacy
    return os.path.join(HOME, *rel_parts)


def report() -> dict:
    """供啟動時輸出路徑狀態（不含隱私）"""
    return {
        "HOME": HOME,
        "GPT_SOVITS_DIR": GPT_SOVITS_DIR,
        "GPT_SOVITS_exists": os.path.isdir(GPT_SOVITS_DIR),
        "FINETUNE_DATA_DIR": FINETUNE_DATA_DIR,
        "ref_voices_found": len(ref_voices()),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(report(), ensure_ascii=False, indent=2))
