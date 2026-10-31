# -*- coding: utf-8 -*-
"""
🪪 身份配置（Identity）：擁有者／角色／模式。

    MODE            companion | vtuber（預設 vtuber）。開機由 core/settings.boot 定一次（後台存的模式開關優先），
                    執行中切換只經 settings.apply_mode
    擁有者稱謂固定「老爸」（2026-10-29 老爸：不用 OWNER_NAME，她叫什麼靠她自己的記憶）
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
    """擁有者稱謂：固定「老爸」。以前讀 env OWNER_NAME，設成別的名字後紙條寫「E5離開電腦」、她嘴上叫老爸，兩邊對不上。"""
    return OWNER_DEFAULT


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


def _owner_bindings_file() -> str:
    from core import paths   # 執行時才讀：測試包裝會把 DATA_DIR 換成副本
    return os.path.join(paths.DATA_DIR, "owner_account_bindings.json")


def _load_owner_bindings() -> dict:
    import json
    try:
        with open(_owner_bindings_file(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_owner_bindings(data: dict) -> None:
    import json
    path = _owner_bindings_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def is_owner_account(platform_uid: str, handle: str = "") -> bool:
    """平台帳號是否為擁有者本人。只看監聽器給的帳號，絕不看顯示名稱或觀眾檔案。
    platform_uid：平台不會變的數字 ID（「id:123…」，2026-10-31 起）或舊的 @帳號名；handle：@帳號名。
    @帳號名可以改、改掉的舊名別人能再註冊（Fable 審查）：老爸的 @名第一次帶數字 ID 出現就綁定這個 ID，
    之後同一個 @名換了數字 ID 不算老爸。OWNER_ACCOUNT_IDS 也可以直接寫「id:數字」。"""
    owners = get_owner_account_ids()
    uid = _norm_account(platform_uid)
    if uid and uid in owners:
        return True
    h = _norm_account(handle)
    if not h or h not in owners:
        return False
    if not uid.startswith("id:"):
        return uid == h   # 沒有數字 ID（舊格式）：照舊認 @名
    bound = _load_owner_bindings()
    if h not in bound:
        bound[h] = uid
        try:
            _save_owner_bindings(bound)
            from core.utils import log_print
            log_print(f"🔐 [認老爸] @{handle} 第一次帶數字 ID 出現，綁定（之後同名不同 ID 不算老爸）")
        except Exception:
            from core.utils import log_swallowed
            log_swallowed()
            return False   # 綁不起來就先不認：寧可老爸再講一次，也不要放過冒牌貨
    return bound.get(h) == uid


def claims_owner_identity(text: str) -> bool:
    """稱呼／關係是否在冒充擁有者。"""
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
