import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "tests/test_sing_queue.py"
src = open(p, encoding="utf-8").read()
block = '''

def test_stop_current_song_keeps_queue():
    """電擊打斷：只停當首，排隊保留，去重鍵不動；閒時回 False。"""
    acp.IS_SINGING_ACTIVE = True
    acp._NOW_PLAYING_TITLE = "歌A"
    acp.request_cover_song("歌A", "老爸")
    acp.request_cover_song("歌B", "老爸")
    assert acp.stop_current_song() is True
    assert acp.IS_SINGING_ACTIVE is False
    assert acp._NOW_PLAYING_TITLE == ""
    assert len(acp.SONG_REQUEST_QUEUE) == 2
    assert acp.is_song_active("歌A")
    assert acp.is_song_active("歌B")
    acp.stop_singing()
    assert acp.stop_current_song() is False
'''
assert "test_stop_current_song_keeps_queue" not in src
open(p, "w", encoding="utf-8", newline="").write(src + block)
print("appended")
