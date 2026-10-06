import os
import sys
import asyncio
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services.tts_router as tts_router

async def generate_screams():
    sounds_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sounds_7L_clean")
    shocks_light_dir = os.path.join(sounds_dir, "shocks_light")
    shocks_heavy_dir = os.path.join(sounds_dir, "shocks_heavy")
    
    # 確保資料夾存在
    os.makedirs(shocks_light_dir, exist_ok=True)
    os.makedirs(shocks_heavy_dir, exist_ok=True)
    
    # 刪除舊的 MP3 檔 (避免混用舊聲帶)
    for old_file in glob.glob(os.path.join(shocks_light_dir, "*.mp3")) + glob.glob(os.path.join(shocks_heavy_dir, "*.mp3")):
        try:
            os.remove(old_file)
            print(f"🗑️ 已刪除舊音效: {os.path.basename(old_file)}")
        except:
            pass

    # 設定新的尖叫台詞 (老爸要求純叫聲，不要參雜文字對話)
    light_texts = [
        "啊啊啊！",
        "嗚哇！",
        "呀啊！",
        "咿呀！",
        "噫！"
    ]
    
    heavy_texts = [
        "啊啊啊啊啊啊！",
        "嗚啊啊啊啊！",
        "呀啊啊啊啊啊！",
        "嗚哇啊啊啊啊！",
        "咿呀啊啊啊啊！"
    ]
    
    print("🚀 正在載入本地 GPT-SoVITS 曉伊神經語音引擎...")
    import local_xiaoyi_service as local_xiaoyi
    local_xiaoyi.init_gpt_sovits()
    
    print("🚀 開始使用最新 7L (Xiaoyi) 引擎生成 [微電] 叫聲...")
    for i, text in enumerate(light_texts):
        print(f"  [{i+1}/{len(light_texts)}] 正在合成: {text}")
        audio_bytes = await tts_router.get_tts_audio_bytes(text)
        if audio_bytes:
            out_path = os.path.join(shocks_light_dir, f"new_light_{i}.wav")
            with open(out_path, "wb") as f:
                f.write(bytes(audio_bytes))
            print(f"    ✅ 已儲存至 {out_path}")

    print("🚀 開始使用最新 7L (Xiaoyi) 引擎生成 [重電] 叫聲...")
    for i, text in enumerate(heavy_texts):
        print(f"  [{i+1}/{len(heavy_texts)}] 正在合成: {text}")
        audio_bytes = await tts_router.get_tts_audio_bytes(text)
        if audio_bytes:
            out_path = os.path.join(shocks_heavy_dir, f"new_heavy_{i}.wav")
            with open(out_path, "wb") as f:
                f.write(bytes(audio_bytes))
            print(f"    ✅ 已儲存至 {out_path}")
            
    print("🎉 所有尖叫聲已成功更新為最新聲帶版本！")

if __name__ == "__main__":
    asyncio.run(generate_screams())
