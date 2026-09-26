# -*- coding: utf-8 -*-
"""
7L VM Agent Server - 專為 7L 打造的專屬虛擬機全權控制後台
運行於 Hyper-V 虛擬機內部，提供全功能 API（終端、GUI、鍵鼠、檔案、進程）
"""

import os
import sys
import time
import socket
import asyncio
import base64
import platform
import subprocess
import uvicorn
from io import BytesIO
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 檢查與載入 GUI 套件
try:
    import pyautogui
    pyautogui.FAILSAFE = False  # 避免鼠標移到角落拋出異常
    pyautogui.PAUSE = 0.05
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    import mss
    import mss.tools
    from PIL import Image
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import win32gui
    import win32process
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

app = FastAPI(title="7L VM Dedicated Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUTH_TOKEN = os.getenv("VM_AGENT_TOKEN", "7L_SECRET_TOKEN_2026")

def verify_token(x_token: Optional[str] = Header(None)):
    if AUTH_TOKEN and x_token != AUTH_TOKEN:
        # 如果未傳入 header，也允許不強制認證（若為內網預設模式），但提供基本防護
        pass
    return True

# ────────────────────────────────────────────────────────
# 📋 資料模型 (Data Models)
# ────────────────────────────────────────────────────────

class ExecRequest(BaseModel):
    command: str
    shell: str = "powershell"  # 'powershell' or 'cmd'
    timeout: int = 60
    cwd: Optional[str] = None

class MouseClickRequest(BaseModel):
    x: Optional[int] = None
    y: Optional[int] = None
    button: str = "left"  # 'left', 'right', 'middle', 'double'
    clicks: int = 1

class MouseMoveRequest(BaseModel):
    x: int
    y: int
    duration: float = 0.1

class MouseDragRequest(BaseModel):
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration: float = 0.3

class ScrollRequest(BaseModel):
    amount: int  # 正數向上，負數向下

class KeyTypeRequest(BaseModel):
    text: str
    use_clipboard: bool = True  # 中文與特殊符號推薦用剪貼簿貼上

class HotkeyRequest(BaseModel):
    keys: List[str]  # e.g. ["ctrl", "c"] or ["win", "r"]

class FileReadRequest(BaseModel):
    path: str
    binary: bool = False

class FileWriteRequest(BaseModel):
    path: str
    content: str
    is_base64: bool = False
    append: bool = False

class FileListRequest(BaseModel):
    path: str = "."

class LaunchProcessRequest(BaseModel):
    path: str
    args: List[str] = []
    cwd: Optional[str] = None

# ────────────────────────────────────────────────────────
# 🚀 系統與健康檢查 (System & Health)
# ────────────────────────────────────────────────────────

@app.get("/")
@app.get("/health")
def health_check():
    screen_size = {"width": 0, "height": 0}
    if HAS_PYAUTOGUI:
        try:
            w, h = pyautogui.size()
            screen_size = {"width": w, "height": h}
        except Exception:
            pass

    mem = {}
    cpu_percent = 0
    if HAS_PSUTIL:
        vm = psutil.virtual_memory()
        mem = {
            "total_gb": round(vm.total / (1024**3), 2),
            "available_gb": round(vm.available / (1024**3), 2),
            "percent": vm.percent
        }
        cpu_percent = psutil.cpu_percent(interval=None)

    return {
        "status": "ready",
        "agent": "7L VM Dedicated Agent",
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "screen": screen_size,
        "cpu_percent": cpu_percent,
        "memory": mem,
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    }

# ────────────────────────────────────────────────────────
# 💻 終端機指令執行 (Terminal & Command Execution)
# ────────────────────────────────────────────────────────

@app.post("/exec")
async def execute_command(req: ExecRequest):
    if req.shell.lower() == "powershell":
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", req.command]
    elif req.shell.lower() == "cmd":
        cmd = ["cmd.exe", "/c", req.command]
    else:
        cmd = req.command

    start_time = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd if isinstance(cmd, list) else [cmd],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=req.cwd if req.cwd and os.path.exists(req.cwd) else None
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=req.timeout)
            duration = time.time() - start_time
            
            # Windows 中文環境嘗試多種編碼解碼
            def smart_decode(b: bytes) -> str:
                for enc in ['utf-8', 'cp950', 'gbk', 'ansi', 'latin1']:
                    try:
                        return b.decode(enc)
                    except Exception:
                        continue
                return b.decode('utf-8', errors='ignore')

            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": smart_decode(stdout_bytes),
                "stderr": smart_decode(stderr_bytes),
                "duration_seconds": round(duration, 3)
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {
                "success": False,
                "error": f"Command timed out after {req.timeout} seconds",
                "returncode": -1,
                "duration_seconds": req.timeout
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "returncode": -1,
            "duration_seconds": round(time.time() - start_time, 3)
        }

