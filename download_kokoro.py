import os
import urllib.request
import concurrent.futures

os.makedirs(r"c:\Users\qiwai\models\kokoro", exist_ok=True)

urls = [
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.1-zh.onnx",
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.1-zh.bin"
]

def download(url):
    filename = url.split('/')[-1]
    filepath = os.path.join(r"c:\Users\qiwai\models\kokoro", filename)
    print(f"Downloading {filename}...")
    try:
        urllib.request.urlretrieve(url, filepath)
        print(f"Successfully downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {filename}: {e}")

with concurrent.futures.ThreadPoolExecutor() as executor:
    executor.map(download, urls)
