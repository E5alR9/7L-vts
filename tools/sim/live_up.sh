#!/bin/bash
# 用模擬直播包裝開 7L：等 Live 連上、TTS 預熱、Roformer 載完；確認看不到螢幕；打開彈幕互動。
# 用法：bash tools/sim/live_up.sh 日誌名   （日誌在 SIM_LOG_DIR，預設 %TEMP%\vtslint）
SIM="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SIM/../.." && pwd)"
LOG_DIR="${SIM_LOG_DIR:-$TEMP/vtslint}"
mkdir -p "$LOG_DIR"
L="$LOG_DIR/$1"
cd "$ROOT"
# 先清掉上一輪殘留的模擬直播程序（只認 sim_run.py，不碰別的 python）
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*sim_run.py*' } | ForEach-Object { Write-Output ('清掉殘留 7L: ' + \$_.ProcessId); Stop-Process -Id \$_.ProcessId -Force }"
PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 nohup python -u "$SIM/sim_run.py" > "$L" 2>&1 &
for i in $(seq 1 240); do
  if grep -aq "Roformer 預載" "$L" 2>/dev/null && grep -aq "已成功連線至 Live API" "$L"; then echo "7L READY（約 ${i} 秒）"; break; fi
  if grep -aq "Traceback" "$L" 2>/dev/null; then echo "CRASH"; tail -c 3000 "$L"; exit 1; fi
  sleep 1
done
sleep 3
# 確認截圖入口真的換掉了、畫面快取是空的；沒擋住就關掉 7L
GUARD=$(PYTHONIOENCODING=utf-8 python "$SIM/ex.py" 'import services.screen_capture as sc
result = [sc.grab_screen.__name__, sc.gdi_capture_screen.__name__, len(getattr(m, "latest_screen_cache", "") or "")]' 2>&1)
if ! echo "$GUARD" | grep -q "'_no_screen', '_no_screen', 0"; then
  echo "❌ 截圖沒擋住，立刻關掉 7L：$GUARD"
  curl -s -m 5 -X POST http://127.0.0.1:7860/api/shutdown >/dev/null
  exit 1
fi
echo "🙈 截圖入口已擋、畫面快取是空的"
curl -s -m 10 -X POST http://127.0.0.1:7860/api/switches/toggle -H "Content-Type: application/json" -d '{"key":"IS_STREAM_CHAT_ENABLED","value":true}' -o /dev/null -w "彈幕開關 %{http_code}\n"
