import os
import shutil
from huggingface_hub import hf_hub_download

def main():
    target_dir = r"C:\Users\qiwai\models\kokoro"
    os.makedirs(target_dir, exist_ok=True)
    
    print("Downloading ONNX model...")
    model_path = hf_hub_download(
        repo_id="onnx-community/Kokoro-82M-v1.1-zh-ONNX", 
        filename="onnx/model.onnx"
    )
    
    print("Downloading voice zf_001 (Default Chinese Female)...")
    voice_path = hf_hub_download(
        repo_id="onnx-community/Kokoro-82M-v1.1-zh-ONNX", 
        filename="voices/zf_001.bin"
    )
    
    # Copy to target dir with correct names
    final_model = os.path.join(target_dir, "kokoro-v1.1-zh.onnx")
    final_voice = os.path.join(target_dir, "voices-v1.1-zh.bin")
    
    print(f"Copying to {final_model}")
    shutil.copyfile(model_path, final_model)
    
    print(f"Copying to {final_voice}")
    shutil.copyfile(voice_path, final_voice)
    
    print("All downloads and setup complete!")

if __name__ == "__main__":
    main()
