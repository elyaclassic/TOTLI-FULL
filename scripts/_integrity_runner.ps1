# TOTLI BI Integrity Check runner — Task Scheduler chaqiradi
# PowerShell Unicode (kirill yo'l) ni to'g'ri qabul qiladi

$ErrorActionPreference = "Continue"
$root = "D:\TOTLI BI"
Set-Location $root

# Python interpretatorini topish
$candidates = @(
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python314\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Program Files\Python314\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe",
    "C:\Python314\python.exe",
    "C:\Python313\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe"
)

$python = $null
foreach ($p in $candidates) {
    if (Test-Path $p) { $python = $p; break }
}

if (-not $python) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path "$root\integrity_check.log" -Value "$ts  ERROR: Python topilmadi"
    exit 1
}

# Skriptni ishga tushirish
& $python "$root\scripts\integrity_check.py" --quiet 2>&1 | Out-File -FilePath "$root\integrity_check.log" -Append -Encoding UTF8
exit $LASTEXITCODE
