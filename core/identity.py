# -*- coding: utf-8 -*-
"""
🪪 身份配置（Identity）：擁有者／角色／模式，全部 env 可配、拒絕寫死。

    MODE            companion | vtuber（預設 vtuber，相容舊行為）
    OWNER_NAME      擁有者稱謂（預設「老爸」）
    CHARACTER_NAME  角色名（預設「7L」）

惰性讀取：改 .env 後重啟生效（MODE 切換需重啟以重裝 worker）。
見 docs/AI_SOURCES.md；白名單在 core/env_config.py。
"""
import os

CHARACTER_DEFAULT = "7L"
OWNER_DEFAULT = "老爸"
MODES = ("companion", "vtuber")


def get_mode() -> str:
    """運行模式；非法值回退 vtuber（絕不炸）。"""
    m = (os.getenv("MODE") or "vtuber").strip().lower()
    return m if m in MODES else "vtuber"


def is_companion() -> bool:
    return get_mode() == "companion"


def is_vtuber() -> bool:
    return get_mode() != "companion"


def get_owner_name() -> str:
    """擁有者稱謂（舊碼裡的「老爸」）。"""
    return (os.getenv("OWNER_NAME") or OWNER_DEFAULT).strip() or OWNER_DEFAULT


def get_character_name() -> str:
    """角色名（舊碼裡的「7L」）。"""
    return (os.getenv("CHARACTER_NAME") or CHARACTER_DEFAULT).strip() or CHARACTER_DEFAULT
