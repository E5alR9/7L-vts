# 🔁 Agent Loop 作戰手冊（整台 agent 化：TikTok 閒聊＋爸爸主腦）

## 開關（兩段式，預設全關）
- `AGENT_LOOP=1`：TikTok 閒聊走常駐 session。
- `AGENT_LOOP_DAD=1`：爸爸主腦也進迴路（整台 agent 化）。可單獨開，互不依賴。
- 日誌關鍵字：`🔁 [AgentLoop]`。沒看到 = 沒啟用，走舊鏈。

## 架構（爸爸迴路 = 前門快答＋旗艦代打）
- 爸爸 session（live 模型）：閒聊、問候、接梗直接回。
- 難題（代碼/除錯/推理）：調 `deep_think` → HTTP `gemini-3.8-flash` 旗艦梯隊（記憶30句＋歷史＋最新螢幕）→ session 轉述。
- Live 沒有 3.8，只有 live-preview 模型；旗艦品質靠 HTTP 後端保住，兩邊都要。
- 觀眾 session：閒聊＋點歌/鋼琴/搜尋工具直調。
- 轉世、打斷、回退機制同前。

## 測試矩陣（開台時照表打勾）
- [ ] 小號閒聊兩句 → 有 `🔁 session #N` 回覆，後台氣泡 model=`agent-loop-live`
- [ ] 發 `唱鐘` → 工具日誌出現，歌照唱，謝幕正常
- [ ] 老爸中途說話 → 迴路語音秒停，爸爸回覆先播
- [ ] 唱歌中彈幕 → 回覆排隊等唱完（不插歌）
- [ ] 刷屏 `666` → `[PASS]` 靜默，無語音
- [ ] `AGENT_LOOP_DAD=1` 後老爸閒聊 → `AgentLoop 爸爸回覆`，model=`agent-loop-dad`
- [ ] 老爸問難題（貼段報錯 code）→ `deep_think` 日誌＋旗艦答案轉述
- [ ] 回滾：拿掉變數重啟，舊鏈行為一致

## 回滾
- 拿掉 `AGENT_LOOP=1` / `AGENT_LOOP_DAD=1` 重啟 = 回舊鏈，零殘留。
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
- 離線測試：`python AppData\Local\Temp\opencode\test_agent_loop.py`（T1~T7 全綠才推）。
