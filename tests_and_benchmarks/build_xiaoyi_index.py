import os
import glob
import io
import wave
import subprocess
import torch
import faiss
import numpy as np
from transformers import HubertModel

def main():
    print("🚀 [Xiaoyi 聲線特徵工程] 正在從 48 條訓練集提取 768 維聲帶音色特徵...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"使用計算設備: {device} ({torch.cuda.get_device_name(0) if device == 'cuda' else 'CPU'})")

    model = HubertModel.from_pretrained("facebook/hubert-base-ls960").to(device)
    model.eval()

    wav_files = glob.glob("dataset/xiaoyi_7L/wavs/*.wav")
    print(f"找到 {len(wav_files)} 條訓練語音檔，開始進行神經特徵萃取...")

    all_features = []

    with torch.no_grad():
        for idx, f in enumerate(wav_files):
            cmd = [
                r"C:\ffmpeg\bin\ffmpeg.exe", "-y",
                "-i", f,
                "-ar", "16000",
                "-ac", "1",
                "-f", "wav",
                "pipe:1"
            ]
            proc = subprocess.run(cmd, capture_output=True)
            with wave.open(io.BytesIO(proc.stdout), "rb") as w:
                frames = w.readframes(w.getnframes())
                data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

            audio_tensor = torch.tensor(data, dtype=torch.float32, device=device).unsqueeze(0)
            outputs = model(audio_tensor)
            feats = outputs.last_hidden_state.squeeze(0).cpu().numpy()
            all_features.append(feats)
            if (idx + 1) % 10 == 0 or (idx + 1) == len(wav_files):
                print(f"[{idx+1}/{len(wav_files)}] 聲線特徵幀已提取完成...")

    all_features = np.concatenate(all_features, axis=0)
    print(f"✨ 萃取完成！總共獲得 {all_features.shape[0]} 組 Xiaoyi 聲帶頻譜特徵向量 (維度: {all_features.shape[1]})")

    # 建立 Faiss Index
    index = faiss.IndexFlatL2(all_features.shape[1])
    index.add(all_features.astype(np.float32))
    out_index = "dataset/xiaoyi_7L/xiaoyi_7L.index"
    faiss.write_index(index, out_index)
    print(f"🎉 [特徵庫建立成功] Xiaoyi 專屬聲線索引檔案已生成: {out_index} (總索引量: {index.ntotal})")

if __name__ == "__main__":
    main()
