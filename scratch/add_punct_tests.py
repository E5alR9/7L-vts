import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "tests/test_tts_router.py"
src = open(p, encoding="utf-8").read()
assert "test_code_punct_to_spoken_boundaries" not in src
block = '''

# ── 程式碼標點轉口語邊界（2026-10-11：Mili 句整段消失＋後面變日文）──────────
def test_code_punct_to_spoken_boundaries():
    from core.prompts import TextCleanEngine as C
    # 拉丁 token 內 .()_/\ 轉空格，獨立 - 轉逗號
    assert C.normalize_spoken_form("Mili - world.execute(me)") == "Mili，world execute me "
    assert C.normalize_spoken_form("唱world_execute_me吧") == "唱world execute me吧"
    assert C.normalize_spoken_form("A/B測") == "A B測"
    # 時間不受傷（先轉時間，冒號本來就不在集合裡）
    assert C.normalize_spoken_form("半夜5:20am開播") == "半夜上午五點二十分開播"
    # 日文語境不動
    assert C.normalize_spoken_form("12:00に会う", for_chinese=False) == "12:00に会う"
    # 整管：Mili 句無殘留毒標點，中文不斷
    out = C.clean_for_tts("好喔，《Mili - world.execute(me)》交給我，背景準備中，好了就唱給你聽！")
    assert out == "好喔，Mili，world execute me 交給我，背景準備中，好了就唱給你聽！"
    for bad in ["《", "》", "(", ")", "."]:
        assert bad not in out.replace("！", "")
'''
open(p, "w", encoding="utf-8", newline="").write(src + block)
print("appended")
