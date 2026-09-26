# 啟動 CosyVoice3 本地 TTS 服務（models/cosyvoice/Fun-CosyVoice3-0.5B → http://127.0.0.1:9881）
# 用法： powershell -ExecutionPolicy Bypass -File scripts\start_cosyvoice.ps1
# 說明： 服務是常駐程序；啟動需 25~60 秒載入 9.3GB 權重。
#       tts_router 的 cosyvoice 引擎在服務沒好之前會自動降級 kokoro/edge（不影響直播）。

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $root "venvs\cosyvoice\Scripts\python.exe"
$server = Join-Path $root "services\cosyvoice_server.py"
$port = if ($env:COSYVOICE_PORT) { $env:COSYVOICE_PORT } else { "9881" }

if (-not (Test-Path $venv)) {
    Write-Host "[CosyVoice] 找不到獨立環境：$venv"
    Write-Host "            請先建立：python -m venv --system-site-packages venvs\cosyvoice"
    Write-Host "            再安裝依賴：venvs\cosyvoice\Scripts\python.exe -m pip install -r venvs\req_notorch.txt"
    exit 1
}
if (-not (Test-Path $server)) { Write-Host "[CosyVoice] 找不到 $server"; exit 1 }

# 已在聽 → 不重複啟動
$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "[CosyVoice] 服務已在 http://127.0.0.1:$port 執行，略過啟動"
    exit 0
}

# 模型存在嗎
$model = Join-Path $root "models\cosyvoice\Fun-CosyVoice3-0.5B\cosyvoice3.yaml"
if (-not (Test-Path $model)) {
    Write-Host "[CosyVoice] 模型未下載：$model"
    Write-Host "            請執行 scripts\download_cosyvoice.ps1"
    exit 1
}

# kaldisft 的 C++ 開檔吃不了中文路徑 → wetext FST 必須放純 ASCII 目錄
$env:WETEXT_DIR = Join-Path $env:USERPROFILE ".cache\7l_wetext"
if (-not (Test-Path (Join-Path $env:WETEXT_DIR "zh\tn\tagger.fst"))) {
    Write-Host "[CosyVoice] 缺 wetext FST（$env:WETEXT_DIR），請執行 scripts\download_wetext.ps1"
    exit 1
}

$log = Join-Path $root "cosyvoice_service.log"
$err = Join-Path $root "cosyvoice_service.err.log"
Remove-Item $log, $err -ErrorAction SilentlyContinue

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
Start-Process -FilePath $venv `
    -ArgumentList "`"$server`"","--port",$port `
    -WorkingDirectory $root `
    -RedirectStandardOutput $log -RedirectStandardError $err `
    -WindowStyle Hidden

Write-Host "[CosyVoice] 已啟動（背景），log: $log"
Write-Host "            載入約 25~60 秒，完成後 /health 會回 ok:true"
# 等待就緒（最多 90 秒）
for ($i = 1; $i -le 18; $i++) {
    Start-Sleep -Seconds 5
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 3
        if ($h.ok) { Write-Host "[$($i*5)s] 就緒 ✅ sr=$($h.sample_rate)"; exit 0 }
    } catch { }
}
Write-Host "[CosyVoice] 90 秒內未就緒（可稍後再查 $log），tts_router 期間會自動用 kokoro"
exit 0
