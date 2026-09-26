# 🔁 Agent Loop 作戰手冊（TikTok 閒聊常駐迴路）

## 開關
- 預設關。啟用：環境變數 `AGENT_LOOP=1` 後重啟主程式。
- 日誌關鍵字：`🔁 [AgentLoop]`。沒看到 = 沒啟用，走舊看板。

## 架構（4 階段全上線）
1. 常駐 Live session（`gemini-3.1-flash-live-preview`），同 session 連聊，不重送 prompt。
2. 工具直調：`auto_sing_song / pe.play_virtual_piano / search_google` 等（觀眾安全表），結果餵回 session 組口語。
3. 30 輪或記錄破萬字 → `3.5-lite` 壓 3 行摘要 → 統一記憶＋下世 `【前情提要】`。
4. 爸爸主腦一開工就 cancel 迴路語音（打斷），爸爸回覆照常排入。

## 測試矩陣（開台時照表打勾）
- [ ] 小號閒聊兩句 → 有 `🔁 session #N` 回覆，後台氣泡 model=`agent-loop-live`
- [ ] 發 `唱鐘` → 工具日誌出現，歌照唱，謝幕正常
- [ ] 老爸中途說話 → 迴路語音秒停，爸爸回覆先播
- [ ] 唱歌中彈幕 → 回覆排隊等唱完（不插歌）
- [ ] 刷屏 `666` → `[PASS]` 靜默，無語音

## 回滾
- 拿掉 `AGENT_LOOP=1` 重啟 = 回舊鏈，零殘留。
- 本機分支：`master` 可開播版；`agent-loop` 施工版；`github-clean` 鏡像線（給 GitHub/Jules）。

## 鏡像同步（給 Jules 看的 GitHub）
```bat
git checkout github-clean
git checkout agent-loop -- services/agent_loop.py vts_7L_test.py
git commit -m "mirror agent-loop ..."
git push origin github-clean:master
git checkout agent-loop
```

## 已知限制
- Live 端工具超時 30 秒；鋼琴/搜尋正常在 10 秒內。
- `send_tool_response` 綁定 google-genai SDK 現行簽名，升級 SDK 後需重驗（跑離線測試）。
- 轉世摘要失敗就裸重開（前情丟失，閒聊可接受）。
- 離線測試：`python AppData\Local\Temp\opencode\test_agent_loop.py`（T1~T5 全綠才推）。
