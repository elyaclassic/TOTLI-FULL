@echo off
chcp 65001 >nul
echo Git dan xavfsiz/keraksiz fayllarni indeksdan olib tashlash (fayllar diskda qoladi).
echo.

git rm --cached cert.pem 2>nul
git rm --cached key.pem 2>nul
git rm --cached python-3.12.7-amd64.exe 2>nul
git rm --cached main.zip 2>nul
git rm --cached repo.zip 2>nul

echo.
echo Qilingan. Endi commit qiling:
echo   git add .gitignore
echo   git commit -m "Xavfsizlik: .gitignore yangilandi, cert/exe/zip indeksdan olib tashlandi"
echo   git push
echo.
pause
