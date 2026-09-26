# -*- coding: utf-8 -*-
"""core/env_config 測試：多行金鑰不可被毀、白名單拒寫、機密只寫不讀、熱套用"""
import os

from conftest import ROOT  # noqa: F401
from core import env_config as ec

# 測試用 .env：刻意含「多行 GROQ 金鑰」（本專案踩過的地雷）
SAMPLE_ENV = """\
# 金鑰
GROQ_API_KEYS=gsk_aaa111,
gsk_bbb222,
gsk_ccc333
GEMINI_API_KEY=AIzaSECRETSECRET
TTS_ENGINE=kokoro
OPERATOR_INPUT=0
GROQ_REQUESTS_PER_MINUTE=20
TWITCH_CHANNELS=
"""


def _write(tmp_path, content=SAMPLE_ENV):
    p = os.path.join(str(tmp_path), ".env")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return p


def test_read_env_handles_multiline_keys(tmp_path):
    p = _write(tmp_path)
    cfg = ec.read_env_file(p)
    assert cfg["GROQ_API_KEYS"] == "gsk_aaa111,\ngsk_bbb222,\ngsk_ccc333"  # 三行完整保留
    assert cfg["TTS_ENGINE"] == "kokoro"
    assert cfg["TWITCH_CHANNELS"] == ""


def test_update_single_key_preserves_multiline_block(tmp_path):
    p = _write(tmp_path)
    applied, restart, errors = ec.update_settings({"TTS_ENGINE": "cosyvoice,kokoro"}, path=p)
    assert errors == {}
    assert applied == ["TTS_ENGINE"] and restart == ["TTS_ENGINE"]   # TTS_ENGINE restart=True
    cfg = ec.read_env_file(p)
    # 多行金鑰必須原封不動（這就是區塊替換的價值）
    assert cfg["GROQ_API_KEYS"] == "gsk_aaa111,\ngsk_bbb222,\ngsk_ccc333"
    assert cfg["GEMINI_API_KEY"] == "AIzaSECRETSECRET"
    assert cfg["TTS_ENGINE"] == "cosyvoice,kokoro"


def test_update_appends_missing_key(tmp_path):
    p = _write(tmp_path)
    applied, _, _ = ec.update_settings({"YOUTUBE_LIVE_ID": "https://www.youtube.com/watch?v=abc123def45"}, path=p)
    assert applied == ["YOUTUBE_LIVE_ID"]
    cfg = ec.read_env_file(p)
    assert cfg["YOUTUBE_LIVE_ID"] == "https://www.youtube.com/watch?v=abc123def45"
    assert cfg["GROQ_API_KEYS"].count("gsk_") == 3     # 追加沒毀到舊的


def test_whitelist_rejects_unknown_keys(tmp_path):
    p = _write(tmp_path)
    before = open(p, encoding="utf-8").read()
    applied, restart, errors = ec.update_settings({"RM_RF_SLASH": "/", "PATH": "x"}, path=p)
    assert applied == [] and restart == []
    assert "RM_RF_SLASH" in errors and "PATH" in errors
    assert open(p, encoding="utf-8").read() == before        # 檔案完全沒動


def test_type_validation(tmp_path):
    p = _write(tmp_path)
    applied, _, errors = ec.update_settings({
        "GROQ_REQUESTS_PER_MINUTE": "abc",        # int 驗證失敗
        "WEB_BIND_HOST": "8.8.8.8",               # choice 驗證失敗
        "TTS_SPEED": "not-a-float",               # float 驗證失敗
    }, path=p)
    assert applied == []
    assert errors["GROQ_REQUESTS_PER_MINUTE"] == "需為整數"
    assert "必須是" in errors["WEB_BIND_HOST"]
    assert errors["TTS_SPEED"] == "需為數字"
    # 合法的照過
    applied, _, errors = ec.update_settings({
        "GROQ_REQUESTS_PER_MINUTE": "0", "WEB_BIND_HOST": "127.0.0.1", "TTS_SPEED": "1.25"},
        path=p)
    assert errors == {} and set(applied) == {"GROQ_REQUESTS_PER_MINUTE", "WEB_BIND_HOST", "TTS_SPEED"}
    assert ec.read_env_file(p)["TTS_SPEED"] == "1.25"


