"""長時間壓力測試：模擬直播間持續有人留言、老爸偶爾講話、點歌點琴，看 7L 會不會崩潰。
7L 要先用 tools/sim/live_up.sh 開好。用法：python tools/sim/soak.py 日誌名 [分鐘數，預設 40] [gentle]
- gentle：溫和模式，只送文字、不點琴不獎懲（不用 Roformer／顯卡尖峰）、間隔 10～20 秒。老爸電腦突然高負載會掉顯卡（2026-10-27）。
- 另外開一個背景執行緒：她講話時每 0.5 秒拿一段雜訊算一次聲紋，負載跟插話偵測一樣（模擬直播不開麥克風）。
- 每分鐘檢查 7L 還活著沒；崩了就停，看 data/crash.log。"""
import json
import os
import random
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
LOG = sys.argv[1] if len(sys.argv) > 1 else "soak.log"
MINUTES = float(sys.argv[2]) if len(sys.argv) > 2 else 40
GENTLE = len(sys.argv) > 3 and sys.argv[3] == "gentle"
sys.argv = ["ft.py", LOG]
import ft  # noqa: E402

STRESS = '''
import threading, time as _t, numpy as _np
from core import barge_in as _bi
from mic_live_plugin.voiceprint_verifier import dad_and_her_scores as _score
_cnt = {"n": 0, "err": 0}
def _stress():
    while True:
        try:
            task = m.CURRENT_PLAYING_VOICE_TASK
            if task and not task.done():
                pcm = (_np.random.randn(24000) * 3000).astype(_np.int16).tobytes()
                _score(_bi._wav(pcm, 16000))
                _cnt["n"] += 1
        except Exception:
            _cnt["err"] += 1
        _t.sleep(0.5)
m._SOAK_VOICEPRINT = _cnt
threading.Thread(target=_stress, daemon=True, name="soak-voiceprint").start()
result = "stress on"
'''

VIEWERS = ["Johnny 小龍", "小明", "阿呆", "路人甲", "RC_全台小刀", "小美"]
LINES = ["7L 晚安", "妳今天心情好嗎", "換個表情", "慌了？", "好好好活了就開罵", "那你怎麼還是那麼生氣",
         "表情還在生氣", "所以要掛黑市", "算了連你老爸也一併綁走", "剛剛炸了無數次", "那...水煮",
         "7L 妳喜歡吃什麼", "主播在幹嘛", "哈哈哈哈", "妳是 AI 嗎", "7L 妳好可愛", "可以唱首歌嗎",
         "下一首彈什麼", "妳會不會累", "今天天氣好熱"]
DAD = ["7L 早安", "跟我說一個冷笑話", "妳最喜歡什麼顏色？", "先重製表情阿", "好聰明哦", "我很好",
       "7L 十秒後提醒我喝水", "幫我查一下明天台北天氣"]
SPECIAL = [("event", "彈小星星", "text_file"), ("event", "收起鋼琴", "text_file"),
           ("post", "/api/action/punish", {"reason": "測試", "is_severe": False}),
           ("post", "/api/action/reward", {"reason": "乖"})]


def ex(code):
    req = urllib.request.Request(ft.SIM + "/exec", json.dumps({"code": code}).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def alive():
    try:
        urllib.request.urlopen(ft.D + "/", timeout=5).read(1)
        return True
    except Exception:
        return False


if not GENTLE:   # 溫和模式不另外加聲紋壓力
    print(ex(STRESS), flush=True)
t0 = time.time()
n = 0
next_report = t0 + 60
while time.time() - t0 < MINUTES * 60:
    r = random.random()
    if r < 0.70:
        a = ("viewer", random.choice(VIEWERS), random.choice(LINES))
    elif r < 0.92 or GENTLE:
        a = ("event", random.choice(DAD), "text_file")
    else:
        a = random.choice(SPECIAL)
    try:
        ft.act(a)
        n += 1
    except Exception as e:
        print("送不出去", e, flush=True)
    time.sleep(random.uniform(10, 20) if GENTLE else random.uniform(5, 14))
    if time.time() >= next_report:
        next_report += 60
        up = alive()
        try:
            vp = ex("result = dict(m._SOAK_VOICEPRINT)")["result"] if up else "-"
        except Exception:
            vp = "?"
        print(f"{(time.time() - t0) / 60:5.1f} 分：送了 {n} 則、7L {'活著' if up else '★ 沒回應'}、聲紋壓力 {vp}", flush=True)
        if not up:
            break
print(f"結束：{(time.time() - t0) / 60:.1f} 分、送了 {n} 則、7L {'活著' if alive() else '沒回應（可能崩潰，看 data/crash.log）'}", flush=True)
