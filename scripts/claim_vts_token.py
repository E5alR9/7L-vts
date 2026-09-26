# -*- coding: utf-8 -*-
"""
一次性領取 VTube Studio 插件 Token（存成 ./vts_token.txt）

背景：VTS 端的 token 存在加密檔 *.vtsauth，但 V7 主程式領取時只有 30 秒視窗，
      使用者若來不及在彈窗按【允許】就會 408 逾時、每次都重問。

本腳本：
  1. 沒有本機 token → 向 VTS 申請（最長等 timeout 秒，彈窗請按允許）
  2. VTS 已有 token → 秒回、不彈窗
  3. 拿到後直接認證驗證一次，成功才算完成

用法：  python scripts/claim_vts_token.py [--timeout 300]
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.vts_client import RobustVTSClient  # noqa: E402

PLUGIN_INFO = {
    "plugin_name": "7L_AI_VTuber",
    "developer": "e5_Studio",
    "authentication_token_path": "./vts_token.txt",
}


async def main(timeout: float) -> int:
    client = RobustVTSClient(plugin_info=PLUGIN_INFO)

    try:
        await client.connect(retries=3, retry_delay=1.0)
    except Exception as e:
        print(f"❌ 無法連上 VTube Studio: {e}")
        print("   請先確認 VTube Studio 已開啟、且設定 → Plugins → API 已啟用 (port 8001)")
        return 1

    token = await client.read_token()
    if token:
        print(f"✔ 本機已有 token（{len(token)} 字元），直接認證驗證...")
    else:
        print(f"… 本機無 token，向 VTS 申請（最多等 {timeout:.0f} 秒）")
        print("  ⚠️ 若 VTS 彈出「允許 7L_AI_VTuber 嗎？」請按【允許】")
        try:
            token = await client.request_authenticate_token(timeout=timeout)
        except Exception as e:
            print(f"❌ 申請逾時/失敗: {type(e).__name__}: {e}")
            print("   常見原因：VTS 上還有一個未關閉的認證彈窗 → 請到 VTS 把它按掉再重跑本腳本")
            return 2
        if token:
            await client.write_token()
            print(f"✔ 已取得並寫入 {PLUGIN_INFO['authentication_token_path']}")

    if not token:
        print("❌ 沒拿到 token")
        return 3

    # 真的認證一次才算數
    try:
        resp = await client.request_authenticate()
    except Exception as e:
        print(f"❌ 認證呼叫失敗: {type(e).__name__}: {e}")
        return 4

    data = (resp or {}).get("data") or {}
    if data.get("authenticated"):
        print(f"✅ 認證成功！plugin={data.get('pluginName')} 狀態已就緒")
        print("   現在啟動 V7.bat 就不會再問了。")
        return 0

    # 認證失敗 → 通常是 token 被 VTS 撤銷，刪掉重領
    reason = data.get("reason") or resp
    print(f"❌ 認證失敗: {reason}")
    try:
        os.remove(PLUGIN_INFO["authentication_token_path"])
        print("   已刪除本機失效 token，請重跑本腳本重新領取。")
    except OSError:
        pass
    return 5


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=300.0, help="等待 VTS 彈窗允許的秒數")
    args = ap.parse_args()
    try:
        code = asyncio.run(main(args.timeout))
    except KeyboardInterrupt:
        code = 130
    sys.stdout.flush()
    sys.exit(code)
