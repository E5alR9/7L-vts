# -*- coding: utf-8 -*-
from vm_agent.client import VMAgentClient

vm = VMAgentClient(host="172.22.212.232")

res = vm.exec("python -c \"import pyautogui, mss, PIL, pyperclip, openai; print('ALL OK')\"")
print("VM Dependencies Output:", res.get("stdout"))
print("VM Dependencies Stderr:", res.get("stderr"))
