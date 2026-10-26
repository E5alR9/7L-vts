# -*- coding: utf-8 -*-
"""運行模式開機定一次（core/settings.py，2026-10-26）。"""
import json
import os

import pytest

from core import settings


@pytest.fixture(autouse=True)
def _keep_env(monkeypatch):
    """apply_mode 直接改 os.environ：每個測試前先經 monkeypatch 記下，測完還原。"""
    for k in ("MODE", "OPERATOR_INPUT", "OPERATOR_SPEECH"):
        monkeypatch.setenv(k, os.environ.get(k, ""))


def _knowledge(tmp_path, mode, switches):
    with open(os.path.join(tmp_path, f"cloud_knowledge_local_{mode}.json"), "w", encoding="utf-8") as f:
        json.dump({"system_switches": switches}, f)


def test_env_mode_when_nothing_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "companion")
    monkeypatch.setenv("OPERATOR_INPUT", "1")
    s = settings.boot(str(tmp_path))
    assert (s.mode, s.source, s.operator_input) == ("companion", ".env", True)


def test_saved_switch_wins_and_sets_operator_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "companion")
    monkeypatch.setenv("OPERATOR_INPUT", "1")
    _knowledge(tmp_path, "companion", {"MODE_TOGGLE": False})          # 後台切成 VTuber 過
    s = settings.boot(str(tmp_path))
    assert (s.mode, s.source, s.operator_input) == ("vtuber", "後台開關", False)
    assert os.environ["MODE"] == "vtuber" and os.environ["OPERATOR_INPUT"] == "0"


def test_bad_values_fall_back_to_vtuber(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "亂寫")
    assert settings.boot(str(tmp_path)).mode == "vtuber"
    assert settings.apply_mode("亂寫") == "vtuber"


def test_apply_mode_companion_turns_operator_on(monkeypatch):
    for k in ("MODE", "OPERATOR_INPUT", "OPERATOR_SPEECH"):
        monkeypatch.delenv(k, raising=False)
    assert settings.apply_mode("companion") == "companion"
    assert (os.environ["OPERATOR_INPUT"], os.environ["OPERATOR_SPEECH"]) == ("1", "1")


def test_main_boots_settings_before_importing_memory():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    boot = src.index("_settings.boot(")
    for mod in ("core.memory", "services.auto_cover_pipeline", "services.web_dashboard"):
        assert src.index(mod) > boot, mod
