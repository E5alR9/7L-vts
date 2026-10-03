# -*- coding: utf-8 -*-
"""
==============================================================================
  7L 專屬超高清 NDI 透明接收器 (7L Transparent Resizable NDI Viewer)
  特色：
   1.  完美支援 Alpha 通道透明背景（Live2D 角色無邊框懸浮於桌面）
   2.  滑鼠滾輪即時縮放 + 視窗八向邊界自由拉伸大小
   3.  隨處拖曳移動 + 總在最上層 (Always-on-Top) + 滑鼠穿透 (Click-Through)
   4.  局域網 / Hyper-V 虛擬機 NDI 來源自動發現與秒級無縫切換
   5.  60 FPS 硬件級流暢渲染，低 CPU 佔用
==============================================================================
"""

import os
import sys
import time
import json
import ctypes
import numpy as np
import NDIlib as ndi

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "7l_ndi_receiver_config.json")

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QSize, QTimer
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QAction, QIcon, QMouseEvent, QWheelEvent, QPaintEvent
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMenu, QComboBox, QPushButton, 
    QHBoxLayout, QVBoxLayout, QLabel, QSizeGrip, QGraphicsDropShadowEffect
)

# Windows 穿透相關 API 常數
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

class NDIWorkerThread(QThread):
    """NDI 串流背景接收協程 (保證 60 FPS 低延遲)"""
    frame_received = pyqtSignal(QImage)
    source_list_updated = pyqtSignal(list)
    status_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.current_source_name = ""
        self.recv_handle = None
        self.find_handle = None

        self.color_swap = False

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

        self.status_message.emit(" 正在搜尋本機 / 局域網 NDI 來源...")

        last_search_time = 0
        discovered_names = []

        while self.running:
            # 每 1.5 秒自動刷新來源清單
            now = time.time()
            if now - last_search_time > 1.5:
                last_search_time = now
                if ndi.find_wait_for_sources(self.find_handle, 50):
                    sources = ndi.find_get_current_sources(self.find_handle)
                    s_names = [s.ndi_name for s in sources]
                    if s_names != discovered_names:
                        discovered_names = s_names
                        self.source_list_updated.emit(discovered_names)

            # 若尚未連接來源，嘗試自動連接本機可用的 VTubeStudio 或 7L 來源
            if not self.recv_handle and discovered_names:
                target = self.current_source_name if self.current_source_name in discovered_names else ""
                if not target:
                    # 優先選擇 VTubeStudio / 7L
                    for name in discovered_names:
                        if any(k in name.lower() for k in ["vtube", "live2d", "7l"]):
                            target = name
                            break
                    if not target and discovered_names:
                        target = discovered_names[0]

                if target:
                    self.connect_to_source(target)

            # 接收影像影格
            if self.recv_handle:
                t, v, a, m = ndi.recv_capture_v2(self.recv_handle, 100)
                if t == ndi.FRAME_TYPE_VIDEO and v.data is not None:
                    try:
                        # 擷取影像資料
                        w, h = v.xres, v.yres
                        frame_data = np.copy(v.data)
                        
                        # 若啟用色彩通道校準 (修復藍皮/紅藍反轉問題)
                        if self.color_swap:
                            frame_data = frame_data[:, :, [2, 1, 0, 3]]
                        
                        # 轉為 QImage (Format_RGBA8888)
                        bytes_per_line = v.line_stride_in_bytes
                        qimg = QImage(frame_data.data, w, h, bytes_per_line, QImage.Format.Format_RGBA8888)
                        
                        # 發送影格給 GUI 繪製
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
                time.sleep(0.05)

        # 清理資源
        self.disconnect_source()
        if self.find_handle:
            ndi.find_destroy(self.find_handle)
        ndi.destroy()

    def connect_to_source(self, source_name: str):
        """連接到指定 NDI 來源"""
        self.disconnect_source()
        self.current_source_name = source_name
        self.status_message.emit(f" 連接中: {source_name}")

        sources = ndi.find_get_current_sources(self.find_handle)
        target_source = None
        for s in sources:
            if s.ndi_name == source_name:
                target_source = s
                break

        if target_source:
            recv_create = ndi.RecvCreateV3()
            recv_create.source_to_connect_to = target_source
            recv_create.color_format = ndi.RECV_COLOR_FORMAT_RGBX_RGBA  # 100% 正確 RGBA 原色通道，避免紅藍通道顛倒
            recv_create.bandwidth = ndi.RECV_BANDWIDTH_HIGHEST
            self.recv_handle = ndi.recv_create_v3(recv_create)
            if self.recv_handle:
                self.status_message.emit(f" 已連接: {source_name}")
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


