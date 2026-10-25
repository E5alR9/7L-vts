# -*- coding: utf-8 -*-
"""網路搜尋 2026-10-25 從主程式搬到 services/web_search.py：多金鑰輪替、搜尋結果格式。"""
import os

from conftest import ROOT
import services.web_search as ws


class _Fake:
    def __init__(self, res):
        self.res, self.calls = res, 0

    def search(self, **kw):
        self.calls += 1
        if isinstance(self.res, Exception):
            raise self.res
        return self.res


def test_multikey_tavily_skips_exhausted_keys():
    c = ws.MultiKeyTavilyClient([])
    good = _Fake({"results": [{"title": "日圓", "content": "1 美元 = 159 日圓"}]})
    c._clients = [_Fake({"error": "quota exceeded"}), _Fake(RuntimeError("429 limit")), good]
    assert c.search("日圓")["results"][0]["title"] == "日圓"
    assert c._current_idx == 2                                            # 下次直接從好的那把開始
    assert ws.MultiKeyTavilyClient([]).search("x") == {"error": "No Tavily API keys configured"}


def test_search_google_formats_tavily_results(monkeypatch):
    monkeypatch.setattr(ws, "tavily_client", _Fake({"results": [{"title": "A", "content": "a"}, {"title": "B", "content": "b"}]}))
    assert ws.search_google("今天新聞") == "- A: a\n- B: b"


def test_search_code_not_left_in_main():
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    for frag in ("def search_google(", "def summarize_search_to_speech(", "class MultiKeyTavilyClient",
                 "class PurePythonTavilyClient", "TAVILY_KEYS = "):
        assert frag not in main