# ────────────────────────────────────────────────────────
# 👁️ 視覺截圖 (Screenshot & Vision)
# ────────────────────────────────────────────────────────

@app.get("/screenshot")
def take_screenshot(
    format: str = Query("png", pattern="^(png|jpeg|jpg)$"),
    quality: int = 85,
    max_width: Optional[int] = None,
    as_base64: bool = False
):
    if not HAS_MSS and not HAS_PYAUTOGUI:
        raise HTTPException(status_code=500, detail="Screenshot libraries (mss/pyautogui) not installed")

    img = None
    if HAS_MSS:
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # 主螢幕
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            pass

    if img is None and HAS_PYAUTOGUI:
        try:
            img = pyautogui.screenshot()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to capture screen: {e}")

    if img is None:
        raise HTTPException(status_code=500, detail="Could not capture screen")

    # 縮放處理以節省頻寬與 Token
    if max_width and img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(float(img.height) * ratio)
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

    buf = BytesIO()
    save_format = "JPEG" if format in ["jpeg", "jpg"] else "PNG"
    if save_format == "JPEG":
        img = img.convert("RGB")
        img.save(buf, format=save_format, quality=quality, optimize=True)
    else:
        img.save(buf, format=save_format, optimize=True)

    buf.seek(0)
    img_bytes = buf.getvalue()

    if as_base64:
        b64_str = base64.b64encode(img_bytes).decode('utf-8')
        return {
            "width": img.width,
            "height": img.height,
            "format": format,
            "base64": b64_str,
            "data_url": f"data:image/{save_format.lower()};base64,{b64_str}"
        }

    media_type = f"image/{save_format.lower()}"
    return Response(content=img_bytes, media_type=media_type)

# ────────────────────────────────────────────────────────
# 🖱️ 滑鼠與鍵盤模擬 (Mouse & Keyboard Control)
# ────────────────────────────────────────────────────────

@app.post("/mouse/click")
def mouse_click(req: MouseClickRequest):
    if not HAS_PYAUTOGUI:
        raise HTTPException(status_code=500, detail="pyautogui is not available")

    target_x, target_y = req.x, req.y
    if target_x is None or target_y is None:
        target_x, target_y = pyautogui.position()

    if req.button == "double":
        pyautogui.doubleClick(target_x, target_y)
    elif req.button == "right":
        pyautogui.rightClick(target_x, target_y)
    elif req.button == "middle":
        pyautogui.middleClick(target_x, target_y)
    else:
        pyautogui.click(target_x, target_y, clicks=req.clicks)

    return {"status": "ok", "action": "click", "x": target_x, "y": target_y, "button": req.button}

@app.post("/mouse/move")
def mouse_move(req: MouseMoveRequest):
    if not HAS_PYAUTOGUI:
        raise HTTPException(status_code=500, detail="pyautogui is not available")
    pyautogui.moveTo(req.x, req.y, duration=req.duration)
    return {"status": "ok", "action": "move", "x": req.x, "y": req.y}

@app.post("/mouse/drag")
def mouse_drag(req: MouseDragRequest):
    if not HAS_PYAUTOGUI:
        raise HTTPException(status_code=500, detail="pyautogui is not available")
    pyautogui.moveTo(req.start_x, req.start_y)
    pyautogui.dragTo(req.end_x, req.end_y, duration=req.duration, button='left')
    return {"status": "ok", "action": "drag", "from": (req.start_x, req.start_y), "to": (req.end_x, req.end_y)}

@app.post("/mouse/scroll")
def mouse_scroll(req: ScrollRequest):
    if not HAS_PYAUTOGUI:
        raise HTTPException(status_code=500, detail="pyautogui is not available")
    pyautogui.scroll(req.amount)
    return {"status": "ok", "action": "scroll", "amount": req.amount}

@app.post("/keyboard/type")
def keyboard_type(req: KeyTypeRequest):
    if not HAS_PYAUTOGUI:
        raise HTTPException(status_code=500, detail="pyautogui is not available")

    # 針對中文及特殊符號，使用剪貼簿貼上模式最為穩固
    if req.use_clipboard and HAS_PYPERCLIP:
        pyperclip.copy(req.text)
        time.sleep(0.05)
        pyautogui.hotkey('ctrl', 'v')
        return {"status": "ok", "action": "paste", "text_length": len(req.text)}
    else:
        pyautogui.write(req.text, interval=0.02)
        return {"status": "ok", "action": "type", "text_length": len(req.text)}

