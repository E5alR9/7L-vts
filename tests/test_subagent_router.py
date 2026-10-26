# -*- coding: utf-8 -*-
"""core.subagent_router — 用腦順序解析（不打任何 API）。"""
from conftest import ROOT  # noqa: F401
from core.subagent_router import resolve_subagent_chain


def test_modes():
    assert resolve_subagent_chain("nv") == ["nv"]
    assert resolve_subagent_chain("gemini") == ["gemini"]
    assert resolve_subagent_chain("auto") == ["gemini", "nv"]


def test_dirty_inputs_fall_back_to_auto():
    assert resolve_subagent_chain("") == ["gemini", "nv"]
    assert resolve_subagent_chain("  NV  ") == ["nv"]
    assert resolve_subagent_chain("Gemini") == ["gemini"]
    assert resolve_subagent_chain("nonsense") == ["gemini", "nv"]


def test_none_uses_module_setting(monkeypatch):
    import core.subagent_router as sr
    assert sr.SUBAGENT_BRAIN == "auto" and resolve_subagent_chain(None) == ["gemini", "nv"]
    monkeypatch.setattr(sr, "SUBAGENT_BRAIN", "nv")
    assert resolve_subagent_chain(None) == ["nv"]
    monkeypatch.setattr(sr, "SUBAGENT_BRAIN", "bogus")
    assert resolve_subagent_chain(None) == ["gemini", "nv"]
