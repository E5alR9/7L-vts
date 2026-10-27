import asyncio, time
from dotenv import load_dotenv

load_dotenv("c:/Users/qiwai/.env")

from core.groq_router import groq_chat, _model_cooldown, _key_cooldown, GROQ_KEYS, MODEL_LADDER

TOOLS = [{"type": "function", "function": {"name": "set_expression", "description": "改變虛擬主播表情",
          "parameters": {"type": "object", "properties": {"emotion": {"type": "string", "enum": ["happy", "sad"]}}, "required": ["emotion"]}}}]


async def run(label, **kw):
    t0 = time.monotonic()
    resp = await groq_chat(**kw)
    dt = time.monotonic() - t0
    if resp:
        print(f"✅ {label} {dt:.1f}s model={resp.model} text={resp.text!r} fcs={[(f.name, f.args) for f in resp.function_calls]}")
    else:
        print(f"❌ {label} {dt:.1f}s 全部失敗 model_cd={_model_cooldown} key_cd={len(_key_cooldown)}")


async def main():
    print(f"keys: {len(GROQ_KEYS)} (nv={sum(k.startswith('nvapi-') for k in GROQ_KEYS)})  ladder[0]={MODEL_LADDER[0]}")
    await run("對話", messages=[{"role": "user", "content": "用一句繁體中文跟觀眾打招呼"}], timeout=4.0)
    await run("工具", messages=[{"role": "user", "content": "觀眾送禮物了，你很開心，改變表情"}], tools=TOOLS, timeout=4.0)


asyncio.run(main())
