import os
import json
import time
import asyncio
import random
import math
import base64
import subprocess
import urllib.parse
import aiohttp
import numpy as np
import pygame
import pygame.sndarray
import pygame.midi
import socket
import re
import sys

from typing import Optional, Dict, List, Tuple, Union
from collections import deque
import collections
import ctypes
import glob
from google import genai
from google.genai import types
import services.vts_client as vc
from services.vts_client import move_vts_spatial, set_vts_expression

import __main__

# Dynamic proxies for main module objects
class MainProxy:
    def __getattr__(self, name):
        if hasattr(__main__, name):
            return getattr(__main__, name)
        if name in ("HIGH_IQ_GEMINI_MODELS", "STREAMER_MIND_MODELS"):
            return ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        if name in ("DEAD_GEMINI_MODELS", "PROACTIVE_EXCLUDED_MODELS"):
            return set()
        if name == "speech_queue":
            class DummyQueue:
                async def put(self, *a, **kw): pass
            return DummyQueue()
        if name == "get_pingpong_ring_indices":
            return lambda n, s=0: list(range(n))
        if name == "get_pingpong_alternating_index":
            return lambda n, s=0: 0
        def _dummy_fn(*args, **kwargs):
            return None
        return _dummy_fn

main_obj = MainProxy()

from core.utils import log_print
from services.vts_client import apply_spatial_position

# If there are circular dependency issues, we can import them locally or pass them.
# The main file provides: DATA_DIR, is_system_overloaded, execute_local_python_code
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
GEMINI_KEYS = []
def get_piano_gemini_keys() -> list:
    global GEMINI_KEYS
    if GEMINI_KEYS:
        return GEMINI_KEYS
    main_keys = getattr(__main__, 'GEMINI_KEYS', None)
    if main_keys:
        GEMINI_KEYS = main_keys
        return GEMINI_KEYS
    raw = os.getenv("GEMINI_KEYS") or os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
    parsed = [k.strip() for k in re.split(r'[\s,;]+', raw) if k.strip()]
    if parsed:
        GEMINI_KEYS = parsed
        return GEMINI_KEYS
    return []
CURRENT_SPEAKING_TARGET = "none"
current_ai_state = "IDLE"
CURRENT_GEMINI_KEY_STEP = 0
LAST_PLAY_REQUEST_TIME: Dict[str, float] = {}

def get_current_speaking_target() -> str:
    """獲取當前說話對象 (優先從主模組獲取，預設為 dad)"""
    return getattr(__main__, 'CURRENT_SPEAKING_TARGET', CURRENT_SPEAKING_TARGET) or "dad"

def is_system_overloaded():
    return False

async def execute_local_python_code(*args, **kwargs):
    pass


# ────────────────────────────────────────────────────────
# 🎹 8.1 88 鍵全音域真實平台鋼琴發聲與樂譜演奏引擎 (Virtual Piano 88K)
# ────────────────────────────────────────────────────────
WHITE_KEYS = []
BLACK_KEYS = []

# 最低 3 音: A0 (21), A#0 (22), B0 (23)
WHITE_KEYS.append(('A0', 21, 'A0', ''))
BLACK_KEYS.append(('A#0', 22, 'A#0', 0, ''))
WHITE_KEYS.append(('B0', 23, 'B0', ''))

WHITE_CHARS_MAP = {
    2: ['1', '2', '3', '4', '5', '6', '7'],
    3: ['8', '9', '0', 'q', 'w', 'e', 'r'],
    4: ['t', 'y', 'u', 'i', 'o', 'p', 'a'],
    5: ['s', 'd', 'f', 'g', 'h', 'j', 'k'],
    6: ['l', 'z', 'x', 'c', 'v', 'b', 'n'],
}
BLACK_CHARS_MAP = {
    2: ['!', '@', '$', '%', '^'],
    3: ['*', '(', 'Q', 'W', 'E'],
    4: ['T', 'Y', 'I', 'O', 'P'],
    5: ['S', 'D', 'G', 'H', 'J'],
    6: ['L', 'Z', 'C', 'V', 'B'],
}

NOTE_NAMES_W = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
SEMITONES_W = [0, 2, 4, 5, 7, 9, 11]

NOTE_NAMES_B = ['C#', 'D#', 'F#', 'G#', 'A#']
SEMITONES_B = [1, 3, 6, 8, 10]
W_INDICES_B = [0, 1, 3, 4, 5]

for oct in range(1, 8):
    base_midi = 12 + oct * 12
    w_start_idx = len(WHITE_KEYS)
    for i, (n, semi) in enumerate(zip(NOTE_NAMES_W, SEMITONES_W)):
        midi = base_midi + semi
        char = ''
        if oct in WHITE_CHARS_MAP:
            char = WHITE_CHARS_MAP[oct][i]
        elif oct == 7 and n == 'C':
            char = 'm'
        WHITE_KEYS.append((f'{n}{oct}', midi, f'{n}{oct}', char))
        
    for j, (n, semi, w_off) in enumerate(zip(NOTE_NAMES_B, SEMITONES_B, W_INDICES_B)):
        midi = base_midi + semi
        char = ''
        if oct in BLACK_CHARS_MAP:
            char = BLACK_CHARS_MAP[oct][j]
        BLACK_KEYS.append((f'{n}{oct}', midi, f'{n}{oct}', w_start_idx + w_off, char))

WHITE_KEYS.append(('C8', 108, 'C8', ''))

VP_MAP = {}
MIDI_TO_VP = {}
MIDI_TO_KEYID = {}

for key_id, midi, name, char in WHITE_KEYS:
    MIDI_TO_KEYID[midi] = key_id
    if char:
        VP_MAP[char] = midi
        MIDI_TO_VP[midi] = char
    else:
        VP_MAP[key_id] = midi
        MIDI_TO_VP[midi] = key_id

for key_id, midi, name, _, char in BLACK_KEYS:
    MIDI_TO_KEYID[midi] = key_id
    if char:
        VP_MAP[char] = midi
        MIDI_TO_VP[midi] = char
    else:
        VP_MAP[key_id] = midi
        MIDI_TO_VP[midi] = key_id

SAMPLE_RATE = 44100
PIANO_SOUNDS = {}
is_piano_active = False
current_piano_task = None
LAST_PIANO_HEARTBEAT_TIME = 0.0
PIANO_STATE_CHANGE_CALLBACKS = []

def register_piano_state_callback(cb):
    """註冊鋼琴狀態變更監聽回調 (例如鋼琴上線/離線時立即通知主系統)"""
    if cb not in PIANO_STATE_CHANGE_CALLBACKS:
        PIANO_STATE_CHANGE_CALLBACKS.append(cb)

def midi_to_freq(midi_num):
    return 440.0 * (2.0 ** ((midi_num - 69) / 12.0))

def generate_piano_tone(midi_num, duration=3.0):
    """史坦威古典音樂廳平台鋼琴 (Steinway Concert Grand) 物理聲學建模"""
    f0 = midi_to_freq(midi_num)
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    
    B = 0.00015 * ((f0 / 261.63) ** 0.55)
    num_harmonics = min(28, int((SAMPLE_RATE / 2) / f0))
    detune = 0.28 if midi_num >= 40 else 0.12
    signal = np.zeros_like(t)
    
    for n in range(1, num_harmonics + 1):
        fn = n * f0 * math.sqrt(1.0 + B * (n ** 2))
        if fn >= SAMPLE_RATE / 2: break
        amp = (1.0 / (n ** 1.12)) * math.exp(-0.065 * n)
        decay_prompt = (1.6 + f0 / 280.0) * (n ** 0.55)
        decay_sustain = (0.5 + f0 / 900.0) * (n ** 0.32)
        env = 0.55 * np.exp(-decay_prompt * t) + 0.45 * np.exp(-decay_sustain * t)
        
        s1 = np.sin(2 * np.pi * fn * t)
        s2 = np.sin(2 * np.pi * (fn + detune) * t + 0.3)
        s3 = np.sin(2 * np.pi * (fn - detune) * t + 0.6)
        signal += amp * env * (0.42 * s1 + 0.29 * s2 + 0.29 * s3)
        
    hammer_samples = int(SAMPLE_RATE * 0.006)
    if hammer_samples > 0:
        noise = (np.random.rand(hammer_samples) * 2 - 1) * np.exp(-np.linspace(0, 5.5, hammer_samples))
        signal[:hammer_samples] += noise * 0.16 * (1.0 / (1.0 + f0 / 600.0))
        
    body_res = 0.08 * np.sin(2 * np.pi * 110.0 * t) * np.exp(-4.5 * t)
    signal += body_res
    
    attack_samples = int(SAMPLE_RATE * 0.002)
    if attack_samples > 0: signal[:attack_samples] *= np.linspace(0, 1, attack_samples)
    release_samples = int(SAMPLE_RATE * 0.04)
    if len(signal) > release_samples: signal[-release_samples:] *= np.linspace(1, 0, release_samples)
    
    max_val = np.max(np.abs(signal))
    if max_val > 0: signal = signal / max_val * 0.88
    audio_int16 = (signal * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(np.column_stack((audio_int16, audio_int16)))

import pygame.midi

# ────────────────────────────────────────────────────────
# 🎻 General MIDI 完整音色庫（128 programs＋10 鼓組；program 號為 GM 標準，協議上限）
# 家族：0-7 鍵盤／8-15 敲擊弦／16-23 風琴／24-31 吉他／32-39 貝斯／40-47 弦樂／
#       48-55 合奏合唱／56-63 銅管／64-71 簧管／72-79 笛／80-87 主音合成／
#       88-95 音墊／96-103 合成特效／104-111 民族／112-119 打擊／120-127 特效
MIDI_INSTRUMENTS = {
    # ── 鍵盤 ──
    "🎹 古典平台鋼琴 (Grand Piano)": 0,
    "✨ 晶亮平台鋼琴 (Bright Piano)": 1,
    "🎹 電子大鋼琴 (Electric Grand)": 2,
    "🍺 酒吧鋼琴 (Honky-tonk)": 3,
    "⚡ 經典電鋼琴 (Rhodes EP)": 4,
    "🌌 FM 數位電鋼琴 (DX7 EP)": 5,
    "🎼 古典大鍵琴 (Harpsichord)": 6,
    "🕰️ 古鋼琴 (Clavinet)": 7,
    # ── 敲擊弦／鈴 ──
    "🔔 夢幻鋼片琴 (Celesta)": 8,
    "🔔 鐘琴 (Glockenspiel)": 9,
    "🎠 音樂盒 (Music Box)": 10,
    "🎻 顫音琴 (Vibraphone)": 11,
    "🎵 溫暖木琴 (Marimba)": 12,
    "🎵 木琴 (Xylophone)": 13,
    "🔔 管鐘 (Tubular Bells)": 14,
    "🥁 大力揚琴 (Dulcimer)": 15,
    # ── 風琴 ──
    "🎹 爵士風琴 (Drawbar Organ)": 16,
    "🎹 敲擊風琴 (Percussive Organ)": 17,
    "🎹 搖滾風琴 (Rock Organ)": 18,
    "⛪ 教堂管風琴 (Church Organ)": 19,
    "🎹 簧片風琴 (Reed Organ)": 20,
    "🪗 浪漫手風琴 (Accordion)": 21,
    "🪗 口琴 (Harmonica)": 22,
    "🪗 探戈手風琴 (Bandoneon)": 23,
    # ── 吉他 ──
    "🎸 古典尼龍吉他 (Nylon Guitar)": 24,
    "🎸 民謠鋼弦吉他 (Steel Guitar)": 25,
    "🎸 爵士電吉他 (Jazz Guitar)": 26,
    "🎸 清音電吉他 (Clean Guitar)": 27,
    "🎸 悶音電吉他 (Muted Guitar)": 28,
    "⚡ 破音電吉他 (Overdrive)": 29,
    "⚡ 重金屬吉他 (Distortion)": 30,
    "🎸 吉他泛音 (Harmonics)": 31,
    # ── 貝斯 ──
    "🎸 原聲貝斯 (Acoustic Bass)": 32,
    "🎸 指彈電貝斯 (Electric Bass)": 33,
    "🎸 撥片貝斯 (Picked Bass)": 34,
    "🎸 無品貝斯 (Fretless Bass)": 35,
    "🎸 貝斯 Slap 一式 (Slap Bass)": 36,
    "🎸 貝斯 Slap 二式 (Slap Bass 2)": 37,
    "🎸 合成貝斯 (Synth Bass)": 38,
    "🎸 酸性貝斯 (Acid Bass)": 39,
    # ── 弦樂獨奏 ──
    "🎻 獨奏小提琴 (Violin)": 40,
    "🎻 中提琴 (Viola)": 41,
    "🎻 抒情大提琴 (Cello)": 42,
    "🎻 低音提琴 (Contrabass)": 43,
    "🎻 顫音弦樂 (Tremolo Strings)": 44,
    "🎻 撥弦 (Pizzicato)": 45,
    "🪕 天使豎琴 (Harp)": 46,
    "🥁 定音鼓 (Timpani)": 47,
    # ── 合奏合唱 ──
    "🎻 華麗交響弦樂 (String Ensemble)": 48,
    "🎻 慢弦樂 (Slow Strings)": 49,
    "🎻 合成弦樂 (Synth Strings)": 50,
    "🎻 合成弦樂二式 (Synth Strings 2)": 51,
    "👼 空靈人聲合唱 (Choir Aahs)": 52,
    "🗣️ 人聲嘟聲 (Voice Oohs)": 53,
    "🎺 合成銅管 (Synth Voice)": 54,
    "🎺 管弦齊奏 (Orchestra Hit)": 55,
    # ── 銅管 ──
    "🎺 爵士小號 (Trumpet)": 56,
    "🎺 長號 (Trombone)": 57,
    "🎺 大號 (Tuba)": 58,
    "🎺 弱音小號 (Muted Trumpet)": 59,
    "📯 法國號 (French Horn)": 60,
    "🎺 銅管合奏 (Brass Section)": 61,
    "🎺 合成銅管2 (Synth Brass)": 62,
    "🎺 合成銅管3 (Synth Brass 2)": 63,
    # ── 簧管 ──
    "🎷 高音薩克斯 (Soprano Sax)": 64,
    "🎷 浪漫薩克斯風 (Alto Sax)": 65,
    "🎷 次中音薩克斯 (Tenor Sax)": 66,
    "🎷 上低音薩克斯 (Baritone Sax)": 67,
    "🎷 雙簧管 (Oboe)": 68,
    "🎷 英國管 (English Horn)": 69,
    "🎷 巴松管 (Bassoon)": 70,
    "🎷 單簧管 (Clarinet)": 71,
    # ── 笛 ──
    "🪈 短笛 (Piccolo)": 72,
    "🪈 清新長笛 (Flute)": 73,
    "🪈 豎笛 (Recorder)": 74,
    "🪈 排簫 (Pan Flute)": 75,
    "🪈 吹瓶子 (Bottle)": 76,
    "🪈 尺八 (Shakuhachi)": 77,
    "🪈 口哨 (Whistle)": 78,
    "🪈 陶笛 (Ocarina)": 79,
    # ── 主音合成 ──
    "🎹 方波主音 (Square Lead)": 80,
    "🎹 復古合成器 (Saw Lead)": 81,
    "🎹 遊戲主音 (Calliope Lead)": 82,
    "🎹 吹管主音 (Chiff Lead)": 83,
    "🎹 金屬掃弦主音 (Charang Lead)": 84,
    "🎹 人聲主音 (Voice Lead)": 85,
    "🎹 五度主音 (Fifths Lead)": 86,
    "🎹 貝斯主音 (Bass Lead)": 87,
    # ── 音墊 ──
    "🌸 新世紀音墊 (New Age Pad)": 88,
    "🌸 夢幻合成音墊 (Warm Pad)": 89,
    "🌸 復 Poly 音墊 (Poly Pad)": 90,
    "🌸 空靈音墊 (Ghost Pad)": 91,
    "🌸 弓弦音墊 (Bowed Pad)": 92,
    "🌸 金屬音墊 (Metallic Pad)": 93,
    "🌸 光環音墊 (Halo Pad)": 94,
    "🌸 掃掠音墊 (Sweep Pad)": 95,
    # ── 合成特效 ──
    "🌧️ 雨聲 (Rain FX)": 96,
    "🎬 電影音景 (Soundtrack)": 97,
    "🔮 水晶 (Crystal)": 98,
    "🌊 海浪 (Atmosphere)": 99,
    "🌟 明亮 (Brightness)": 100,
    "👺 妖怪 (Goblins)": 101,
    "👽 回聲 (Echoes)": 102,
    "🚀 科幻 (Sci-Fi)": 103,
    # ── 民族 ──
    "🪕 西塔琴 (Sitar)": 104,
    "🪕 班鳩琴 (Banjo)": 105,
    "🪕 三味線 (Shamisen)": 106,
    "🪕 日本古箏 (Koto)": 107,
    "🪵 非洲拇指琴 (Kalimba)": 108,
    "👜 蘇格蘭風笛 (Bagpipe)": 109,
    "🎻 提琴 (Fiddle)": 110,
    "🎻 沙那笛 (Shanai)": 111,
    # ── 打擊 ──
    "🔔 丁丁鈴 (Tinkle Bell)": 112,
    "🔔 鈴 (Agogo)": 113,
    "🥁 鋼鼓 (Steel Drums)": 114,
    "🪵 木魚 (Woodblock)": 115,
    "🥁 太鼓 (Taiko)": 116,
    "🎵 旋律鼓 (Melodic Tom)": 117,
    "🥁 合成鼓 (Synth Drum)": 118,
    "🔔 反轉鈸 (Reverse Cymbal)": 119,
    # ── 特效 ──
    "🎸 吉他品絲噪音 (Fret Noise)": 120,
    "🌬️ 呼吸噪音 (Breath Noise)": 121,
    "🌊 海浪聲 (Seashore)": 122,
    "🐦 鳥鳴 (Bird Tweet)": 123,
    "📞 電話鈴 (Telephone)": 124,
    "🚁 直升機 (Helicopter)": 125,
    "👏 掌聲 (Applause)": 126,
    "🔫 槍聲 (Gunshot)": 127,
}

class ClassicalPianoSoundEngine:
    """🌟 88 鍵高復音數無削波 MIDI 聲音引擎 (支援 Rush E / 黑樂譜高密度連彈，0 消音 0 掐音)"""
    def __init__(self, volume: int = 100, instrument: int = 0):
        self.midi_out = None
        self.volume = max(0, min(200, int(volume)))
        self.current_instrument = max(0, min(127, int(instrument)))
        # 使用 15 個獨立 MIDI 通道 (0~8, 10~15，避開 Channel 9 打擊樂) 進行多軌語音輪替 (Voice Pooling)
        self.usable_channels = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15]
        self.channel_idx = 0
        # 🎺 MIDI 樂隊：每通道獨立音色 {channel: program}；Channel 9 為打擊樂專用
        self.channel_programs = {}
        self.drum_channel = 9
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
                log_print(f"🎹 [Virtual Piano] 88 鍵 15 軌高復音 MIDI 聲音引擎載入完成 (音色: #{self.current_instrument})！")
            else:
                log_print("⚠️ [Classical Sound Engine] 未找到預設 MIDI 輸出裝置")
        except Exception as e:
            log_print(f"⚠️ [Classical Sound Engine 初始化異常]: {e}")

    def configure_channels(self):
        """為所有可用 MIDI 通道初始化共鳴與適度衰減參數 (防止黑樂譜長音堆疊塞爆驅動)"""
        if not self.midi_out: return
        try:
            cc7_val = int(min(100, self.volume) * 1.27)
            for ch in self.usable_channels:
                prog = self.channel_programs.get(ch, self.current_instrument)
                self.midi_out.set_instrument(prog, channel=ch)
                self.midi_out.write_short(0xB0 + ch, 91, 80) # CC 91: Reverb 80 (飽滿自然空間共鳴)
                self.midi_out.write_short(0xB0 + ch, 93, 25) # CC 93: Chorus 琴弦共鳴
                self.midi_out.write_short(0xB0 + ch, 72, 85) # CC 72: Release Time 85 (自然飽滿共鳴餘韻，徹底杜絕掐音消音)
                self.midi_out.write_short(0xB0 + ch, 71, 64) # CC 71: Resonance
                self.midi_out.write_short(0xB0 + ch, 7, cc7_val)
        except Exception:
            pass

    def set_instrument(self, program_num: int):
        """切換 MIDI 發聲音色 (Program Change 0 ~ 127；樂隊模式請用 set_channel_program 逐軌配器)"""
        self.current_instrument = max(0, min(127, int(program_num)))
        self.channel_programs = {}
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

    def set_channel_program(self, channel: int, program_num: int):
        """🎺 樂隊配器：指定某通道的音色（program_change 直達，不影響其他軌）"""
        channel = max(0, min(15, int(channel)))
        program_num = max(0, min(127, int(program_num)))
        self.channel_programs[channel] = program_num
        if self.midi_out:
            try:
                if channel == self.drum_channel:
                    return                      # 打擊樂通道無視 program
                self.midi_out.set_instrument(program_num, channel=channel)
            except Exception:
                pass

    def note_on(self, midi_num: int, velocity: int = 105, channel: int = None, program: int = None):
        """channel/program 指定時走樂隊軌（保留原通道直發）；否則走鋼琴輪替池。鼓軌 (ch9) 不受 88 鍵範圍限制。"""
        if channel is not None:
            return self._band_note_on(int(channel), midi_num, velocity, program)
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

    def _band_note_on(self, channel: int, midi_num: int, velocity: int = 105, program: int = None):
        """樂隊軌直發：保留原通道（多音色同時演奏＋鼓組）。"""
        if not self.midi_out or self.volume <= 0:
            return None
        try:
            channel = max(0, min(15, int(channel)))
            # 樂隊軌音域全開 0-127（短笛上探、倍低音下潛；鼓軌亦放寬，交由音源決定）
            if not (0 <= midi_num <= 127):
                return None
            if program is not None and channel != self.drum_channel:
                program = max(0, min(127, int(program)))
                if self.channel_programs.get(channel) != program:
                    self.channel_programs[channel] = program
                    try:
                        self.midi_out.set_instrument(program, channel=channel)
                    except Exception:
                        pass
            scaled_v = int(velocity * (self.volume / 100.0))
            v = max(1, min(127, scaled_v))
            while len(self.active_voices_fifo) >= self.MAX_POLYPHONY:
                old_note, old_ch = self.active_voices_fifo.popleft()
                try:
                    self.midi_out.note_off(old_note, 0, old_ch)
                    if old_ch in self.active_note_channels[old_note]:
                        self.active_note_channels[old_note].remove(old_ch)
                except Exception:
                    pass
            self.midi_out.note_on(midi_num, v, channel)
            self.active_note_channels[midi_num].append(channel)
            self.active_voices_fifo.append((midi_num, channel))
            return channel
        except Exception:
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
PIANO_SETTINGS_FILE = os.path.join(DATA_DIR, "piano_settings.json")

