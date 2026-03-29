from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, Date, UniqueConstraint, Table, text
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from datetime import datetime
import os
import logging

logger = logging.getLogger("database")

Base = declarative_base()

# Loyiha ildizidagi baza (qayerdan ishga tushirilmasa ham bir xil fayl)
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_db_path = os.path.join(_root, "totli_holva.db")
DATABASE_URL = f"sqlite:///{_db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    echo=False,
)

employee_piecework_tasks = Table(
    "employee_piecework_tasks",
    Base.metadata,
    Column("employee_id", Integer, ForeignKey("employees.id"), primary_key=True),
    Column("task_id", Integer, ForeignKey("piecework_tasks.id"), primary_key=True),
)


def _set_sqlite_pragma(conn, _):
    """Har bir ulanishda SQLite tezligini oshirish uchun PRAGMA."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-64000")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


from sqlalchemy import event
event.listen(engine, "connect", _set_sqlite_pragma)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================================
# TOVAR KIRIMI (PURCHASE)
# ==========================================

class Purchase(Base):
    """Tovar kirim hujjati"""
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    total = Column(Float, default=0)
    total_expenses = Column(Float, default=0)  # Xarajatlar jami (so'm)
    status = Column(String(20), default="draft")
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    expense_cash_register_id = Column(Integer, ForeignKey("cash_registers.id"), nullable=True)  # Xarajatlar (yo'l kiro va b.) qaysi kassadan
    expense_direction_id = Column(Integer, ForeignKey("directions.id"), nullable=True)   # Xarajatlar qaysi yo'nalishdan
    expense_department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)  # Xarajatlar qaysi bo'limdan

    items = relationship("PurchaseItem", back_populates="purchase")
    expenses = relationship("PurchaseExpense", back_populates="purchase")
    partner = relationship("Partner")
    warehouse = relationship("Warehouse")
    expense_cash_register = relationship("CashRegister", foreign_keys=[expense_cash_register_id], lazy="select")
    expense_direction = relationship("Direction", foreign_keys=[expense_direction_id], lazy="select")
    expense_department = relationship("Department", foreign_keys=[expense_department_id], lazy="select")

class PurchaseItem(Base):
    """Kirim qatorlari"""
    __tablename__ = "purchase_items"
    id = Column(Integer, primary_key=True, index=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Float)
    price = Column(Float)
    total = Column(Float)
    purchase = relationship("Purchase", back_populates="items")
    product = relationship("Product")


class PurchaseExpense(Base):
    """Tovar kirimi xarajatlari"""
    __tablename__ = "purchase_expenses"
    id = Column(Integer, primary_key=True, index=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"))
    name = Column(String(200))   # Xarajat turi/nomi (yo'l, yuk, boj, ...)
    amount = Column(Float)       # Summa (so'm)
    created_at = Column(DateTime, default=datetime.now)

    purchase = relationship("Purchase", back_populates="expenses")


# ==========================================
# FOYDALANUVCHILAR
# ==========================================

class User(Base):
    """Foydalanuvchilar"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    password_hash = Column(String(255))
    full_name = Column(String(100))
    role = Column(String(20), default="user")  # admin, manager, user, sotuvchi
    phone = Column(String(20))
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)  # Bo'lim
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)   # Ombor
    cash_register_id = Column(Integer, ForeignKey("cash_registers.id"), nullable=True)  # Kassa
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    department = relationship("Department", foreign_keys=[department_id], backref="users")
    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id], backref="users")
    cash_register = relationship("CashRegister", foreign_keys=[cash_register_id], backref="users")
    # Bir nechta bo'lim, ombor, kassa, kontragent (ro'yxat)
    departments_list = relationship("Department", secondary="user_departments", backref="users_list_dept", lazy="select")
    warehouses_list = relationship("Warehouse", secondary="user_warehouses", backref="users_list_wh", lazy="select")
    cash_registers_list = relationship("CashRegister", secondary="user_cash_registers", backref="users_list_cash", lazy="select")
    partners_list = relationship("Partner", secondary="user_partners", backref="users_list_partner", lazy="select")


# ==========================================
# CHAT (User↔User DM, Admin↔User Support)
# ==========================================

class ChatThread(Base):
    __tablename__ = "chat_threads"
    __table_args__ = (
        # direct: user1_id/user2_id kombinatsiyasi unik (user1_id < user2_id sifatida saqlanadi)
        UniqueConstraint("type", "user1_id", "user2_id", name="uq_chat_direct_pair"),
        # support: bitta user uchun bitta support thread
        UniqueConstraint("type", "support_user_id", name="uq_chat_support_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(20), default="direct")  # direct | support | group
    name = Column(String(200), nullable=True)  # group uchun nom
    created_at = Column(DateTime, default=datetime.now)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # direct uchun
    user1_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user2_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # support uchun (murojaat qilgan user)
    support_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_id], lazy="select")
    user1 = relationship("User", foreign_keys=[user1_id], lazy="select")
    user2 = relationship("User", foreign_keys=[user2_id], lazy="select")
    support_user = relationship("User", foreign_keys=[support_user_id], lazy="select")

    participants = relationship("ChatParticipant", back_populates="thread", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="thread", cascade="all, delete-orphan")


class ChatParticipant(Base):
    __tablename__ = "chat_participants"
    __table_args__ = (UniqueConstraint("thread_id", "user_id", name="uq_chat_participant"),)

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("chat_threads.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    role = Column(String(20), default="member")  # member | admin (support)
    last_read_at = Column(DateTime, nullable=True)
    unread_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    thread = relationship("ChatThread", back_populates="participants")
    user = relationship("User")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("chat_threads.id"), index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # NULL = Telegram user
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now, index=True)
    telegram_sender_name = Column(String(200), nullable=True)  # Telegram dan kelgan xabar uchun

    thread = relationship("ChatThread", back_populates="messages")
    sender = relationship("User")


class ChatTelegramLink(Base):
    """Telegram foydalanuvchini chat threadga bog'lash"""
    __tablename__ = "chat_telegram_links"
    __table_args__ = (
        UniqueConstraint("thread_id", "telegram_chat_id", name="uq_tg_thread_chat"),
    )

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("chat_threads.id"), index=True)
    telegram_chat_id = Column(String(50), index=True)  # Telegram user yoki group chat_id
    telegram_username = Column(String(100), nullable=True)
    telegram_full_name = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    thread = relationship("ChatThread")


# ==========================================
# TOVARLAR VA XOM ASHYO
# ==========================================

class Category(Base):
    """Kategoriyalar"""
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(100), index=True)
    type = Column(String(20))  # product, material
    description = Column(Text)
    
    products = relationship("Product", back_populates="category")


class Unit(Base):
    """O'lchov birliklari"""
    __tablename__ = "units"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, index=True)  # kg, dona, l
    name = Column(String(50))  # Kilogram, Dona, Litr
    
    products = relationship("Product", back_populates="unit")


