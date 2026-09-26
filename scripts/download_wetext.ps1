# 下載 wetext 文字正規化 FST（CosyVoice 中文前端必備）到「純 ASCII 路徑」
# 為什麼不能放專案裡： kaldisft 的 C++ ifstream 無法開啟含中文的路徑
#   （實測 Desktop\thumb\大拇哥實驗室\... 直接 "Error opening input stream"）
# 用法： powershell -ExecutionPolicy Bypass -File scripts\download_wetext.ps1
# 來源： modelscope（路徑不可 URL-encode；若遇「操作过于频繁」限流，隔幾秒重跑）

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$dest = Join-Path $env:USERPROFILE ".cache\7l_wetext"
$base = "https://www.modelscope.cn/api/v1/models/pengzhendong/wetext/repo?Revision=master&FilePath="

# CosyVoice 用到的最小集合（Normalizer 會載入 en/zh 的 tn tagger+verbalizer）
$files = @(
    "zh/tn/tagger.fst",
    "zh/tn/verbalizer.fst",
    "en/tn/tagger.fst",
    "en/tn/verbalizer.fst",
    # 備用（ITN/兒化音/日文，之後要用再抓）
    "zh/tn/verbalizer_remove_erhua.fst",
    "en/itn/tagger.fst",
    "en/itn/verbalizer.fst"
)

$ok = 0; $fail = 0
foreach ($f in $files) {
    $out = Join-Path $dest ($f -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
    if ((Test-Path $out) -and ((Get-Item $out).Length -gt 1000)) {
        Write-Host ("  SKIP {0}  ({1:N1} KB)" -f $f, ((Get-Item $out).Length / 1KB)); $ok++; continue
    }
    curl.exe -s -L --max-time 90 -o $out ($base + $f)     # 注意：路徑不要 encode，保留斜線
    $len = if (Test-Path $out) { (Get-Item $out).Length } else { 0 }
    if ($len -gt 1000) { Write-Host ("  OK   {0}  ({1:N1} KB)" -f $f, ($len / 1KB)); $ok++ }
    else { Write-Host ("  FAIL {0}  ({1} bytes) — 可能被限流，稍後重跑" -f $f, $len); $fail++; Remove-Item $out -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 800
}
Write-Host ("完成：成功 {0}、失敗 {1} → {2}" -f $ok, $fail, $dest)
if ($fail -gt 0) { Write-Host "  限流（10013201001 操作过于频繁）時隔 30 秒重跑本腳本即可（已成功的會 SKIP）"; exit 1 }
exit 0
