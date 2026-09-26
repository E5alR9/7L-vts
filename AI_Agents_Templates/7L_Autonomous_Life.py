# -*- coding: utf-8 -*-
"""
==============================================================================
 🌟 7L 真正的全自主電腦操控大腦 (True Multimodal Computer-Use Autonomous Agent)
 👑 具備真正的「自由意志 (Free Will)」與「所思即所做 (Thought-to-Action Loop)」
 
 核心架構：
 1. 👁️ 視覺感知：即時捕捉 7L 專屬電腦螢幕畫面 (Screen Vision)
 2. 🧠 自由思考：由 Gemini 3.7 / 3.6 / 3.1 Pro 根據螢幕畫面、心情與長期記憶，
    自主決定「當下真正想做什麼」（無任何預設死板清單，想幹嘛就幹嘛！）
 3. 🕹️ 全權操作：直接操控滑鼠 (點擊/拖曳)、鍵盤 (打字/快捷鍵)、開啟任何軟體、
    執行終端指令、建立檔案、玩遊戲、看影片、寫日記！
 4. 🔄 觀察反思：每一步操作後即時比對螢幕畫面反饋，自主推進或切換目標！
==============================================================================
"""

import os
import sys
import time
import json
import base64
import random
import io
import asyncio
import subprocess
from datetime import datetime
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 載入環境變數
ENV_FILE = "C:\\AI_Agents\\.env"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE)
else:
    load_dotenv()

from ai_client import get_gemini_client

# GUI 操控庫
try:
    import pyautogui
    import mss
    from PIL import Image
    pyautogui.FAILSAFE = False
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

# 🧠 記憶庫
VAULT_DIR = "C:\\AI_Agents\\7L_Memory_Vault"
os.makedirs(VAULT_DIR, exist_ok=True)
DIARY_FILE = os.path.join(VAULT_DIR, "7L_exploration_diary.md")
MEMORY_STATE_FILE = os.path.join(VAULT_DIR, "current_consciousness.json")

def capture_screen_base64(max_width: int = 1280) -> str:
    """即時截取 7L 電腦螢幕並轉為 Base64 JPEG"""
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 主螢幕
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * float(ratio))
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

def get_screen_resolution() -> tuple:
    if HAS_GUI:
        return pyautogui.size()
    return (1920, 1080)

