import asyncio, os, re, time, json
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv("c:/Users/qiwai/.env")
KEYS = [k for k in re.split(r"[\s,;]+", os.getenv("NV_API_KEYS") or os.getenv("NV_API_KEY") or "") if k.startswith("nvapi-")]
BASE = "https://integrate.api.nvidia.com/v1"
CANDS = [
    "meta/llama-3.2-11b-vision-instruct", "meta/llama-3.2-90b-vision-instruct",
    "nvidia/nemotron-3-super-120b-a12b", "openai/gpt-oss-20b", "deepseek-ai/deepseek-v4.1-flash",
    "nvidia/nemotron-3.5-lightning-30b-a3b", "google/gemma-4-31b-it", "meta/muse-glimmer-30b",
    "moonshotai/kimi-k3", "poolside/laguna-xs-2.1", "z-ai/glm-5.3", "z-ai/glm-5.3-flash",
    "nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]
TOOLS = [{"type": "function", "function": {
    "name": "set_expression", "description": "改變虛擬主播的表情",
    "parameters": {"type": "object", "properties": {"emotion": {"type": "string", "enum": ["happy", "sad", "angry"]}}, "required": ["emotion"]}}}]


async def chat(client, m):
    t0 = time.monotonic()
    try:
        r = await asyncio.wait_for(client.chat.completions.create(
            model=m, messages=[{"role": "user", "content": "用一句繁體中文跟觀眾打招呼，20字內"}], max_tokens=1024), 90)
        txt = (r.choices[0].message.content or "").strip().replace("\n", " ")[:40]
        return f"{time.monotonic()-t0:5.1f}s {'OK ' if txt else 'EMPTY'} {txt}"
    except asyncio.TimeoutError:
        return "  TIMEOUT(90s)"
    except Exception as e:
        return f"  ERR {str(e)[:70]}"


async def tool(client, m):
    t0 = time.monotonic()
    try:
        r = await asyncio.wait_for(client.chat.completions.create(
            model=m, messages=[{"role": "user", "content": "觀眾送了禮物，你很開心，請改變表情"}],
            tools=TOOLS, tool_choice="auto", max_tokens=1024), 90)
        tc = r.choices[0].message.tool_calls
        if tc:
            return f"{time.monotonic()-t0:5.1f}s TOOL {tc[0].function.name}{tc[0].function.arguments}"
        return f"{time.monotonic()-t0:5.1f}s NO-TOOL"
    except asyncio.TimeoutError:
        return "  TIMEOUT(90s)"
    except Exception as e:
        return f"  ERR {str(e)[:70]}"


async def probe(m, i, sem):
    async with sem:
        c = AsyncOpenAI(api_key=KEYS[i % len(KEYS)], base_url=BASE, max_retries=0)
        a, b = await asyncio.gather(chat(c, m), tool(c, m))
        print(f"{m}\n   chat: {a}\n   tool: {b}", flush=True)


async def main():
    sem = asyncio.Semaphore(6)
    await asyncio.gather(*(probe(m, i, sem) for i, m in enumerate(CANDS)))


if __name__ == "__main__":
    asyncio.run(main())
