# -*- coding: utf-8 -*-
"""
⚙️ .env 在哪、怎麼讀：ENV_PATH（專案資料夾有就用它，沒有就家目錄的）、load_project_env()。
以前這裡還有後台改 .env 的白名單編輯器，網頁從沒接上，2026-10-29 刪掉（git 歷史裡有）。
"""
import os

def _env_path() -> str:
    """金鑰檔：專案資料夾裡有 .env 就用它，沒有就用家目錄的（2026-10-27 專案搬進 7L-vts，.env 留在家目錄不動）。"""
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    home = os.path.join(os.path.expanduser("~"), ".env")
    return here if os.path.exists(here) or not os.path.exists(home) else home


ENV_PATH = _env_path()

_PROJECT_ENV_LOADED = False


def load_project_env() -> None:
    """把專案根目錄的 .env 讀進環境變數（已經有的不蓋；只讀一次）。
    llm_engine、groq_router 這些模組載入時就讀金鑰：誰先被 import，金鑰池就照當時的環境決定。
    以前只有主程式開頭讀 .env，別的入口先 import 它們就是空金鑰池（2026-10-25 測試時本能腦因此崩潰）。"""
    global _PROJECT_ENV_LOADED
    if _PROJECT_ENV_LOADED:
        return
    _PROJECT_ENV_LOADED = True
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH, override=False)
    except Exception:
        pass