def test_bool_normalization(tmp_path):
    p = _write(tmp_path)
    for raw in ("1", "true", "YES", "on"):
        ec.update_settings({"OPERATOR_INPUT": raw}, path=p)
        assert ec.read_env_file(p)["OPERATOR_INPUT"] == "1"
    for raw in ("0", "false", "no", "off"):
        ec.update_settings({"OPERATOR_INPUT": raw}, path=p)
        assert ec.read_env_file(p)["OPERATOR_INPUT"] == "0"


def test_secret_write_only(tmp_path):
    p = _write(tmp_path)
    specs = {s["key"]: s for s in ec.read_settings(p)}
    # 讀：永不含值
    g = specs["GROQ_API_KEYS"]
    assert g["secret"] is True and g["value"] == ""
    assert g["secret_info"]["set"] is True and g["secret_info"]["len"] > 0
    assert g["secret_info"]["prefix"].startswith("gsk_")
    # 寫：非空才覆蓋
    applied, _, errors = ec.update_settings({"GROQ_API_KEYS": ""}, path=p)   # 留空=不改
    assert applied == [] and errors == {}
    assert ec.read_env_file(p)["GROQ_API_KEYS"].startswith("gsk_aaa111")
    applied, restart, _ = ec.update_settings({"GROQ_API_KEYS": "gsk_new_key_123"}, path=p)
    assert applied == ["GROQ_API_KEYS"] and restart == ["GROQ_API_KEYS"]
    assert ec.read_env_file(p)["GROQ_API_KEYS"] == "gsk_new_key_123"
    # 非機密欄位會回傳值
    t = specs["TTS_ENGINE"]
    assert t["secret"] is False and t["value"] == "kokoro"


def test_hot_apply_non_restart_keys(tmp_path, monkeypatch):
    """restart=False 的 key 寫檔同時進 os.environ（惰性讀取的設定立即生效）"""
    p = _write(tmp_path)
    monkeypatch.delenv("OPERATOR_INPUT", raising=False)
    monkeypatch.delenv("GROQ_REQUESTS_PER_MINUTE", raising=False)
    ec.update_settings({"OPERATOR_INPUT": "1", "GROQ_REQUESTS_PER_MINUTE": "99"}, path=p)
    assert os.environ["OPERATOR_INPUT"] == "1"
    assert os.environ["GROQ_REQUESTS_PER_MINUTE"] == "99"
    # restart=True 的不碰 os.environ（避免未重啟就半生效）
    monkeypatch.delenv("TTS_ENGINE", raising=False)
    ec.update_settings({"TTS_ENGINE": "edge"}, path=p)
    assert "TTS_ENGINE" not in os.environ
    # 熱套用的函式立刻看得到
    from core.utils import operator_input_enabled
    assert operator_input_enabled() is True


def test_quoting_for_special_values(tmp_path):
    p = _write(tmp_path, "A=\n")
    ec.update_settings({"TWITCH_CHANNELS": "has space"}, path=p)     # 空白 → 加引號
    raw = open(p, encoding="utf-8").read()
    assert 'TWITCH_CHANNELS="has space"' in raw
    cfg = ec.read_env_file(p)
    assert cfg["TWITCH_CHANNELS"] == "has space"                    # 讀回來會剝引號
    # 更新既有 key（不是追加）
    ec.update_settings({"TWITCH_CHANNELS": "plain,id"}, path=p)
    raw2 = open(p, encoding="utf-8").read()
    assert raw2.count("TWITCH_CHANNELS=") == 1
    assert ec.read_env_file(p)["TWITCH_CHANNELS"] == "plain,id"


def test_backup_created_with_previous_content_before_write(tmp_path):
    """控制台改 .env 前必須先備份（.env.backup = 寫入前的舊內容）"""
    p = _write(tmp_path)                      # 內容 = SAMPLE_ENV（TTS_ENGINE=kokoro）
    backup = p + ".backup"
    if os.path.exists(backup):
        os.remove(backup)
    ec.update_settings({"TTS_ENGINE": "cosyvoice"}, path=p)
    assert os.path.exists(backup), "未建立 .env.backup"
    old = open(backup, encoding="utf-8").read()
    assert "TTS_ENGINE=kokoro" in old          # 備份是「改之前的」舊值
    assert "gsk_ccc333" in old                 # 多行金鑰也完整備份
    # 備份不被 git 追蹤（間接驗證：檔名在 .gitignore 清單）
    gi = open(os.path.join(str(ROOT), ".gitignore"), encoding="utf-8").read()
    assert ".env.backup" in gi