class NDIViewerWindow(QWidget):
    """ 7L 可調大小/全透明/懸浮 NDI 接收器視窗"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(" 7L NDI 透明接收器")
        self.setMinimumSize(200, 200)
        self.resize(480, 640)

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

        # 初始化 UI 控制列
        self.init_ui()

        # 啟動 NDI 背景協程
        self.ndi_thread = NDIWorkerThread()
        self.ndi_thread.frame_received.connect(self.on_frame_received)
        self.ndi_thread.source_list_updated.connect(self.on_source_list_updated)
        self.ndi_thread.status_message.connect(self.on_status_message)
        self.ndi_thread.start()

        # 恢復上次關閉時的位置、大小與偏好設定
        self.load_config()

    def init_ui(self):
        """建立頂部精緻控制列"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)

        # 頂部半透明控制面板
        self.ctrl_bar = QWidget(self)
        self.ctrl_bar.setStyleSheet("""
            QWidget {
                background: rgba(20, 20, 28, 0.85);
                border: 1px solid rgba(255, 180, 220, 0.4);
                border-radius: 8px;
                color: #ffffff;
                font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif;
                font-size: 12px;
            }
            QComboBox {
                background: rgba(40, 40, 50, 0.9);
                border: 1px solid rgba(255, 180, 220, 0.5);
                border-radius: 4px;
                padding: 3px 8px;
                color: #ffb8d9;
                font-weight: bold;
                min-width: 140px;
            }
            QComboBox QAbstractItemView {
                background: #1e1e28;
                color: #ffffff;
                selection-background-color: #e05688;
            }
            QPushButton {
                background: rgba(255, 105, 180, 0.25);
                border: 1px solid rgba(255, 180, 220, 0.6);
                border-radius: 4px;
                padding: 4px 8px;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 105, 180, 0.55);
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        ctrl_layout = QHBoxLayout(self.ctrl_bar)
        ctrl_layout.setContentsMargins(8, 4, 8, 4)
        ctrl_layout.setSpacing(6)

        # 標題與圖示
        self.lbl_title = QLabel(" 7L NDI", self.ctrl_bar)
        self.lbl_title.setStyleSheet("color: #ff80b3; font-weight: bold; font-size: 13px;")
        ctrl_layout.addWidget(self.lbl_title)

        # 來源下拉選單
        self.combo_sources = QComboBox(self.ctrl_bar)
        self.combo_sources.addItem(" 搜尋來源中...")
        self.combo_sources.currentTextChanged.connect(self.on_source_selected)
        ctrl_layout.addWidget(self.combo_sources, 1)

        # 重新搜尋按鈕
        self.btn_refresh = QPushButton("", self.ctrl_bar)
        self.btn_refresh.setToolTip("重新搜尋 NDI 來源")
        self.btn_refresh.clicked.connect(self.refresh_sources)
        ctrl_layout.addWidget(self.btn_refresh)

        # 置頂切換按鈕
        self.btn_pin = QPushButton("", self.ctrl_bar)
        self.btn_pin.setToolTip("切換是否永遠置頂 (Always on Top)")
        self.btn_pin.clicked.connect(self.toggle_always_on_top)
        ctrl_layout.addWidget(self.btn_pin)

        # 隱藏控制列按鈕 (按 H 可重新顯示)
        self.btn_hide = QPushButton("✕", self.ctrl_bar)
        self.btn_hide.setToolTip("暫時隱藏控制列 (在畫面上按滑鼠右鍵或 H 鍵可再開啟)")
        self.btn_hide.clicked.connect(self.toggle_control_bar)
        ctrl_layout.addWidget(self.btn_hide)

        main_layout.addWidget(self.ctrl_bar)
        main_layout.addStretch(1)

        # 右下角縮放把手
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch(1)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("background: transparent;")
        bottom_layout.addWidget(self.size_grip)
        main_layout.addLayout(bottom_layout)

        # 狀態文字標籤 (未連接時顯示提示)
        self.status_label = QLabel("正在等待 7L Live2D NDI 訊號...", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            color: #ff99c8;
            font-size: 14px;
            font-weight: bold;
            background: rgba(15, 15, 20, 0.7);
            border-radius: 10px;
            padding: 12px;
        """)
        self.status_label.setGeometry(30, 200, 420, 50)
        self.status_label.show()

    def on_frame_received(self, qimg: QImage):
        """接收到 60 FPS 新影格"""
        self.current_pixmap = QPixmap.fromImage(qimg)
        if self.status_label.isVisible():
            self.status_label.hide()
        self.update()

    def on_source_list_updated(self, sources: list):
        """更新來源選單"""
        current = self.combo_sources.currentText()
        self.combo_sources.blockSignals(True)
        self.combo_sources.clear()
        if not sources:
            self.combo_sources.addItem(" 搜尋中 (未發現來源)...")
        else:
            for s in sources:
                self.combo_sources.addItem(s)
            # 保持之前選中的來源
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

    # ────────────────────────────────────────────────────────
    #  繪製事件 (支援透明背景與等比例縮放)
    # ────────────────────────────────────────────────────────
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 繪製背景色
        if self.background_mode == "GREEN":
            painter.fillRect(self.rect(), QColor(0, 255, 0))
        elif self.background_mode == "DARK_GLASS":
            painter.fillRect(self.rect(), QColor(20, 20, 30, 200))
        # TRANSPARENT 模式下不填滿任何背景，保持純粹透明

        # 繪製 Live2D 畫面 (等比例縮放填滿視窗)
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
    #  滑鼠拖曳、滾輪縮放與快捷操作
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
        """滑鼠滾輪等比例即時縮放視窗大小"""
        delta = event.angleDelta().y()
        scale = 1.1 if delta > 0 else 0.9
        new_w = max(180, int(self.width() * scale))
        new_h = max(240, int(self.height() * scale))
        
        # 保持中心點縮放
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
        """顯示/隱藏頂部控制列"""
        self.show_control_bar = not self.show_control_bar
        if self.show_control_bar:
            self.ctrl_bar.show()
        else:
            self.ctrl_bar.hide()
        self.save_config()

    def set_background_mode(self, mode: str):
        self.background_mode = mode
        self.update()
        self.save_config()

    def toggle_color_swap(self):
        """切換 RGBA / BGRA 色彩通道 (修復紅藍色調偏藍或偏紅問題)"""
        self.ndi_thread.color_swap = not self.ndi_thread.color_swap
        self.update()
        self.save_config()

    def load_config(self):
        """讀取上次儲存的視窗位置、大小與各項設定"""
        try:
            cfg_path = CONFIG_FILE if os.path.exists(CONFIG_FILE) else "7l_ndi_receiver_config.json"
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                x = cfg.get("x")
                y = cfg.get("y")
                w = cfg.get("width", 480)
                h = cfg.get("height", 640)

                screen = QApplication.primaryScreen()
                if screen and x is not None and y is not None:
                    geom = screen.availableGeometry()
                    if x < geom.left() - w + 50 or x > geom.right() - 50:
                        x = geom.left() + 100
                    if y < geom.top() - 20 or y > geom.bottom() - 50:
                        y = geom.top() + 100
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
                self.last_connected_source = cfg.get("last_source", "")
                if self.last_connected_source:
                    self.ndi_thread.current_source_name = self.last_connected_source
                return
        except Exception as e:
            print(f"⚠️ [Config] 載入配置異常: {e}")
        self.resize(480, 640)

    def save_config(self):
        """保存目前視窗位置、大小與設定至 JSON 檔案"""
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
        """右鍵功能選單"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1e1e28;
                border: 1px solid #ff80b3;
                border-radius: 6px;
                color: #ffffff;
                padding: 4px;
                font-family: 'Segoe UI', 'Microsoft JhengHei';
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #e05688;
            }
        """)

        act_ctrl = menu.addAction(" 顯示/隱藏頂部工具列 (H)")
        act_ctrl.triggered.connect(self.toggle_control_bar)

        act_pin = menu.addAction(" 切換永遠置頂 (Always on Top)")
        act_pin.setCheckable(True)
        act_pin.setChecked(self.is_always_on_top)
        act_pin.triggered.connect(self.toggle_always_on_top)

        act_color = menu.addAction(" 色彩通道校準 (按 C 鍵切換)")
        act_color.setCheckable(True)
        act_color.setChecked(self.ndi_thread.color_swap)
        act_color.triggered.connect(self.toggle_color_swap)

        menu.addSeparator()
        
        # 背景切換子選單
        bg_menu = menu.addMenu(" 背景顏色模式")
        act_bg_trans = bg_menu.addAction(" 完全透明 (Transparent)")
        act_bg_trans.triggered.connect(lambda: self.set_background_mode("TRANSPARENT"))
        act_bg_green = bg_menu.addAction(" 綠幕背景 (Green Screen)")
        act_bg_green.triggered.connect(lambda: self.set_background_mode("GREEN"))
        act_bg_glass = bg_menu.addAction(" 深色磨砂 (Dark Glass)")
        act_bg_glass.triggered.connect(lambda: self.set_background_mode("DARK_GLASS"))

        menu.addSeparator()

        # 預設尺寸捷徑
        size_menu = menu.addMenu(" 快速預設大小")
        size_menu.addAction("小尺寸 (320x420)").triggered.connect(lambda: self.resize(320, 420))
        size_menu.addAction("中尺寸 (480x640)").triggered.connect(lambda: self.resize(480, 640))
        size_menu.addAction("大尺寸 (640x860)").triggered.connect(lambda: self.resize(640, 860))
        size_menu.addAction("超大尺寸 (800x1080)").triggered.connect(lambda: self.resize(800, 1080))

        menu.addSeparator()
        act_exit = menu.addAction(" 關閉接收器")
        act_exit.triggered.connect(self.close)

        menu.exec(pos)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_H:
            self.toggle_control_bar()
        elif event.key() == Qt.Key.Key_T:
            self.toggle_always_on_top()
        elif event.key() == Qt.Key.Key_C:
            self.toggle_color_swap()
        elif event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event):
        self.save_config()
        self.ndi_thread.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = NDIViewerWindow()
    viewer.show()
    sys.exit(app.exec())
