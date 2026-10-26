#!/bin/bash
# 跑完整測試：印最後一行，失敗的列出來；回傳 pytest 的結束碼（0 才算過）。
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${SIM_LOG_DIR:-$TEMP/vtslint}/pytest_last.log"
mkdir -p "$(dirname "$OUT")"
cd "$ROOT"
timeout 900 python -m pytest tests -q -p no:cacheprovider > "$OUT" 2>&1
rc=$?
tail -1 "$OUT"
[ $rc -ne 0 ] && grep -a "^FAILED\|^ERROR" "$OUT" | head -10
exit $rc