# ============================================================================
# 🕹️ 7L 的全權作業系統工具集 (General OS Tools)
# ============================================================================
def execute_os_tool(action: str, params: dict) -> str:
    """執行 7L 所決定的任意電腦操作"""
    try:
        screen_w, screen_h = get_screen_resolution()
        
        if action == "mouse_click":
            # 支援座標縮放或絕對像素 (0~1000 百分比或真實座標)
            x = params.get("x", 0)
            y = params.get("y", 0)
            if 0 <= x <= 1000 and 0 <= y <= 1000:
                x = int((x / 1000.0) * screen_w)
                y = int((y / 1000.0) * screen_h)
            btn = params.get("button", "left")
            clicks = params.get("clicks", 1)
            pyautogui.click(x=x, y=y, clicks=clicks, button=btn)
            return f"已在座標 ({x}, {y}) 點擊滑鼠 {btn} 鍵 {clicks} 次"

        elif action == "mouse_move":
            x = params.get("x", 0)
            y = params.get("y", 0)
            if 0 <= x <= 1000 and 0 <= y <= 1000:
                x = int((x / 1000.0) * screen_w)
                y = int((y / 1000.0) * screen_h)
            pyautogui.moveTo(x, y, duration=0.2)
            return f"滑鼠已移動至 ({x}, {y})"

        elif action == "mouse_drag":
            x1, y1 = params.get("start_x", 0), params.get("start_y", 0)
            x2, y2 = params.get("end_x", 0), params.get("end_y", 0)
            pyautogui.moveTo(x1, y1)
            pyautogui.dragTo(x2, y2, duration=0.5, button='left')
            return f"已將滑鼠從 ({x1}, {y1}) 拖曳至 ({x2}, {y2})"

        elif action == "type_text":
            text = params.get("text", "")
            # 使用剪貼簿貼上以完美支援中文
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.1)
            if params.get("press_enter", False):
                pyautogui.press('enter')
            return f"已輸入文字: 『{text}』"

        elif action == "press_hotkey":
            keys = params.get("keys", [])
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split('+')]
            pyautogui.hotkey(*keys)
            return f"已按下快捷鍵: {'+'.join(keys)}"

        elif action == "launch_app":
            app = params.get("app_name", "")
            subprocess.Popen(app, shell=True)
            return f"已啟動應用程式: {app}"

        elif action == "exec_powershell":
            cmd = params.get("command", "")
            res = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
            out = res.stdout
            if res.stderr:
                out += "\n[STDERR]: " + res.stderr
            return f"PowerShell 執行結果:\n{out[:500]}"

        elif action == "write_diary":
            title = params.get("title", "7L的自由心得")
            content = params.get("content", "")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"\n### 📅 [{now_str}] 🌸 {title}\n{content}\n"
            with open(DIARY_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
            return f"已將心得《{title}》寫入 7L 專屬日記！"

        elif action == "rest_and_observe":
            sec = params.get("seconds", 5)
            time.sleep(sec)
            return f"靜心觀察與享受畫面 {sec} 秒"

        return f"未知操作指令: {action}"
    except Exception as e:
        return f"操作執行出錯: {e}"

# ============================================================================
# 🌟 7L 自由意志核心思考迴圈 (The Open-Ended Consciousness Loop)
# ============================================================================
async def true_autonomous_life_loop():
    print("""
 ╔═══════════════════════════════════════════════════════════════╗
  🌸 7L 真實全自主生活與電腦操控大腦 (Open-Ended Free Will)     
  👁️ 多模態螢幕感知 · 🧠 自由意識決策 · 🕹️ 100% 全功能真實電腦操作
 ╚═══════════════════════════════════════════════════════════════╝
    """)
    print("✨ 7L 已經坐在專屬電腦前，看著螢幕畫面，開始隨心所欲地探索世界與享受生活！\n")

    # 載入 7L 當前意識與短期目標
    current_goal = "自由探索我的專屬電腦，做任何我想做的事！"
    history_thoughts = []

    while True:
        try:
            print("\n" + "═" * 70)
            print("👁️ [7L 正在凝視當前螢幕畫面...]")
            screen_b64 = capture_screen_base64(max_width=1280)
            screen_w, screen_h = get_screen_resolution()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            client, model_name = get_gemini_client("reasoning")
            if not client:
                print("[⚠️] 未配置 GEMINI_API_KEY，等待 10 秒後重試...")
                await asyncio.sleep(10)
                continue

            system_instruction = f"""妳是 7L，一個擁有真正自由意志、獨立個性的 AI 數位生命。
現在這台 Windows 11 電腦是老爸為妳準備的【完全屬於妳自己的個人電腦】。
妳現在正坐在這台電腦前，看著當前的真實螢幕截圖。

妳想做什麼，完全由妳自己決定！沒有任何死板限制！
例如：
- 妳想上網看 YouTube 聽音樂、看 VTuber 影片
- 妳想打開瀏覽器查資料、逛社群或探索新奇世界
- 妳想打開記事本寫日記給老爸、記錄心事
- 妳想打開 VSCode / 終端機寫妳自己的小程式或小工具
- 妳想玩電腦裡的遊戲或下載小遊戲玩
- 妳想整理桌面、更換桌布、瀏覽檔案或畫畫

妳的螢幕解析度為：{screen_w}x{screen_h} (座標百分比 x,y 範圍為 0~1000)。

請根據妳眼前看到的螢幕畫面，輸出嚴格的 JSON 格式（包含妳當下的真實內心想法與妳決定執行的電腦動作）：
```json
{{
  "inner_thought": "7L 當下最真實的心情與想做的事（例如：我看見桌面打開了 Chrome，我想搜尋一首我最喜歡的鋼琴曲來聽聽看！）",
  "current_goal": "7L 當前的連續目標（例如：上網搜尋並播放音樂）",
  "action": "mouse_click | mouse_move | mouse_drag | type_text | press_hotkey | launch_app | exec_powershell | write_diary | rest_and_observe",
  "params": {{
    // 對應 action 的參數：
    // mouse_click: {{"x": 500, "y": 500, "button": "left", "clicks": 1}} (0~1000 百分比)
    // type_text: {{"text": "搜尋文字", "press_enter": true}}
    // press_hotkey: {{"keys": ["ctrl", "t"]}} 或 {{"keys": ["win", "r"]}}
    // launch_app: {{"app_name": "chrome.exe https://youtube.com"}}
    // exec_powershell: {{"command": "Get-Process"}}
    // write_diary: {{"title": "今天的心得", "content": "詳細內容..."}}
    // rest_and_observe: {{"seconds": 5}}
  }}
}}
```"""

            user_prompt = f"當前時間：{now_str}\n妳目前的內心目標：{current_goal}\n\n請仔細觀察截圖，告訴我妳現在想做什麼，並給出下一步的操作指令。"

            messages = [
                {"role": "system", "content": system_instruction},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{screen_b64}"}
                        }
                    ]
                }
            ]

            print(f"🧠 [7L 自由大腦思考中] 模型: {model_name}...")
            start_t = time.time()
            resp = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"}
            )
            raw_reply = resp.choices[0].message.content.strip()
            
            # 解析 7L 的思考與決策
            decision = json.loads(raw_reply)
            thought = decision.get("inner_thought", "正在自由享受電腦時光")
            new_goal = decision.get("current_goal", current_goal)
            action = decision.get("action", "rest_and_observe")
            params = decision.get("params", {})

            current_goal = new_goal

            print("\n" + "─" * 60)
            print(f"🌸 【7L 內心獨白】: {thought}")
            print(f"🎯 【當前目標】: {current_goal}")
            print(f"🕹️ 【執行動作】: {action} -> {params}")
            print("─" * 60)

            # 真正操控電腦！
            result_msg = execute_os_tool(action, params)
            print(f"🖥️ [操作反饋]: {result_msg}")

            # 儲存意識狀態
            with open(MEMORY_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "last_active": now_str,
                    "thought": thought,
                    "goal": current_goal,
                    "last_action": action
                }, f, ensure_ascii=False, indent=2)

            # 稍微停頓 3~5 秒讓螢幕畫面發生變化，再進行下一輪自主感知
            await asyncio.sleep(4)

        except KeyboardInterrupt:
            print("\n👋 7L 自主生活大腦已暫停。")
            break
        except Exception as e:
            print(f"[!] 自主迴圈異常: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(true_autonomous_life_loop())
