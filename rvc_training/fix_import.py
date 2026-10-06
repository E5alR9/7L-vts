import os

filepath = r'C:\Users\qiwai\RVC-WebUI\train\preprocess.py'
with open(filepath, 'rb') as f:
    raw = f.read()

if raw.startswith(b'\xef\xbb\xbf'):
    raw = raw[3:]
content = raw.decode('utf-8')

# The fix: replace sys.path[0] (the 'train/' directory) with RVC root
# Also handles multiprocessing by registering the module properly
inj = (
    'import sys as _sys, os as _os\r\n'
    '_rvc = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))\r\n'
    '# Replace sys.path[0] (= train/ dir) with RVC root to avoid circular imports\r\n'
    'if _sys.path and _sys.path[0] == _os.path.dirname(_os.path.abspath(__file__)):\r\n'
    '    _sys.path[0] = _rvc\r\n'
    'elif _rvc not in _sys.path:\r\n'
    '    _sys.path.insert(0, _rvc)\r\n'
    'del _sys, _os, _rvc\r\n'
    '\r\n'
)

with open(filepath, 'wb') as f:
    f.write((inj + content).encode('utf-8'))
print('Fixed preprocess.py')

# Verify syntax
import py_compile
py_compile.compile(filepath, doraise=True)
print('Syntax OK!')
