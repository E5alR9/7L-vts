# -*- coding: utf-8 -*-
"""提示詞快照（2026-10-26）：各角色的提示詞用固定的輸入組一次，跟 tests/snapshots/prompts/ 比。
提示詞（core/promptkit.py、prompts/*.md、表情選單）改了這裡會紅；確定是故意改的，重產快照：
    UPDATE_PROMPT_SNAPSHOTS=1 python -m pytest tests/test_prompt_snapshots.py
"""
import difflib
import os

import pytest

import services.vts_client as vc
from core import promptkit
from core.memory import DEFAULT_CLOUD_KNOWLEDGE

SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots", "prompts")
MENU_NAMES = "、".join(n for _ctx, names in vc.EXPRESSION_MENU for n in names)

ROLES = {
    "brain": lambda: promptkit.brain_system("老爸", "7L", DEFAULT_CLOUD_KNOWLEDGE, vc.EXPRESSION_MENU_TEXT),
    "board_sentry": lambda: promptkit.BOARD_SENTRY_SYSTEM,
    "screen_sentry": lambda: promptkit.SCREEN_SENTRY_SYSTEM + "\n---\n" + promptkit.screen_sentry_user("老爸在寫程式"),
    "director": lambda: promptkit.director_system(MENU_NAMES),
    "instinct": lambda: promptkit.instinct_system(vc.EXPRESSION_MENU_TEXT),
    "subagent": lambda: promptkit.subagent_system(),
}


@pytest.mark.parametrize("role", sorted(ROLES))
def test_prompt_matches_snapshot(role):
    text = ROLES[role]()
    assert text.strip(), f"{role} 的提示詞是空的"
    path = os.path.join(SNAP_DIR, f"{role}.txt")
    if os.environ.get("UPDATE_PROMPT_SNAPSHOTS") == "1" or not os.path.exists(path):
        os.makedirs(SNAP_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return
    snap = open(path, encoding="utf-8").read()
    if text != snap:
        diff = "\n".join(difflib.unified_diff(snap.splitlines(), text.splitlines(), "快照", "現在", lineterm="", n=1))
        pytest.fail(f"{role} 的提示詞跟快照不一樣（故意改的就設 UPDATE_PROMPT_SNAPSHOTS=1 重產）：\n{diff[:3000]}")
