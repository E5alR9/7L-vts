import asyncio
import sys
import os

sys.path.insert(0, r'c:\Users\qiwai')
from core.groq_router import groq_chat

async def main():
    messages = [
        {"role": "system", "content": "You are a subagent."},
        {"role": "user", "content": "Hello, please just say 'Test successful'."}
    ]
    model_name = "nvidia/llama-3.1-nemotron-70b-instruct"
    try:
        resp = await groq_chat(messages=messages, tools=[], model=model_name)
        if resp:
            print(f"Success! Model {model_name} says: {resp.text}")
        else:
            print("Response was empty or failed.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
