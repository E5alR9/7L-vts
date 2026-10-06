import os

def patch(filepath, rvc_root_depth):
    with open(filepath, 'rb') as fp:
        raw = fp.read()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    content = raw.decode('utf-8')
    if '_rvc not in _sys.path' in content:
        print(f'Already patched: {os.path.basename(filepath)}')
        return
    dots = '/'.join(['..'] * rvc_root_depth)
    inj = (
        'import sys as _sys, os as _os\r\n'
        f'_rvc = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "{dots}"))\r\n'
        'if _rvc not in _sys.path: _sys.path.insert(0, _rvc)\r\n'
        'del _sys, _os, _rvc\r\n'
        '\r\n'
    )
    with open(filepath, 'wb') as fp:
        fp.write((inj + content).encode('utf-8'))
    print(f'Patched: {os.path.basename(filepath)} (depth={rvc_root_depth})')

rvc = r'C:\Users\qiwai\RVC-WebUI'
# train/ is 1 level below RVC-WebUI/
patch(os.path.join(rvc, 'train', 'preprocess.py'), 1)
patch(os.path.join(rvc, 'train', 'train_index.py'), 1)
# train/dataset/ is 2 levels below RVC-WebUI/
patch(os.path.join(rvc, 'train', 'dataset', 'extract_f0.py'), 2)
patch(os.path.join(rvc, 'train', 'dataset', 'extract_hubert_feature.py'), 2)
print('Done!')

# Verify
for f in ['train/preprocess.py', 'train/train_index.py', 'train/dataset/extract_f0.py']:
    fp = os.path.join(rvc, f.replace('/', os.sep))
    with open(fp, 'r', encoding='utf-8') as fh:
        for line in fh:
            if '_rvc' in line:
                print(f'{f}: {line.strip()}')
                break
