# Flutter o'rnatish — TOTLI HOLVA

## O'rnatilgan (avtomatik)

- **Flutter** — C:\src\flutter
- **Java JDK 17** — C:\Java\jdk-17
- **Android SDK** — C:\Android\sdk (platform-tools, android-34, build-tools)
- **PATH** — flutter\bin, Java\bin, Android\platform-tools

---

## Variant 1: Avtomatik (PowerShell skript)

1. **PowerShell** ni **Administrator** sifatida oching
2. Quyidagini yozing:
   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process -Force
   cd "d:\TOTLI BI"
   .\flutter_install.ps1
   ```
3. Yuklab olish tugagach, **yangi terminal** oching
4. Tekshiring: `flutter doctor`

---

## Variant 2: Qo'lda o'rnatish

### 1. Flutter SDK yuklab olish

- **Havola:** https://docs.flutter.dev/get-started/install/windows
- "Download Flutter SDK" tugmasini bosing
- Yoki to'g'ridan-to'g'ri: https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.24.5-stable.zip

### 2. Chiqarish

- ZIP faylni `C:\src\` papkasiga chiqaring
- Chiqarilgan papka nomi `flutter` bo'lishi kerak
- Natija: `C:\src\flutter\`

### 3. PATH ga qo'shish

**PowerShell (foydalanuvchi uchun):**
```powershell
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\src\flutter\bin", "User")
```

**Qo'lda:**
1. Win + R → `sysdm.cpl` → Enter
2. "Advanced" → "Environment Variables"
3. "Path" → Edit → New → `C:\src\flutter\bin`
4. OK

### 4. Tekshirish

Yangi terminal oching:
```bat
flutter doctor
```

---

## Android ilova uchun (totli_mobile)

1. **Android Studio** o'rnating: https://developer.android.com/studio
2. Android Studio ichida: Tools → SDK Manager → Android SDK o'rnating
3. `flutter doctor` da Android litsenziyalarini qabul qiling:
   ```bat
   flutter doctor --android-licenses
   ```

---

## totli_mobile loyihasini ishga tushirish

```bat
cd d:\TOTLI BI\totli_mobile
flutter pub get
flutter run
```

(Telefon USB orqali ulangan yoki emulyator ishlayotgan bo'lishi kerak)
