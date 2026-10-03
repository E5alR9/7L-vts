# -*- coding: utf-8 -*-
"""
==============================================================================
  7L 專屬超高清「鋼琴」NDI 透明懸浮接收器 (7L Piano Transparent NDI Viewer)
  專為 Virtual Piano / Synthesia / SeeMusic / 虛擬機琴鍵設計
  核心特色：
   1.  完美橫向琴鍵寬條比例 (預設 980x260，支援滾輪等比縮放 & 自由拉伸)
   2.  內建 NumPy 即時智慧去背 (支援去黑底 / 去綠幕 / 去藍幕 / 去白底)
   3.  即時上下左右邊界裁切 (輕鬆裁除 VM 視窗邊框與工作列，只留琴鍵)
   4.  支援 Windows 滑鼠點擊穿透 (Click-Through) + 永遠置頂 (Always-on-Top)
   5.  支援 Hyper-V / VMware 跨網段直連與局域網 NDI 來源自動搜尋配對
   6.  60 FPS 硬件級超低延遲渲染，極致順暢
==============================================================================
"""

import sys
import os
import time
import json
import ctypes
import numpy as np
import NDIlib as ndi

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "7l_piano_ndi_config.json")

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QSize, QRect, QTimer
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QFont, QAction, 
    QMouseEvent, QWheelEvent, QPaintEvent, QCursor
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMenu, QComboBox, QPushButton, 
    QHBoxLayout, QVBoxLayout, QLabel, QSizeGrip, QDialog,
    QSpinBox, QFormLayout, QDialogButtonBox, QMessageBox
)

# Windows API 點擊穿透常數
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

# 去背模式常數
KEY_NONE = "NONE"          # 原生 Alpha (無額外去背)
KEY_BLACK = "BLACK"        # 去黑底 (最適合大部分黑底虛擬鋼琴與瀑布流)
KEY_GREEN = "GREEN"        # 去綠幕 (Chroma Key Green)
KEY_BLUE = "BLUE"          # 去藍幕 (Chroma Key Blue)
KEY_WHITE = "WHITE"        # 去白底 (Luma Key White)


