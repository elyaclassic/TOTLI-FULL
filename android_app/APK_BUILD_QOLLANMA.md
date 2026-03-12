# 📱 APK Build Qilish Qo'llanmasi

## 🎯 Tezkor Yo'l (Android Studio)

### 1. Android Studio ni ochish
1. **Android Studio** ni ishga tushiring
2. **File → Open** → `android_app` papkasini tanlang
3. Gradle sync tugaguniga kuting (pastki o'ng burchakda progress ko'rsatiladi)

### 2. APK Build qilish
**Variant A: Menu orqali (tavsiya)**
1. Yuqori menyuda **Build** → **Build Bundle(s) / APK(s)** → **Build APK(s)**
2. Build tugaguniga kuting (pastki o'ng burchakda "Build finished" ko'rsatiladi)
3. APK joylashuvi: `app/build/outputs/apk/debug/app-debug.apk`

**Variant B: Terminal orqali**
1. Android Studio da **Terminal** oynasini oching (pastki qismda)
2. Quyidagi buyruqni kiriting:
   ```bash
   # Windows
   gradlew.bat assembleDebug
   
   # Mac/Linux
   ./gradlew assembleDebug
   ```
3. Build tugagach, APK: `app/build/outputs/apk/debug/app-debug.apk`

### 3. APK ni topish
APK fayli quyidagi joyda:
```
android_app/app/build/outputs/apk/debug/app-debug.apk
```

---

## 🔧 Muammolar va Yechimlar

### Muammo 1: "SDK location not found"
**Yechim:**
1. Android Studio da **File → Project Structure** → **SDK Location**
2. SDK yo'lini ko'rsating (odatda: `C:\Users\ELYOR\AppData\Local\Android\Sdk`)
3. Yoki `local.properties` faylini yarating:
   ```
   sdk.dir=C\:\\Users\\ELYOR\\AppData\\Local\\Android\\Sdk
   ```

### Muammo 2: "Gradle sync failed"
**Yechim:**
1. **File → Invalidate Caches...** → **Invalidate and Restart**
2. Qayta sync qiling: **File → Sync Project with Gradle Files**

### Muammo 3: "Build failed"
**Yechim:**
1. **Build → Clean Project**
2. Keyin **Build → Rebuild Project**
3. Agar baribir ishlamasa, Android Studio ni qayta ishga tushiring

---

## 📦 Release APK (Production uchun)

### 1. Keystore yaratish
```bash
keytool -genkey -v -keystore totli-holva-release.jks -keyalg RSA -keysize 2048 -validity 10000 -alias totli-holva
```

### 2. Build Configuration
`app/build.gradle.kts` da release sozlamalari allaqachon mavjud.

### 3. Release APK build qilish
1. **Build → Generate Signed Bundle / APK**
2. **APK** ni tanlang
3. Keystore faylini tanlang va parolni kiriting
4. **release** build type ni tanlang
5. **Finish** ni bosing

Release APK: `app/build/outputs/apk/release/app-release.apk`

---

## 📲 Telefonga O'rnatish

### 1. APK ni telefonga ko'chirish
- USB orqali
- Email orqali
- Cloud storage (Google Drive, Dropbox) orqali

### 2. O'rnatish
1. Telefonda **Fayl menejer** ni oching
2. APK faylini toping va bosing
3. **Noma'lum manbalardan o'rnatish** ruxsatini bering (agar kerak bo'lsa)
4. **O'rnatish** tugmasini bosing

---

## ✅ Build Muvaffaqiyatli Bo'lganda

APK muvaffaqiyatli build bo'lganda:
- ✅ `app/build/outputs/apk/debug/app-debug.apk` fayli yaratiladi
- ✅ Fayl hajmi: ~5-10 MB
- ✅ Telefonga o'rnatishga tayyor

---

## 🚀 Keyingi Qadamlar

1. APK ni telefonga o'rnating
2. GPS permission berilganligini tekshiring
3. GPS ni qurilma sozlamalaridan yoqing
4. Login qilib, GPS ni test qiling

---

## 📝 Eslatmalar

- **Debug APK** - test uchun (tezkor build)
- **Release APK** - production uchun (signed, optimized)
- Har safar kod o'zgarganda yangi APK build qilish kerak
- APK faylini eski versiyalar bilan almashtirish mumkin
