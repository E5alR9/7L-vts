# 7L VM Agent Installer (Pure PowerShell - Encoding-safe)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Continue"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " [1/4] Checking Python environment..." -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (!$pyCmd) {
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
}

if (!$pyCmd) {
    Write-Host "[ERROR] Python is not found in PATH!" -ForegroundColor Red
    Write-Host "Please install Python 3.10+ and make sure 'Add Python to PATH' is checked during installation." -ForegroundColor Yellow
    Read-Host "Press Enter to exit..."
    exit 1
}

$pythonPath = $pyCmd.Source
Write-Host "[*] Found Python: $pythonPath" -ForegroundColor Green

Write-Host "`n[2/4] Installing required packages (FastAPI, Uvicorn, PyAutoGUI, etc.)..." -ForegroundColor Cyan
& $pythonPath -m pip install --upgrade pip
& $pythonPath -m pip install fastapi "uvicorn[standard]" pydantic pyautogui mss pillow pyperclip psutil pywin32 --timeout 180

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Retrying with alternative mirror..." -ForegroundColor Yellow
    & $pythonPath -m pip install fastapi "uvicorn[standard]" pydantic pyautogui mss pillow pyperclip psutil pywin32 -i https://pypi.org/simple
}

Write-Host "`n[3/4] Configuring Windows Firewall (Opening Port 7777)..." -ForegroundColor Cyan
try {
    Remove-NetFirewallRule -DisplayName "7L_VM_Agent" -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "7L_VM_Agent" -Direction Inbound -LocalPort 7777 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null
    Write-Host "[*] Firewall rule added successfully!" -ForegroundColor Green
} catch {
    Write-Host "[!] Note: Could not add firewall rule automatically. Please ensure port 7777 is allowed." -ForegroundColor Yellow
}

Write-Host "`n[4/4] Setting up Startup shortcut..." -ForegroundColor Cyan
try {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $startupFolder = [Environment]::GetFolderPath("Startup")
    $shortcutPath = Join-Path $startupFolder "Start_7L_Agent.lnk"
    
    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonPath
    $shortcut.Arguments = "`"$scriptDir\server.py`""
    $shortcut.WorkingDirectory = $scriptDir
    $shortcut.WindowStyle = 7 # Minimized
    $shortcut.Save()
    Write-Host "[*] Auto-start shortcut created in Windows Startup!" -ForegroundColor Green
} catch {
    Write-Host "[!] Note: Startup shortcut could not be created: $_" -ForegroundColor Yellow
}

Write-Host "`n==================================================" -ForegroundColor Green
Write-Host " 🎉 7L VM Dedicated Agent successfully installed!" -ForegroundColor Green
Write-Host " [*] Starting server.py now on port 7777..." -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Green

$serverScript = Join-Path $scriptDir "server.py"
Start-Process -FilePath $pythonPath -ArgumentList "`"$serverScript`"" -WorkingDirectory $scriptDir
Write-Host "`nAgent is now running in background! You can close this window." -ForegroundColor Cyan
