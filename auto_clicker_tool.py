#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快捷鍵螢幕指令巨集工具 (XMBC-Style Hotkey Macro Tool)
- 透過指令巨集語法（如 XMBC 風格）進行連續、多步驟自動化操作
- 支援移動座標 {MOVETO: x, y}、游標防推鎖定 {LOCK}/{UNLOCK}
- 支援滑鼠各鍵 {LMB_HOLD: ms}, {RMB_HOLD: ms}, {MMB_HOLD: ms}, {MB4_HOLD: ms}, {MB5_HOLD: ms}
- 支援鍵盤按鍵 {KEY: f}, {KEY_HOLD: space, ms}, {KEYDOWN: ctrl}, {KEYUP: ctrl}
- 支援延遲等待 {WAIT: ms} 與文字輸入 {TEXT: str}
- 支援全域快捷鍵 / 滑鼠側鍵 4/5 觸發
- 支援單次執行與連續循環模式
- 自動儲存並載入本機設定檔 (auto_clicker_config.json)
"""

import sys
import os
import re
import json
import time
import ctypes
import threading
import shutil
from typing import Optional, Dict, Any, List

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint, QObject
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QComboBox, QCheckBox,
    QPlainTextEdit, QTextEdit, QGroupBox, QFrame, QMessageBox, QDialog,
    QGridLayout, QMenu, QSplitter
)
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QCursor, QTextCursor

import keyboard
import pynput
from pynput import mouse

# ==============================================================================
# Windows Native Mouse & Keyboard Controller
# ==============================================================================

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long)
    ]

class MouseController:
    # Windows Mouse Event Constants
    MOUSEEVENTF_LEFTDOWN   = 0x0002
    MOUSEEVENTF_LEFTUP     = 0x0004
    MOUSEEVENTF_RIGHTDOWN  = 0x0008
    MOUSEEVENTF_RIGHTUP    = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP   = 0x0040
    MOUSEEVENTF_XDOWN      = 0x0080
    MOUSEEVENTF_XUP        = 0x0100
    
    # XBUTTON Constants (Mouse 4 & Mouse 5)
    XBUTTON1 = 0x0001
    XBUTTON2 = 0x0002

    @staticmethod
    def get_cursor_pos():
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    @staticmethod
    def set_cursor_pos(x: int, y: int):
        ctypes.windll.user32.SetCursorPos(int(x), int(y))

    @staticmethod
    def lock_cursor(x: int = None, y: int = None):
        """Locks cursor to coordinate (or current position) so physical mouse movement is restricted."""
        if x is None or y is None:
            x, y = MouseController.get_cursor_pos()
        rect = RECT(int(x), int(y), int(x) + 1, int(y) + 1)
        ctypes.windll.user32.ClipCursor(ctypes.byref(rect))

    @staticmethod
    def unlock_cursor():
        """Releases the cursor lock back to full screen."""
        ctypes.windll.user32.ClipCursor(None)

    @classmethod
    def mouse_down(cls, button: str = "left"):
        btn = button.lower()
        if btn == "left":
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        elif btn == "right":
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        elif btn in ["middle", "mouse3"]:
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
        elif btn in ["mouse4", "x1", "side1", "側鍵1"]:
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_XDOWN, 0, 0, cls.XBUTTON1, 0)
        elif btn in ["mouse5", "x2", "side2", "側鍵2"]:
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_XDOWN, 0, 0, cls.XBUTTON2, 0)

    @classmethod
    def mouse_up(cls, button: str = "left"):
        btn = button.lower()
        if btn == "left":
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif btn == "right":
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        elif btn in ["middle", "mouse3"]:
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
        elif btn in ["mouse4", "x1", "side1", "側鍵1"]:
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_XUP, 0, 0, cls.XBUTTON1, 0)
        elif btn in ["mouse5", "x2", "side2", "側鍵2"]:
            ctypes.windll.user32.mouse_event(cls.MOUSEEVENTF_XUP, 0, 0, cls.XBUTTON2, 0)

    @classmethod
    def hold_button(cls, button: str, hold_ms: int):
        cls.mouse_down(button)
        sleep_sec = max(0.001, hold_ms / 1000.0)
        start_time = time.perf_counter()
        while time.perf_counter() - start_time < sleep_sec:
            rem = sleep_sec - (time.perf_counter() - start_time)
            if rem > 0.005:
                time.sleep(rem - 0.003)
            else:
                pass
        cls.mouse_up(button)

    WM_MOUSEMOVE   = 0x0200
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP   = 0x0202
    WM_RBUTTONDOWN = 0x0204
    WM_RBUTTONUP   = 0x0205
    MK_LBUTTON     = 0x0001
    MK_RBUTTON     = 0x0002

    @classmethod
    def background_click(cls, x: int, y: int, hold_ms: int = 100, button: str = "left"):
        """Sends PostMessage click directly to active window without moving or unhiding physical cursor."""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return False
        client_pt = POINT(int(x), int(y))
        ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(client_pt))
        lparam = (client_pt.y << 16) | (client_pt.x & 0xFFFF)
        
        down_msg = cls.WM_LBUTTONDOWN if button == "left" else cls.WM_RBUTTONDOWN
        up_msg = cls.WM_LBUTTONUP if button == "left" else cls.WM_RBUTTONUP
        flag = cls.MK_LBUTTON if button == "left" else cls.MK_RBUTTON
        
        ctypes.windll.user32.PostMessageW(hwnd, cls.WM_MOUSEMOVE, 0, lparam)
        time.sleep(0.003)
        ctypes.windll.user32.PostMessageW(hwnd, down_msg, flag, lparam)
        time.sleep(max(0.001, hold_ms / 1000.0))
        ctypes.windll.user32.PostMessageW(hwnd, up_msg, 0, lparam)
        return True


# ==============================================================================
# Macro Parser (XMBC Style Command Engine)
# ==============================================================================

class MacroParser:
    @staticmethod
    def parse(script_text: str) -> List[Dict[str, Any]]:
        actions = []
        # Filter comments
        clean_lines = []
        for line in script_text.splitlines():
            line_str = line.strip()
            if line_str.startswith("//") or line_str.startswith("#"):
                continue
            line_str = re.sub(r'(//|#).*$', '', line_str).strip()
            if line_str:
                clean_lines.append(line_str)
        
        full_text = " ".join(clean_lines)
        tag_pattern = re.compile(r'\{([A-Za-z0-9_]+)(?:\s*:\s*([^}]+))?\}')
        matches = tag_pattern.findall(full_text)

        for tag, arg in matches:
            tag = tag.upper().strip()
            arg = arg.strip() if arg else ""

            if tag in ["MOVETO", "MOVE", "POS"]:
                parts = [p.strip() for p in arg.split(",")]
                if len(parts) >= 2:
                    actions.append({"type": "move", "x": int(parts[0]), "y": int(parts[1])})
            elif tag == "LOCK":
                actions.append({"type": "lock"})
            elif tag == "UNLOCK":
                actions.append({"type": "unlock"})
            elif tag in ["LMB", "LCLICK", "LEFT"]:
                actions.append({"type": "click", "button": "left", "hold_ms": 50})
            elif tag in ["LMB_HOLD", "LCLICK_HOLD", "LEFT_HOLD"]:
                ms = int(arg) if arg else 100
                actions.append({"type": "click", "button": "left", "hold_ms": ms})
            elif tag in ["LDOWN", "LEFT_DOWN"]:
                actions.append({"type": "mouse_down", "button": "left"})
            elif tag in ["LUP", "LEFT_UP"]:
                actions.append({"type": "mouse_up", "button": "left"})
            elif tag in ["RMB", "RCLICK", "RIGHT"]:
                actions.append({"type": "click", "button": "right", "hold_ms": 50})
            elif tag in ["RMB_HOLD", "RCLICK_HOLD", "RIGHT_HOLD"]:
                ms = int(arg) if arg else 100
                actions.append({"type": "click", "button": "right", "hold_ms": ms})
            elif tag in ["RDOWN", "RIGHT_DOWN"]:
                actions.append({"type": "mouse_down", "button": "right"})
            elif tag in ["RUP", "RIGHT_UP"]:
                actions.append({"type": "mouse_up", "button": "right"})
            elif tag in ["MMB", "MCLICK", "MIDDLE"]:
                actions.append({"type": "click", "button": "middle", "hold_ms": 50})
            elif tag in ["MMB_HOLD", "MIDDLE_HOLD"]:
                ms = int(arg) if arg else 100
                actions.append({"type": "click", "button": "middle", "hold_ms": ms})
            elif tag in ["MDOWN", "MIDDLE_DOWN"]:
                actions.append({"type": "mouse_down", "button": "middle"})
            elif tag in ["MUP", "MIDDLE_UP"]:
                actions.append({"type": "mouse_up", "button": "middle"})
            elif tag in ["MB4", "X1", "SIDE1"]:
                actions.append({"type": "click", "button": "mouse4", "hold_ms": 50})
            elif tag in ["MB4_HOLD", "X1_HOLD", "SIDE1_HOLD"]:
                ms = int(arg) if arg else 100
                actions.append({"type": "click", "button": "mouse4", "hold_ms": ms})
            elif tag in ["MB4_DOWN", "X1_DOWN"]:
                actions.append({"type": "mouse_down", "button": "mouse4"})
            elif tag in ["MB4_UP", "X1_UP"]:
                actions.append({"type": "mouse_up", "button": "mouse4"})
            elif tag in ["MB5", "X2", "SIDE2"]:
                actions.append({"type": "click", "button": "mouse5", "hold_ms": 50})
            elif tag in ["MB5_HOLD", "X2_HOLD", "SIDE2_HOLD"]:
                ms = int(arg) if arg else 100
                actions.append({"type": "click", "button": "mouse5", "hold_ms": ms})
            elif tag in ["MB5_DOWN", "X2_DOWN"]:
                actions.append({"type": "mouse_down", "button": "mouse5"})
            elif tag in ["MB5_UP", "X2_UP"]:
                actions.append({"type": "mouse_up", "button": "mouse5"})
            elif tag in ["WAIT", "SLEEP", "DELAY", "PAUSE"]:
                ms = int(arg) if arg else 100
                actions.append({"type": "wait", "ms": ms})
            elif tag in ["KEY", "PRESS"]:
                actions.append({"type": "key_press", "key": arg})
            elif tag in ["KEYDOWN", "KEY_DOWN"]:
                actions.append({"type": "key_down", "key": arg})
            elif tag in ["KEYUP", "KEY_UP"]:
                actions.append({"type": "key_up", "key": arg})
            elif tag in ["KEY_HOLD"]:
                parts = [p.strip() for p in arg.split(",")]
                k = parts[0]
                ms = int(parts[1]) if len(parts) > 1 else 100
                actions.append({"type": "key_hold", "key": k, "ms": ms})
            elif tag in ["CLICK_POS", "CLICK_AT", "POINT_CLICK"]:
                parts = [p.strip() for p in arg.split(",")]
                if len(parts) >= 2:
                    x, y = int(parts[0]), int(parts[1])
                    ms = int(parts[2]) if len(parts) > 2 else 100
                    btn = parts[3].lower() if len(parts) > 3 else "left"
                    actions.append({"type": "click_pos", "x": x, "y": y, "hold_ms": ms, "button": btn})
            elif tag in ["BG_LMB", "BG_CLICK", "POST_LMB", "DIRECT_LMB"]:
                parts = [p.strip() for p in arg.split(",")]
                if len(parts) >= 2:
                    x, y = int(parts[0]), int(parts[1])
                    ms = int(parts[2]) if len(parts) > 2 else 100
                    actions.append({"type": "bg_click", "x": x, "y": y, "hold_ms": ms, "button": "left"})
            elif tag in ["BG_RMB", "POST_RMB", "DIRECT_RMB"]:
                parts = [p.strip() for p in arg.split(",")]
                if len(parts) >= 2:
                    x, y = int(parts[0]), int(parts[1])
                    ms = int(parts[2]) if len(parts) > 2 else 100
                    actions.append({"type": "bg_click", "x": x, "y": y, "hold_ms": ms, "button": "right"})
            elif tag in ["TEXT"]:
                actions.append({"type": "text", "content": arg})
            elif tag in [
                "TAB", "ENTER", "RETURN", "SPACE", "ESC", "ESCAPE", "BACKSPACE", "BS", "DELETE", "DEL",
                "INSERT", "INS", "HOME", "END", "PAGEUP", "PGUP", "PAGEDOWN", "PGDN",
                "UP", "DOWN", "LEFT", "RIGHT", "CAPSLOCK", "PRINTSCREEN", "SCROLLLOCK", "PAUSE",
                "CTRL", "CONTROL", "ALT", "SHIFT", "WIN", "WINDOWS",
                "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"
            ] or (len(tag) == 1 and tag.isalnum()):
                actions.append({"type": "key_press", "key": tag.lower()})

        return actions


# ==============================================================================
# Froststrap Korblox Mesh Auto-Replacer
# ==============================================================================

KORBLOX_SOURCE_FILE = os.path.join(os.path.expanduser("~"), "Downloads", "korblox", "rightleg.mesh")
FROSTSTRAP_TARGET_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Froststrap", "Versions", "version-f5a60436d48947d3", "content", "avatar", "meshes")
FROSTSTRAP_VERSIONS_BASE = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Froststrap", "Versions")

def replace_korblox_mesh(source_mesh: str = KORBLOX_SOURCE_FILE, target_dir: str = FROSTSTRAP_TARGET_DIR) -> tuple:
    """
    自動將 Korblox rightleg.mesh 替換到 Froststrap 的 avatar meshes 目錄中。
    會替換指定的版本目錄 (version-f5a60436d48947d3) 以及 Versions 底下的其他版本目錄。
    """
    if not os.path.exists(source_mesh):
        return False, f"找不到來源檔案: {source_mesh}"
    
    target_dirs = set()
    # 加入指定目標目錄
    target_dirs.add(target_dir)

    # 搜尋 Versions 底下所有版本資料夾
    if os.path.exists(FROSTSTRAP_VERSIONS_BASE):
        try:
            for entry in os.listdir(FROSTSTRAP_VERSIONS_BASE):
                full_v = os.path.join(FROSTSTRAP_VERSIONS_BASE, entry)
                if os.path.isdir(full_v):
                    m_dir = os.path.join(full_v, "content", "avatar", "meshes")
                    target_dirs.add(m_dir)
        except Exception:
            pass

    success_count = 0
    error_list = []

    for d in target_dirs:
        try:
            os.makedirs(d, exist_ok=True)
            dst_file = os.path.join(d, "rightleg.mesh")
            shutil.copy2(source_mesh, dst_file)
            success_count += 1
        except Exception as e:
            error_list.append(f"{d}: {e}")

    if success_count > 0:
        return True, f"已成功替換 Korblox rightleg.mesh 至 {success_count} 個 Froststrap 版本目錄！"
    else:
        return False, f"替換失敗: {'; '.join(error_list)}"


# ==============================================================================
# Configuration Manager
# ==============================================================================

CONFIG_FILENAME = "auto_clicker_config.json"

DEFAULT_MACRO_SCRIPT = """// XMBC 指令巨集範例：
// 1. 移動到螢幕座標 (960, 540)
// 2. 鎖定滑鼠 (防誤推)
// 3. 左鍵按住 100 毫秒後放開
// 4. 解鎖滑鼠
{MOVETO: 960, 540}
{LOCK}
{LMB_HOLD: 100}
{UNLOCK}
"""

DEFAULT_CONFIG: Dict[str, Any] = {
    "hotkey": "f6",
    "macro_script": DEFAULT_MACRO_SCRIPT,
    "interval_ms": 500,
    "click_mode": "single",        # "single" or "continuous"
    "always_on_top": True
}

def get_config_path() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, CONFIG_FILENAME)

def load_config() -> Dict[str, Any]:
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = DEFAULT_CONFIG.copy()
                config.update(data)
                return config
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(config: Dict[str, Any]) -> bool:
    config_path = get_config_path()
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

def format_key_display(key_str: str) -> str:
    k = key_str.lower().strip()
    if k in ["mouse4", "x1"]:
        return "側鍵 1 (Mouse 4)"
    elif k in ["mouse5", "x2"]:
        return "側鍵 2 (Mouse 5)"
    elif k in ["mouse3", "middle"]:
        return "滑鼠中鍵 (Mouse 3)"
    elif k in ["mouse2", "right"]:
        return "滑鼠右鍵 (Mouse 2)"
    elif k in ["mouse1", "left"]:
        return "滑鼠左鍵 (Mouse 1)"
    return k.upper()


# ==============================================================================
# Screen Coordinate Picker Overlay
# ==============================================================================

class CoordinatePickerOverlay(QWidget):
    coordinate_picked = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        self.current_pos = QPoint(0, 0)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_mouse_position)
        self.update_timer.start(16)

    def show_fullscreen_picker(self):
        screen_geo = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geo)
        self.show()
        self.raise_()
        self.activateWindow()

    def update_mouse_position(self):
        x, y = MouseController.get_cursor_pos()
        self.current_pos = QPoint(x, y)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

        # Crosshair lines
        pen = QPen(QColor(16, 185, 129, 220), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(0, self.current_pos.y(), self.width(), self.current_pos.y())
        painter.drawLine(self.current_pos.x(), 0, self.current_pos.x(), self.height())

        # Target Circle
        circle_pen = QPen(QColor(56, 189, 248, 255), 2)
        painter.setPen(circle_pen)
        painter.drawEllipse(self.current_pos, 14, 14)
        painter.drawPoint(self.current_pos)

        # Info Box Tooltip
        box_x = self.current_pos.x() + 20
        box_y = self.current_pos.y() + 20
        if box_x + 160 > self.width():
            box_x = self.current_pos.x() - 170
        if box_y + 50 > self.height():
            box_y = self.current_pos.y() - 60

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(24, 24, 27, 230))
        painter.drawRoundedRect(box_x, box_y, 160, 48, 6, 6)

        painter.setPen(QColor(244, 244, 245))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(box_x + 8, box_y + 20, f"座標: X={self.current_pos.x()}  Y={self.current_pos.y()}")
        painter.setPen(QColor(148, 163, 184))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(box_x + 8, box_y + 38, "左鍵插入 | ESC 取消")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            x, y = MouseController.get_cursor_pos()
            self.update_timer.stop()
            self.close()
            self.coordinate_picked.emit(x, y)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.update_timer.stop()
            self.close()


# ==============================================================================
# Hotkey & Mouse Button Recorder Dialog
# ==============================================================================

class KeyCaptureSignaler(QObject):
    key_captured = pyqtSignal(str)

class HotkeyRecorderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定觸發快捷鍵 / 側鍵")
        self.setFixedSize(320, 150)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.captured_key: Optional[str] = None

        self.signaler = KeyCaptureSignaler()
        self.signaler.key_captured.connect(self._on_key_received)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.label_info = QLabel("請直接按下【鍵盤按鍵】\n或點擊【滑鼠側鍵 4 / 5 / 中鍵】", self)
        self.label_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_info.setFont(QFont("Segoe UI", 10))
        layout.addWidget(self.label_info)

        self.label_key = QLabel("等待按下按鍵 / 側鍵...", self)
        self.label_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_key.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.label_key.setStyleSheet("color: #10b981; padding: 8px; background: #27272a; border-radius: 6px;")
        layout.addWidget(self.label_key)

        btn_cancel = QPushButton("取消 (Esc)", self)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

        # Hook keyboard
        self.kb_hook = keyboard.on_press(self._on_kb_event)

        # Hook mouse buttons
        self.mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
        self.mouse_listener.start()

    def _on_kb_event(self, e):
        if e.name in ["ctrl", "alt", "shift", "windows", "left ctrl", "right ctrl", "left shift", "right shift", "left alt", "right alt"]:
            return
        self.signaler.key_captured.emit(e.name.lower())

    def _on_mouse_click(self, x, y, button, pressed):
        if pressed:
            key_name = None
            if button == mouse.Button.x1:
                key_name = "mouse4"
            elif button == mouse.Button.x2:
                key_name = "mouse5"
            elif button == mouse.Button.middle:
                key_name = "mouse3"
            
            if key_name:
                self.signaler.key_captured.emit(key_name)

    def _on_key_received(self, key_str: str):
        self.captured_key = key_str
        self._cleanup()
        self.accept()

    def _cleanup(self):
        try:
            keyboard.unhook(self.kb_hook)
        except Exception:
            pass
        try:
            if self.mouse_listener.is_alive():
                self.mouse_listener.stop()
        except Exception:
            pass

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)


# ==============================================================================
# Macro Executor Worker Thread
# ==============================================================================

class MacroWorker(QObject):
    step_executed = pyqtSignal(str)      # Log message
    status_changed = pyqtSignal(bool)    # Running status

    def __init__(self):
        super().__init__()
        self.is_running = False
        self.script_text = ""
        self.interval_ms = 500
        self.mode = "single"
        self._stop_event = threading.Event()

    def set_params(self, script_text: str, interval_ms: int, mode: str):
        self.script_text = script_text
        self.interval_ms = interval_ms
        self.mode = mode

    def trigger_single(self):
        t = threading.Thread(target=self._run_single_macro, daemon=True)
        t.start()

    def _execute_actions(self, actions: List[Dict[str, Any]]):
        for idx, act in enumerate(actions, 1):
            if self._stop_event.is_set():
                break
            
            atype = act.get("type")
            if atype == "move":
                x, y = act["x"], act["y"]
                MouseController.unlock_cursor()
                MouseController.set_cursor_pos(x, y)
                time.sleep(0.003)
                self.step_executed.emit(f"📍 移至座標: ({x}, {y})")
            elif atype == "lock":
                MouseController.lock_cursor()
                self.step_executed.emit("🔒 鎖定游標 (防推)")
            elif atype == "unlock":
                MouseController.unlock_cursor()
                self.step_executed.emit("🔓 解鎖游標")
            elif atype == "click":
                btn = act["button"]
                h_ms = act["hold_ms"]
                btn_disp = format_key_display(btn)
                self.step_executed.emit(f"🖱️ 按下 {btn_disp} (按住 {h_ms}ms)")
                MouseController.hold_button(btn, h_ms)
            elif atype == "mouse_down":
                btn = act["button"]
                self.step_executed.emit(f"⬇️ {format_key_display(btn)} 按下")
                MouseController.mouse_down(btn)
            elif atype == "mouse_up":
                btn = act["button"]
                self.step_executed.emit(f"⬆️ {format_key_display(btn)} 放開")
                MouseController.mouse_up(btn)
            elif atype == "wait":
                w_ms = act["ms"]
                self.step_executed.emit(f"⏱️ 延遲 {w_ms}ms")
                time.sleep(max(0.001, w_ms / 1000.0))
            elif atype == "key_press":
                k = act["key"]
                self.step_executed.emit(f"⌨️ 按鍵: [{k.upper()}]")
                keyboard.press_and_release(k)
            elif atype == "key_down":
                k = act["key"]
                self.step_executed.emit(f"⬇️ 按鍵按下: [{k.upper()}]")
                keyboard.press(k)
            elif atype == "key_up":
                k = act["key"]
                self.step_executed.emit(f"⬆️ 按鍵放開: [{k.upper()}]")
                keyboard.release(k)
            elif atype == "key_hold":
                k = act["key"]
                h_ms = act["ms"]
                self.step_executed.emit(f"⌨️ 按鍵 [{k.upper()}] (按住 {h_ms}ms)")
                keyboard.press(k)
                time.sleep(max(0.001, h_ms / 1000.0))
                keyboard.release(k)
            elif atype == "click_pos":
                x, y = act["x"], act["y"]
                h_ms = act["hold_ms"]
                btn = act["button"]
                self.step_executed.emit(f"🎯 定點鎖定點擊: ({x}, {y}) | 按住 {h_ms}ms ({format_key_display(btn)})")
                MouseController.set_cursor_pos(x, y)
                MouseController.lock_cursor(x, y)
                MouseController.hold_button(btn, h_ms)
                MouseController.unlock_cursor()
            elif atype == "bg_click":
                x, y = act["x"], act["y"]
                h_ms = act["hold_ms"]
                btn = act["button"]
                self.step_executed.emit(f"🎯 背景直發點擊: ({x}, {y}) | 按住 {h_ms}ms ({format_key_display(btn)})")
                MouseController.background_click(x, y, h_ms, btn)
            elif atype == "text":
                txt = act["content"]
                self.step_executed.emit(f"✍️ 輸入文字: {txt}")
                keyboard.write(txt)

    def _run_single_macro(self):
        actions = MacroParser.parse(self.script_text)
        if not actions:
            self.step_executed.emit("⚠️ 巨集為空或未解析到有效指令！")
            return

        self.step_executed.emit(f"⚡ [開始執行單次巨集] 共 {len(actions)} 個步驟")
        try:
            self._execute_actions(actions)
            self.step_executed.emit("✅ [單次巨集執行完畢]")
        finally:
            MouseController.unlock_cursor()

    def toggle_continuous(self):
        if self.is_running:
            self.stop_continuous()
        else:
            self.start_continuous()

    def start_continuous(self):
        if not self.is_running:
            actions = MacroParser.parse(self.script_text)
            if not actions:
                self.step_executed.emit("⚠️ 巨集為空或未解析到有效指令！")
                return

            self.is_running = True
            self._stop_event.clear()
            self.status_changed.emit(True)
            self.step_executed.emit(f"🟢 [循環巨集已啟動] (步驟數: {len(actions)})")
            t = threading.Thread(target=self._run_continuous_loop, daemon=True)
            t.start()

    def stop_continuous(self):
        if self.is_running:
            self.is_running = False
            self._stop_event.set()
            MouseController.unlock_cursor()
            self.status_changed.emit(False)
            self.step_executed.emit("🔴 [循環巨集已停止]")

    def _run_continuous_loop(self):
        actions = MacroParser.parse(self.script_text)
        cycle = 0
        try:
            while self.is_running and not self._stop_event.is_set():
                cycle += 1
                self.step_executed.emit(f"🔄 --- 循環輪次 #{cycle} ---")
                self._execute_actions(actions)
                
                # Interval sleep between cycles
                sleep_time = max(0.01, self.interval_ms / 1000.0)
                interval_start = time.perf_counter()
                while (time.perf_counter() - interval_start < sleep_time) and self.is_running:
                    time.sleep(0.01)
        finally:
            MouseController.unlock_cursor()


# ==============================================================================
# Unified Global Hotkey & Mouse Button Listener
# ==============================================================================

class GlobalTriggerManager(QObject):
    triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.current_key: Optional[str] = None
        self.kb_hook = None
        self.mouse_listener: Optional[mouse.Listener] = None

    def set_trigger(self, key_str: str):
        self.stop()
        self.current_key = key_str.lower().strip()
        
        if not self.current_key:
            return

        if self.current_key in ["mouse4", "mouse5", "mouse3", "x1", "x2"]:
            target_btn = None
            if self.current_key in ["mouse4", "x1"]:
                target_btn = mouse.Button.x1
            elif self.current_key in ["mouse5", "x2"]:
                target_btn = mouse.Button.x2
            elif self.current_key == "mouse3":
                target_btn = mouse.Button.middle

            def on_click(x, y, button, pressed):
                if pressed and button == target_btn:
                    self.triggered.emit()

            self.mouse_listener = mouse.Listener(on_click=on_click)
            self.mouse_listener.daemon = True
            self.mouse_listener.start()
        else:
            try:
                self.kb_hook = keyboard.add_hotkey(self.current_key, self._on_kb_triggered, suppress=False)
            except Exception as e:
                print(f"[Warn] Failed to hook keyboard key {self.current_key}: {e}")

    def _on_kb_triggered(self):
        self.triggered.emit()

    def stop(self):
        if self.kb_hook and self.current_key:
            try:
                keyboard.remove_hotkey(self.current_key)
            except Exception:
                pass
            self.kb_hook = None

        if self.mouse_listener:
            try:
                self.mouse_listener.stop()
            except Exception:
                pass
            self.mouse_listener = None


# ==============================================================================
# Main GUI Window (XMBC Macro Style)
# ==============================================================================

class AutoClickerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("XMBC 指令巨集連點工具")
        self.setMinimumSize(440, 560)
        self.resize(460, 600)

        self.config = load_config()
        self.macro_worker = MacroWorker()
        self.trigger_mgr = GlobalTriggerManager()
        self.picker_overlay = CoordinatePickerOverlay()

        self.picker_overlay.coordinate_picked.connect(self.on_coordinate_picked)
        self.trigger_mgr.triggered.connect(self.on_trigger_fired)
        self.macro_worker.step_executed.connect(self.append_log)
        self.macro_worker.status_changed.connect(self.update_status_display)

        self.init_ui()
        self.load_settings_to_ui()
        self.apply_trigger_binding()

        # 自動執行 Korblox rightleg.mesh 替換
        self.auto_apply_korblox_mesh(show_dialog=False)

    def init_ui(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #111827;
            }
            QWidget {
                color: #f3f4f6;
                font-family: "Segoe UI", "Microsoft JhengHei", sans-serif;
                font-size: 12px;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #1f2937;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 10px;
                background-color: #1f2937;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #38bdf8;
            }
            QLabel {
                color: #d1d5db;
            }
            QSpinBox, QComboBox {
                background-color: #111827;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 3px 6px;
                color: #ffffff;
                selection-background-color: #0284c7;
            }
            QSpinBox:focus, QComboBox:focus {
                border: 1px solid #38bdf8;
            }
            QPushButton {
                background-color: #374151;
                color: #ffffff;
                border: 1px solid #4b5563;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
            QPushButton#btnRecord {
                background-color: #0284c7;
                border-color: #0369a1;
            }
            QPushButton#btnRecord:hover {
                background-color: #0369a1;
            }
            QPushButton#btnPick {
                background-color: #059669;
                border-color: #047857;
            }
            QPushButton#btnPick:hover {
                background-color: #047857;
            }
            QPushButton#btnTest {
                background-color: #d97706;
                border-color: #b45309;
            }
            QPushButton#btnTest:hover {
                background-color: #b45309;
            }
            QPushButton#btnTag {
                background-color: #1f2937;
                border: 1px solid #374151;
                color: #93c5fd;
                font-size: 11px;
                padding: 3px 6px;
            }
            QPushButton#btnTag:hover {
                background-color: #374151;
                color: #ffffff;
            }
            QCheckBox {
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid #4b5563;
                background-color: #111827;
            }
            QCheckBox::indicator:checked {
                background-color: #10b981;
                border-color: #10b981;
            }
            QPlainTextEdit {
                background-color: #030712;
                border: 1px solid #374151;
                border-radius: 4px;
                color: #38bdf8;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
                line-height: 1.4;
                padding: 6px;
            }
            QTextEdit {
                background-color: #030712;
                border: 1px solid #1f2937;
                border-radius: 4px;
                color: #9ca3af;
                font-family: "Consolas", monospace;
                font-size: 10px;
                padding: 4px;
            }
        """)

        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        # -------------------------------------------------------------
        # 1. Status Bar Banner
        # -------------------------------------------------------------
        self.status_card = QFrame(self)
        self.status_card.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        st_layout = QHBoxLayout(self.status_card)
        st_layout.setContentsMargins(6, 2, 6, 2)

        self.status_dot = QLabel("🟢", self)
        self.status_text = QLabel("待命 (Ready)", self)
        self.status_text.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.status_text.setStyleSheet("color: #38bdf8;")

        st_layout.addWidget(self.status_dot)
        st_layout.addWidget(self.status_text)
        st_layout.addStretch()

        self.btn_korblox = QPushButton("🦴 換 Korblox 右腿", self)
        self.btn_korblox.setStyleSheet("""
            QPushButton {
                background-color: #4c1d95;
                border: 1px solid #6d28d9;
                color: #e9d5ff;
                font-size: 11px;
                padding: 3px 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #6d28d9;
                color: #ffffff;
            }
        """)
        self.btn_korblox.setToolTip("手動替換 Korblox rightleg.mesh 到 Froststrap 目錄")
        self.btn_korblox.clicked.connect(lambda: self.auto_apply_korblox_mesh(show_dialog=True))
        st_layout.addWidget(self.btn_korblox)

        self.chk_top = QCheckBox("視窗置頂", self)
        self.chk_top.setChecked(True)
        self.chk_top.toggled.connect(self.on_always_on_top_toggled)
        st_layout.addWidget(self.chk_top)

        main_layout.addWidget(self.status_card)

        # -------------------------------------------------------------
        # 2. 觸發快捷鍵與模式
        # -------------------------------------------------------------
        grp_trigger = QGroupBox("⌨️ 觸發快捷鍵 / 側鍵與模式", self)
        layout_trig = QVBoxLayout(grp_trigger)
        layout_trig.setContentsMargins(8, 6, 8, 6)
        layout_trig.setSpacing(6)

        row_trig = QHBoxLayout()
        self.lbl_current_hotkey = QLabel("F6", self)
        self.lbl_current_hotkey.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_current_hotkey.setStyleSheet("color: #38bdf8; background: #111827; padding: 4px 8px; border-radius: 4px; border: 1px solid #374151;")
        
        self.btn_record_hotkey = QPushButton("🎙️ 設定觸發鍵/側鍵", self)
        self.btn_record_hotkey.setObjectName("btnRecord")
        self.btn_record_hotkey.clicked.connect(self.record_hotkey)

        row_trig.addWidget(self.lbl_current_hotkey, stretch=1)
        row_trig.addWidget(self.btn_record_hotkey)
        layout_trig.addLayout(row_trig)

        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("模式:", self))
        self.combo_mode = QComboBox(self)
        self.combo_mode.addItem("單次執行 (按一次執行一次巨集)", "single")
        self.combo_mode.addItem("循環重複 (按一下開始/停止連點)", "continuous")
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        row_mode.addWidget(self.combo_mode, stretch=1)

        self.lbl_interval = QLabel("循環間隔:", self)
        self.spin_interval_ms = QSpinBox(self)
        self.spin_interval_ms.setRange(10, 60000)
        self.spin_interval_ms.setValue(500)
        self.spin_interval_ms.setSuffix(" ms")
        self.spin_interval_ms.valueChanged.connect(self.auto_save)
        row_mode.addWidget(self.lbl_interval)
        row_mode.addWidget(self.spin_interval_ms)

        layout_trig.addLayout(row_mode)
        main_layout.addWidget(grp_trigger)

        # -------------------------------------------------------------
        # 3. 巨集指令編輯區 (XMBC Macro Editor)
        # -------------------------------------------------------------
        grp_macro = QGroupBox("📜 指令巨集編輯區 (XMBC Macro Script)", self)
        layout_macro = QVBoxLayout(grp_macro)
        layout_macro.setContentsMargins(8, 6, 8, 6)
        layout_macro.setSpacing(6)

        # Quick Insert Toolbar Row 1
        row_tb1 = QHBoxLayout()
        row_tb1.setSpacing(4)
        
        btn_insert_pos = QPushButton("🎯 準心插座標", self)
        btn_insert_pos.setObjectName("btnPick")
        btn_insert_pos.clicked.connect(self.start_coordinate_picker)
        
        btn_lmb_hold = QPushButton("+ 左鍵按住", self)
        btn_lmb_hold.setObjectName("btnTag")
        btn_lmb_hold.clicked.connect(lambda: self.insert_macro_tag("{LMB_HOLD: 100}"))

        btn_lock = QPushButton("+ 鎖定游標", self)
        btn_lock.setObjectName("btnTag")
        btn_lock.clicked.connect(lambda: self.insert_macro_tag("{LOCK}"))

        btn_unlock = QPushButton("+ 解鎖游標", self)
        btn_unlock.setObjectName("btnTag")
        btn_unlock.clicked.connect(lambda: self.insert_macro_tag("{UNLOCK}"))

        btn_wait = QPushButton("+ 延遲", self)
        btn_wait.setObjectName("btnTag")
        btn_wait.clicked.connect(lambda: self.insert_macro_tag("{WAIT: 100}"))

        row_tb1.addWidget(btn_insert_pos)
        row_tb1.addWidget(btn_lmb_hold)
        row_tb1.addWidget(btn_lock)
        row_tb1.addWidget(btn_unlock)
        row_tb1.addWidget(btn_wait)
        layout_macro.addLayout(row_tb1)

        # Quick Insert Toolbar Row 2
        row_tb2 = QHBoxLayout()
        row_tb2.setSpacing(4)

        btn_mb4 = QPushButton("+ 側鍵1 (MB4)", self)
        btn_mb4.setObjectName("btnTag")
        btn_mb4.clicked.connect(lambda: self.insert_macro_tag("{MB4_HOLD: 100}"))

        btn_mb5 = QPushButton("+ 側鍵2 (MB5)", self)
        btn_mb5.setObjectName("btnTag")
        btn_mb5.clicked.connect(lambda: self.insert_macro_tag("{MB5_HOLD: 100}"))

        btn_rmb = QPushButton("+ 右鍵", self)
        btn_rmb.setObjectName("btnTag")
        btn_rmb.clicked.connect(lambda: self.insert_macro_tag("{RMB_HOLD: 100}"))

        btn_key = QPushButton("+ 按鍵", self)
        btn_key.setObjectName("btnTag")
        btn_key.clicked.connect(lambda: self.insert_macro_tag("{KEY: space}"))

        btn_templates = QPushButton("📋 範本...", self)
        btn_templates.clicked.connect(self.show_template_menu)

        row_tb2.addWidget(btn_mb4)
        row_tb2.addWidget(btn_mb5)
        row_tb2.addWidget(btn_rmb)
        row_tb2.addWidget(btn_key)
        row_tb2.addWidget(btn_templates)
        layout_macro.addLayout(row_tb2)

        # Macro Text Editor
        self.txt_macro = QPlainTextEdit(self)
        self.txt_macro.setPlainText(DEFAULT_MACRO_SCRIPT)
        self.txt_macro.textChanged.connect(self.auto_save)
        layout_macro.addWidget(self.txt_macro)

        main_layout.addWidget(grp_macro)

        # -------------------------------------------------------------
        # 4. 操作按鈕
        # -------------------------------------------------------------
        row_actions = QHBoxLayout()
        self.btn_test = QPushButton("⚡ 立即測試執行巨集", self)
        self.btn_test.setObjectName("btnTest")
        self.btn_test.clicked.connect(self.execute_test_macro)

        self.btn_save = QPushButton("💾 儲存巨集至本機", self)
        self.btn_save.clicked.connect(self.save_settings_manual)

        self.btn_clear = QPushButton("🧹 清空", self)
        self.btn_clear.clicked.connect(self.txt_macro.clear)

        row_actions.addWidget(self.btn_test, stretch=2)
        row_actions.addWidget(self.btn_save, stretch=1)
        row_actions.addWidget(self.btn_clear)
        main_layout.addLayout(row_actions)

        # -------------------------------------------------------------
        # 5. 執行日誌窗 (Activity Log)
        # -------------------------------------------------------------
        self.log_text = QTextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(85)
        main_layout.addWidget(self.log_text)

    # ==========================================================================
    # Logic & Event Handlers
    # ==========================================================================

    def load_settings_to_ui(self):
        cfg = self.config
        raw_key = cfg.get("hotkey", "f6")
        self.lbl_current_hotkey.setText(format_key_display(raw_key))
        self.lbl_current_hotkey.setProperty("raw_key", raw_key.lower())

        script = cfg.get("macro_script", DEFAULT_MACRO_SCRIPT)
        self.txt_macro.setPlainText(script)

        self.spin_interval_ms.setValue(cfg.get("interval_ms", 500))
        
        mode = cfg.get("click_mode", "single")
        idx = self.combo_mode.findData(mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)

        always_top = cfg.get("always_on_top", True)
        self.chk_top.setChecked(always_top)
        self.apply_always_on_top(always_top)

        self.append_log(f"📁 已載入上次本機巨集紀錄 (觸發: {format_key_display(raw_key)})")

    def get_ui_config(self) -> Dict[str, Any]:
        raw_key = self.lbl_current_hotkey.property("raw_key") or "f6"
        return {
            "hotkey": raw_key,
            "macro_script": self.txt_macro.toPlainText(),
            "interval_ms": self.spin_interval_ms.value(),
            "click_mode": self.combo_mode.currentData(),
            "always_on_top": self.chk_top.isChecked()
        }

    def auto_save(self):
        self.config = self.get_ui_config()
        save_config(self.config)

    def save_settings_manual(self):
        self.auto_save()
        self.append_log("💾 本機巨集設定已儲存！")
        QMessageBox.information(self, "儲存成功", f"巨集設定已成功儲存至:\n{get_config_path()}")

    def on_always_on_top_toggled(self, checked: bool):
        self.apply_always_on_top(checked)
        self.auto_save()

    def apply_always_on_top(self, enabled: bool):
        if enabled:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()

    def on_mode_changed(self):
        mode = self.combo_mode.currentData()
        is_continuous = (mode == "continuous")
        self.spin_interval_ms.setEnabled(is_continuous)
        self.lbl_interval.setEnabled(is_continuous)
        self.auto_save()

    def insert_macro_tag(self, tag_text: str):
        cursor = self.txt_macro.textCursor()
        cursor.insertText(tag_text + "\n")
        self.txt_macro.setTextCursor(cursor)
        self.txt_macro.setFocus()

    def start_coordinate_picker(self):
        self.append_log("🎯 準心取點中，請在目標位置點擊滑鼠左鍵...")
        self.picker_overlay.show_fullscreen_picker()

    def on_coordinate_picked(self, x: int, y: int):
        tag_str = f"{{MOVETO: {x}, {y}}}"
        self.insert_macro_tag(tag_str)
        self.append_log(f"🎯 插入座標指令: {tag_str}")

    def show_template_menu(self):
        menu = QMenu(self)
        act1 = menu.addAction("📌 範本 1: 定點鎖定按住左鍵 (Move -> Lock -> Left Hold -> Unlock)")
        act2 = menu.addAction("🎯 範本 2: 雙點循環連點 (Point A Click -> Point B Click)")
        act3 = menu.addAction("🖱️ 範本 3: 側鍵連點防推 (Lock -> MB4 Hold -> Unlock -> Wait)")
        act4 = menu.addAction("⚔️ 範本 4: 技能連招 (Key 1 -> Wait -> Mouse 4 -> Left Click)")

        action = menu.exec(QCursor.pos())
        if action == act1:
            self.txt_macro.setPlainText(
                "// 範本 1: 定點鎖定按住左鍵\n"
                "{MOVETO: 960, 540}\n"
                "{LOCK}\n"
                "{LMB_HOLD: 100}\n"
                "{UNLOCK}\n"
            )
        elif action == act2:
            self.txt_macro.setPlainText(
                "// 範本 2: 雙點點擊\n"
                "{MOVETO: 800, 500}\n"
                "{LMB_HOLD: 50}\n"
                "{WAIT: 100}\n"
                "{MOVETO: 1100, 500}\n"
                "{LMB_HOLD: 50}\n"
            )
        elif action == act3:
            self.txt_macro.setPlainText(
                "// 範本 3: 側鍵防推連點\n"
                "{LOCK}\n"
                "{MB4_HOLD: 80}\n"
                "{UNLOCK}\n"
                "{WAIT: 50}\n"
            )
        elif action == act4:
            self.txt_macro.setPlainText(
                "// 範本 4: 技能連招\n"
                "{KEY: 1}\n"
                "{WAIT: 150}\n"
                "{MB4_HOLD: 50}\n"
                "{WAIT: 100}\n"
                "{LMB_HOLD: 100}\n"
            )

    def record_hotkey(self):
        self.trigger_mgr.stop()
        dlg = HotkeyRecorderDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.captured_key:
            new_key = dlg.captured_key.lower()
            self.lbl_current_hotkey.setText(format_key_display(new_key))
            self.lbl_current_hotkey.setProperty("raw_key", new_key)
            self.append_log(f"⌨️ 觸發鍵更新為: {format_key_display(new_key)}")
            self.auto_save()
        self.apply_trigger_binding()

    def apply_trigger_binding(self):
        raw_key = self.lbl_current_hotkey.property("raw_key") or "f6"
        self.trigger_mgr.set_trigger(raw_key)
        self.append_log(f"🟢 觸發鍵 [{format_key_display(raw_key)}] 監聽就緒")

    def on_trigger_fired(self):
        cfg = self.get_ui_config()
        self.macro_worker.set_params(
            script_text=cfg["macro_script"],
            interval_ms=cfg["interval_ms"],
            mode=cfg["click_mode"]
        )

        if cfg["click_mode"] == "single":
            self.macro_worker.trigger_single()
        else:
            self.macro_worker.toggle_continuous()

    def execute_test_macro(self):
        cfg = self.get_ui_config()
        self.macro_worker.set_params(
            script_text=cfg["macro_script"],
            interval_ms=cfg["interval_ms"],
            mode=cfg["click_mode"]
        )
        self.macro_worker.trigger_single()

    def update_status_display(self, is_running: bool):
        raw_key = self.lbl_current_hotkey.property("raw_key") or "f6"
        key_name = format_key_display(raw_key)
        if is_running:
            self.status_dot.setText("🔴")
            self.status_text.setText(f"巨集循環中... [按 {key_name} 停止]")
            self.status_text.setStyleSheet("color: #ef4444;")
            self.status_card.setStyleSheet("""
                QFrame {
                    background-color: #450a0a;
                    border: 1px solid #b91c1c;
                    border-radius: 6px;
                    padding: 4px;
                }
            """)
        else:
            self.status_dot.setText("🟢")
            self.status_text.setText(f"待命 - 觸發鍵 [{key_name}]")
            self.status_text.setStyleSheet("color: #38bdf8;")
            self.status_card.setStyleSheet("""
                QFrame {
                    background-color: #1e293b;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 4px;
                }
            """)

    def auto_apply_korblox_mesh(self, show_dialog: bool = False):
        success, msg = replace_korblox_mesh()
        if success:
            self.append_log(f"🦴 [Korblox] {msg}")
            if show_dialog:
                QMessageBox.information(self, "Korblox 替換成功", f"✅ {msg}")
        else:
            self.append_log(f"⚠️ [Korblox] {msg}")
            if show_dialog:
                QMessageBox.warning(self, "Korblox 替換失敗", f"⚠️ {msg}")

    def append_log(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {text}")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        MouseController.unlock_cursor()
        self.trigger_mgr.stop()
        self.macro_worker.stop_continuous()
        self.auto_save()
        super().closeEvent(event)


# ==============================================================================
# Entry Point
# ==============================================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = AutoClickerApp()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
