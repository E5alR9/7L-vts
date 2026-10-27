import glob, io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mido

cands = glob.glob(os.path.join("midi_sheets", "*.mid"))
print("total mid:", len(cands))
for p in cands:
    try:
        if "晴天" in os.path.basename(p) or "sunny" in os.path.basename(p).lower():
            mid = mido.MidiFile(p)
            notes = sum(1 for t in mid.tracks for m in t
                        if m.type == "note_on" and getattr(m, "velocity", 0) > 0)
            print("FILE:", os.path.basename(p), "bytes:", os.path.getsize(p),
                  "note_on:", notes, "len_sec:", round(mid.length, 1))
    except Exception as e:
        print("PARSE FAIL:", os.path.basename(p), e)
