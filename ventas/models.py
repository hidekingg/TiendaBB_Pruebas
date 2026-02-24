# ventas/models.py
from django.db import models
import os
from uuid import uuid4
# ventas/models.py
from django.db import models
from django.utils import timezone

class AuditLog(models.Model):
    log_id = models.BigAutoField(primary_key=True)
    table_name = models.CharField(max_length=50)
    record_id = models.BigIntegerField(null=True)
    action = models.CharField(max_length=20)  # CREATE, UPDATE, DELETE, LOGIN
    user_id = models.IntegerField(null=True)
    old_data = models.JSONField(null=True, blank=True)
    new_data = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        managed = False  # Importante: Para que Django no intente crear la tabla otra vez



# --- UTILIDADES ---
def path_and_rename(instance, filename):
    upload_to = ''
    ext = filename.split('.')[-1]
    filename = '{}.{}'.format(uuid4().hex, ext)
    if hasattr(instance, 'username'):
        upload_to = 'users/'
    elif hasattr(instance, 'barcode'):
        upload_to = 'products/'
    elif hasattr(instance, 'company_name'):
        upload_to = 'suppliers/'
    return os.path.join(upload_to, filename)



# ==========================================
# 1. CATÁLOGOS BASE (Nivel 0 - Sin dependencias)
# ==========================================

class Role(models.Model):
    role_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    class Meta:
        managed = False
        db_table = 'roles'
    def __str__(self): return self.name

class Brand(models.Model):
    brand_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    # --- NUEVO CAMPO ---
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'brands'
    def __str__(self): return self.name

class Category(models.Model):
    category_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    parent = models.ForeignKey('self', models.DO_NOTHING, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    # --- NUEVO CAMPO ---
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'categories'
    def __str__(self): return self.name

class UnitOfMeasure(models.Model):
    uom_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=10)
    class Meta:
        managed = False
        db_table = 'units_of_measure'
    def __str__(self): return self.name

class CashRegister(models.Model):
    register_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50)
    class Meta:
        managed = False
        db_table = 'cash_registers'
    def __str__(self): return self.name

class Supplier(models.Model):
    supplier_id = models.AutoField(primary_key=True)
    company_name = models.CharField(max_length=150)
    contact_name = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.CharField(max_length=100, null=True, blank=True)
    
    # Campo para la foto: Le decimos a Django que maneje archivos, pero lo guarde en la columna photo_url
    photo = models.ImageField(upload_to=path_and_rename, db_column='photo_url', null=True, blank=True)
    
    # Nuestro nuevo campo
    is_active = models.BooleanField(default=True) 

    class Meta:
        db_table = 'suppliers'
        managed = False
        
    def __str__(self): 
        return self.company_name

class Customer(models.Model):
    customer_id = models.AutoField(primary_key=True)
    full_name = models.CharField(max_length=150)
    tax_id = models.CharField(max_length=20, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    allow_credit = models.BooleanField(default=False)
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    current_debt = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        managed = False
        db_table = 'customers'
    def __str__(self): return self.full_name

# ==========================================
# 2. USUARIOS (Depende de Role)
# ==========================================

class UsuarioPersonalizado(models.Model):
    user_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=50, unique=True)
    password_hash = models.CharField(max_length=255)
    full_name = models.CharField(max_length=100)
    role = models.ForeignKey(Role, on_delete=models.RESTRICT)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    photo = models.ImageField(upload_to=path_and_rename, null=True, blank=True, db_column='photo_url')
    class Meta:
        managed = False
        db_table = 'users'
    def __str__(self): return self.username

# ==========================================
# 3. PRODUCTO (Depende de Nivel 0)
# ==========================================

class Product(models.Model):
    product_id = models.AutoField(primary_key=True)
    barcode = models.CharField(max_length=50, unique=True, null=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    
    # Foreign Keys a Nivel 0
    category = models.ForeignKey(Category, on_delete=models.DO_NOTHING, blank=True, null=True)
    brand = models.ForeignKey(Brand, on_delete=models.DO_NOTHING, db_column='brand_id', blank=True, null=True)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.DO_NOTHING, blank=True, null=True)
    
    is_weighted = models.BooleanField(default=False)
    min_stock_alert = models.DecimalField(max_digits=10, decimal_places=3, default=5.000)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    is_service = models.BooleanField(default=False)
    service_commission = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    photo = models.ImageField(upload_to=path_and_rename, null=True, blank=True, db_column='photo_url')
    is_returnable = models.BooleanField(default=False)
    deposit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        managed = False
        db_table = 'products'
    def __str__(self): return self.name

# ==========================================
# 4. TABLAS INTERMEDIAS Y DETALLES (Dependen de Product/Supplier)
# ==========================================

