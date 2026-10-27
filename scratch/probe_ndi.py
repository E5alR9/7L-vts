# -*- coding: utf-8 -*-
"""NDI 無頭探測：runtime 初始化＋3 秒發現來源。不開視窗，不碰 VTS 設定。"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
try:
    import NDIlib as ndi
except Exception as e:
    print("NDILIB_IMPORT_FAIL:", e)
    raise SystemExit(2)

t0 = time.time()
ok = ndi.initialize()
print("ndi.initialize:", ok, f"({time.time()-t0:.1f}s)")
if not ok:
    print("DIAG: NDI Runtime 未安裝/損壞 → 去裝 NDI Tools (Runtime)")
    raise SystemExit(3)

find_settings = ndi.FindCreate()
find_settings.show_local_sources = True
find_handle = ndi.find_create_v2(find_settings)
if not find_handle:
    print("DIAG: find_create 失敗")
    raise SystemExit(4)
deadline = time.time() + 5.0
found = []
while time.time() < deadline:
    if ndi.find_wait_for_sources(find_handle, 500):
        for s in ndi.find_get_current_sources(find_handle):
            if s.ndi_name not in found:
                found.append(s.ndi_name)
print("sources:", found if found else "(none)")
ndi.find_destroy(find_handle)
ndi.destroy()
if not found:
    print("DIAG: 區網內零 NDI 來源 → VTS 那側 NDI 輸出沒開（或跟接收器不在同網段）")
