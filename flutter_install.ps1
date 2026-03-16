# TOTLI BI - Flutter o'rnatish skripti (Windows)
# Ishga tushirish: PowerShell da "Set-ExecutionPolicy Bypass -Scope Process" keyin .\flutter_install.ps1

# Flutter 3.19.6 - barqaror versiya (3.24+ bo'lsa URL ni o'zgartiring)
$FlutterVersion = "3.19.6"
$FlutterUrl = "https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_$FlutterVersion-stable.zip"
$InstallDir = "C:\src"
$FlutterDir = "$InstallDir\flutter"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Flutter SDK o'rnatish" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Papka yaratish
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "[OK] Papka yaratildi: $InstallDir" -ForegroundColor Green
}

# Flutter allaqachon bormi?
if (Test-Path "$FlutterDir\bin\flutter.bat") {
    Write-Host "[!] Flutter allaqachon mavjud: $FlutterDir" -ForegroundColor Yellow
    Write-Host "    PATH ga qo'shish uchun quyidagini bajaring:" -ForegroundColor Yellow
    Write-Host "    [Environment]::SetEnvironmentVariable('Path', `$env:Path + ';$FlutterDir\bin', 'User')" -ForegroundColor Gray
    exit 0
}

# Eski papka bo'lsa olib tashlash
if (Test-Path $FlutterDir) {
    Write-Host "[*] Eski Flutter papkasi olib tashlanmoqda..." -ForegroundColor Yellow
    Remove-Item -Path $FlutterDir -Recurse -Force -ErrorAction SilentlyContinue
}

# Yuklab olish
$ZipPath = "$InstallDir\flutter_sdk.zip"
Write-Host "[1/3] Flutter SDK yuklanmoqda (~1 GB)..." -ForegroundColor Cyan
try {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $FlutterUrl -OutFile $ZipPath -UseBasicParsing
    Write-Host "[OK] Yuklab olindi" -ForegroundColor Green
} catch {
    Write-Host "[X] Yuklab olishda xato: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Qo'lda o'rnatish:" -ForegroundColor Yellow
    Write-Host "1. https://docs.flutter.dev/get-started/install/windows oching" -ForegroundColor Gray
    Write-Host "2. 'Download Flutter SDK' tugmasini bosing" -ForegroundColor Gray
    Write-Host "3. ZIP faylni $InstallDir ga chiqarib oling" -ForegroundColor Gray
    Write-Host "4. Chiqarilgan papkani 'flutter' deb nomlang" -ForegroundColor Gray
    exit 1
}

# Chiqarish
Write-Host "[2/3] Fayllar chiqarilmoqda..." -ForegroundColor Cyan
Expand-Archive -Path $ZipPath -DestinationPath $InstallDir -Force
Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
Write-Host "[OK] Chiqarildi" -ForegroundColor Green

# PATH ga qo'shish (foydalanuvchi uchun)
$BinPath = "$FlutterDir\bin"
$CurrentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($CurrentPath -notlike "*$BinPath*") {
    [Environment]::SetEnvironmentVariable("Path", "$CurrentPath;$BinPath", "User")
    $env:Path = "$env:Path;$BinPath"
    Write-Host "[3/3] PATH ga qo'shildi (User)" -ForegroundColor Green
} else {
    Write-Host "[3/3] PATH da allaqachon mavjud" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Flutter muvaffaqiyatli o'rnatildi!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Yangi terminal oching va tekshiring:" -ForegroundColor Yellow
Write-Host "  flutter doctor" -ForegroundColor Gray
Write-Host ""
Write-Host "Android ilova uchun Android Studio o'rnating:" -ForegroundColor Yellow
Write-Host "  https://developer.android.com/studio" -ForegroundColor Gray
Write-Host ""
