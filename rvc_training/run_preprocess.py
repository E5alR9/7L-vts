import sys
sys.path.insert(0, r'C:\Users\qiwai\RVC-WebUI')

# Now run preprocess with patched args
import importlib.util
import os

# manually parse what preprocess.py expects
sys.argv = [
    'preprocess.py',
    r'C:\Users\qiwai\RVC-WebUI\datasets\7L_singing',
    '48000', '6',
    r'C:\Users\qiwai\RVC-WebUI\logs\7L_v2',
    'False', '3.7'
]

spec = importlib.util.spec_from_file_location('preprocess', r'C:\Users\qiwai\RVC-WebUI\train\preprocess.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
