import torch

infer_device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
infer_dtype = torch.float32

def get_device_dtype_sm(device_index=0):
    device = torch.device(f"cuda:{device_index}" if torch.cuda.is_available() else "cpu")
    dtype = torch.float32
    return device, dtype, 0, 0
