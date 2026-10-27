import inspect, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from audio_separator.separator import Separator
print(inspect.signature(Separator.__init__))
print(inspect.signature(Separator.separate))
print(inspect.signature(Separator.load_model))
