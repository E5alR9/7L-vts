# 下載 Kokoro-82M (ONNX) 模型到 models/kokoro/
# 用法： powershell -ExecutionPolicy Bypass -File scripts\download_kokoro.ps1
# 支援斷點續傳（-C -），重跑不會重下。

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$d = Join-Path (Split-Path $PSScriptRoot -Parent) "models\kokoro"
New-Item -ItemType Directory -Force -Path $d | Out-Null

$base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
$files = @(
    @{ name = "kokoro-v1.1-zh.onnx"; minMB = 300 },   # 模型 ~310MB（中文版）
    @{ name = "voices-v1.1-zh.bin";  minMB = 50 }     # 聲線檔 ~51MB（103 組聲線，含 zf_001~）
)

foreach ($f in $files) {
    $out = Join-Path $d $f.name
    if ((Test-Path $out) -and ((Get-Item $out).Length -gt ($f.minMB * 1MB))) {
        Write-Host "  SKIP $($f.name)（已存在）"
        continue
    }
    Write-Host "  下載 $($f.name) ..."
    curl.exe -L -C - --fail --retry 5 --retry-delay 3 --max-time 3000 -o $out "$base/$($f.name)"
    if ((Test-Path $out) -and ((Get-Item $out).Length -gt ($f.minMB * 1MB))) {
        Write-Host ("  OK   {0}  {1:N1} MB" -f $f.name, ((Get-Item $out).Length / 1MB))
    } else {
        Write-Host "  FAIL $($f.name) — 請檢查網路後重跑本腳本"
    }
}

Write-Host "完成。測試： python -c `"import sys; sys.path.insert(0,'.'); import services.tts_router as t; print(t.ENGINE_CHAIN)`""
