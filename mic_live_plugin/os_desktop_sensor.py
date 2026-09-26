# -*- coding: utf-8 -*-
"""
💻 7L Windows 底層桌面與應用程式感應中樞 (OS Desktop Sensor)
- 透過 Windows Win32 原生 API 與 psutil 獲取 1 毫秒級底層真實進程與視窗情報
- 零截圖負載、零 GPU 開銷，秒級洞察老爸當前最前端活躍焦點視窗與桌面上運行的應用程式
- 支援任意執行緒呼叫 (自動關聯 Windows Input Desktop)
"""

import os
import sys
import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional, Any
import psutil

# 忽略的系統內部或無實質內容的隱形視窗
IGNORED_PROCESSES = {
    "shellexperiencehost.exe", "searchhost.exe", "textinputhost.exe",
    "startmenuexperiencehost.exe", "crossdeviceresume.exe", "applicationframehost.exe",
    "system", "idle", "registry", "smss.exe", "csrss.exe", "wininit.exe"
}

IGNORED_WINDOW_TITLES = {
    "program manager", "settings", "default ime", "msctfime ui",
    "windows input experience", "task view", "crossdeviceresume",
    "snap assist", "", "nvidia geforce overlay"
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class OSDesktopSensor:
    def __init__(self):
        self._cached_media_info = []
        self._cached_media_time = 0.0
        self._gsmtc_encoded_cmd = None

    def get_windows_media_info(self, max_cache_age: float = 3.0) -> List[Dict[str, str]]:
        """
        透過 Windows 原生 GSMTC (GlobalSystemMediaTransportControls)
        獲取系統當前正在播放的多媒體曲目與演出者 (支援 Chrome, Spotify, Edge, PotPlayer 等)
        """
        import time
        now = time.time()
        if (now - self._cached_media_time) < max_cache_age and self._cached_media_info:
            return self._cached_media_info

        if not self._gsmtc_encoded_cmd:
            import base64
            ps_code = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media, ContentType=WindowsRuntime] | Out-Null
