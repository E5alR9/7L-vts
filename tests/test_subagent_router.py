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


def test_none_reads_env(monkeypatch):
    monkeypatch.setenv("SUBAGENT_BRAIN", "nv")
    assert resolve_subagent_chain(None) == ["nv"]
    monkeypatch.setenv("SUBAGENT_BRAIN", "gemini")
    assert resolve_subagent_chain(None) == ["gemini"]
    monkeypatch.setenv("SUBAGENT_BRAIN", "bogus")
    assert resolve_subagent_chain(None) == ["gemini", "nv"]
    monkeypatch.delenv("SUBAGENT_BRAIN", raising=False)
    assert resolve_subagent_chain(None) == ["gemini", "nv"]
