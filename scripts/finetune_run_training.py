# -*- coding: utf-8 -*-
"""
GPT-SoVITS incremental fine-tune pipeline runner
Runs: feature extraction -> s2 train (SoVITS) -> s1 train (GPT T2S)
"""

import os, sys, subprocess, shutil

# ── 路徑設定 ────────────────────────────────────────────────
GPT_SOVITS_DIR  = r"C:\Users\qiwai\GPT-SoVITS"
CORE_DIR        = os.path.join(GPT_SOVITS_DIR, "GPT_SoVITS")
PRETRAIN_DIR    = os.path.join(GPT_SOVITS_DIR, "pretrained_models")

DATA_DIR        = r"C:\Users\qiwai\finetune_data"
WAV_DIR         = os.path.join(DATA_DIR, "wavs")
LIST_FILE       = os.path.join(DATA_DIR, "train.list")
EXP_NAME        = "xiaoyi_finetune"
OPT_DIR         = os.path.join(DATA_DIR, "opt", EXP_NAME)

BERT_DIR        = os.path.join(PRETRAIN_DIR, "chinese-roberta-wwm-ext-large")
HUBERT_DIR      = os.path.join(PRETRAIN_DIR, "chinese-hubert-base")

# 預訓練底模 (v2)
PRETRAIN_S1     = os.path.join(PRETRAIN_DIR, "s1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt")
PRETRAIN_S2G    = os.path.join(PRETRAIN_DIR, "s2G488k.pth")
PRETRAIN_S2D    = os.path.join(PRETRAIN_DIR, "s2D488k.pth")

OUTPUT_S2G      = os.path.join(DATA_DIR, "output", f"{EXP_NAME}_s2G.pth")
OUTPUT_S1       = os.path.join(DATA_DIR, "output", f"{EXP_NAME}_s1.ckpt")
os.makedirs(OPT_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "output"), exist_ok=True)

PYTHON = sys.executable
ENV = {**os.environ,
       "PYTHONIOENCODING": "utf-8",
       "PYTHONPATH": CORE_DIR + os.pathsep + GPT_SOVITS_DIR,
       "CUDA_VISIBLE_DEVICES": "0"}

# ── 輔助函式 ────────────────────────────────────────────────

def run(cmd, cwd=GPT_SOVITS_DIR, env_extra=None):
    e = {**ENV, **(env_extra or {})}
    print(f"\n>>> {' '.join(str(c) for c in cmd)}\n")
    ret = subprocess.run(cmd, cwd=cwd, env=e)
    if ret.returncode != 0:
        print(f"ERROR: step failed (code {ret.returncode})")
        sys.exit(ret.returncode)


# ── Step 1: 1-get-text.py  BERT 語義特徵 ────────────────────
if os.path.exists(os.path.join(OPT_DIR, "2-name2text.txt")):
    print("Step 1/4: 特徵已存在，跳過 BERT 提取")
else:
    print("=" * 60)
    print("Step 1/4  BERT 語義特徵提取")
    print("=" * 60)
    run([PYTHON, "-X", "utf8",
         os.path.join(CORE_DIR, "prepare_datasets", "1-get-text.py")],
        env_extra={
            "inp_text":         LIST_FILE,
            "inp_wav_dir":      WAV_DIR,
            "exp_name":         EXP_NAME,
            "opt_dir":          OPT_DIR,
            "bert_pretrained_dir": BERT_DIR,
            "is_half":          "True",
            "version":          "v2",
            "i_part":           "0",
            "all_parts":        "1",
            "_CUDA_VISIBLE_DEVICES": "0",
        })

# ── Step 2: 2-get-hubert-wav32k.py  Hubert 音頻特徵 ─────────
if os.path.exists(os.path.join(OPT_DIR, "4-cnhubert")):
    print("Step 2/4: 特徵已存在，跳過 Hubert 提取")
else:
    print("=" * 60)
    print("Step 2/4  Hubert 音頻特徵提取")
    print("=" * 60)
    run([PYTHON, "-X", "utf8",
         os.path.join(CORE_DIR, "prepare_datasets", "2-get-hubert-wav32k.py")],
        env_extra={
            "inp_text":         LIST_FILE,
            "inp_wav_dir":      WAV_DIR,
            "exp_name":         EXP_NAME,
            "opt_dir":          OPT_DIR,
            "cnhubert_base_dir": HUBERT_DIR,
            "is_half":          "True",
            "i_part":           "0",
            "all_parts":        "1",
            "_CUDA_VISIBLE_DEVICES": "0",
        })

# ── Step 3: 3-get-semantic.py  Semantic Token ───────────────
if os.path.exists(os.path.join(OPT_DIR, "6-name2semantic.tsv")):
    print("Step 3/4: 特徵已存在，跳過 Semantic Token 提取")
else:
    print("=" * 60)
    print("Step 3/4  Semantic Token 提取")
    print("=" * 60)
    run([PYTHON, "-X", "utf8",
         os.path.join(CORE_DIR, "prepare_datasets", "3-get-semantic.py")],
        env_extra={
            "inp_text":         LIST_FILE,
            "exp_name":         EXP_NAME,
            "opt_dir":          OPT_DIR,
            "pretrained_s2G":   PRETRAIN_S2G,
            "s2config_path":    os.path.join(CORE_DIR, "configs", "s2.json"),
            "is_half":          "True",
            "i_part":           "0",
            "all_parts":        "1",
            "_CUDA_VISIBLE_DEVICES": "0",
        })

