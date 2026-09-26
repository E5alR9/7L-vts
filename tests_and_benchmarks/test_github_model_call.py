# -*- coding: utf-8 -*-
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from vm_agent.client import VMAgentClient

vm = VMAgentClient(host="172.22.212.232")

test_code = """
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv("C:\\\\AI_Agents\\\\.env")
github_token = os.getenv("GITHUB_TOKEN")

print(f"Token len: {len(github_token) if github_token else 0}")

client = OpenAI(
    api_key=github_token,
    base_url="https://models.inference.ai.azure.com"
)

try:
    resp = client.chat.completions.create(
        model="DeepSeek-R1",
        messages=[{"role": "user", "content": "請用繁體中文以一句話向 7L 打招呼！"}],
        max_tokens=60
    )
    print("\\n[✔️ 成功連線 GitHub Models DeepSeek-R1!]:")
    print(resp.choices[0].message.content)
except Exception as e:
    print("[❌ 呼叫錯誤]:", e)
"""

vm.write_file("C:\\AI_Agents\\test_github_call.py", test_code)
res = vm.exec("python C:\\AI_Agents\\test_github_call.py", timeout=30)
print(res.get('stdout'))
print(res.get('stderr'))
