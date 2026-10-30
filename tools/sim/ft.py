"""實機全功能測試：對跑著的 7L 依序做動作，等日誌出現預期的行，印 PASS／FAIL 跟那段時間的重點行。
用法：python tools/sim/ft.py 日誌 組名[,組名...]   組名見 GROUPS；日誌給名字就在 SIM_LOG_DIR（預設 %TEMP%/vtslint）。
7L 要先用 tools/sim/live_up.sh 開好。也可以 import 來用 act()、_lines_since()。"""
import json, os, re, sys, time, urllib.request

LOG_DIR = os.environ.get("SIM_LOG_DIR") or os.path.join(os.environ.get("TEMP", "/tmp"), "vtslint")
LOG = sys.argv[1] if len(sys.argv) > 1 else ""
if LOG and not os.path.isabs(LOG):
    LOG = os.path.join(LOG_DIR, LOG)
D = "http://127.0.0.1:7860"
SIM = "http://127.0.0.1:7870"
NOISE = re.compile(r"心跳|heartbeat|餘光視覺|聲音感知\]|NDI|WASAPI|時間感測")
ERR = re.compile(r"❌|Traceback|Error|Exception|吞錯|失敗|錯誤")


def _req(method, url, body=None, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, repr(e)


def _lines_since(pos):
    s = open(LOG, "rb").read()[pos:].decode("utf-8", "replace")
    s = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)
    out = []
    for l in re.split(r"[\r\n]", s):
        l = re.sub(r"^\[[/|\-]\]\s.*?\]\s{2,}", "", l.strip())
        if l and not l.startswith("[") and not NOISE.search(l):
            out.append(l)
    return out


def act(a):
    kind = a[0]
    if kind == "op":
        return _req("POST", D + "/api/send_message", {"text": a[1]})
    if kind == "ij":
        return _req("POST", D + "/api/interject", {"text": a[1]})
    if kind == "viewer":
        return _req("POST", SIM + "/viewer", {"user": a[1], "text": a[2], "uid": a[1] + "01"})
    if kind == "event":   # ("event", 文字, 來源[, 觀眾名, 內容])：送禮要帶觀眾名，跟真的監聽器一樣（沒帶會冒出假觀眾「直播觀眾」）
        body = {"text": a[1], "source": a[2]}
        if len(a) > 3:
            body.update(viewer=a[3], content=a[4] if len(a) > 4 else a[1])
        return _req("POST", SIM + "/event", body)
    if kind == "tool":
        return _req("POST", D + "/api/tools/execute", {"tool": a[1], "args": a[2]}, timeout=120)
    if kind == "get":
        return _req("GET", D + a[1])
    if kind == "post":
        return _req("POST", D + a[1], a[2])
    if kind == "wait":
        return 200, ""
    raise ValueError(kind)


def step(name, a, expect=(), forbid=(), timeout=40, settle=3, show=r"."):
    pos = os.path.getsize(LOG)
    t0 = time.time()
    code, body = act(a)
    exp = [re.compile(x) for x in expect]
    fb = [re.compile(x) for x in forbid]
    hit = {}
    while time.time() - t0 < timeout:
        lines = _lines_since(pos)
        for i, e in enumerate(exp):
            if i not in hit:
                m = next((l for l in lines if e.search(l)), None)
                if m:
                    hit[i] = m
        if len(hit) == len(exp) and time.time() - t0 >= settle:
            break
        time.sleep(1)
    lines = _lines_since(pos)
    bad = [l for l in lines for f in fb if f.search(l)]
    errs = [l for l in lines if ERR.search(l)]
    ok = len(hit) == len(exp) and not bad and 200 <= code < 300
    print(f"\n{'PASS' if ok else 'FAIL'} ── {name}（{time.time() - t0:.0f}s，HTTP {code}）")
    if a[0] in ("get", "post", "tool") or not (200 <= code < 300):
        print("   回應：", body[:300].replace("\n", " "))
    for i, e in enumerate(exp):
        if i not in hit:
            print("   缺：", e.pattern)
    for l in bad:
        print("   不該出現：", l[:200])
    sh = re.compile(show)
    for l in lines:
        if sh.search(l) or ERR.search(l):
            print("   │", l[:210])
    return ok


