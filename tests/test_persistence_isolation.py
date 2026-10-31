"""存檔與測試隔離（2026-10-31 Fable 審查）。"""
import asyncio
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_sleep_and_stream_link_are_not_saved_or_restored():
    import services.dashboard_bridge as db
    assert {"IS_SLEEPING", "IS_STREAM_CHAT_ENABLED"} <= db.TRANSIENT_SWITCHES
    src = open(db.__file__, encoding="utf-8").read()
    assert "if key in TRANSIENT_SWITCHES:\n            sync_cloud = False" in src
    assert 'k != "MODE_TOGGLE" and k not in TRANSIENT_SWITCHES' in src


def test_second_dotenv_load_does_not_undo_the_mode_switch():
    from conftest import MAIN_SRC
    assert MAIN_SRC.count("load_dotenv(_ENV_PATH, override=True)") == 1   # 只有開頭那次
    assert "load_dotenv(_ENV_PATH, override=False)" in MAIN_SRC


def test_saving_prompts_keeps_the_switches():
    src = open(os.path.join(ROOT, "services", "web_dashboard.py"), encoding="utf-8").read()
    save = src[src.index("async def api_save_prompts"):src.index("async def api_reset_prompts")]
    assert "merged = dict(await get_cloud_knowledge())" in save and "merged.update(body)" in save
    reset = src[src.index("async def api_reset_prompts"):]
    assert 'default_kn["system_switches"] = _switches' in reset[:900]


def test_unreadable_viewer_file_is_not_overwritten(tmp_path, monkeypatch):
    import core.memory as mem
    f = tmp_path / "viewers.json"
    f.write_text('{"小明": {"call": "明哥"}, "小美', encoding="utf-8")   # 寫到一半當機
    monkeypatch.setattr(mem, "VIEWER_PROFILES_FILE", str(f))
    mem._store_viewer_profile_local("阿呆", {"call": "呆呆"})
    assert f.read_text(encoding="utf-8").startswith('{"小明"')   # 沒被蓋成只剩阿呆
    f.write_text(json.dumps({"小明": {"call": "明哥"}}), encoding="utf-8")
    mem._store_viewer_profile_local("阿呆", {"call": "呆呆"})
    assert set(json.loads(f.read_text(encoding="utf-8"))) == {"小明", "阿呆"} and not os.path.exists(str(f) + ".tmp")


def test_piano_settings_keep_the_window_geometry(tmp_path, monkeypatch):
    import services.piano_engine as pe
    f = tmp_path / "piano_settings.json"
    f.write_text(json.dumps({"geometry": "1200x300+10+700", "volume": 60}), encoding="utf-8")
    monkeypatch.setattr(pe, "PIANO_SETTINGS_FILE", str(f))
    pe.save_persisted_piano_settings(80, 1.2)
    assert json.loads(f.read_text(encoding="utf-8")) == {"geometry": "1200x300+10+700", "volume": 80, "speed": 1.2}


def test_sim_uses_a_copy_of_the_data_and_no_cloud():
    src = open(os.path.join(ROOT, "tools", "sim", "sim_run.py"), encoding="utf-8").read()
    assert 'os.environ.get("SIM_NO_CLOUD", "1") == "1"' in src                   # 預設不連雲端
    assert "_paths.DATA_DIR = os.path.join(SIM_DATA, \"data\")" in src
    assert "_pe.MIDI_CATALOG_FILE" in src and "_rag_store.PERSIST_DIR" in src and "_db.OFFLINE_QUEUE_FILE" in src
    assert "sys.argv = [os.path.abspath(__file__)]" in src                       # 重開開回測試包裝
    assert "正式的 7L 正在跑" in src                                             # 不把正式的 7L 殺掉
    # 路徑要在主程式 import 記憶模組之前改：import core.memory 在改完路徑之後、runpy 之前
    assert src.index("_paths.DATA_DIR =") < src.index("import core.memory as _mem") < src.index("runpy.run_path")
