# -*- coding: utf-8 -*-
from vm_agent.client import VMAgentClient

vm = VMAgentClient(host="172.22.212.232")

script = """
$exePath = "C:\\Users\\qiwai\\AppData\\Local\\Programs\\Antigravity IDE\\Antigravity IDE.exe"
$desktops = @(
    "C:\\Users\\qiwai\\OneDrive\\Desktop",
    "C:\\Users\\Public\\Desktop",
    "C:\\Users\\qiwai\\Desktop"
)

$wsh = New-Object -ComObject WScript.Shell

foreach ($d in $desktops) {
    if (Test-Path $d) {
        $shortcutPath = Join-Path $d "🚀_Antigravity_AI_IDE.lnk"
        $shortcut = $wsh.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $exePath
        $shortcut.WorkingDirectory = "C:\\AI_Agents"
        $shortcut.Description = "Google Antigravity AI IDE"
        $shortcut.Save()
        Write-Output "已建立桌面捷徑: $shortcutPath"
    }
}
"""

res = vm.exec(script)
print("STDOUT:", res.get("stdout"))
