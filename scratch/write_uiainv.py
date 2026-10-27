import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

lines = [
    "Add-Type -AssemblyName UIAutomationClient",
    "$procs = Get-Process Gemini -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -ne '' }",
    "$root = [System.Windows.Automation.AutomationElement]::FromHandle($procs[0].MainWindowHandle)",
    "$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,",
    "    [System.Windows.Automation.Condition]::TrueCondition)",
    'Write-Output ("total={0}" -f $all.Count)',
    "$n = 0",
    "foreach ($el in $all) {",
    "    try {",
    "        $ip = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)",
    "        if ($ip) {",
    "            $nm = $el.Current.Name",
    "            $ct = $el.Current.ControlType.ProgrammaticName",
    "            if ($nm -match '新對話|對話|新增|音樂|影片|傳送|發送|送出') {",
    "                Write-Output (\"HIT {0} namelen={1}\" -f $ct, $nm.Length)",
    "                $n++",
    "            }",
    "        }",
    "    } catch {}",
    "}",
    'Write-Output ("hits={0}" -f $n)',
]
open("scratch/uia_inv.ps1", "w", encoding="utf-8-sig", newline="").write("\n".join(lines) + "\n")
print("wrote")
