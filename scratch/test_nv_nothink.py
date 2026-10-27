import asyncio, os, re, time
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv("c:/Users/qiwai/.env")
KEYS = [k for k in re.split(r"[\s,;]+", os.getenv("NV_API_KEYS") or "") if k.startswith("nvapi-")]
TOOLS = [{"type": "function", "function": {"name": "set_expression", "description": "改變表情",
          "parameters": {"type": "object", "properties": {"emotion": {"type": "string", "enum": ["happy", "sad"]}}, "required": ["emotion"]}}}]
OFF = {"chat_template_kwargs": {"enable_thinking": False}}
CASES = [
    ("nvidia/nemotron-3-super-120b-a12b", OFF), ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", OFF),
    ("nvidia/nemotron-3.5-lightning-30b-a3b", OFF), ("deepseek-ai/deepseek-v4.1-flash", {"chat_template_kwargs": {"thinking": False}}),
    ("meta/llama-3.2-11b-vision-instruct", None),
]


async def one(m, eb, i, tools):
    c = AsyncOpenAI(api_key=KEYS[i % len(KEYS)], base_url="https://integrate.api.nvidia.com/v1", max_retries=0)
    t0 = time.monotonic()
    try:
        kw = dict(model=m, max_tokens=300, messages=[{"role": "user", "content": "觀眾送禮物了！用一句繁中回應並改表情" if tools else "用一句繁中跟觀眾打招呼"}])
        if tools: kw["tools"] = TOOLS
        if eb: kw["extra_body"] = eb
        r = await asyncio.wait_for(c.chat.completions.create(**kw), 45)
        msg = r.choices[0].message
        tc = msg.tool_calls[0].function.name if msg.tool_calls else "-"
        return f"{time.monotonic()-t0:5.1f}s tool={tc} | {(msg.content or '').strip()[:40]}"
    except asyncio.TimeoutError:
        return "TIMEOUT"
    except Exception as e:
        return f"ERR {str(e)[:80]}"


async def main():
    async def run(i, m, eb):
        a, b = await asyncio.gather(one(m, eb, i, False), one(m, eb, i + 1, True))
        print(f"{m}\n  chat {a}\n  tool {b}", flush=True)
    await asyncio.gather(*(run(i, m, eb) for i, (m, eb) in enumerate(CASES)))


asyncio.run(main())
