# TOTLI HOLVA — Mobil ilova (Agent / Haydovchi)

Flutter ilovasi TOTLI BI tizimiga Agent va Haydovchilar uchun.

## Xususiyatlar

- **Login** — Telefon raqam va parol bilan kirish (Agent/Driver)
- **GPS tracking** — Lokatsiya har 5 daqiqada avtomatik yuboriladi
- **Dashboard** — Foydalanuvchi ma'lumotlari va tezkor amallar
- **Server sozlash** — Login sahifasida server manzilini o'zgartirish mumkin

## Talablar

- Flutter SDK 3.0+
- Android Studio yoki VS Code
- Android SDK 21+ (yoki iOS 11+)

## O'rnatish

1. **Flutter o'rnatish** (agar yo'q bo'lsa):
   - https://docs.flutter.dev/get-started/install

2. **Loyihani yuklash**:
   ```bash
   cd totli_mobile
   flutter pub get
   ```

3. **Ishga tushirish**:
   ```bash
   flutter run
   ```

4. **APK yaratish**:
   ```bash
   flutter build apk --release
   ```

## Server sozlash

- **Emulyator:** `http://10.0.2.2:8080` (Android emulator uchun localhost)
- **Haqiqiy qurilma:** Kompyuter IP manzili, masalan `http://192.168.1.100:8080`
- Login sahifasida "Server manzili" maydonida o'zgartirish mumkin

## API Endpoint'lar

Ilova quyidagi TOTLI BI API'lardan foydalanadi:

- `POST /api/login` — Kirish (username, password)
- `POST /api/agent/location` — Agent lokatsiya
- `POST /api/driver/location` — Haydovchi lokatsiya
- `GET /api/agent/partners` — Mijozlar ro'yxati
- `GET /api/agent/orders` — Buyurtmalar

## Ruxsatlar

**Android:** GPS (foreground va background) — AndroidManifest.xml da

**iOS:** Info.plist da:
- `NSLocationWhenInUseUsageDescription`
- `NSLocationAlwaysAndWhenInUseUsageDescription`
