# GitHub — Yangi repo yaratish va loyihani saqlash

## 1. GitHubda yangi repository yaratish

1. https://github.com/new ga kiring
2. **Repository name:** `totli-bi` yoki `totli-business-system` (o'zingiz xohlagan nom)
3. **Description:** `TOTLI HOLVA biznes boshqaruv tizimi`
4. **Public** yoki **Private** tanlang
5. ⚠️ **README, .gitignore, license QO'SHMASLANG** — loyihada allaqachon bor
6. **Create repository** bosing
7. Yaratilgan repo URL ni nusxalang, masalan:
   - `https://github.com/SIZNING_USERNAME/totli-bi.git`

---

## 2. Lokal loyihani GitHubga yuklash

PowerShell da (Git o'rnatilgan bo'lishi kerak):

```powershell
cd "d:\TOTLI BI"

# Git init
git init

# Barcha fayllarni qo'shish
git add .

# Birinchi commit
git commit -m "TOTLI BI: Backend + Flutter mobil ilova"

# Asosiy branch
git branch -M main

# GitHub remote (YANGI_REPO_URL ni 1-qadamda olingan URL bilan almashtiring)
git remote add origin https://github.com/SIZNING_USERNAME/totli-bi.git

# Yuklash
git push -u origin main
```

---

## 3. Avtomatik skript

`deploy_yangi_repo.ps1` skriptini ishlatishdan oldin ichidagi `GITHUB_REPO_URL` ni o'z yangi repo manzilingizga o'zgartiring.
