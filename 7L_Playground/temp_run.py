import urllib.request
import json

# 呼叫停止唱歌的 API
try:
    req = urllib.request.Request('http://127.0.0.1:7860/stop_singing', method='POST')
    with urllib.request.urlopen(req) as response:
        print(response.read().decode())
except Exception as e:
    print(e)
