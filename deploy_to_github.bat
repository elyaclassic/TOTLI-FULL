@echo off
chcp 65001 >nul
echo === TOTLI BI — GitHubga yuklash ===
echo.

cd /d "d:\TOTLI BI"

where git >nul 2>&1
if errorlevel 1 (
    echo XATO: Git topilmadi. Git o'rnating: https://git-scm.com/download/win
    pause
    exit /b 1
)

if not exist ".git" (
    echo git init...
    git init
)

echo.
echo git add .
git add .

echo.
echo git commit...
git commit -m "TOTLI BI: Backend + Flutter mobil ilova" 2>nul
if errorlevel 1 (
    echo Commit mavjud yoki o'zgarish yo'q.
)

echo.
echo REMOTE va PUSH qilish uchun quyidagilarni qo'lda bajaring:
echo   git remote add origin https://github.com/YOUR_USERNAME/totli-bi.git
echo   git branch -M main
echo   git push -u origin main
echo.
echo Yoki deploy_to_github.ps1 skriptini ishlatib, GITHUB_REPO_URL ni o'zgartiring.
pause
