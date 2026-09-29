# -*- coding: utf-8 -*-
"""
🎭 模式裝配宣告（modes/workers）：MODE=companion|vtuber 裝哪些 worker 的唯一真相來源。

- COMMON：兩模式都裝（大腦／軌道／記憶／語音／MIDI 樂隊／點播台）
- COMPANION_ONLY：伴侶專屬（操作者通道／感知／陪伴／Discord／休眠）
- VTUBER_ONLY：主播專屬（目前為空集合＋行為禁令：禁休眠／禁感知／禁私聊）
- vts_7L_test.py 啟動裝配必須與本表一致（tests/test_modes.py 鎖死同步）。
"""
COMMON = [
    "tts_prewarm", "mic_volume_meter",
    "chat_processor", "streamer_mind_loop", "background_mind_stream",
    "anti_watermark", "cma_monitor", "speech_queue",
    "expression_keeper", "autonomous_wander",
    "piano_focus_udp", "piano_liveness_watchdog", "piano_auto_restore",
    "tiktok_live", "twitch_live", "youtube_live",
    "video_watch", "live_timer_sensor", "vts_health",
]

COMPANION_ONLY = [
    "mic_worker", "text_file_listener", "console_keyboard",
    "screen_capture", "peripheral_vision", "system_audio", "proactive",
    "discord_runner", "sleep_mode",
]

VTUBER_ONLY = []  # 主播無專屬 worker，只有禁令（見 VTUBER_BANS）

VTUBER_BANS = [
    "sleep_mode", "screen_capture", "peripheral_vision", "system_audio",
    "proactive", "discord_runner", "yt_watcher", "operator_private_reply",
]


def plan(mode: str) -> dict:
    """回傳該模式的裝配清單（純函式，可測）。"""
    m = (mode or "vtuber").strip().lower()
    if m not in ("companion", "vtuber"):
        m = "vtuber"
    workers = list(COMMON)
    bans = []
    if m == "companion":
        workers += COMPANION_ONLY
    else:
        bans = list(VTUBER_BANS)
    return {"mode": m, "workers": workers, "bans": bans}


def describe() -> str:
    lines = ["# 模式裝配（modes/workers.py 自動產生）", ""]
    for m in ("companion", "vtuber"):
        p = plan(m)
        lines.append(f"## {m}（{len(p['workers'])} workers）")
        lines.append("- " + "\n- ".join(p["workers"]))
        if p["bans"]:
            lines.append("")
            lines.append("禁令： " + "、".join(p["bans"]))
        lines.append("")
    return "\n".join(lines)
