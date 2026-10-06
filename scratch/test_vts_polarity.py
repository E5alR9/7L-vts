import asyncio
import pyvts
import time

async def main():
    print("🔌 正在連接 VTube Studio...")
    plugin_info = {
        "plugin_name": "7L_Polarity_Tester",
        "developer": "e5_Studio",
        "authentication_token_path": "./vts_token_test.txt"
    }
    vts = pyvts.vts(plugin_info=plugin_info)
    
    try:
        await vts.connect()
        print("✅ 連線成功！")
        
        await vts.request_authenticate_token()
        await vts.request_authenticate()
        print("✅ 認證成功！")
    except Exception as e:
        print(f"❌ 連線失敗: {e}")
        return

    def build_inject_req(param_id, value):
        return {
            "apiName": "VTubeStudioPublicAPI", 
            "apiVersion": "1.0", 
            "requestID": "PolarityTest",
            "messageType": "InjectParameterDataRequest",
            "data": {
                "faceFound": True,
                "mode": "set",
                "parameterValues": [
                    {"id": param_id, "value": value, "weight": 1.0}
                ]
            }
        }

    print("\n=========================================")
    print("🔍 [測試 1/3] 測試「頭部 X 軸 (FaceAngleX)」")
    print("=========================================")
    
    # 測試頭部
    print("👉 傳送 FaceAngleX = +30 (正值) ... 請觀察 7L 的頭轉向哪邊？")
    await vts.request(build_inject_req("FaceAngleX", 30.0))
    await asyncio.sleep(3)

    print("👉 傳送 FaceAngleX = -30 (負值) ... 請觀察 7L 的頭轉向哪邊？")
    await vts.request(build_inject_req("FaceAngleX", -30.0))
    await asyncio.sleep(3)

    print("\n=========================================")
    print("🔍 [測試 2/3] 測試「眼球 X 軸 (EyeLeftX / EyeRightX)」")
    print("=========================================")
    
    # 測試眼球
    print("👉 傳送 EyeLeftX/RightX = +1.0 (正值) ... 請觀察 7L 的眼球轉向哪邊？")
    for _ in range(5):  # 延長注入時間，避免被 Live2D 預設物理蓋掉
        await vts.request(build_inject_req("EyeLeftX", 1.0))
        await vts.request(build_inject_req("EyeRightX", 1.0))
        await asyncio.sleep(0.5)

    print("👉 傳送 EyeLeftX/RightX = -1.0 (負值) ... 請觀察 7L 的眼球轉向哪邊？")
    for _ in range(5):
        await vts.request(build_inject_req("EyeLeftX", -1.0))
        await vts.request(build_inject_req("EyeRightX", -1.0))
        await asyncio.sleep(0.5)

    print("\n=========================================")
    print("🔍 [測試 3/3] 復原狀態")
    print("=========================================")
    await vts.request(build_inject_req("FaceAngleX", 0.0))
    await vts.request(build_inject_req("EyeLeftX", 0.0))
    await vts.request(build_inject_req("EyeRightX", 0.0))
    
    print("✅ 測試完成！請關閉此腳本。")
    await vts.close()

if __name__ == "__main__":
    asyncio.run(main())
