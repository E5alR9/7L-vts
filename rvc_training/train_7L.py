"""
RVC v2 一鍵訓練腳本 — 7L 歌聲模型
====================================
策略：直接使用 songs_library/cover_cache/ 中已分離的 68 首歌唱人聲
      (~120 分鐘素材)，遠超 20 分鐘最低需求。

流程：
  Step 0. 複製歌唱素材 -> rvc_training/dataset_7L_singing/
  Step 1. Preprocess   (切片 + 重採樣)
  Step 2. Extract F0   (RMVPE)
  Step 3. Extract HuBERT features
  Step 4. Train index  (FAISS)
  Step 5. Train model
"""
import os, sys, glob, shutil, subprocess, multiprocessing, time

RVC_ROOT   = r"C:\Users\qiwai\RVC-WebUI"
VENV_PY    = os.path.join(RVC_ROOT, ".venv", "Scripts", "python.exe")
VOCAL_SRC  = r"C:\Users\qiwai\songs_library\cover_cache"
DATASET    = os.path.join(RVC_ROOT, "datasets", "7L_singing")
EXP_NAME   = "7L_v2"
EXP_DIR    = os.path.join(RVC_ROOT, "logs", EXP_NAME)
INDEX_ROOT = os.path.join(RVC_ROOT, "logs")
SR         = 48000
VERSION    = "v2"
N_CPU      = max(1, multiprocessing.cpu_count() - 2)
IS_HALF    = "True"
TOTAL_EPOCHS  = 300
SAVE_EVERY    = 50
BATCH_SIZE    = 8

def run(cmd, desc="", check=True):
    print(f"\n{'='*60}\n{desc}\n{'='*60}")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=RVC_ROOT)
    elapsed = time.time() - t0
    if check and r.returncode != 0:
        print(f"FAILED! code={r.returncode}")
        sys.exit(1)
    print(f"Done in {elapsed/60:.1f} min")
    return r

def step0_collect():
    print("\nStep 0 collecting vocal WAVs...")
    os.makedirs(DATASET, exist_ok=True)
    os.makedirs(EXP_DIR, exist_ok=True)
    wavs = sorted(glob.glob(os.path.join(VOCAL_SRC, "*_7l_vocal.wav")))
    copied = sum(1 for s in wavs if not os.path.exists(os.path.join(DATASET, os.path.basename(s))) and not shutil.copy2(s, os.path.join(DATASET, os.path.basename(s))))
    print(f"Done. {len(wavs)} wavs available in {DATASET}")

def step1_preprocess():
    run([VENV_PY, "train/preprocess.py", DATASET, str(SR), str(N_CPU), EXP_DIR, "False", "3.7"], "Step 1 Preprocess")

def step2_f0():
    run([VENV_PY, "train/dataset/extract_f0.py", "cuda", "1", "0", "0", EXP_DIR, IS_HALF], "Step 2 Extract F0 RMVPE")

def step3_hubert():
    run([VENV_PY, "train/dataset/extract_hubert_feature.py", "cuda", "1", "0", "0", EXP_DIR, VERSION, IS_HALF], "Step 3 Extract HuBERT")

def step4_index():
    run([VENV_PY, "train/train_index.py", EXP_NAME, VERSION, INDEX_ROOT, str(N_CPU), "auto"], "Step 4 Train FAISS index")

def step5_train():
    run([VENV_PY, "train/train.py", "-e", EXP_NAME, "-sr", str(SR), "-f0", "1", "-bs", str(BATCH_SIZE), "-g", "0", "-te", str(TOTAL_EPOCHS), "-se", str(SAVE_EVERY), "-v", VERSION, "-l", "0", "-c", "0", "-sw", "0", "-t", "0"], "Step 5 Train model", check=False)

if __name__ == "__main__":
    print(f"RVC 7L v2 Training | GPU=RTX3080Ti | {TOTAL_EPOCHS} epochs | batch={BATCH_SIZE}")
    step0_collect()
    step1_preprocess()
    step2_f0()
    step3_hubert()
    step4_index()
    step5_train()
    print("DONE! Check:", EXP_DIR)
