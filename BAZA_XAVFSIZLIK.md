# Baza ma'lumotlari xavfsizligi

## Git va baza

- **totli_holva.db** — barcha ma'lumotlar shu faylda
- Bu fayl **.gitignore** da — Git ga **hech qachon** kirmaydi
- GitHubga push qilganda baza **o'chib ketmaydi**, faqat kod yuboriladi
- Baza har doim **lokal** kompyuteringizda qoladi

## Qo'shimcha xavfsizlik

Muntazam rezerv nusxa olish uchun:

```powershell
Copy-Item "d:\TOTLI BI\totli_holva.db" "d:\TOTLI_BI_backup_$(Get-Date -Format 'yyyy-MM-dd').db"
```

Yoki `baza_nusxasi_saqlash.bat` skriptini ishlating.