class Product(Base):
    """Mahsulotlar va xom ashyolar"""
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=True, default=None)
    name = Column(String(200), index=True)
    type = Column(String(20))  # product, material (mahsulot yoki xom ashyo)
    category_id = Column(Integer, ForeignKey("categories.id"))
    unit_id = Column(Integer, ForeignKey("units.id"))
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=True)  # Yo'nalish
    purchase_price = Column(Float, default=0)  # Sotib olish narxi
    sale_price = Column(Float, default=0)  # Sotish narxi
    min_stock = Column(Float, default=0)  # Minimal qoldiq
    barcode = Column(String(50))
    image = Column(String(255))  # Rasm fayli nomi
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    category = relationship("Category", back_populates="products")
    unit = relationship("Unit", back_populates="products")
    stock_items = relationship("Stock", back_populates="product")
    recipe_items = relationship("RecipeItem", back_populates="product")
    product_prices = relationship("ProductPrice", back_populates="product", cascade="all, delete-orphan")


class PriceType(Base):
    """Narx turlari (Chakana, Ulgurji, VIP va h.k.) — har bir mijoz turi uchun narx"""
    __tablename__ = "price_types"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, index=True, nullable=True)
    is_active = Column(Boolean, default=True)
    product_prices = relationship("ProductPrice", back_populates="price_type")


class ProductPrice(Base):
    """Mahsulot narxi narx turi bo'yicha (har bir tur uchun alohida sotuv narxi)"""
    __tablename__ = "product_prices"
    __table_args__ = (UniqueConstraint("product_id", "price_type_id", name="uq_product_price_type"),)
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    price_type_id = Column(Integer, ForeignKey("price_types.id"), nullable=False)
    sale_price = Column(Float, default=0)
    product = relationship("Product", back_populates="product_prices")
    price_type = relationship("PriceType", back_populates="product_prices")


class ProductPriceHistory(Base):
    """Narx o'zgarishi hujjati — har bir saqlash avvalgi va yangi narxlarni tarixda qoldiradi"""
    __tablename__ = "product_price_history"
    id = Column(Integer, primary_key=True, index=True)
    doc_number = Column(String(50), unique=True, index=True, nullable=False)  # PN-YYYYMMDD-NNN
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    price_type_id = Column(Integer, ForeignKey("price_types.id"), nullable=True)  # None = umumiy sotuv narxi
    old_purchase_price = Column(Float, default=0)
    new_purchase_price = Column(Float, default=0)
    old_sale_price = Column(Float, default=0)
    new_sale_price = Column(Float, default=0)
    changed_at = Column(DateTime, default=datetime.now)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    product = relationship("Product", backref="price_history")
    price_type = relationship("PriceType", backref="price_history")
    changed_by = relationship("User", backref="price_change_docs")


# ==========================================
# OMBORLAR VA QOLDIQLAR
# ==========================================

class Warehouse(Base):
    """Omborlar"""
    __tablename__ = "warehouses"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(100), index=True)
    address = Column(String(255))
    responsible_id = Column(Integer, ForeignKey("users.id"))
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)  # Bo'limga biriktirish
    is_active = Column(Boolean, default=True)
    
    stocks = relationship("Stock", back_populates="warehouse")
    department = relationship("Department", back_populates="warehouses")


class Stock(Base):
    """Ombor qoldiqlari"""
    __tablename__ = "stocks"
    
    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Float, default=0)
    cost_price = Column(Float, default=0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    warehouse = relationship("Warehouse", back_populates="stocks")
    product = relationship("Product", back_populates="stock_items")
    movements = relationship("StockMovement", back_populates="stock", order_by="StockMovement.created_at.desc()")


class StockMovement(Base):
    """Ombor harakati - har bir operatsiya uchun hujjat"""
    __tablename__ = "stock_movements"
    
    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=True)  # null bo'lishi mumkin (yangi qoldiq)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    # Operatsiya turi va hujjat
    operation_type = Column(String(50), nullable=False)  # purchase, production, transfer_in, transfer_out, sale, adjustment, other
    document_type = Column(String(50), nullable=False)  # Purchase, Production, WarehouseTransfer, Sale, StockAdjustmentDoc
    document_id = Column(Integer, nullable=False)  # Hujjat ID
    document_number = Column(String(100), nullable=True)  # Hujjat raqami (ko'rsatish uchun)
    
    # Harakat miqdori
    quantity_change = Column(Float, nullable=False)  # O'zgarish miqdori (+ kirim, - chiqim)
    quantity_after = Column(Float, nullable=False)  # O'zgarishdan keyingi qoldiq
    
    # Qo'shimcha ma'lumotlar
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Operatsiyani bajargan foydalanuvchi
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    
    # Relationships
    stock = relationship("Stock", back_populates="movements")
    warehouse = relationship("Warehouse")
    product = relationship("Product")
    user = relationship("User")


class WarehouseTransfer(Base):
    """Ombordan omborga o'tkazish hujjati"""
    __tablename__ = "warehouse_transfers"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    from_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    to_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    status = Column(String(20), default="draft")  # draft, pending_approval, confirmed
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Yaratgan foydalanuvchi
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Tasdiqlagan foydalanuvchi (bo'lim foydalanuvchisi)
    approved_at = Column(DateTime, nullable=True)  # Tasdiqlash vaqti
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])
    user = relationship("User", foreign_keys=[user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_user_id])
    items = relationship("WarehouseTransferItem", back_populates="transfer", cascade="all, delete-orphan")


class WarehouseTransferItem(Base):
    """Ombordan omborga o'tkazish hujjati qatori"""
    __tablename__ = "warehouse_transfer_items"
    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey("warehouse_transfers.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Float, default=0)

    transfer = relationship("WarehouseTransfer", back_populates="items")
    product = relationship("Product")


# ==========================================
# TOVAR QOLDIQ HUJJATI (1C uslubida)
# ==========================================

class StockAdjustmentDoc(Base):
    """Tovar qoldiqlari hujjati (bitta hujjat — bir nechta qator)"""
    __tablename__ = "stock_adjustment_docs"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # Inventarizatsiya: bitta hujjat = bitta ombor
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="draft")  # draft, confirmed
    total_tannarx = Column(Float, default=0)   # Jami summa tannarx (so'm)
    total_sotuv = Column(Float, default=0)     # Jami sotuv summa (so'm)
    created_at = Column(DateTime, default=datetime.now)

    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id])
    user = relationship("User")
    items = relationship("StockAdjustmentDocItem", back_populates="doc", cascade="all, delete-orphan")


