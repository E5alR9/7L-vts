# -*- coding: utf-8 -*-
import numpy as np
import soundfile as sf
d, _ = sf.read('scratch/_rvc_test/judge_post_only_plus6.wav', always_2d=True)
o, _ = sf.read('scratch/_rvc_test/open_direct.wav', always_2d=True)
print("dur_match:", abs(len(d) - len(o)) / len(o) < 0.01)
print("judge rms:", round(float(np.sqrt(np.mean(d.astype(np.float64) ** 2))), 3))
print("judge peak:", round(float(np.max(np.abs(d))), 3))
