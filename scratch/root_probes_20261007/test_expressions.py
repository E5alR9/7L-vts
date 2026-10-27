import asyncio
import time
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import services.vts_client as vc
from services.vts_client import RobustVTSClient

async def main():
    print("🚀 啟動表情與實體動作雙重觸發 真實連線測試...")
    
    # 建立與 VTube Studio 的真實連線
    plugin_info = {"plugin_name": "7L_AI_VTuber", "developer": "e5_Studio", "authentication_token_path": "./vts_token.txt"}
    vts = RobustVTSClient(plugin_info=plugin_info)
    vc.GLOBAL_VTS = vts
    
    print("正在連線至 VTube Studio (Port 8001)...")
    try:
        await vts.connect(retries=1, retry_delay=1.0)
        await vts.read_token()
        if not vts.authentic_token:
            await vts.request_authenticate_token()
            await vts.write_token()
        await vts.request_authenticate()
        print("✅ 成功連接並驗證 VTube Studio！\n")
    except Exception as e:
        print(f"❌ 無法連線至 VTube Studio: {e}")
        print("請確保 VTube Studio 正在執行並已開啟 API 功能。")
        return

    # 先還原預設
    await vc.set_vts_expression(vts, "_RESET_")
    await asyncio.sleep(2.0)
    
    # 網羅所有主要表情分類與實體動作的完整測試清單
    test_cases = [
        "愛心", "星星眼", "臉紅", "委屈", "生氣", "黑化", 
        "無語", "暈暈", "著急", "吐舌", "比心", "花花", 
        "問號", "麥克風", "打遊戲", "雙馬尾", "右抬手", "左抬手",
        "翻白眼", "震驚", "WINK", "_RESET_"
    ]
    
    for exp in test_cases:
        print(f"\n--- 測試 [EXPRESSION: {exp}] ---")
        
        # 紀錄觸發前的計時器狀態
        before_frown = vc.frown_timer
        before_roll = vc.eye_roll_timer
        before_shock = vc.shock_timer
        before_wink = vc.wink_timer
        
        # 觸發真實連線
        await vc.set_vts_expression(vts, exp)
        
        # 驗證表情檔是否正確掛上
        print(f"👉 綁定的表情檔 (CURRENT_ACTIVE_EXP): {vc.CURRENT_ACTIVE_EXP}")
        
        # 驗證實體參數是否正確設定
        if vc.frown_timer > before_frown:
            print(f"👉 實體動作: [八字眉/委屈] 已啟用 (計時器設定為未來 {(vc.frown_timer - time.time()):.1f} 秒)")
        if vc.eye_roll_timer > before_roll:
            print(f"👉 實體動作: [翻白眼] 已啟用 (計時器設定為未來 {(vc.eye_roll_timer - time.time()):.1f} 秒)")
        if vc.shock_timer > before_shock:
            print(f"👉 實體動作: [震驚縮瞳] 已啟用 (計時器設定為未來 {(vc.shock_timer - time.time()):.1f} 秒)")
        if vc.wink_timer > before_wink:
            print(f"👉 實體動作: [WINK] 已啟用 (方向: {vc.wink_side}, 計時器設定為未來 {(vc.wink_timer - time.time()):.1f} 秒)")

        print("⏳ 觀察模型變化 3 秒...")
        await asyncio.sleep(3.0)

if __name__ == "__main__":
    asyncio.run(main())
