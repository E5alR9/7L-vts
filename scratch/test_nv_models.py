import asyncio, os, re, time
import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv("c:/Users/qiwai/.env")
KEYS = [k for k in re.split(r"[\s,;]+", os.getenv("NV_API_KEYS") or os.getenv("NV_API_KEY") or "") if k.startswith("nvapi-")]
BASE = "https://integrate.api.nvidia.com/v1"
SKIP = re.compile(r"embed|guard|safety|reward|parse|clip|retriever|detector|deplot|kosmos|fuyu|vila|neva|translate|calibration|diffusion|starcoder|codegemma|codellama|llama2|riva", re.I)


async def test(client, sem, m):
    async with sem:
        t0 = time.monotonic()
        try:
            r = await asyncio.wait_for(client.chat.completions.create(
                model=m, messages=[{"role": "user", "content": "用一句繁體中文打招呼"}], max_tokens=64), 30)
            txt = (r.choices[0].message.content or "").strip().replace("\n", " ")[:50]
            return m, True, time.monotonic() - t0, txt
        except Exception as e:
            return m, False, time.monotonic() - t0, str(e)[:90]


async def main():
    print(f"NV keys: {len(KEYS)}")
    ids = sorted(x["id"] for x in httpx.get(f"{BASE}/models", headers={"Authorization": f"Bearer {KEYS[0]}"}, timeout=20).json()["data"])
    cands = [m for m in ids if not SKIP.search(m)]
    print(f"/models 共 {len(ids)} 個，測試對話候選 {len(cands)} 個\n")
    client = AsyncOpenAI(api_key=KEYS[0], base_url=BASE, max_retries=0)
    sem = asyncio.Semaphore(8)
    res = await asyncio.gather(*(test(client, sem, m) for m in cands))
    ok = sorted([r for r in res if r[1]], key=lambda r: r[2])
    print("=== ✅ 可用（依延遲排序）===")
    for m, _, dt, txt in ok:
        print(f"{dt:5.1f}s  {m}  | {txt}")
    print("\n=== ❌ 失敗 ===")
    for m, _, dt, err in res:
        if not _:
            print(f"{m}: {err}")


if __name__ == "__main__":
    asyncio.run(main())
