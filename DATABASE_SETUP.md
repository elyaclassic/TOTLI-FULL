# Database Sozlash — SQL Server va SQLite

Tizim endi **ikkala database'ni qo'llab-quvvatlaydi**: SQLite (development) va SQL Server (production).

## SQLite (Default)

Agar `DATABASE_URL` environment variable o'rnatilmagan bo'lsa, avtomatik SQLite ishlatiladi:

```bash
# Hech narsa qilish shart emas — avtomatik ishlaydi
python main.py
```

Database fayli: `totli_holva.db` (loyiha ildizida)

## SQL Server (Windows Server)

SQL Server'ga o'tish uchun:

### 1. Driver o'rnatish

Windows Server'da **ODBC Driver 17 for SQL Server** o'rnatilgan bo'lishi kerak:
- [Microsoft'dan yuklab olish](https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

### 2. Environment Variable o'rnatish

Windows Server'da environment variable qo'shing:

**PowerShell (default login va parol bilan):**
```powershell
[System.Environment]::SetEnvironmentVariable("DATABASE_URL", "mssql+pyodbc://sa:123456@localhost/TotliHolvaDB?driver=ODBC+Driver+17+for+SQL+Server", "Machine")
```

**Yoki foydalanuvchi va parol bilan:**
```powershell
[System.Environment]::SetEnvironmentVariable("DATABASE_URL", "mssql+pyodbc://username:password@server_name/database_name?driver=ODBC+Driver+17+for+SQL+Server", "Machine")
```

**Yoki `.env` fayl yaratish** (loyiha ildizida):
```
DATABASE_URL=mssql+pyodbc://username:password@server_name/database_name?driver=ODBC+Driver+17+for+SQL+Server
```

**Misol (default login va parol):**
```
DATABASE_URL=mssql+pyodbc://sa:123456@localhost/TotliHolvaDB?driver=ODBC+Driver+17+for+SQL+Server
```

**Yoki IP manzil bilan:**
```
DATABASE_URL=mssql+pyodbc://sa:123456@192.168.1.100/TotliHolvaDB?driver=ODBC+Driver+17+for+SQL+Server
```

### 3. PyODBC o'rnatish

```bash
pip install pyodbc
```

### 4. Database yaratish

SQL Server Management Studio'da yangi database yarating:
```sql
CREATE DATABASE TotliHolvaDB;
```

### 5. Migration ishlatish

SQL Server uchun Alembic migration ishlatish:

```bash
# Alembic.ini faylida DATABASE_URL ni o'zgartiring yoki environment variable ishlatish
alembic upgrade head
```

## Ikkala Database'ni Parallel Ishlatish

Agar development'da SQLite, production'da SQL Server ishlatmoqchi bo'lsangiz:

**Development (local):**
```bash
# Environment variable o'rnatmaslik — SQLite ishlatiladi
python main.py
```

**Production (Windows Server):**
```bash
# Environment variable o'rnatilgan — SQL Server ishlatiladi
set DATABASE_URL=mssql+pyodbc://sa:123456@localhost/TotliHolvaDB?driver=ODBC+Driver+17+for+SQL+Server
python main.py
```

## Kod O'zgarishlari

- `app/models/database.py` endi `DATABASE_URL` environment variable'dan o'qiydi
- SQLite-specific kodlar (`PRAGMA`, `AUTOINCREMENT`) faqat SQLite'da ishlaydi
- SQL Server uchun migration ishlatiladi (Alembic)
- Barcha SQLAlchemy modellar ikkala database'da ham ishlaydi

## Tekshirish

Database qaysi ishlatilayotganini ko'rish:

```python
from app.models.database import DATABASE_URL, _is_sqlite, _is_sql_server
print(f"Database URL: {DATABASE_URL}")
print(f"SQLite: {_is_sqlite}")
print(f"SQL Server: {_is_sql_server}")
```

## Eslatmalar

- SQLite: `CREATE TABLE IF NOT EXISTS` va `PRAGMA` ishlatiladi
- SQL Server: Migration (Alembic) ishlatiladi, `INFORMATION_SCHEMA` tekshiriladi
- Connection pooling SQL Server uchun optimallashtirilgan (pool_size=10, max_overflow=20)
- SQLite uchun WAL mode va cache optimizatsiyasi saqlanadi
