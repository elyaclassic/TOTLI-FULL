# TOTLI Inbox Responder runner — har 1 daqiqada Task Scheduler chaqiradi
$ErrorActionPreference = "Continue"
$root = "D:\TOTLI BI"
Set-Location $root

$candidates = @(
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python314\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Python313\python.exe",
    "C:\Python312\python.exe"
)
$python = $null
foreach ($p in $candidates) { if (Test-Path $p) { $python = $p; break } }
if (-not $python) {
    Add-Content -Path "$root\watchdog.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [responder] ERROR: Python topilmadi"
    exit 1
}

& $python "$root\scripts\claude_inbox_responder.py" 2>&1 | ForEach-Object {
    if ($_) { Add-Content -Path "$root\watchdog.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [responder-out] $_" }
}
exit $LASTEXITCODE
