"""
🎹 7L 虛擬鋼琴 - 88 鍵真實古典平台鋼琴 (A0~C8 / 古典取樣 + 粉白黑深粉自由配色)
========================================================================
✨ 特色核心：
1. 緊湊無死角介面：徹底刪除鋼琴下方多餘空白區，琴鍵底部完美貼合
2. 🎨 客製粉白黑深粉配色體系 (User Color Aesthetic)：
   - 白鍵長條：粉、白自由搭配 (柔櫻粉、珍珠白、淺櫻粉、霜白相間)
   - 黑鍵長條：黑、深粉自由搭配 (霧炭黑、暗夜黑、莓果深粉、玫瑰深粉相間)
   - 擊鍵光刃與時間軸：櫻花粉與深粉光芒
3. 真實古典平台鋼琴取樣音色 (Acoustic Grand Piano - 告別電子琴合成音，高音清澈明亮、低音渾厚深邃)
4. 零延遲無縫中途切歌 (Smooth Song Switching - 下拉即切、即刻清空殘響與方塊)
5. 頂部可拖動互動時間軸 (Draggable Timeline - 任意點選/拖動快進倒退)
6. Synthesia 正統瀑布流下落長條方形視覺化 (前置預落下落，碰線擊鍵瞬間精準發聲)
7. 🌐 BitMidi (https://bitmidi.com) 雲端百萬 MIDI 樂譜即時搜尋與一鍵下載演奏
"""

import os
import sys

# Ensure workspace root is always in sys.path
_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)

import json
import time
import math
import mido
import bisect
import random
import pygame
import pygame.midi
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from typing import Dict, List, Optional, Tuple
import bitmidi_engine
import numpy as np

try:
    import NDIlib as ndi
    HAS_NDI = True
except ImportError:
    HAS_NDI = False

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

class PianoNDIBroadcaster:
    """🎹 鋼琴 NDI 影像廣播引擎 (極致 60 FPS 超低延遲串流，支援跨網段推流至主電腦)"""
    def __init__(self, get_bbox_callback, stream_name="🎹 7L Virtual Piano"):
        self.get_bbox = get_bbox_callback
        self.stream_name = stream_name
        self.running = False
        self.thread = None
        self.send_handle = None
        self.transparent_black = False

    def start(self) -> bool:
        if not HAS_NDI or not HAS_MSS:
            print("⚠️ [NDI Broadcaster] 缺少 NDIlib 或 mss 套件，無法啟用 NDI 串流。")
            return False
        if self.running:
            return True
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"📡 [NDI Broadcaster] 已成功開啟 NDI 串流廣播: {self.stream_name}")
        return True

    def stop(self):
        self.running = False
        print("📡 [NDI Broadcaster] 已關閉 NDI 串流廣播。")

    def _run(self):
        if not ndi.initialize():
            print("❌ [NDI Broadcaster] NDI 初始化失敗！")
            return
        send_settings = ndi.SendCreate()
        send_settings.ndi_name = self.stream_name
        self.send_handle = ndi.send_create(send_settings)
        if not self.send_handle:
            print("❌ [NDI Broadcaster] 無法建立 NDI 發送器！")
            return

        with mss.mss() as sct:
            while self.running:
                t0 = time.perf_counter()
                try:
                    bbox = self.get_bbox()
                    if bbox and bbox.get("width", 0) > 50 and bbox.get("height", 0) > 50:
                        sct_img = sct.grab(bbox)
                        arr = np.array(sct_img, dtype=np.uint8)  # Shape: (H, W, 4) - BGRA

                        if self.transparent_black:
                            b, g, r = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
                            brightness = np.maximum(r, np.maximum(g, b))
                            arr[:, :, 3] = np.where(brightness < 20, 0, 255)

                        video_frame = ndi.VideoFrameV2()
                        video_frame.data = arr
                        video_frame.FourCC = ndi.FOURCC_VIDEO_TYPE_BGRX
                        video_frame.xres = arr.shape[1]
                        video_frame.yres = arr.shape[0]
                        video_frame.line_stride_in_bytes = arr.shape[1] * 4
                        ndi.send_send_video_v2(self.send_handle, video_frame)
                except Exception:
                    pass

                elapsed = time.perf_counter() - t0
                sleep_time = max(0.001, (1.0 / 60.0) - elapsed)
                time.sleep(sleep_time)

        if self.send_handle:
            ndi.send_destroy(self.send_handle)
            self.send_handle = None
        ndi.destroy()

import socket
import atexit
SYNC_UDP_SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
SYNC_UDP_ADDR = ("127.0.0.1", 39281)

def _piano_shutdown_hook():
    try:
        msg = json.dumps({
            "type": "PIANO_STATUS",
            "event": "closed",
            "is_alive": False,
            "is_window_open": False,
            "is_playing": False,
            "title": "",
            "timestamp": time.time()
        }).encode('utf-8')
        SYNC_UDP_SOCK.sendto(msg, SYNC_UDP_ADDR)
    except Exception:
        pass
atexit.register(_piano_shutdown_hook)

RANDOM_PIANO_SEEDS = [
    "李斯特 鐘", "月光奏鳴曲 第三樂章", "愛之夢", "冬風練習曲", "少女的祈禱", 
    "幻想即興曲", "卡農", "給愛麗絲", "土耳其進行曲", "月光奏鳴曲 第一樂章",
    "神隱少女", "霍爾的移動城堡", "天空之城", "殘酷天使的行動綱領", "千本櫻", 
    "River Flows in You", "名偵探柯南 主題曲", "大魚海棠", "青花瓷", "菊次郎的夏天",
    "夜的第七章", "晴天", "Lemon", "打上花火", "紅蓮華", "夜訪吸血鬼", "Chopin Nocturne Op 9 No 2"
]

def broadcast_piano_focus(midi_list):
    """將當前擊鍵的音符密集重心即時廣播給 7L 虛擬主播大腦 (鏡像視角：高音在螢幕左側，低音在螢幕右側)"""
    if not midi_list: return
    try:
        avg_midi = sum(midi_list) / len(midi_list)
        offset = max(-1.0, min(1.0, (avg_midi - 60.0) / 28.0))
        # 鏡像校正：7L 面對觀眾彈琴，其右手高音區在觀眾視角的螢幕左側 (-)，左手低音區在螢幕右側 (+)
        target_deg = -offset * 22.0
        SYNC_UDP_SOCK.sendto(f"{target_deg:.2f}".encode('utf-8'), SYNC_UDP_ADDR)
    except Exception:
        pass

MIDI_SHEETS_DIR = "midi_sheets"
os.makedirs(MIDI_SHEETS_DIR, exist_ok=True)

# ────────────────────────────────────────────────────────
# 🌸 1. 使用者專屬指定配色庫 (粉白黑深粉 4 色全隨機 + 左右手專屬分色)
# ────────────────────────────────────────────────────────
# 🎲 預設全隨機混搭庫 (當 MIDI 未明確寫出左右手時使用，完全隨機自由搭配)
WHITE_NOTE_PALETTE = [
    ("#ffc5d3", "#ffffff"), # 柔櫻粉 + 白框
    ("#ffffff", "#fbcfe8"), # 珍珠白 + 粉框
    ("#fbcfe8", "#ffffff"), # 櫻花淡粉 + 白框
    ("#fdf2f8", "#fda4af"), # 霜白 + 亮粉框
    ("#fda4af", "#ffffff"), # 淺粉 + 白框
    ("#f472b6", "#ffffff"), # 玫粉 + 白框
]

BLACK_NOTE_PALETTE = [
    ("#9d385a", "#ffffff"), # 深粉色 + 白框
    ("#2b262d", "#ffc5d3"), # 霧炭黑 + 粉框
    ("#be185d", "#ffffff"), # 莓果深粉 + 白框
    ("#1f1b24", "#fbcfe8"), # 暗夜深黑 + 粉框
    ("#a8325a", "#fdf2f8"), # 玫瑰深粉 + 霜白框
    ("#362f38", "#fda4af"), # 暖炭黑 + 櫻花框
]

# 🌸 左手專屬指定配色 (當 MIDI 軌道有明確標註 Left / Bass / 左手 時使用)
LH_WHITE_PALETTE = [
    ("#ffc5d3", "#ffffff"), # 柔櫻粉 + 白框
    ("#fbcfe8", "#ffffff"), # 櫻花淡粉 + 白框
    ("#fda4af", "#ffffff"), # 淺粉 + 白框
]
LH_BLACK_PALETTE = [
    ("#9d385a", "#ffffff"), # 深粉色 + 白框
    ("#be185d", "#ffffff"), # 莓果深粉 + 白框
    ("#a8325a", "#fdf2f8"), # 玫瑰深粉 + 霜白框
]

# 🤍 右手專屬指定配色 (當 MIDI 軌道有明確標註 Right / Treble / 右手 時使用)
RH_WHITE_PALETTE = [
    ("#ffffff", "#fda4af"), # 純珍珠白 + 淺粉框
    ("#fdf2f8", "#fbcfe8"), # 霜白色 + 櫻花淡粉框
]
RH_BLACK_PALETTE = [
    ("#2b262d", "#ffc5d3"), # 霧炭黑 + 柔粉框
    ("#1f1b24", "#fbcfe8"), # 暗夜深黑 + 櫻花粉框
    ("#362f38", "#fda4af"), # 暖炭黑 + 淺粉框
]



# ────────────────────────────────────────────────────────
# 🎹 2. 88 鍵全音域物理鍵盤定義 (MIDI 21 ~ 108)
# ────────────────────────────────────────────────────────
WHITE_KEYS = [
    ('A0', 21, 'A0', '1'),
    ('B0', 23, 'B0', '2'),
]
BLACK_KEYS = [
    ('A#0', 22, 'A#0', 0, '!'),
]

NOTE_NAMES_W = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
SEMITONES_W = [0, 2, 4, 5, 7, 9, 11]

NOTE_NAMES_B = ['C#', 'D#', 'F#', 'G#', 'A#']
SEMITONES_B = [1, 3, 6, 8, 10]
W_INDICES_B = [0, 1, 3, 4, 5]

WHITE_CHARS_MAP = {
    1: ['3', '4', '5', '6', '7', '8', '9'],
    2: ['0', 'q', 'w', 'e', 'r', 't', 'y'],
    3: ['u', 'i', 'o', 'p', 'a', 's', 'd'],
    4: ['f', 'g', 'h', 'j', 'k', 'l', 'z'],
    5: ['x', 'c', 'v', 'b', 'n', 'm', ''],
}

BLACK_CHARS_MAP = {
    1: ['@', '$', '%', '^', '&'],
    2: ['*', '(', 'Q', 'W', 'E'],
    3: ['R', 'T', 'Y', 'I', 'O'],
    4: ['P', 'S', 'D', 'G', 'H'],
    5: ['J', 'L', 'Z', 'C', 'V'],
}

for oct in range(1, 8):
    base_midi = 12 + oct * 12
    w_start_idx = len(WHITE_KEYS)
    for j, (n, semi) in enumerate(zip(NOTE_NAMES_W, SEMITONES_W)):
        midi = base_midi + semi
        WHITE_KEYS.append((f'{n}{oct}', midi, f'{n}{oct}', ''))
        
    for j, (n, semi, w_off) in enumerate(zip(NOTE_NAMES_B, SEMITONES_B, W_INDICES_B)):
        midi = base_midi + semi
        BLACK_KEYS.append((f'{n}{oct}', midi, f'{n}{oct}', w_start_idx + w_off, ''))

# 最高音 C8 (108)
WHITE_KEYS.append(('C8', 108, 'C8', ''))

# 🎹 雙排全無縫不重疊鍵盤鍵位定義 (Continuous Dual-Row Layout, 0% Overlap):
# 下排 (Lower Tier): 白鍵 zxcvbnm,./ | 黑鍵 asdfghjkl;' (覆蓋 C 到 E，10 個白鍵 + 7 個黑鍵)
# 上排 (Upper Tier): 白鍵 qwertyuiop[]\ | 黑鍵 1234567890-= (接續 F 到 D，13 個白鍵 + 9 個黑鍵)
LOWER_TIER_NOTES = [
    ('z', 0, False),    # C
    ('s', 1, True),     # C#
    ('x', 2, False),    # D
    ('d', 3, True),     # D#
    ('c', 4, False),    # E
    ('v', 5, False),    # F
    ('g', 6, True),     # F#
    ('b', 7, False),    # G
    ('h', 8, True),     # G#
    ('n', 9, False),    # A
    ('j', 10, True),    # A#
    ('m', 11, False),   # B
    (',', 12, False),   # C (+1 Octave)
    ('l', 13, True),    # C#
    ('.', 14, False),   # D
    (';', 15, True),    # D#
    ('/', 16, False),   # E
    ("'", 18, True),    # F#
]

UPPER_TIER_NOTES = [
    ('q', 17, False),   # F (接在下排 / 的 E 之後，零重疊無縫展開！)
    ('2', 18, True),    # F#
    ('w', 19, False),   # G
    ('3', 20, True),    # G#
    ('e', 21, False),   # A
    ('4', 22, True),    # A#
    ('r', 23, False),   # B
    ('t', 24, False),   # C (+2 Octaves)
    ('6', 25, True),    # C#
    ('y', 26, False),   # D
    ('7', 27, True),    # D#
    ('u', 28, False),   # E
    ('i', 29, False),   # F
    ('9', 30, True),    # F#
    ('o', 31, False),   # G
    ('0', 32, True),    # G#
    ('p', 33, False),   # A
    ('-', 34, True),    # A#
    ('[', 35, False),   # B
    (']', 36, False),   # C (+3 Octaves)
    ('=', 37, True),    # C#
    ('\\', 38, False),  # D
]

EXTRA_KEY_HELPERS = [
    ('a', -1, True),    # 低音 B
    ('f', 5, True),     # F
    ('k', 11, True),    # B
    ('1', 17, True),    # F
    ('5', 23, True),    # B
    ('8', 29, True),    # F
]

PITCH_PRESETS = [
    {"name": "🎼 超低音 (C1~D4)", "base_c": 24, "desc": "超低音檔 (C1 ~ D4)"},
    {"name": "🎼 中低音 (C2~D5)", "base_c": 36, "desc": "中低音檔 (C2 ~ D5)"},
    {"name": "🎼 標準中音 (C3~D6)", "base_c": 48, "desc": "標準中音檔 (C3 ~ D6，預設)"},
    {"name": "🎼 中高音 (C4~D7)", "base_c": 60, "desc": "中高音檔 (C4 ~ D7)"},
    {"name": "🎼 極高音 (C5~C8)", "base_c": 70, "desc": "極高音檔 (C5 ~ C8，覆蓋至最右側高音 C8)"},
]

VP_MAP = {}
MIDI_TO_KEYID = {}
VP_MAP_REV_WHITE = {}
VP_MAP_REV_BLACK = {}

