# -*- coding: utf-8 -*-
"""金鑰健康面板：每分鐘盤點 Gemini 金鑰／模型的冷卻與鎖定（CMA），寫狀態列、給 Discord 指令看。

主程式的狀態經 host.<名稱> 即時讀寫（host＝主程式模組，主程式 import 本檔後 bind()）。
用到的名稱列在 HOST_ATTRS，tests/test_workers_host.py 核對主程式真的都有定義。
"""
import asyncio
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import psutil

from core.llm_engine import API_LOCKS, GEMINI_KEYS, GEMINI_MODELS, is_locked, save_api_locks
from core.utils import get_current_time_string, log_swallowed

HOST_ATTRS = (
    "DATA_DIR",
    "current_ai_status_str",
)

host = None


def bind(main_module) -> None:
    global host
    host = main_module


async def cma_monitor_worker():
    """背景輪詢監控協程：負責維護 CMA 狀態面板並即時刷新 data/cma_status.txt"""
    
    try:
        with open(os.path.join(host.DATA_DIR, "cma_status.txt"), "w", encoding="utf-8") as f:
            f.write("==================================================\n")
            f.write(f"  7L CMA 監控面板初始化中... - {get_current_time_string()}\n")
            f.write("==================================================")
    except Exception:
        log_swallowed()

    while True:
        try:
            now = time.time()
            expired_keys = [k for k, lock_time in API_LOCKS.items() if now >= lock_time]
            if expired_keys:
                for k in expired_keys:
                    del API_LOCKS[k]
                save_api_locks()

            cma_lines = []
            cma_lines.append("==================================================")
            cma_lines.append(f"  7L CMA (Console Monitor Area) - {get_current_time_string()}")
            cma_lines.append("  當前運作模式:  正常全能模式 (Gemini 多模態/鋼琴/工具/視覺)")
            cma_lines.append("==================================================")
            
            cma_lines.append("--- 【Gemini 模型通道清單】 ---")
            avail_gemini = 0
            for g_model in GEMINI_MODELS:
                short_m = g_model.replace("gemini-", "")
                for idx, g_key in enumerate(GEMINI_KEYS):
                    target_id = f"G{idx}_{short_m}"
                    if is_locked(target_id):
                        rem = int(API_LOCKS[target_id] - now)
                        mins = rem // 60
                        secs = rem % 60
                        cma_lines.append(f"  [G{idx}] {short_m:<22} :  封印中 (剩餘 {mins}m {secs}s)")
                    else:
                        cma_lines.append(f"  [G{idx}] {short_m:<22} :  準備就緒")
                        avail_gemini += 1

            cma_lines.append("==================================================")
            
            status_data = {
                "timestamp": time.time(),
                "gemini_available": avail_gemini,
                "locks": {k: int(v - now) for k, v in API_LOCKS.items()}
            }
            
            try:
                with open(os.path.join(host.DATA_DIR, "cma_status.json"), "w", encoding="utf-8") as f:
                    json.dump(status_data, f, ensure_ascii=False, indent=2)
            except PermissionError:
                pass  
            
            try:
                with open(os.path.join(host.DATA_DIR, "cma_status.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(cma_lines))
            except PermissionError:
                pass  

            if not any(k in host.current_ai_status_str for k in ["思考中", "提取中", "探測中", "繪圖中"]):
                host.current_ai_status_str = f" 通道就緒 (Gemini:{avail_gemini})"
        except Exception:
            log_swallowed()
            
        await asyncio.sleep(1.0)


async def show_cma_panel(ctx, mode: str = "brief"):
    """ CMA (Console Monitor Area) - 顯示全線 API 健康狀態（支援 brief 精簡 / full 詳細）"""
    current_time = time.time()
    now_str = datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')
    
    total_gemini = len(GEMINI_MODELS) * len(GEMINI_KEYS)
    avail_gemini = 0
    locked_gemini = []
    gemini_details = []
    
    for g_model in GEMINI_MODELS:
        short_m = g_model.replace("gemini-", "")
        for idx, g_key in enumerate(GEMINI_KEYS):
            target_id = f"G{idx}_{short_m}"
            if target_id in API_LOCKS and current_time < API_LOCKS[target_id]:
                rem = int(API_LOCKS[target_id] - current_time)
                mins, secs = rem // 60, rem % 60
                locked_gemini.append(f"`{target_id}`:  封印中 ({mins}m {secs}s)")
                gemini_details.append(f"[{target_id:<20}] :  封印中 ({mins}m {secs}s)")
            else:
                avail_gemini += 1
                gemini_details.append(f"[{target_id:<20}] :  準備就緒")

    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        mem_percent = psutil.virtual_memory().percent
    except Exception:
        cpu_percent, mem_percent = 0, 0
    
    # 精簡摘要卡片
    gem_pct = (avail_gemini * 100 // total_gemini) if total_gemini else 0
    
    all_locked = locked_gemini
    if all_locked:
        locked_sample = all_locked[:6]
        locked_str = "\n".join([f"• {item}" for item in locked_sample])
        if len(all_locked) > 6:
            locked_str += f"\n• ...以及其餘 {len(all_locked) - 6} 條通道"
    else:
        locked_str = "•  全線綠燈，無任何通道處於封印狀態！"

    brief_card = (
        f" **【7L VAPI 系統健康監控 - 精簡摘要】**\n"
        f" 同步時間: `{now_str}`\n"
        f"────────────────────────────\n"
        f" **Gemini 視覺旗艦大腦**:  `{avail_gemini} / {total_gemini}` 準備就緒 ({gem_pct}%)\n"
        f" **本機硬體負載**: CPU `{cpu_percent}%` | RAM `{mem_percent}%`\n"
        f"────────────────────────────\n"
        f" **當前受限通道 ({len(all_locked)} 條)**:\n{locked_str}\n"
        f"────────────────────────────\n"
        f" *輸入 `*vapi full` 可匯出全部通道清單*"
    )
    
    await ctx.send(brief_card)

    if mode.lower() in ["full", "detail", "all", "verbose"]:
        categories = {"Gemini 視覺矩陣": gemini_details}
        for cat_name, cat_results in categories.items():
            if not cat_results: continue
            current_chunk = f"**--- 【{cat_name} (詳細清單)】 ---**\n```markdown\n"
            for row_text in cat_results:
                row = row_text + "\n"
                if len(current_chunk) + len(row) > 1850:
                    current_chunk += "```"
                    await ctx.send(current_chunk)
                    current_chunk = f"**--- 【{cat_name} (續)】 ---**\n```markdown\n" + row
                else:
                    current_chunk += row
            if current_chunk.strip() and not current_chunk.endswith("```"):
                current_chunk += "```"
                await ctx.send(current_chunk)
