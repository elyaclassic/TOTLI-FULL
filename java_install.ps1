# Java JDK 17 o'rnatish - Android SDK uchun
$JavaDir = "C:\Java\jdk-17"
$JavaUrl = "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.13%2B11/OpenJDK17U-jdk_x64_windows_hotspot_17.0.13_11.zip"
$ZipPath = "$env:TEMP\jdk17.zip"

Write-Host "Java JDK 17 o'rnatilmoqda..." -ForegroundColor Cyan
if (-not (Test-Path "C:\Java")) { New-Item -ItemType Directory -Path "C:\Java" -Force | Out-Null }

if (Test-Path "$JavaDir\bin\java.exe") {
    Write-Host "[OK] Java allaqachon mavjud: $JavaDir" -ForegroundColor Green
    exit 0
}

Write-Host "[1/2] Yuklanmoqda..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri $JavaUrl -OutFile $ZipPath -UseBasicParsing
} catch {
    Write-Host "[X] Xato: $_" -ForegroundColor Red
    Write-Host "Qo'lda: https://adoptium.net/temurin/releases/?version=17" -ForegroundColor Yellow
    exit 1
}

Write-Host "[2/2] Chiqarilmoqda..." -ForegroundColor Cyan
Expand-Archive -Path $ZipPath -DestinationPath "C:\Java" -Force
$extracted = Get-ChildItem "C:\Java" -Directory | Where-Object { $_.Name -like "jdk*" } | Select-Object -First 1
if ($extracted) {
    if ($extracted.FullName -ne $JavaDir) {
        if (Test-Path $JavaDir) { Remove-Item $JavaDir -Recurse -Force }
        Rename-Item $extracted.FullName "jdk-17"
    }
}
Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue

$JavaHome = "C:\Java\jdk-17"
if (-not (Test-Path "$JavaHome\bin\java.exe")) {
    $JavaHome = (Get-ChildItem "C:\Java" -Directory -Recurse -Filter "java.exe" -ErrorAction SilentlyContinue | Select-Object -First 1).Directory.Parent.FullName
}
if ($JavaHome) {
    [Environment]::SetEnvironmentVariable("JAVA_HOME", $JavaHome, "User")
    $path = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($path -notlike "*$JavaHome\bin*") {
        [Environment]::SetEnvironmentVariable("Path", "$path;$JavaHome\bin", "User")
    }
    Write-Host "[OK] Java o'rnatildi: $JavaHome" -ForegroundColor Green
}
