# Android SDK (command line tools) o'rnatish - Flutter Android uchun
$SdkDir = "C:\Android\sdk"
$CmdToolsUrl = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
$ZipPath = "$env:TEMP\cmdline-tools.zip"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Android SDK o'rnatish" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if (-not (Test-Path $SdkDir)) { New-Item -ItemType Directory -Path $SdkDir -Force | Out-Null }
$LatestDir = "$SdkDir\cmdline-tools\latest"
if (-not (Test-Path $LatestDir)) { New-Item -ItemType Directory -Path $LatestDir -Force | Out-Null }

Write-Host "[1/4] Command line tools yuklanmoqda..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri $CmdToolsUrl -OutFile $ZipPath -UseBasicParsing
} catch {
    Write-Host "[X] Yuklab olishda xato. Qo'lda: https://developer.android.com/studio#command-line-tools-only" -ForegroundColor Red
    exit 1
}

Write-Host "[2/4] Chiqarilmoqda..." -ForegroundColor Cyan
Expand-Archive -Path $ZipPath -DestinationPath "$SdkDir\cmdline-tools" -Force
$extracted = Get-ChildItem "$SdkDir\cmdline-tools" -Directory | Select-Object -First 1
if ($extracted -and $extracted.Name -ne "latest") {
    Move-Item "$($extracted.FullName)\*" $LatestDir -Force
    Remove-Item $extracted.FullName -Force -ErrorAction SilentlyContinue
}
Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue

Write-Host "[3/4] Platform va build-tools o'rnatilmoqda..." -ForegroundColor Cyan
$sdkmanager = "$LatestDir\bin\sdkmanager.bat"
if (Test-Path $sdkmanager) {
    & $sdkmanager --sdk_root=$SdkDir "platform-tools" "platforms;android-34" "build-tools;34.0.0" | Out-Null
}

Write-Host "[4/4] ANDROID_HOME sozlanmoqda..." -ForegroundColor Cyan
[Environment]::SetEnvironmentVariable("ANDROID_HOME", $SdkDir, "User")
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";$SdkDir\platform-tools;$LatestDir\bin", "User")

Write-Host "[OK] Android SDK o'rnatildi: $SdkDir" -ForegroundColor Green
Write-Host "Yangi terminal oching va: flutter doctor --android-licenses" -ForegroundColor Yellow
