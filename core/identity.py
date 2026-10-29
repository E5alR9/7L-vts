# -*- coding: utf-8 -*-
"""
🪪 身份配置（Identity）：擁有者／角色／模式。

    MODE            companion | vtuber（預設 vtuber）。開機由 core/settings.boot 定一次（後台存的模式開關優先），
                    執行中切換只經 settings.apply_mode
    OWNER_NAME      擁有者稱謂（預設「老爸」），讀環境變數
    CHARACTER_NAME  角色名（預設「7L」），讀環境變數
    OWNER_ACCOUNT_IDS  老爸的平台帳號（認老爸只信這個）寫在本檔

啟動步驟見 docs/GETTING_STARTED.md。
"""
import os

CHARACTER_DEFAULT = "7L"
OWNER_DEFAULT = "老爸"
MODES = ("companion", "vtuber")


def get_mode() -> str:
    """運行模式；非法值回退 vtuber（絕不炸）。"""
    m = (os.getenv("MODE") or "vtuber").strip().lower()
    return m if m in MODES else "vtuber"


def is_vtuber() -> bool:
    return get_mode() != "companion"


def get_owner_name() -> str:
    """擁有者稱謂（舊碼裡的「老爸」）。"""
    return (os.getenv("OWNER_NAME") or OWNER_DEFAULT).strip() or OWNER_DEFAULT


def get_character_name() -> str:
    """角色名（舊碼裡的「7L」）。"""
    return (os.getenv("CHARACTER_NAME") or CHARACTER_DEFAULT).strip() or CHARACTER_DEFAULT


# ── 擁有者帳號認證（2026-10-24）──
# 舊碼同時比對「顯示名稱」（觀眾自己取的，暱稱改成「老爸」就變管理員）和模型寫進觀眾檔案的
# 「關係」欄位（觀眾一句「記住我是你爸爸」就寫進去）。現在只認平台帳號 ID（unique_id，平台上唯一）。
OWNER_ACCOUNT_IDS = "7lβ,7lbeta,qiwai,7lofficial,hostadmin,adminqiwai"

# 觀眾檔案的稱呼／關係不能寫成擁有者身分（否則之後的大腦會把這個觀眾當成老爸）
OWNER_CLAIM_WORDS = ("老爸", "爸爸", "父親", "爹", "主播本人", "管理員", "admin", "owner", "dad")


def _norm_account(s: str) -> str:
    return str(s or "").lower().replace(" ", "").replace("_", "").replace("-", "").lstrip("@")


def get_owner_account_ids() -> frozenset:
    raw = OWNER_ACCOUNT_IDS   # 要改擁有者帳號就改上面的 OWNER_ACCOUNT_IDS（不放 .env：.env 只放 API 金鑰）
    return frozenset(_norm_account(x) for x in raw.split(",") if _norm_account(x))


def is_owner_account(unique_id: str) -> bool:
    """平台帳號 ID 是否為擁有者本人。只看 unique_id，絕不看顯示名稱或觀眾檔案。"""
    uid = _norm_account(unique_id)
    return bool(uid) and uid in get_owner_account_ids()


def claims_owner_identity(text: str) -> bool:
    """稱呼／關係是否在冒充擁有者（含設定的 OWNER_NAME）。"""
    t = _norm_account(text)
    if not t:
        return False
    words = {_norm_account(w) for w in OWNER_CLAIM_WORDS} | {_norm_account(get_owner_name())}
    for w in words:
        if not w:
            continue
        # 英文整詞比對（避免 badminton 命中 admin）；中文用子字串（「我是老爸」「老爸本人」都算）
        if w.isascii():
            if t == w:
                return True
        elif w in t:
            return True
    return False