class StockAdjustmentDocItem(Base):
    """Tovar qoldiq hujjati qatori"""
    __tablename__ = "stock_adjustment_doc_items"
    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(Integer, ForeignKey("stock_adjustment_docs.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    quantity = Column(Float)                    # Haqiqiy (yangilangan) qoldiq
    previous_quantity = Column(Float, nullable=True)  # Tasdiqlashdan oldingi qoldiq (bekor qilish uchun)
    cost_price = Column(Float, default=0)   # Tannarx (so'm)
    sale_price = Column(Float, default=0)     # Sotuv narxi (so'm)

    doc = relationship("StockAdjustmentDoc", back_populates="items")
    product = relationship("Product")
    warehouse = relationship("Warehouse")


# ==========================================
# KASSA QOLDIQ HUJJATI (1C uslubida)
# ==========================================

class CashBalanceDoc(Base):
    """Kassa qoldiqlari hujjati"""
    __tablename__ = "cash_balance_docs"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="draft")  # draft, confirmed
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User")
    items = relationship("CashBalanceDocItem", back_populates="doc", cascade="all, delete-orphan")


class CashBalanceDocItem(Base):
    """Kassa qoldiq hujjati qatori — bitta kassa, yangi balans"""
    __tablename__ = "cash_balance_doc_items"
    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(Integer, ForeignKey("cash_balance_docs.id"))
    cash_register_id = Column(Integer, ForeignKey("cash_registers.id"))
    balance = Column(Float, default=0)
    previous_balance = Column(Float, default=None)  # Tasdiqdan oldingi balans (revert uchun)

    doc = relationship("CashBalanceDoc", back_populates="items")
    cash_register = relationship("CashRegister")


class CashTransfer(Base):
    """Kassadan kassaga o'tkazish: bitta kassadan ikkinchisiga pul, jo'natuvchi yuboradi — qabul qiluvchi tasdiqlaydi"""
    __tablename__ = "cash_transfers"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    from_cash_id = Column(Integer, ForeignKey("cash_registers.id"), nullable=False)
    to_cash_id = Column(Integer, ForeignKey("cash_registers.id"), nullable=False)
    amount = Column(Float, default=0)
    status = Column(String(20), default="pending")  # pending, in_transit, completed, cancelled
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Yaratuvchi (admin)
    sent_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Sotuvchi (pulni bergan)
    sent_at = Column(DateTime, nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Admin (pulni qabul qilgan)
    approved_at = Column(DateTime, nullable=True)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    from_cash = relationship("CashRegister", foreign_keys=[from_cash_id])
    to_cash = relationship("CashRegister", foreign_keys=[to_cash_id])
    user = relationship("User", foreign_keys=[user_id])
    sent_by = relationship("User", foreign_keys=[sent_by_user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_user_id])


# ==========================================
# KONTRAGENT QOLDIQ HUJJATI (1C uslubida)
# ==========================================

class PartnerBalanceDoc(Base):
    """Kontragent qoldiqlari (balans) hujjati"""
    __tablename__ = "partner_balance_docs"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="draft")  # draft, confirmed
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User")
    items = relationship("PartnerBalanceDocItem", back_populates="doc", cascade="all, delete-orphan")


class PartnerBalanceDocItem(Base):
    """Kontragent balans hujjati qatori"""
    __tablename__ = "partner_balance_doc_items"
    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(Integer, ForeignKey("partner_balance_docs.id"))
    partner_id = Column(Integer, ForeignKey("partners.id"))
    balance = Column(Float, default=0)
    previous_balance = Column(Float, default=None)  # Tasdiqdan oldingi balans (revert uchun)

    doc = relationship("PartnerBalanceDoc", back_populates="items")
    partner = relationship("Partner")


# ==========================================
# ISHLAB CHIQARISH
# ==========================================

class Recipe(Base):
    """Retseptlar (mahsulot tarkibi)"""
    __tablename__ = "recipes"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))  # Qaysi mahsulot uchun
    name = Column(String(200))
    output_quantity = Column(Float, default=1)  # Chiqish miqdori
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    default_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # Retseptda tanlangan 1-ombor (xom ashyo)
    default_output_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # Retseptda tanlangan 2-ombor (yarim tayyor)
    
    product = relationship("Product")
    items = relationship("RecipeItem", back_populates="recipe")
    stages = relationship("RecipeStage", back_populates="recipe", order_by="RecipeStage.stage_number", cascade="all, delete-orphan")


class RecipeStage(Base):
    """Retseptga bog'langan ishlab chiqarish bosqichlari"""
    __tablename__ = "recipe_stages"
    __table_args__ = (UniqueConstraint("recipe_id", "stage_number", name="uq_recipe_stage_number"),)

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    stage_number = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)

    recipe = relationship("Recipe", back_populates="stages")


class RecipeItem(Base):
    """Retsept tarkibi"""
    __tablename__ = "recipe_items"
    
    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"))
    product_id = Column(Integer, ForeignKey("products.id"))  # Xom ashyo
    quantity = Column(Float)  # Miqdori
    
    recipe = relationship("Recipe", back_populates="items")
    product = relationship("Product", back_populates="recipe_items")


class Production(Base):
    """Ishlab chiqarish"""
    __tablename__ = "productions"
    
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    recipe_id = Column(Integer, ForeignKey("recipes.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))  # 1-ombor: xom ashyo ombori (material shu yerdan olinadi)
    output_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # 2-ombor: yarim tayyor ombori (mahsulot shu yerga yoziladi)
    quantity = Column(Float)  # Ishlab chiqarilgan miqdor (o'zgarmaydi)
    status = Column(String(20), default="draft")  # draft, in_progress, completed, cancelled
    current_stage = Column(Integer, default=1)  # joriy bosqich (1 dan max_stage gacha)
    max_stage = Column(Integer, nullable=True)   # retseptdagi bosqichlar soni (yoki 4)
    user_id = Column(Integer, ForeignKey("users.id"))
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)  # Qaysi uskunda (oxirgi bosqich)
    operator_id = Column(Integer, ForeignKey("employees.id"), nullable=True)  # Operator (xodim)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    recipe = relationship("Recipe")
    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id])
    machine = relationship("Machine")
    operator = relationship("Employee", foreign_keys=[operator_id])
    user = relationship("User", foreign_keys=[user_id])
    output_warehouse = relationship("Warehouse", foreign_keys=[output_warehouse_id])
    production_items = relationship("ProductionItem", back_populates="production", cascade="all, delete-orphan")
    stages = relationship("ProductionStage", back_populates="production", cascade="all, delete-orphan", order_by="ProductionStage.stage_number")


class ProductionItem(Base):
    """Ishlab chiqarish buyurtmasidagi xom ashyo miqdori (shu buyurtma uchun tahrirlanadi, retsept o'zgarmaydi)"""
    __tablename__ = "production_items"
    
    id = Column(Integer, primary_key=True, index=True)
    production_id = Column(Integer, ForeignKey("productions.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Float)  # Shu buyurtma uchun ishlatiladigan miqdor (kg)

    production = relationship("Production", back_populates="production_items")
    product = relationship("Product")


# Ishlab chiqarish 4 bosqichi: 1) qiyom 2) qiyomga qo'shimchalar → yarim tayyor 3) holva kesish 4) qadoqlash
PRODUCTION_STAGE_NAMES = {
    1: "Qiyom tayyorlash",
    2: "Qiyomga qo'shiladigan mahsulotlar, yarim tayyor",
    3: "Holva kesish",
    4: "Qadoqlash",
}


class ProductionStage(Base):
    """Ishlab chiqarish buyurtmasining har bir bosqichi (1–4)"""
    __tablename__ = "production_stages"

    id = Column(Integer, primary_key=True, index=True)
    production_id = Column(Integer, ForeignKey("productions.id"), nullable=False)
    stage_number = Column(Integer, nullable=False)  # 1, 2, 3, 4
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    operator_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    quantity_in = Column(Float, nullable=True)   # Kiruvchi miqdor (kg)
    quantity_out = Column(Float, nullable=True)  # Chiquvchi miqdor (kg)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    production = relationship("Production", back_populates="stages")
    machine = relationship("Machine")
    operator = relationship("Employee", foreign_keys=[operator_id])


class Machine(Base):
    """Ishlab chiqarish uskunalari"""
    __tablename__ = "machines"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(200), index=True)
    machine_type = Column(String(100))  # mixer, oven, packaging, etc.
    status = Column(String(20), default="idle")  # idle, active, maintenance, broken
    operator_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    capacity = Column(Float)  # Maximum capacity per hour
    efficiency = Column(Float, default=100.0)  # Current efficiency percentage
    last_maintenance = Column(DateTime, nullable=True)
    next_maintenance = Column(DateTime, nullable=True)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    operator = relationship("Employee", foreign_keys=[operator_id])


class PieceworkTask(Base):
    """Bajariladigan ishlar (bo'lak narxi) — 1 birlik ish narxi."""
    __tablename__ = "piecework_tasks"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=True)
    name = Column(String(200), nullable=True)
    price_per_unit = Column(Float, default=0)
    unit_name = Column(String(50), nullable=True)  # dona, kg, m
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


