# TOTLI HOLVA — Loyiha sozlamalari

## 1. Environment (.env)

`.env.example` ni `.env` ga nusxalang va qiymatlarni to'ldiring:

```bat
copy .env.example .env
```

**Asosiy o'zgaruvchilar:**
- `SECRET_KEY` — session shifrlash (production da majburiy o'zgartiring)
- `YANDEX_MAPS_API_KEY` — xarita uchun (ixtiyoriy)
- `PRODUCTION=1` — production rejimida SECRET_KEY default bo'lmasligi uchun
- `HTTPS=1` — cookie secure (reverse proxy orqali HTTPS bo'lsa)

## 2. Admin foydalanuvchi

```bat
python create_admin.py
```

Parol kiritish so'raladi (xavfsizlik uchun). Mavjud admin uchun parolni o'zgartirish mumkin.

## 3. Backup (avtomatik)

**Bir martalik:**
```bat
backup_avtomatik.bat
```

**Har kuni 02:00 da (Task Scheduler):**
```bat
schtasks /create /tn "TOTLI Backup" /tr "d:\TOTLI BI\backup_avtomatik.bat" /sc daily /st 02:00
```

Nusxalar `backups\YYYY-MM\` papkasida saqlanadi.

## 4. HTTPS (production)

**Caddy** (oson):
1. [Caddy o'rnating](https://caddyserver.com/docs/install)
2. `deploy/Caddyfile` da domeningizni yozing
3. `caddy run --config deploy/Caddyfile`

**Nginx:**
- `deploy/nginx.conf.example` ni nusxalang va domen/yo'l ni o'zgartiring
- `certbot --nginx -d totli.example.com` — SSL sertifikat

## 5. Logging

Login va muhim harakatlar `logs/totli_holva.log` ga yoziladi (5 MB rotation).
