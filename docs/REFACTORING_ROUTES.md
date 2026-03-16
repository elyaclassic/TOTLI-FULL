# Route'larni routerlarga ko'chirish — holat

## Bajarildi

### 1. Sales router (to'liq)
- **app/routes/sales.py** — barcha savdo route'lari (sotuvlar ro'yxati, yangi/tahrir/tasdiq/revert/o'chirish, **POS** (sotuv oynasi), **savdodan qaytarish**).
- **main.py** — sales route'lari olib tashlandi, `app.include_router(sales_routes.router)` qo'shildi.

### 2. Qoldiqlar router (to'liq)
- **app/routes/qoldiqlar.py** — `tarix`, `edit-row`, `apply-to-warehouse` qo'shildi; tasdiqlash/revert `create_stock_movement` bilan yangilandi.
- main dan barcha /qoldiqlar route'lari olib tashlandi.

### 3. Finance + cash/transfers
- **app/routes/finance.py** — harajatlar, kassa, payment, expense-types, harajat hujjati; cash_router (prefix="/cash") — transfers.
- main dan olib tashlandi.

### 4. Info router (to'liq)
- **app/routes/info.py** — units, categories, price-types, prices, cash, departments, directions, users, positions, piecework-tasks, production-groups.
- main dan olib tashlandi.

### 5. Products router (to'liq)
- **app/routes/products.py** — ro'yxat, add, edit, delete, import, bulk-update, barcode, product-check.
- main dan olib tashlandi.

### 6. Warehouse + Inventory
- **app/routes/warehouse.py** — warehouse router va inventory_router.
- main dan olib tashlandi.

### 7. Purchases router (to'liq)
- **app/routes/purchases.py** — list, new, create, edit, add-item, delete-item, add-expense, delete-expense, set-expense-cash, confirm, revert, delete.
- main dan olib tashlandi.

### 8. Partners router (to'liq)
- **app/routes/partners.py** — list, add, edit, delete, export, template, import.
- main dan olib tashlandi.

### 9. Employees router (to'liq)
- **app/routes/employees.py** — APIRouter(prefix="/employees"); barcha xodimlar route'lari (list, add, edit, delete, dismissal, hiring-docs, attendance, advances, salary va h.k.).
- main dan olib tashlandi.

### 10. Dashboard
- main dagi dublikat dashboard route'lari olib tashlandi (dashboard_routes.router allaqachon bor edi).

---

## Yakuniy holat

main.py da faqat `/ping` va `/favicon.ico` qoldi. Barcha boshqa route'lar routerlarga ko'chirildi.

### Qo'shimcha ko'chirilgan (davom ettirish)

| Router | Prefix | Holat |
|--------|--------|-------|
| **Production** | `/production/*` | quick-recipes, by-operator, movements qo'shildi; main dan olib tashlandi |
| **API** | `/api/*` | notifications/unread qo'shildi; main dan olib tashlandi |
| **Agents** | `/agents/*` | main dan olib tashlandi |
| **Delivery** | `/delivery/*`, `/map`, `/supervisor` | main dan olib tashlandi |
| **Admin** | `/admin/*` | backup route; main.py ga ulanib qo'shildi |

### Yakuniy tozalash (2025-03)
- **Admin router** — `main.py` da `admin_routes.router` include qilindi; `/admin/backup` ishlaydi.
- **Import tozalash** — main.py dan keraksiz import'lar olib tashlandi (openpyxl, docx, barcode, PIL va boshqalar).
- **Hardcoded path** — `r"C:\Users\ELYOR\.cursor\worktrees\business_system\pwp"` olib tashlandi; faqat `os.path.dirname(__file__)` va `os.getcwd()` qoldi.
- **db_schema refaktoring** — `ensure_payments_status_column` va `ensure_cash_opening_balance_column` `app/utils/db_schema.py` ga ko'chirildi; finance.py va info.py dagi dublikatlar olib tashlandi; main.py startup db_schema dan import qiladi.

---

## Ko'chirishda qoidalar

- `@app.get` → `@router.get` (yoki post/put/delete)
- Path da prefix qo'yilmasin (router allaqachon `prefix="/..."` oladi)
- Kerakli import'lar router faylida bo'lishi kerak