def compute_pitch_mappings(base_c: int = 48):
    r"""
    根據基準 C 音符 (MIDI 24~72) 動態建立全鍵盤映射：
    - 下排白鍵: z x c v b n m , . /  (黑鍵: a s d f g h j k l ; ')
    - 上排白鍵: q w e r t y u i o p [ ] \  (黑鍵: 1 2 3 4 5 6 7 8 9 0 - =)
    """
    base_c = max(21, min(72, base_c))
    VP_MAP.clear()
    VP_MAP_REV_WHITE.clear()
    VP_MAP_REV_BLACK.clear()
    
    # 預設所有琴鍵以 key_id / MIDI 號碼自身映射
    for key_id, midi, name, _ in WHITE_KEYS:
        MIDI_TO_KEYID[midi] = key_id
        VP_MAP[key_id] = midi
        VP_MAP_REV_WHITE[key_id] = ""

    for key_id, midi, name, _, _ in BLACK_KEYS:
        MIDI_TO_KEYID[midi] = key_id
        VP_MAP[key_id] = midi
        VP_MAP_REV_BLACK[key_id] = ""

    # 1. 映射下排與上排音階 (支援雙排無縫演奏，零重疊)
    all_mappings = LOWER_TIER_NOTES + UPPER_TIER_NOTES + EXTRA_KEY_HELPERS
    for char, semi_offset, is_black in all_mappings:
        target_midi = base_c + semi_offset
        if 21 <= target_midi <= 108:
            VP_MAP[char] = target_midi
            VP_MAP[char.upper()] = target_midi
            key_id = MIDI_TO_KEYID.get(target_midi)
            if key_id:
                if is_black:
                    if not VP_MAP_REV_BLACK.get(key_id) or char in "1234567890-=asdfghjkl;'":
                        VP_MAP_REV_BLACK[key_id] = char
                else:
                    if not VP_MAP_REV_WHITE.get(key_id) or char in "zxcvbnm,./qwertyuiop[]\\":
                        VP_MAP_REV_WHITE[key_id] = char

compute_pitch_mappings(48)

# ────────────────────────────────────────────────────────
# 🎻 3. General MIDI 精選音色庫與聲音引擎 (Acoustic Grand Piano & GM Sound Engine)
# ────────────────────────────────────────────────────────
MIDI_INSTRUMENTS = {
    "🎹 古典平台鋼琴 (Grand Piano)": 0,
    "✨ 晶亮平台鋼琴 (Bright Piano)": 1,
    "⚡ 經典電鋼琴 (Rhodes EP)": 4,
    "🌌 FM 數位電鋼琴 (DX7 EP)": 5,
    "🎼 古典大鍵琴 (Harpsichord)": 6,
    "🔔 夢幻鋼片琴 (Celesta)": 8,
    "🎵 溫暖木琴 (Marimba)": 12,
    "⛪ 教堂管風琴 (Church Organ)": 19,
    "🪗 浪漫手風琴 (Accordion)": 21,
    "🎸 古典尼龍吉他 (Nylon Guitar)": 24,
    "🎸 民謠鋼弦吉他 (Steel Guitar)": 25,
    "🎸 清音電吉他 (Clean Guitar)": 27,
    "⚡ 破音電吉他 (Overdrive)": 29,
    "⚡ 重金屬吉他 (Distortion)": 30,
    "🎸 指彈電貝斯 (Electric Bass)": 33,
    "🎻 獨奏小提琴 (Violin)": 40,
    "🎻 抒情大提琴 (Cello)": 42,
    "🪕 天使豎琴 (Harp)": 46,
    "🎻 華麗交響弦樂 (String Ensemble)": 48,
    "👼 空靈人聲合唱 (Choir Aahs)": 52,
    "🎺 爵士小號 (Trumpet)": 56,
    "🎷 浪漫薩克斯風 (Alto Sax)": 65,
    "🪈 清新長笛 (Flute)": 73,
    "🎹 復古合成器 (Saw Lead)": 81,
    "🌸 夢幻合成音墊 (Warm Pad)": 89,
    "🪕 日本古箏 (Koto)": 107,
    "🪵 非洲拇指琴 (Kalimba)": 108
}

import collections

class ClassicalPianoSoundEngine:
    """🌟 88 鍵高復音數無削波 MIDI 聲音引擎 (支援 Rush E / 黑樂譜高密度連彈，0 消音 0 掐音)"""
    def __init__(self, volume: int = 100, instrument: int = 0):
        self.midi_out = None
        self.volume = max(0, min(200, int(volume)))
        self.current_instrument = max(0, min(127, int(instrument)))
        # 使用 15 個獨立 MIDI 通道 (0~8, 10~15，避開 Channel 9 打擊樂) 進行多軌語音輪替 (Voice Pooling)
        self.usable_channels = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15]
        self.channel_idx = 0
        # 記錄各音符當前佔用的通道: {midi_num: [channel_list]}
        self.active_note_channels = collections.defaultdict(list)
        # 復音上限守護隊列: deque of (midi_num, channel)
        self.active_voices_fifo = collections.deque()
        self.MAX_POLYPHONY = 256  # 升級至 256 超高復音，徹底杜絕黑樂譜/大編制連彈時音符被提早消音
        self.init_sound()
        
    def init_sound(self):
        try:
            if not pygame.midi.get_init():
                pygame.midi.init()
            out_id = pygame.midi.get_default_output_id()
            if out_id != -1:
                self.midi_out = pygame.midi.Output(out_id)
                self.configure_channels()
                print(f"✅ [Sound Engine] 成功載入 15 軌高復音 MIDI 聲音引擎 (音色: #{self.current_instrument})！")
            else:
                print("⚠️ [Classical Sound Engine] 未找到預設 MIDI 輸出裝置")
        except Exception as e:
            print(f"⚠️ [Classical Sound Engine] 初始化異常: {e}")

    def configure_channels(self):
        """為所有可用 MIDI 通道初始化共鳴與適度衰減參數 (防止黑樂譜長音堆疊塞爆驅動)"""
        if not self.midi_out: return
        try:
            cc7_val = int(min(100, self.volume) * 1.27)
            for ch in self.usable_channels:
                self.midi_out.set_instrument(self.current_instrument, channel=ch)
                self.midi_out.write_short(0xB0 + ch, 91, 80) # CC 91: Reverb 80 (飽滿自然空間共鳴)
                self.midi_out.write_short(0xB0 + ch, 93, 25) # CC 93: Chorus 琴弦共鳴
                self.midi_out.write_short(0xB0 + ch, 72, 85) # CC 72: Release Time 85 (自然飽滿共鳴餘韻，徹底杜絕掐音消音)
                self.midi_out.write_short(0xB0 + ch, 71, 64) # CC 71: Resonance
                self.midi_out.write_short(0xB0 + ch, 7, cc7_val)
        except Exception:
            pass

    def set_instrument(self, program_num: int):
        """切換 MIDI 發聲音色 (Program Change 0 ~ 127)"""
        self.current_instrument = max(0, min(127, int(program_num)))
        if self.midi_out:
            try:
                for ch in self.usable_channels:
                    self.midi_out.set_instrument(self.current_instrument, channel=ch)
            except Exception:
                pass

    def set_volume(self, volume: int):
        """設定鋼琴總音量 (0 ~ 200)"""
        self.volume = max(0, min(200, int(volume)))
        if self.midi_out:
            try:
                cc7_val = int(min(100, self.volume) * 1.27)
                for ch in self.usable_channels:
                    self.midi_out.write_short(0xB0 + ch, 7, cc7_val)
            except Exception:
                pass

    def note_on(self, midi_num: int, velocity: int = 105):
        if self.midi_out and 21 <= midi_num <= 108 and self.volume > 0:
            try:
                # 1. 輪替選取下一個可用頻道 (Round-Robin Voice Allocation)
                ch = self.usable_channels[self.channel_idx % len(self.usable_channels)]
                self.channel_idx += 1
                
                # 2. 力度增益計算
                scaled_v = int(velocity * (self.volume / 100.0))
                v = max(1, min(127, scaled_v))
                
                # 3. 復音數保護：若當前發聲總數達到上限，提前釋放最舊的音符 (Voice Stealing)
                while len(self.active_voices_fifo) >= self.MAX_POLYPHONY:
                    old_note, old_ch = self.active_voices_fifo.popleft()
                    try:
                        self.midi_out.note_off(old_note, 0, old_ch)
                        if old_ch in self.active_note_channels[old_note]:
                            self.active_note_channels[old_note].remove(old_ch)
                    except Exception:
                        pass
                
                # 4. 發聲並記錄
                self.midi_out.note_on(midi_num, v, ch)
                self.active_note_channels[midi_num].append(ch)
                self.active_voices_fifo.append((midi_num, ch))
                return ch
            except Exception:
                pass
        return None

    def note_off(self, midi_num: int, channel: Optional[int] = None):
        if self.midi_out and 21 <= midi_num <= 108:
            try:
                # 準確釋放該音符所屬的通道 (若無指定則釋放最舊的一個活躍通道)
                ch_list = self.active_note_channels.get(midi_num, [])
                if channel is not None and channel in ch_list:
                    ch = channel
                    ch_list.remove(ch)
                elif ch_list:
                    ch = ch_list.pop(0)
                else:
                    ch = None

                if ch is not None:
                    self.midi_out.note_off(midi_num, 0, ch)
                    try:
                        self.active_voices_fifo.remove((midi_num, ch))
                    except ValueError:
                        pass
            except Exception:
                pass

    def set_sustain_pedal(self, is_down: bool):
        """控制延音踏板 (Sustain / Damper Pedal - CC 64)"""
        if self.midi_out:
            try:
                val = 127 if is_down else 0
                for ch in self.usable_channels:
                    self.midi_out.write_short(0xB0 + ch, 64, val)
            except Exception:
                pass

    def all_notes_off(self):
        if self.midi_out:
            try:
                for ch in self.usable_channels:
                    self.midi_out.write_short(0xB0 + ch, 64, 0)
                    self.midi_out.write_short(0xB0 + ch, 120, 0)
                    self.midi_out.write_short(0xB0 + ch, 123, 0)
                self.active_note_channels.clear()
                self.active_voices_fifo.clear()
            except Exception:
                pass

SOUND_ENGINE: Optional[ClassicalPianoSoundEngine] = None

def init_piano_synthesizer(volume: int = 100):
    global SOUND_ENGINE
    if SOUND_ENGINE is None:
        SOUND_ENGINE = ClassicalPianoSoundEngine(volume=volume)
    else:
        SOUND_ENGINE.set_volume(volume)

def format_time_str(seconds: float) -> str:
    """格式化時間為 mm:ss"""
    if seconds < 0:
        seconds = 0
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def format_speed_str(speed: float) -> str:
    """格式化倍速顯示字串 (如: 1.0x, 1.25x, 1.5x, 2.0x)"""
    s = round(float(speed), 2)
    if s == int(s):
        return f"{int(s)}.0x"
    s_str = f"{s:.2f}".rstrip('0')
    if s_str.endswith('.'):
        s_str += '0'
    return f"{s_str}x"

def parse_speed_str(speed_str: str) -> float:
    """解析倍速字串為浮點數 (支援 0.05 ~ 50.0)"""
    try:
        clean = str(speed_str).lower().replace('x', '').replace('倍', '').replace('速', '').replace('✏️', '').replace('自訂', '').replace('...', '').strip()
        return max(0.05, min(50.0, round(float(clean), 2)))
    except Exception:
        return 1.0

def get_piano_settings_path():
    p1 = os.path.join("data", "piano_settings.json")
    if os.path.exists("data"):
        return p1
    return "piano_settings.json"

def load_piano_settings():
    path = get_piano_settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_piano_settings(data_dict):
    path = get_piano_settings_path()
    try:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        cur = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cur = json.load(f)
            except Exception:
                cur = {}
        cur.update(data_dict)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ────────────────────────────────────────────────────────
