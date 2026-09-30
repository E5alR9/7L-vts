import os
from huggingface_hub import HfApi, hf_hub_download

api = HfApi()

repos = [
    "onnx-community/Kokoro-82M-v1.1-zh-ONNX",
    "hexgrad/Kokoro-82M-v1.1-zh",
    "hexgrad/Kokoro-82M",
    "onnx-community/Kokoro-82M-ONNX"
]

for repo in repos:
    try:
        print(f"\n--- Files in {repo} ---")
        files = api.list_repo_files(repo)
        for f in files:
            if f.endswith('.onnx') or f.endswith('.bin'):
                print(f)
    except Exception as e:
        print(f"Repo {repo} not found: {e}")
