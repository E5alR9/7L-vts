import asyncio
from google import genai

async def test():
    client = genai.Client(api_key='fake_key_for_testing_types')
    stream = await client.aio.models.generate_content_stream(model='gemini-2.5-flash', contents='hi')
    try:
        async for chunk in stream:
            pass
    except Exception as e:
        print(f"e str: '{e}'")
        print(f"e repr: {repr(e)}")

asyncio.run(test())