class ProductSupplier(models.Model):
    # Clave compuesta simulada en Django (usualmente se usa oneToOne en el primero, pero aquí es ManyToMany through table manual)
    # Como Django exige una PK simple para admin, en managed=False usamos la que tenga sentido o el ID implícito si existiera.
    # Dado tu SQL: PRIMARY KEY (product_id, supplier_id). Django prefiere una columna ID única.
    # Para lectura funcionará usando product como 'primary_key' logica para el ORM si solo leemos.
    # Pero para escribir correctamente ProductSupplier, lo mejor es tratarla con cuidado o agregar un ID serial en BD.
    # Por ahora, mapeamos product como PK para que Django arranque, aunque sea una composite key real.
    product = models.OneToOneField(Product, on_delete=models.DO_NOTHING, primary_key=True) 
    supplier = models.ForeignKey(Supplier, on_delete=models.DO_NOTHING)
    is_primary = models.BooleanField(default=False)
    current_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_notes = models.CharField(max_length=200, null=True, blank=True) # Ej: "Mayoreo $13 x 6 pzs"
    last_updated = models.DateTimeField(auto_now=True) # Se actualiza solo cada vez que se edita

    class Meta:
        managed = False
        db_table = 'product_suppliers'
        unique_together = (('product', 'supplier'),)

class InventoryStock(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, primary_key=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    location_code = models.CharField(max_length=50, null=True)
    class Meta:
        managed = False
        db_table = 'inventory_stock'

class InventoryMovement(models.Model):
    movement_id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.RESTRICT)
    user = models.ForeignKey(UsuarioPersonalizado, on_delete=models.SET_NULL, null=True)
    type = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reference_id = models.IntegerField(null=True)
    reason = models.TextField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        managed = False
        db_table = 'inventory_movements'

class Promotion(models.Model):
    promo_id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    trigger_quantity = models.DecimalField(max_digits=10, decimal_places=3)
    promo_price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=100, null=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        managed = False
        db_table = 'promotions'

class PriceHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    old_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    new_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    old_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    new_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    changed_by = models.ForeignKey(UsuarioPersonalizado, on_delete=models.SET_NULL, null=True, db_column='changed_by')
    changed_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        managed = False
        db_table = 'price_history'

# ==========================================
# 5. VENTAS Y OPERACIONES (Nivel más alto)
# ==========================================

class Shift(models.Model):
    shift_id = models.AutoField(primary_key=True)
    register = models.ForeignKey(CashRegister, on_delete=models.RESTRICT)
    user = models.ForeignKey(UsuarioPersonalizado, on_delete=models.RESTRICT)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    initial_cash = models.DecimalField(max_digits=10, decimal_places=2)
    final_cash_expected = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    final_cash_counted = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    difference = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    is_closed = models.BooleanField(default=False)
    class Meta:
        managed = False
        db_table = 'shifts'

class Sale(models.Model):
    sale_id = models.BigAutoField(primary_key=True)
    shift = models.ForeignKey(Shift, on_delete=models.RESTRICT, null=True, db_column='shift_id')
    customer = models.ForeignKey(Customer, on_delete=models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey(UsuarioPersonalizado, on_delete=models.RESTRICT)
    amount_cash = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_card = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    card_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20)
    status = models.CharField(max_length=20, default='COMPLETED')
    created_at = models.DateTimeField(auto_now_add=True)
    
    # --- NUEVOS CAMPOS ---
    cash_received = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    change_given = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        managed = False
        db_table = 'sales'

class SaleDetail(models.Model):
    detail_id = models.BigAutoField(primary_key=True)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.RESTRICT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.CharField(max_length=255, null=True, blank=True)
    deposit_charged = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        managed = False
        db_table = 'sale_details'

class InternalWithdrawal(models.Model):
    withdrawal_id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.RESTRICT)
    user = models.ForeignKey(UsuarioPersonalizado, on_delete=models.RESTRICT)
    beneficiary_name = models.CharField(max_length=100, null=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.CharField(max_length=50)
    status = models.CharField(max_length=20, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    # --- NUEVO CAMPO ---
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        managed = False
        db_table = 'internal_withdrawals'

#============================================================
#ADMIN

class Promotion(models.Model):
    promo_id = models.AutoField(primary_key=True)
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='promotions')
    trigger_quantity = models.DecimalField(max_digits=10, decimal_places=3) # Cuántos llevas
    promo_price = models.DecimalField(max_digits=10, decimal_places=2)      # Precio total del paquete
    description = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'promotions'
        managed = False

# --- AGREGAR AL FINAL DE ventas/models.py ---

class PhysicalCount(models.Model):
    count_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(UsuarioPersonalizado, on_delete=models.PROTECT)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'physical_counts'
        managed = False  # <--- Esto le dice a Django que la tabla ya fue creada por ti en SQL

class PhysicalCountDetail(models.Model):
    detail_id = models.AutoField(primary_key=True)
    count = models.ForeignKey(PhysicalCount, on_delete=models.CASCADE, related_name='details')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    system_qty = models.DecimalField(max_digits=10, decimal_places=3)
    counted_qty = models.DecimalField(max_digits=10, decimal_places=3)
    difference = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        db_table = 'physical_count_details'
        managed = False  # <--- Esto le dice a Django que la tabla ya fue creada por ti en SQL


class BottleReturn(models.Model):
    return_id = models.AutoField(primary_key=True)
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(UsuarioPersonalizado, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'bottle_returns'
        managed = False