# ==========================================
# KONTRAGENTLAR (MIJOZLAR, YETKAZUVCHILAR)
# ==========================================

class Partner(Base):
    """Kontragentlar"""
    __tablename__ = "partners"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(200), index=True)  # Savdo nuqtasi nomi
    legal_name = Column(String(200), nullable=True)  # Yuridik nomi
    type = Column(String(20))  # customer, supplier, both
    
    # Contact Information
    contact_person = Column(String(100), nullable=True)  # Aloqa shaxsi
    phone = Column(String(20))
    phone2 = Column(String(20), nullable=True)  # Qo'shimcha telefon
    
    # Address
    address = Column(String(255))
    landmark = Column(String(255), nullable=True)  # Mo'ljal
    
    # Location
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    # Business Details
    visit_day = Column(Integer, nullable=True)  # Tashrif kuni (0-6)
    category = Column(String(10), nullable=True)  # A, B, C, D
    region = Column(String(50), nullable=True)  # Hudud
    customer_type = Column(String(50), nullable=True)  # retail, wholesale, horeca, distributor
    sales_channel = Column(String(50), nullable=True)  # direct, distributor, online
    product_categories = Column(String(100), nullable=True)  # food, drinks, household, cosmetics
    
    # Financial
    inn = Column(String(20), nullable=True)
    balance = Column(Float, default=0)  # Balans (qarzdorlik)
    credit_limit = Column(Float, default=0)  # Kredit limiti
    discount_percent = Column(Float, default=0)  # Chegirma foizi
    
    # Requisites
    account = Column(String(50), nullable=True)  # Hisob raqami
    bank = Column(String(100), nullable=True)  # Bank
    mfo = Column(String(20), nullable=True)  # MFO
    oked = Column(String(20), nullable=True)  # OKED
    pinfl = Column(String(20), nullable=True)  # PINFL
    contract_number = Column(String(50), nullable=True)  # Shartnoma raqami
    contract_date = Column(Date, nullable=True)  # Shartnoma sanasi
    
    # Other
    notes = Column(Text, nullable=True)  # Izoh
    photo = Column(String(255), nullable=True)  # Rasm fayli nomi
    agent_id = Column(Integer, nullable=True)  # Qaysi agent qo'shgan
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    orders = relationship("Order", back_populates="partner")
    payments = relationship("Payment", back_populates="partner")


# ==========================================
# BUYURTMALAR VA SOTISH
# ==========================================

class Order(Base):
    """Buyurtmalar va sotuvlar"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    type = Column(String(20))  # sale, purchase, return_sale, return_purchase
    partner_id = Column(Integer, ForeignKey("partners.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    price_type_id = Column(Integer, ForeignKey("price_types.id"), nullable=True)  # Sotuvda qaysi narx turi ishlatiladi
    user_id = Column(Integer, ForeignKey("users.id"))
    subtotal = Column(Float, default=0)  # Jami (chegirmasiz)
    discount_percent = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    total = Column(Float, default=0)  # Jami (chegirmali)
    paid = Column(Float, default=0)  # To'langan
    debt = Column(Float, default=0)  # Qarz
    status = Column(String(20), default="draft")  # draft, confirmed, completed, cancelled
    payment_type = Column(String(20), nullable=True)  # naqd, plastik — to'lov turi (POS sotuvlar uchun)
    payment_due_date = Column(Date, nullable=True)  # Qarz bo'lganda to'lov muddati (boshqa kontragent)
    note = Column(Text)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    source = Column(String(20), default="web")  # "web" | "agent"
    created_at = Column(DateTime, default=datetime.now)

    partner = relationship("Partner", back_populates="orders")
    warehouse = relationship("Warehouse")
    items = relationship("OrderItem", back_populates="order")
    price_type = relationship("PriceType")
    user = relationship("User", foreign_keys=[user_id])
    agent = relationship("Agent", foreign_keys=[agent_id])


class OrderItem(Base):
    """Buyurtma qatorlari"""
    __tablename__ = "order_items"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # Qator uchun ombor (barcha omborlardan sotuvda)
    quantity = Column(Float)
    price = Column(Float)
    discount_percent = Column(Float, default=0)
    total = Column(Float)
    
    order = relationship("Order", back_populates="items")
    product = relationship("Product")
    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id])


class PosDraft(Base):
    """POS: vaqtinchalik saqlangan chek (savat). Chekni saqlash / Chekni yuklash."""
    __tablename__ = "pos_drafts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    name = Column(String(200), nullable=True)  # ixtiyoriy nom (masalan "Chek 12:30")
    items_json = Column(Text, nullable=False)  # [{"productId", "productName", "price", "quantity"}, ...]
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User")
    warehouse = relationship("Warehouse")


# ==========================================
# MOLIYA (KASSA)
# ==========================================

class CashRegister(Base):
    """Kassalar. payment_type: POS da qaysi to'lov turiga bog'lanishi (naqd, plastik, click, terminal).
    Balans = opening_balance (qoldiq) + kirim − chiqim. Qoldiq «Kassa qoldiq hujjati» orqali kiritiladi."""
    __tablename__ = "cash_registers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    balance = Column(Float, default=0)  # Eski maydon (saqlandi); ko'rsatish opening_balance + kirim - chiqim
    opening_balance = Column(Float, default=0)  # Qoldiq — faqat qoldiq hujjati orqali o'rnatiladi
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)  # Bo'limga biriktirish
    payment_type = Column(String(20), nullable=True)  # naqd, plastik, click, terminal — POS to'lov turi
    is_active = Column(Boolean, default=True)
    
    department = relationship("Department", back_populates="cash_registers")


# Foydalanuvchi — bir nechta bo'lim, ombor, kassa (many-to-many)
user_departments = Table(
    "user_departments",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("department_id", Integer, ForeignKey("departments.id"), primary_key=True),
)
user_warehouses = Table(
    "user_warehouses",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("warehouse_id", Integer, ForeignKey("warehouses.id"), primary_key=True),
)
user_cash_registers = Table(
    "user_cash_registers",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("cash_register_id", Integer, ForeignKey("cash_registers.id"), primary_key=True),
)
user_partners = Table(
    "user_partners",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("partner_id", Integer, ForeignKey("partners.id"), primary_key=True),
)


class Payment(Base):
    """To'lovlar"""
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    type = Column(String(20))  # income, expense (kirim, chiqim)
    cash_register_id = Column(Integer, ForeignKey("cash_registers.id"))
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    amount = Column(Float)
    payment_type = Column(String(20))  # cash, card, transfer
    category = Column(String(50))  # sale, purchase, salary, rent, other
    description = Column(Text)
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(20), default="confirmed")  # confirmed, cancelled — admin tasdiqlash/bekor qilish
    created_at = Column(DateTime, default=datetime.now)
    
    partner = relationship("Partner", back_populates="payments")
    cash_register = relationship("CashRegister", foreign_keys=[cash_register_id])


