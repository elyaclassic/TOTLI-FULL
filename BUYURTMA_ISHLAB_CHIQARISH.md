# Buyurtma va Ishlab Chiqarish — Qanday Ishlaydi?

## Hozirgi Holat

Hozirgi tizimda:
- **Buyurtma (Order)** — `type="sale"` sifatida yaratiladi (Sotuvlar bo'limida)
- **Ishlab chiqarish** — alohida bo'lim (Production), buyurtmadan avtomatik yaratilmaydi
- **Qoldiq tekshiruvi** — sotuv tasdiqlashda tekshiriladi, lekin ishlab chiqarishga avtomatik yo'naltirilmaydi

---

## Taklif Qilingan Jarayon

### 1. Buyurtma Yaratish

**Kim yaratadi:**
- Agentlar (mobil ilova orqali)
- Menejerlar (web ilova orqali)

**Qayerda:**
- Hozirgi kodda: `/sales` sahifasida `type="sale"` Order yaratiladi
- Yoki yangi "Buyurtmalar" bo'limi qo'shilishi mumkin (`type="order"`)

### 2. Qoldiq Tekshiruvi

Buyurtma yaratilganda yoki tasdiqlashda:

```
1. Tayyor mahsulot omborida yetarli tovar bormi?
   ├─ Ha → Buyurtma tasdiqlanadi, sotuv sifatida ishlaydi
   └─ Yo'q → Ishlab chiqarishga yo'naltiriladi
```

### 3. Ishlab Chiqarish Jarayoni

**3.1. Yarim tayyor mahsulotlarga qarash:**

```
Yarim tayyor omborida yetarli yarim tayyor mahsulot bormi?
├─ Ha → 
│   ├─ Kesish va qadoqlash foydalanuvchilariga habar
│   └─ Ishlab chiqarish: bosqich 3-4 (kesish + qadoqlash)
│
└─ Yo'q →
    ├─ Qiyom quyush foydalanuvchilariga habar
    └─ Ishlab chiqarish: bosqich 1-4 (to'liq jarayon)
```

**3.2. Ishlab chiqarish bosqichlari:**

1. **Qiyom tayyorlash** (bosqich 1)
   - Xom ashyo omboridan materiallar olinadi
   - Qiyom tayyorlanadi

2. **Qiyomga qo'shiladigan mahsulotlar** (bosqich 2)
   - Yarim tayyor mahsulotlar qo'shiladi
   - Yarim tayyor omborga yoziladi

3. **Holva kesish** (bosqich 3)
   - Yarim tayyor omboridan olinadi
   - Kesiladi

4. **Qadoqlash** (bosqich 4)
   - Tayyor mahsulot omborga yoziladi

---

## Taklif Qilingan Yechim

### Variant 1: Buyurtma Bo'limi Qo'shish

**Yangi model:** `Order` endi `type="order"` (buyurtma) va `type="sale"` (sotuv) bo'lishi mumkin

**Jarayon:**
1. Agent/Menejer buyurtma yaratadi (`type="order"`, `status="draft"`)
2. Buyurtma tasdiqlashda:
   - Tayyor mahsulot tekshiriladi
   - Yetarli bo'lsa → `status="ready"` → sotuvga o'tkaziladi
   - Yetarli bo'lmasa → Ishlab chiqarishga yo'naltiriladi

### Variant 2: Sotuvda Avtomatik Tekshiruv

**Hozirgi kodni yaxshilash:**
- Sotuv yaratilganda qoldiq tekshiriladi
- Yetarli bo'lmasa → Ishlab chiqarish buyurtmasi avtomatik yaratiladi
- Notification yuboriladi (kesish/qadoqlash yoki qiyom quyush foydalanuvchilariga)

---

## Kodda Qanday Amalga Oshirish

### 1. Buyurtma Yaratishda Qoldiq Tekshiruvi

```python
@app.post("/orders/create")
async def order_create(...):
    # Buyurtma yaratiladi
    order = Order(type="order", status="draft", ...)
    
    # Har bir mahsulot uchun qoldiq tekshiruvi
    insufficient_products = []
    for item in order.items:
        stock = db.query(Stock).filter(
            Stock.warehouse_id == finished_warehouse_id,
            Stock.product_id == item.product_id
        ).first()
        available = stock.quantity if stock else 0
        if available < item.quantity:
            insufficient_products.append({
                "product": item.product,
                "required": item.quantity,
                "available": available
            })
    
    if insufficient_products:
        # Ishlab chiqarishga yo'naltirish
        return create_production_orders(order, insufficient_products)
    else:
        # Tayyor — sotuvga o'tkazish
        order.status = "ready"
        db.commit()
```

### 2. Ishlab Chiqarishga Yo'naltirish

```python
def create_production_orders(order, insufficient_products):
    """Yetarli bo'lmagan mahsulotlar uchun ishlab chiqarish buyurtmalari yaratish"""
    production_orders = []
    
    for item in insufficient_products:
        product = item["product"]
        required = item["required"]
        available = item["available"]
        needed = required - available
        
        # Retseptni topish
        recipe = db.query(Recipe).filter(Recipe.product_id == product.id).first()
        if not recipe:
            continue
        
        # Yarim tayyor omborida yarim tayyor mahsulot bormi?
        semi_finished_stock = check_semi_finished_stock(recipe, needed)
        
        if semi_finished_stock >= needed:
            # Yarim tayyor yetarli → kesish + qadoqlash
            production = Production(
                recipe_id=recipe.id,
                quantity=needed,
                current_stage=3,  # Kesishdan boshlanadi
                max_stage=4,
                order_id=order.id,  # Buyurtmaga bog'langan
                ...
            )
            # Kesish va qadoqlash foydalanuvchilariga notification
            notify_users(["kesish", "qadoqlash"], f"Buyurtma {order.number} uchun ishlab chiqarish kerak")
        else:
            # Yarim tayyor yetmasa → to'liq jarayon
            production = Production(
                recipe_id=recipe.id,
                quantity=needed,
                current_stage=1,  # Qiyomdan boshlanadi
                max_stage=4,
                order_id=order.id,
                ...
            )
            # Qiyom quyush foydalanuvchilariga notification
            notify_users(["qiyom"], f"Buyurtma {order.number} uchun qiyom tayyorlash kerak")
        
        production_orders.append(production)
        db.add(production)
    
    db.commit()
    return production_orders
```

### 3. Notification Tizimi

```python
def notify_users(stages, message):
    """Ishlab chiqarish bosqichlari foydalanuvchilariga habar yuborish"""
    # stages = ["qiyom", "kesish", "qadoqlash"]
    # Bu bosqichlarda ishlaydigan foydalanuvchilarni topish
    # Notification yaratish
```

---

## Hozirgi Kodda Nima Bor?

### Order Modeli:
- `type`: "sale", "purchase", "return_sale", "return_purchase"
- `status`: "draft", "confirmed", "completed", "cancelled"
- **"order" type yo'q** — faqat "sale" bor

### Production Modeli:
- `status`: "draft", "in_progress", "completed", "cancelled"
- `current_stage`: 1-4
- `max_stage`: retseptdagi bosqichlar soni
- **Order bilan bog'lanish yo'q** — `order_id` maydoni yo'q

### Recipe Modeli:
- `product_id`: Qaysi mahsulot uchun retsept
- `items`: Xom ashyo ro'yxati
- `stages`: Ishlab chiqarish bosqichlari

---

## Taklif Qilingan O'zgarishlar

### 1. Order Modeliga Qo'shish:
```python
# Order modelida:
order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)  # Buyurtmaga bog'lanish
production_id = Column(Integer, ForeignKey("productions.id"), nullable=True)  # Ishlab chiqarishga bog'lanish
```

### 2. Production Modeliga Qo'shish:
```python
# Production modelida:
order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)  # Qaysi buyurtma uchun
```

### 3. Yangi Funksiyalar:
- `check_stock_for_order(order)` — buyurtma uchun qoldiq tekshiruvi
- `create_production_from_order(order)` — buyurtmadan ishlab chiqarish yaratish
- `check_semi_finished_stock(recipe, quantity)` — yarim tayyor mahsulot tekshiruvi
- `notify_production_users(stages, message)` — foydalanuvchilarga habar

---

## Qisqacha Jarayon

```
1. Agent/Menejer buyurtma yaratadi
   ↓
2. Qoldiq tekshiruvi (tayyor mahsulot ombori)
   ├─ Yetarli → Sotuvga o'tkaziladi
   └─ Yetarli emas → 
       ↓
3. Yarim tayyor tekshiruvi
   ├─ Yetarli → Kesish + qadoqlash (bosqich 3-4)
   └─ Yetarli emas → Qiyom quyush (bosqich 1-4)
       ↓
4. Ishlab chiqarish buyurtmasi yaratiladi
   ↓
5. Tegishli foydalanuvchilarga notification
   ↓
6. Ishlab chiqarish yakunlanganda → Buyurtma tasdiqlanadi
```

---

## Keyingi Qadamlar

1. **Order modeliga `order_id` va `production_id` qo'shish**
2. **Production modeliga `order_id` qo'shish**
3. **Buyurtma yaratishda qoldiq tekshiruvi funksiyasi**
4. **Yarim tayyor mahsulot tekshiruvi funksiyasi**
5. **Notification tizimi (foydalanuvchilarga habar)**
6. **Buyurtmalar ro'yxati sahifasi** (agar alohida bo'lim kerak bo'lsa)

Agar bu funksiyalarni qo'shishni xohlasangiz, yozing — kodlaymiz!
