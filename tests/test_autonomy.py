# -*- coding: utf-8 -*-
"""持續感知（2026-10-29 老爸：Live 退到幕後了，讓她持續感知世界、自己決定要不要講）。"""
import ast
import time

from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE  # noqa: E402


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _const(name):
    node = next(n for n in TREE.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name)
    return ast.literal_eval(node.value)


def _load(*names, **ns):
    for n in names:
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    return ns


def test_changes_since_last_pulse():
    ns = _load("_autonomy_changes", _owner_name=lambda: "老爸", _NO_CHANGE_WORDS=_const("_NO_CHANGE_WORDS"))
    f = ns["_autonomy_changes"]
    prev = {"screen": "VS Code 在寫程式", "screen_ts": 100.0, "music": "", "present": True}
    assert f(None, prev) == [] and f(prev, dict(prev)) == []                 # 第一輪、沒變
    cur = dict(prev, screen="YouTube 在看貓咪影片", screen_ts=200.0, music="晴天 - 周杰倫", present=False)
    out = f(prev, cur)
    assert any("貓咪影片" in x for x in out) and any("晴天" in x for x in out) and "老爸離開電腦了" in out
    assert "老爸回到電腦前了" in f(dict(prev, present=False), prev)
    assert f(prev, dict(prev, screen_ts=300.0)) == []                         # 又看了一次但畫面一樣：不算變
    # 第一版實測：描述寫「這段時間畫面沒有明顯的動態變化」也被當成畫面變了，她就去評論
    assert f(prev, dict(prev, screen="這段時間畫面沒有明顯的動態變化，老爸保持著開啟工作管理員", screen_ts=300.0)) == []
    # 第二版實測：開機後第一次看到畫面（上一輪還沒有畫面）也算「變了」，她就去講
    assert f(dict(prev, screen="", screen_ts=0.0), prev) == []
    # 第三版實測：開機佔位字「目前沒有特別的畫面動態。」也被當成上一輪的畫面
    # 第四版實測：老爸放 YouTube 鋼琴歌單，每換一首她就評論一次；只算「安靜→開始放」
    assert f(dict(prev, music="《暴風雨》"), dict(prev, music="《華麗圓舞曲》")) == []
    assert "目前沒有特別的畫面動態" in MAIN and 'scr.startswith("目前沒有特別的畫面動態")' in MAIN
    # 老爸剛開口才變成「在」：不是回到電腦前
    away = dict(prev, present=False, dad_ts=0.0)
    assert f(away, dict(prev, dad_ts=500.0)) == [] and "老爸回到電腦前了" in f(away, dict(prev, dad_ts=0.0))


def _snap_ns(idle, dad_ts, music="", singing=False, piano=False, title=""):
    import types
    return _load("_her_own_music", "_autonomy_snapshot", time=time, _input_idle_sec=lambda: idle,
                 _BRAIN_INPUT_ORIGIN={"who": "dad", "ts": dad_ts}, LATEST_SYSTEM_MUSIC_INFO=music,
                 current_screen_context="VS Code", LAST_VISION_LOOK_TIME=1.0, AUTONOMY_PRESENT_IDLE_SEC=300.0,
                 is_singing_active=lambda: singing, getattr=getattr, bool=bool,
                 pe=types.SimpleNamespace(is_piano_active=piano, current_piano_song_title=title),
                 stage=types.SimpleNamespace(ai_state=lambda: "IDLE"))["_autonomy_snapshot"]


def test_snapshot_presence_and_her_own_music():
    now = time.time()
    # 第二版實測：老爸打字叫她「陪我就好」後只看不動滑鼠 6 分鐘，就被寫成「離開電腦」
    assert _snap_ns(idle=400.0, dad_ts=now - 50)(now)["present"] is True
    assert _snap_ns(idle=400.0, dad_ts=now - 600)(now)["present"] is False
    # 她自己唱完，琴聲被當成「電腦開始在放《鋼琴曲》」
    assert _snap_ns(None, now, music="《鋼琴曲》")(now)["music"] == ""
    assert _snap_ns(None, now, music="《晴天》", title="晴天")(now)["music"] == ""
    assert _snap_ns(None, now, music="《晴天》", piano=True)(now)["music"] == ""
    assert _snap_ns(None, now, music="《稻香》")(now)["music"] == "《稻香》"


def test_pulse_rhythm_comes_early_on_change():
    ns = _load("_autonomy_due", AUTONOMY_CHANGE_SEC=45.0)
    f = ns["_autonomy_due"]
    assert not f(100.0, 0.0, 120.0, False) and f(120.0, 0.0, 120.0, False)
    assert f(50.0, 0.0, 120.0, True) and not f(40.0, 0.0, 120.0, True)        # 有變化：45 秒就想
    assert not f(200.0, 0.0, 300.0, False)                                    # 退避拉長後照長間隔