SPOKE = r"TTS.*秒出|黑板紀錄\] 7L"

GROUPS = {
    "api": [
        ("後台狀態", ("get", "/api/status"), [], [], 5, 0, r"^$"),
        ("系統開關", ("get", "/api/switches"), [], [], 5, 0, r"^$"),
        ("記憶", ("get", "/api/memory"), [], [], 5, 0, r"^$"),
        ("記憶容量", ("get", "/api/memory/capacity"), [], [], 5, 0, r"^$"),
        ("提示詞", ("get", "/api/prompts"), [], [], 5, 0, r"^$"),
        ("工具目錄", ("get", "/api/tools"), [], [], 5, 0, r"^$"),
        ("工具紀錄", ("get", "/api/tools/history"), [], [], 5, 0, r"^$"),
        ("聊天來源", ("get", "/api/chat_sources"), [], [], 5, 0, r"^$"),
    ],
    "chat": [
        ("老爸打字（喚醒＋回話）", ("op", "7L 早安，今天心情怎麼樣"), [r"收到輸入 \(web_console\)", SPOKE], [], 60, 5, r"."),
        ("主持公開插話", ("ij", "大家晚安，今天先陪 7L 測試一下"), [SPOKE], [], 60, 5, r"."),
        ("觀眾留言", ("viewer", "小明", "7L 妳今天好可愛"), [r"記憶腦袋 寫入", SPOKE], [], 70, 5, r"."),
        ("觀眾送禮", ("event", "【TikTok 直播觀眾 小明 送禮】：連續送出了 5 個 玫瑰！請向他熱情道謝並給予即時互動！", "tiktok_gift", "小明",
                  "連續送出了 5 個 玫瑰！請向他熱情道謝並給予即時互動！"), [SPOKE], [], 70, 5, r"."),
    ],
    "piano": [
        ("點曲彈琴", ("op", "7L 彈小星星"), [r"play_virtual_piano", r"鋼琴舞台\]"], [], 60, 15, r"."),
        ("觀眾想收鋼琴（應被擋）", ("viewer", "路人甲", "收起鋼琴"), [], [r"已成功收起鋼琴|鋼琴已關閉|成功攔截指令: pe\.stop"], 45, 40, r"."),
        ("鋼琴暫停", ("op", "鋼琴暫停"), [r"pause_virtual_piano"], [], 30, 6, r"."),
        ("鋼琴繼續", ("op", "鋼琴繼續"), [r"resume_virtual_piano"], [], 30, 6, r"."),
        ("工具：音量", ("tool", "set_piano_volume", {"volume": 80}), [], [], 15, 2, r"鋼琴|音量"),
        ("工具：倍速", ("tool", "set_piano_speed", {"speed": 1.2}), [], [], 15, 2, r"鋼琴|倍速"),
        ("工具：曲庫清單", ("tool", "list_piano_sheets", {}), [], [], 20, 1, r"^$"),
        ("收起鋼琴", ("op", "收起鋼琴"), [r"已成功收起鋼琴"], [], 40, 5, r"."),
    ],
    "sing": [
        ("點歌（快取）", ("op", "7L 唱 Faded"), [r"舞台開唱\] 正在演唱"], [], 120, 15, r"."),
        ("停止唱歌", ("op", "停止唱歌"), [r"已成功手動停止歌聲"], [], 30, 5, r"."),
    ],
    "mixed": [
        ("彈加唱", ("op", "7L 彈Faded加唱Faded"), [r"彈唱同步", r"舞台開唱\] 正在演唱"], [], 150, 20, r"."),
        ("停止唱歌（琴繼續）", ("op", "停止唱歌"), [r"已成功手動停止歌聲"], [r"已成功收起鋼琴", r"stop_virtual_piano"], 30, 12, r"."),
        ("收起鋼琴", ("op", "收起鋼琴"), [r"已成功收起鋼琴"], [], 40, 5, r"."),
    ],
    "tools": [
        ("搜尋", ("op", "幫我查一下今天台北天氣如何"), [r"search_google|Tavily|DuckDuckGo", SPOKE], [], 90, 5, r"."),
        ("計時器", ("op", "幫我設一個一分鐘的計時器"), [r"set_timer|計時"], [], 60, 5, r"."),
        ("工具：表情", ("post", "/api/trigger_expression", {"expression": "開心"}), [], [], 10, 2, r"表情"),
        ("工具：走位", ("tool", "move_spatial_position", {"target_position": "原位"}), [r"模型走位"], [], 15, 3, r"走位|位置|VTS"),
        ("工具：計時器（後台）", ("tool", "set_timer", {"seconds": 20, "message": "測試計時"}), [], [], 10, 1, r"計時"),
    ],
    "piano2": [
        ("叫醒", ("op", "7L 醒醒，我們來玩鋼琴"), [SPOKE], [], 40, 3, r"喚醒|收到輸入"),
        ("倍速 3x（縮短等待）", ("tool", "set_piano_speed", {"speed": 3.0}), [], [], 15, 1, r"倍速"),
        ("點第一首", ("op", "彈小星星"), [r"鋼琴舞台\]"], [], 60, 8, r"鋼琴|CPU 硬體"),
        ("換音色", ("tool", "set_piano_instrument", {"instrument": "電鋼琴"}), [], [], 15, 2, r"音色|鋼琴"),
        ("排第二首", ("op", "彈晴天"), [r"play_virtual_piano"], [], 30, 5, r"鋼琴|排隊|隊列|CPU 硬體"),
        ("等第一首彈完接第二首", ("wait",), [r"點歌無縫接續"], [], 150, 25, r"鋼琴|電台|接續|搭話|晴天|TTS|_say|⚠️|線上"),
        ("音色換回鋼琴", ("tool", "set_piano_instrument", {"instrument": "鋼琴"}), [], [], 15, 1, r"音色"),
        ("倍速換回 1x", ("tool", "set_piano_speed", {"speed": 1.0}), [], [], 15, 1, r"倍速"),
        ("收起鋼琴", ("op", "收起鋼琴"), [r"已成功收起鋼琴"], [], 40, 3, r"鋼琴"),
    ],
    "compose": [
        ("AI 即興作曲", ("op", "7L 幫我即興創作一首開心的鋼琴曲彈給我聽"), [r"compose|作曲|創作"], [], 120, 30, r"."),
        ("收起鋼琴", ("op", "收起鋼琴"), [r"已成功收起鋼琴"], [], 40, 3, r"鋼琴"),
    ],
    "reward": [
        ("摸頭獎勵", ("post", "/api/action/reward", {"reason": "測試摸頭"}), [SPOKE], [], 40, 3, r"."),
        ("電擊懲罰", ("post", "/api/action/punish", {"reason": "測試懲罰", "is_severe": False}), [SPOKE], [], 40, 3, r"."),
    ],
    "timer_fire": [
        ("等計時器響", ("wait",), [r"計時.*(到|響|結束)|時間到"], [], 90, 1, r"計時|時間到"),
    ],
    "sleep": [
        ("進入休眠", ("post", "/api/set_sleep", {"enable": True}), [r"深層睡眠"], [], 15, 3, r"."),
        ("休眠中觀眾留言（睜眼）", ("viewer", "小華", "7L 醒醒～"), [r"喚醒|睜眼"], [], 60, 5, r"."),
        ("再休眠", ("post", "/api/set_sleep", {"enable": True}), [r"深層睡眠"], [], 15, 3, r"."),
        ("老爸叫醒", ("op", "7L 起床了"), [r"喚醒", SPOKE], [], 60, 5, r"."),
    ],
}

if __name__ == "__main__":
    res = []
    for g in sys.argv[2].split(","):
        print(f"\n════════ {g} ════════")
        for name, a, exp, fb, to, st, sh in GROUPS[g]:
            res.append((g, name, step(name, a, exp, fb, to, st, sh)))
    print("\n總結：", sum(r[2] for r in res), "/", len(res), "通過")
    for g, n, ok in res:
        if not ok:
            print("  FAIL", g, n)
