# TOTLI BI — GitHubga yuklash skripti
# Ishlatish: .\deploy_to_github.ps1
# Avval: GITHUB_REPO_URL ni o'z GitHub repo manzilingizga o'zgartiring

$ErrorActionPreference = "Stop"
$GITHUB_REPO_URL = "https://github.com/elyaclassic/totli-business-system.git"

Write-Host "=== TOTLI BI — GitHubga yuklash ===" -ForegroundColor Green
Write-Host ""

$projectPath = "d:\TOTLI BI"
Set-Location $projectPath

# Git mavjudligini tekshirish
try {
    $null = git --version
} catch {
    Write-Host "XATO: Git topilmadi. Git o'rnating: https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}

# Git init
if (-not (Test-Path ".git")) {
    Write-Host "git init..." -ForegroundColor Yellow
    git init
}

# Status
Write-Host "`ngit add ." -ForegroundColor Yellow
git add .

$status = git status --short
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "O'zgarishlar yo'q. Commit qilinadi (--allow-empty)." -ForegroundColor Gray
    git commit --allow-empty -m "TOTLI BI: Backend + Flutter mobil ilova"
} else {
    Write-Host "`ngit commit..." -ForegroundColor Yellow
    git commit -m "TOTLI BI: Backend + Flutter mobil ilova (Agent/Driver mobil ilova)"
}

# Remote
$remote = git remote get-url origin 2>$null
if (-not $remote) {
    Write-Host "`ngit remote add origin..." -ForegroundColor Yellow
    git remote add origin $GITHUB_REPO_URL
}

git branch -M main 2>$null

Write-Host "`ngit push..." -ForegroundColor Yellow
git push -u origin main

Write-Host "`n=== Muvaffaqiyatli yakunlandi ===" -ForegroundColor Green
Write-Host "Repo: $GITHUB_REPO_URL" -ForegroundColor Cyan
