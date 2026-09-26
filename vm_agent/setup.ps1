# 7L VM Setup Script (PowerShell Native)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " [*] Downloading and setting up 7L VM Agent..." -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan

$destDir = "C:\7L_VM_Agent"
if (!(Test-Path $destDir)) {
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
}

$zipUrl = "http://172.22.208.1:8888/7L_VM_Agent.zip"
$zipPath = "$destDir\7L_VM_Agent.zip"

Write-Host "[1/3] Downloading 7L_VM_Agent.zip from host..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
} catch {
    Write-Host "[!] Trying fallback IP 192.168.1.102..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "http://192.168.1.102:8888/7L_VM_Agent.zip" -OutFile $zipPath -UseBasicParsing
}

Write-Host "[2/3] Extracting archive..." -ForegroundColor Green
Expand-Archive -Path $zipPath -DestinationPath $destDir -Force

Write-Host "[3/3] Running installer script..." -ForegroundColor Green
Set-Location $destDir
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$destDir\install.ps1"