$asyncOp = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()
$mgr = Await $asyncOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$sessions = @()
$curr = $mgr.GetCurrentSession()
if ($curr) { $sessions += $curr }
$all = $mgr.GetSessions()
if ($all) { foreach ($s in $all) { if ($sessions -notcontains $s) { $sessions += $s } } }
foreach ($s in $sessions) {
    try {
        $propAsync = $s.TryGetMediaPropertiesAsync()
        $props = Await $propAsync ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
        if ($props.Title) {
            $line = $props.Title + ' ||| ' + $props.Artist + ' ||| ' + $s.SourceAppUserModelId
            $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($line))
            Write-Output ('B64:' + $b64)
        }
    } catch {}
}
"""
            self._gsmtc_encoded_cmd = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")

        try:
            import subprocess, base64
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", self._gsmtc_encoded_cmd]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2.0)
            items = []
            seen = set()
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("B64:"):
                    raw = base64.b64decode(line[4:]).decode("utf-8", errors="ignore")
                    parts = raw.split(" ||| ")
                    title = parts[0].strip() if len(parts) > 0 else ""
                    artist = parts[1].strip() if len(parts) > 1 else ""
                    app = parts[2].strip() if len(parts) > 2 else ""
                    if "chrome" in app.lower(): app_name = "Chrome"
                    elif "spotify" in app.lower(): app_name = "Spotify"
                    elif "edge" in app.lower(): app_name = "Edge"
                    else: app_name = app.split("!")[-1].replace(".exe", "")

                    k = (title, artist)
                    if title and k not in seen:
                        seen.add(k)
                        items.append({
                            "title": title,
                            "artist": artist,
                            "app": app_name
                        })
            self._cached_media_info = items
            self._cached_media_time = now
            return items
        except Exception:
            return self._cached_media_info if self._cached_media_info else []

    def _ensure_desktop_access(self):
        """確保當前執行緒連接至 Windows 互動式桌面 (InputDesktop)"""
        try:
            h_desk = user32.OpenInputDesktop(0, False, 0x01FF) # GENERIC_ALL
            if h_desk:
                user32.SetThreadDesktop(h_desk)
                return h_desk
        except Exception:
            pass
        return None

    def get_foreground_window(self) -> Dict[str, Any]:
        """
        獲取當前最前端活躍視窗資訊 (老爸正在操作的焦點視窗)
        
        Returns:
            Dict: {"pid": int, "process_name": str, "window_title": str, "app_label": str}
        """
        h_desk = self._ensure_desktop_access()
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return {"pid": 0, "process_name": "", "window_title": "", "app_label": "未知"}

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()

            pname = ""
            if pid.value > 0:
                try:
                    pname = psutil.Process(pid.value).name()
                except Exception:
                    pname = ""

            app_label = self._guess_app_label(pname, title)

            return {
                "pid": pid.value,
                "process_name": pname,
                "window_title": title,
                "app_label": app_label
            }
        except Exception:
            return {"pid": 0, "process_name": "", "window_title": "", "app_label": "未知"}
        finally:
            if h_desk:
                try: user32.CloseDesktop(h_desk)
                except Exception: pass

    def get_visible_windows(self, max_count: int = 10) -> List[Dict[str, str]]:
        """枚舉目前桌面上真實可見的工作視窗列表"""
        h_desk = self._ensure_desktop_access()
        results = []
        seen_titles = set()

        def enum_cb(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True

            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            title_lower = title.lower()

            if not title or title_lower in IGNORED_WINDOW_TITLES:
                return True

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pname = ""
            if pid.value > 0:
                try:
                    pname = psutil.Process(pid.value).name()
                except Exception:
                    pname = ""

            if pname.lower() in IGNORED_PROCESSES:
                return True

            key = f"{pname}:{title}"
            if key not in seen_titles:
                seen_titles.add(key)
                results.append({
                    "process_name": pname,
                    "window_title": title,
                    "app_label": self._guess_app_label(pname, title)
                })

            return len(results) < max_count

        try:
            cb_func = WNDENUMPROC(enum_cb)
            if h_desk:
                user32.EnumDesktopWindows(h_desk, cb_func, 0)
            else:
                user32.EnumWindows(cb_func, 0)
        except Exception:
            pass
        finally:
            if h_desk:
                try: user32.CloseDesktop(h_desk)
                except Exception: pass

        return results

    def _guess_app_label(self, pname: str, title: str) -> str:
        """根據進程名和標題提取友善中文名稱"""
        p_lower = pname.lower()
        t_lower = title.lower()

        if "roblox" in p_lower or "roblox" in t_lower:
            return "Roblox (遊戲)"
        elif "antigravity" in p_lower or "antigravity" in t_lower or "cursor" in p_lower or "code" in p_lower or ".py" in t_lower:
            return "AI 程式編輯器 (寫 Code 中)"
        elif "discord" in p_lower or "discord" in t_lower:
            return "Discord 社群聊天"
        elif "chrome" in p_lower:
            return "Google Chrome 瀏覽器"
        elif "msedge" in p_lower or "edge" in p_lower:
            return "Edge 瀏覽器"
        elif "vtube" in p_lower or "vts" in p_lower:
            return "VTube Studio (妳的身體)"
        elif "auto_clicker" in t_lower or "xmbc" in t_lower:
            return "自動連點巨集工具"
        elif "piano" in p_lower or "piano" in t_lower or "鋼琴" in title:
            return "88鍵虛擬鋼琴"
        elif "spotify" in p_lower:
            return "Spotify 音樂"
        elif "steam" in p_lower:
            return "Steam 遊戲平台"
        elif "obs" in p_lower:
            return "OBS 直播推流軟體"
        
        # 預設直接精簡標題
        clean_t = title.split(" - ")[0].split(" — ")[0].strip()
        return clean_t if len(clean_t) <= 15 else (pname.replace(".exe", ""))

    def build_os_telemetry_prompt(self) -> str:
        """
        生成專門注入大腦 System Prompt 的作業系統底層即時情報
        """
        fg = self.get_foreground_window()
        visible_apps = self.get_visible_windows(max_count=8)

        fg_proc = fg.get("process_name", "")
        fg_title = fg.get("window_title", "")
        fg_label = fg.get("app_label", "桌面")

        lines = [
            "【💻 電腦底層行程與當前焦點情報 (Windows 原生 0 延遲硬體遙測)】：",
        ]

        if fg_title or fg_proc:
            lines.append(f"- 🎯 最前端活躍焦點視窗 (老爸此刻正在操作)：【{fg_label}】(進程: {fg_proc} | 視窗標題: 「{fg_title}」)")
        else:
            lines.append("- 🎯 最前端焦點視窗：老爸目前停留在桌面或待命狀態。")

        # 列出其他可見的應用程式
        other_apps = []
        for app in visible_apps:
            p = app.get("process_name", "")
            t = app.get("window_title", "")
            label = app.get("app_label", "")
            if p != fg_proc or t != fg_title:
                other_apps.append(f"{label} (「{t[:20]}」)" if t else label)

        if other_apps:
            lines.append(f"- 🗂️ 背景同時運行/開啟中的應用程式：{'、'.join(other_apps[:6])}")

        # 🎵 Windows 系統底層即時媒體播放情報 (GSMTC)
        media_list = self.get_windows_media_info(max_cache_age=3.5)
        if media_list:
            m_strs = []
            for m in media_list:
                desc = f"[{m.get('app', '媒體')}] 『{m.get('title', '')}』"
                if m.get("artist"):
                    desc += f" (演出者: {m['artist']})"
                m_strs.append(desc)
            lines.append(f"- 🎵 電腦正在播放的音樂/影片 (Windows GSMTC 原生硬體級精準資訊)：{' ｜ '.join(m_strs)}")

        lines.append("- 💡 互動指引：妳【100% 確切掌握】老爸當前正在使用或玩什麼程式，以及電腦背景正在播放的確切歌曲/影片！若老爸問起「妳知道我在開什麼/做什麼/聽什麼歌嗎？」，請直接自信點名說出（如歌曲名、演奏者、Roblox、寫 Code 等），無需依賴截圖，因為這是 Windows 底層核心直報的精準即時數據！")

        return "\n".join(lines)


# 全域單例
os_desktop_sensor = OSDesktopSensor()
