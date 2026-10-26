#!/bin/bash
# 原生終端機開的模擬直播（tools/sim/native_up.bat）：等 7L 起來、確認看不到螢幕（沒擋住就立刻關掉）、打開彈幕互動。
SIM="$(cd "$(dirname "$0")" && pwd)"
for i in $(seq 1 300); do
  if curl -s -m 3 -o /dev/null http://127.0.0.1:7870/ && curl -s -m 3 -o /dev/null http://127.0.0.1:7860/; then
    echo "7L 測試埠有回應（約 ${i} 秒）"
    break
  fi
  sleep 1
done
GUARD=$(PYTHONIOENCODING=utf-8 python "$SIM/ex.py" 'import services.screen_capture as sc
result = [sc.grab_screen.__name__, sc.gdi_capture_screen.__name__, len(getattr(m, "latest_screen_cache", "") or "")]' 2>&1)
if ! echo "$GUARD" | grep -q "'_no_screen', '_no_screen', 0"; then
  echo "❌ 截圖沒擋住，立刻關掉 7L：$GUARD"
  curl -s -m 5 -X POST http://127.0.0.1:7860/api/shutdown >/dev/null
  exit 1
fi
echo "🙈 截圖入口已擋、畫面快取是空的"
curl -s -m 10 -X POST http://127.0.0.1:7860/api/switches/toggle -H "Content-Type: application/json" -d '{"key":"IS_STREAM_CHAT_ENABLED","value":true}' -o /dev/null -w "彈幕開關 %{http_code}\n"
