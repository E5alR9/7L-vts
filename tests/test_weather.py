# -*- coding: utf-8 -*-
"""天氣專用資料源（services/weather，2026-11-01）：以前問天氣走網路搜尋，拿到 4 月清明的舊新聞。不連網，假的 Open-Meteo。"""
import services.weather as w
import services.web_search as ws

FAKE = {"current": {"time": "2026-11-01T23:45", "temperature_2m": 23.1, "weather_code": 0},
        "daily": {"time": ["2026-11-01", "2026-11-02", "2026-11-03"], "weather_code": [3, 61, 2],
                  "temperature_2m_max": [31.0, 30.5, 31.5], "temperature_2m_min": [22.1, 22.3, 21.5],
                  "precipitation_probability_max": [0, 80, 2]}}


def test_taiwan_places_come_from_the_table_not_the_geocoder(monkeypatch):
    urls = []
    monkeypatch.setattr(w, "_get", lambda u: urls.append(u) or FAKE)
    assert w.find_place("明天台中會不會下雨")[0] == "台中"
    assert w.find_place("新竹明天天氣")[0] == "新竹"
    assert w.find_place("後天墾丁的天氣")[0] == "墾丁"
    assert urls == []                                                         # 「高雄」問 Open-Meteo 會抓到四川的高雄


def test_forecast_lines_have_dates_and_rain(monkeypatch):
    monkeypatch.setattr(w, "_get", lambda u: FAKE)
    t = w.forecast_text("明天台中會不會下雨")
    assert "台中明天 11/2（星期一）：小雨，22～30 度，降雨機率 80%" in t
    assert "台中現在 23 度，晴" in t


def test_not_weather_or_no_place_or_down_falls_back(monkeypatch):
    monkeypatch.setattr(w, "_get", lambda u: FAKE)
    assert w.forecast_text("今天美金匯率") == ""
    assert w.forecast_text("最近台灣有颱風嗎") == ""                           # 颱風查新聞比較準

    def down(u):
        raise OSError("offline")
    monkeypatch.setattr(w, "_get", down)
    assert w.forecast_text("台北明天天氣") == ""


def test_search_google_uses_forecast_first(monkeypatch):
    monkeypatch.setattr(w, "_get", lambda u: FAKE)
    assert "降雨機率 80%" in ws.search_google("台北明天天氣")
