"""
Gemini Desktop Windows Automation Controller
============================================
用於自動化操作 Windows 桌面版 Google Gemini 官方應用程式 (Electron / UIAutomation)。

功能支援：
1. 自動偵測與連接 Gemini 桌面版視窗
2. 支援從背景／服務程序透過 OpenInputDesktop / SetThreadDesktop 跨桌面綁定操作
3. 透過 Windows UIAutomation 直接將提示詞寫入輸入框（無需暴力搶佔剪貼簿）
4. 自動點擊「傳送訊息」按鈕
5. 監控串流輸出，等待 Gemini 生成完畢並自動獲取最新回覆
6. 取得完整對話紀錄
"""

import sys
import time
import ctypes
from ctypes import wintypes
from typing import List, Dict, Optional, Tuple

import uiautomation as auto

# 確保輸出支援 UTF-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class GeminiDesktopController:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.hwnd: Optional[int] = None
        self.window_ctrl: Optional[auto.WindowControl] = None
        self._attach_input_desktop()

    def _attach_input_desktop(self) -> bool:
        """如果當前程序在後台或沒有交互桌面權限，嘗試綁定到當前活動桌面 (WinSta0\\default)。"""
        try:
            h_input_desk = self.user32.OpenInputDesktop(0, False, 0x01FF)  # GENERIC_ALL
            if h_input_desk:
                self.user32.SetThreadDesktop(h_input_desk)
                return True
        except Exception:
            pass
        return False

    def find_window(self) -> Optional[int]:
        """搜尋桌面版 Gemini 視窗 (Class: Chrome_WidgetWin_1, Title: Gemini)。"""
        self._attach_input_desktop()
        h_desk = self.user32.OpenDesktopW("default", 0, False, 0x01FF)

        target_hwnd = None
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_desk_proc(hwnd, lparam):
            nonlocal target_hwnd
            buff = ctypes.create_unicode_buffer(512)
            self.user32.GetWindowTextW(hwnd, buff, 512)
            cls_buff = ctypes.create_unicode_buffer(512)
            self.user32.GetClassNameW(hwnd, cls_buff, 512)
            if buff.value == "Gemini" and cls_buff.value == "Chrome_WidgetWin_1":
                target_hwnd = hwnd
            return 1

        cb = WNDENUMPROC(enum_desk_proc)
        self.user32.EnumDesktopWindows(h_desk, cb, 0)

        if target_hwnd:
            self.hwnd = target_hwnd
            self.window_ctrl = auto.ControlFromHandle(target_hwnd)
            return target_hwnd
        return None

    def ensure_connected(self):
        """確保已成功連線到 Gemini 視窗。"""
        if not self.hwnd or not self.user32.IsWindow(self.hwnd):
            hwnd = self.find_window()
            if not hwnd:
                raise RuntimeError("找不到執行中的桌面版 Gemini 視窗！請先開啟 Gemini 應用程式。")

    def show_window(self):
        """將 Gemini 視窗還原並置於前台。"""
        self.ensure_connected()
        self.user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
        self.user32.SetForegroundWindow(self.hwnd)
        self.user32.BringWindowToTop(self.hwnd)

    def get_input_field(self) -> auto.EditControl:
        """取得對話輸入框控制項。"""
        self.ensure_connected()
        edit_ctrl = self.window_ctrl.EditControl()
        if not edit_ctrl.Exists(2):
            raise RuntimeError("找不到 Gemini 輸入框控制項！")
        return edit_ctrl

    def set_prompt_text(self, text: str):
        """將提示詞寫入輸入框。"""
        edit_ctrl = self.get_input_field()
        legacy = edit_ctrl.GetLegacyIAccessiblePattern()
        if legacy:
            legacy.SetValue(text)
        else:
            val_pat = edit_ctrl.GetValuePattern()
            if val_pat:
                val_pat.SetValue(text)
            else:
                edit_ctrl.SendKeys(text)

    def get_send_button(self) -> Optional[auto.ButtonControl]:
        """尋找「傳送訊息」按鈕。"""
        self.ensure_connected()
        btn = self.window_ctrl.ButtonControl(Name='傳送訊息')
        if btn.Exists(1):
            return btn
        # 若語言或名稱不同，搜尋輸入區域周圍按鈕
        edit_ctrl = self.get_input_field()
        p = edit_ctrl
        for _ in range(6):
            p = p.GetParentControl()
            if not p:
                break
            for child in p.GetChildren():
                if child.ControlTypeName == 'ButtonControl' and ('傳送' in child.Name or 'Send' in child.Name):
                    return child
        return None

    def send_prompt(self, text: str):
        """填入提示詞並點擊發送按鈕。"""
        self.set_prompt_text(text)
        time.sleep(0.3)

        send_btn = self.get_send_button()
        if send_btn and send_btn.Exists(1):
            pat = send_btn.GetInvokePattern()
            if pat:
                pat.Invoke()
            else:
                send_btn.Click()
            return True

        # 若按鈕未啟用，嘗試發送 Enter 鍵
        edit_ctrl = self.get_input_field()
        edit_ctrl.SendKeys('{Enter}')
        return True

    def _get_chat_container(self) -> Optional[auto.Control]:
        """尋找對話容器節點。"""
        edit_ctrl = self.get_input_field()
        p = edit_ctrl
        for _ in range(12):
            p = p.GetParentControl()
            if not p:
                break
            for child in p.GetChildren():
                if 'chat-history' in child.ClassName:
                    return child
        return None

    def _collect_text_nodes(self, node: auto.Control) -> List[str]:
        """遞迴收集容器中的所有 TextControl 內容。"""
        results = []
        if node.ControlTypeName == 'TextControl' and node.Name:
            txt = node.Name.strip()
            if txt:
                results.append(txt)
        for child in node.GetChildren():
            results.extend(self._collect_text_nodes(child))
        return results

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """
        取得目前的完整對話紀錄列表。
        回傳格式：[{'role': 'user'|'gemini', 'content': '...'}, ...]
        """
        self.ensure_connected()
        container = self._get_chat_container()
        if not container:
            return []

        all_texts = self._collect_text_nodes(container)
        turns = []
        current_role = None
        current_lines = []

        for t in all_texts:
            if t.startswith("你說了"):
                if current_role and current_lines:
                    turns.append({"role": current_role, "content": "\n".join(current_lines)})
                current_role = "user"
                current_lines = []
                rest = t[len("你說了"):].strip()
                if rest:
                    current_lines.append(rest)
            elif t.startswith("Gemini 說了"):
                if current_role and current_lines:
                    turns.append({"role": current_role, "content": "\n".join(current_lines)})
                current_role = "gemini"
                current_lines = []
            else:
                if current_role and t not in current_lines:
                    current_lines.append(t)

        if current_role and current_lines:
            turns.append({"role": current_role, "content": "\n".join(current_lines)})

        return turns

    def get_last_response(self) -> Optional[str]:
        """取得 Gemini 的最後一則回覆內容。"""
        history = self.get_conversation_history()
        for msg in reversed(history):
            if msg["role"] == "gemini":
                return msg["content"]
        return None

    def ask(self, prompt: str, timeout: float = 60.0, poll_interval: float = 0.8) -> str:
        """
        傳送問題並等待 Gemini 完成生成回覆。

        :param prompt: 想詢問的提示詞
        :param timeout: 最長等待秒數
        :param poll_interval: 輪詢間隔秒數
        :return: Gemini 回覆的文字內容
        """
        self.ensure_connected()
        history_before = self.get_conversation_history()
        initial_gemini_count = sum(1 for m in history_before if m["role"] == "gemini")

        # 發送提示詞
        self.send_prompt(prompt)

        start_time = time.time()
        last_text = ""
        stable_count = 0

        # 等待回覆出現且生成完畢（文字穩定不變超過 2 次輪詢）
        while time.time() - start_time < timeout:
            time.sleep(poll_interval)
            history = self.get_conversation_history()
            gemini_msgs = [m for m in history if m["role"] == "gemini"]

            if len(gemini_msgs) > initial_gemini_count:
                current_text = gemini_msgs[-1]["content"]
                if current_text:
                    if current_text == last_text:
                        stable_count += 1
                        # 連續兩次文字未變化，視為回答完畢
                        if stable_count >= 2:
                            return current_text
                    else:
                        last_text = current_text
                        stable_count = 0

        if last_text:
            return last_text
        raise TimeoutError("等待 Gemini 回覆逾時！")


if __name__ == "__main__":
    controller = GeminiDesktopController()
    print("正在尋找桌面版 Gemini 視窗...")
    hwnd = controller.find_window()
    if not hwnd:
        print("未偵測到 Gemini 桌面版，請先啟動程式。")
        sys.exit(1)

    print(f"成功連接 Gemini 視窗 (HWND: {hex(hwnd)})")
    question = "請用一句話總結台灣的特色美食。"
    print(f"\n發送提問: {question}")
    
    try:
        answer = controller.ask(question, timeout=30.0)
        print(f"\n--- Gemini 回覆結果 ---\n{answer}\n-----------------------")
    except Exception as e:
        print(f"執行發生錯誤: {e}")