# ==========================================
# HARAJATLAR JURNALI (1C uslubida)
# ==========================================

class ExpenseType(Base):
    """Harajat turlari (ish haqqi, ishxona harajati, ...)."""
    __tablename__ = "expense_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=True)  # Ishlab chiqarish, Ma'muriy
    is_active = Column(Boolean, default=True)


class ExpenseDoc(Base):
    """Harajat hujjati — bitta hujjat, bir nechta qator (harajat turi + summa)."""
    __tablename__ = "expense_docs"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    cash_register_id = Column(Integer, ForeignKey("cash_registers.id"), nullable=False)
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=True)  # Yo'nalishdan
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)  # Bo'limdan
    status = Column(String(20), default="draft")  # draft, confirmed
    total_amount = Column(Float, default=0)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)  # Tasdiqlanganda yaratiladi
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    cash_register = relationship("CashRegister")
    direction = relationship("Direction")
    department = relationship("Department")
    payment = relationship("Payment", foreign_keys=[payment_id])
    user = relationship("User")
    items = relationship("ExpenseDocItem", back_populates="expense_doc", cascade="all, delete-orphan")


class ExpenseDocItem(Base):
    """Harajat hujjati qatori — harajat turi, summa, izoh."""
    __tablename__ = "expense_doc_items"

    id = Column(Integer, primary_key=True, index=True)
    expense_doc_id = Column(Integer, ForeignKey("expense_docs.id"), nullable=False)
    expense_type_id = Column(Integer, ForeignKey("expense_types.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)  # Bo'limga
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=True)  # Yo'nalishga
    amount = Column(Float, nullable=False)
    description = Column(Text, nullable=True)

    expense_doc = relationship("ExpenseDoc", back_populates="items")
    expense_type = relationship("ExpenseType")
    department = relationship("Department")
    direction = relationship("Direction")


# ==========================================
# XODIMLAR
# ==========================================

class Employee(Base):
    """Xodimlar"""
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    full_name = Column(String(200), index=True)
    position = Column(String(100))
    department = Column(String(100))  # Eski maydon (deprecated)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)  # Yangi maydon
    phone = Column(String(20))
    address = Column(String(255))
    hire_date = Column(Date)
    birth_date = Column(Date, nullable=True)  # Tug'ilgan kun (bosh sahifa bildirishnomalari uchun)
    salary = Column(Float, default=0)
    salary_type = Column(String(50), nullable=True)  # oylik, soatlik, bo'lak
    piecework_task_id = Column(Integer, ForeignKey("piecework_tasks.id"), nullable=True)  # Bo'lak turi uchun ish
    is_active = Column(Boolean, default=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    hikvision_id = Column(String(50))  # Hikvision tizimidagi ID
    created_at = Column(DateTime, default=datetime.now)

    salaries = relationship("Salary", back_populates="employee")
    piecework_tasks = relationship("PieceworkTask", secondary=employee_piecework_tasks, backref="employees")


class Salary(Base):
    """Ish haqi (oylik)"""
    __tablename__ = "salaries"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    year = Column(Integer)
    month = Column(Integer)
    base_salary = Column(Float, default=0)
    bonus = Column(Float, default=0)
    deduction = Column(Float, default=0)
    advance_deduction = Column(Float, default=0)  # Avans ushlab qolish
    total = Column(Float, default=0)
    paid = Column(Float, default=0)
    status = Column(String(20), default="pending")  # pending, paid
    created_at = Column(DateTime, default=datetime.now)
    
    employee = relationship("Employee", back_populates="salaries")


class Attendance(Base):
    """Davomat yozuvi (kunlik — bitta xodim, bitta sana)"""
    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_attendance_employee_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    date = Column(Date, nullable=False)
    doc_id = Column(Integer, ForeignKey("attendance_docs.id"), nullable=True)
    check_in = Column(DateTime, nullable=True)
    check_out = Column(DateTime, nullable=True)
    hours_worked = Column(Float, default=0)
    status = Column(String(20), default="present")  # present, absent, leave, kasallik, tatil, mehnat_safari
    event_snapshot_path = Column(String(255), nullable=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    employee = relationship("Employee", backref="attendances")
    doc = relationship("AttendanceDoc", backref="attendances")


class AttendanceDoc(Base):
    """Kunlik tabel hujjati (sana bo'yicha tasdiqlangan davomat)"""
    __tablename__ = "attendance_docs"
    
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    date = Column(Date, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    user = relationship("User")


class EmployeeAdvance(Base):
    """Xodimga berilgan avans"""
    __tablename__ = "employee_advances"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    cash_register_id = Column(Integer, ForeignKey("cash_registers.id"), nullable=True)  # Qaysi kassadan berilgani
    amount = Column(Float, default=0)
    advance_date = Column(Date, nullable=False)
    note = Column(String(500), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)  # Tasdiqlangan vaqti
    created_at = Column(DateTime, default=datetime.now)
    
    employee = relationship("Employee", backref="advances")
    cash_register = relationship("CashRegister", foreign_keys=[cash_register_id])


class EmploymentDoc(Base):
    """Ishga qabul qilish hujjati (Mehnat shartnomasi tamoyillari bo'yicha — O'zR Mehnat kodeksi, gov.uz)"""
    __tablename__ = "employment_docs"
    
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    doc_date = Column(Date, nullable=False)   # Hujjat sanasi (imzolangan sana)
    hire_date = Column(Date, nullable=True)   # Ishning boshlanish kuni
    position = Column(String(100), nullable=True)   # Lavozim (mehnat vazifasi)
    department = Column(String(100), nullable=True)   # Ish joyi (korxona/bo'lim)
    salary = Column(Float, default=0)   # Mehnat haqi miqdori
    salary_type = Column(String(50), nullable=True)   # oylik, soatlik, bo'lak — ish haqi turi
    piecework_task_ids = Column(Text, nullable=True)  # Bo'lak turlari snapshot (vergul bilan)
    rest_days = Column(String(100), nullable=True)    # Dam olish kunlari (mon,tue,...)
    probation = Column(String(100), nullable=True)    # Sinov muddati
    # Mehnat shartnomasi muddati (gov.uz: nomuayyan / muayyan muddatga max 5 yil / muayyan ish)
    contract_type = Column(String(50), nullable=True)   # indefinite, fixed, task
    contract_end_date = Column(Date, nullable=True)   # Muayyan muddatga bo'lsa — amal qilish tugash sanasi
    note = Column(String(500), nullable=True)   # Mehnatning boshqa shartlari
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)   # Tasdiqlangan vaqti
    created_at = Column(DateTime, default=datetime.now)
    
    employee = relationship("Employee", backref="employment_docs")
    user = relationship("User")


# Ishlab chiqarish guruhi (masalan qiyomchilar): bitta operator nomidan yozilgan ish kunlik tabel bo'yicha guruh a'zolari orasida teng bo'linadi
production_group_members = Table(
    "production_group_members",
    Base.metadata,
    Column("group_id", Integer, ForeignKey("production_groups.id"), primary_key=True),
    Column("employee_id", Integer, ForeignKey("employees.id"), primary_key=True),
    Column("price_per_unit", Float, default=0),
)


class ProductionGroup(Base):
    """Ishlab chiqarish guruhi (qiyomchilar va h.k.) — operator bitta, ish haqi kunlik davomat bo'yicha a'zolar orasida teng taqsimlanadi"""
    __tablename__ = "production_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # masalan "Qiyomchilar"
    operator_id = Column(Integer, ForeignKey("employees.id"), nullable=False)  # Tizimga kirib buyurtma yakunlovchi (Production.operator_id)
    piecework_task_id = Column(Integer, ForeignKey("piecework_tasks.id"), nullable=True)  # Bo'lak narxi (so'm/kg)
    include_qiyom = Column(Boolean, default=True)  # Qiyom retseptlari ham kg ga kiritilsin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    operator = relationship("Employee", foreign_keys=[operator_id])
    piecework_task = relationship("PieceworkTask")
    members = relationship("Employee", secondary=production_group_members, backref="production_groups")


class DismissalDoc(Base):
    """Ishdan bo'shatish hujjati (O'zR Mehnat kodeksi bo'yicha)"""
    __tablename__ = "dismissal_docs"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True, nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    doc_date = Column(Date, nullable=False)   # Ishdan bo'shatish sanasi
    reason = Column(String(200), nullable=True)   # Sabab (o'z ixtiyori, muddati tugadi, ...)
    note = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    employee = relationship("Employee", backref="dismissal_docs")
    user = relationship("User")


# ==========================================
# SAVDO AGENTLARI
# ==========================================

class Agent(Base):
    """Savdo agentlari"""
    __tablename__ = "agents"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    full_name = Column(String(200), index=True)
    phone = Column(String(20))
    telegram_id = Column(String(50))
    photo = Column(String(255))
    region = Column(String(100))  # Hudud
    is_active = Column(Boolean, default=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    locations = relationship("AgentLocation", back_populates="agent", order_by="AgentLocation.recorded_at.desc()")
    routes = relationship("Route", back_populates="agent")
    visits = relationship("Visit", back_populates="agent")
    orders = relationship("Order", foreign_keys="Order.agent_id", back_populates="agent")


class AgentLocation(Base):
    """Agent joylashuvi (GPS)"""
    __tablename__ = "agent_locations"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    latitude = Column(Float)
    longitude = Column(Float)
    accuracy = Column(Float)  # GPS aniqlik (metr)
    battery = Column(Integer)  # Telefon batareya %
    recorded_at = Column(DateTime, default=datetime.now)
    
    agent = relationship("Agent", back_populates="locations")


# ==========================================
# MARSHRUTLAR
# ==========================================

class Route(Base):
    """Kunlik marshrutlar"""
    __tablename__ = "routes"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    agent_id = Column(Integer, ForeignKey("agents.id"))
    day_of_week = Column(Integer)  # 0=Dushanba, 6=Yakshanba
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    agent = relationship("Agent", back_populates="routes")
    points = relationship("RoutePoint", back_populates="route")


class RoutePoint(Base):
    """Marshrut nuqtalari"""
    __tablename__ = "route_points"
    
    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"))
    partner_id = Column(Integer, ForeignKey("partners.id"))
    order_num = Column(Integer)  # Tartib raqami
    planned_time = Column(String(10))  # "09:00"
    
    route = relationship("Route", back_populates="points")


# ==========================================
# TASHRIFLAR (VIZITLAR)
# ==========================================

class Visit(Base):
    """Agent tashriflari"""
    __tablename__ = "visits"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    partner_id = Column(Integer, ForeignKey("partners.id"))
    visit_date = Column(DateTime, default=datetime.now)
    latitude = Column(Float)
    longitude = Column(Float)
    accuracy = Column(Float)  # GPS accuracy in meters
    check_in_time = Column(DateTime)
    check_out_time = Column(DateTime)
    status = Column(String(20))  # planned, visited, skipped
    notes = Column(Text)
    photo = Column(String(255))
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    
    agent = relationship("Agent", back_populates="visits")
    partner = relationship("Partner", lazy="select")


# ==========================================
# YETKAZIB BERISH
# ==========================================

class Driver(Base):
    """Haydovchilar/Yetkazib beruvchilar"""
    __tablename__ = "drivers"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    full_name = Column(String(200), index=True)
    phone = Column(String(20))
    telegram_id = Column(String(50))
    vehicle_number = Column(String(20))  # Mashina raqami
    vehicle_type = Column(String(50))  # Mashina turi
    is_active = Column(Boolean, default=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    locations = relationship("DriverLocation", back_populates="driver")
    deliveries = relationship("Delivery", back_populates="driver")


class DriverLocation(Base):
    """Haydovchi joylashuvi (GPS)"""
    __tablename__ = "driver_locations"
    
    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(Integer, ForeignKey("drivers.id"))
    latitude = Column(Float)
    longitude = Column(Float)
    accuracy = Column(Float)  # GPS aniqlik (metr)
    battery = Column(Integer)  # Telefon batareya %
    speed = Column(Float)  # Tezlik km/s
    recorded_at = Column(DateTime, default=datetime.now)
    
    driver = relationship("Driver", back_populates="locations")


class Delivery(Base):
    """Yetkazib berishlar"""
    __tablename__ = "deliveries"
    
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    order_number = Column(String(50))  # Buyurtma raqami (qo'lda kiritish uchun)
    delivery_address = Column(String(500))  # Yetkazish manzili
    driver_id = Column(Integer, ForeignKey("drivers.id"))
    status = Column(String(20), default="pending")  # pending, in_progress, delivered, failed
    planned_date = Column(DateTime)
    delivered_at = Column(DateTime)
    latitude = Column(Float)  # Yetkazilgan joy
    longitude = Column(Float)
    photo = Column(String(255))  # Tasdiqlash rasmi
    signature = Column(String(255))  # Imzo
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    
    driver = relationship("Driver", back_populates="deliveries")


# ==========================================
# MIJOZ LOKATSIYALARI
# ==========================================

class PartnerLocation(Base):
    """Mijoz/do'kon manzili"""
    __tablename__ = "partner_locations"
    
    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, ForeignKey("partners.id"))
    name = Column(String(100))  # "Asosiy do'kon", "Filial 1"
    address = Column(String(255))
    latitude = Column(Float)
    longitude = Column(Float)
    is_primary = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


# ==========================================
# BO'LIMLAR VA YO'NALISHLAR
# ==========================================

class Department(Base):
    """Bo'limlar (Ishlab chiqarish, Savdo, Boshqaruv, ...)"""
    __tablename__ = "departments"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(100), index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    warehouses = relationship("Warehouse", back_populates="department")
    cash_registers = relationship("CashRegister", back_populates="department")


class Direction(Base):
    """Yo'nalishlar (Halva, Konfet, Shirinlik, ...)"""
    __tablename__ = "directions"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(100), index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class Position(Base):
    """Lavozimlar"""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(100), index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class Region(Base):
    """Hududlar (Toshkent, Samarqand, Buxoro, ...)"""
    __tablename__ = "regions"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(100), index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


# ==========================================
# BILDIRISHNOMALAR (NOTIFICATIONS)
# ==========================================

class Notification(Base):
    """Tizim bildirish nomalari"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # null = all users
    title = Column(String(200))
    message = Column(Text)
    notification_type = Column(String(50))  # info, warning, error, success
    priority = Column(String(20), default="normal")  # low, normal, high, urgent
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)
    action_url = Column(String(500), nullable=True)  # Optional link
    related_entity_type = Column(String(50), nullable=True)  # order, delivery, stock, etc.
    related_entity_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, nullable=True)


def ensure_recipe_warehouse_columns():
    """recipes jadvaliga default_warehouse_id va default_output_warehouse_id qo'shadi (mavjud bo'lsa o'tkazib yuboriladi)."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(recipes)"))
            cols = [row[1] for row in r]
            if "default_warehouse_id" not in cols:
                conn.execute(text("ALTER TABLE recipes ADD COLUMN default_warehouse_id INTEGER REFERENCES warehouses(id)"))
            if "default_output_warehouse_id" not in cols:
                conn.execute(text("ALTER TABLE recipes ADD COLUMN default_output_warehouse_id INTEGER REFERENCES warehouses(id)"))
    except Exception as e:
        print(f"ensure_recipe_warehouse_columns: {e}")


def ensure_cash_register_payment_type():
    """cash_registers jadvaliga payment_type ustunini qo'shadi (POS to'lov turi: naqd, plastik, click, terminal)."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(cash_registers)"))
            cols = [row[1] for row in r]
            if "payment_type" not in cols:
                conn.execute(text("ALTER TABLE cash_registers ADD COLUMN payment_type VARCHAR(20)"))
                print("cash_registers.payment_type ustuni qo'shildi.")
    except Exception as e:
        print(f"ensure_cash_register_payment_type: {e}")


def ensure_purchase_expense_cash_register():
    """purchases jadvaliga expense_cash_register_id ustunini qo'shadi (xarajatlar qaysi kassadan)."""
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(purchases)"))
            cols = [row[1] for row in r]
            if "expense_cash_register_id" not in cols:
                conn.execute(text("ALTER TABLE purchases ADD COLUMN expense_cash_register_id INTEGER REFERENCES cash_registers(id)"))
                print("purchases.expense_cash_register_id ustuni qo'shildi.")
    except Exception as e:
        print(f"ensure_purchase_expense_cash_register: {e}")


def ensure_purchase_expense_direction_department():
    """purchases jadvaliga expense_direction_id va expense_department_id ustunlarini qo'shadi."""
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(purchases)"))
            cols = [row[1] for row in r]
            if "expense_direction_id" not in cols:
                conn.execute(text("ALTER TABLE purchases ADD COLUMN expense_direction_id INTEGER REFERENCES directions(id)"))
                print("purchases.expense_direction_id ustuni qo'shildi.")
            if "expense_department_id" not in cols:
                conn.execute(text("ALTER TABLE purchases ADD COLUMN expense_department_id INTEGER REFERENCES departments(id)"))
                print("purchases.expense_department_id ustuni qo'shildi.")
    except Exception as e:
        print(f"ensure_purchase_expense_direction_department: {e}")


# Bazani yaratish — faqat jadvallar yaratiladi, mavjud ma'lumotlar o'chirilmaydi (saqlanadi)
def ensure_employee_salary_type():
    """employees jadvalida salary_type ustuni bo'lishini ta'minlash."""
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(employees)"))
            cols = [row[1] for row in r]
            if "salary_type" not in cols:
                conn.execute(text("ALTER TABLE employees ADD COLUMN salary_type VARCHAR(50)"))
            if "piecework_task_id" not in cols:
                conn.execute(text("ALTER TABLE employees ADD COLUMN piecework_task_id INTEGER REFERENCES piecework_tasks(id)"))
    except Exception as e:
        print(f"ensure_employee_salary_type: {e}")


def ensure_employee_piecework_tasks_table():
    """employee_piecework_tasks jadvali mavjudligini ta'minlash."""
    try:
        with engine.begin() as conn:
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='employee_piecework_tasks'"))
            if r.fetchone() is None:
                conn.execute(text("""
                    CREATE TABLE employee_piecework_tasks (
                        employee_id INTEGER NOT NULL REFERENCES employees(id),
                        task_id INTEGER NOT NULL REFERENCES piecework_tasks(id),
                        PRIMARY KEY (employee_id, task_id)
                    )
                """))
    except Exception as e:
        print(f"ensure_employee_piecework_tasks_table: {e}")


def ensure_piecework_tasks_table():
    """piecework_tasks jadvali mavjudligini ta'minlash."""
    try:
        with engine.begin() as conn:
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='piecework_tasks'"))
            if r.fetchone() is None:
                conn.execute(text("""
                    CREATE TABLE piecework_tasks (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        code VARCHAR(50) UNIQUE,
                        name VARCHAR(200),
                        price_per_unit FLOAT DEFAULT 0,
                        unit_name VARCHAR(50),
                        description TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        created_at DATETIME
                    )
                """))
    except Exception as e:
        print(f"ensure_piecework_tasks_table: {e}")


def ensure_production_groups_tables():
    """production_groups va production_group_members jadvalarini ta'minlash."""
    try:
        with engine.begin() as conn:
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='production_groups'"))
            if r.fetchone() is None:
                conn.execute(text("""
                    CREATE TABLE production_groups (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(100) NOT NULL,
                        operator_id INTEGER NOT NULL REFERENCES employees(id),
                        piecework_task_id INTEGER REFERENCES piecework_tasks(id),
                        include_qiyom BOOLEAN DEFAULT 1,
                        is_active BOOLEAN DEFAULT 1,
                        created_at DATETIME
                    )
                """))
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='production_group_members'"))
            if r.fetchone() is None:
                conn.execute(text("""
                    CREATE TABLE production_group_members (
                        group_id INTEGER NOT NULL REFERENCES production_groups(id),
                        employee_id INTEGER NOT NULL REFERENCES employees(id),
                        PRIMARY KEY (group_id, employee_id)
                    )
                """))
    except Exception as e:
        print(f"ensure_production_groups_tables: {e}")


def ensure_dismissal_docs_table():
    """dismissal_docs jadvali mavjudligini ta'minlash."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='dismissal_docs'"))
            if r.fetchone() is None:
                conn.execute(text("""
                    CREATE TABLE dismissal_docs (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        number VARCHAR(50) NOT NULL UNIQUE,
                        employee_id INTEGER NOT NULL REFERENCES employees(id),
                        doc_date DATE NOT NULL,
                        reason VARCHAR(200),
                        note TEXT,
                        user_id INTEGER REFERENCES users(id),
                        created_at DATETIME
                    )
                """))
    except Exception as e:
        print(f"ensure_dismissal_docs_table: {e}")


def ensure_agent_order_columns():
    """orders va agents jadvallariga qo'shimcha kolonkalar qo'shish."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE orders ADD COLUMN agent_id INTEGER REFERENCES agents(id)"))
            except Exception as e:
                logger.debug(f"orders.agent_id already exists: {e}")
            try:
                conn.execute(text("ALTER TABLE orders ADD COLUMN source VARCHAR(20) DEFAULT 'web'"))
            except Exception as e:
                logger.debug(f"orders.source already exists: {e}")
            try:
                conn.execute(text("ALTER TABLE agents ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            except Exception as e:
                logger.debug(f"agents.user_id already exists: {e}")
    except Exception as e:
        logger.error(f"ensure_agent_order_columns: {e}")


def ensure_agent_tasks():
    """agent_tasks jadvalini yaratadi (SQLite)."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    title VARCHAR(200) NOT NULL,
                    description TEXT,
                    due_date DATE,
                    status VARCHAR(20) DEFAULT 'pending',
                    priority VARCHAR(10) DEFAULT 'normal',
                    partner_id INTEGER REFERENCES partners(id),
                    created_at DATETIME,
                    completed_at DATETIME
                )
            """))
    except Exception as e:
        logger.error(f"ensure_agent_tasks: {e}")


def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_agent_tasks()
    ensure_agent_order_columns()
    ensure_recipe_warehouse_columns()
    ensure_cash_register_payment_type()
    ensure_purchase_expense_cash_register()
    ensure_purchase_expense_direction_department()
    ensure_piecework_tasks_table()
    ensure_employee_salary_type()
    ensure_employee_piecework_tasks_table()
    ensure_dismissal_docs_table()
    ensure_production_groups_tables()
    ensure_attendance_improvements()
    print("Database tayyor (mavjud ma'lumotlar saqlanadi).")


def ensure_attendance_advance_tables():
    """Davomat, tabel hujjati va avans jadvalarini yaratadi (SQLite); salaries.advance_deduction qo'shadi."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS attendances (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                date DATE NOT NULL,
                check_in DATETIME,
                check_out DATETIME,
                hours_worked FLOAT DEFAULT 0,
                status VARCHAR(20) DEFAULT 'present',
                event_snapshot_path VARCHAR(255),
                note VARCHAR(500),
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS attendance_docs (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                number VARCHAR(50) NOT NULL UNIQUE,
                date DATE NOT NULL,
                user_id INTEGER REFERENCES users(id),
                confirmed_at DATETIME,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS employee_advances (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                amount FLOAT DEFAULT 0,
                advance_date DATE NOT NULL,
                note VARCHAR(500),
                created_at DATETIME
            )
        """))
        r = conn.execute(text("PRAGMA table_info(employee_advances)"))
        adv_cols = [row[1] for row in r]
        if "confirmed_at" not in adv_cols:
            conn.execute(text("ALTER TABLE employee_advances ADD COLUMN confirmed_at DATETIME"))
        if "cash_register_id" not in adv_cols:
            conn.execute(text("ALTER TABLE employee_advances ADD COLUMN cash_register_id INTEGER REFERENCES cash_registers(id)"))
        r = conn.execute(text("PRAGMA table_info(salaries)"))
        cols = [row[1] for row in r]
        if "advance_deduction" not in cols:
            conn.execute(text("ALTER TABLE salaries ADD COLUMN advance_deduction FLOAT"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS employment_docs (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                number VARCHAR(50) NOT NULL UNIQUE,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                doc_date DATE NOT NULL,
                hire_date DATE,
                position VARCHAR(100),
                department VARCHAR(100),
                salary FLOAT DEFAULT 0,
                note VARCHAR(500),
                user_id INTEGER REFERENCES users(id),
                confirmed_at DATETIME,
                created_at DATETIME
            )
        """))
        r = conn.execute(text("PRAGMA table_info(employment_docs)"))
        ed_cols = [row[1] for row in r]
        if "confirmed_at" not in ed_cols:
            conn.execute(text("ALTER TABLE employment_docs ADD COLUMN confirmed_at DATETIME"))
        for col, sql in [("contract_type", "VARCHAR(50)"), ("contract_end_date", "DATE"), ("salary_type", "VARCHAR(50)"), ("piecework_task_ids", "TEXT"), ("rest_days", "VARCHAR(100)"), ("probation", "VARCHAR(100)")]:
            r = conn.execute(text("PRAGMA table_info(employment_docs)"))
            ed_cols = [row[1] for row in r]
            if col not in ed_cols:
                conn.execute(text(f"ALTER TABLE employment_docs ADD COLUMN {col} {sql}"))


def ensure_attendance_improvements():
    """Attendance jadvaliga doc_id, UNIQUE constraint va yangi status qo'shish."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(attendances)"))
            cols = [row[1] for row in r]
            if "doc_id" not in cols:
                conn.execute(text("ALTER TABLE attendances ADD COLUMN doc_id INTEGER REFERENCES attendance_docs(id)"))
            # UNIQUE index (dublikat bo'lmasligi uchun)
            try:
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_employee_date ON attendances(employee_id, date)"))
            except Exception:
                pass  # Agar dublikatlar bor bo'lsa, index yaratilmaydi
    except Exception as e:
        print(f"ensure_attendance_improvements: {e}")


def ensure_cash_transfer_inkasatsiya():
    """CashTransfer jadvaliga inkasatsiya ustunlarini qo'shadi va eski statuslarni yangilaydi."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(cash_transfers)"))
            cols = [row[1] for row in r]
            if "sent_by_user_id" not in cols:
                conn.execute(text("ALTER TABLE cash_transfers ADD COLUMN sent_by_user_id INTEGER REFERENCES users(id)"))
            if "sent_at" not in cols:
                conn.execute(text("ALTER TABLE cash_transfers ADD COLUMN sent_at DATETIME"))
            # Eski statuslarni yangilash
            conn.execute(text("UPDATE cash_transfers SET status='completed' WHERE status='confirmed'"))
            conn.execute(text("UPDATE cash_transfers SET status='in_transit' WHERE status='pending_approval'"))
            conn.execute(text("UPDATE cash_transfers SET status='pending' WHERE status='draft'"))
    except Exception as e:
        print(f"ensure_cash_transfer_inkasatsiya: {e}")


class AgentTask(Base):
    """Agent vazifalari (SD Agent)"""
    __tablename__ = "agent_tasks"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    title = Column(String(200))
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(20), default="pending")  # pending, completed
    priority = Column(String(10), default="normal")  # low, normal, high
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    agent = relationship("Agent")
    partner = relationship("Partner")


class AuditLog(Base):
    """Audit log — barcha muhim operatsiyalar tarixi"""
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_name = Column(String(200))  # Tez qidirish uchun
    action = Column(String(50), index=True)  # create, update, delete, confirm, revert, login
    entity_type = Column(String(50), index=True)  # production, order, partner, payment, ...
    entity_id = Column(Integer, nullable=True)
    entity_number = Column(String(100), nullable=True)  # Hujjat raqami
    details = Column(Text, nullable=True)  # Batafsil ma'lumot (JSON yoki matn)
    ip_address = Column(String(50), nullable=True)

    user = relationship("User", foreign_keys=[user_id])


if __name__ == "__main__":
    init_db()
