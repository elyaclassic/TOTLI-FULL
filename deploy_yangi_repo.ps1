# TOTLI BI — Yangi GitHub repoga yuklash
# 1. https://github.com/new da yangi repo yarating (README qo'shmaslang)
# 2. Quyidagi GITHUB_REPO_URL ni o'z repo manzilingizga o'zgartiring
# 3. Skriptni ishga tushiring: .\deploy_yangi_repo.ps1

$ErrorActionPreference = "Stop"
$GITHUB_REPO_URL = "https://github.com/SIZNING_USERNAME/totli-bi.git"  # <-- O'ZGARTIRING

Write-Host "=== TOTLI BI — Yangi GitHub repoga yuklash ===" -ForegroundColor Green
Write-Host ""

$projectPath = "d:\TOTLI BI"
Set-Location $projectPath

# Git tekshirish
try {
    $null = git --version
} catch {
    Write-Host "XATO: Git topilmadi. O'rnating: https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}

# URL tekshirish
if ($GITHUB_REPO_URL -match "SIZNING_USERNAME") {
    Write-Host "XATO: GITHUB_REPO_URL ni o'zgartiring!" -ForegroundColor Red
    Write-Host "  1. https://github.com/new da yangi repo yarating" -ForegroundColor Yellow
    Write-Host "  2. deploy_yangi_repo.ps1 faylida GITHUB_REPO_URL ni yangilang" -ForegroundColor Yellow
    Write-Host "  Misol: https://github.com/elyaclassic/totli-bi.git" -ForegroundColor Gray
    exit 1
}

# Git init
if (-not (Test-Path ".git")) {
    Write-Host "git init..." -ForegroundColor Cyan
    git init
}

# Add va commit
Write-Host "`ngit add ." -ForegroundColor Cyan
git add .

$status = git status --short
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "O'zgarishlar yo'q. Bo'sh commit..." -ForegroundColor Gray
    git commit --allow-empty -m "TOTLI BI: Backend + Flutter mobil ilova"
} else {
    Write-Host "`ngit commit..." -ForegroundColor Cyan
    git commit -m "TOTLI BI: Backend + Flutter mobil ilova (Agent/Driver)"
}

git branch -M main 2>$null

# Remote
$remote = git remote get-url origin 2>$null
if ($remote) {
    Write-Host "`nRemote mavjud: $remote" -ForegroundColor Yellow
    $change = Read-Host "O'zgartirish kerakmi? (y/n)"
    if ($change -eq "y") {
        git remote remove origin
        git remote add origin $GITHUB_REPO_URL
    }
} else {
    Write-Host "`ngit remote add origin..." -ForegroundColor Cyan
    git remote add origin $GITHUB_REPO_URL
}

# Push
Write-Host "`ngit push -u origin main..." -ForegroundColor Cyan
git push -u origin main

Write-Host "`n=== Muvaffaqiyatli ===" -ForegroundColor Green
Write-Host "Repo: $GITHUB_REPO_URL" -ForegroundColor Cyan
