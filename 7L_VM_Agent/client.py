# -*- coding: utf-8 -*-
"""
7L VM Controller Client
7L 用來操控 Hyper-V 專屬虛擬機的客戶端 API 封裝
"""

import requests
import json
import base64
from typing import Optional, List, Dict, Any, Union

class VMAgentClient:
    def __init__(self, host: str = "172.22.212.232", port: int = 7777, token: str = "7L_SECRET_TOKEN_2026", timeout: float = 10.0):
        self.base_url = f"http://{host}:{port}"
        self.token = token
        self.timeout = timeout
        self.headers = {
            "x-token": self.token,
            "Content-Type": "application/json"
        }

    def ping(self) -> bool:
        """測試虛擬機 Agent 是否在線"""
        try:
            r = requests.get(f"{self.base_url}/health", headers=self.headers, timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def get_status(self) -> Dict[str, Any]:
        """取得虛擬機的狀態、規格、螢幕解析度、CPU/記憶體使用量"""
        r = requests.get(f"{self.base_url}/health", headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def exec(self, command: str, shell: str = "powershell", timeout: int = 60, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        在虛擬機內執行命令（PowerShell 或 CMD）
        返回: {"success": bool, "returncode": int, "stdout": str, "stderr": str, "duration_seconds": float}
        """
        payload = {
            "command": command,
            "shell": shell,
            "timeout": timeout,
            "cwd": cwd
        }
        r = requests.post(f"{self.base_url}/exec", json=payload, headers=self.headers, timeout=timeout + 5)
        r.raise_for_status()
        return r.json()

    def get_screenshot(self, as_base64: bool = True, max_width: Optional[int] = 1280, format: str = "jpeg", quality: int = 80) -> Union[Dict[str, Any], bytes]:
        """
        取得虛擬機目前桌面截圖
        若 as_base64=True，返回包含 {"base64": ..., "data_url": ..., "width": ..., "height": ...}
        若 as_base64=False，返回圖片 binary bytes
        """
        params = {
            "format": format,
            "quality": quality,
            "as_base64": "true" if as_base64 else "false"
        }
        if max_width:
            params["max_width"] = max_width

        r = requests.get(f"{self.base_url}/screenshot", params=params, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        if as_base64:
            return r.json()
        return r.content

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
        """在虛擬機螢幕上點擊滑鼠 (button: 'left', 'right', 'double', 'middle')"""
        payload = {"x": x, "y": y, "button": button, "clicks": clicks}
        r = requests.post(f"{self.base_url}/mouse/click", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def move(self, x: int, y: int, duration: float = 0.1) -> Dict[str, Any]:
        """移動滑鼠至指定座標"""
        payload = {"x": x, "y": y, "duration": duration}
        r = requests.post(f"{self.base_url}/mouse/move", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.3) -> Dict[str, Any]:
        """拖曳滑鼠"""
        payload = {"start_x": start_x, "start_y": start_y, "end_x": end_x, "end_y": end_y, "duration": duration}
        r = requests.post(f"{self.base_url}/mouse/drag", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def scroll(self, amount: int) -> Dict[str, Any]:
        """滾動滑鼠滾輪（正數向上，負數向下）"""
        payload = {"amount": amount}
        r = requests.post(f"{self.base_url}/mouse/scroll", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def type(self, text: str, use_clipboard: bool = True) -> Dict[str, Any]:
        """在虛擬機中輸入文字（支援中文字串貼上）"""
        payload = {"text": text, "use_clipboard": use_clipboard}
        r = requests.post(f"{self.base_url}/keyboard/type", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def hotkey(self, *keys: str) -> Dict[str, Any]:
        """按下快捷鍵組合，例如 hotkey("win", "r") 或 hotkey("ctrl", "shift", "esc")"""
        payload = {"keys": list(keys)}
        r = requests.post(f"{self.base_url}/keyboard/hotkey", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def list_windows(self) -> List[Dict[str, Any]]:
        """列出虛擬機目前所有可視視窗"""
        r = requests.get(f"{self.base_url}/windows", headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("windows", [])

    def focus_window(self, title_keyword: str) -> Dict[str, Any]:
        """將指定標題關鍵字的視窗切換至最前景"""
        params = {"title_keyword": title_keyword}
        r = requests.post(f"{self.base_url}/windows/focus", params=params, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def list_files(self, path: str = ".") -> Dict[str, Any]:
        """列出虛擬機指定目錄下的檔案"""
        payload = {"path": path}
        r = requests.post(f"{self.base_url}/files/list", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def read_file(self, path: str, binary: bool = False) -> Dict[str, Any]:
        """讀取虛擬機內的檔案內容"""
        payload = {"path": path, "binary": binary}
        r = requests.post(f"{self.base_url}/files/read", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def write_file(self, path: str, content: Union[str, bytes], append: bool = False) -> Dict[str, Any]:
        """寫入檔案到虛擬機內"""
        is_bytes = isinstance(content, bytes)
        payload = {
            "path": path,
            "content": base64.b64encode(content).decode('utf-8') if is_bytes else content,
            "is_base64": is_bytes,
            "append": append
        }
        r = requests.post(f"{self.base_url}/files/write", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def launch_app(self, app_path: str, args: Optional[List[str]] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
        """在虛擬機中啟動應用程式（如 chrome.exe、notepad.exe 等）"""
        payload = {"path": app_path, "args": args or [], "cwd": cwd}
        r = requests.post(f"{self.base_url}/process/launch", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

if __name__ == "__main__":
    import sys
    client = VMAgentClient()
    print(f"正在測試連線至 7L 虛擬機 (172.22.212.232:7777)...")
    if client.ping():
        print(" [✔️] 7L 虛擬機連線成功！")
        status = client.get_status()
        print(" 狀態資訊:", json.dumps(status, indent=2, ensure_ascii=False))
    else:
        print(" [⚠️] 目前無法連線至虛擬機，請確認虛擬機內已執行 install.bat 或 server.py。")
