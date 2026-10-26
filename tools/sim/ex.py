"""在模擬直播的 7L 主迴圈裡跑一段程式：python tools/sim/ex.py '程式'（設 result 變數回傳；m＝主程式模組）。"""
import json
import sys
import urllib.request

code = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
req = urllib.request.Request("http://127.0.0.1:7870/exec", json.dumps({"code": code}).encode(),
                             {"Content-Type": "application/json"})
print(json.loads(urllib.request.urlopen(req, timeout=70).read()))