# ── Step 4a: s2_train.py  SoVITS 聲線微調 ───────────────────
s2_config_src = os.path.join(CORE_DIR, "configs", "s2.json")
s2_config_dst = os.path.join(OPT_DIR, "s2.json")
import json, shutil

with open(s2_config_src, encoding="utf-8") as f:
    s2_cfg = json.load(f)

if os.path.exists(os.path.join(OPT_DIR, "xiaoyi_sovits_inference.pth")):
    print("Step 4a/4: SoVITS (s2) 已微調並導出推論模型，跳過 s2 訓練")
else:
    print("=" * 60)
    print("Step 4a/4  SoVITS (s2) Fine-tune")
    print("=" * 60)
    s2_cfg["train"]["log_interval"]    = 1
    s2_cfg["train"]["eval_interval"]   = 100
    s2_cfg["train"]["epochs"]          = 6      # 6 epoch 防止過擬合
    s2_cfg["train"]["batch_size"]      = 2
    s2_cfg["train"]["learning_rate"]   = 0.0001
    s2_cfg["train"]["gpu_numbers"]     = "0"
    s2_cfg["data"]["training_files"]   = LIST_FILE
    s2_cfg["data"]["exp_dir"]          = OPT_DIR
    s2_cfg["model"]["version"]         = "v2"
    s2_cfg["s2_ckpt_dir"]              = OPT_DIR
    s2_cfg["content_module"]           = "cnhubert"

    with open(s2_config_dst, "w", encoding="utf-8") as f:
        json.dump(s2_cfg, f, ensure_ascii=False, indent=2)

    run([PYTHON, "-X", "utf8",
         os.path.join(CORE_DIR, "s2_train.py"),
         "--config", s2_config_dst],
        env_extra={
            "pretrained_s2G":   PRETRAIN_S2G,
            "pretrained_s2D":   PRETRAIN_S2D,
            "s2_dir":           OPT_DIR,
            "_CUDA_VISIBLE_DEVICES": "0",
        })

# ── Step 4b: s1_train.py  GPT T2S 韻律微調 ──────────────────
print("=" * 60)
print("Step 4b/4  GPT T2S (s1) Fine-tune")
print("=" * 60)

s1_config_src = os.path.join(CORE_DIR, "configs", "s1longer.yaml")
s1_config_dst = os.path.join(OPT_DIR, "s1.yaml")
import yaml

with open(s1_config_src, encoding="utf-8") as f:
    s1_cfg = yaml.safe_load(f)

gpt_weights_dir = os.path.join(GPT_SOVITS_DIR, "GPT_weights_v2")
os.makedirs(gpt_weights_dir, exist_ok=True)

# 清理舊的過擬合 logs_s1，確保從純淨底模全新微調
s1_output_dir = os.path.join(OPT_DIR, "logs_s1")
if os.path.exists(s1_output_dir):
    print("清理舊 logs_s1，確保從純淨底模全新微調...")
    shutil.rmtree(s1_output_dir, ignore_errors=True)

s1_cfg["train_semantic_path"]       = os.path.join(OPT_DIR, "6-name2semantic.tsv")
s1_cfg["train_phoneme_path"]        = os.path.join(OPT_DIR, "2-name2text.txt")
s1_cfg["output_dir"]                = os.path.join(OPT_DIR, "logs_s1")
s1_cfg["pretrained_s1"]             = PRETRAIN_S1
s1_cfg["train"]["epochs"]           = 4      # 4 epoch 保守微調，保留底模常識
s1_cfg["train"]["batch_size"]       = 4
s1_cfg["train"]["save_every_n_epoch"] = 1
s1_cfg["train"]["if_save_latest"]   = False
s1_cfg["train"]["if_save_every_weights"] = True
s1_cfg["train"]["half_weights_save_dir"] = gpt_weights_dir
s1_cfg["train"]["exp_name"]         = "xiaoyi_finetune"
s1_cfg["train"]["if_dpo"]           = False
s1_cfg["data"]["num_workers"]       = 0      # Windows 友善，防止多行程死鎖

with open(s1_config_dst, "w", encoding="utf-8") as f:
    yaml.dump(s1_cfg, f, allow_unicode=True)

run([PYTHON, "-X", "utf8",
     os.path.join(CORE_DIR, "s1_train.py"),
     "--config_file", s1_config_dst],
    env_extra={
        "_CUDA_VISIBLE_DEVICES": "0",
        "hz": "25hz",
    })

# ── 完成：自動轉為推理模型格式 ────────────────────────────────
import glob, torch

print("\n" + "=" * 60)
print("訓練完成！自動轉為推論格式...")
print("=" * 60)

s2g_ckpts = sorted(glob.glob(os.path.join(OPT_DIR, "**", "*.pth"), recursive=True), key=os.path.getmtime)
s1_ckpts  = sorted(glob.glob(os.path.join(OPT_DIR, "**", "*.ckpt"), recursive=True), key=os.path.getmtime)

if s2g_ckpts:
    latest_s2g = s2g_ckpts[-1]
    print(f"Converting SoVITS {latest_s2g} to inference format...")
    raw = torch.load(latest_s2g, map_location="cpu")
    inf_dict = {
        "weight": raw["weight"] if "weight" in raw else raw,
        "config": s2_cfg,
        "info": "7L Xiaoyi SoVITS Finetuned Model"
    }
    inf_path = os.path.join(OPT_DIR, "xiaoyi_sovits_inference.pth")
    torch.save(inf_dict, inf_path)
    print(f"Saved inference model: {inf_path}")

if s1_ckpts:
    print(f"Latest GPT T2S checkpoint: {s1_ckpts[-1]}")