class PianoNDIWorkerThread(QThread):
    """ NDI 串流背景接收協程 (極致 60 FPS + 即時去背 & 裁切)"""
    frame_received = pyqtSignal(QImage)
    source_list_updated = pyqtSignal(list)
    status_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.current_source_name = ""
        self.recv_handle = None
        self.find_handle = None

        # 影像處理參數
        self.color_swap = False          # RGB/BGR 修正
        self.key_mode = KEY_BLACK        # 預設開啟「去黑底」，讓虛擬鋼琴直接懸浮透明
        self.black_threshold = 28        # 去黑閥值 (0~100)
        self.green_threshold = 0.5       # 去綠敏感度
        
        # 邊界裁切比例 (0.0 ~ 0.5)
        self.crop_top = 0.0
        self.crop_bottom = 0.0
        self.crop_left = 0.0
        self.crop_right = 0.0

    def run(self):
        if not ndi.initialize():
            self.status_message.emit(" NDI 初始化失敗！")
            return

        # 建立 NDI 來源探索器 (配置本機與局域網探索)
        find_settings = ndi.FindCreate()
        find_settings.show_local_sources = True
        find_settings.extra_ips = "127.0.0.1,localhost,172.31.116.232,172.22.212.232,172.22.208.1,172.31.112.1,192.168.1.104,192.168.1.0/24"
        self.find_handle = ndi.find_create_v2(find_settings)
        if not self.find_handle:
            self.status_message.emit(" 無法建立 NDI 尋找器")
            return

        self.status_message.emit(" 正在搜尋本機 / 局域網鋼琴 NDI 來源...")

        last_search_time = 0
        discovered_names = []

        while self.running:
            # 每 1.5 秒自動刷新來源清單
            now = time.time()
            if now - last_search_time > 1.5:
                last_search_time = now
                if ndi.find_wait_for_sources(self.find_handle, 40):
                    sources = ndi.find_get_current_sources(self.find_handle)
                    s_names = [s.ndi_name for s in sources]
                    if s_names != discovered_names:
                        discovered_names = s_names
                        self.source_list_updated.emit(discovered_names)

            # 若尚未連接來源，嘗試自動連接本機鋼琴來源
            if not self.recv_handle and discovered_names:
                target = self.current_source_name if self.current_source_name in discovered_names else ""
                if not target:
                    # 優先配對包含 piano, synthesia, seemusic, keysight, 7l 等關鍵字
                    priority_keywords = ["piano", "seemusic", "synthesia", "keysight", "screen", "7l", "capture", "vm"]
                    for kw in priority_keywords:
                        for name in discovered_names:
                            if kw in name.lower():
                                target = name
                                break
                        if target:
                            break
                    
                    # 若無特定關鍵字，則連第一個可用來源
                    if not target and discovered_names:
                        target = discovered_names[0]

                if target:
                    self.connect_to_source(target)

            # 接收影像影格
            if self.recv_handle:
                t, v, a, m = ndi.recv_capture_v2(self.recv_handle, 80)
                if t == ndi.FRAME_TYPE_VIDEO and v.data is not None:
                    try:
                        w, h = v.xres, v.yres
                        frame_data = np.copy(v.data)

                        # 1. 邊界裁切 (Crop)
                        y1 = int(h * self.crop_top)
                        y2 = int(h * (1.0 - self.crop_bottom))
                        x1 = int(w * self.crop_left)
                        x2 = int(w * (1.0 - self.crop_right))
                        if y2 > y1 + 10 and x2 > x1 + 10:
                            frame_data = frame_data[y1:y2, x1:x2]
                            h_crop, w_crop = frame_data.shape[:2]
                        else:
                            h_crop, w_crop = h, w

                        # 2. 色彩通道反轉 (RGB / BGR 修正)
                        if self.color_swap:
                            frame_data = frame_data[:, :, [2, 1, 0, 3]]

                        # 3. 即時去背演算法 (NumPy 向量化加速，耗時 < 1ms)
                        r = frame_data[:, :, 0].astype(np.float32)
                        g = frame_data[:, :, 1].astype(np.float32)
                        b = frame_data[:, :, 2].astype(np.float32)

                        if self.key_mode == KEY_BLACK:
                            # 去黑底模式 (亮度過濾 + 平滑羽化過渡)
                            brightness = np.maximum(r, np.maximum(g, b))
                            thresh = float(self.black_threshold)
                            # 在 thresh/2 ~ thresh 之間進行 alpha 平滑漸變
                            alpha_mask = np.clip((brightness - (thresh * 0.4)) / (thresh * 0.6 + 1e-5), 0.0, 1.0)
                            frame_data[:, :, 3] = (frame_data[:, :, 3].astype(np.float32) * alpha_mask).astype(np.uint8)

                        elif self.key_mode == KEY_GREEN:
                            # 去綠幕模式 (Green Screen Chroma Key)
                            green_diff = g - np.maximum(r, b)
                            green_mask = green_diff > 30
                            frame_data[:, :, 3][green_mask] = 0

                        elif self.key_mode == KEY_BLUE:
                            # 去藍幕模式 (Blue Screen Chroma Key)
                            blue_diff = b - np.maximum(r, g)
                            blue_mask = blue_diff > 30
                            frame_data[:, :, 3][blue_mask] = 0

                        elif self.key_mode == KEY_WHITE:
                            # 去白底模式 (White Luma Key)
                            min_rgb = np.minimum(r, np.minimum(g, b))
                            white_mask = min_rgb > 220
                            frame_data[:, :, 3][white_mask] = 0

                        # 轉為 QImage (Format_RGBA8888)
                        bytes_per_line = w_crop * 4
                        qimg = QImage(frame_data.data, w_crop, h_crop, bytes_per_line, QImage.Format.Format_RGBA8888)

                        self.frame_received.emit(qimg.copy())
                    except Exception as e:
                        pass
                    finally:
                        ndi.recv_free_video_v2(self.recv_handle, v)
                elif t == ndi.FRAME_TYPE_AUDIO:
                    ndi.recv_free_audio_v2(self.recv_handle, a)
                elif t == ndi.FRAME_TYPE_METADATA:
                    ndi.recv_free_metadata(self.recv_handle, m)
            else:
                time.sleep(0.04)

        # 清理資源
        self.disconnect_source()
        if self.find_handle:
            ndi.find_destroy(self.find_handle)
        ndi.destroy()

    def connect_to_source(self, source_name: str):
        """連接到指定 NDI 來源"""
        self.disconnect_source()
        self.current_source_name = source_name
        self.status_message.emit(f" 連接鋼琴來源: {source_name}")

        sources = ndi.find_get_current_sources(self.find_handle)
        target_source = None
        for s in sources:
            if s.ndi_name == source_name:
                target_source = s
                break

        if target_source:
            recv_create = ndi.RecvCreateV3()
            recv_create.source_to_connect_to = target_source
            recv_create.color_format = ndi.RECV_COLOR_FORMAT_RGBX_RGBA
            recv_create.bandwidth = ndi.RECV_BANDWIDTH_HIGHEST
            self.recv_handle = ndi.recv_create_v3(recv_create)
            if self.recv_handle:
                self.status_message.emit(f" 鋼琴畫面已連接: {source_name}")
            else:
                self.status_message.emit(f" 連接失敗: {source_name}")
                self.current_source_name = ""
        else:
            self.status_message.emit(f" 找不到來源: {source_name}")
            self.current_source_name = ""

    def disconnect_source(self):
        if self.recv_handle:
            ndi.recv_destroy(self.recv_handle)
            self.recv_handle = None

    def stop(self):
        self.running = False
        self.wait()


