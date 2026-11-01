r"""
天氣專用資料源（2026-11-01 老爸：查其他好用有效率的 AI 架構試看看——工具專門化）
PROVIDER: Open-Meteo（免金鑰；見 docs/AI_SOURCES.md）

以前問天氣也走一般網路搜尋（Tavily）：「明天台中會不會下雨」拿到 4 月清明連假的新聞和社群貼文，
她講成「最近鋒面多經常下雨」。這裡直接拿預報數字（今天起三天：天氣、最高最低溫、降雨機率），
帶日期，交給同一套搜尋摘要講成一兩句。

台灣地名用下面的座標表：Open-Meteo 的中文地名查詢「台中」查不到、「高雄」抓到四川的高雄（2026-11-01 實測）。
表裡沒有的（國外城市）才問它的地名查詢。
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional, Tuple

from core.utils import log_print

# 縣市＋常問的地方（緯度, 經度）
TAIWAN_PLACES = {
    "台北": (25.04, 121.56), "臺北": (25.04, 121.56), "新北": (25.01, 121.46), "板橋": (25.01, 121.46),
    "基隆": (25.13, 121.74), "桃園": (24.99, 121.30), "新竹": (24.80, 120.97), "苗栗": (24.56, 120.82),
    "台中": (24.15, 120.67), "臺中": (24.15, 120.67), "彰化": (24.08, 120.54), "南投": (23.91, 120.68),
    "雲林": (23.71, 120.43), "斗六": (23.71, 120.54), "嘉義": (23.48, 120.45), "台南": (22.99, 120.21),
    "臺南": (22.99, 120.21), "高雄": (22.63, 120.30), "屏東": (22.67, 120.49), "宜蘭": (24.75, 121.75),
    "花蓮": (23.98, 121.60), "台東": (22.76, 121.15), "臺東": (22.76, 121.15), "澎湖": (23.57, 119.58),
    "金門": (24.43, 118.32), "馬祖": (26.16, 119.95), "墾丁": (21.95, 120.80), "恆春": (22.00, 120.74),
    "阿里山": (23.51, 120.80), "日月潭": (23.86, 120.91), "清境": (24.06, 121.16), "合歡山": (24.14, 121.27),
    "九份": (25.11, 121.84), "淡水": (25.17, 121.44), "陽明山": (25.16, 121.55), "太魯閣": (24.16, 121.62),
    "綠島": (22.66, 121.49), "蘭嶼": (22.05, 121.55), "小琉球": (22.34, 120.37),
}
WEATHER_WORDS = re.compile(r"天氣|下雨|會不會雨|降雨|氣溫|溫度|幾度|冷不冷|熱不熱|帶傘|晴天|陰天|預報")   # 颱風不算：颱風消息查新聞比較準
_CODES = {0: "晴", 1: "大致晴朗", 2: "晴時多雲", 3: "多雲", 45: "有霧", 48: "有霧", 51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
          56: "凍雨", 57: "凍雨", 61: "小雨", 63: "中雨", 65: "大雨", 66: "凍雨", 67: "凍雨", 71: "小雪", 73: "中雪",
          75: "大雪", 77: "雪", 80: "陣雨", 81: "陣雨", 82: "大陣雨", 85: "陣雪", 86: "陣雪", 95: "雷雨", 96: "雷雨夾冰雹",
          99: "雷雨夾冰雹"}
_WEEK = "一二三四五六日"
TIMEOUT_SEC = 6.0


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as r:
        return json.loads(r.read().decode("utf-8"))


def find_place(text: str) -> Optional[Tuple[str, float, float]]:
    """句子裡的地名 → (地名, 緯度, 經度)。台灣先查表（長的地名先比，「新竹」不會被「竹」搶走）；
    表裡沒有就把天氣字眼前面那段當地名問 Open-Meteo（國外城市）。找不到回 None。"""
    t = text or ""
    for name in sorted(TAIWAN_PLACES, key=len, reverse=True):
        if name in t:
            return (name, *TAIWAN_PLACES[name])
    m = re.search(r"([一-鿿A-Za-z]{2,10}?)(?:市|縣)?(?:今天|明天|後天|這週末|週末|現在|最近)?的?" + WEATHER_WORDS.pattern, t)
    if not m:
        return None
    cand = re.sub(r"^(幫我|請|查一下|查查|查|看一下|看看|問一下|我想知道)+", "", m.group(1))
    cand = re.sub(r"(今天|明天|後天|這週末|週末|現在|最近)$", "", cand)
    if len(cand) < 2:
        return None
    try:
        res = _get("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {"name": cand, "count": 1, "language": "zh", "format": "json"})).get("results") or []
    except Exception as e:
        log_print(f"⚠️ [天氣] 地名查詢失敗（{cand}）：{str(e)[:60]}")
        return None
    if not res:
        return None
    return (res[0].get("name") or cand, float(res[0]["latitude"]), float(res[0]["longitude"]))


def is_weather_query(text: str) -> bool:
    return bool(WEATHER_WORDS.search(text or ""))


def forecast_text(text: str) -> str:
    """問天氣的句子 → 帶日期的預報幾行（給搜尋摘要用）；不是問天氣、找不到地名、查不到回空字串（呼叫端改走一般搜尋）。"""
    if not is_weather_query(text):
        return ""
    place = find_place(text)
    if not place:
        return ""
    name, lat, lon = place
    q = {"latitude": lat, "longitude": lon, "timezone": "Asia/Taipei", "forecast_days": 3,   # 日期照台灣算，國外城市的「明天」才跟老爸講的一樣
         "current": "temperature_2m,weather_code",
         "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}
    try:
        d = _get("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q))
    except Exception as e:
        log_print(f"⚠️ [天氣] Open-Meteo 查不到（{name}）：{str(e)[:60]}")
        return ""
    daily = d.get("daily") or {}
    lines = []
    cur = d.get("current") or {}
    if cur.get("temperature_2m") is not None:
        lines.append(f"- {name}現在 {cur['temperature_2m']:.0f} 度，{_CODES.get(cur.get('weather_code'), '')}"
                     f"（資料時間 {str(cur.get('time', ''))[5:16].replace('T', ' ')}）")
    for i, day in enumerate(daily.get("time") or []):
        try:
            dt = datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            continue
        label = ("今天", "明天", "後天")[i] if i < 3 else ""
        rain = (daily.get("precipitation_probability_max") or [None] * 3)[i]
        lines.append(f"- {name}{label} {dt.month}/{dt.day}（星期{_WEEK[dt.weekday()]}）："
                     f"{_CODES.get((daily.get('weather_code') or [None] * 3)[i], '')}，"
                     f"{daily['temperature_2m_min'][i]:.0f}～{daily['temperature_2m_max'][i]:.0f} 度"
                     + (f"，降雨機率 {rain}%" if rain is not None else ""))
    if lines:
        log_print(f"🌤️ [天氣] {name} 用 Open-Meteo 預報（{len(lines)} 行）")
    return "\n".join(lines)
