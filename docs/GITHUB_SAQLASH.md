# TOTLI BI — GitHubga saqlash bo'yicha qo'llanma

## 1. Git o'rnatish

Agar Git o'rnatilmagan bo'lsa:

1. https://git-scm.com/download/win dan yuklab oling
2. O'rnatishda **"Add Git to PATH"** ni tanlang
3. PowerShell yoki CMD ni qayta ishga tushiring

## 2. Mavjud GitHub repository

Loyiha allaqachon GitHubda mavjud:
- **URL:** https://github.com/elyaclassic/totli-business-system

## 3. Loyihani GitHubga yuklash

PowerShell da quyidagi buyruqlarni ketma-ket bajaring:

```powershell
cd "d:\TOTLI BI"

# Git init (agar hali qilinmagan bo'lsa)
git init

# Barcha fayllarni qo'shish
git add .

# Birinchi commit
git commit -m "TOTLI BI: Backend + Flutter mobil ilova"

# GitHub remote qo'shish
git remote add origin https://github.com/elyaclassic/totli-business-system.git

# Asosiy branch nomi
git branch -M main

# Yuklash
git push -u origin main
```

## 4. Avtomatik skript (deploy_to_github.ps1)

`deploy_to_github.ps1` faylini ishga tushiring. Avval ichidagi `GITHUB_REPO_URL` ni o'z GitHub repo manzilingizga o'zgartiring.
