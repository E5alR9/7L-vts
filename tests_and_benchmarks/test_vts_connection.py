import os
import sys
import asyncio
import pyvts

# Set UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

async def test_vts():
    print("=" * 60)
    print("🔍 【VTube Studio 連線與模型控制診斷測試】")
    print("=" * 60)
    
    plugin_info = {
        "plugin_name": "7L_AI_VTuber",
        "developer": "e5_Studio",
        "authentication_token_path": "./vts_token.txt"
    }
    
    vts = pyvts.vts(plugin_info=plugin_info)
    
    print("\n1. 正在嘗試連線至 VTube Studio API (ws://127.0.0.1:8001)...")
    try:
        await vts.connect()
        print("   ✅ WebSocket 成功連線！VTube Studio 正在運行。")
    except Exception as e:
        print(f"   ❌ 連線失敗: {e}")
        print("\n💡 診斷建議：")
        print("   1. 請確認 VTube Studio 軟體是否有開啟？")
        print("   2. 請進入 VTS 設定 ➔ 齒輪圖示 ➔ 往下拉找到「開啟 API (Start API)」是否已勾選開啟？")
        print("   3. 確認 Port 是否為預設的 8001。")
        return

    print("\n2. 正在檢查/讀取 Token 驗證狀態...")
    try:
        await vts.read_token()
        if not vts.authentic_token:
            print("   ⚠️ 本地尚未儲存授權 Token，正在向 VTS 請求彈出視窗授權...")
            print("   👉 請查看 VTS 畫面是否有彈出「Allow 7L_AI_VTuber to access VTS?」，請點擊 Allow！")
            await vts.request_authenticate_token()
            await vts.write_token()
            print("   ✅ 已成功取得並保存 Token！")
        else:
            print(f"   ✅ 已讀取到本地 Token ({vts.authentic_token[:10]}...)")
            
        await vts.request_authenticate()
        print("   ✅ VTube Studio API 認證成功！")
    except Exception as e:
        print(f"   ❌ 認證失敗: {e}")
        print("   👉 請刪除 ./vts_token.txt 並重試，讓 VTS 重新彈出授權視窗。")
        return

    print("\n3. 正在查詢當前加載的 Live2D 模型資訊...")
    try:
        resp = await vts.request({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "GetModelInfoReq",
            "messageType": "CurrentModelRequest"
        })
        model_data = resp.get("data", {})
        model_loaded = model_data.get("modelLoaded", False)
        model_name = model_data.get("modelName", "None")
        model_pos = model_data.get("modelPosition", {})
        
        if model_loaded:
            print(f"   ✅ 成功讀取到模型：【{model_name}】")
            print(f"   📍 當前模型座標: X={model_pos.get('positionX')}, Y={model_pos.get('positionY')}, Size={model_pos.get('size')}")
        else:
            print("   ⚠️ VTube Studio 目前尚未加載任何 Live2D 模型！請在 VTS 中載入 7L 模型。")
    except Exception as e:
        print(f"   ❌ 讀取模型資訊失敗: {e}")

    print("\n4. 正在測試模型表情清單...")
    try:
        exp_resp = await vts.request({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "GetExpListReq",
            "messageType": "ExpressionStateRequest"
        })
        exps = exp_resp.get("data", {}).get("expressions", [])
        print(f"   ✅ 成功讀取到 {len(exps)} 個表情檔:")
        for exp in exps[:6]:
            print(f"      • {exp.get('name')} ({exp.get('file')}) [狀態: {'開啟' if exp.get('active') else '關閉'}]")
    except Exception as e:
        print(f"   ⚠️ 讀取表情清單失敗: {e}")

    print("\n5. 正在測試微調模型走位 (平移 0.05 再復原)...")
    try:
        if model_loaded and model_pos:
            orig_x = model_pos.get('positionX', 0)
            orig_y = model_pos.get('positionY', 0)
            orig_sz = model_pos.get('size', 0)
            
            # 微移動
            await vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "MoveModelReq1",
                "messageType": "MoveModelRequest",
                "data": {
                    "timeInSeconds": 0.5,
                    "valuesAreRelativeToModel": False,
                    "positionX": orig_x + 0.05,
                    "positionY": orig_y,
                    "size": orig_sz
                }
            })
            print("   ✅ 模型成功向右微移！")
            await asyncio.sleep(0.6)
            
            # 復原
            await vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "MoveModelReq2",
                "messageType": "MoveModelRequest",
                "data": {
                    "timeInSeconds": 0.5,
                    "valuesAreRelativeToModel": False,
                    "positionX": orig_x,
                    "positionY": orig_y,
                    "size": orig_sz
                }
            })
            print("   ✅ 模型已成功復原位置！")
    except Exception as e:
        print(f"   ❌ 移動控制失敗: {e}")

    print("\n" + "=" * 60)
    print("🎉 【診斷完成】連線與控制一切正常！")
    print("=" * 60)
    await vts.close()

if __name__ == "__main__":
    asyncio.run(test_vts())