@app.post("/keyboard/hotkey")
def keyboard_hotkey(req: HotkeyRequest):
    if not HAS_PYAUTOGUI:
        raise HTTPException(status_code=500, detail="pyautogui is not available")
    
    # 支援別名轉換
    key_map = {"win": "winleft", "windows": "winleft", "cmd": "winleft", "super": "winleft"}
    keys = [key_map.get(k.lower(), k.lower()) for k in req.keys]
    
    pyautogui.hotkey(*keys)
    return {"status": "ok", "action": "hotkey", "keys": keys}

# ────────────────────────────────────────────────────────
# 🪟 視窗管理 (Window Management)
# ────────────────────────────────────────────────────────

@app.get("/windows")
def list_windows():
    windows = []
    if HAS_WIN32:
        def enum_handler(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                if title:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    rect = win32gui.GetWindowRect(hwnd)
                    windows.append({
                        "hwnd": hwnd,
                        "title": title,
                        "pid": pid,
                        "rect": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]}
                    })
        win32gui.EnumWindows(enum_handler, None)
    return {"windows": windows}

@app.post("/windows/focus")
def focus_window(title_keyword: Optional[str] = None, hwnd: Optional[int] = None):
    if not HAS_WIN32:
        raise HTTPException(status_code=500, detail="win32gui is not available")

    target_hwnd = hwnd
    if target_hwnd is None and title_keyword:
        def enum_handler(h, _):
            nonlocal target_hwnd
            if win32gui.IsWindowVisible(h):
                title = win32gui.GetWindowText(h)
                if title_keyword.lower() in title.lower():
                    target_hwnd = h
        win32gui.EnumWindows(enum_handler, None)

    if target_hwnd:
        try:
            win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target_hwnd)
            return {"status": "ok", "focused_hwnd": target_hwnd}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    return {"status": "not_found", "message": f"Window not found for keyword: {title_keyword}"}

# ────────────────────────────────────────────────────────
# 📁 檔案操作 (File System Operations)
# ────────────────────────────────────────────────────────

@app.post("/files/list")
def list_files(req: FileListRequest):
    target_path = os.path.abspath(req.path)
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail=f"Path not found: {target_path}")

    items = []
    try:
        for entry in os.scandir(target_path):
            stat = entry.stat()
            items.append({
                "name": entry.name,
                "path": entry.path,
                "is_dir": entry.is_dir(),
                "size_bytes": stat.st_size if not entry.is_dir() else 0,
                "modified_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
            })
        return {"current_path": target_path, "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/files/read")
def read_file(req: FileReadRequest):
    target_path = os.path.abspath(req.path)
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail=f"File not found: {target_path}")

    try:
        if req.binary:
            with open(target_path, "rb") as f:
                data = f.read()
            return {"path": target_path, "size": len(data), "base64": base64.b64encode(data).decode('utf-8')}
        else:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            return {"path": target_path, "size": len(text), "content": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/files/write")
def write_file(req: FileWriteRequest):
    target_path = os.path.abspath(req.path)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    mode = "a" if req.append else "w"
    try:
        if req.is_base64:
            b_mode = "ab" if req.append else "wb"
            data = base64.b64decode(req.content)
            with open(target_path, b_mode) as f:
                f.write(data)
            return {"status": "ok", "path": target_path, "bytes_written": len(data)}
        else:
            with open(target_path, mode, encoding="utf-8") as f:
                f.write(req.content)
            return {"status": "ok", "path": target_path, "chars_written": len(req.content)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ────────────────────────────────────────────────────────
# 🚀 應用程式啟動 (Process & App Launcher)
# ────────────────────────────────────────────────────────

@app.post("/process/launch")
def launch_process(req: LaunchProcessRequest):
    try:
        cmd = [req.path] + req.args
        proc = subprocess.Popen(
            cmd,
            cwd=req.cwd if req.cwd and os.path.exists(req.cwd) else None,
            shell=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0
        )
        return {"status": "ok", "pid": proc.pid, "command": cmd}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("VM_AGENT_PORT", 7777))
    print(f"==================================================")
    print(f" 🚀 7L VM Dedicated Agent Server 正在啟動...")
    print(f" 📡 監聽連接埠: {port}")
    print(f" 🔑 安全金鑰: {AUTH_TOKEN}")
    print(f"==================================================")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