# 🖥️ 4. 88 鍵虛擬鋼琴 GUI (自適應大視窗 + 解除大小鎖定 + 可拖動時間軸)
# ────────────────────────────────────────────────────────
class VirtualPianoGUI:
    def __init__(self, root, auto_midi_path: str = "", auto_title: str = "", auto_close: bool = False, is_loop: bool = False, is_random: bool = False, initial_volume: int = 100, initial_speed: float = 1.0):
        self.root = root
        self.root.title("🎹 7L 88 鍵古典平台鋼琴 - Synthesia 瀑布流 & BitMidi 雲端曲庫")
        
        # 讀取已保存的視窗幾何尺寸與位置，若無則依螢幕解析度設定寬敞舒適的大視窗
        settings = load_piano_settings()
        saved_geo = settings.get("geometry", "")
        
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        
        if saved_geo:
            try:
                self.root.geometry(saved_geo)
            except Exception:
                init_w = min(1680, max(1360, int(sw * 0.82)))
                init_h = min(760, max(540, int(sh * 0.58)))
                init_x = max(0, (sw - init_w) // 2)
                init_y = max(0, (sh - init_h) // 2 - 40)
                self.root.geometry(f"{init_w}x{init_h}+{init_x}+{init_y}")
        else:
            # 預設寬敞舒適大視窗 (例如 1560x580，置中)
            init_w = min(1680, max(1360, int(sw * 0.82)))
            init_h = min(760, max(540, int(sh * 0.58)))
            init_x = max(0, (sw - init_w) // 2)
            init_y = max(0, (sh - init_h) // 2 - 40)
            self.root.geometry(f"{init_w}x{init_h}+{init_x}+{init_y}")

        self.root.minsize(960, 380)
        self.root.resizable(True, True)  # 🔓 徹底解鎖視窗自由縮放與最大化！
        self.root.configure(bg="#0f1015")
        
        self.auto_midi_path = auto_midi_path
        self.auto_title = auto_title
        self.auto_close = auto_close
        
        # 播放模式：循環播放 / 隨機連播 / 可手彈模式開關
        self.is_loop = is_loop
        self.is_random = is_random
        self.is_manual_play = False  # 🎹 鋼琴手動預設關 (預設為純自動演奏狀態，不顯示快捷字母鍵)
        self.current_base_c = 48     # 🎼 基準 C 音符 (預設 48 = C3 標準中音檔)
        self.pitch_var = tk.StringVar(value=PITCH_PRESETS[2]["name"])
        
        # 🔊 音量控制 (0 ~ 200)
        self.current_volume = max(0, min(200, int(initial_volume)))
        self.prev_volume = self.current_volume if self.current_volume > 0 else 100
        if SOUND_ENGINE:
            SOUND_ENGINE.set_volume(self.current_volume)
            
        # ⚡ 播放倍速控制 (0.05x ~ 50.0x，預設 1.0x)
        self.playback_speed = max(0.05, min(50.0, round(float(initial_speed), 2)))
        self.SPEED_OPTIONS = [
            "0.25x", "0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "1.75x", 
            "2.0x", "2.5x", "3.0x", "4.0x", "5.0x", "10.0x", "✏️ 自訂倍速..."
        ]
        self.last_perf_time = None
        
        self.key_rects = {}
        self.key_type = {}
        self.key_labels = {}
        self.key_x_coords = {}
        
        # 瀑布流與時間線參數 (依初始視窗動態計算)
        try:
            cur_geo = self.root.geometry()
            init_win_w = int(cur_geo.split('x')[0]) if 'x' in cur_geo else 1560
            init_win_h = int(cur_geo.split('x')[1].split('+')[0]) if 'x' in cur_geo else 580
        except Exception:
            init_win_w, init_win_h = 1560, 580
            
        self.canvas_width = max(800, init_win_w - 30)
        self.canvas_height = max(260, init_win_h - 75)
        self.waterfall_height = int(self.canvas_height * 0.62)
        self.piano_top = self.waterfall_height + 4
        self.piano_height = self.canvas_height - self.piano_top - 4
        self.FALL_TIME = 1.6
        self.SPEED_PX_PER_SEC = self.waterfall_height / self.FALL_TIME
        
        # 演奏狀態 (支援多軌 MIDI 同時並發執行，無數量限制！)
        self.is_playing = False
        self.active_tracks = []         # [{'id', 'title', 'midi_path', 'events', 'event_times', 'event_idx', 'current_song_time', 'total_duration', 'theme'}, ...]
        self._track_counter = 0
        self.playback_events = []        # 相容主軌
        self.playback_event_times = []
        self.playback_event_idx = 0
        self.playback_start_perf = 0.0
        self.current_song_time = 0.0
        self.paused_song_time = 0.0
        self.total_song_duration = 0.0
        self.active_falling_bars = []
        self.current_song_title = ""
        self.current_midi_path = ""
        
        # 時間軸拖動狀態
        self.is_dragging_timeline = False
        self.drag_seek_time = 0.0
        self.current_instrument_name = "🎹 古典平台鋼琴 (Grand Piano)"
        self._last_status_broadcast_time = 0.0
        self._resize_save_timer = None
        
        self.search_results_cache = []
        self.local_midi_files = {}

        # 📡 NDI 廣播與背景模式
        self.is_frameless = False
        self._current_bg_mode = "DARK"
        self.ndi_broadcaster = PianoNDIBroadcaster(self.get_window_bbox)
        
        self.setup_ui()
        self.bind_keyboard_events()
        self.refresh_local_library()
        self.animate_timeline_loop()
        self.start_ipc_command_server()
        
        # 綁定 NDI / 舞台快捷鍵 (F9: NDI, F10: 背景, F11: 無邊框舞台) 與視窗縮放監聽
        self.root.bind("<F9>", lambda e: self.toggle_ndi_broadcast())
        self.root.bind("<F10>", lambda e: self.cycle_bg_mode())
        self.root.bind("<F11>", self.toggle_frameless_stage)
        self.root.bind("<Configure>", self.on_window_configure)
        self.root.bind("<Destroy>", self._on_window_destroy)
        self.broadcast_piano_status("window_opened")
        self.start_heartbeat_loop()
        
        if self.auto_midi_path and os.path.exists(self.auto_midi_path):
            t = self.auto_title or os.path.basename(self.auto_midi_path)
            self.root.after(300, lambda: self.start_midi_playback(t, self.auto_midi_path))
        
    def start_heartbeat_loop(self):
        """每 1 秒發送一次心跳至主系統 Port 39281，確保鋼琴與 7L 主系統即時互通雙向在線"""
        def _beat():
            try:
                if hasattr(self, 'root') and self.root.winfo_exists():
                    self.broadcast_piano_status("heartbeat")
                    self.root.after(1000, _beat)
            except Exception:
                pass
        self.root.after(1000, _beat)

    def broadcast_piano_status(self, event: str = "update"):
        """將鋼琴視窗當前的即時全量狀態透過 UDP 廣播給 7L 主腦 (Port 39281)"""
        try:
            active_track_titles = [t['title'] for t in self.active_tracks] if self.active_tracks else ([self.current_song_title] if self.current_song_title else [])
            cur_t = max(0.0, float(self.current_song_time))
            tot_t = float(self.total_song_duration)
            prog_pct = round((cur_t / tot_t * 100.0), 1) if tot_t > 0 else 0.0
            
            inst_name = getattr(self, 'current_instrument_name', '')
            if not inst_name and hasattr(self, 'inst_var'):
                inst_name = self.inst_var.get()
            if not inst_name:
                inst_name = "🎹 古典平台鋼琴 (Grand Piano)"

            is_actually_playing = bool(self.is_playing) and (event not in ["closed", "piano_shutdown", "stopped"])
            is_window_alive = (event not in ["closed", "piano_shutdown"])
            
            status_payload = {
                "type": "PIANO_STATUS",
                "event": event,
                "is_alive": is_window_alive,
                "is_window_open": is_window_alive,
                "is_playing": is_actually_playing,
                "title": (self.current_song_title if is_actually_playing else ""),
                "tracks": (active_track_titles if is_actually_playing else []),
                "current_time": round(cur_t, 1),
                "total_duration": round(tot_t, 1),
                "progress_percent": prog_pct,
                "current_time_str": format_time_str(cur_t),
                "total_duration_str": format_time_str(tot_t),
                "speed": float(self.playback_speed),
                "volume": int(self.current_volume),
                "instrument": inst_name,
                "is_loop": bool(self.is_loop),
                "is_random": bool(self.is_random),
                "is_manual_play": bool(self.is_manual_play),
                "base_c": int(self.current_base_c),
                "pid": os.getpid(),
                "timestamp": time.time()
            }
            msg_bytes = json.dumps(status_payload, ensure_ascii=False).encode('utf-8')
            SYNC_UDP_SOCK.sendto(msg_bytes, SYNC_UDP_ADDR)
        except Exception:
            pass

    def start_ipc_command_server(self):
        """啟動本地 UDP 指令接收服務 (Port 39282)，支援 7L 大腦無縫切歌、多曲同時並發合奏、調音量、停止與關閉"""
        import socket
        import json
        import threading

        def server_thread():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", 39282))
            except Exception as e:
                print(f"⚠️ [Piano IPC] Socket 綁定失敗: {e}")
                return

            while True:
                try:
                    data, addr = sock.recvfrom(8192)
                    if not data:
                        continue
                    cmd_obj = json.loads(data.decode('utf-8'))
                    cmd = cmd_obj.get("cmd", "")
                    if cmd == "play":
                        title = cmd_obj.get("title", "")
                        midi_path = cmd_obj.get("midi_path", "")
                        vol = cmd_obj.get("volume")
                        spd = cmd_obj.get("speed")
                        if vol is not None:
                            self.root.after(0, lambda v=vol: self.set_piano_volume(v))
                        if spd is not None:
                            self.root.after(0, lambda s=spd: self.set_playback_speed(s))
                        if midi_path and os.path.exists(midi_path):
                            def do_play(t=title, p=midi_path):
                                try:
                                    self.root.deiconify()
                                    self.root.lift()
                                except Exception:
                                    pass
                                self.start_midi_playback(t, p)
                            self.root.after(0, do_play)
                    elif cmd in ["play_simultaneous", "play_multi", "mashup"]:
                        # 🌟 多曲同時並發演奏 (無數量限制！)
                        tracks = cmd_obj.get("tracks", [])
                        vol = cmd_obj.get("volume")
                        spd = cmd_obj.get("speed")
                        if vol is not None:
                            self.root.after(0, lambda v=vol: self.set_piano_volume(v))
                        if spd is not None:
                            self.root.after(0, lambda s=spd: self.set_playback_speed(s))
                        if tracks:
                            def do_multi(tr=tracks):
                                try:
                                    self.root.deiconify()
                                    self.root.lift()
                                except Exception:
                                    pass
                                self.start_multi_midi_playback(tr)
                            self.root.after(0, do_multi)
                    elif cmd in ["bring_to_front", "open", "show"]:
                        def do_show():
                            try:
                                self.root.deiconify()
                                self.root.lift()
                            except Exception:
                                pass
                        self.root.after(0, do_show)
                    elif cmd == "add_track":
                        title = cmd_obj.get("title", "")
                        midi_path = cmd_obj.get("midi_path", "")
                        if midi_path and os.path.exists(midi_path):
                            self.root.after(0, lambda t=title, p=midi_path: self.add_concurrent_track(t, p))
                    elif cmd == "stop":
                        self.root.after(0, self.stop_playback)
                    elif cmd == "set_volume":
                        vol = cmd_obj.get("volume", 100)
                        self.root.after(0, lambda v=vol: self.set_piano_volume(v))
                    elif cmd == "set_speed":
                        spd = cmd_obj.get("speed", 1.0)
                        self.root.after(0, lambda s=spd: self.set_playback_speed(s))
                    elif cmd == "set_instrument":
                        inst = cmd_obj.get("instrument", 0)
                        if isinstance(inst, str):
                            found = False
                            for k, v in MIDI_INSTRUMENTS.items():
                                if inst.lower() in k.lower():
                                    self.root.after(0, lambda p=v, n=k: self.set_piano_instrument(p, n))
                                    found = True
                                    break
                            if not found:
                                try:
                                    p_num = int(inst)
                                    self.root.after(0, lambda p=p_num: self.set_piano_instrument(p))
                                except Exception:
                                    pass
                        elif isinstance(inst, int):
                            self.root.after(0, lambda p=inst: self.set_piano_instrument(p))
                    elif cmd == "set_manual_play":
                        is_man = cmd_obj.get("is_manual", True)
                        self.root.after(0, lambda m=is_man: self.set_manual_play_mode(m))
                    elif cmd == "set_pitch":
                        p_off = cmd_obj.get("offset", 0)
                        self.root.after(0, lambda o=p_off: self.set_pitch_offset(o))
                    elif cmd == "step_pitch_up":
                        self.root.after(0, self.step_pitch_up)
                    elif cmd == "step_pitch_down":
                        self.root.after(0, self.step_pitch_down)
                    elif cmd == "close":
                        def do_close():
                            try:
                                self.broadcast_piano_status("closed")
                            except Exception:
                                pass
                            try:
                                self.root.destroy()
                            except Exception:
                                pass
                            import threading
                            threading.Timer(0.1, lambda: os._exit(0)).start()
                        self.root.after(0, do_close)
                    elif cmd == "ping":
                        # 💓 收到主系統在線檢測 Ping，立即回覆 pong 狀態包
                        self.root.after(0, lambda: self.broadcast_piano_status("pong"))
                except Exception:
                    pass

        t = threading.Thread(target=server_thread, daemon=True)
        t.start()

    def set_status_text(self, text: str):
        """將狀態即時顯示在頂部時間軸微光標籤中"""
        self.tl_canvas.itemconfig(self.tl_title_txt, text=text)

    def on_volume_slider_changed(self, val):
        """當滑動音量桿時即時調整音量"""
        vol = int(float(val))
        self.set_piano_volume(vol, from_slider=True)

    def on_volume_mousewheel(self, event):
        """滾輪在音量區滾動時增減音量"""
        delta = 5 if event.delta > 0 else -5
        new_vol = max(0, min(200, self.current_volume + delta))
        self.set_piano_volume(new_vol)

    def set_piano_volume(self, vol: int, from_slider: bool = False):
        """設定鋼琴音量並同步更新 UI 與聲音引擎 (0 ~ 200)"""
        vol = max(0, min(200, int(vol)))
        self.current_volume = vol
        if vol > 0:
            self.prev_volume = vol
            
        try:
            piano_set_path = os.path.join("data", "piano_settings.json") if os.path.exists("data") else "piano_settings.json"
            with open(piano_set_path, "w", encoding="utf-8") as f:
                json.dump({"volume": int(vol), "speed": float(self.current_speed)}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
            
        if SOUND_ENGINE:
            SOUND_ENGINE.set_volume(vol)
            
        if not from_slider and hasattr(self, 'volume_var'):
            self.volume_var.set(vol)
        if hasattr(self, 'lbl_volume'):
            self.lbl_volume.config(text=f"{vol}%")
        
        if hasattr(self, 'btn_mute'):
            if vol == 0:
                self.btn_mute.config(text="🔇", fg="#e06c75")
            elif vol < 50:
                self.btn_mute.config(text="🔉", fg="#f472b6")
            else:
                self.btn_mute.config(text="🔊", fg="#f472b6")
        self.broadcast_piano_status("volume_changed")

    def toggle_mute(self):
        """點擊音量圖示切換靜音 / 恢復音量"""
        if self.current_volume > 0:
            self.set_piano_volume(0)
            self.set_status_text("🔇 鋼琴已靜音")
        else:
            restore_vol = self.prev_volume if self.prev_volume > 0 else 80
            self.set_piano_volume(restore_vol)
            self.set_status_text(f"🔊 鋼琴音量已恢復至 {restore_vol}%")

    def on_speed_selected(self, event=None):
        """當在下拉選單選取倍速時即時切換 (支援自訂倍速)"""
        val_str = self.speed_var.get().strip()
        if "自訂" in val_str or "custom" in val_str.lower() or val_str.startswith("✏️"):
            # 彈出自訂倍速輸入框
            custom_val = simpledialog.askstring(
                "自訂倍速", 
                f"請輸入自訂播放倍速 (0.05 ~ 50.0)：\n當前倍速: {format_speed_str(self.playback_speed)}",
                initialvalue=f"{self.playback_speed:.2f}".rstrip('0').rstrip('.'),
                parent=self.root
            )
            if custom_val:
                spd = parse_speed_str(custom_val)
                self.set_playback_speed(spd)
            else:
                self.speed_var.set(format_speed_str(self.playback_speed))
            return
            
        spd = parse_speed_str(val_str)
        self.set_playback_speed(spd, from_ui=True)

    def on_speed_mousewheel(self, event):
        """滾輪在倍速選單滾動時升降倍速檔位"""
        delta = 1 if event.delta > 0 else -1
        self.step_speed(delta)

    def step_speed(self, step: int):
        """依序在預設倍速檔位中切換"""
        speeds = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0]
        closest_idx = min(range(len(speeds)), key=lambda i: abs(speeds[i] - self.playback_speed))
        new_idx = max(0, min(len(speeds) - 1, closest_idx + step))
        self.set_playback_speed(speeds[new_idx])

    def set_playback_speed(self, speed: float, from_ui: bool = False):
        """設定鋼琴演奏倍速並同步更新 UI 與狀態 (0.05 ~ 50.0)"""
        speed = max(0.05, min(50.0, round(float(speed), 2)))
        self.playback_speed = speed
        spd_str = format_speed_str(speed)
        
        if hasattr(self, 'speed_var'):
            self.speed_var.set(spd_str)
            
        self.set_status_text(f"⚡ 播放倍速已設定為: {spd_str}")
        self.broadcast_piano_status("speed_changed")

    def on_instrument_selected(self, event=None):
        """當在下拉選單選取不同音色時即時切換"""
        name = self.inst_var.get()
        if name in MIDI_INSTRUMENTS:
            prog_id = MIDI_INSTRUMENTS[name]
            self.set_piano_instrument(prog_id, name)

    def set_piano_instrument(self, program_num: int, name: str = ""):
        """設定發聲音色並同步 UI 與聲音引擎"""
        program_num = max(0, min(127, int(program_num)))
        if SOUND_ENGINE:
            SOUND_ENGINE.set_instrument(program_num)
        if not name:
            for k, v in MIDI_INSTRUMENTS.items():
                if v == program_num:
                    name = k
                    break
            if not name:
                name = f"MIDI 音色 #{program_num}"
        self.current_instrument_name = name
        if hasattr(self, 'inst_var'):
            self.inst_var.set(name)
        self.set_status_text(f"🎻 音色已切換為: {name}")
        self.broadcast_piano_status("instrument_changed")

    def _on_window_destroy(self, e):
        if e.widget == self.root:
            self.save_window_geometry()
            if hasattr(self, 'ndi_broadcaster') and self.ndi_broadcaster:
                try:
                    self.ndi_broadcaster.stop()
                except Exception:
                    pass
            try:
                self.broadcast_piano_status("closed")
            except Exception:
                pass
            import threading
            threading.Timer(0.15, lambda: os._exit(0)).start()

    def get_window_bbox(self):
        try:
            if not self.root.winfo_exists():
                return None
            # 優先抓取瀑布流 + 鋼琴鍵盤區域 (提供最乾淨的琴鍵與瀑布流)
            if hasattr(self, 'canvas') and self.canvas.winfo_exists():
                cx = self.canvas.winfo_rootx()
                cy = self.tl_canvas.winfo_rooty() if hasattr(self, 'tl_canvas') and self.tl_canvas.winfo_exists() else self.canvas.winfo_rooty()
                cw = self.canvas.winfo_width()
                ch = (self.canvas.winfo_rooty() + self.canvas.winfo_height()) - cy
                if cw > 50 and ch > 50:
                    return {"top": int(cy), "left": int(cx), "width": int(cw), "height": int(ch)}

            rx = self.root.winfo_rootx()
            ry = self.root.winfo_rooty()
            rw = self.root.winfo_width()
            rh = self.root.winfo_height()
            return {"top": int(ry), "left": int(rx), "width": int(rw), "height": int(rh)}
        except Exception:
            return None

    def toggle_ndi_broadcast(self):
        """切換 NDI 廣播開關 (可透過 F9 快捷鍵切換)"""
        if self.ndi_broadcaster.running:
            self.ndi_broadcaster.stop()
            if hasattr(self, 'btn_ndi'):
                self.btn_ndi.config(text="📡 NDI:關", bg="#2d3139", fg="#abb2bf")
            self.set_status_text("📡 NDI 串流廣播已關閉")
        else:
            success = self.ndi_broadcaster.start()
            if success:
                if hasattr(self, 'btn_ndi'):
                    self.btn_ndi.config(text="📡 NDI:開", bg="#059669", fg="#ffffff")
                self.set_status_text("📡 NDI 串流廣播已啟動 (名稱: 🎹 7L Virtual Piano)")
            else:
                self.set_status_text("⚠️ 無法啟動 NDI 廣播，請確認已安裝 ndi-python 套件")

    def cycle_bg_mode(self):
        """循環切換背景顏色 (深黑 / 綠幕 / 純黑，可透過 F10 切換)"""
        modes = [
            ("DARK", "#0a0a0e", "#14161f", "#0f1015", "🎨 深黑"),
            ("GREEN", "#00ff00", "#00ff00", "#00ff00", "🟩 綠幕"),
            ("BLACK", "#000000", "#000000", "#000000", "🖤 純黑")
        ]
        curr = getattr(self, '_current_bg_mode', 'DARK')
        next_idx = 0
        for i, (m, _, _, _, _) in enumerate(modes):
            if m == curr:
                next_idx = (i + 1) % len(modes)
                break
        mode_id, c_bg, tl_bg, r_bg, label = modes[next_idx]
        self._current_bg_mode = mode_id
        
        try:
            self.root.configure(bg=r_bg)
            if hasattr(self, 'canvas'): self.canvas.configure(bg=c_bg)
            if hasattr(self, 'tl_canvas'): self.tl_canvas.configure(bg=tl_bg)
            if hasattr(self, 'btn_bg_mode'): self.btn_bg_mode.config(text=label)
            self.set_status_text(f"🎨 背景已切換為: {label}")
        except Exception:
            pass

    def set_bg_mode(self, mode_name: str):
        """指定背景顏色模式 (DARK / GREEN / BLACK)"""
        mode_name = mode_name.upper()
        if mode_name == "GREEN":
            self._current_bg_mode = "GREEN"
            self.root.configure(bg="#00ff00")
            if hasattr(self, 'canvas'): self.canvas.configure(bg="#00ff00")
            if hasattr(self, 'tl_canvas'): self.tl_canvas.configure(bg="#00ff00")
            if hasattr(self, 'btn_bg_mode'): self.btn_bg_mode.config(text="🟩 綠幕")
        elif mode_name == "BLACK":
            self._current_bg_mode = "BLACK"
            self.root.configure(bg="#000000")
            if hasattr(self, 'canvas'): self.canvas.configure(bg="#000000")
            if hasattr(self, 'tl_canvas'): self.tl_canvas.configure(bg="#000000")
            if hasattr(self, 'btn_bg_mode'): self.btn_bg_mode.config(text="🖤 純黑")
        else:
            self._current_bg_mode = "DARK"
            self.root.configure(bg="#0f1015")
            if hasattr(self, 'canvas'): self.canvas.configure(bg="#0a0a0e")
            if hasattr(self, 'tl_canvas'): self.tl_canvas.configure(bg="#14161f")
            if hasattr(self, 'btn_bg_mode'): self.btn_bg_mode.config(text="🎨 深黑")

    def toggle_frameless_stage(self, event=None):
        """切換無邊框舞台模式 (按 F11 快捷鍵)"""
        self.is_frameless = not getattr(self, 'is_frameless', False)
        try:
            self.root.overrideredirect(self.is_frameless)
            if hasattr(self, 'btn_stage'):
                self.btn_stage.config(
                    text="🪟 舞台:開" if self.is_frameless else "🪟 舞台:關",
                    bg="#7c3aed" if self.is_frameless else "#2d3139",
                    fg="#ffffff" if self.is_frameless else "#abb2bf"
                )
            self.set_status_text("🪟 已切換至無邊框舞台模式 (按 F11 退出)" if self.is_frameless else "🪟 已恢復標準視窗模式")
        except Exception:
            pass

    def setup_ui(self):
        # 1. 簡潔整合控制列 (單行極簡工具列)
        ctrl_bar = tk.Frame(self.root, bg="#161822", pady=4, padx=8)
        ctrl_bar.pack(fill=tk.X)
        
        # 本機曲庫選單
        tk.Label(ctrl_bar, text="🎼", font=("Segoe UI", 9, "bold"), fg="#f472b6", bg="#161822").pack(side=tk.LEFT, padx=(0, 2))
        self.local_midi_var = tk.StringVar()
        self.local_menu = ttk.Combobox(ctrl_bar, textvariable=self.local_midi_var, width=17, state="readonly")
        self.local_menu.pack(side=tk.LEFT, padx=2)
        self.local_menu.bind("<<ComboboxSelected>>", self.on_local_song_selected)
        
        self.btn_play = tk.Button(ctrl_bar, text="▶", font=("Segoe UI", 9, "bold"), bg="#f472b6", fg="#ffffff", padx=6, pady=1, relief=tk.FLAT, command=self.toggle_play_current)
        self.btn_play.pack(side=tk.LEFT, padx=2)
        
        self.btn_stop = tk.Button(ctrl_bar, text="⏹", font=("Segoe UI", 9), bg="#2d3139", fg="#abb2bf", padx=5, pady=1, relief=tk.FLAT, command=self.stop_playback)
        self.btn_stop.pack(side=tk.LEFT, padx=2)

        # 🔁 循環播放按鈕
        loop_bg = "#be185d" if self.is_loop else "#2d3139"
        loop_fg = "#ffffff" if self.is_loop else "#abb2bf"
        loop_txt = "🔁 循環:開" if self.is_loop else "🔁 循環"
        self.btn_loop = tk.Button(ctrl_bar, text=loop_txt, font=("Segoe UI", 8, "bold" if self.is_loop else "normal"), bg=loop_bg, fg=loop_fg, padx=3, pady=1, relief=tk.FLAT, command=self.toggle_loop_mode)
        self.btn_loop.pack(side=tk.LEFT, padx=2)

        # 🔀 隨機一直播放按鈕
        rand_bg = "#7c3aed" if self.is_random else "#2d3139"
        rand_fg = "#ffffff" if self.is_random else "#abb2bf"
        rand_txt = "🔀 隨機:開" if self.is_random else "🔀 隨機"
        self.btn_random = tk.Button(ctrl_bar, text=rand_txt, font=("Segoe UI", 8, "bold" if self.is_random else "normal"), bg=rand_bg, fg=rand_fg, padx=3, pady=1, relief=tk.FLAT, command=self.toggle_random_mode)
        self.btn_random.pack(side=tk.LEFT, padx=2)
        
        # 🎹 可手彈按鈕開關 (手動鍵盤滑鼠演奏開關)
        man_bg = "#059669" if self.is_manual_play else "#2d3139"
        man_fg = "#ffffff" if self.is_manual_play else "#abb2bf"
        man_txt = "🎹 手彈:開" if self.is_manual_play else "🎹 手彈:關"
        self.btn_manual = tk.Button(ctrl_bar, text=man_txt, font=("Segoe UI", 8, "bold" if self.is_manual_play else "normal"), bg=man_bg, fg=man_fg, padx=3, pady=1, relief=tk.FLAT, command=self.toggle_manual_play_mode, cursor="hand2")
        self.btn_manual.pack(side=tk.LEFT, padx=2)
        
        # 🎼 音高調節控制區 (降音 🔽 / 選單 / 升音 🔼)
        self.btn_pitch_down = tk.Button(ctrl_bar, text="🔽", font=("Segoe UI", 8, "bold"), bg="#2d3139", fg="#ffc5d3", padx=3, pady=1, relief=tk.FLAT, command=self.step_pitch_down, cursor="hand2")
        self.btn_pitch_down.pack(side=tk.LEFT, padx=(1, 0))
        
        self.pitch_menu = ttk.Combobox(ctrl_bar, textvariable=self.pitch_var, values=[p["name"] for p in PITCH_PRESETS], width=13, state="readonly")
        self.pitch_menu.pack(side=tk.LEFT, padx=1)
        self.pitch_menu.bind("<<ComboboxSelected>>", self.on_pitch_selected)
        
        self.btn_pitch_up = tk.Button(ctrl_bar, text="🔼", font=("Segoe UI", 8, "bold"), bg="#2d3139", fg="#ffc5d3", padx=3, pady=1, relief=tk.FLAT, command=self.step_pitch_up, cursor="hand2")
        self.btn_pitch_up.pack(side=tk.LEFT, padx=(0, 2))
        
        btn_open = tk.Button(ctrl_bar, text="📂", font=("Segoe UI", 9), bg="#2d3139", fg="#abb2bf", padx=5, pady=1, relief=tk.FLAT, command=self.load_custom_file)
        btn_open.pack(side=tk.LEFT, padx=(2, 3))

        # 分隔線
        tk.Label(ctrl_bar, text="|", font=("Segoe UI", 9), fg="#3e4451", bg="#161822").pack(side=tk.LEFT, padx=2)

        # ⚡ 倍速調節選單 (支援 0.25x ~ 10.0x / 自訂倍速，支援鍵盤輸入與滾輪微調)
        tk.Label(ctrl_bar, text="⚡", font=("Segoe UI", 9, "bold"), fg="#f472b6", bg="#161822").pack(side=tk.LEFT, padx=(2, 0))
        self.speed_var = tk.StringVar(value=format_speed_str(self.playback_speed))
        self.speed_menu = ttk.Combobox(
            ctrl_bar, 
            textvariable=self.speed_var, 
            values=self.SPEED_OPTIONS, 
            width=8, 
            state="normal"
        )
        self.speed_menu.pack(side=tk.LEFT, padx=2)
        self.speed_menu.bind("<<ComboboxSelected>>", self.on_speed_selected)
        self.speed_menu.bind("<Return>", lambda e: self.on_speed_selected())
        self.speed_menu.bind("<MouseWheel>", self.on_speed_mousewheel)

        # 分隔線
        tk.Label(ctrl_bar, text="|", font=("Segoe UI", 9), fg="#3e4451", bg="#161822").pack(side=tk.LEFT, padx=2)

        # 🔊 音量調節控制區 (喇叭圖標 + 滑動桿 + 百分比)
        self.btn_mute = tk.Button(ctrl_bar, text="🔊", font=("Segoe UI", 9, "bold"), bg="#161822", fg="#f472b6", padx=2, pady=1, relief=tk.FLAT, command=self.toggle_mute, cursor="hand2")
        self.btn_mute.pack(side=tk.LEFT, padx=(2, 0))
        
        self.volume_var = tk.IntVar(value=self.current_volume)
        self.scale_volume = tk.Scale(
            ctrl_bar,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=self.volume_var,
            command=self.on_volume_slider_changed,
            showvalue=0,
            length=65,
            bg="#161822",
            fg="#ffc5d3",
            troughcolor="#282c34",
            activebackground="#f472b6",
            highlightthickness=0,
            bd=0,
            sliderrelief=tk.FLAT,
            sliderlength=12,
            cursor="hand2"
        )
        self.scale_volume.pack(side=tk.LEFT, padx=1)
        
        self.lbl_volume = tk.Label(ctrl_bar, text=f"{self.current_volume}%", font=("Consolas", 8, "bold"), fg="#ffc5d3", bg="#161822", width=5, anchor="w")
        self.lbl_volume.pack(side=tk.LEFT, padx=(0, 2))

        # 綁定滾輪微調音量
        self.btn_mute.bind("<MouseWheel>", self.on_volume_mousewheel)
        self.scale_volume.bind("<MouseWheel>", self.on_volume_mousewheel)
        self.lbl_volume.bind("<MouseWheel>", self.on_volume_mousewheel)

        # 分隔線
        tk.Label(ctrl_bar, text="|", font=("Segoe UI", 9), fg="#3e4451", bg="#161822").pack(side=tk.LEFT, padx=2)

        # 🎻 音色選擇下拉選單
        tk.Label(ctrl_bar, text="🎻", font=("Segoe UI", 9, "bold"), fg="#f472b6", bg="#161822").pack(side=tk.LEFT, padx=(2, 1))
        self.inst_var = tk.StringVar(value="🎹 古典平台鋼琴 (Grand Piano)")
        self.inst_menu = ttk.Combobox(ctrl_bar, textvariable=self.inst_var, values=list(MIDI_INSTRUMENTS.keys()), width=15, state="readonly")
        self.inst_menu.pack(side=tk.LEFT, padx=2)
        self.inst_menu.bind("<<ComboboxSelected>>", self.on_instrument_selected)

        # 分隔線
        tk.Label(ctrl_bar, text="|", font=("Segoe UI", 9), fg="#3e4451", bg="#161822").pack(side=tk.LEFT, padx=2)

        # 雲端搜尋
        tk.Label(ctrl_bar, text="🌐 BitMidi:", font=("Segoe UI", 9, "bold"), fg="#ffc5d3", bg="#161822").pack(side=tk.LEFT, padx=(3, 2))
        
        self.entry_search = tk.Entry(ctrl_bar, font=("Segoe UI", 9), bg="#0f1015", fg="#ffffff", insertbackground="white", width=12, relief=tk.SOLID, bd=1)
        self.entry_search.pack(side=tk.LEFT, padx=2)
        self.entry_search.insert(0, "Chopin")
        self.entry_search.bind("<Return>", lambda e: self.do_search_bitmidi())
        
        btn_search = tk.Button(ctrl_bar, text="🔍", font=("Segoe UI", 9, "bold"), bg="#ffc5d3", fg="#121318", padx=5, pady=1, relief=tk.FLAT, command=self.do_search_bitmidi)
        btn_search.pack(side=tk.LEFT, padx=2)
        
        self.search_result_var = tk.StringVar(value="輸入曲名搜尋")
        self.search_menu = ttk.Combobox(ctrl_bar, textvariable=self.search_result_var, width=16, state="readonly")
        self.search_menu.pack(side=tk.LEFT, padx=2)
        
        self.btn_download_play = tk.Button(ctrl_bar, text="⬇ 下載演奏", font=("Segoe UI", 8, "bold"), bg="#be185d", fg="#ffffff", padx=5, pady=1, relief=tk.FLAT, command=self.download_and_play_search_result)
        self.btn_download_play.pack(side=tk.LEFT, padx=2)

        # 分隔線
        tk.Label(ctrl_bar, text="|", font=("Segoe UI", 9), fg="#3e4451", bg="#161822").pack(side=tk.LEFT, padx=2)

        # 📡 NDI 廣播與背景模式
        self.btn_ndi = tk.Button(ctrl_bar, text="📡 NDI:關", font=("Segoe UI", 8, "bold"), bg="#2d3139", fg="#abb2bf", padx=4, pady=1, relief=tk.FLAT, command=self.toggle_ndi_broadcast, cursor="hand2")
        self.btn_ndi.pack(side=tk.LEFT, padx=2)

        self.btn_bg_mode = tk.Button(ctrl_bar, text="🎨 深黑", font=("Segoe UI", 8), bg="#2d3139", fg="#abb2bf", padx=4, pady=1, relief=tk.FLAT, command=self.cycle_bg_mode, cursor="hand2")
        self.btn_bg_mode.pack(side=tk.LEFT, padx=2)

        self.btn_stage = tk.Button(ctrl_bar, text="🪟 舞台", font=("Segoe UI", 8), bg="#2d3139", fg="#abb2bf", padx=4, pady=1, relief=tk.FLAT, command=self.toggle_frameless_stage, cursor="hand2")
        self.btn_stage.pack(side=tk.LEFT, padx=2)

        # ────────────────────────────────────────────────────────
        # ⏱️ 2. 下落動畫框頂部：可拖動時間軸 (Interactive Timeline)
        # ────────────────────────────────────────────────────────
        self.tl_width = self.canvas_width
        self.tl_height = 26
        self.tl_track_x1 = 12
        self.tl_track_x2 = max(200, self.tl_width - 110)
        self.tl_track_y = 13
        
        self.timeline_frame = tk.Frame(self.root, bg="#0f1015", padx=15, pady=2)
        self.timeline_frame.pack(fill=tk.X)
        
        self.tl_canvas = tk.Canvas(
            self.timeline_frame, 
            width=self.tl_width, 
            height=self.tl_height, 
            bg="#14161f", 
            highlightthickness=1, 
            highlightbackground="#282c34"
        )
        self.tl_canvas.pack(fill=tk.X, expand=True)
        
        # 時間軸背景軌道
        self.tl_track_bg = self.tl_canvas.create_rectangle(
            self.tl_track_x1, self.tl_track_y - 3, 
            self.tl_track_x2, self.tl_track_y + 3, 
            fill="#21252b", outline=""
        )
        
        # 進度填滿條 (櫻花粉色光條)
        self.tl_prog_rect = self.tl_canvas.create_rectangle(
            self.tl_track_x1, self.tl_track_y - 3, 
            self.tl_track_x1, self.tl_track_y + 3, 
            fill="#f472b6", outline=""
        )
        
        # 拖動手柄 (Thumb Handle)
        self.tl_thumb = self.tl_canvas.create_oval(
            self.tl_track_x1 - 6, self.tl_track_y - 6, 
            self.tl_track_x1 + 6, self.tl_track_y + 6, 
            fill="#ffffff", outline="#f472b6", width=2
        )
        
        # 歌曲名稱顯示
        self.tl_title_txt = self.tl_canvas.create_text(
            self.tl_track_x1 + 8, self.tl_track_y - 8, 
            text="🎵 就緒 (真實古典平台鋼琴音色 | 粉白黑深粉主題)", font=("Segoe UI", 8, "bold"), fill="#ffc5d3", anchor="w"
        )
        
        # 時間文字標籤
        self.tl_time_txt = self.tl_canvas.create_text(
            self.tl_width - 12, self.tl_track_y, 
            text="00:00 / 00:00", font=("Consolas", 9, "bold"), fill="#abb2bf", anchor="e"
        )
        
        # 綁定時間軸滑鼠拖動跳轉事件
        self.tl_canvas.bind("<Button-1>", self.on_timeline_click)
        self.tl_canvas.bind("<B1-Motion>", self.on_timeline_drag)
        self.tl_canvas.bind("<ButtonRelease-1>", self.on_timeline_release)

        # ────────────────────────────────────────────────────────
        # 🌊 3. 88 鍵瀑布流 + 鋼琴畫布 Canvas (自適應高寬度)
        # ────────────────────────────────────────────────────────
        self.canvas = tk.Canvas(
            self.root, 
            width=self.canvas_width, 
            height=self.canvas_height, 
            bg="#0a0a0e", 
            highlightthickness=1, 
            highlightbackground="#282c34"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=15, pady=(2, 2))
        
        self.draw_waterfall_and_piano()

    def on_window_configure(self, event):
        """當使用者拉伸縮放或最大化視窗時，智慧動態重繪與等比縮放 88 鍵盤、瀑布流與時間軸"""
        if event.widget != self.root:
            return
            
        win_w = self.root.winfo_width()
        win_h = self.root.winfo_height()
        if win_w < 100 or win_h < 100:
            return
            
        target_cw = max(800, win_w - 30)
        target_ch = max(260, win_h - 75)
        
        # 防抖過濾微小抖動
        if abs(target_cw - self.canvas_width) > 2 or abs(target_ch - self.canvas_height) > 2:
            self.canvas_width = target_cw
            self.canvas_height = target_ch
            self.waterfall_height = int(self.canvas_height * 0.62)
            self.piano_top = self.waterfall_height + 4
            self.piano_height = self.canvas_height - self.piano_top - 4
            self.SPEED_PX_PER_SEC = self.waterfall_height / self.FALL_TIME
            
            # 更新時間軸
            self.tl_width = self.canvas_width
            self.tl_track_x2 = max(200, self.tl_width - 110)
            if hasattr(self, 'tl_canvas') and self.tl_canvas.winfo_exists():
                self.tl_canvas.config(width=self.tl_width)
                if hasattr(self, 'tl_track_bg'):
                    self.tl_canvas.coords(self.tl_track_bg, self.tl_track_x1, self.tl_track_y - 3, self.tl_track_x2, self.tl_track_y + 3)
                if hasattr(self, 'tl_time_txt'):
                    self.tl_canvas.coords(self.tl_time_txt, self.tl_width - 12, self.tl_track_y)
                self.update_timeline_ui(self.current_song_time)
            
            # 更新畫布尺寸並重繪琴鍵
            if hasattr(self, 'canvas') and self.canvas.winfo_exists():
                self.canvas.config(width=self.canvas_width, height=self.canvas_height)
                self.canvas.delete("all")
                self.draw_waterfall_and_piano()
            
            # 防抖儲存視窗大小
            if getattr(self, '_resize_save_timer', None):
                try:
                    self.root.after_cancel(self._resize_save_timer)
                except Exception:
                    pass
            self._resize_save_timer = self.root.after(800, self.save_window_geometry)

    def save_window_geometry(self):
        """保存當前視窗幾何尺寸與位置"""
        try:
            if self.root.winfo_exists() and not getattr(self, 'is_frameless', False):
                geo = self.root.geometry()
                save_piano_settings({"geometry": geo})
        except Exception:
            pass

    def draw_waterfall_and_piano(self):
        """繪製瀑布流軌道背景、擊鍵光刃基準線與 88 鍵黑白琴鍵"""
        num_white = len(WHITE_KEYS)  # 52
        w_width = self.canvas_width / num_white
        b_width = w_width * 0.64
        
        # 1. 繪製瀑布流垂直微光軌道
        for idx in range(num_white + 1):
            x = idx * w_width + 2
            self.canvas.create_line(x, 0, x, self.waterfall_height, fill="#12131a", width=1)
            
        # 2. 計算並儲存所有 88 鍵的 X 座標
        for idx, (key_id, midi, name, char) in enumerate(WHITE_KEYS):
            x1 = idx * w_width + 2
            x2 = x1 + w_width - 1
            self.key_x_coords[midi] = (x1, x2, False)
            self.key_x_coords[key_id] = (x1, x2, False)
            if char: self.key_x_coords[char] = (x1, x2, False)
            
        for key_id, midi, name, white_idx, char in BLACK_KEYS:
            center_x = (white_idx + 1) * w_width + 2
            x1 = center_x - b_width / 2
            x2 = center_x + b_width / 2
            self.key_x_coords[midi] = (x1, x2, True)
            self.key_x_coords[key_id] = (x1, x2, True)
            if char: self.key_x_coords[char] = (x1, x2, True)

        # 3. 擊鍵光刃線 (Laser Hit Line - 櫻花粉光刃)
        self.canvas.create_rectangle(0, self.waterfall_height - 3, self.canvas_width, self.waterfall_height + 2, fill="#1e293b", outline="")
        self.hit_line = self.canvas.create_line(0, self.waterfall_height, self.canvas_width, self.waterfall_height, fill="#f472b6", width=2)
        
        # 4. 繪製 52 個白鍵 (y = 246 ~ 391)
        p_top = self.piano_top
        p_bottom = p_top + self.piano_height
        
        for idx, (key_id, midi, name, char) in enumerate(WHITE_KEYS):
            x1, x2, _ = self.key_x_coords[midi]
            y1 = p_top
            y2 = p_bottom
            
            fill_color = "#ffffff" if not name.startswith("C") else "#fff5f7"
            rect = self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill_color, outline="#64748b", width=1)
            
            char = VP_MAP_REV_WHITE.get(key_id, '')
            label_text = char if (self.is_manual_play and char) else (name if name.startswith("C") or name == "A0" else "")
            label_color = "#0f172a" if (self.is_manual_play and char) else "#94a3b8"
            font_size = 8 if (self.is_manual_play and char) else 7
            lbl = self.canvas.create_text((x1 + x2)/2, y2 - 12, text=label_text, font=("Segoe UI", font_size, "bold"), fill=label_color)
            
            self.key_rects[key_id] = rect
            self.key_rects[midi] = rect
            if char: self.key_rects[char] = rect
            self.key_type[key_id] = 'white'
            self.key_type[midi] = 'white'
            if char: self.key_type[char] = 'white'
            self.key_labels[key_id] = lbl
            
            self.canvas.tag_bind(rect, "<Button-1>", lambda e, m=midi, k=key_id: self.play_midi_interactive(m, k))
            self.canvas.tag_bind(lbl, "<Button-1>", lambda e, m=midi, k=key_id: self.play_midi_interactive(m, k))
            
        # 5. 繪製 36 個黑鍵 (覆蓋在白鍵上方)
        b_height = self.piano_height * 0.62
        for key_id, midi, name, white_idx, char in BLACK_KEYS:
            x1, x2, _ = self.key_x_coords[midi]
            y1 = p_top
            y2 = p_top + b_height
            
            rect = self.canvas.create_rectangle(x1, y1, x2, y2, fill="#18181b", outline="#09090b", width=1)
            b_char = VP_MAP_REV_BLACK.get(key_id, '') if self.is_manual_play else ""
            lbl = self.canvas.create_text((x1 + x2)/2, y2 - 10, text=b_char, font=("Segoe UI", 7, "bold"), fill="#ffc5d3")
            
            self.key_rects[key_id] = rect
            self.key_rects[midi] = rect
            if char: self.key_rects[char] = rect
            self.key_type[key_id] = 'black'
            self.key_type[midi] = 'black'
            if char: self.key_type[char] = 'black'
            self.key_labels[key_id] = lbl
            
            self.canvas.tag_bind(rect, "<Button-1>", lambda e, m=midi, k=key_id: self.play_midi_interactive(m, k))
            self.canvas.tag_bind(lbl, "<Button-1>", lambda e, m=midi, k=key_id: self.play_midi_interactive(m, k))

    # ────────────────────────────────────────────────────────
    # ⏱️ 時間軸拖動與跳轉 (Draggable Timeline Seeking Logic)
    # ────────────────────────────────────────────────────────
    def get_time_from_x(self, x: float) -> float:
        track_w = self.tl_track_x2 - self.tl_track_x1
        clamped_x = max(self.tl_track_x1, min(self.tl_track_x2, x))
        ratio = (clamped_x - self.tl_track_x1) / track_w
        return ratio * self.total_song_duration

    def update_timeline_ui(self, current_sec: float):
        """更新時間軸滑塊與進度條位置"""
        if self.total_song_duration <= 0:
            ratio = 0.0
        else:
            ratio = max(0.0, min(1.0, current_sec / self.total_song_duration))
            
        track_w = self.tl_track_x2 - self.tl_track_x1
        thumb_x = self.tl_track_x1 + ratio * track_w
        
        self.tl_canvas.coords(
            self.tl_prog_rect, 
            self.tl_track_x1, self.tl_track_y - 3, 
            thumb_x, self.tl_track_y + 3
        )
        self.tl_canvas.coords(
            self.tl_thumb, 
            thumb_x - 6, self.tl_track_y - 6, 
            thumb_x + 6, self.tl_track_y + 6
        )
        
        cur_str = format_time_str(current_sec)
        tot_str = format_time_str(self.total_song_duration)
        self.tl_canvas.itemconfig(self.tl_time_txt, text=f"{cur_str} / {tot_str}")

    def on_timeline_click(self, event):
        if not self.playback_events or self.total_song_duration <= 0:
            return
        self.is_dragging_timeline = True
        self.drag_seek_time = self.get_time_from_x(event.x)
        self.update_timeline_ui(self.drag_seek_time)

    def on_timeline_drag(self, event):
        if not self.is_dragging_timeline or self.total_song_duration <= 0:
            return
        self.drag_seek_time = self.get_time_from_x(event.x)
        self.update_timeline_ui(self.drag_seek_time)

    def on_timeline_release(self, event):
        if not self.is_dragging_timeline or self.total_song_duration <= 0:
            return
        self.is_dragging_timeline = False
        seek_sec = self.get_time_from_x(event.x)
        self.seek_to_time(seek_sec)

    def seek_to_time(self, seek_sec: float):
        """將播放進度無縫跳轉到指定的秒數 (支援多軌同步精準跳轉)"""
        if not self.active_tracks and not self.playback_events:
            return
            
        seek_sec = max(0.0, min(self.total_song_duration, seek_sec))
        
        if SOUND_ENGINE:
            SOUND_ENGINE.all_notes_off()
        
        # 1. 調整開始基準時間與記錄點
        self.playback_start_perf = time.perf_counter() - (seek_sec + self.FALL_TIME)
        self.paused_song_time = seek_sec
        self.current_song_time = seek_sec
        self.last_perf_time = time.perf_counter()
        
        # 2. 定位各軌道事件索引 (從 seek_sec 前置預落時間開始找，確保跳轉後立即有下落方塊)
        for track in self.active_tracks:
            track['current_song_time'] = seek_sec
            track['paused_song_time'] = seek_sec
            track['event_idx'] = bisect.bisect_left(track['event_times'], max(0.0, seek_sec - self.FALL_TIME))
            
        if self.playback_events:
            self.playback_event_idx = bisect.bisect_left(self.playback_event_times, max(0.0, seek_sec - self.FALL_TIME))
        
        # 3. 清理畫面上殘留的下落方塊並復原琴鍵
        for bar in self.active_falling_bars:
            self.canvas.delete(bar['id'])
        self.active_falling_bars.clear()
        self.release_all_keys()
        
        self.is_playing = True
        self.btn_play.config(text="⏸ 暫停", bg="#be185d", fg="#ffffff")
        spd_tag = f" [{format_speed_str(self.playback_speed)}]" if self.playback_speed != 1.0 else ""
        self.set_status_text(f"⏩ 跳轉至 {format_time_str(seek_sec)}{spd_tag} | 《{self.current_song_title}》")
        self.broadcast_piano_status("seek")

    def toggle_loop_mode(self):
        """切換單曲循環播放模式 (🔁 循環播放)"""
        self.is_loop = not self.is_loop
        if self.is_loop:
            self.is_random = False
            self.btn_loop.config(text="🔁 循環: 開", bg="#be185d", fg="#ffffff", font=("Segoe UI", 9, "bold"))
            self.btn_random.config(text="🔀 隨機連播", bg="#2d3139", fg="#abb2bf", font=("Segoe UI", 9, "normal"))
            self.set_status_text(f"🔁 已開啟「循環播放」模式（曲目播畢後將自動重新演奏）")
            # 若尚未載入任何曲目且未在播放，才啟動選定曲目
            if not self.is_playing and not self.playback_events:
                self.play_selected_local()
        else:
            self.btn_loop.config(text="🔁 循環播放", bg="#2d3139", fg="#abb2bf", font=("Segoe UI", 9, "normal"))
            self.set_status_text("⏹ 已關閉「循環播放」模式")
        self.broadcast_piano_status("mode_changed")

    def toggle_random_mode(self):
        """切換隨機一直播放模式 (🔀 隨機連播：按下按鈕並在背景自動查音樂放入曲庫)"""
        self.is_random = not self.is_random
        if self.is_random:
            self.is_loop = False
            self.btn_random.config(text="🔀 隨機: 開", bg="#7c3aed", fg="#ffffff", font=("Segoe UI", 9, "bold"))
            self.btn_loop.config(text="🔁 循環播放", bg="#2d3139", fg="#abb2bf", font=("Segoe UI", 9, "normal"))
            self.set_status_text(f"🔀 已按下「隨機連播」按鈕！7L 正在背景搜尋新曲目放入曲庫...")
            # 若尚未載入任何曲目且未在播放，立即在背景查曲並開始演奏！
            if not self.is_playing and not self.playback_events:
                self.play_random_song(exclude_current=False)
        else:
            self.btn_random.config(text="🔀 隨機連播", bg="#2d3139", fg="#abb2bf", font=("Segoe UI", 9, "normal"))
            self.set_status_text("⏹ 已關閉「隨機連播」模式")
        self.broadcast_piano_status("mode_changed")

    def toggle_manual_play_mode(self):
        """切換鍵盤與滑鼠手彈模式開關 (🎹 手彈:開 / 關)"""
        self.is_manual_play = not self.is_manual_play
        man_bg = "#059669" if self.is_manual_play else "#2d3139"
        man_fg = "#ffffff" if self.is_manual_play else "#abb2bf"
        man_txt = "🎹 手彈:開" if self.is_manual_play else "🎹 手彈:關"
        self.btn_manual.config(text=man_txt, bg=man_bg, fg=man_fg, font=("Segoe UI", 8, "bold" if self.is_manual_play else "normal"))
        if self.is_manual_play:
            self.set_status_text("🎹 已開啟「手彈模式」：可直接使用電腦鍵盤 (1~0, Q~P, A~L, Z~M) 或滑鼠點擊 88 琴鍵演奏！")
        else:
            self.set_status_text("🎹 已關閉「手彈模式」：手動琴鍵彈奏已鎖定（純自動演奏模式）。")
        self.update_key_labels_visibility()
        self.broadcast_piano_status("manual_mode_changed")

    def set_manual_play_mode(self, enabled: bool):
        """設定手彈模式"""
        if self.is_manual_play != enabled:
            self.is_manual_play = enabled
            man_bg = "#059669" if self.is_manual_play else "#2d3139"
            man_fg = "#ffffff" if self.is_manual_play else "#abb2bf"
            man_txt = "🎹 手彈:開" if self.is_manual_play else "🎹 手彈:關"
            if hasattr(self, 'btn_manual'):
                self.btn_manual.config(text=man_txt, bg=man_bg, fg=man_fg, font=("Segoe UI", 8, "bold" if self.is_manual_play else "normal"))
            self.update_key_labels_visibility()
            self.broadcast_piano_status("manual_mode_changed")

    def step_pitch_up(self):
        """升一個音高檔位（向右高音移位，覆蓋右側高音 C8）"""
        cur_idx = self.get_current_pitch_preset_index()
        if cur_idx < len(PITCH_PRESETS) - 1:
            self.set_pitch_preset_by_index(cur_idx + 1)
        else:
            self.set_pitch_preset_by_index(0)

    def step_pitch_down(self):
        """降一個音高檔位（向左低音移位，覆蓋左側低音）"""
        cur_idx = self.get_current_pitch_preset_index()
        if cur_idx > 0:
            self.set_pitch_preset_by_index(cur_idx - 1)
        else:
            self.set_pitch_preset_by_index(len(PITCH_PRESETS) - 1)

    def get_current_pitch_preset_index(self) -> int:
        for idx, p in enumerate(PITCH_PRESETS):
            if p["base_c"] == self.current_base_c:
                return idx
        return 2

    def set_pitch_preset_by_index(self, idx: int):
        idx = max(0, min(len(PITCH_PRESETS) - 1, idx))
        p = PITCH_PRESETS[idx]
        self.set_pitch_base_c(p["base_c"], preset_name=p["name"], desc=p["desc"])

    def on_pitch_selected(self, event=None):
        sel_name = self.pitch_var.get()
        for idx, p in enumerate(PITCH_PRESETS):
            if p["name"] == sel_name:
                self.set_pitch_preset_by_index(idx)
                break

    def set_pitch_base_c(self, base_c: int, preset_name: str = "", desc: str = ""):
        """設定琴鍵基準 C 音符 (24~72) 並同步更新所有 88 琴鍵字元標籤與 VP_MAP 映射"""
        self.current_base_c = max(21, min(72, base_c))
        compute_pitch_mappings(self.current_base_c)
        
        if not preset_name:
            for p in PITCH_PRESETS:
                if p["base_c"] == self.current_base_c:
                    preset_name = p["name"]
                    desc = p["desc"]
                    break
            if not preset_name:
                preset_name = f"🎼 基準 C: #{self.current_base_c}"
                desc = f"自訂基準 C #{self.current_base_c}"
                
        if hasattr(self, 'pitch_var'):
            self.pitch_var.set(preset_name)
            
        self.update_key_labels_visibility()
        self.set_status_text(f"🎼 琴鍵音高已切換為：【{desc}】")
        self.broadcast_piano_status("pitch_changed")

    def update_key_labels_visibility(self):
        """根據手彈模式開關與當前音高檔位動態刷新琴鍵上的按鍵提示標籤"""
        for key_id, lbl in self.key_labels.items():
            k_type = self.key_type.get(key_id, 'white')
            if k_type == 'white':
                char = VP_MAP_REV_WHITE.get(key_id, '')
                name = key_id
                if self.is_manual_play and char:
                    label_text = char
                    label_color = "#0f172a"
                    font_size = 8
                else:
                    label_text = name if (name.startswith("C") or name == "A0") else ""
                    label_color = "#94a3b8"
                    font_size = 7
                try:
                    self.canvas.itemconfig(lbl, text=label_text, fill=label_color, font=("Segoe UI", font_size, "bold"))
                except Exception:
                    pass
            else:
                char = VP_MAP_REV_BLACK.get(key_id, '')
                label_text = char if self.is_manual_play else ""
                try:
                    self.canvas.itemconfig(lbl, text=label_text, fill="#ffc5d3")
                except Exception:
                    pass

    def play_random_song(self, exclude_current: bool = True):
        """隨機挑選曲目：若本機已有則直接演奏；若選到新曲則在背景向 BitMidi 搜尋並下載放入曲庫後無縫演奏"""
        self.refresh_local_library()
        
        local_songs = list(self.local_midi_files.keys())
        cur = self.local_midi_var.get()
        
        # 1. 結合本機曲庫與雲端熱門種子曲庫
        all_candidates = list(local_songs)
        for seed in RANDOM_PIANO_SEEDS:
            if seed not in all_candidates:
                all_candidates.append(seed)
                
        valid_candidates = [s for s in all_candidates if s != cur] if (exclude_current and len(all_candidates) > 1) else all_candidates
        if not valid_candidates:
            valid_candidates = all_candidates
            
        chosen_item = random.choice(valid_candidates)
        
        # 2. 若該曲已在本機曲庫中，直接平滑開始演奏
        if chosen_item in self.local_midi_files and os.path.exists(self.local_midi_files[chosen_item]):
            chosen_path = self.local_midi_files[chosen_item]
            self.local_midi_var.set(chosen_item)
            self.start_midi_playback(chosen_item, chosen_path)
            spd_tag = f" [{format_speed_str(self.playback_speed)}]" if self.playback_speed != 1.0 else ""
            self.set_status_text(f"🔀 隨機連播{spd_tag}：正在演奏 《{chosen_item}》")
            return
            
        # 3. 若為雲端種子曲目（本機尚未收錄）：在背景自動向 BitMidi 搜尋並下載放入曲庫！
        self.set_status_text(f"🌐 [背景查歌] 7L 正在向 BitMidi 雲端搜尋《{chosen_item}》並放入曲庫...")
        
        def background_fetch_and_play():
            try:
                dl_path = bitmidi_engine.fetch_and_download_first_match(chosen_item, save_dir=MIDI_SHEETS_DIR)
                if dl_path and os.path.exists(dl_path):
                    def on_ready():
                        self.refresh_local_library()
                        new_title = f"🎵 {os.path.basename(dl_path).replace('.mid', '').replace('.MID', '')}"
                        self.local_midi_var.set(new_title)
                        self.start_midi_playback(new_title, dl_path)
                        spd_tag = f" [{format_speed_str(self.playback_speed)}]" if self.playback_speed != 1.0 else ""
                        self.set_status_text(f"🔀 隨機連播{spd_tag}：已從雲端收錄並開始演奏 《{new_title}》！")
                    self.root.after(0, on_ready)
                else:
                    def on_fallback():
                        if local_songs:
                            fb_song = random.choice(local_songs)
                            fb_p = self.local_midi_files.get(fb_song)
                            if fb_p and os.path.exists(fb_p):
                                self.local_midi_var.set(fb_song)
                                self.start_midi_playback(fb_song, fb_p)
                                spd_tag = f" [{format_speed_str(self.playback_speed)}]" if self.playback_speed != 1.0 else ""
                                self.set_status_text(f"🔀 隨機連播{spd_tag}：正在演奏本機精選 《{fb_song}》")
                    self.root.after(0, on_fallback)
            except Exception:
                pass
                
        threading.Thread(target=background_fetch_and_play, daemon=True).start()

    # ────────────────────────────────────────────────────────
    # 🔄 曲目選取與無縫中途切歌 (Smooth Song Switching)
    # ────────────────────────────────────────────────────────
    def on_local_song_selected(self, event=None):
        """當使用者從下拉選單選取新歌曲時，立即平滑中途切歌"""
        name = self.local_midi_var.get()
        p = self.local_midi_files.get(name)
        if p and os.path.exists(p):
            self.start_midi_playback(name, p)

    def refresh_local_library(self):
        """掃描 midi_sheets 資料夾更新本機選單 (自動清理非 .mid 檔案)"""
        if os.path.exists(MIDI_SHEETS_DIR):
            for fname in list(os.listdir(MIDI_SHEETS_DIR)):
                fpath = os.path.join(MIDI_SHEETS_DIR, fname)
                if os.path.isfile(fpath) and fname.lower() != "midi_catalog.json":
                    if not fname.lower().endswith(('.mid', '.midi')):
                        try: os.remove(fpath)
                        except Exception: pass
        self.local_midi_files.clear()
        
        friendly_names = {
            "campanella.mid": "🔔 鐘 (Liszt - La Campanella)",
            "moonlight_3rd.mid": "⚡ 月光奏鳴曲 第三樂章 (Beethoven - Moonlight 3rd)",
            "liebestraum.mid": "❤️ 愛之夢 第三號 (Liszt - Liebestraum No. 3)",
            "Liebestraum-1.mid": "❤️ 愛之夢 (版本二 / Liebestraum Var. 1)",
            "winter_wind.mid": "❄️ 冬風練習曲 (Chopin - Winter Wind Op. 25 No. 11)",
            "maidens_prayer.mid": "🙏 少女的祈禱 (Badarzewska - A Maiden's Prayer)",
            "fantaisie_impromptu.mid": "💫 幻想即興曲 (Chopin - Fantaisie-Impromptu Op. 66)",
            "canon_in_d.mid": "🎻 卡農 (Pachelbel - Canon in D)",
            "Bagatella Fur Elise.mid": "🌸 給愛麗絲 (Beethoven - Für Elise)",
            "Spirited Away - Boiler Mushi.mid": "🏮 神隱少女 (久石讓 - Spirited Away)",
            "alla-turca.mid": "🎼 土耳其進行曲 (Mozart - Alla Turca)",
            "Clair-De-Lune-Opus-46-Nr-1.mid": "🌙 月光 (Debussy - Clair de Lune)",
            "Jasper Folks - River Flows in You.mid": "💧 你的心河 (River Flows in You)",
            "frederic-chopin-nocturne-no20.mid": "🌃 蕭邦 第20號夜曲 (Nocturne No. 20)",
        }
        
        if os.path.exists(MIDI_SHEETS_DIR):
            for fname in sorted(os.listdir(MIDI_SHEETS_DIR)):
                if fname.lower().endswith('.mid') or fname.lower().endswith('.midi'):
                    display_name = friendly_names.get(fname, f"🎵 {fname}")
                    full_p = os.path.join(MIDI_SHEETS_DIR, fname)
                    self.local_midi_files[display_name] = full_p
                    
        names = list(self.local_midi_files.keys())
        self.local_menu['values'] = names
        if names:
            if not self.local_midi_var.get() or self.local_midi_var.get() not in names:
                self.local_midi_var.set(names[0])

    def do_search_bitmidi(self):
        """搜尋 BitMidi 雲端曲庫"""
        q = self.entry_search.get().strip()
        if not q:
            messagebox.showwarning("提示", "請先輸入想搜尋的歌曲名稱或作曲家！")
            return
            
        self.set_status_text(f"🔍 正在連線 BitMidi 搜尋《{q}》...")
        
        def worker():
            res = bitmidi_engine.search_bitmidi(q)
            self.root.after(0, lambda: self.on_search_finished(q, res))
            
        threading.Thread(target=worker, daemon=True).start()

    def on_search_finished(self, query: str, results: List[Dict[str, str]]):
        self.search_results_cache = results
        if not results:
            self.search_result_var.set("❌ 未找到相關歌曲")
            self.search_menu['values'] = []
            self.set_status_text(f"⚠️ 未找到與《{query}》相關的曲目。")
            return
            
        titles = [r['title'] for r in results]
        self.search_menu['values'] = titles
        self.search_result_var.set(titles[0])
        self.set_status_text(f"✅ 找到 {len(results)} 首《{query}》曲目！點選「⬇ 下載演奏」即可播放！")

    def download_and_play_search_result(self):
        """下載選取的搜尋結果並即刻開始演奏"""
        idx = self.search_menu.current()
        if idx < 0 or idx >= len(self.search_results_cache):
            messagebox.showwarning("提示", "請先搜尋並從下拉選單選擇一首歌曲！")
            return
            
        target_song = self.search_results_cache[idx]
        self.set_status_text(f"⬇ 正在下載《{target_song['title']}》...")
        
        def worker():
            saved_path = bitmidi_engine.download_bitmidi_song(target_song, save_dir=MIDI_SHEETS_DIR)
            if saved_path and os.path.exists(saved_path):
                self.root.after(0, lambda: self.on_download_complete_play(target_song['title'], saved_path))
            else:
                self.root.after(0, lambda: messagebox.showerror("錯誤", "下載 MIDI 失敗，請重試或選擇其他版本！"))
                
        threading.Thread(target=worker, daemon=True).start()

    def on_download_complete_play(self, title: str, saved_path: str):
        self.refresh_local_library()
        self.local_midi_var.set(f"🎵 {os.path.basename(saved_path)}")
        self.start_midi_playback(title, saved_path)

    def toggle_play_current(self):
        """播放 / 暫停 切換 / 切換至選取歌曲"""
        selected_name = self.local_midi_var.get()
        selected_path = self.local_midi_files.get(selected_name)
        
        # 若選取的曲目與當前曲目不同，立即切換播放新歌！
        if selected_path and selected_path != self.current_midi_path:
            self.start_midi_playback(selected_name, selected_path)
            return

        if self.is_playing:
            # 暫停播放
            self.is_playing = False
            self.paused_song_time = self.current_song_time
            self.last_perf_time = None
            
            if SOUND_ENGINE:
                SOUND_ENGINE.all_notes_off()
                
            # 釋放琴鍵發光狀態，避免暫停時琴鍵卡在深色
            self.release_all_keys()
            
            self.btn_play.config(text="▶ 繼續", bg="#f472b6", fg="#ffffff")
            self.set_status_text(f"⏸ 已暫停 | 《{self.current_song_title}》 (進度: {format_time_str(max(0.0, self.paused_song_time))} / {format_time_str(self.total_song_duration)})")
        else:
            # 繼續播放 或 播放新歌
            has_remaining = any(t['event_idx'] < len(t['events']) for t in self.active_tracks) if self.active_tracks else (self.playback_events and self.playback_event_idx < len(self.playback_events))
            if (self.active_tracks or self.playback_events) and (has_remaining or len(self.active_falling_bars) > 0 or self.paused_song_time < self.total_song_duration):
                self.current_song_time = self.paused_song_time
                self.playback_start_perf = time.perf_counter() - (self.paused_song_time + self.FALL_TIME)
                self.last_perf_time = time.perf_counter()
                self.is_playing = True
                
                # 對於剛好壓在擊鍵線上的長音符，重新啟動琴鍵按下狀態與發聲
                for bar in self.active_falling_bars:
                    if bar.get('is_holding'):
                        m = bar['midi']
                        self.set_key_pressed(m, True, is_left_hand=bar.get('is_lh'))
                        if SOUND_ENGINE:
                            bar['channel'] = SOUND_ENGINE.note_on(m, velocity=bar.get('vel', 105))
                            
                self.btn_play.config(text="⏸ 暫停", bg="#be185d", fg="#ffffff")
                mode_tag = " [🔁 循環]" if self.is_loop else (" [🔀 隨機]" if self.is_random else "")
                spd_tag = f" [{format_speed_str(self.playback_speed)}]" if self.playback_speed != 1.0 else ""
                self.set_status_text(f"▶ [正在演奏{mode_tag}{spd_tag}] 《{self.current_song_title}》 | 進度: {format_time_str(max(0.0, self.paused_song_time))} / {format_time_str(self.total_song_duration)}")
            else:
                # 播放選取的本機曲目
                self.play_selected_local()

    def play_selected_local(self):
        name = self.local_midi_var.get()
        p = self.local_midi_files.get(name)
        if p and os.path.exists(p):
            self.start_midi_playback(name, p)
        else:
            messagebox.showerror("錯誤", f"找不到檔案: {p}")

    def load_custom_file(self):
        file_p = filedialog.askopenfilename(filetypes=[("MIDI Files", "*.mid;*.midi")])
        if file_p:
            fname = os.path.basename(file_p)
            self.start_midi_playback(f"📂 {fname}", file_p)

    def extract_midi_timeline(self, midi_path: str) -> List[Tuple[float, int, float, int, Optional[bool]]]:
        """
        將 MIDI 樂譜檔案解析為精確的時間軸事件串列 [(hit_time, midi, duration, velocity, hand_tag), ...]
        - 若 MIDI 軌道明確寫有 Left Hand / Bass / 左手 ➔ hand_tag = True (左手)
        - 若 MIDI 軌道明確寫有 Right Hand / Treble / 右手 ➔ hand_tag = False (右手)
        - 若 MIDI 未明確寫清楚左右手 ➔ hand_tag = None (100% 維持之前一樣的 4 色全隨機混搭！)
        """
        mid = mido.MidiFile(midi_path, clip=True)
        
        # 1. 偵測軌道是否包含明確的左右手名稱
        track_hand_map = {}
        lh_keywords = ['left', 'lh', 'l.h.', 'bass', 'lower', '左手', '左']
        rh_keywords = ['right', 'rh', 'r.h.', 'treble', 'upper', '右手', '右']
        has_explicit_lh = False
        has_explicit_rh = False

        for trk_idx, trk in enumerate(mid.tracks):
            trk_name = ""
            for msg in trk:
                if msg.type in ['track_name', 'text']:
                    trk_name += (" " + str(getattr(msg, 'name', getattr(msg, 'text', ''))))
            clean_name = trk_name.lower()
            if any(k in clean_name for k in lh_keywords) and not any(k in clean_name for k in rh_keywords):
                track_hand_map[trk_idx] = True # 左手
                has_explicit_lh = True
            elif any(k in clean_name for k in rh_keywords) and not any(k in clean_name for k in lh_keywords):
                track_hand_map[trk_idx] = False # 右手
                has_explicit_rh = True

        use_explicit_hands = (has_explicit_lh or has_explicit_rh)

        events = []
        active_notes = {}
        current_time = 0.0

        for msg in mid:
            current_time += msg.time
            ch = getattr(msg, 'channel', 0)
            if msg.type == 'note_on' and msg.velocity > 0:
                note_num = max(0, min(127, int(msg.note)))
                vel = max(1, min(127, int(msg.velocity)))
                key = (ch, note_num)
                
                hand_tag = None
                if use_explicit_hands:
                    hand_tag = True if note_num < 60 else False
                    
                if key in active_notes:
                    start_t, old_vel, old_tag = active_notes.pop(key)
                    dur = max(0.18, current_time - start_t)
                    events.append((start_t, note_num, dur, old_vel, old_tag))
                active_notes[key] = (current_time, vel, hand_tag)
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                note_num = max(0, min(127, int(msg.note)))
                key = (ch, note_num)
                if key in active_notes:
                    start_t, vel, hand_tag = active_notes.pop(key)
                    dur = max(0.18, current_time - start_t)
                    events.append((start_t, note_num, dur, vel, hand_tag))

        for key, (start_t, vel, hand_tag) in active_notes.items():
            events.append((start_t, key[1], 0.35, vel, hand_tag))

        events.sort(key=lambda x: x[0])
        return events

    def start_midi_playback(self, title: str, midi_path: str, clear_existing: bool = True):
        """開始/切換 Synthesia 前置下落時間軸演奏 (支援單曲與多軌無縫切歌)"""
        if clear_existing:
            if SOUND_ENGINE:
                SOUND_ENGINE.all_notes_off()
            for bar in self.active_falling_bars:
                self.canvas.delete(bar['id'])
            self.active_falling_bars.clear()
            self.release_all_keys()
            self.active_tracks.clear()
            self._track_counter = 0
            
        try:
            events = self.extract_midi_timeline(midi_path)
            if not events:
                self.set_status_text(f"⚠️ 《{title}》 MIDI 檔案無有效音符！")
                return
                
            self._track_counter += 1
            track = {
                'id': f"trk_{self._track_counter}",
                'title': title,
                'midi_path': midi_path,
                'events': events,
                'event_times': [e[0] for e in events],
                'event_idx': 0,
                'current_song_time': -self.FALL_TIME,
                'paused_song_time': -self.FALL_TIME,
                'total_duration': events[-1][0] + events[-1][2] if events else 0.0
            }
            self.active_tracks.append(track)
            
            # 相容單軌主屬性
            self.current_song_title = title
            self.current_midi_path = midi_path
            self.playback_events = events
            self.playback_event_times = track['event_times']
            self.total_song_duration = max(t['total_duration'] for t in self.active_tracks)
            self.playback_event_idx = 0
            self.playback_start_perf = time.perf_counter()
            self.current_song_time = -self.FALL_TIME
            self.paused_song_time = -self.FALL_TIME
            self.last_perf_time = time.perf_counter()
            self.is_playing = True
            
            # 更新時間軸與狀態
            self.update_timeline_ui(0.0)
            mode_tag = " [🔁 循環]" if self.is_loop else (" [🔀 隨機]" if self.is_random else "")
            spd_tag = f" [{format_speed_str(self.playback_speed)}]" if self.playback_speed != 1.0 else ""
            self.set_status_text(f"▶ [正在演奏{mode_tag}{spd_tag}] 《{title}》 | 音符數: {len(events)} | 全長: {format_time_str(self.total_song_duration)}")
            self.btn_play.config(text="⏸ 暫停", bg="#be185d", fg="#ffffff")
            self.broadcast_piano_status("play_start")
        except Exception as e:
            self.set_status_text(f"⚠️ 解析 MIDI 失敗: {e}")

    def start_multi_midi_playback(self, tracks_info: list):
        """同時啟動多首 MIDI 即時多軌並發演奏 (無數量限制，經典粉白黑深粉 4 色瀑布流)"""
        if SOUND_ENGINE:
            SOUND_ENGINE.all_notes_off()
        for bar in self.active_falling_bars:
            self.canvas.delete(bar['id'])
        self.active_falling_bars.clear()
        self.release_all_keys()
        self.active_tracks.clear()
        self._track_counter = 0

        valid_tracks = []
        for item in tracks_info:
            if isinstance(item, dict):
                t_title = item.get("title", "")
                t_path = item.get("midi_path", "") or item.get("path", "")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                t_title, t_path = item[0], item[1]
            elif isinstance(item, str):
                t_path = item
                t_title = os.path.basename(item).replace(".mid", "").replace(".MID", "")
            else:
                continue
                
            if t_path and os.path.exists(t_path):
                evs = self.extract_midi_timeline(t_path)
                if evs:
                    self._track_counter += 1
                    valid_tracks.append({
                        'id': f"trk_{self._track_counter}",
                        'title': t_title or os.path.basename(t_path),
                        'midi_path': t_path,
                        'events': evs,
                        'event_times': [e[0] for e in evs],
                        'event_idx': 0,
                        'current_song_time': -self.FALL_TIME,
                        'paused_song_time': -self.FALL_TIME,
                        'total_duration': evs[-1][0] + evs[-1][2] if evs else 0.0
                    })

        if not valid_tracks:
            self.set_status_text("⚠️ 無有效的多軌 MIDI 檔案！")
            return

        self.active_tracks = valid_tracks
        self.total_song_duration = max(t['total_duration'] for t in self.active_tracks)
        self.current_song_time = -self.FALL_TIME
        self.paused_song_time = -self.FALL_TIME
        self.last_perf_time = time.perf_counter()
        self.is_playing = True
        self.playback_events = self.active_tracks[0]['events']
        self.playback_event_times = self.active_tracks[0]['event_times']

        # 組合標題
        titles_str = " ✕ ".join([f"《{t['title']}》" for t in self.active_tracks])
        self.current_song_title = titles_str
        self.current_midi_path = self.active_tracks[0]['midi_path']
        self.update_timeline_ui(0.0)
        self.btn_play.config(text="⏸ 暫停", bg="#be185d", fg="#ffffff")
        spd_tag = f" [{format_speed_str(self.playback_speed)}]" if self.playback_speed != 1.0 else ""
        self.set_status_text(f"🔥 [神仙打架 {len(self.active_tracks)}首同時演奏{spd_tag}] {titles_str}")
        self.broadcast_piano_status("play_start_multi")

    def add_concurrent_track(self, title: str, midi_path: str):
        """在目前正在播放的基礎上，動態追加一首歌曲同時合奏（無縫注入，不中斷當前曲目）"""
        if not os.path.exists(midi_path):
            return
        evs = self.extract_midi_timeline(midi_path)
        if not evs:
            return
        self._track_counter += 1
        new_track = {
            'id': f"trk_{self._track_counter}",
            'title': title or os.path.basename(midi_path),
            'midi_path': midi_path,
            'events': evs,
            'event_times': [e[0] for e in evs],
            'event_idx': 0,
            'current_song_time': -self.FALL_TIME,
            'paused_song_time': -self.FALL_TIME,
            'total_duration': evs[-1][0] + evs[-1][2] if evs else 0.0
        }
        self.active_tracks.append(new_track)
        self.total_song_duration = max(t['total_duration'] for t in self.active_tracks)
        self.is_playing = True
        titles_str = " ✕ ".join([f"《{t['title']}》" for t in self.active_tracks])
        self.current_song_title = titles_str
        self.btn_play.config(text="⏸ 暫停", bg="#be185d", fg="#ffffff")
        spd_tag = f" [{format_speed_str(self.playback_speed)}]" if self.playback_speed != 1.0 else ""
        self.set_status_text(f"🔥 [神仙打架 {len(self.active_tracks)}首同時演奏{spd_tag}] {titles_str}")
        self.broadcast_piano_status("track_added")

    def stop_playback(self):
        """停止所有演奏與動畫，並立即復原所有發光琴鍵"""
        if SOUND_ENGINE:
            SOUND_ENGINE.all_notes_off()
        self.is_playing = False
        self.paused_song_time = 0.0
        self.current_song_time = 0.0
        self.last_perf_time = None
        self.playback_events = []
        self.playback_event_times = []
        self.playback_event_idx = 0
        self.active_tracks.clear()
        for bar in self.active_falling_bars:
            self.canvas.delete(bar['id'])
        self.active_falling_bars.clear()
        
        # 立即復原所有琴鍵顏色
        self.release_all_keys()
            
        self.btn_play.config(text="▶ 播放", bg="#f472b6", fg="#ffffff")
        self.set_status_text("✨ 狀態：已停止。")
        self.update_timeline_ui(0.0)
        self.broadcast_piano_status("stopped")

    def animate_timeline_loop(self):
        """60 FPS Synthesia 正統多軌並發時間線下落與擊鍵發聲引擎 (經典粉白黑深粉 4 色自由搭配)"""
        if self.is_playing and (self.active_tracks or self.playback_events):
            current_perf = time.perf_counter()
            if self.last_perf_time is None:
                self.last_perf_time = current_perf
            dt_perf = current_perf - self.last_perf_time
            self.last_perf_time = current_perf
            
            delta_song_time = dt_perf * self.playback_speed
            tracks_by_id = {t['id']: t for t in self.active_tracks}
            
            # 1. 驅動各軌道時間進度並預生成即將下落的方塊 (🌸 粉白 / 黑深粉 自由搭配)
            if self.active_tracks:
                for track in self.active_tracks:
                    track['current_song_time'] += delta_song_time
                    song_t = track['current_song_time']
                    
                    while track['event_idx'] < len(track['events']):
                        event_data = track['events'][track['event_idx']]
                        hit_t, midi, dur, vel = event_data[0], event_data[1], event_data[2], event_data[3]
                        is_lh = event_data[4] if len(event_data) > 4 else (midi < 60)
                        
                        if hit_t - self.FALL_TIME <= song_t:
                            coords = self.key_x_coords.get(midi)
                            if coords:
                                x1, x2, is_black = coords
                                bar_len = max(18, int(dur * self.SPEED_PX_PER_SEC))
                                
                                # 🌸 配色選取：有寫清楚左右手才套用分色，沒寫則跟之前一樣 4 色全隨機
                                if is_lh is True:
                                    fill_col, border_col = random.choice(LH_BLACK_PALETTE if is_black else LH_WHITE_PALETTE)
                                elif is_lh is False:
                                    fill_col, border_col = random.choice(RH_BLACK_PALETTE if is_black else RH_WHITE_PALETTE)
                                else:
                                    fill_col, border_col = random.choice(BLACK_NOTE_PALETTE if is_black else WHITE_NOTE_PALETTE)
                                    
                                rect_id = self.canvas.create_rectangle(
                                    x1 + 1, -bar_len, x2 - 1, 0,
                                    fill=fill_col, outline=border_col, width=1
                                )
                                self.active_falling_bars.append({
                                    'id': rect_id,
                                    'track_id': track['id'],
                                    'midi': midi,
                                    'hit_time': hit_t,
                                    'dur': dur,
                                    'vel': vel,
                                    'is_lh': is_lh,
                                    'len': bar_len,
                                    'x1': x1 + 1,
                                    'x2': x2 - 1,
                                    'played': False,
                                    'is_holding': False
                                })
                            track['event_idx'] += 1
                        else:
                            break
                            
                max_song_time = max(t['current_song_time'] for t in self.active_tracks)
                self.current_song_time = max_song_time
            else:
                # 單軌相容
                self.current_song_time += delta_song_time
                song_t = self.current_song_time
                while self.playback_event_idx < len(self.playback_events):
                    event_data = self.playback_events[self.playback_event_idx]
                    hit_t, midi, dur, vel = event_data[0], event_data[1], event_data[2], event_data[3]
                    is_lh = event_data[4] if len(event_data) > 4 else (midi < 60)
                    
                    if hit_t - self.FALL_TIME <= song_t:
                        coords = self.key_x_coords.get(midi)
                        if coords:
                            x1, x2, is_black = coords
                            bar_len = max(18, int(dur * self.SPEED_PX_PER_SEC))
                            if is_lh is True:
                                fill_col, border_col = random.choice(LH_BLACK_PALETTE if is_black else LH_WHITE_PALETTE)
                            elif is_lh is False:
                                fill_col, border_col = random.choice(RH_BLACK_PALETTE if is_black else RH_WHITE_PALETTE)
                            else:
                                fill_col, border_col = random.choice(BLACK_NOTE_PALETTE if is_black else WHITE_NOTE_PALETTE)
                            rect_id = self.canvas.create_rectangle(
                                x1 + 1, -bar_len, x2 - 1, 0,
                                fill=fill_col, outline=border_col, width=1
                            )
                            self.active_falling_bars.append({
                                'id': rect_id,
                                'track_id': None,
                                'midi': midi,
                                'hit_time': hit_t,
                                'dur': dur,
                                'vel': vel,
                                'is_lh': is_lh,
                                'len': bar_len,
                                'x1': x1 + 1,
                                'x2': x2 - 1,
                                'played': False,
                                'is_holding': False
                            })
                        self.playback_event_idx += 1
                    else:
                        break
            
            # 更新時間軸進度
            if not self.is_dragging_timeline:
                self.update_timeline_ui(max(0.0, self.current_song_time))
            
            # 2. 驅動方塊向下移動，抵達基準線瞬間擊鍵發聲並持續按住深色直到長條結束！
            removals = []
            hit_notes_frame = []
            for bar in self.active_falling_bars:
                track = tracks_by_id.get(bar['track_id']) if bar['track_id'] else None
                cur_t = track['current_song_time'] if track else self.current_song_time
                time_to_hit = bar['hit_time'] - cur_t
                y_bottom = self.waterfall_height - (time_to_hit * self.SPEED_PX_PER_SEC)
                y_top = y_bottom - bar['len']
                
                # 🎯 碰線瞬間：古典鋼琴發聲 + 琴鍵按下變深色（持續保持到長條結束！）
                now_perf = time.perf_counter()
                if y_bottom >= self.waterfall_height and not bar['played']:
                    bar['played'] = True
                    bar['is_holding'] = True
                    bar['hit_perf_time'] = now_perf
                    m = bar['midi']
                    hit_notes_frame.append(m)
                    if SOUND_ENGINE:
                        bar['channel'] = SOUND_ENGINE.note_on(m, velocity=bar.get('vel', 105))
                    self.set_key_pressed(m, True)
                    
                # 🎵 離線瞬間：長條頂部完全通過擊鍵線（長條結束）➔ Note Off + 琴鍵彈起恢復原色
                # 🛡️ 守護音符飽滿度：音符至少需發聲 150ms，嚴防高密度音符在同一影格剛 Note On 就立即 Note Off 造成消音！
                if y_top >= self.waterfall_height:
                    hit_t = bar.get('hit_perf_time')
                    if hit_t and (now_perf - hit_t < 0.15):
                        visible_bottom = min(self.waterfall_height, y_bottom)
                        self.canvas.coords(bar['id'], bar['x1'], y_top, bar['x2'], visible_bottom)
                    else:
                        bar['is_holding'] = False
                        self.canvas.delete(bar['id'])
                        removals.append(bar)
                else:
                    # 更新畫布方塊座標
                    visible_bottom = min(self.waterfall_height, y_bottom)
                    self.canvas.coords(bar['id'], bar['x1'], y_top, bar['x2'], visible_bottom)
                    
            if hit_notes_frame:
                broadcast_piano_focus(hit_notes_frame)
                
            for r in removals:
                self.active_falling_bars.remove(r)
                m = r['midi']
                if SOUND_ENGINE:
                    SOUND_ENGINE.note_off(m, r.get('channel'))
                still_holding = any(b.get('is_holding') and b['midi'] == m for b in self.active_falling_bars)
                if not still_holding:
                    self.set_key_pressed(m, False)
                
            # 3. 檢查所有音軌是否演奏結束
            if self.active_tracks:
                all_done = all(t['event_idx'] >= len(t['events']) for t in self.active_tracks)
            else:
                all_done = self.playback_event_idx >= len(self.playback_events)
                
            if all_done and len(self.active_falling_bars) == 0:
                if self.is_loop:
                    if len(self.active_tracks) > 1:
                        t_info = [(t['title'], t['midi_path']) for t in self.active_tracks]
                        self.start_multi_midi_playback(t_info)
                    elif self.current_midi_path and os.path.exists(self.current_midi_path):
                        self.set_status_text(f"🔁 循環播放：重新開始演奏 《{self.current_song_title}》...")
                        self.start_midi_playback(self.current_song_title, self.current_midi_path)
                    else:
                        self.stop_playback()
                elif self.is_random:
                    self.set_status_text("🔀 隨機連播：準備播放下一首...")
                    self.play_random_song(exclude_current=True)
                else:
                    self.stop_playback()
                    self.set_status_text(f"🎉 《{self.current_song_title}》演奏完畢！")
                    self.broadcast_piano_status("song_finished")
                    if self.auto_close:
                        self.root.after(1200, self.root.destroy)
            else:
                # 定期心跳廣播演奏進度 (每 0.4 秒)
                now_perf = time.perf_counter()
                if getattr(self, '_last_status_broadcast_time', 0.0) + 0.4 < now_perf:
                    self._last_status_broadcast_time = now_perf
                    self.broadcast_piano_status("tick")
                
        self.root.after(16, self.animate_timeline_loop)

    def bind_keyboard_events(self):
        """綁定電腦實體鍵盤事件"""
        self.root.bind("<KeyPress>", self.on_key_press)

    def on_key_press(self, event):
        if event.widget == self.entry_search:
            return
            
        # 鍵盤快速調節音高檔位 (PageUp / F2 🔼 升音高 | PageDown / F1 🔽 降音高)
        if event.keysym in ['Prior', 'Page_Up', 'F2']:
            self.step_pitch_up()
            return
        elif event.keysym in ['Next', 'Page_Down', 'F1']:
            self.step_pitch_down()
            return

        # 🎹 當開啟手彈模式時：所有按鍵（包括 1~0, -, =, q~p, [, ], \, a~l, ;, ', z~m, ,, ., /）100% 專注於琴鍵彈奏，完全關閉 +- 音量與倍速快捷鍵！
        if not self.is_manual_play:
            # 僅在手彈模式關閉時（純自動播放狀態），才開放鍵盤 +- 調整音量與快捷調節倍速
            if event.keysym in ['minus', 'underscore'] or event.char == '-':
                self.set_piano_volume(max(0, self.current_volume - 5))
                self.set_status_text(f"🔉 鋼琴音量調低至 {self.current_volume}%")
                return
            elif event.keysym in ['equal', 'plus'] or event.char in ['+', '=']:
                self.set_piano_volume(min(200, self.current_volume + 5))
                self.set_status_text(f"🔊 鋼琴音量調高至 {self.current_volume}%")
                return
            elif event.keysym in ['bracketleft', 'less', 'comma'] or event.char in ['[', '<', ',']:
                self.step_speed(-1)
                return
            elif event.keysym in ['bracketright', 'greater', 'period'] or event.char in [']', '>', '.']:
                self.step_speed(1)
                return
            elif event.keysym in ['backslash'] or event.char == '\\':
                self.set_playback_speed(1.0)
                return
            return

        char = event.char
        if not char:
            char = event.keysym

        # 優先搜尋字符與小寫
        midi = VP_MAP.get(char) or VP_MAP.get(char.lower())
        if midi:
            broadcast_piano_focus([midi])
            if SOUND_ENGINE:
                SOUND_ENGINE.note_on(midi, 110)
                self.root.after(250, lambda m=midi: SOUND_ENGINE.note_off(m))
            self.highlight_key(midi, duration_ms=180)

    def play_midi_interactive(self, midi_num: int, key_id: str):
        """滑鼠點擊任意 88 鍵：即時發聲 + 琴鍵發光"""
        if not self.is_manual_play:
            self.set_status_text("💡 提示：目前手彈開關為【關閉】，點擊上方「🎹 手彈」按鈕即可開啟自由彈奏！")
            return
        broadcast_piano_focus([midi_num])
        if SOUND_ENGINE:
            SOUND_ENGINE.note_on(midi_num, 110)
            self.root.after(300, lambda m=midi_num: SOUND_ENGINE.note_off(m))
        self.highlight_key(midi_num, duration_ms=180)

    def set_key_pressed(self, key_identifier, is_pressed: bool, is_left_hand: Optional[bool] = None):
        """設定 88 琴鍵按下深色/彈起復原"""
        rect = self.key_rects.get(key_identifier)
        if not rect: return
        
        k_type = self.key_type.get(key_identifier, 'white')
        if is_left_hand is True:
            active_color = "#f472b6" if k_type == 'white' else "#be185d" # 🌸 左手：櫻花亮粉 / 莓果深粉
        elif is_left_hand is False:
            active_color = "#fdf2f8" if k_type == 'white' else "#2b262d" # 🤍 右手：純白霜白 / 霧炭黑
        else:
            active_color = "#f472b6" if k_type == 'white' else "#be185d" # 預設自然亮粉
            
        default_color = "#ffffff" if k_type == 'white' else "#18181b"
        target_color = active_color if is_pressed else default_color
        try:
            self.canvas.itemconfig(rect, fill=target_color)
        except Exception:
            pass

    def release_all_keys(self):
        """復原所有 88 琴鍵為原始顏色並清空定時器"""
        if hasattr(self, '_key_highlight_timers'):
            for t_id in self._key_highlight_timers.values():
                try: self.root.after_cancel(t_id)
                except Exception: pass
            self._key_highlight_timers.clear()
            
        for k_id, rect in self.key_rects.items():
            k_type = self.key_type.get(k_id, 'white')
            def_col = "#ffffff" if k_type == 'white' else "#18181b"
            try:
                self.canvas.itemconfig(rect, fill=def_col)
            except Exception:
                pass

    def highlight_key(self, key_identifier, duration_ms=180):
        """滑鼠點擊或鍵盤敲擊時的瞬態深色高亮"""
        rect = self.key_rects.get(key_identifier)
        if not rect: return
        
        if not hasattr(self, '_key_highlight_timers'):
            self._key_highlight_timers = {}
            
        old_timer = self._key_highlight_timers.get(key_identifier)
        if old_timer:
            try: self.root.after_cancel(old_timer)
            except Exception: pass

        self.set_key_pressed(key_identifier, True)
        
        def reset_color():
            self.set_key_pressed(key_identifier, False)
            if key_identifier in self._key_highlight_timers:
                del self._key_highlight_timers[key_identifier]

        self._key_highlight_timers[key_identifier] = self.root.after(duration_ms, reset_color)

# ────────────────────────────────────────────────────────
# 🚀 5. 主程式進入點 (支援 CLI 參數自動演奏與關閉)
# ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import re
    parser = argparse.ArgumentParser(description="7L 88 鍵古典平台鋼琴視覺化演奏引擎 (支援 NDI 串流廣播)")
    parser.add_argument("--midi", type=str, default="", help="啟動時直接自動載入並演奏的 MIDI 檔案路徑 (多首可用 | 或 , 分隔)")
    parser.add_argument("--multi-midi", type=str, default="", help="多首同時演奏的 MIDI 檔案路徑串列 (以 | 或 , 分隔)")
    parser.add_argument("--title", type=str, default="", help="曲目標題")
    parser.add_argument("--auto-close", action="store_true", help="曲目演奏完畢後自動關閉視窗")
    parser.add_argument("--loop", action="store_true", help="開啟單曲循環播放模式")
    parser.add_argument("--random", action="store_true", help="開啟隨機連續播放模式")
    parser.add_argument("--volume", type=int, default=None, help="初始鋼琴音量 (0~200)")
    parser.add_argument("--speed", type=float, default=None, help="初始播放倍速 (0.05~50.0)")
    parser.add_argument("--instrument", type=int, default=0, help="初始 MIDI 音色代號 (0~127)")
    parser.add_argument("--ndi", action="store_true", help="啟動時自動開啟 NDI 影像廣播串流 (推流至主電腦/OBS)")
    parser.add_argument("--green", action="store_true", help="啟動時使用純綠色綠幕背景 (方便 OBS 色度鍵去背)")
    parser.add_argument("--black", action="store_true", help="啟動時使用純黑底背景 (方便 Luma Key 去背)")
    parser.add_argument("--frameless", action="store_true", help="啟動時開啟無邊框純淨舞台模式")
    args, _ = parser.parse_known_args()

    saved_vol, saved_spd = 100, 1.0
    piano_set_path = os.path.join("data", "piano_settings.json") if os.path.exists(os.path.join("data", "piano_settings.json")) else "piano_settings.json"
    if os.path.exists(piano_set_path):
        try:
            with open(piano_set_path, "r", encoding="utf-8") as sf:
                sd = json.load(sf)
                saved_vol = sd.get("volume", 100)
                saved_spd = sd.get("speed", 1.0)
        except Exception:
            pass
            
    final_volume = args.volume if args.volume is not None else saved_vol
    final_speed = args.speed if args.speed is not None else saved_spd

    init_piano_synthesizer(volume=final_volume)
    if SOUND_ENGINE:
        SOUND_ENGINE.set_instrument(args.instrument)
    root = tk.Tk()
    app = VirtualPianoGUI(
        root, 
        auto_midi_path="", 
        auto_title=args.title, 
        auto_close=args.auto_close,
        is_loop=args.loop,
        is_random=args.random,
        initial_volume=final_volume,
        initial_speed=final_speed
    )
    if args.instrument != 0:
        app.set_piano_instrument(args.instrument)

    # 處理外觀模式與 NDI 自動啟動
    if args.green:
        app.set_bg_mode("GREEN")
    elif args.black:
        app.set_bg_mode("BLACK")

    if args.frameless:
        app.toggle_frameless_stage()

    if args.ndi:
        root.after(500, app.toggle_ndi_broadcast)
        
    # 檢查是否有傳入單首或多首 MIDI 檔案
    multi_paths = []
    if args.multi_midi:
        multi_paths = [p.strip() for p in re.split(r'[|,]', args.multi_midi) if p.strip()]
    elif args.midi and ("|" in args.midi or "," in args.midi):
        multi_paths = [p.strip() for p in re.split(r'[|,]', args.midi) if p.strip()]
    elif args.midi and os.path.exists(args.midi):
        multi_paths = [args.midi]
        
    if len(multi_paths) > 1:
        tracks_info = [{"title": os.path.basename(p).replace(".mid", "").replace(".MID", ""), "midi_path": p} for p in multi_paths if os.path.exists(p)]
        if tracks_info:
            root.after(300, lambda: app.start_multi_midi_playback(tracks_info))
    elif len(multi_paths) == 1:
        p = multi_paths[0]
        t = args.title or os.path.basename(p).replace(".mid", "").replace(".MID", "")
        root.after(300, lambda: app.start_midi_playback(t, p))
        
    root.mainloop()
    try:
        if SOUND_ENGINE:
            SOUND_ENGINE.all_notes_off()
    except Exception:
        pass
    os._exit(0)