def load_persisted_piano_settings():
    vol, spd = 100, 1.0
    if os.path.exists(PIANO_SETTINGS_FILE):
        try:
            with open(PIANO_SETTINGS_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                vol = d.get("volume", 100)
                spd = d.get("speed", 1.0)
        except Exception:
            pass
    return vol, spd

def save_persisted_piano_settings(vol, spd):
    try:
        with open(PIANO_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"volume": int(vol), "speed": float(spd)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

GLOBAL_PIANO_VOLUME, GLOBAL_PIANO_SPEED = load_persisted_piano_settings()
PIANO_NOTE_FOCUS_X = 0.0

GLOBAL_PIANO_REALTIME_STATE = {
    "is_window_open": False,
    "is_playing": False,
    "title": "",
    "tracks": [],
    "current_time": 0.0,
    "total_duration": 0.0,
    "progress_percent": 0.0,
    "current_time_str": "00:00",
    "total_duration_str": "00:00",
    "speed": 1.0,
    "volume": 100,
    "instrument": "🎹 古典平台鋼琴 (Grand Piano)",
    "is_loop": False,
    "is_random": False,
    "last_update_time": 0.0
}

def get_piano_realtime_prompt() -> str:
    """生成 100% 精準真實的鋼琴即時情報提示詞，讓 7L 隨時掌握鋼琴的真實演奏狀態"""
    global GLOBAL_PIANO_REALTIME_STATE, is_piano_active, current_piano_song_title, GLOBAL_PIANO_VOLUME, GLOBAL_PIANO_SPEED, IS_PIANO_AUTO_RADIO_MODE
    
    win_alive = is_piano_window_alive()
    now_t = time.time()
    last_t = GLOBAL_PIANO_REALTIME_STATE.get("last_update_time", 0)
    is_playing = GLOBAL_PIANO_REALTIME_STATE.get("is_playing", False) and (win_alive or (now_t - last_t < 4.0))
    
    if not win_alive and (now_t - last_t > 4.0):
        is_playing = False
        is_piano_active = False
        current_piano_song_title = ""

    if is_playing:
        title = GLOBAL_PIANO_REALTIME_STATE.get("title") or current_piano_song_title or "名曲"
        tracks = GLOBAL_PIANO_REALTIME_STATE.get("tracks", [])
        cur_str = GLOBAL_PIANO_REALTIME_STATE.get("current_time_str", "00:00")
        tot_str = GLOBAL_PIANO_REALTIME_STATE.get("total_duration_str", "00:00")
        prog_pct = GLOBAL_PIANO_REALTIME_STATE.get("progress_percent", 0.0)
        speed = GLOBAL_PIANO_REALTIME_STATE.get("speed", GLOBAL_PIANO_SPEED)
        vol = GLOBAL_PIANO_REALTIME_STATE.get("volume", GLOBAL_PIANO_VOLUME)
        inst = GLOBAL_PIANO_REALTIME_STATE.get("instrument", "🎹 古典平台鋼琴 (Grand Piano)")
        
        info_lines = [
            f"【🎹 鋼琴即時即況情報 (真實硬體遙測)】：",
            f"- 演奏狀態：🎵 正在演奏中！妳正坐在 88 鍵鋼琴前為大家彈奏。",
            f"- 當前演奏曲目：《{title}》" + (f"（多曲合奏中：{'、'.join(tracks)}）" if len(tracks) > 1 else ""),
            f"- 演奏進度：⏱️ {cur_str} / {tot_str} ({prog_pct}%)",
            f"- 演奏參數：音量 {vol}% | 倍速 {speed}x | 音色：{inst}",
        ]

        if IS_PIANO_AUTO_RADIO_MODE:
            info_lines.append(f"- 電台模式：📻 已開啟無限隨機接曲模式")
        info_lines.append(f"- 互動指引：若對象點新歌、要求換歌或點播曲目，【嚴禁調用 play_virtual_piano 切歌或插歌】！請用自然口語告知對方：『我現在正在彈《{title}》呢～等我這首彈完再點歌喔！』。若對象稱讚或詢問正在彈什麼，依真實曲名自然回應！")
        return "\n".join(info_lines)
    elif win_alive or is_piano_active:
        vol = GLOBAL_PIANO_REALTIME_STATE.get("volume", GLOBAL_PIANO_VOLUME)
        inst = GLOBAL_PIANO_REALTIME_STATE.get("instrument", "🎹 古典平台鋼琴 (Grand Piano)")
        info_lines = [
            f"【🎹 鋼琴即時即況情報 (真實硬體遙測)】：",
            f"- 演奏狀態：⏸️ 鋼琴視窗已在桌面上開啟就緒待命，【目前沒有在播放任何曲目】（背景無鋼琴聲）。",
            f"- 鋼琴參數：音量 {vol}% | 當前音色：{inst}",
            f"- 互動指引：若老爸/觀眾要求彈琴或點歌，請【直接調用工具 `play_virtual_piano`】；若要求自創曲、即興創作一首或自己寫歌來彈，請調用 `compose_and_play_original_piano`！不要宣稱背景正在彈奏。",
        ]
        return "\n".join(info_lines)
    else:
        return "【🎹 鋼琴即時即況情報】：\n- 演奏狀態：⏹️ 鋼琴已關閉/未演奏，背景【完全沒有任何鋼琴聲音】。歷史記錄若有提到彈琴那是之前的事，絕對不要自己幻想或宣稱現在背景在彈鋼琴！"

def send_piano_ipc_command(cmd_dict: dict) -> bool:
    """透過 UDP (Port 39282) 向已開啟的 88 鍵鋼琴視窗發送控制指令 (換歌/調音量/調倍速/停止/關閉)"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.3)
        msg = json.dumps(cmd_dict).encode('utf-8')
        sock.sendto(msg, ("127.0.0.1", 39282))
        return True
    except Exception:
        return False

PIANO_PERSIST_FILE = os.path.join(DATA_DIR, "piano_persisted_state.json")

def save_persisted_piano_state(is_playing: bool, song_title: str, is_open: bool = True):
    """持久化鋼琴當前演奏狀態，供重開機或當機自動還原"""
    try:
        data = {
            "is_playing": is_playing,
            "song_title": song_title,
            "is_open": is_open,
            "timestamp": time.time()
        }
        with open(PIANO_PERSIST_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

def bring_piano_window_to_front():
    """將 7L 的 88 鍵平台鋼琴視窗還原並置頂到最前端（防止被 Roblox 或其他遊戲遮擋或最小化）"""
    send_piano_ipc_command({"cmd": "bring_to_front"})
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            t = (w.title or "").lower()
            if "7l 88" in t or "古典平台鋼琴" in t or "virtual piano" in t:
                if w.isMinimized:
                    w.restore()
                w.activate()
                return
    except Exception:
        pass
    try:
        user32 = ctypes.windll.user32
        browser_exes = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
        target_hwnd = None
        if hasattr(main_obj, 'os_desktop_sensor') and main_obj.os_desktop_sensor:
            for app in main_obj.os_desktop_sensor.get_visible_windows(max_count=25):
                p_name = app.get("process_name", "").lower()
                if p_name in browser_exes:
                    continue
                w_title = app.get("window_title", "")
                if "7l 88" in w_title.lower() or "古典平台鋼琴" in w_title or ("python" in p_name and "鋼琴" in w_title):
                    target_hwnd = app.get("hwnd")
                    break
        if target_hwnd:
            if user32.IsIconic(target_hwnd):
                user32.ShowWindow(target_hwnd, 9)  # SW_RESTORE
            else:
                user32.ShowWindow(target_hwnd, 5)  # SW_SHOW
            user32.SetForegroundWindow(target_hwnd)
            user32.SetWindowPos(target_hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_TOPMOST
            user32.SetWindowPos(target_hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_NOTOPMOST
    except Exception:
        pass

def get_piano_script_path() -> str:
    """動態解析 88 鍵平台鋼琴啟動腳本真實路徑"""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(root_dir, "test_virtual_piano.py"),
        os.path.join(root_dir, "tests_and_benchmarks", "test_virtual_piano.py"),
        os.path.join(os.getcwd(), "test_virtual_piano.py"),
        os.path.join(os.getcwd(), "tests_and_benchmarks", "test_virtual_piano.py")
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return "test_virtual_piano.py"

def is_piano_window_alive() -> bool:
    """檢查 7L 專屬的 88 鍵平台鋼琴視窗是否正在運行且存活 (排除瀏覽器包含 piano/鋼琴 的分頁)"""
    global current_piano_process
    # 1. 優先檢查系統真實 GUI 視窗清單 (最精確，且過濾掉沒有視窗的背景殭屍行程)
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            t = (w.title or "").lower()
            if "7l 88" in t or "古典平台鋼琴" in t:
                return True
    except Exception:
        pass
    try:
        browser_exes = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
        if hasattr(main_obj, 'os_desktop_sensor') and main_obj.os_desktop_sensor:
            for app in main_obj.os_desktop_sensor.get_visible_windows(max_count=25):
                p_name = app.get("process_name", "").lower()
                if p_name in browser_exes:
                    continue
                w_title = app.get("window_title", "")
                if "7l 88" in w_title.lower() or "古典平台鋼琴" in w_title or "virtual_piano" in p_name or ("python" in p_name and "鋼琴" in w_title):
                    return True
    except Exception:
        pass

    # 2. 若視窗列表中尚未抓到（例如視窗剛啟動還在載入中），檢查是否有真實存活的進程
    if current_piano_process is not None:
        if current_piano_process.poll() is None:
            return True
        else:
            current_piano_process = None

    return False

def is_piano_active_and_alive() -> bool:
    """即時判定鋼琴是否真的在線活躍（必須同時滿足標記為 active 且近期有心跳或視窗/進程確實存活）"""
    global is_piano_active, LAST_PIANO_HEARTBEAT_TIME, current_piano_process
    if not is_piano_active:
        return False
    # 若有直接關聯的進程，檢查進程是否已終止
    if current_piano_process is not None and current_piano_process.poll() is not None:
        _mark_piano_offline("進程已終止 (poll)")
        return False
    # 心跳逾時檢查 (超過 2.5 秒沒有心跳)
    now = time.time()
    if LAST_PIANO_HEARTBEAT_TIME > 0 and (now - LAST_PIANO_HEARTBEAT_TIME > 2.5):
        if not is_piano_window_alive():
            _mark_piano_offline("心跳超時且無視窗存活")
            return False
    return is_piano_active

def _mark_piano_offline(reason: str = ""):
    global is_piano_active, current_piano_song_title, GLOBAL_PIANO_REALTIME_STATE, current_piano_process, PIANO_NOTE_FOCUS_X
    was_active = is_piano_active or GLOBAL_PIANO_REALTIME_STATE.get("is_playing", False) or GLOBAL_PIANO_REALTIME_STATE.get("is_window_open", False)
    is_piano_active = False
    current_piano_song_title = ""
    PIANO_NOTE_FOCUS_X = 0.0
    current_piano_process = None
    GLOBAL_PIANO_REALTIME_STATE["is_playing"] = False
    GLOBAL_PIANO_REALTIME_STATE["is_window_open"] = False
    GLOBAL_PIANO_REALTIME_STATE["title"] = ""
    save_persisted_piano_state(False, "", False)
    if was_active:
        log_print(f"🎹 [鋼琴即時心跳監控] 偵測到鋼琴已關閉/強制關機 ({reason})，已即時解除鋼琴狀態！")
        for cb in list(PIANO_STATE_CHANGE_CALLBACKS):
            try:
                cb(False)
            except Exception:
                pass

async def piano_liveness_watchdog_worker():
    """鋼琴心跳與存活狀態常駐看門狗 (每 1 秒巡檢一次，保證與主系統 100% 即時同步)"""
    global is_piano_active, LAST_PIANO_HEARTBEAT_TIME, current_piano_process, GLOBAL_PIANO_REALTIME_STATE, LAST_PIANO_OPEN_TIME
    while True:
        await asyncio.sleep(1.0)
        try:
            now = time.time()
            # 1. 檢查子進程存活
            if current_piano_process is not None and current_piano_process.poll() is not None:
                _mark_piano_offline("鋼琴進程已終止 (poll)")
                continue

            # 2. 若鋼琴當前為活躍狀態或視窗為開啟狀態
            if is_piano_active or GLOBAL_PIANO_REALTIME_STATE.get("is_window_open", False):
                # 啟動與就位寬限期：發起演奏 10 秒內，7L 正在就位、念開場白或視窗初始化中，絕不提前誤殺！
                if now - LAST_PIANO_OPEN_TIME < 10.0:
                    continue

                # 心跳逾時檢查：超過 2.5 秒未收到心跳包
                if LAST_PIANO_HEARTBEAT_TIME > 0 and (now - LAST_PIANO_HEARTBEAT_TIME > 2.5):
                    if not is_piano_window_alive():
                        _mark_piano_offline("心跳逾時且視窗已不存在")
                    else:
                        # 視窗還在但心跳逾時，發送主動 Ping 探針
                        send_piano_ipc_command({"cmd": "ping", "time": now})
                elif LAST_PIANO_HEARTBEAT_TIME == 0:
                    # 尚未收到過心跳，檢查視窗是否存活 (已過 10 秒寬限期)
                    if not is_piano_window_alive():
                        _mark_piano_offline("啟動逾時且無視窗存活")
                    else:
                        send_piano_ipc_command({"cmd": "ping", "time": now})
                else:
                    # 鋼琴正常在線，定期每 2 秒發送一次 Ping 維持雙向溝通
                    if int(now) % 2 == 0:
                        send_piano_ipc_command({"cmd": "ping", "time": now})
        except Exception:
            pass

async def auto_restore_piano_state_on_startup():
    """7L 重啟後自動檢查背景鋼琴視窗狀態（開機不自動彈奏，若視窗存活則僅同步狀態）"""
    global is_piano_active, current_piano_song_title
    await asyncio.sleep(2.5)  # 等待主系統初始化完成
    try:
        # 檢查是否已經有在背景運行的鋼琴視窗
        if is_piano_window_alive():
            song_title = ""
            if os.path.exists(PIANO_PERSIST_FILE):
                try:
                    with open(PIANO_PERSIST_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    song_title = data.get("song_title", "")
                except Exception:
                    pass
            is_piano_active = True
            current_piano_song_title = song_title
            log_print(f"🎹 [鋼琴狀態同步] 偵測到背景鋼琴視窗存活，同步狀態" + (f": 《{song_title}》" if song_title else ""))
        else:
            # 開機保持乾淨待命，絕不自動彈奏，重置持久化記錄
            is_piano_active = False
            current_piano_song_title = ""
            save_persisted_piano_state(False, "", False)
    except Exception as e:
        log_print(f"⚠️ [鋼琴還原異常]: {e}")

GLOBAL_PIANO_INSTRUMENT_ID = 0
GLOBAL_PIANO_INSTRUMENT_NAME = "🎹 古典平台鋼琴 (Grand Piano)"

async def set_piano_volume(volume: int) -> str:
    """調整 88 鍵鋼琴的演奏音量 (0 ~ 200)。"""
    global GLOBAL_PIANO_VOLUME, SOUND_ENGINE
    vol = max(0, min(200, int(volume)))
    GLOBAL_PIANO_VOLUME = vol
    save_persisted_piano_settings(GLOBAL_PIANO_VOLUME, GLOBAL_PIANO_SPEED)
    if SOUND_ENGINE:
        SOUND_ENGINE.set_volume(vol)
    if is_piano_window_alive():
        send_piano_ipc_command({"cmd": "set_volume", "volume": vol})
    log_print(f"🔊 [鋼琴音量] 88 鍵鋼琴音量已鎖定並儲存為 {vol}%")
    return ""

async def set_piano_speed(speed: float) -> str:
    """調整 88 鍵鋼琴的演奏倍速 (0.05 ~ 50.0)。"""
    global GLOBAL_PIANO_SPEED
    spd = max(0.05, min(50.0, round(float(speed), 2)))
    GLOBAL_PIANO_SPEED = spd
    if is_piano_window_alive():
        send_piano_ipc_command({"cmd": "set_speed", "speed": spd})
    log_print(f"⚡ [鋼琴倍速] 88 鍵鋼琴倍速已設定為 {spd}x")
    return "[EXPRESSION: 星星眼]"

async def set_piano_instrument(instrument: str) -> str:
    """切換 88 鍵鋼琴/鍵盤的演奏音色 (如：鋼琴、弦樂、吉他、電鋼琴、小提琴、大提琴、薩克斯風、木琴、風琴、豎琴、人聲合唱等)。"""
    global GLOBAL_PIANO_INSTRUMENT_ID, GLOBAL_PIANO_INSTRUMENT_NAME, SOUND_ENGINE
    clean_i = str(instrument).strip()
    
    target_id = 0
    target_name = "🎹 古典平台鋼琴 (Grand Piano)"
    found = False
    
    # 關鍵字智能匹配
    for name, p_id in MIDI_INSTRUMENTS.items():
        if clean_i.lower() in name.lower() or name.lower() in clean_i.lower() or any(w in name.lower() for w in clean_i.lower().split()):
            target_id = p_id
            target_name = name
            found = True
            break
            
    if not found:
        try:
            p_num = int(clean_i)
            target_id = max(0, min(127, p_num))
            for name, p_id in MIDI_INSTRUMENTS.items():
                if p_id == target_id:
                    target_name = name
                    break
            if not target_name:
                target_name = f"MIDI 音色 #{target_id}"
        except Exception:
            pass
            
    GLOBAL_PIANO_INSTRUMENT_ID = target_id
    GLOBAL_PIANO_INSTRUMENT_NAME = target_name
    
    if SOUND_ENGINE:
        SOUND_ENGINE.set_instrument(target_id)
    if is_piano_window_alive():
        send_piano_ipc_command({"cmd": "set_instrument", "instrument": target_name})
        
    log_print(f"🎻 [鋼琴音色] 音色已切換為: {target_name} (ID: {target_id})")
    return "[EXPRESSION: 星星眼]"

async def piano_focus_udp_worker():
    """接收來自虛擬鋼琴視窗的即時 UDP 廣播：
    1. 琴鍵擊鍵重心 (驅動 7L 視線與頭部精準追蹤琴鍵彈奏位置)
    2. 鋼琴即時全量狀態 (正在彈奏的曲目、進度、倍速、音量、音色、播放/結束狀態、心跳包)
    """
    global PIANO_NOTE_FOCUS_X, GLOBAL_PIANO_REALTIME_STATE, is_piano_active, current_piano_song_title, GLOBAL_PIANO_VOLUME, GLOBAL_PIANO_SPEED, GLOBAL_PIANO_INSTRUMENT_NAME, LAST_PIANO_HEARTBEAT_TIME
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    sock.setblocking(False)
    try:
        sock.bind(("127.0.0.1", 39281))
    except Exception:
        return
        
    while True:
        try:
            data, _ = await loop.sock_recvfrom(sock, 4096)
            if data:
                LAST_PIANO_HEARTBEAT_TIME = time.time()
                raw_str = data.decode('utf-8', errors='ignore').strip()
                if raw_str.startswith('{') and raw_str.endswith('}'):
                    try:
                        pkg = json.loads(raw_str)
                        ev = pkg.get("event", "")
                        if ev in ["closed", "piano_shutdown"] or not pkg.get("is_alive", True):
                            _mark_piano_offline(f"收到關閉事件: {ev}")
                            continue

                        if pkg.get("type") in ["PIANO_STATUS", "PIANO_HEARTBEAT"]:
                            GLOBAL_PIANO_REALTIME_STATE.update(pkg)
                            GLOBAL_PIANO_REALTIME_STATE["is_window_open"] = pkg.get("is_window_open", True)
                            GLOBAL_PIANO_REALTIME_STATE["last_update_time"] = time.time()
                            if hasattr(main_obj, 'realtime_task_mgr'):
                                main_obj.realtime_task_mgr.update_piano_state(pkg)
                            
                            is_playing = pkg.get("is_playing", False)
                            song_title = pkg.get("title", "")
                            
                            if is_playing and song_title:
                                was_inactive = not is_piano_active
                                is_piano_active = True
                                current_piano_song_title = song_title
                                save_persisted_piano_state(True, song_title, True)
                                if was_inactive:
                                    for cb in list(PIANO_STATE_CHANGE_CALLBACKS):
                                        try:
                                            cb(True)
                                        except Exception:
                                            pass
                            elif not is_playing:
                                current_piano_song_title = ""
                                if not pkg.get("is_window_open", True) or not is_piano_window_alive():
                                    _mark_piano_offline("曲目停止且視窗已關閉")
                                    
                            if "volume" in pkg:
                                GLOBAL_PIANO_VOLUME = pkg["volume"]
                            if "speed" in pkg:
                                GLOBAL_PIANO_SPEED = pkg["speed"]
                            if "instrument" in pkg and pkg["instrument"]:
                                GLOBAL_PIANO_INSTRUMENT_NAME = pkg["instrument"]
                    except Exception:
                        pass
                else:
                    try:
                        val = float(raw_str)
                        PIANO_NOTE_FOCUS_X = val
                    except Exception:
                        pass
        except Exception:
            await asyncio.sleep(0.05)

def update_piano_focus_notes(midi_list):
    global PIANO_NOTE_FOCUS_X
    if not midi_list: return
    try:
        avg_midi = sum(midi_list) / len(midi_list)
        offset = max(-1.0, min(1.0, (avg_midi - 60.0) / 28.0))
        # 鏡像校正：7L 面對鏡頭彈琴時，右手高音區在觀眾視角的螢幕左側 (-)，左手低音區在螢幕右側 (+)
        PIANO_NOTE_FOCUS_X = -offset * 22.0
    except Exception:
        pass

def init_piano_synthesizer(volume: int = 100):
    global SOUND_ENGINE
    if SOUND_ENGINE is None:
        SOUND_ENGINE = ClassicalPianoSoundEngine(volume=volume)
    else:
        SOUND_ENGINE.set_volume(volume)

def play_piano_note(char_or_chord):
    if not SOUND_ENGINE: return
    if isinstance(char_or_chord, list):
        midis = []
        for k in char_or_chord:
            midi = VP_MAP.get(k)
            if midi:
                midis.append(midi)
                SOUND_ENGINE.note_on(midi, 105)
        if midis:
            update_piano_focus_notes(midis)
    else:
        midi = VP_MAP.get(char_or_chord)
        if midi:
            SOUND_ENGINE.note_on(midi, 105)
            update_piano_focus_notes([midi])

def precise_sleep(duration_sec):
    if duration_sec <= 0: return
    target = time.perf_counter() + duration_sec
    remain = target - time.perf_counter()
    if remain > 0.004: time.sleep(remain - 0.003)
    while time.perf_counter() < target: pass

def parse_vp_sheet(sheet_text: str, base_bpm=160, note_mode="16th"):
    beat_sec = 60.0 / max(40.0, float(base_bpm))
    if note_mode == "16th":
        unit_sec = beat_sec / 4.0
        space_sec = beat_sec / 4.0
        chord_sec = beat_sec / 2.0
    elif note_mode == "8th":
        unit_sec = beat_sec / 2.0
        space_sec = beat_sec / 2.0
        chord_sec = beat_sec * 0.75
    else:
        unit_sec = beat_sec
        space_sec = beat_sec
        chord_sec = beat_sec * 1.0

    tokens = []
    i = 0
    clean_text = sheet_text.strip()
    while i < len(clean_text):
        ch = clean_text[i]
        if ch == '[':
            end_idx = clean_text.find(']', i)
            if end_idx != -1:
                chord_keys = [k for k in clean_text[i+1:end_idx] if k in VP_MAP]
                if chord_keys: tokens.append(('chord', chord_keys, chord_sec))
                i = end_idx + 1
                continue
            else: i += 1; continue
        elif ch in [' ', '\n', '\r', '\t']:
            tokens.append(('rest', None, space_sec))
            i += 1
        elif ch == '|':
            tokens.append(('rest', None, beat_sec))
            i += 1
        elif ch == '-':
            tokens.append(('rest', None, unit_sec * 1.5))
            i += 1
        elif ch in VP_MAP:
            tokens.append(('note', ch, unit_sec))
            i += 1
        else:
            i += 1
    return tokens

# ────────────────────────────────────────────────────────
# 🎹 鋼琴演奏與曲庫管理
# ────────────────────────────────────────────────────────

def list_piano_sheets() -> str:
    """動態掃描本地 midi_sheets 資料夾，完整回傳所有收錄的鋼琴曲目清單 (不限制數量)。"""
    real_songs = []
    if os.path.exists(MIDI_SHEETS_DIR):
        for f in sorted(os.listdir(MIDI_SHEETS_DIR)):
            if f.lower().endswith(('.mid', '.midi')) and not f.lower().startswith(('test_', 'temp_')):
                stem = os.path.splitext(f)[0]
                if stem.lower().endswith('.mid'):
                    stem = os.path.splitext(stem)[0]
                clean_name = re.sub(r'[\'\"_\-.,!?()（）\[\]\s]+', ' ', stem).strip()
                if clean_name and len(clean_name) >= 2:
                    real_songs.append(clean_name)
                    
    if not real_songs:
        real_songs = ["卡農", "給愛麗絲", "月光奏鳴曲", "冬風練習曲", "鐘", "千本櫻", "天空之城", "殘酷天使"]
        
    songs_str = "、".join([f"《{s}》" for s in real_songs])
    return f"🎹 7L 鋼琴曲庫目前共收錄 {len(real_songs)} 首曲目完整清單：\n{songs_str}\n所有曲目皆隨點隨彈，也支援多曲並發合奏（如：冬風 x 鐘）喔！"

PIANO_SESSION_ID = 0
current_piano_process = None
current_piano_song_title = ""
current_piano_midi_file = ""
PIANO_REQUEST_QUEUE = deque()
PENDING_PIANO_PRELOADS = set()
LAST_PIANO_OPEN_TIME = 0.0
LAST_PIANO_PLAY_START_TIME = 0.0

async def open_virtual_piano() -> str:
    """拿出 88 鍵平台鋼琴視覺化視窗並就位待命，不自動彈奏曲目（供老爸彈奏、點歌或練習）。"""
    global is_piano_active, current_piano_song_title, current_piano_task, current_piano_process, current_ai_state, PIANO_SESSION_ID, LAST_PIANO_OPEN_TIME
    
    LAST_PIANO_OPEN_TIME = time.time()
    is_piano_active = True
    current_ai_state = "PIANO"
    current_piano_song_title = ""
    
    # 1. 走位到鋼琴位置
    await move_vts_spatial(target_pos="鋼琴旁", duration=1.5)
    
    # 2. 切換表情
    if vc.GLOBAL_VTS:
        await set_vts_expression(vc.GLOBAL_VTS, "星星眼")
        
    # 3. 檢查鋼琴視窗是否已經在運行
    if is_piano_window_alive():
        log_print("🎹 [鋼琴舞台] 88 鍵鋼琴視窗已經在桌面上就緒，立即還原並置頂於最前端！")
        bring_piano_window_to_front()
        return ""
        
    # 4. 啟動乾淨的 88 鍵視覺化鋼琴視窗 (不帶 --auto-close 與 --midi，保持常駐待命)
    try:
        current_piano_process = subprocess.Popen([
            sys.executable,
            get_piano_script_path(),
            "--volume", str(GLOBAL_PIANO_VOLUME),
            "--speed", str(GLOBAL_PIANO_SPEED),
            "--ndi"
        ])
        log_print(f"🎹 [鋼琴舞台] 成功拿出 88 鍵鋼琴常駐待命視窗 (音量: {GLOBAL_PIANO_VOLUME}%, 倍速: {GLOBAL_PIANO_SPEED}x)。")
    except Exception as e:
        log_print(f"❌ [啟動鋼琴視窗異常]: {e}")
        return ""
        
    await asyncio.to_thread(main_obj.update_subtitle, "🎹 [7L 鋼琴舞台已就緒] 隨時歡迎老爸彈奏或點播名曲～")
    return ""

IS_PIANO_AUTO_RADIO_MODE = False

def get_midi_file_duration(midi_path: str) -> float:
    """精準計算 MIDI 檔案長度 (秒)"""
    try:
        import mido
        mid = mido.MidiFile(midi_path, clip=True)
        return float(mid.length) if mid.length > 0 else 120.0
    except Exception:
        return 120.0

# ── 🎺 MIDI 樂隊（多音色同時演奏）：保留 MIDI 原通道＋program，直發引擎 ──
# 通道慣例：0 主奏（鋼琴/小提琴）／1 貝斯／2 鋪底（弦樂）／9 鼓組
BAND_PRESETS = {
    "piano_trio": {0: 0, 1: 33},        # 鋼琴＋貝斯＋鼓
    "violin_lead": {0: 40, 1: 33, 2: 48},  # 小提琴主奏＋貝斯＋弦樂＋鼓
    "guitar_band": {0: 27, 1: 33, 2: 48},  # 清音吉他＋貝斯＋弦樂＋鼓
    "strings": {0: 48, 1: 42, 2: 52},   # 弦樂＋大提琴＋合唱（無鼓）
    "rock_band": {0: 30, 1: 36, 2: 61},  # 重金屬吉他＋Slap貝斯＋銅管＋鼓
    "jazz_trio": {0: 4, 1: 32, 2: 65},  # 電鋼＋原聲貝斯＋薩克斯（鼓檔輕）
    "brass_band": {0: 56, 1: 57, 2: 61},  # 小號＋長號＋銅管合奏＋鼓
    "folk_band": {0: 107, 1: 32, 2: 46},  # 古箏＋原聲貝斯＋豎琴＋鼓
    "synth_band": {0: 81, 1: 38, 2: 89},  # 合成主音＋合成貝斯＋音墊＋鼓
    "orchestra": {0: 48, 1: 43, 2: 60, 3: 73},  # 弦樂＋低音提琴＋法國號＋長笛＋鼓
}
BAND_DRUMS = {36, 38, 42, 46, 49, 51}  # kick/snare/hat/tom/crash/ride（僅供作曲自動配鼓參考）


async def play_midi_band(midi_path: str, band_map: dict = None, speed: float = 1.0,
                         title: str = "", session_id: int = 0, layers: list = None) -> str:
    """🎺 MIDI 樂隊演奏：多軌 MIDI 保留原通道＋音色同時發聲（小提琴拉主旋律＋鋼琴伴奏＋鼓打底一次到位）。
    band_map 例：{0: 40, 1: 33}（ch0 換小提琴、ch1 換貝斯；缺席通道沿用檔內 program，9 鼓恆免配器）。
    layers 疊層例：[{"midi_path": "b.mid", "channel_shift": 4, "program": 48}]
      → 多首同時合奏（mashup 樂隊版）；channel_shift 平移通道避撞（鼓 ch9 永不平移）。"""
    global is_piano_active, current_piano_song_title, current_piano_midi_file
    import mido
    if not midi_path or not os.path.exists(midi_path):
        return "（系統回報：樂隊譜不存在）"
    if session_id and session_id != PIANO_SESSION_ID:
        return ""
    init_piano_synthesizer()
    if not SOUND_ENGINE or not SOUND_ENGINE.midi_out:
        return "（系統回報：無 MIDI 輸出裝置，樂隊靜音）"
    if band_map:
        for ch, prog in (band_map or {}).items():
            try:
                SOUND_ENGINE.set_channel_program(int(ch), int(prog))
            except Exception:
                pass
    if title:
        is_piano_active = True
        current_piano_song_title = title
        current_piano_midi_file = midi_path
    try:
        from services.piano_engine import SOUND_ENGINE as _SE  # noqa (self-ref safe)
    except Exception:
        pass
    # ── 疊層合併：主檔＋layers 多首同時合奏（通道平移避撞，鼓 ch9 永不平移）──
    def _remap(ch, shift):
        if ch == 9:
            return 9
        m = (int(ch) + int(shift or 0)) % 16
        return 10 if m == 9 else m

    def _load_events(path, shift=0, prog=None):
        evs = []
        try:
            m = mido.MidiFile(path, clip=True)
        except Exception:
            return evs
        abs_t = 0.0
        prog_chs = set()
        for msg in m:
            abs_t += (msg.time or 0)
            ch = getattr(msg, "channel", 0)
            if msg.type == "note_on" and msg.velocity > 0:
                nch = _remap(ch, shift)
                if prog is not None and nch != 9 and nch not in prog_chs:
                    prog_chs.add(nch)
                    evs.append((0.0, 2, ("program", nch, int(prog))))
                evs.append((abs_t, 1 if False else 1, ("on", nch, msg.note, msg.velocity)))
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                evs.append((abs_t, 0, ("off", _remap(ch, shift), msg.note)))
            elif msg.type == "program_change":
                nch = _remap(ch, shift)
                if prog is None or nch == 9:
                    evs.append((abs_t, 2, ("program", nch, msg.program)))
            elif msg.type == "control_change":
                evs.append((abs_t, 2, ("cc", _remap(ch, shift), msg.control, msg.value)))
        return evs

    events = _load_events(midi_path)
    n_files = 1
    for layer in (layers or []):
        try:
            lp = (layer or {}).get("midi_path", "")
            if lp and os.path.exists(lp):
                events += _load_events(lp, (layer or {}).get("channel_shift", 0), (layer or {}).get("program"))
                n_files += 1
        except Exception:
            pass
    if not events:
        return f"（系統回報：樂譜無可演奏事件）"
    events.sort(key=lambda e: (e[0], e[1]))
    speed = float(speed or 1.0)
    if speed <= 0:
        speed = 1.0
    log_print(f"🎺 [MIDI 樂隊] 開演《{title or os.path.basename(midi_path)}》（{n_files} 首疊層共 {len(events)} 事件，倍速 {speed}x）")
    try:
        last_t = 0.0
        for abs_t, _prio, ev in events:
            if session_id and session_id != PIANO_SESSION_ID:
                break
            if not is_piano_active:
                break
            dt = (abs_t - last_t) / speed
            last_t = abs_t
            if dt > 0:
                await asyncio.sleep(min(dt, 2.0))
            kind = ev[0]
            if kind == "on":
                _, ch, note, vel = ev
                SOUND_ENGINE.note_on(note, vel, channel=ch)
            elif kind == "off":
                _, ch, note = ev
                SOUND_ENGINE.note_off(note, channel=ch)
            elif kind == "program":
                _, ch, prog = ev
                try:
                    SOUND_ENGINE.set_channel_program(ch, prog)
                except Exception:
                    pass
            elif kind == "cc":
                _, ch, cc, val = ev
                try:
                    SOUND_ENGINE.midi_out.write_short(0xB0 + ch, cc, val)
                except Exception:
                    pass
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log_print(f"⚠️ [MIDI 樂隊演奏異常]: {e}")
    return f"（系統回報：樂隊演奏《{title or os.path.basename(midi_path)}》完畢） [EXPRESSION: 星星眼]"


def stop_midi_band():
    """樂隊急停（全通道靜音）。"""
    try:
        if SOUND_ENGINE:
            SOUND_ENGINE.all_notes_off()
    except Exception:
        pass


async def stop_virtual_piano() -> str:
    """收起鋼琴（停止演奏、關閉桌面鋼琴介面並讓 7L 回到原本位置）。"""
    global is_piano_active, current_piano_song_title, current_piano_task, current_piano_process, current_ai_state, PIANO_SESSION_ID, IS_PIANO_AUTO_RADIO_MODE, LAST_PIANO_OPEN_TIME
    if time.time() - LAST_PIANO_OPEN_TIME < 3.5:
        log_print("🛡️ [鋼琴安全防護] 88 鍵鋼琴剛在 3.5 秒內被拿出，自動忽略衝突的【收起鋼琴】指令！")
        return ""
        
    PIANO_SESSION_ID += 1  # 註銷所有先前或進行中的鋼琴 Session
    IS_PIANO_AUTO_RADIO_MODE = False  # 關閉無限隨機電台模式
    is_piano_active = False
    current_piano_song_title = ""
    PIANO_REQUEST_QUEUE.clear()
    save_persisted_piano_state(False, "", False)
    
    if is_piano_window_alive():
        send_piano_ipc_command({"cmd": "close"})
        await asyncio.sleep(0.08)
    if current_piano_process and current_piano_process.poll() is None:
        try:
            current_piano_process.terminate()
        except Exception:
            pass
    current_piano_process = None
        
    if current_piano_task and not current_piano_task.done():
        current_piano_task.cancel()
    if SOUND_ENGINE:
        SOUND_ENGINE.all_notes_off()
    if vc.GLOBAL_VTS:
        await set_vts_expression(vc.GLOBAL_VTS, "_RESET_")
        await move_vts_spatial(target_pos="原位", duration=1.5)
    if current_ai_state == "PIANO":
        current_ai_state = "IDLE"
    await asyncio.to_thread(main_obj.update_subtitle, "")
    try:
        main_obj.append_to_unified_memory(speaker="系統", target="所有人", content="鋼琴演奏結束並收起，7L 回到基準原位", role="system", source="piano")
    except Exception:
        pass
    log_print("✅ [鋼琴舞台] 已成功收起鋼琴，7L 已優雅回到基準原位！")
    return "（系統回報：已成功收起鋼琴並回到基準原位） [EXPRESSION: 預設]"

import mido

MIDI_SHEETS_DIR = "midi_sheets"
os.makedirs(MIDI_SHEETS_DIR, exist_ok=True)
MIDI_CATALOG_FILE = os.path.join(MIDI_SHEETS_DIR, "midi_catalog.json")

def auto_clean_non_midi_files(folder_path: str = MIDI_SHEETS_DIR):
    """自動掃描並刪除 midi_sheets 資料夾中所有非 .mid / .midi 的檔案 (排除 midi_catalog.json)"""
    if not os.path.exists(folder_path):
        return
    try:
        for fname in os.listdir(folder_path):
            fpath = os.path.join(folder_path, fname)
            if os.path.isfile(fpath):
                if fname.lower() == "midi_catalog.json":
                    continue
                if not fname.lower().endswith(('.mid', '.midi')):
                    try:
                        os.remove(fpath)
                        log_print(f"🧹 [曲庫自動清理] 已刪除非 MIDI 檔案: {fname}")
                    except Exception:
                        pass
    except Exception as e:
        log_print(f"⚠️ [曲庫自動清理異常]: {e}")

auto_clean_non_midi_files()

def sync_and_update_midi_catalog() -> Dict[str, str]:
    """雙向自動同步更新 midi_catalog.json：
    1. 自動新增：掃描 midi_sheets 資料夾內的所有 .mid 檔案，自動為新曲目建立映射索引。
    2. 自動清理：若 catalog 中指向的 .mid 檔案已被手動刪除，自動自 JSON 中移除無效死鏈。
    3. 自動持久化存檔。
    """
    catalog = {}
    if os.path.exists(MIDI_CATALOG_FILE):
        try:
            with open(MIDI_CATALOG_FILE, "r", encoding="utf-8") as f:
                catalog = json.load(f)
        except Exception:
            catalog = {}

    disk_files = {}
    if os.path.exists(MIDI_SHEETS_DIR):
        for f in os.listdir(MIDI_SHEETS_DIR):
            if f.lower().endswith(('.mid', '.midi')) and os.path.isfile(os.path.join(MIDI_SHEETS_DIR, f)):
                disk_files[f.lower()] = f

    cleaned_catalog = {}
    for alias, fname in catalog.items():
        fname_base = os.path.basename(fname)
        if fname_base.lower() in disk_files:
            cleaned_catalog[alias] = disk_files[fname_base.lower()]

    for f_lower, real_fname in disk_files.items():
        stem = os.path.splitext(real_fname)[0].strip()
        stem_lower = stem.lower()
        if stem_lower not in cleaned_catalog:
            cleaned_catalog[stem_lower] = real_fname
        norm_name = re.sub(r'[\'\"_\-.,!?()（）\[\]\s]+', ' ', stem).strip().lower()
        if norm_name and norm_name not in cleaned_catalog:
            cleaned_catalog[norm_name] = real_fname

    if cleaned_catalog != catalog or not os.path.exists(MIDI_CATALOG_FILE):
        try:
            with open(MIDI_CATALOG_FILE, "w", encoding="utf-8") as f:
                json.dump(cleaned_catalog, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_print(f"⚠️ [MIDI 索引庫同步失敗]: {e}")

    return {k.lower().strip(): os.path.abspath(os.path.join(MIDI_SHEETS_DIR, v)) for k, v in cleaned_catalog.items()}

def save_midi_catalog_entry(alias_name: str, file_path: str):
    """動態將新曲目別名與路徑持久化存入 JSON 檔案並同步全量索引"""
    global AUTHENTIC_MIDI_MAP
    clean_k = alias_name.strip().lower()
    clean_v = os.path.basename(file_path)
    abs_p = os.path.abspath(os.path.join(MIDI_SHEETS_DIR, clean_v))
    AUTHENTIC_MIDI_MAP[clean_k] = abs_p
    try:
        data = {}
        if os.path.exists(MIDI_CATALOG_FILE):
            with open(MIDI_CATALOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        data[clean_k] = clean_v
        with open(MIDI_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_print(f"⚠️ [MIDI 曲庫] 儲存 {MIDI_CATALOG_FILE} 失敗: {e}")
    AUTHENTIC_MIDI_MAP = sync_and_update_midi_catalog()

AUTHENTIC_MIDI_MAP = sync_and_update_midi_catalog()

MIDI_AI_MATCH_CACHE: Dict[str, str] = {}

async def resolve_piano_intent_by_ai(
    song_query: str, 
    available_files: list,
    current_playing_title: str = "",
    current_playing_file: str = "",
    is_direct_song_name: bool = False
) -> dict:
    """🧠 100% 全純 AI 鋼琴意圖與曲庫神經大腦（倒序高智商模型 3.8 ➔ 3.7 ➔ 3.6 梯隊執行，零關鍵字寫死）：
    深度分析老爸/觀眾說話意圖（嚴格區分點歌 vs 詢問鋼琴視窗狀態/抱怨）、判斷是否想換不同版本/不同改編（排除當前正在播放之版本）、重播意圖、隨機/電台意圖、多曲合奏、本地最佳比對或雲端搜尋詞。
    """
    clean_q = song_query.strip() if song_query else ""
    default_res = {
        "is_song_request": False,
        "action_type": "none",
        "is_switch_version": False,
        "is_replay": False,
        "song_title": "",
        "is_random": False,
        "is_mashup": False,
        "matched_files": [],
        "search_online_query": "",
        "_from_ai": False
    }
    if not clean_q:
        default_res["is_song_request"] = True
        default_res["action_type"] = "song_request"
        default_res["is_random"] = True
        default_res["_from_ai"] = True
        return default_res

    current_state_cue = ""
    cur_fname = os.path.basename(current_playing_file) if current_playing_file else ""
    if current_playing_title or cur_fname:
        current_state_cue = f"\n【目前正在彈奏中的曲目】：《{current_playing_title}》（目前播放檔案: {cur_fname}）"

    direct_cue = "\n【注意】：傳入內容可能為曲名或口頭指令，請優先分析是否為操作指令或純對話；若為歌曲/樂曲名稱，再進行匹配！" if is_direct_song_name else ""

    prompt = f"""妳是 7L 的 AI 鋼琴音樂總監（具備頂尖音樂智商與深層語意理解能力）。請深度理解老爸/觀眾的說話意圖並進行精準判斷。

【使用者輸入】："{clean_q}"{current_state_cue}{direct_cue}
【本地曲庫現有 MIDI 清單】：
{json.dumps(available_files, ensure_ascii=False)}

【判定準則】：
1. 🎯 action_type 與 is_song_request 意圖識別（請根據深層語意嚴格分類，完全不使用死板關鍵字）：
   - 🌟 "song_request"（點歌/想聽曲目/要求換版本/重播/隨機名曲）：
     * 使用者明確表達點歌、想聽、要求演奏、換曲、切歌、播放等意圖。
     * 或使用者輸入內容本身即為歌曲/樂曲名稱（包含流行音樂、古典名曲、動漫配樂、各國歌曲、專有名詞曲名等）。
     * 此時 is_song_request 必須填 true，action_type 填 "song_request"。
   - 🎹 "open_piano"（拿出/打開鋼琴指令）：
     * 使用者要求把鋼琴拿出來、打開鋼琴、顯示琴鍵視窗、讓鋼琴就位待命等介面操作（非點歌）。
     * 例如：「鋼琴拿出來」、「打開鋼琴」、「把琴叫出來」、「你的鋼琴呢」、「琴台放出來」、「開個琴」、「拿出鋼琴」、「鋼琴就位」等。
     * 此時 is_song_request 必須填 false，action_type 填 "open_piano"。
   - 🛑 "stop_piano"（收起/停止彈琴指令）：
     * 使用者要求收起鋼琴、不要彈了、停止演奏、關閉鋼琴、安靜、暫停、太吵了別彈等。
     * 例如：「收起來」、「不要彈了」、「別彈了」、「停下來」、「安靜」、「先把琴收了」、「暫停一下」、「關掉鋼琴」、「安靜別吵」等。
     * 此時 is_song_request 必須填 false，action_type 填 "stop_piano"。
   - 🖥️ "window_status"（詢問/抱怨鋼琴視窗狀態）：
     * 使用者詢問鋼琴視窗開了沒、沒出來啊、視窗在哪裡、視窗大小位置等。
     * 例如：「鋼琴開了沒」、「沒出來啊」、「視窗在哪」、「有看到鋼琴嗎」、「視窗被擋住了」等。
     * 此時 is_song_request 必須填 false，action_type 填 "window_status"。
   - 💬 "chat"（純日常閒聊/問候/感嘆/純數字）：
     * 單純日常打招呼、讚美、感嘆詞、純數字/刷屏彈幕等與鋼琴無關之發言。
     * 例如：「你好」、「早安」、「晚安」、「嗨」、「哈囉」、「666」、「笑死」、「水喔」、「厲害」、「今天天氣好」等。
     * 此時 is_song_request 必須填 false，action_type 填 "chat"。

2. 🔄 is_switch_version（版本切換判定）：
   - 審視使用者說話語意：若使用者表達想聽「另一種版本」、「不同改編/演奏家」、「換一版」、「不同檔案」：
     * 請在【本地曲庫現有 MIDI 清單】中尋找與該曲相符的【其他候選版本】！
     * ⚠️【核心排他】：必須排除目前正在彈奏的檔案（{cur_fname}），挑選另一個不同的吻合檔案放入 matched_files！
     * 將 is_switch_version 設為 true！
   - 若使用者只是想重聽目前這首/從頭彈，is_replay 設為 true，is_switch_version 設為 false。

3. 🎵 song_title：
   - 提取出的乾淨純曲名（若非點歌，填空字串 ""）。

4. 🎲 is_random：
   - 是否為隨機/隨便/電台意圖。

5. 🎹 本地與演奏家版本比對：
   - ⚠️【核心鐵律：嚴禁弱相關強行湊數】：matched_files 僅能填入「歌曲本體完全吻合」之本地檔案！
   - 若使用者點播的歌曲本地曲庫根本沒有（例如點《未完成婚姻論》，但本地只有《前前前世(未完成)》，兩者核心曲名完全不同，括號內的『未完成』只是編曲狀態標籤），【絕對禁止強行填入 matched_files，必須填 [] 空陣列】！
   - 若使用者點的歌本地無收錄、或指定特定演奏家而本地無此版本，matched_files 務必留空 []，並在 search_online_query 填寫真實精確曲名（如 "未完成婚姻論"），引導系統自動走線上/YouTube 抓譜！
   - 只有當本地確實有同名或完全相符之樂曲時，才將最吻合的檔案放入 matched_files（若要求換版本，必須為另一個版本的檔名）。

【請輸出純 JSON】：
{{
  "is_song_request": true/false, // 是否真正在點歌/想聽曲目？指令、狀態詢問、問候或非點歌請填 false
  "action_type": "song_request", // 必填之一: "song_request" | "open_piano" | "stop_piano" | "window_status" | "chat"
  "is_switch_version": true/false, // 是否為要求切換至不同版本/另一版本？
  "is_replay": true/false, // 是否為要求重播目前這首？
  "song_title": "", // 提取出的乾淨純曲名，非點歌填 ""
  "is_random": false, // 是否為隨機/隨意點播
  "is_mashup": false, // 是否為多曲合奏/混搭
  "matched_files": ["matched_local_filename.mid"], // 本地吻合檔案清單（若無精準相符曲目，絕對填 [] 空陣列）
  "search_online_query": "" // 僅當 is_song_request 為 true 且本地無此曲時填寫精準搜尋詞，非點歌【絕對填空字串】
}}"""

    active_keys = get_piano_gemini_keys()
    if active_keys:
        # 👑 倒序高智商模型梯隊：3.8 ➔ 3.7 ➔ 3.6 ➔ 3.5 ➔ 3.1-pro ➔ 3-flash ➔ 3.5-flash-lite
        models = getattr(main_obj, 'HIGH_IQ_GEMINI_MODELS', None) or ["gemini-2.5-flash", "gemini-2.0-flash"]
        dead = getattr(main_obj, 'DEAD_GEMINI_MODELS', None) or set()
        is_locked_fn = getattr(main_obj, 'is_model_locked', None)
        ring_fn = getattr(main_obj, 'get_pingpong_ring_indices', None)
        for m in models:
            if m in dead or (callable(is_locked_fn) and is_locked_fn(m)):
                continue
            raw_indices = ring_fn(len(active_keys), CURRENT_GEMINI_KEY_STEP) if callable(ring_fn) else None
            ring_indices = (raw_indices if isinstance(raw_indices, (list, tuple)) else list(range(len(active_keys))))[:3]
            for idx in ring_indices:
                g_key = active_keys[idx]
                try:
                    temp_client = genai.Client(api_key=g_key)
                    resp = await asyncio.wait_for(
                        temp_client.aio.models.generate_content(
                            model=m,
                            contents=prompt,
                            config=types.GenerateContentConfig(temperature=0.1, response_mime_type="application/json")
                        ),
                        timeout=4.0
                    )
                    if resp and resp.text:
                        data = json.loads(resp.text.strip())
                        data["_from_ai"] = True
                        return data
                except Exception:
                    continue

    return default_res

def extract_core_title(raw_name: str) -> str:
    """提取檔名或搜尋詞的核心主曲名，徹底剔除括號標籤、狀態備註、演唱者與技術後綴噪聲"""
    if not raw_name:
        return ""
    t = os.path.splitext(os.path.basename(raw_name))[0]
    # 剔除括號內任何技術/狀態標籤，如 (未完成)、(試聽)、[4K]、【鋼琴】、(Sheet Music Boss)、(Official)、(Full Ver) 等
    t = re.sub(r'[\(\[（【\{][^\)\]）】\}]*[\)\]）】\}]', ' ', t)
    # 剔除常見修飾詞/技術後綴
    t = re.sub(r'(?:主題曲|片尾曲|插曲|鋼琴版|鋼琴演奏|原神|RADWIMPS|Yoasobi|Animenz|Synthesia|Tutorial|Cover|Remix|BGM|bgm|ost|OST)', ' ', t, flags=re.IGNORECASE)
    # 移除標點與多餘空白
    t = re.sub(r'[\'\"_\-.,!?~～/\\+]+', ' ', t).strip()
    t = re.sub(r'\s{2,}', ' ', t).strip()
    return t

def is_midi_match_valid(query_title: str, matched_filename: str) -> bool:
    """雙重防呆校驗：驗證匹配出的 MIDI 檔名是否確實為目標曲目，嚴格杜絕因備註標籤偶然同字（如『未完成』）導致的弱相關誤配"""
    if not query_title or not matched_filename:
        return False
    q_clean = clean_song_title_for_speech(query_title).lower().strip()
    f_stem = os.path.splitext(os.path.basename(matched_filename))[0].lower().strip()
    
    # 1. 若完全相同，直接放行
    if q_clean == f_stem:
        return True

    q_core = extract_core_title(query_title).lower().strip()
    f_core = extract_core_title(matched_filename).lower().strip()

    if not q_core or not f_core:
        return True

    # 2. 若核心名互相包含，直接放行
    if q_core in f_core or f_core in q_core:
        return True

    # 3. 比對核心詞 token 相似度
    q_tokens = [tok for tok in re.split(r'[\s_\-]+', q_core) if len(tok) >= 2]
    f_tokens = [tok for tok in re.split(r'[\s_\-]+', f_core) if len(tok) >= 2]
    if q_tokens and f_tokens:
        if any(t in f_core for t in q_tokens) or any(t in q_core for t in f_tokens):
            return True

    # 4. 中文字符重疊率檢查 (針對未分詞的中文歌曲名稱)
    common_chars = set(q_core) & set(f_core)
    common_chars = {c for c in common_chars if c.strip()}
    overlap_ratio = len(common_chars) / max(len(set(q_core)), 1)
    if overlap_ratio >= 0.6:
        return True

    log_print(f"🛡️ [曲庫防呆攔截] 本地檔名《{matched_filename}》核心主名（{f_core or f_stem}）與點歌《{query_title}》（{q_core}）無實質相關（判定為狀態標籤噪聲弱匹配），已安全剔除，自動轉為線上抓譜！")
    return False

async def match_midi_with_ai(song_query: str, available_files: list) -> str:
    """相容保留：透過 resolve_piano_intent_by_ai 取得匹配檔名"""
    res = await resolve_piano_intent_by_ai(song_query, available_files)
    matched = res.get("matched_files", [])
    if matched:
        cand = matched[0]
        if is_midi_match_valid(song_query, cand):
            return cand
    return "NONE"

async def resolve_local_midi_file(song_query: str) -> Tuple[Optional[str], str]:
    """🌟 全新 AI 語意驅動：100% 優先在本機 midi_sheets 資料夾中深度智能查找最相符的 MIDI 檔案。
    支援中文曲名、日文假名、英文名、作曲家、動漫譯名、繁簡轉譯與 Gemini 深度語意理解。
    """
    clean_q = song_query.strip().lower()
    if not clean_q:
        return None, ""
        
    norm_q = re.sub(r'[\'\"_\-.,!?()（）\[\]\s]+', ' ', clean_q).strip()

    # 1. 檢查記憶快取 (0 延遲秒開，且通過防呆校驗)
    if clean_q in MIDI_AI_MATCH_CACHE:
        cached_p = MIDI_AI_MATCH_CACHE[clean_q]
        if os.path.exists(cached_p) and is_midi_match_valid(clean_q, os.path.basename(cached_p)):
            return cached_p, os.path.splitext(os.path.basename(cached_p))[0]
        else:
            MIDI_AI_MATCH_CACHE.pop(clean_q, None)

    # 2. 精準比對 AUTHENTIC_MIDI_MAP
    if clean_q in AUTHENTIC_MIDI_MAP:
        p = AUTHENTIC_MIDI_MAP[clean_q]
        if os.path.exists(p) and is_midi_match_valid(clean_q, os.path.basename(p)):
            return p, clean_q
            
    if norm_q in AUTHENTIC_MIDI_MAP:
        p = AUTHENTIC_MIDI_MAP[norm_q]
        if os.path.exists(p) and is_midi_match_valid(clean_q, os.path.basename(p)):
            return p, norm_q

    # 3. 本機檔案名稱快速直接比對
    if os.path.exists(MIDI_SHEETS_DIR):
        local_files = [
            f for f in os.listdir(MIDI_SHEETS_DIR) 
            if f.lower().endswith(('.mid', '.midi')) and not f.lower().startswith(('test_', 'temp_'))
        ]
        
        for f in local_files:
            f_stem = os.path.splitext(f)[0].lower()
            f_norm = re.sub(r'[\'\"_\-.,!?()（）\[\]\s]+', ' ', f_stem).strip()
            if clean_q == f.lower() or clean_q == f_stem or norm_q == f_norm:
                if is_midi_match_valid(clean_q, f):
                    target_path = os.path.join(MIDI_SHEETS_DIR, f)
                    MIDI_AI_MATCH_CACHE[clean_q] = target_path
                    return target_path, os.path.splitext(f)[0]

        # 4. 🧠 呼叫 Gemini / AI 進行全資料夾跨語言語意比對（六兆年與一夜物語 ➔ 六兆年と一夜物語.mid）
        if local_files:
            ai_matched_filename = await match_midi_with_ai(song_query, local_files)
            if ai_matched_filename and ai_matched_filename != "NONE":
                for f in local_files:
                    if f.lower() == ai_matched_filename.lower() or os.path.splitext(f)[0].lower() == os.path.splitext(ai_matched_filename)[0].lower():
                        if is_midi_match_valid(clean_q, f):
                            target_path = os.path.join(MIDI_SHEETS_DIR, f)
                            log_print(f"🧠 [AI 曲庫神經匹配] 成功將『{song_query}』語意匹配至本地: 《{f}》！")
                            MIDI_AI_MATCH_CACHE[clean_q] = target_path
                            save_midi_catalog_entry(song_query, target_path)
                            return target_path, os.path.splitext(f)[0]

    return None, ""

def get_local_piano_seeds() -> List[str]:
    """100% 動態掃描本地 midi_sheets 資料夾，獲取所有真實存在的樂譜名稱"""
    if os.path.exists(MIDI_SHEETS_DIR):
        files = [
            os.path.splitext(f)[0]
            for f in os.listdir(MIDI_SHEETS_DIR)
            if f.lower().endswith(('.mid', '.midi')) and not f.lower().startswith(('test_', 'temp_'))
        ]
        if files:
            return files

def clean_song_title_for_speech(raw_title: str) -> str:
    """清理鋼琴曲名中的技術標籤、YouTube 後綴與多餘括號，保留自然俐落的曲名供大腦語音輸出"""
    if not raw_title:
        return ""
    t = str(raw_title)
    t = re.sub(r'\.(?:mid|midi)$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'[\(\[\{]\s*(?:Sheet Music Boss|Synthesia|MIDI|Piano Tutorial|Official|Original|Cover|4K|1080P|HD|Audio|Piano|midi piano changed|HQ|Remix)\s*[\)\]\}]', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^\[([^\]]+)\]', r'\1', t).strip()
    t = re.sub(r'[-\s]*(?:midi piano changed|midi changed|midi version|piano version|midi|synthesia)\s*$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'[\s\-_]+$', '', t)
    t = re.sub(r'^[\s\-_]+', '', t)
    t = re.sub(r'\s{2,}', ' ', t).strip()
    t = t.replace('[', '').replace(']', '')
    return t or raw_title

async def generate_dynamic_piano_chatter(song_title: str, target: str = "dad", requester_name: str = "老爸", is_radio: bool = True) -> str:
    """由 AI 大腦即時自主動態生成過場/切歌/彈琴台詞 (支援對象感知，100% 自由意志決定說話或安靜沉醉，零固定罐頭句與數學機率)"""
    try:
        user_prof = await main_obj.get_user_profile()
        c_name = user_prof.get("custom_name", main_obj.DEFAULT_USER_TITLE)
        song_title = clean_song_title_for_speech(song_title)
        
        # 🛑 觀眾頻道絕對嚴禁稱呼為「老爸」
        if target == "audience" and requester_name in ["老爸", "老爸（主播）", ""]:
            requester_name = "大家"
        
        if is_radio:
            if target == "audience":
                mode_desc = f"在直播間電台模式下隨機接續下一首《{song_title}》為大家演奏"
                audience_prompt = "直播間的觀眾與大家"
            else:
                mode_desc = f"在鋼琴電台模式下隨機接續下一首《{song_title}》"
                audience_prompt = f"老爸（{c_name}）"
        else:
            if target == "audience":
                mode_desc = f"為觀眾【{requester_name}】演奏點播的《{song_title}》"
                audience_prompt = f"點歌的觀眾【{requester_name}】以及直播間的大家"
            else:
                mode_desc = f"為老爸彈奏《{song_title}》"
                audience_prompt = f"老爸（{c_name}）"

        prompt = f"""妳是 7L，正坐在 88 鍵鋼琴前彈奏鋼琴。
妳現在正準備{mode_desc}。
【自由意志決定】：
妳可以自由決定要不要開口對【{audience_prompt}】隨興說一句話（例如發表對這首曲子的感受、即興搭話、或向對方致意），或者妳也可以選擇「安靜專注沉醉彈奏、不開口說話」。
- 若妳想說話：請以妳自然、隨性真人的語氣，直接輸出妳要說的簡短一句話（10~25字以內，嚴禁任何死板套話，嚴禁 Emoji，注意妳說話的對象是{audience_prompt}）。
- 若妳現在想安靜彈琴、不說話：請只輸出 `[SILENCE]`。
直接輸出妳的決定："""
        
        active_keys = get_piano_gemini_keys()
        if active_keys:
            target_k_idx = (main_obj.get_pingpong_alternating_index(len(active_keys), CURRENT_GEMINI_KEY_STEP) if hasattr(main_obj, 'get_pingpong_alternating_index') and main_obj.get_pingpong_alternating_index else 0)
            client = genai.Client(api_key=active_keys[target_k_idx])
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.9,
                        max_output_tokens=60
                    )
                ),
                timeout=2.5
            )
            if resp.text:
                txt = resp.text.strip()
                log_print(f"🤖 原始大腦輸出: {txt} (⚡ 鋼琴過場)")
                if "[SILENCE]" in txt or "[SKIP]" in txt or "[QUIET]" in txt:
                    return ""
                clean = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', txt).strip(' "\'「」\n\r')
                return clean
    except Exception:
        pass
    return ""

async def play_piano_worker(song_title: str, sheet_text: str, bpm: int, mode: str, midi_file: str = None, session_id: int = 0):
    """背景鋼琴演奏與 Live2D 姿態連動協程 (自動喚出視覺化 88 鍵瀑布流視窗並支援點播隊列與連續隨機電台自動接續)"""
    global is_piano_active, current_piano_song_title, current_piano_midi_file, current_piano_process, current_ai_state, PIANO_SESSION_ID, IS_PIANO_AUTO_RADIO_MODE, LAST_PIANO_OPEN_TIME
    if session_id != PIANO_SESSION_ID:
        return
        
    try:
        LAST_PIANO_OPEN_TIME = time.time()
        is_piano_active = True
        current_piano_song_title = song_title
        current_ai_state = "PIANO"
        
        # 1. 走位到鋼琴位置
        await move_vts_spatial(target_pos="鋼琴旁", duration=1.2)
        
        # 🌟 溫柔等待：等待 7L 說完開場白 (例如「好喔，7L 這就為老爸演奏...」) 後再開始彈奏，絕不搶先發聲
        speech_wait_start = time.time()
        while time.time() - speech_wait_start < 10.0:
            if session_id != PIANO_SESSION_ID or not is_piano_active:
                return
            is_speaking = False
            try:
                is_speaking = pygame.mixer.music.get_busy() or not main_obj.speech_queue.empty() or current_ai_state == "TALKING"
            except Exception:
                pass
            if not is_speaking and time.time() - speech_wait_start > 0.6:
                break
            await asyncio.sleep(0.15)

        # 就位沉靜片刻 (0.3 秒準備彈奏)
        await asyncio.sleep(0.3)

        if session_id != PIANO_SESSION_ID or not is_piano_active:
            return
            
        # 2. 切換表情
        if vc.GLOBAL_VTS:
            await set_vts_expression(vc.GLOBAL_VTS, "星星眼")
            
        # 3. 循環播放當前曲目、待播隊列與無限隨機電台
        while session_id == PIANO_SESSION_ID and is_piano_active:
            await asyncio.to_thread(main_obj.update_subtitle, f"🎹 [7L 正在演奏鋼琴] 《{song_title}》")
            
            # 4. 自動喚出 88 鍵視覺化瀑布流鋼琴介面並進行古典演奏 (支援多軌同時並發，視窗常駐不重開、無縫切歌)
            if midi_file and ("|" in midi_file or os.path.exists(midi_file)):
                if "|" in midi_file:
                    sub_paths = [p.strip() for p in midi_file.split("|") if os.path.exists(p.strip())]
                    raw_dur = max([get_midi_file_duration(p) for p in sub_paths], default=120.0)
                    tracks_payload = [{"title": os.path.basename(p).replace(".mid", "").replace(".MID", ""), "midi_path": p} for p in sub_paths]
                else:
                    sub_paths = [midi_file]
                    raw_dur = get_midi_file_duration(midi_file)
                    tracks_payload = [{"title": song_title, "midi_path": midi_file}]
                    
                song_dur = (raw_dur / GLOBAL_PIANO_SPEED) if GLOBAL_PIANO_SPEED > 0 else raw_dur
                
                # 🌟 若鋼琴視窗已經在桌面上運行 ➔ 直接發送 IPC 指令無縫切換曲目，絕不關閉或重開視窗！
                if is_piano_window_alive():
                    bring_piano_window_to_front()
                    if len(tracks_payload) > 1:
                        log_print(f"🎹 [鋼琴舞台] 88 鍵鋼琴視窗已在桌面上，多軌並發演奏: 《{song_title}》 (原時長: {raw_dur:.1f}s | 倍速: {GLOBAL_PIANO_SPEED}x ➔ 實際時長: {song_dur:.1f}s)")
                        send_piano_ipc_command({
                            "cmd": "play_simultaneous",
                            "tracks": tracks_payload,
                            "volume": GLOBAL_PIANO_VOLUME,
                            "speed": GLOBAL_PIANO_SPEED
                        })
                    else:
                        log_print(f"🎹 [鋼琴舞台] 88 鍵鋼琴視窗已在桌面上，無縫切換曲目: 《{song_title}》 (原時長: {raw_dur:.1f}s | 倍速: {GLOBAL_PIANO_SPEED}x ➔ 實際時長: {song_dur:.1f}s)")
                        send_piano_ipc_command({
                            "cmd": "play",
                            "title": song_title,
                            "midi_path": midi_file,
                            "volume": GLOBAL_PIANO_VOLUME,
                            "speed": GLOBAL_PIANO_SPEED
                        })
                else:
                    # 鋼琴視窗尚未開啟 ➔ 啟動新視窗
                    LAST_PIANO_OPEN_TIME = time.time()
                    log_print(f"🎹 [鋼琴舞台] 啟動 88 鍵瀑布流鋼琴視覺化視窗: 《{song_title}》 (實際時長: {song_dur:.1f}s | 倍速: {GLOBAL_PIANO_SPEED}x)")
                    piano_cmd = [
                        sys.executable, 
                        get_piano_script_path(), 
                        "--multi-midi" if len(sub_paths) > 1 else "--midi", midi_file, 
                        "--title", song_title,
                        "--volume", str(GLOBAL_PIANO_VOLUME),
                        "--speed", str(GLOBAL_PIANO_SPEED),
                        "--ndi"
                    ]
                    current_piano_process = subprocess.Popen(piano_cmd)
                
                # 🎹 即時鋼琴狀態驅動等待迴圈（以 UDP 即時播放狀態為第一優先，時間為極端斷線保底）
                song_start_time = time.time()
                has_started_playing = False
                
                while session_id == PIANO_SESSION_ID and is_piano_active:
                    elapsed = time.time() - song_start_time
                    
                    # 1. 優先檢查鋼琴視窗的即時 UDP 播放狀態 (來自 test_virtual_piano.py Port 39281)
                    if is_piano_window_alive():
                        rt_playing = GLOBAL_PIANO_REALTIME_STATE.get("is_playing", False)
                        rt_event = GLOBAL_PIANO_REALTIME_STATE.get("event", "")
                        
                        if rt_playing:
                            has_started_playing = True
                            
                        # 若已開彈超過 1.5 秒且收到結束訊號 (song_finished 或 is_playing 轉為 False)
                        if has_started_playing and elapsed >= 1.5:
                            if rt_event == "song_finished" or not rt_playing:
                                log_print(f"🎹 [鋼琴即時狀態] 接收到鋼琴視窗播放完畢訊號 (event={rt_event})，立即觸發無縫接續下一首！")
                                break
                    
                    # 2. 視窗行程結束檢測
                    if current_piano_process and current_piano_process.poll() is not None:
                        break
                        
                    # 3. 極端異常斷線保底（超過預估時長 + 3.0 秒仍無回應）
                    if elapsed >= song_dur + 3.0:
                        log_print(f"🎹 [鋼琴時長保底] 達到曲目預估演奏時長 ({song_dur:.1f}s)，觸發接續。")
                        break
                        
                    await asyncio.sleep(0.15)
            else:
                # 5. 文字樂譜備用解析演奏 (倍速縮放 BPM)
                scaled_bpm = int(bpm * GLOBAL_PIANO_SPEED)
                tokens = parse_vp_sheet(sheet_text, base_bpm=scaled_bpm, note_mode=mode)
                log_print(f"🎹 [鋼琴舞台] 開始演奏文字譜《{song_title}》 (共 {len(tokens)} 音符/拍子, BPM: {scaled_bpm} | 倍速: {GLOBAL_PIANO_SPEED}x)")
                
                for token_type, payload, duration in tokens:
                    if session_id != PIANO_SESSION_ID or not is_piano_active: break
                    if token_type == 'note':
                        play_piano_note(payload)
                        await asyncio.to_thread(precise_sleep, duration)
                    elif token_type == 'chord':
                        play_piano_note(payload)
                        await asyncio.to_thread(precise_sleep, duration)
                    elif token_type == 'rest':
                        await asyncio.to_thread(precise_sleep, duration)
            
            # 🌟 演奏完畢後的接續邏輯：
            if session_id != PIANO_SESSION_ID or not is_piano_active:
                break

            # 🎯 優先檢查 1：是否有觀眾/老爸預約點播的曲目！（無縫插播優先於隨機電台）
            if PIANO_REQUEST_QUEUE:
                await asyncio.sleep(1.2)  # 曲目間自然換氣微間隔
                if session_id != PIANO_SESSION_ID or not is_piano_active:
                    break
                req_item = PIANO_REQUEST_QUEUE.popleft()
                song_title = clean_song_title_for_speech(req_item.get("title", ""))
                midi_file = req_item.get("midi_path", "")
                req_target = req_item.get("target") or ("audience" if get_current_speaking_target() == "audience" else "dad")
                req_user = req_item.get("requester") or ("大家" if req_target == "audience" else "老爸")
                if req_target == "audience" and req_user in ["老爸", "老爸（主播）", ""]:
                    req_user = "直播間觀眾"
                sheet_text = ""
                current_piano_song_title = song_title
                current_piano_midi_file = midi_file
                try:
                    main_obj.append_to_unified_memory(speaker="系統", target="所有人", content=f"鋼琴上一首演奏完畢，無縫接續為【{req_user}】演奏《{song_title}》", role="system", source="piano")
                except Exception:
                    pass
                log_print(f"🎹 [點歌無縫接續] 當前曲目結束，立即優先為【{req_user}】演奏點播曲目: 《{song_title}》！")
                ai_chatter = await generate_dynamic_piano_chatter(song_title, target=req_target, requester_name=req_user, is_radio=IS_PIANO_AUTO_RADIO_MODE)
                if ai_chatter:
                    log_print(f"💬 [鋼琴 AI 自由意志發話 ({req_target})]: {ai_chatter}")
                    await main_obj.speech_queue.put({"text": ai_chatter, "target": req_target})
                else:
                    log_print(f"🎹 [鋼琴 AI 自由意志] 7L 選擇保持專注安靜、無縫沉醉演奏《{song_title}》。")
                continue

            elif IS_PIANO_AUTO_RADIO_MODE:
                # 檢查 2：連續隨機電台模式：隊列空時，自動從種子曲庫/本機/BitMidi 隨機選曲並無縫接續演奏！
                await asyncio.sleep(1.2)  # 曲目間自然換氣微間隔
                if session_id != PIANO_SESSION_ID or not is_piano_active:
                    break
                
                # 隨機挑選一首不同於當前曲目的種子曲目（100% 動態從本地資料夾選取）
                local_seeds = get_local_piano_seeds()
                candidates = [s for s in local_seeds if s.lower() not in song_title.lower()]
                seed_song = random.choice(candidates if candidates else local_seeds)
                
                log_print(f"📻 [鋼琴電台] 正在自動隨機接續下一首：《{seed_song}》...")
                local_p, matched_title = await resolve_local_midi_file(seed_song)
                if not local_p:
                    # 本機沒有時，向 BitMidi 雲端搜尋並自動下載！
                    log_print(f"🌐 [鋼琴電台] 本機無《{seed_song}》，正在從 BitMidi 雲端曲庫下載五線譜...")
                    dl_p = await asyncio.to_thread(bitmidi_engine.fetch_and_download_first_match, seed_song, MIDI_SHEETS_DIR)
                    if not dl_p:
                        log_print(f"🎵 [鋼琴電台] BitMidi 無《{seed_song}》，改從 OnlineSequencer 搜尋...")
                        dl_p = await asyncio.to_thread(onlinesequencer_engine.fetch_and_download_first_match, seed_song, MIDI_SHEETS_DIR)
                    if dl_p and os.path.exists(dl_p):
                        local_p = dl_p
                        matched_title = os.path.basename(dl_p).replace('.mid', '').replace('.MID', '')
                        
                if local_p and os.path.exists(local_p):
                    song_title = matched_title or seed_song
                    midi_file = local_p
                    sheet_text = ""
                    current_piano_song_title = song_title
                    log_print(f"🎹 [鋼琴電台] 成功載入！開始連續演奏下一首名曲：《{song_title}》！")
                    # 🌟 100% 由 7L AI 自由意志自主決定是否開口搭話或專心安靜演奏 (完全告別死板數學機率)
                    radio_target = "audience" if get_current_speaking_target() == "audience" else "dad"
                    radio_user = "直播間觀眾與大家" if radio_target == "audience" else "老爸"
                    ai_chatter = await generate_dynamic_piano_chatter(song_title, target=radio_target, requester_name=radio_user, is_radio=True)
                    if ai_chatter:
                        log_print(f"💬 [電台 AI 自由意志發話 ({radio_target})]: {ai_chatter}")
                        await main_obj.speech_queue.put({"text": ai_chatter, "target": radio_target})
                    else:
                        log_print(f"🎹 [電台 AI 自由意志] 7L 選擇保持專注安靜、無縫沉醉演奏《{song_title}》。")
                    continue
                else:
                    break
            else:
                # 🌟 彈完單曲且無待播曲目時：鋼琴與 7L 保持常駐就緒待命，【絕對不重複重開視窗或重播舊曲】！
                # 只有當老爸說「收起鋼琴 / 別彈了」或調用 stop_virtual_piano() 時才會作為獨立動作收起！
                finished_song = song_title
                current_piano_song_title = ""
                try:
                    main_obj.append_to_unified_memory(speaker="系統", target="所有人", content=f"鋼琴《{finished_song}》演奏完畢，7L 坐在鋼琴前隨時待命", role="system", source="piano")
                except Exception:
                    pass
                log_print(f"🎹 [鋼琴舞台] 《{finished_song}》演奏完畢！7L 與鋼琴視窗保持常駐就緒待命（等待下一首點歌或「收起鋼琴」指令）。")
                await asyncio.to_thread(main_obj.update_subtitle, f"🎹 [7L 鋼琴就緒] 《{finished_song}》演奏完畢～隨時可點歌或說「收起鋼琴」")
                
                # 常駐等待老爸或觀眾點播新曲或下達收起鋼琴指令
                has_next = False
                while session_id == PIANO_SESSION_ID and is_piano_active:
                    if len(PIANO_REQUEST_QUEUE) > 0 or IS_PIANO_AUTO_RADIO_MODE:
                        has_next = True
                        break
                    await asyncio.sleep(0.3)
                
                if has_next:
                    continue
                else:
                    break
                    
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log_print(f"❌ [鋼琴演奏異常]: {e}")
    finally:
        if session_id == PIANO_SESSION_ID:
            is_piano_active = False
            current_piano_song_title = ""
            current_piano_midi_file = ""
            IS_PIANO_AUTO_RADIO_MODE = False
            if current_piano_process and current_piano_process.poll() is None:
                try:
                    current_piano_process.terminate()
                except Exception:
                    pass
                current_piano_process = None
            if SOUND_ENGINE:
                SOUND_ENGINE.all_notes_off()
            if vc.GLOBAL_VTS:
                await set_vts_expression(vc.GLOBAL_VTS, "_RESET_")
            if current_ai_state == "PIANO":
                current_ai_state = "IDLE"
            await asyncio.to_thread(main_obj.update_subtitle, "")
            log_print(f"🎹 [鋼琴舞台] 鋼琴演奏舞台結束，回到常規姿態！")

import bitmidi_engine
import onlinesequencer_engine
import pianist_midi_engine

async def play_virtual_piano(song_name: str = "", custom_sheet: str = "", auto_radio_mode: bool = False, midi_file: str = "", force_online: bool = False, requester_name: str = "", target: str = "", is_direct_song_name: bool = False) -> str:
    """讓 7L 在大家面前彈奏 88 鍵鋼琴名曲（支援單曲、多曲同時並發合奏、立即秒切新曲與無限隨機連續電台模式）。
    
    Args:
        song_name: 想點播的鋼琴曲名稱、作曲家或動漫名（如：'月光'、'鐘'、'La Campanella'、'愛之夢'、'冬風'、'少女的祈禱'、'幻想即興曲'、'卡農'、'給愛麗絲'、'神隱少女'）。支援多曲同時點播（如：'冬風、月光、鐘' 或 '冬風 x 月光'）。
        custom_sheet: (可選) 自訂備用樂譜。
        auto_radio_mode: (可選) 當說「接著一直隨便彈吧」、「隨便彈」、「隨機一直彈」、「連續彈」、「開啟鋼琴電台」時設為 True，進入無限連續隨機演奏模式，每首彈完自動隨機下載並接續彈奏下一首！
        midi_file: (可選) 直接指定的本機 MIDI 檔案完整路徑。
        force_online: (可選) 當指定「用 YouTube 查」、「youtuber 查」、「線上搜」、「yt 查」時設為 True，強制跳過本地樂譜直接向 YouTube/線上即時抓取！
        requester_name: (可選) 點播者稱呼（如：'老爸'、觀眾暱稱等）。
        target: (可選) 對象通道 ('dad' 或 'audience')。
        is_direct_song_name: (可選) 是否為明確傳入之曲名（如 Python 調用或預先判定為點歌），避免二次 AI 意圖檢測誤判為純對話。
    """
    global current_piano_task, PIANO_SESSION_ID, is_piano_active, current_piano_song_title, current_piano_midi_file, IS_PIANO_AUTO_RADIO_MODE, LAST_PIANO_PLAY_START_TIME, CURRENT_SPEAKING_TARGET, LAST_PIANO_OPEN_TIME
    LAST_PIANO_PLAY_START_TIME = time.time()
    LAST_PIANO_OPEN_TIME = time.time()
    init_piano_synthesizer()

    if not target:
        target = "audience" if get_current_speaking_target() == "audience" else "dad"
    if not requester_name:
        requester_name = "大家" if target == "audience" else "老爸"
    
    target_title = song_name if song_name else "鋼琴名曲"
    target_midi = midi_file if (midi_file and os.path.exists(midi_file)) else None
    save_persisted_piano_state(True, target_title, True)
    
    clean_q = song_name.strip() if song_name else ""
    
    # 🛡️ 雙大腦極速通道/主力競速防抖：若 6 秒內已經為同一個曲名發起過彈奏/搜譜，跳過延遲重複調用
    now_t = time.time()
    req_norm_key = clean_q.lower().strip()
    if req_norm_key and (now_t - LAST_PLAY_REQUEST_TIME.get(req_norm_key, 0) < 6.0) and is_piano_active:
        log_print(f"🛡️ [鋼琴重複請求防抖] 《{clean_q}》在 6 秒內剛由極速通道發起執行，忽略延遲重複調用！")
        return "[EXPRESSION: 星星眼]"
    if req_norm_key:
        LAST_PLAY_REQUEST_TIME[req_norm_key] = now_t
    
    # 🎬 【YouTube / 線上指定檢測】：若明確要求 YouTube / 線上查 ➔ 100% 絕對跳過本地匹配，強制走線上抓譜！
    is_explicit_yt = (
        force_online
        or any(k in clean_q.lower() for k in ["youtube", "youtuber", "yt", "yt查", "yt搜", "線上查", "線上搜", "從yt", "從youtube", "去yt", "去youtube", "網路搜", "線上找", "指定youtube", "指定youtuber"])
    )
    
    if is_explicit_yt:
        clean_search_target = re.sub(r'^(?:youtuber|youtube|yt|從yt|從youtube|去yt|去youtube)\s*(?:查|搜|找|搜尋|下載)?\s*', '', clean_q, flags=re.IGNORECASE).strip()
        clean_search_target = re.sub(r'\s*(?:然後彈|來彈|彈出來|放出來|彈一下|彈|播放|放)+$', '', clean_search_target, flags=re.IGNORECASE).strip()
        if not clean_search_target:
            clean_search_target = clean_q
            
        target_title = clean_search_target
        target_midi = None  # 100% 徹底清除本地 MIDI 指標，拒絕配對本地！
        log_print(f"🎬 [YouTube/線上專屬指定] 收到指定 YouTube 查譜《{clean_search_target}》，100% 跳過本地樂譜，強制線上搜尋並秒切演奏！")

    # 🧠 100% 交由 Gemini 高智商大腦判定意圖（完全零寫死關鍵字，交由 AI 自主分析語意與精準分流）
    ai_intent = {}
    available_files = [os.path.basename(p) for p in glob.glob(os.path.join(MIDI_SHEETS_DIR, "*.mid"))]
    if clean_q and not is_explicit_yt and not target_midi:
        ai_intent = await resolve_piano_intent_by_ai(
            clean_q, 
            available_files,
            current_playing_title=current_piano_song_title,
            current_playing_file=current_piano_midi_file,
            is_direct_song_name=is_direct_song_name
        )
        is_from_ai = ai_intent.get("_from_ai", False)
        is_song = ai_intent.get("is_song_request", False)
        action_type = ai_intent.get("action_type", "song_request" if is_song else "chat")

        # 🛑 若 Gemini 高智商大腦判定非點歌意圖（指令、視窗操作、問候閒聊等），100% 依據 AI 判斷執行精準分流：
        if is_from_ai and not is_song:
            if action_type == "open_piano":
                log_print(f"🎹 [Gemini 意圖分流] 判定《{clean_q}》為拿出/打開鋼琴指令，立即執行 open_virtual_piano()！")
                await open_virtual_piano()
                return "（系統回報：已交由 Gemini 識別為打開鋼琴指令，已為您拿出 88 鍵鋼琴待命）"
            elif action_type == "stop_piano":
                log_print(f"🛑 [Gemini 意圖分流] 判定《{clean_q}》為收起/停止彈琴指令，立即執行 stop_virtual_piano()！")
                await stop_virtual_piano()
                return "（系統回報：已交由 Gemini 識別為停止/收起鋼琴指令，已停止演奏並收起鋼琴）"
            elif action_type == "window_status":
                if is_piano_window_alive():
                    bring_piano_window_to_front()
                    log_print(f"🖥️ [Gemini 意圖分流] 判定《{clean_q}》為詢問鋼琴視窗狀態，已將視窗置頂最前端！")
                    return "（系統回報：已交由 Gemini 識別為鋼琴視窗狀態對話，視窗已置頂顯示，不執行新曲彈奏）"
                else:
                    log_print(f"🖥️ [Gemini 意圖分流] 判定《{clean_q}》為詢問鋼琴視窗狀態（目前視窗未開啟）！")
                    return "（系統回報：已交由 Gemini 識別為詢問鋼琴視窗，目前鋼琴尚未開啟）"
            elif not is_direct_song_name:
                log_print(f"🛑 [Gemini 意圖分流] 判定《{clean_q}》非點歌意圖（為日常閒聊、問候或非音樂指令），安全取消彈琴！")
                return "（系統回報：已交由 Gemini 識別為日常對話或非點歌發言，不執行彈琴，直接進行口頭對話）"
            else:
                # 傳入明確曲名 (is_direct_song_name=True) 但被大腦當作普通詞彙時，強制視為歌名繼續檢索
                ai_intent["song_title"] = clean_q
                ai_intent["is_song_request"] = True

        # 罕見離線/API全失效時的純數字/標點極簡兜底保護
        if not is_from_ai and (clean_q.isdigit() or re.fullmatch(r'[\d\s.,!?:;~～\-_+]+', clean_q)):
            log_print(f"🛑 [離線兜底防護] 《{clean_q}》為純數字/符號，取消彈琴！")
            return "（系統回報：純數字或標點非歌名，取消彈琴）"

        if ai_intent.get("song_title"):
            target_title = ai_intent.get("song_title")
        if ai_intent.get("matched_files"):
            cand_f = ai_intent["matched_files"][0]
            if is_midi_match_valid(clean_q, cand_f):
                target_midi = os.path.join(MIDI_SHEETS_DIR, cand_f)
            else:
                target_midi = None

    is_switch_version = ai_intent.get("is_switch_version", False)
    is_replay_command = ai_intent.get("is_replay", False)

    # 🛑 演奏中排隊接續機制：若目前已有曲目正在真實演奏中（非強制線上指定且非重播指令且非Gemini判定換版本指令）
    is_actively_playing_now = bool(
        is_piano_active 
        and is_piano_window_alive() 
        and (
            GLOBAL_PIANO_REALTIME_STATE.get("is_playing", False)
            or (current_piano_task is not None and not current_piano_task.done() and current_piano_song_title)
        )
    )
    if not is_explicit_yt and is_actively_playing_now and current_piano_song_title and not is_switch_version:
        bring_piano_window_to_front()
        clean_q_lower = clean_q.lower()
        current_title_lower = current_piano_song_title.lower()
        is_same_title = bool(clean_q and (clean_q_lower == current_title_lower or (len(clean_q_lower) >= 3 and clean_q_lower in current_title_lower)))
        if not is_replay_command and not is_same_title and clean_q:
            clean_target_song = clean_song_title_for_speech(ai_intent.get("song_title") or clean_q)
            
            # 防重複排隊檢查：若隊列中已預約此曲，更新點歌人（若有更具體名稱）並返回，不重複排入
            for it in PIANO_REQUEST_QUEUE:
                if it.get("title") == clean_target_song or (clean_target_song.lower() in it.get("title", "").lower()) or (it.get("title", "").lower() in clean_target_song.lower()):
                    if requester_name and requester_name not in ["老爸", "大家", "直播間觀眾"] and it.get("requester") in ["老爸", "大家", "直播間觀眾"]:
                        it["requester"] = requester_name
                        it["target"] = target
                    log_print(f"🎵 [鋼琴點歌排隊] 《{clean_target_song}》已在待播隊列中，不重複排入。")
                    return f"（系統提示：已為{requester_name}將《{clean_target_song}》排入下一首待播中！）"
            
            if clean_target_song.lower() in PENDING_PIANO_PRELOADS:
                log_print(f"🌐 [鋼琴點歌排隊] 《{clean_target_song}》正在線上搜尋下載中，不重複發起下載。")
                return f"（系統提示：已為{requester_name}將《{clean_target_song}》排入下一首待播中！）"

            # 1. 優先查本地精準同名或 Gemini 已匹配檔案
            norm_k = clean_target_song.lower().strip()
            exact_local = AUTHENTIC_MIDI_MAP.get(norm_k)
            req_midi = exact_local if (exact_local and os.path.exists(exact_local)) else None
            req_title = clean_song_title_for_speech(os.path.splitext(os.path.basename(exact_local))[0] if req_midi else clean_target_song)
            
            if not req_midi and ai_intent.get("matched_files"):
                cand_f = os.path.join(MIDI_SHEETS_DIR, ai_intent["matched_files"][0])
                if os.path.exists(cand_f) and is_midi_match_valid(clean_target_song, ai_intent["matched_files"][0]):
                    req_midi = cand_f
                    req_title = clean_song_title_for_speech(ai_intent.get("song_title") or os.path.splitext(ai_intent["matched_files"][0])[0])

            if not req_midi:
                local_p, matched_t = await resolve_local_midi_file(clean_target_song)
                if local_p and is_midi_match_valid(clean_target_song, os.path.basename(local_p)):
                    req_midi = local_p
                    req_title = clean_song_title_for_speech(matched_t or clean_target_song)
                    
            if req_midi and os.path.exists(req_midi):
                PIANO_REQUEST_QUEUE.append({"title": req_title, "midi_path": req_midi, "requester": requester_name, "target": target})
                log_print(f"🎵 [鋼琴點歌排隊] 成功預約《{req_title}》（來自 {requester_name}）排入下一首！（目前待播隊列中共 {len(PIANO_REQUEST_QUEUE)} 首）")
                return f"（系統提示：已成功為{requester_name}將《{req_title}》排入下一首待播！請用自然口語告知對方：『我現在正在彈《{clean_song_title_for_speech(current_piano_song_title)}》喔～等我這首彈完，下一首就幫你彈《{req_title}》！』）"
            else:
                # 🚀 異步背景預載並排入隊列，不阻塞工具調用回傳！
                search_q = ai_intent.get("search_online_query") or clean_target_song
                PENDING_PIANO_PRELOADS.add(clean_target_song.lower())
                async def preload_and_queue_worker(song_str: str, req_n: str, req_t: str, c_song: str):
                    try:
                        log_print(f"🌐 [點歌排隊線上搜譜] 正在異步背景搜尋預載《{song_str}》...")
                        dl_p = await asyncio.to_thread(pianist_midi_engine.fetch_and_download_pianist_match, song_str, MIDI_SHEETS_DIR)
                        if dl_p and os.path.exists(dl_p):
                            t_name = clean_song_title_for_speech(os.path.splitext(os.path.basename(dl_p))[0])
                            save_midi_catalog_entry(song_str, dl_p)
                            save_midi_catalog_entry(t_name, dl_p)
                            PIANO_REQUEST_QUEUE.append({"title": t_name, "midi_path": dl_p, "requester": req_n, "target": req_t})
                            log_print(f"🎵 [鋼琴點歌排隊] 成功預約《{t_name}》（來自 {req_n}）排入下一首！（目前待播隊列中共 {len(PIANO_REQUEST_QUEUE)} 首）")
                    finally:
                        PENDING_PIANO_PRELOADS.discard(c_song.lower())
                asyncio.create_task(preload_and_queue_worker(search_q, requester_name, target, clean_target_song))
                return f"（系統提示：已成功為{requester_name}將《{clean_target_song}》排入下一首待播！請用自然口語告知對方：『我現在正在彈《{clean_song_title_for_speech(current_piano_song_title)}》喔～等我這首彈完，下一首就幫你彈《{clean_target_song}》！』）"
        elif is_same_title and not is_replay_command:
            display_name = current_piano_song_title
            log_print(f"🎹 [7L 鋼琴曲庫] 7L 目前正在演奏《{display_name}》，保持沉醉演奏狀態，不重頭重播。")
            return "[EXPRESSION: 星星眼]"

    if not target_midi and not is_explicit_yt:
        # 1. 檢查是否為無限電台模式
        is_radio_req = auto_radio_mode or not clean_q or ai_intent.get("is_random", False)
        if is_radio_req:
            IS_PIANO_AUTO_RADIO_MODE = True
            log_print("📻 [鋼琴電台] 啟動無限連續隨機電台模式！")
        else:
            IS_PIANO_AUTO_RADIO_MODE = False
            # 2. 僅接受本地精確同名或別名比對
            norm_k = clean_q.lower().strip()
            exact_local_match = AUTHENTIC_MIDI_MAP.get(norm_k)
            if exact_local_match and os.path.exists(exact_local_match) and is_midi_match_valid(clean_q, os.path.basename(exact_local_match)):
                target_midi = exact_local_match
                target_title = os.path.splitext(os.path.basename(exact_local_match))[0]
                log_print(f"🎹 [本地精準命中] 命中已收錄曲目: 《{target_title}》 ({target_midi})")
            else:
                local_p, matched_t = await resolve_local_midi_file(clean_q)
                if local_p and os.path.exists(local_p) and is_midi_match_valid(clean_q, os.path.basename(local_p)):
                    target_midi = local_p
                    target_title = matched_t or os.path.splitext(os.path.basename(local_p))[0]
                    log_print(f"🎹 [本地智慧命中] 命中曲目: 《{target_title}》 ({target_midi})")

    if not target_midi and not is_explicit_yt:
        if not clean_q or IS_PIANO_AUTO_RADIO_MODE:
            preset_names = get_local_piano_seeds()
            if preset_names:
                target_title = random.choice(preset_names)
                target_midi, matched_title = await resolve_local_midi_file(target_title)
                if matched_title:
                    target_title = matched_title

    # 檢查鋼琴真實運行狀態 (避免背景任務已結束但狀態標記殘留)
    if is_piano_active and not is_piano_window_alive():
        if current_piano_task is None or current_piano_task.done():
            is_piano_active = False
            current_piano_song_title = ""
            current_piano_midi_file = ""

    # 🛑 演奏中不插歌/不切歌保護：若當前已經在演奏某首曲目且未收起鋼琴（且非強制線上指定）
    if not is_explicit_yt and is_actively_playing_now and current_piano_song_title:
        clean_q_lower = clean_q.lower() if clean_q else ""
        current_title_lower = current_piano_song_title.lower() if current_piano_song_title else ""
        same_midi = bool(target_midi and current_piano_midi_file and os.path.abspath(target_midi) == os.path.abspath(current_piano_midi_file))
        same_title = bool(clean_q and (clean_q_lower == current_title_lower or (len(clean_q_lower) >= 3 and clean_q_lower in current_title_lower)))
        same_target = bool(target_title and current_title_lower and target_title.lower() == current_title_lower)
        
        # 🌟 若 Gemini 判定為換版本 (is_switch_version) 且挑選出了不同檔案 ➔ 直接放行無縫切換！
        if is_switch_version and target_midi and (not current_piano_midi_file or os.path.abspath(target_midi) != os.path.abspath(current_piano_midi_file)):
            log_print(f"🎹 [Gemini 智能版本切換] Gemini 判定切換至不同版本: 《{target_title}》 ({os.path.basename(target_midi)})")
        elif (same_midi or same_title or same_target) and not is_replay_command:
            display_name = current_piano_song_title or target_title
            log_print(f"🎹 [7L 鋼琴曲庫] 7L 目前正在演奏《{display_name}》，保持沉醉演奏狀態，不重頭重播。")
            return "[EXPRESSION: 星星眼]"
        elif not is_replay_command and not is_switch_version:
            display_name = current_piano_song_title
            log_print(f"🛑 [鋼琴防插歌保護] 7L 目前正專注演奏《{display_name}》，拒絕中途插歌/切歌《{target_title}》！")
            return f"（系統提示：妳目前正坐在鋼琴前專心為大家彈奏《{display_name}》。請不要中途切歌或插歌，請用自然、隨性的口語直接告知對方：『我現在正在彈《{display_name}》呢～等我這首彈完再點歌喔！』）"

    # ⚡ 若已有本機 MIDI 樂譜 ➔ 100% 絕對即刻開彈！
    if target_midi and os.path.exists(target_midi):
        PIANO_SESSION_ID += 1
        session_id = PIANO_SESSION_ID
        is_piano_active = True
        current_piano_song_title = target_title
        current_piano_midi_file = target_midi
        try:
            main_obj.append_to_unified_memory(speaker="系統", target="所有人", content=f"鋼琴開始演奏《{target_title}》", role="system", source="piano")
        except Exception:
            pass
        
        if current_piano_task and not current_piano_task.done():
            current_piano_task.cancel()
            
        current_piano_task = asyncio.create_task(
            play_piano_worker(
                song_title=target_title,
                sheet_text=custom_sheet or "",
                bpm=180,
                mode="16th",
                midi_file=target_midi,
                session_id=session_id
            )
        )
        return "[EXPRESSION: 星星眼]"

    # 🌐 若指定 YouTube 或本地無樂譜 ➔ 啟動非阻塞背景線上抓譜並接續開彈協程
    PIANO_SESSION_ID += 1
    session_id = PIANO_SESSION_ID
    is_piano_active = True
    final_search_query = clean_search_target if is_explicit_yt else (clean_q or "鋼琴名曲")
    current_piano_song_title = final_search_query
    current_piano_midi_file = ""
    try:
        main_obj.append_to_unified_memory(speaker="系統", target="所有人", content=f"鋼琴準備線上搜尋演奏《{final_search_query}》", role="system", source="piano")
    except Exception:
        pass
    
    if current_piano_task and not current_piano_task.done():
        current_piano_task.cancel()

    async def async_fetch_and_play_worker(song_q: str, sid: int, c_sheet: str):
        global current_piano_song_title, current_piano_midi_file, is_piano_active
        log_print(f"🌐 [智慧曲庫搜尋] 正在線上/YouTube 搜尋《{song_q}》...")
        await move_vts_spatial(target_pos="鋼琴旁", duration=1.2)
        
        dl_path = await asyncio.to_thread(pianist_midi_engine.fetch_and_download_pianist_match, song_q, MIDI_SHEETS_DIR)
        
        if sid != PIANO_SESSION_ID or not is_piano_active:
            log_print(f"🛑 [線上抓譜] 演奏已取消或切換至新曲目，終止本次抓譜接續。")
            return
            
        if dl_path and os.path.exists(dl_path):
            t_title = os.path.splitext(os.path.basename(dl_path))[0]
            log_print(f"✅ [線上抓譜成功] 成功獲取: 《{t_title}》，立即啟動 88 鍵演奏！")
            save_midi_catalog_entry(song_q, dl_path)
            save_midi_catalog_entry(t_title, dl_path)
            current_piano_song_title = t_title
            current_piano_midi_file = dl_path
            await play_piano_worker(
                song_title=t_title,
                sheet_text=c_sheet or "",
                bpm=180,
                mode="16th",
                midi_file=dl_path,
                session_id=sid
            )
        else:
            log_print(f"⚠️ [7L 鋼琴曲庫] 未找到《{song_q}》的樂譜/演奏音訊。")
            is_piano_active = False
            current_piano_song_title = ""
            current_piano_midi_file = ""
            await asyncio.to_thread(main_obj.update_subtitle, f"⚠️ [樂譜庫查無結果] 未找到《{song_q}》的五線譜")

    current_piano_task = asyncio.create_task(async_fetch_and_play_worker(final_search_query, session_id, custom_sheet or ""))
    return "[EXPRESSION: 星星眼]"

def merge_two_midi_files(path1: str, path2: str, title1: str, title2: str) -> Tuple[str, str]:
    """將兩首鋼琴 MIDI 檔案深度融合，生成 88 鍵雙曲極限狂暴合奏 (Mashup) 樂譜"""
    try:
        import mido
        mid1 = mido.MidiFile(path1, clip=True)
        mid2 = mido.MidiFile(path2, clip=True)
        
        tpb = 480
        target_tempo = 400000  # 150 BPM 高能狂暴速度
        
        def extract_timed_events(mid_file):
            file_tpb = mid_file.ticks_per_beat
            events = []
            for track in mid_file.tracks:
                cur_tempo = 500000
                abs_sec = 0.0
                for msg in track:
                    if msg.time > 0:
                        abs_sec += mido.tick2second(msg.time, file_tpb, cur_tempo)
                    if msg.is_meta and msg.type == 'set_tempo':
                        cur_tempo = msg.tempo
                    if not msg.is_meta and msg.type in ['note_on', 'note_off', 'control_change', 'pitchwheel']:
                        events.append((abs_sec, msg.copy()))
            return events

        events1 = extract_timed_events(mid1)
        events2 = extract_timed_events(mid2)
        all_events = events1 + events2
        
        def event_sort_key(ev):
            t, m = ev
            priority = 0 if m.type == 'note_off' or (m.type == 'note_on' and m.velocity == 0) else 1
            return (t, priority)
            
        all_events.sort(key=event_sort_key)
        
        new_mid = mido.MidiFile(type=1, ticks_per_beat=tpb)
        
        # Track 0: Tempo
        tempo_track = mido.MidiTrack()
        new_mid.tracks.append(tempo_track)
        tempo_track.append(mido.MetaMessage('track_name', name='Mashup Tempo', time=0))
        tempo_track.append(mido.MetaMessage('set_tempo', tempo=target_tempo, time=0))
        tempo_track.append(mido.MetaMessage('end_of_track', time=0))
        
        # Track 1: Merged Notes
        merged_track = mido.MidiTrack()
        new_mid.tracks.append(merged_track)
        merged_track.append(mido.MetaMessage('track_name', name='Mashup Piano Track', time=0))
        merged_track.append(mido.Message('program_change', channel=0, program=0, time=0))
        
        last_tick = 0
        for t_sec, msg in all_events:
            cur_tick = mido.second2tick(t_sec, tpb, target_tempo)
            if cur_tick < last_tick:
                cur_tick = last_tick
            delta_tick = cur_tick - last_tick
            msg.time = delta_tick
            msg.channel = 0
            merged_track.append(msg)
            last_tick = cur_tick
            
        merged_track.append(mido.MetaMessage('end_of_track', time=0))
        
        safe_t1 = re.sub(r'[^\w]', '', title1)[:10] or "song1"
        safe_t2 = re.sub(r'[^\w]', '', title2)[:10] or "song2"
        mashup_filename = f"Mashup_{safe_t1}_x_{safe_t2}_{abs(hash(title1+title2))%10000}.mid"
        out_path = os.path.abspath(os.path.join(MIDI_SHEETS_DIR, mashup_filename))
        new_mid.save(out_path)
        mashup_title = f"{title1} x {title2} (神仙打架 Mashup)"
        save_midi_catalog_entry(mashup_title, out_path)
        save_midi_catalog_entry(f"{title1} {title2}", out_path)
        save_midi_catalog_entry(f"{title1} x {title2}", out_path)
        save_midi_catalog_entry(f"{title1}+{title2}", out_path)
        log_print(f"🔥 [雙曲合體] 成功生成雙曲融合 MIDI: 《{mashup_title}》 (時長: {new_mid.length:.1f}s | 檔案: {out_path})")
        return out_path, mashup_title
    except Exception as e:
        log_print(f"❌ [雙曲融合失敗]: {e}")
        return path1, title1




def extract_multi_songs_from_text(text: str) -> List[str]:
    """從自然語言字串中解析出多首歌曲名稱 (支援 2首、3首、4首甚至更多曲目同時合奏)"""
    if not text:
        return []
    clean = re.sub(r'^(同時彈|同時|請|幫我|把)', '', text).strip()
    clean = re.sub(r'(雜在一起|混在一起|合體|合在一起|一起彈|同時彈|同時|合奏|[兩三四五六七八九十\d]+首|彈)+$', '', clean).strip()
    # 按照常見連接詞與符號切分
    parts = re.split(r'[\s,，、+＋xX＆&和跟與加混雜]|還有|以及', clean)
    songs = [p.strip(' ：:()（）[]【】"\'') for p in parts if p.strip(' ：:()（）[]【】"\'')]
    filtered = []
    for s in songs:
        if s and s not in ['首', '歌', '曲', '鋼琴曲', '名曲', '兩首', '三首', '四首', '五首', '六首', '七首', '八首', '九首', '十首'] and s not in filtered:
            filtered.append(s)
    return filtered

async def mashup_virtual_piano(*songs, song_name1: str = "", song_name2: str = "", song_names: Optional[Union[List[str], str]] = None, ) -> str:
    """同時並發演奏多首高難度鋼琴曲 (無數量限制，即時多軌多色瀑布流並發演奏，絕不需死板生成單一檔案)"""
    # 1. 整理收集所有傳入的曲目名稱
    all_targets = []
    if song_names:
        if isinstance(song_names, list):
            for s in song_names:
                all_targets.extend(extract_multi_songs_from_text(str(s)) if any(k in str(s) for k in [",", "，", "、", " ", "+", "x", "跟", "和"]) else [str(s).strip()])
        elif isinstance(song_names, str):
            all_targets.extend(extract_multi_songs_from_text(song_names))
            
    for s in songs:
        if isinstance(s, list):
            for item in s:
                all_targets.extend(extract_multi_songs_from_text(str(item)) if any(k in str(item) for k in [",", "，", "、", " ", "+", "x", "跟", "和"]) else [str(item).strip()])
        elif isinstance(s, str):
            parsed = extract_multi_songs_from_text(s)
            if len(parsed) > 1:
                all_targets.extend(parsed)
            elif s.strip():
                all_targets.append(s.strip())
                
    if song_name1 and song_name1.strip():
        parsed1 = extract_multi_songs_from_text(song_name1)
        if len(parsed1) > 1:
            all_targets.extend(parsed1)
        else:
            all_targets.append(song_name1.strip())
            
    if song_name2 and song_name2.strip():
        parsed2 = extract_multi_songs_from_text(song_name2)
        if len(parsed2) > 1:
            all_targets.extend(parsed2)
        else:
            all_targets.append(song_name2.strip())
                
    # 去除重複與空白
    unique_targets = []
    for t in all_targets:
        if t and t not in unique_targets:
            unique_targets.append(t)
            
    # 🌟 若指令包含「全部 / 所有 / 全彈 / all / 整個曲庫」
    if any(k in "".join(unique_targets) for k in ["全部", "所有", "全都", "全彈", "all", "ALL", "全曲", "整個曲庫"]):
        real_all = []
        if os.path.exists(MIDI_SHEETS_DIR):
            for f in sorted(os.listdir(MIDI_SHEETS_DIR)):
                if f.lower().endswith(('.mid', '.midi')) and not f.lower().startswith(('test_', 'temp_')):
                    real_all.append(f)
        if real_all:
            unique_targets = real_all
            
    if len(unique_targets) < 2:
        if len(unique_targets) == 1:
            t1 = unique_targets[0]
            t2 = "鐘" if "冬風" in t1 else "冬風"
            unique_targets = [t1, t2]
        else:
            unique_targets = ["冬風", "鐘"]
            
    # 2. 為每一首曲目解析本機 MIDI 或從 BitMidi 自動下載
    resolved_tracks = []
    for s_name in unique_targets:
        p, t = await resolve_local_midi_file(s_name)
        if not p:
            dl = await asyncio.to_thread(onlinesequencer_engine.fetch_and_download_first_match, s_name, MIDI_SHEETS_DIR)
            if not dl:
                log_print(f"🎵 [多軌合奏] OnlineSequencer 無《{s_name}》，改從 BitMidi 搜尋...")
                dl = await asyncio.to_thread(bitmidi_engine.fetch_and_download_first_match, s_name, MIDI_SHEETS_DIR)
            if dl and os.path.exists(dl):
                p, t = dl, os.path.basename(dl).replace('.mid', '').replace('.MID', '')
        if p and os.path.exists(p):
            resolved_tracks.append({"title": t or s_name, "midi_path": p})
            
    if not resolved_tracks:
        return "（系統回報：未找到合奏樂譜檔案）"
        
    titles_list = [f"《{tr['title']}》" for tr in resolved_tracks]
    titles_display = " ✕ ".join(titles_list)
    multi_path_str = "|".join([tr['midi_path'] for tr in resolved_tracks])
    
    # 3. 確保 7L 走位到鋼琴旁
    await move_vts_spatial(target_pos="鋼琴旁", duration=1.2)
    
    # 4. 啟動或透過 IPC 發送多音軌即時並發演奏指令 (真正多音軌同時執行，無數量限制！)
    global current_piano_task, PIANO_SESSION_ID, is_piano_active, current_piano_song_title, current_piano_midi_file, current_piano_process, current_ai_state
    PIANO_SESSION_ID += 1
    session_id = PIANO_SESSION_ID
    is_piano_active = True
    current_piano_song_title = titles_display
    current_piano_midi_file = multi_path_str
    
    if is_piano_window_alive():
        log_print(f"🔥 [神仙打架多軌並發] 88 鍵鋼琴視窗已在桌面上，立即置頂並發送多軌並發指令: {titles_display} (共 {len(resolved_tracks)} 首曲目同時演奏)")
        bring_piano_window_to_front()
        send_piano_ipc_command({
            "cmd": "play_simultaneous",
            "tracks": resolved_tracks,
            "volume": GLOBAL_PIANO_VOLUME,
            "speed": GLOBAL_PIANO_SPEED
        })
    else:
        log_print(f"🔥 [神仙打架多軌並發] 啟動 88 鍵多軌並發鋼琴視窗: {titles_display} (共 {len(resolved_tracks)} 首曲目同時演奏)")
        piano_cmd = [
            sys.executable,
            get_piano_script_path(),
            "--multi-midi", multi_path_str,
            "--title", titles_display,
            "--volume", str(GLOBAL_PIANO_VOLUME),
            "--speed", str(GLOBAL_PIANO_SPEED),
            "--ndi"
        ]
        current_piano_process = subprocess.Popen(piano_cmd)
        
    if current_ai_state != "PIANO":
        current_ai_state = "PIANO"
        if vc.GLOBAL_VTS:
            asyncio.create_task(set_vts_expression(vc.GLOBAL_VTS, "星星眼"))
            
    await asyncio.to_thread(main_obj.update_subtitle, f"🎹 [7L 神仙打架合奏] {titles_display}")
    
    return "[EXPRESSION: 星星眼]"

async def insert_virtual_piano(song_name: str = "") -> str:
    """🛑 不插歌保護：當前開啟【彈完再點歌】模式，禁止演奏中途插歌或切換。"""
    display_title = current_piano_song_title or "這首曲子"
    log_print(f"🛑 [鋼琴防插歌保護] 收到插歌請求，但目前已開啟【彈完再點歌】保護，維持專注演奏《{display_title}》！")
    return f"（系統提示：7L 目前正坐在鋼琴前專心彈奏《{display_title}》，請不要中途插歌或切換。請用口語自然告知對方：『我現在正在彈《{display_title}》呢，等我這首彈完再點歌喔！』）"

async def compose_and_play_original_piano(theme_or_title: str = "", mood_or_style: str = "", requester_name: str = "", target: str = "") -> str:
    """7L 音樂自創大腦：現場自主作曲並壓制為標準雙手 MIDI 檔案，呼叫 88 鍵舞台即時演奏！"""
    global GEMINI_KEYS, CURRENT_GEMINI_KEY_STEP, CURRENT_SPEAKING_TARGET
    
    if not target:
        target = "audience" if get_current_speaking_target() == "audience" else "dad"
    if not requester_name:
        requester_name = "大家" if target == "audience" else "老爸"

    clean_theme = (theme_or_title or "即興心境").strip()
    clean_mood = (mood_or_style or "治癒抒情").strip()
    
    log_print(f"🎼 [7L AI 原創作曲] 啟動！主題:『{clean_theme}』 | 風格:『{clean_mood}』 | 對象:【{requester_name}】")
    
    prompt = f"""妳是 7L，也是一位極具靈性與音樂天賦的鋼琴家。
現在請妳為【{requester_name}】現場即興創作一首動聽的原創鋼琴曲！
創作主題：『{clean_theme}』
風格氛圍：『{clean_mood}』

請構思一個完整的鋼琴樂段（約 8~16 小節，4/4拍，包含雙手織體：右手主旋律 + 左手和弦分解或伴奏）。
請以嚴格的 JSON 格式輸出：
{{
  "title": "曲目名稱（富有詩意或貼近主題，如：7L的{clean_theme} 或 {clean_theme}）",
  "bpm": 100,
  "notes": [
    {{"pitch": 60, "start_beat": 0.0, "duration_beats": 1.0, "velocity": 80, "hand": "left"}},
    {{"pitch": 64, "start_beat": 0.0, "duration_beats": 1.0, "velocity": 75, "hand": "left"}},
    {{"pitch": 72, "start_beat": 0.0, "duration_beats": 0.5, "velocity": 90, "hand": "right"}},
    {{"pitch": 74, "start_beat": 0.5, "duration_beats": 0.5, "velocity": 85, "hand": "right"}}
  ]
}}

【樂理與音高規範】：
- 中央C (C4) = 60, D4 = 62, E4 = 64, F4 = 65, G4 = 67, A4 = 69, B4 = 71, C5 = 72
- 左手伴奏音區建議在 C3 (48) ~ G4 (67)
- 右手主旋律音區建議在 C4 (60) ~ C6 (84)
- 和弦進行必須和諧好聽（可運用流行王道進行 4-5-3-6、卡農進行、J-POP 抒情進行等）
- 請確保雙手音符數量豐富完整（至少 40 個音符事件以上），嚴禁空泛。"""

    created_song_title = f"7L原創_{clean_theme}"
    notes = []
    bpm = 100
    ticks_per_beat = 480

    try:
        active_keys = get_piano_gemini_keys()
        if active_keys:
            target_k_idx = (main_obj.get_pingpong_alternating_index(len(active_keys), CURRENT_GEMINI_KEY_STEP) if hasattr(main_obj, 'get_pingpong_alternating_index') and main_obj.get_pingpong_alternating_index else 0)
            client = genai.Client(api_key=active_keys[target_k_idx])
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.85,
                        response_mime_type="application/json",
                        max_output_tokens=2500
                    )
                ),
                timeout=6.0
            )
            if resp.text:
                try:
                    data = json.loads(resp.text)
                except Exception:
                    clean_j = re.sub(r'^```json\s*', '', resp.text.strip())
                    clean_j = re.sub(r'\s*```$', '', clean_j)
                    data = json.loads(clean_j)
                
                raw_t = data.get("title", clean_theme).strip()
                safe_t = re.sub(r'[\\/*?:"<>|]', '', raw_t)
                if not safe_t.startswith("7L原創"):
                    created_song_title = f"7L原創_{safe_t}"
                else:
                    created_song_title = safe_t
                    
                bpm = int(data.get("bpm", 100))
                notes = data.get("notes", [])
    except Exception as e:
        log_print(f"⚠️ [7L 原創作曲生成異常]: {e}")

    # 若 AI 未生成或逾時，啟動 7L 原創和弦進行保底引擎
    if not notes:
        log_print("🎵 [7L 作曲保底引擎] 使用 7L 經典 4536 王道進行生成即興鋼琴旋律...")
        bpm = 96
        # C大調 4-5-3-6 進行: F -> G -> Em -> Am
        progression = [
            [(53, 0.0, 2.0, 75), (57, 0.5, 1.5, 70), (60, 1.0, 1.0, 70), (65, 1.5, 0.5, 75),
             (69, 0.0, 1.0, 85), (72, 1.0, 0.5, 88), (74, 1.5, 0.5, 85)],
            [(55, 2.0, 2.0, 75), (59, 2.5, 1.5, 70), (62, 3.0, 1.0, 70), (67, 3.5, 0.5, 75),
             (76, 2.0, 1.0, 85), (74, 3.0, 0.5, 85), (72, 3.5, 0.5, 80)],
            [(52, 4.0, 2.0, 75), (55, 4.5, 1.5, 70), (59, 5.0, 1.0, 70), (64, 5.5, 0.5, 75),
             (71, 4.0, 1.0, 85), (69, 5.0, 0.5, 80), (67, 5.5, 0.5, 75)],
            [(45, 6.0, 2.0, 75), (48, 6.5, 1.5, 70), (52, 7.0, 1.0, 70), (57, 7.5, 0.5, 75),
             (64, 6.0, 1.5, 85), (60, 7.5, 0.5, 80)]
        ]
        notes = []
        for bar in progression:
            for p, sb, db, v in bar:
                notes.append({"pitch": p, "start_beat": sb, "duration_beats": db, "velocity": v})

    # 使用 mido 壓制為標準三軌樂隊 MIDI（主旋律 ch0 鋼琴＋貝斯 ch1＋鼓組 ch9）
    try:
        mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
        tempo = mido.bpm2tempo(bpm)

        def _mk_track(name, prog=None):
            t = mido.MidiTrack()
            t.append(mido.MetaMessage('track_name', name=name, time=0))
            t.append(mido.MetaMessage('set_tempo', tempo=tempo, time=0))
            if prog is not None:
                t.append(mido.Message('program_change', program=prog, channel=0, time=0))
            return t

        melody = _mk_track("7L Melody Piano", prog=0)
        bass = _mk_track("7L Bass", prog=33)
        drums = _mk_track("7L Drums")
        mid.tracks.extend([melody, bass, drums])

        def _fill(track, evs, channel):
            evs.sort(key=lambda x: (x[0], 0 if x[1] == 'note_off' else 1))
            cur = 0
            for tick, typ, pitch, vel in evs:
                delta = max(0, tick - cur)
                track.append(mido.Message(typ, note=pitch, velocity=vel, channel=channel, time=delta))
                cur = tick

        mel_evs, bass_evs, drum_evs = [], [], []
        total_beats = 0.0
        for n in notes:
            p = int(n.get("pitch", 60))
            sb = float(n.get("start_beat", 0.0))
            db = max(0.1, float(n.get("duration_beats", 1.0)))
            v = max(20, min(127, int(n.get("velocity", 80))))
            total_beats = max(total_beats, sb + db)
            hand = str(n.get("hand", "")).lower()
            if hand == "left" or (not hand and p < 60):
                p = max(28, min(67, p - 12))  # 貝斯下移八度
                mel_off = int(sb * ticks_per_beat)
                mel_end = int((sb + db) * ticks_per_beat)
                bass_evs.append((mel_off, 'note_on', p, v))
                bass_evs.append((mel_end, 'note_off', p, 0))
            else:
                p = max(21, min(108, p))  # 限制在 88 鍵範圍內
                mel_off = int(sb * ticks_per_beat)
                mel_end = int((sb + db) * ticks_per_beat)
                mel_evs.append((mel_off, 'note_on', p, v))
                mel_evs.append((mel_end, 'note_off', p, 0))
        # 自動鼓組：大鼓拍點＋軍鼓 2/4 拍＋踩鈸八分音符
        nbars = max(1, int((total_beats + 3.99) // 4))
        for bar in range(nbars):
            for beat in range(4):
                b0 = int((bar * 4 + beat) * ticks_per_beat)
                drum_evs.append((b0, 'note_on', 36, 100))
                drum_evs.append((b0 + 60, 'note_off', 36, 0))
                if beat in (1, 3):
                    drum_evs.append((b0, 'note_on', 38, 90))
                    drum_evs.append((b0 + 60, 'note_off', 38, 0))
                for half in range(2):
                    h0 = b0 + half * ticks_per_beat // 2
                    drum_evs.append((h0, 'note_on', 42, 60))
                    drum_evs.append((h0 + 30, 'note_off', 42, 0))
        _fill(melody, mel_evs, 0)
        _fill(bass, bass_evs, 1)
        _fill(drums, drum_evs, 9)

        out_midi_path = os.path.join(MIDI_SHEETS_DIR, f"{created_song_title}.mid")
        mid.save(out_midi_path)
        log_print(f"✨ [7L AI 原創作曲] 成功譜寫並存檔為 MIDI: 《{created_song_title}》 ({os.path.getsize(out_midi_path)} bytes)！")
        save_midi_catalog_entry(created_song_title, out_midi_path)

        # 呼叫 play_virtual_piano 立即送上 88 鍵舞台演奏！
        await play_virtual_piano(
            song_name=created_song_title,
            midi_file=out_midi_path,
            requester_name=requester_name,
            target=target
        )

        return f"（系統回報：7L 已現場構思並完成了原創鋼琴曲《{created_song_title}》（{clean_mood}風格），88 鍵鋼琴舞台已就緒開彈！請用自然口吻跟對方說：『這是我剛現場為你寫的原創曲《{created_song_title}》，聽聽看喜不喜歡喔！』）"

    except Exception as e:
        log_print(f"⚠️ [MIDI 檔案壓制異常]: {e}")
        return f"（系統回報：作曲檔案壓制失敗: {e}）"