def _say_ns(pulse_ts, human_ts, last_self=0.0, said=False):
    import re
    a = {"pulse_ts": pulse_ts, "said_in_pulse": said, "last_self_say_ts": last_self, "last_self_say": "", "self_says": 0,
         "recent_self_says": [], "interval": 120.0}
    return _load("_autonomy_note_say", re=re, AUTONOMY_ENABLED=True, _AUTONOMY=a, _BRAIN_INPUT_ORIGIN={"ts": human_ts},
                 AUTONOMY_AFTER_HUMAN_SEC=30.0, AUTONOMY_SAY_MIN_GAP=240.0, AUTONOMY_AFTER_SAY_SEC=900.0,
                 AUTONOMY_SELF_SAY_MEMORY=3), a


def test_self_initiated_say_is_capped_but_replies_and_results_are_not():
    now = time.time()
    ns, a = _say_ns(pulse_ts=now - 2, human_ts=now - 300)
    assert ns["_autonomy_note_say"]("[EXPRESSION: 笑] 老爸還在寫程式喔？", now) == "self" and a["self_says"] == 1
    assert a["recent_self_says"] == ["老爸還在寫程式喔？"] and a["interval"] == 900.0   # 記下來別再提、下一輪等久一點
    assert ns["_autonomy_note_say"]("我看看～查到了", now + 5) == ""             # 這輪開過口了：後面的結果照講
    ns, a = _say_ns(pulse_ts=now - 2, human_ts=now - 300, last_self=now - 200)
    assert ns["_autonomy_note_say"]("又想講一句", now) == "block"                # 200 秒前才主動講過（上限 240 秒）
    ns, a = _say_ns(pulse_ts=now - 100, human_ts=now - 5, last_self=now - 30)
    assert ns["_autonomy_note_say"]("回老爸", now) == ""                         # 最近一則是人講的：在回人，不限


def test_slip_says_what_changed_and_how_to_behave():
    import types
    ns = _load("_autonomy_slip", _owner_name=lambda: "老爸", get_current_time_string=lambda: "下午 3:00",
               _BRAIN_INPUT_ORIGIN={"ts": time.time() - 600, "who": "dad", "said": "我在寫程式，妳陪我就好"}, int=int,
               pe=types.SimpleNamespace(is_piano_performing=lambda: False, is_piano_active=False),
               _AUTONOMY={"last_self_say_ts": 0.0, "last_self_say": "", "recent_self_says": ["那個對話框卡很久了耶"]},
               AUTONOMY_PRESENT_IDLE_SEC=300.0)
    s = ns["_autonomy_slip"](["電腦畫面變了：在看貓咪影片"], {"screen": "貓咪影片", "present": False, "idle": 400}, time.time())
    assert s.startswith("[系統提示：【感知】") and "不是誰在跟妳說話" in s and "貓咪影片" in s
    assert "離開電腦約 6 分鐘" in s and "最後跟妳講話是 10 分鐘前" in s and "預設安靜" in s and "say" in s
    assert "對話框卡很久" in s and "不要再提" in s                              # 提過的不再提（第一版同一個對話框講 4 輪）
    assert "不要問問題" in s                                                    # 老爸不在：第一版對空房間問「你要聽哪一首」
    assert "妳陪我就好" not in s and "沒寫的不要編" in s                        # 第二版編「音樂也播完了」；10 分鐘前的話不附
    ns["_BRAIN_INPUT_ORIGIN"]["ts"] = time.time() - 60
    assert "妳陪我就好" in ns["_autonomy_slip"]([], {"present": True, "idle": 10}, time.time())   # 剛講的才附
    s = ns["_autonomy_slip"]([], {"screen": "VS Code", "present": True, "idle": 10}, time.time())
    assert "想自己彈琴唱歌可以" in s and "不要問問題" not in s                 # 老爸在也准她自己彈唱（老爸 10-29）
    assert "什麼都沒發生" in s and "不想就繼續安靜" in s                        # 沒事那輪＝很久沒事的「無聊了」


def test_wiring():
    assert _const("AUTONOMY_ENABLED") is True and _const("AUTONOMY_PULSE_SEC") == 900.0   # 有事才想；沒事 15 分鐘才給一輪「無聊了」
    assert "spawn(autonomy_worker())" in MAIN
    idle = ast.get_source_segment(MAIN, _fn("idle_chatter_worker"))
    assert "if AUTONOMY_ENABLED and LIVE_SAY_GATE:" in idle                    # 舊的時間表閒聊讓位
    assert '"【感知】" in (prompt or "")' in ast.get_source_segment(MAIN, _fn("_slip_watchdog"))   # 不講話是合法答案
    blocked = ast.get_source_segment(MAIN, _fn("_autonomy_blocked"))
    assert "剛遞過別的紙條" in blocked                                          # 謝幕紙條跟感知同一秒到
    assert "剛主動講過" in blocked                                              # 上限內不想：想講的一定被擋
    say = ast.get_source_segment(MAIN, _fn("_handle_say"))
    assert "queue_while_singing=True" in say and '_autonomy_note_say(raw, time.time()) == "block"' in say
    speak = ast.get_source_segment(MAIN, _fn("_speak_brain_turn"))
    assert "queue_while_singing or not is_singing_active()" in speak           # 唱歌中 say 排隊，等間奏空白
