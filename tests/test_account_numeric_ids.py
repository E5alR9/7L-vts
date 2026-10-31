"""認人、認老爸改用平台不會變的數字 ID（老爸 2026-10-31：「那搬一下」）。
@帳號名可以改、改掉的舊名別人能再註冊：拿它當 key，熟客改名變新人，撿到舊名的人直接拿到熟客的檔（Fable 審查）。"""
import json
from types import SimpleNamespace

import core.identity as idt
import core.memory as mem
import services.twitch_listener as tw
from core.input_sources import parse_input_item
from services.tiktok_listener import tiktok_account


def test_tiktok_listener_sends_the_numeric_id_and_keeps_the_handle_aside():
    u = SimpleNamespace(id=7123456789, id_str="7123456789", unique_id="adai_real", nickname="阿呆")
    assert tiktok_account(u) == {"platform_uid": "id:7123456789", "platform_handle": "adai_real"}
    assert tiktok_account(SimpleNamespace(id=0, id_str="", unique_id="old_style")) == \
        {"platform_uid": "old_style", "platform_handle": "old_style"}                   # 拿不到數字 ID 才退回 @名
    assert tiktok_account(None) == {"platform_uid": "", "platform_handle": ""}


def test_twitch_uses_the_user_id_tag():
    line = ("@badges=;display-name=Alice;id=m1;user-id=44322889 :alice!alice@alice.tmi.twitch.tv "
            "PRIVMSG #chan :hello")
    msg = tw.parse_irc_line(line)
    assert msg["user_id"] == "44322889"
    item = parse_input_item(tw.build_queue_item(msg["user"], msg["display"], msg["message"], "m1", msg["user_id"]))
    assert item.platform_uid == "id:44322889" and item.platform_handle == "alice"
    assert parse_input_item(tw.build_queue_item("bob", "bob", "hi")).platform_uid == "bob"   # 沒有標籤照舊


def test_owner_handle_is_bound_to_the_first_numeric_id(tmp_path, monkeypatch):
    import core.paths as paths
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(idt, "OWNER_ACCOUNT_IDS", "qiwai")
    assert idt.is_owner_account("id:111", "qiwai")                     # 老爸第一次帶數字 ID：綁定
    assert json.loads((tmp_path / "owner_account_bindings.json").read_text(encoding="utf-8")) == {"qiwai": "id:111"}
    assert idt.is_owner_account("id:111", "qiwai")
    assert not idt.is_owner_account("id:999", "qiwai")                 # 撿到 @qiwai 的別人：不是老爸
    assert not idt.is_owner_account("id:111", "someone")
    assert idt.is_owner_account("qiwai")                               # 舊格式（沒有數字 ID）照舊
    monkeypatch.setattr(idt, "OWNER_ACCOUNT_IDS", "qiwai,id:222")
    assert idt.is_owner_account("id:222", "whatever")                  # 也能直接寫數字 ID


def test_handle_keyed_profile_moves_to_the_numeric_id_once(tmp_path, monkeypatch):
    f = tmp_path / "viewers.json"
    f.write_text(json.dumps({"tiktok:jaded_jjj": {"name": "J", "names": ["J"], "call": "阿J", "uid": "jaded_jjj"}},
                            ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mem, "VIEWER_PROFILES_FILE", str(f))
    monkeypatch.setattr(mem, "VIEWER_ADOPT_PENDING_FILE", str(tmp_path / "pending.json"))
    monkeypatch.setattr(mem, "_DISPLAY_TO_KEY", {})
    monkeypatch.setattr(mem.db_module, "db", None)
    monkeypatch.setattr(mem, "_RAG", None)
    mem.note_viewer_seen("J", "tiktok:id:555", "tiktok:jaded_jjj")
    data = json.loads(f.read_text(encoding="utf-8"))
    assert "tiktok:jaded_jjj" not in data
    assert data["tiktok:id:555"]["call"] == "阿J" and data["tiktok:id:555"]["uid"] == "id:555" \
        and data["tiktok:id:555"]["handle"] == "jaded_jjj"
    # 之後有人撿到 @jaded_jjj（不同數字 ID）：拿不到 J 的檔
    monkeypatch.setattr(mem, "_DISPLAY_TO_KEY", {})
    mem.note_viewer_seen("J", "tiktok:id:777", "tiktok:jaded_jjj")
    data = json.loads(f.read_text(encoding="utf-8"))
    assert "tiktok:id:777" not in data and data["tiktok:id:555"]["call"] == "阿J"


def test_an_event_without_an_account_does_not_overwrite_the_name_mapping(tmp_path, monkeypatch):
    """2026-10-31 實機：只帶名字的送禮把「小明 → 帳號」蓋成名字 key，熟客之後的更新寫進名字 key 的舊檔。"""
    monkeypatch.setattr(mem, "VIEWER_PROFILES_FILE", str(tmp_path / "v.json"))
    monkeypatch.setattr(mem, "VIEWER_ADOPT_PENDING_FILE", str(tmp_path / "p.json"))
    monkeypatch.setattr(mem, "_DISPLAY_TO_KEY", {})
    monkeypatch.setattr(mem.db_module, "db", None)
    mem.note_viewer_seen("小明", "tiktok:id:1")
    assert mem.note_viewer_seen("小明", "小明") == "小明"
    assert mem.resolve_viewer_key("小明") == "tiktok:id:1"
