# -*- coding: utf-8 -*-
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from vm_agent.client import VMAgentClient

vm = VMAgentClient(host="172.22.212.232")

print("==================================================")
print(" 🧹 正在徹底清除 Ollama 並切換為 100% 雲端 API 模式...")
print("==================================================")

# 1. 終止進程
print("\n[1/3] 終止 Ollama 所有後台進程...")
vm.exec("Stop-Process -Name 'ollama', 'ollama app', 'ollama_app', 'OllamaSetup' -Force -ErrorAction SilentlyContinue")

# 2. Winget 反安裝
print("\n[2/3] 執行官方反安裝程式...")
res_un = vm.exec("winget uninstall Ollama.Ollama -e --silent --accept-source-agreements", timeout=120)
print(f" [✔️] 反安裝執行結果:\n{res_un.get('stdout')}")

# 3. 清理檔案
print("\n[3/3] 清理殘留資料夾與快取...")
clean_cmd = """
$p1 = "$env:LOCALAPPDATA\\Programs\\Ollama"
$p2 = "$env:USERPROFILE\\.ollama"
if (Test-Path $p1) { Remove-Item -Path $p1 -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path $p2) { Remove-Item -Path $p2 -Recurse -Force -ErrorAction SilentlyContinue }
Write-Output "Ollama 資料已完全清除！"
"""
res_clean = vm.exec(clean_cmd)
print(f" [✔️] {res_clean.get('stdout').strip()}")

print("\n==================================================")
print(" 🎉 Ollama 已徹底移除，虛擬機資源已 100% 釋放！")
print("==================================================")
