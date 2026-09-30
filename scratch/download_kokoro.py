import os
import urllib.request

def download_file(url, dest_path):
    print(f"Downloading {url} to {dest_path}...")
    try:
        urllib.request.urlretrieve(url, dest_path)
        print("Download complete.")
    except Exception as e:
        print(f"Failed to download {url}: {e}")

def main():
    target_dir = r"C:\Users\qiwai\models\kokoro"
    os.makedirs(target_dir, exist_ok=True)

    # Repository: xun/kokoro-v1.1-zh-onnx
    base_url = "https://huggingface.co/xun/kokoro-v1.1-zh-onnx/resolve/main"
    
    files = [
        "kokoro-v1.1-zh.onnx",
        "voices-v1.1-zh.bin"
    ]
    
    for f in files:
        url = f"{base_url}/{f}"
        dest_path = os.path.join(target_dir, f)
        download_file(url, dest_path)

if __name__ == "__main__":
    main()
