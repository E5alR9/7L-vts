import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

lines = [
    "Add-Type -AssemblyName UIAutomationClient",
    "$procs = Get-Process Gemini -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -ne '' }",
    "$root = [System.Windows.Automation.AutomationElement]::FromHandle($procs[0].MainWindowHandle)",
    "$cond = New-Object System.Windows.Automation.PropertyCondition(",
    "    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,",
    "    [System.Windows.Automation.ControlType]::Button)",
    "$btns = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)",
    "$target = $null",
    "foreach ($b in $btns) {",
    "    try { if ($b.Current.Name -eq '新對話') { $target = $b; break } } catch {}",
    "}",
    "if (-not $target) { Write-Output 'BTN_NOT_FOUND'; exit 1 }",
    "try {",
    "    $pat = $target.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)",
    "    $pat.Invoke()",
    "    Write-Output 'INVOKED'",
    "} catch { Write-Output 'INVOKE_FAIL'; exit 2 }",
]
open("scratch/uia_newchat.ps1", "w", encoding="utf-8-sig", newline="").write("\n".join(lines) + "\n")
print("wrote")