class CropSettingsDialog(QDialog):
    """ 邊界裁切設定對話框"""
    def __init__(self, parent=None, top=0, bottom=0, left=0, right=0):
        super().__init__(parent)
        self.setWindowTitle(" 鋼琴畫面裁切設定 (只保留琴鍵/瀑布流)")
        self.resize(360, 220)
        self.setStyleSheet("""
            QDialog {
                background: #1e1e28;
                color: #ffffff;
                font-family: 'Segoe UI', 'Microsoft JhengHei';
            }
            QLabel {
                color: #ffb8d9;
                font-size: 13px;
                font-weight: bold;
            }
            QSpinBox {
                background: #2a2a38;
                border: 1px solid #ff80b3;
                border-radius: 4px;
                color: #ffffff;
                padding: 4px 8px;
                font-size: 13px;
                min-width: 80px;
            }
            QPushButton {
                background: #ff4081;
                border: none;
                border-radius: 4px;
                color: white;
                font-weight: bold;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background: #ff669a;
            }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.sp_top = QSpinBox(self)
        self.sp_top.setRange(0, 45)
        self.sp_top.setSuffix(" %")
        self.sp_top.setValue(int(top * 100))
        form.addRow("頂部裁切 (裁除選單/工具列):", self.sp_top)

        self.sp_bottom = QSpinBox(self)
        self.sp_bottom.setRange(0, 45)
        self.sp_bottom.setSuffix(" %")
        self.sp_bottom.setValue(int(bottom * 100))
        form.addRow("底部裁切 (裁除狀態列/工作列):", self.sp_bottom)

        self.sp_left = QSpinBox(self)
        self.sp_left.setRange(0, 45)
        self.sp_left.setSuffix(" %")
        self.sp_left.setValue(int(left * 100))
        form.addRow("左側裁切:", self.sp_left)

        self.sp_right = QSpinBox(self)
        self.sp_right.setRange(0, 45)
        self.sp_right.setSuffix(" %")
        self.sp_right.setValue(int(right * 100))
        form.addRow("右側裁切:", self.sp_right)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_values(self):
        return (
            self.sp_top.value() / 100.0,
            self.sp_bottom.value() / 100.0,
            self.sp_left.value() / 100.0,
            self.sp_right.value() / 100.0
        )


class PianoNDIViewerWindow(QWidget):
    """ 7L 專屬鋼琴 NDI 透明懸浮接收器"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(" 7L 鋼琴 NDI 透明接收器")
        
        # 鋼琴專屬寬橫條長寬比 (預設 980 x 260)
        self.setMinimumSize(320, 100)
        self.resize(980, 260)

        # 視窗屬性：無邊框 + 全透明背景 + 預設置頂
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        # 互動狀態變數
        self.drag_position = QPoint()
        self.current_pixmap = None
        self.is_always_on_top = True
        self.is_click_through = False
        self.show_control_bar = True
        self.background_mode = "TRANSPARENT"  # TRANSPARENT, GREEN, DARK_GLASS
        self.last_connected_source = ""

        # 定時防抖存檔器 (避免拖曳時頻繁寫入硬碟)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.save_config)

        # 初始化 UI
        self.init_ui()

        # 啟動 NDI 背景協程
        self.ndi_thread = PianoNDIWorkerThread()
        self.ndi_thread.frame_received.connect(self.on_frame_received)
        self.ndi_thread.source_list_updated.connect(self.on_source_list_updated)
        self.ndi_thread.status_message.connect(self.on_status_message)
        self.ndi_thread.start()

        # 恢復上次關閉時的位置、大小、去背與裁切設定
        self.load_config()

    def init_ui(self):
        """建立頂部精緻鋼琴控制列"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(0)

        # 頂部半透明控制面板
        self.ctrl_bar = QWidget(self)
        self.ctrl_bar.setStyleSheet("""
            QWidget {
                background: rgba(16, 16, 24, 0.88);
                border: 1px solid rgba(255, 120, 180, 0.45);
                border-radius: 8px;
                color: #ffffff;
                font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif;
                font-size: 12px;
            }
            QComboBox {
                background: rgba(35, 35, 48, 0.92);
                border: 1px solid rgba(255, 140, 200, 0.5);
                border-radius: 4px;
                padding: 3px 8px;
                color: #ffd1e6;
                font-weight: bold;
                min-width: 160px;
            }
            QComboBox QAbstractItemView {
                background: #181824;
                color: #ffffff;
                selection-background-color: #e0457b;
            }
            QPushButton {
                background: rgba(255, 64, 129, 0.28);
                border: 1px solid rgba(255, 160, 210, 0.6);
                border-radius: 4px;
                padding: 4px 9px;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 64, 129, 0.65);
                border-color: #ff80b3;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        ctrl_layout = QHBoxLayout(self.ctrl_bar)
        ctrl_layout.setContentsMargins(8, 4, 8, 4)
        ctrl_layout.setSpacing(6)

        # 標題圖示
        self.lbl_title = QLabel(" 7L 鋼琴 NDI", self.ctrl_bar)
        self.lbl_title.setStyleSheet("color: #ff77aa; font-weight: bold; font-size: 13px;")
        ctrl_layout.addWidget(self.lbl_title)

        # 來源下拉選單
        self.combo_sources = QComboBox(self.ctrl_bar)
        self.combo_sources.addItem(" 搜尋虛擬機/鋼琴來源...")
        self.combo_sources.currentTextChanged.connect(self.on_source_selected)
        ctrl_layout.addWidget(self.combo_sources, 1)

        # 重新搜尋按鈕
        self.btn_refresh = QPushButton("", self.ctrl_bar)
        self.btn_refresh.setToolTip("重新掃描 NDI 來源 (Refresh Sources)")
        self.btn_refresh.clicked.connect(self.refresh_sources)
        ctrl_layout.addWidget(self.btn_refresh)

        #  去背模式切換按鈕
        self.btn_key = QPushButton(" 去黑底", self.ctrl_bar)
        self.btn_key.setToolTip("切換即時去背模式 (去黑底 / 去綠幕 / 去白底 / 原圖)")
        self.btn_key.clicked.connect(self.cycle_key_mode)
        ctrl_layout.addWidget(self.btn_key)

        #  邊界裁切按鈕
        self.btn_crop = QPushButton(" 裁切", self.ctrl_bar)
        self.btn_crop.setToolTip("裁切視窗邊框與工作列，只留琴鍵")
        self.btn_crop.clicked.connect(self.open_crop_dialog)
        ctrl_layout.addWidget(self.btn_crop)

        #  置頂切換按鈕
        self.btn_pin = QPushButton("", self.ctrl_bar)
        self.btn_pin.setToolTip("切換是否永遠置頂 (Always on Top)")
        self.btn_pin.clicked.connect(self.toggle_always_on_top)
        ctrl_layout.addWidget(self.btn_pin)

        #  穿透按鈕
        self.btn_ghost = QPushButton(" 穿透", self.ctrl_bar)
        self.btn_ghost.setToolTip("開啟滑鼠穿透 (開啟後點擊穿透至後面，按 H 或快速鍵 K 恢復)")
        self.btn_ghost.clicked.connect(self.toggle_click_through)
        ctrl_layout.addWidget(self.btn_ghost)

        # ✕ 隱藏控制列按鈕
        self.btn_hide = QPushButton("✕", self.ctrl_bar)
        self.btn_hide.setToolTip("暫時隱藏控制列 (按 H 鍵或滑鼠右鍵可隨時重新呼出)")
        self.btn_hide.clicked.connect(self.toggle_control_bar)
        ctrl_layout.addWidget(self.btn_hide)

        main_layout.addWidget(self.ctrl_bar)
        main_layout.addStretch(1)

        # 底部大小拉伸把手
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch(1)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("background: transparent;")
        bottom_layout.addWidget(self.size_grip)
        main_layout.addLayout(bottom_layout)

        # 提示標籤 (未連接時置中顯示)
        self.status_label = QLabel("正在等待 Virtual Piano / 虛擬機 NDI 訊號...", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            color: #ff99c8;
            font-size: 15px;
            font-weight: bold;
            background: rgba(18, 18, 26, 0.85);
            border: 1px solid #ff77aa;
            border-radius: 10px;
            padding: 14px 20px;
        """)
        self.status_label.setGeometry(80, 100, 820, 60)
        self.status_label.show()

    def on_frame_received(self, qimg: QImage):
        """接收 60 FPS 影格並刷新視窗"""
        self.current_pixmap = QPixmap.fromImage(qimg)
        if self.status_label.isVisible():
            self.status_label.hide()
        self.update()

    def on_source_list_updated(self, sources: list):
        """更新來源清單"""
        current = self.combo_sources.currentText()
        self.combo_sources.blockSignals(True)
        self.combo_sources.clear()
        if not sources:
            self.combo_sources.addItem(" 搜尋中 (未發現來源)...")
        else:
            for s in sources:
                self.combo_sources.addItem(s)
            idx = self.combo_sources.findText(current)
            if idx >= 0:
                self.combo_sources.setCurrentIndex(idx)
        self.combo_sources.blockSignals(False)

    def on_source_selected(self, source_name: str):
        if source_name and "搜尋" not in source_name:
            self.ndi_thread.connect_to_source(source_name)

    def refresh_sources(self):
        self.ndi_thread.current_source_name = ""
        self.ndi_thread.disconnect_source()

    def on_status_message(self, msg: str):
        self.lbl_title.setToolTip(msg)
        if not self.current_pixmap:
            self.status_label.setText(msg)
            self.status_label.show()

    def cycle_key_mode(self):
        """循環切換去背模式"""
        modes = [KEY_BLACK, KEY_GREEN, KEY_WHITE, KEY_NONE]
        mode_names = {
            KEY_BLACK: " 去黑底",
            KEY_GREEN: " 去綠幕",
            KEY_WHITE: " 去白底",
            KEY_NONE: " 原圖模式"
        }
        curr_idx = modes.index(self.ndi_thread.key_mode) if self.ndi_thread.key_mode in modes else 0
        next_mode = modes[(curr_idx + 1) % len(modes)]
        self.ndi_thread.key_mode = next_mode
        self.btn_key.setText(mode_names[next_mode])
        self.update()
        self.save_config()

    def open_crop_dialog(self):
        """開啟裁切設定視窗"""
        dlg = CropSettingsDialog(
            self, 
            self.ndi_thread.crop_top, 
            self.ndi_thread.crop_bottom, 
            self.ndi_thread.crop_left, 
            self.ndi_thread.crop_right
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            top, bottom, left, right = dlg.get_values()
            self.ndi_thread.crop_top = top
            self.ndi_thread.crop_bottom = bottom
            self.ndi_thread.crop_left = left
            self.ndi_thread.crop_right = right
            self.update()
            self.save_config()

    # ────────────────────────────────────────────────────────
    #  繪製事件 (支援透明背景與鋼琴寬條等比平滑縮放)
    # ────────────────────────────────────────────────────────
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 繪製自訂背景色
        if self.background_mode == "GREEN":
            painter.fillRect(self.rect(), QColor(0, 255, 0))
        elif self.background_mode == "DARK_GLASS":
            painter.fillRect(self.rect(), QColor(15, 15, 22, 210))
        # TRANSPARENT 模式下不填滿任何背景，保持懸浮透明

        # 繪製鋼琴畫面 (等比例填滿視窗)
        if self.current_pixmap and not self.current_pixmap.isNull():
            scaled = self.current_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            # 置中繪製
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

    # ────────────────────────────────────────────────────────
    #  滑鼠拖曳、滾輪縮放與操作
    # ────────────────────────────────────────────────────────
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_position.isNull():
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def wheelEvent(self, event: QWheelEvent):
        """滑鼠滾輪等比例縮放視窗大小 (保持鋼琴寬條比例)"""
        delta = event.angleDelta().y()
        scale = 1.08 if delta > 0 else 0.92
        new_w = max(320, int(self.width() * scale))
        new_h = max(90, int(self.height() * scale))

        center = self.geometry().center()
        self.resize(new_w, new_h)
        new_geo = self.geometry()
        new_geo.moveCenter(center)
        self.setGeometry(new_geo)
        event.accept()

    def toggle_always_on_top(self):
        """切換視窗置頂"""
        self.is_always_on_top = not self.is_always_on_top
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_always_on_top)
        self.btn_pin.setText("" if self.is_always_on_top else "")
        self.btn_pin.setToolTip("已開啟置頂" if self.is_always_on_top else "已關閉置頂")
        self.show()
        self.save_config()

    def toggle_control_bar(self):
        """顯示/隱藏頂部工具列"""
        self.show_control_bar = not self.show_control_bar
        if self.show_control_bar:
            self.ctrl_bar.show()
        else:
            self.ctrl_bar.hide()
        self.save_config()

    def toggle_click_through(self):
        """切換 Windows 滑鼠點擊穿透"""
        self.is_click_through = not self.is_click_through
        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        
        if self.is_click_through:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
            self.btn_ghost.setText(" 穿透中")
            self.btn_ghost.setStyleSheet("background: rgba(0, 230, 118, 0.4); border-color: #00e676;")
        else:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
            self.btn_ghost.setText(" 穿透")
            self.btn_ghost.setStyleSheet("")

    def toggle_color_swap(self):
        """切換 RGBA / BGRA 色彩通道"""
        self.ndi_thread.color_swap = not self.ndi_thread.color_swap
        self.update()
        self.save_config()

    def set_background_mode(self, mode: str):
        self.background_mode = mode
        self.update()
        self.save_config()

    def load_config(self):
        """讀取上次儲存的視窗位置、大小、去背與裁切等設定"""
        try:
            cfg_path = CONFIG_FILE if os.path.exists(CONFIG_FILE) else "7l_piano_ndi_config.json"
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                x = cfg.get("x")
                y = cfg.get("y")
                w = cfg.get("width", 980)
                h = cfg.get("height", 260)

                screen = QApplication.primaryScreen()
                if screen and x is not None and y is not None:
                    geom = screen.availableGeometry()
                    if x < geom.left() - w + 50 or x > geom.right() - 50:
                        x = geom.left() + 50
                    if y < geom.top() - 20 or y > geom.bottom() - 50:
                        y = geom.top() + 50
                    self.setGeometry(x, y, w, h)
                else:
                    self.resize(w, h)

                self.is_always_on_top = cfg.get("is_always_on_top", True)
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_always_on_top)
                self.btn_pin.setText("" if self.is_always_on_top else "")

                self.show_control_bar = cfg.get("show_control_bar", True)
                if not self.show_control_bar:
                    self.ctrl_bar.hide()

                self.background_mode = cfg.get("background_mode", "TRANSPARENT")
                self.ndi_thread.color_swap = cfg.get("color_swap", False)

                key_mode = cfg.get("key_mode", KEY_BLACK)
                self.ndi_thread.key_mode = key_mode
                mode_names = {
                    KEY_BLACK: " 去黑底",
                    KEY_GREEN: " 去綠幕",
                    KEY_WHITE: " 去白底",
                    KEY_NONE: " 原圖模式"
                }
                self.btn_key.setText(mode_names.get(key_mode, " 去黑底"))

                self.ndi_thread.crop_top = cfg.get("crop_top", 0.0)
                self.ndi_thread.crop_bottom = cfg.get("crop_bottom", 0.0)
                self.ndi_thread.crop_left = cfg.get("crop_left", 0.0)
                self.ndi_thread.crop_right = cfg.get("crop_right", 0.0)

                self.last_connected_source = cfg.get("last_source", "")
                if self.last_connected_source:
                    self.ndi_thread.current_source_name = self.last_connected_source
                return
        except Exception as e:
            print(f"⚠️ [Piano Config] 載入配置異常: {e}")
        self.resize(980, 260)

    def save_config(self):
        """保存目前視窗位置、大小、去背與裁切等設定至 JSON 檔案"""
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            cfg = {
                "x": self.x(),
                "y": self.y(),
                "width": self.width(),
                "height": self.height(),
                "is_always_on_top": bool(self.is_always_on_top),
                "show_control_bar": bool(self.show_control_bar),
                "background_mode": str(self.background_mode),
                "color_swap": bool(self.ndi_thread.color_swap),
                "key_mode": str(self.ndi_thread.key_mode),
                "crop_top": float(self.ndi_thread.crop_top),
                "crop_bottom": float(self.ndi_thread.crop_bottom),
                "crop_left": float(self.ndi_thread.crop_left),
                "crop_right": float(self.ndi_thread.crop_right),
                "last_source": str(self.ndi_thread.current_source_name or self.last_connected_source)
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, 'save_timer'):
            self.save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'save_timer'):
            self.save_timer.start()

    def show_context_menu(self, pos: QPoint):
        """右鍵選單"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #181824;
                border: 1px solid #ff77aa;
                border-radius: 6px;
                color: #ffffff;
                padding: 4px;
                font-family: 'Segoe UI', 'Microsoft JhengHei';
            }
            QMenu::item {
                padding: 6px 22px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #e0457b;
            }
        """)

        act_ctrl = menu.addAction(" 顯示/隱藏頂部工具列 (H)")
        act_ctrl.triggered.connect(self.toggle_control_bar)

        act_pin = menu.addAction(" 切換永遠置頂 (T)")
        act_pin.setCheckable(True)
        act_pin.setChecked(self.is_always_on_top)
        act_pin.triggered.connect(self.toggle_always_on_top)

        act_ghost = menu.addAction(" 滑鼠穿透模式 (K)")
        act_ghost.setCheckable(True)
        act_ghost.setChecked(self.is_click_through)
        act_ghost.triggered.connect(self.toggle_click_through)

        act_crop = menu.addAction(" 邊界裁切設定 (Crop)")
        act_crop.triggered.connect(self.open_crop_dialog)

        menu.addSeparator()

        # 去背模式子選單
        key_menu = menu.addMenu(" 即時去背模式 (Chroma Key)")
        for km, label in [
            (KEY_BLACK, " 去黑底 (Black Key - 推薦)"),
            (KEY_GREEN, " 去綠幕 (Green Key)"),
            (KEY_BLUE, " 去藍幕 (Blue Key)"),
            (KEY_WHITE, " 去白底 (White Key)"),
            (KEY_NONE, " 原圖模式 (No Key)")
        ]:
            act = key_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.ndi_thread.key_mode == km)
            act.triggered.connect(lambda checked, m=km: (setattr(self.ndi_thread, 'key_mode', m), self.save_config()))

        act_color = menu.addAction(" 色彩通道反轉 RGB/BGR (C)")
        act_color.setCheckable(True)
        act_color.setChecked(self.ndi_thread.color_swap)
        act_color.triggered.connect(self.toggle_color_swap)

        menu.addSeparator()

        # 鋼琴預設解析度
        size_menu = menu.addMenu(" 鋼琴專屬預設比例")
        size_menu.addAction("標準橫條 (980 x 260)").triggered.connect(lambda: self.resize(980, 260))
        size_menu.addAction("超寬琴鍵 (1280 x 320)").triggered.connect(lambda: self.resize(1280, 320))
        size_menu.addAction("精巧琴鍵 (720 x 200)").triggered.connect(lambda: self.resize(720, 200))
        size_menu.addAction("大瀑布流 (1280 x 540)").triggered.connect(lambda: self.resize(1280, 540))
        size_menu.addAction("全寬橫幅 (1600 x 380)").triggered.connect(lambda: self.resize(1600, 380))

        # 背景模式
        bg_menu = menu.addMenu(" 背景襯底顏色")
        bg_menu.addAction(" 完全透明 (Transparent)").triggered.connect(lambda: self.set_background_mode("TRANSPARENT"))
        bg_menu.addAction(" 綠幕背景 (Green Screen)").triggered.connect(lambda: self.set_background_mode("GREEN"))
        bg_menu.addAction(" 深色磨砂 (Dark Glass)").triggered.connect(lambda: self.set_background_mode("DARK_GLASS"))

        menu.addSeparator()
        act_exit = menu.addAction(" 關閉鋼琴接收器")
        act_exit.triggered.connect(self.close)

        menu.exec(pos)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_H:
            self.toggle_control_bar()
        elif event.key() == Qt.Key.Key_T:
            self.toggle_always_on_top()
        elif event.key() == Qt.Key.Key_K:
            self.toggle_click_through()
        elif event.key() == Qt.Key.Key_C:
            self.toggle_color_swap()
        elif event.key() == Qt.Key.Key_M:
            self.cycle_key_mode()
        elif event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event):
        self.save_config()
        self.ndi_thread.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = PianoNDIViewerWindow()
    viewer.show()
    sys.exit(app.exec())
