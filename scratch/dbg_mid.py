import io, os, sys, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

import mido

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "good.mid")
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("program_change", program=0, time=0))
    per = max(1, int(480 * 30.0 / 30))
    for i in range(30):
        tr.append(mido.Message("note_on", note=60 + (i % 12), velocity=90, time=0))
        tr.append(mido.Message("note_off", note=60 + (i % 12), velocity=0, time=per))
    mid.save(p)
    m2 = mido.MidiFile(p)
    print("length:", m2.length)
    print("size:", os.path.getsize(p))
    import services.piano_engine as pe
    print("playable:", pe.is_midi_playable(p))
