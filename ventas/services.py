# ventas/services.py
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, F
from django.utils import timezone
import json
from django.forms.models import model_to_dict
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields.files import FieldFile
from .models import AuditLog
from .models import (
    Sale, SaleDetail, InventoryMovement, InventoryStock, 
    InternalWithdrawal, Shift, CashRegister, Product, PriceHistory,
    Promotion
)


class AuditLogger:
    
    @staticmethod
    def get_snapshot(instance):
        """
        Captura los datos del modelo, limpia archivos y convierte tipos complejos.
        """
        if not instance:
            return {}
            
        # 1. Obtener datos crudos
        data = model_to_dict(instance)
        
        # 2. SANITIZACIÓN: 
        clean_data = {}
        for key, value in data.items():
            # Si es un archivo/imagen, guardamos solo el nombre o null
            if isinstance(value, FieldFile):
                clean_data[key] = value.name if value else None
            else:
                clean_data[key] = value

        # 3. Serialización previa para asegurar que comparamos "peras con peras"
        # (ej: que Decimal('10.00') sea igual a '10.00')
        try:
            return json.loads(json.dumps(clean_data, cls=DjangoJSONEncoder))
        except Exception:
            return {}

    @staticmethod
    def _calcular_diferencias(old, new):
        """
        Compara dos diccionarios y devuelve solo los campos que cambiaron.
        Retorna: (diff_old, diff_new)
        """
        if not old or not new:
            return old, new
            
        diff_old = {}
        diff_new = {}
        
        # Recorremos todas las llaves del nuevo estado
        for key, new_val in new.items():
            old_val = old.get(key)
            
            # Si el valor es diferente, lo agregamos al reporte de cambios
            if new_val != old_val:
                diff_old[key] = old_val
                diff_new[key] = new_val
                
        return diff_old, diff_new

    @staticmethod
    def log_action(user_id, instance, action, old_data=None):
        """Registra la acción guardando solo lo necesario"""
        try:
            table_name = instance._meta.db_table
            record_id = instance.pk
            
            new_data = None
            
            # --- LÓGICA DE OPTIMIZACIÓN ---
            
            # 1. Si es CREAR: Todo es nuevo, no hay old_data
            if action == 'CREATE':
                new_data = AuditLogger.get_snapshot(instance)
                # old_data se queda en None o {}
            
            # 2. Si es BORRAR: Todo se pierde, guardamos el old_data completo
            elif action == 'DELETE':
                if old_data is None: 
                    old_data = AuditLogger.get_snapshot(instance)
                # new_data se queda en None
            
            # 3. Si es UPDATE: ¡Aquí ocurre la magia!
            elif action == 'UPDATE':
                snapshot_actual = AuditLogger.get_snapshot(instance)
                
                # Comparamos para guardar SOLO lo que cambió
                if old_data:
                    old_data, new_data = AuditLogger._calcular_diferencias(old_data, snapshot_actual)
                    
                    # Si después de comparar no hay cambios (old_data y new_data vacíos),
                    # significa que el usuario guardó sin editar nada.
                    # OPCIONAL: Puedes retornar aquí si no quieres guardar logs vacíos.
                    if not old_data and not new_data:
                        return 
                else:
                    # Si por alguna razón no llegó el old_data, guardamos todo el new
                    new_data = snapshot_actual

            # Guardar en BD
            AuditLog.objects.create(
                table_name=table_name,
                record_id=record_id,
                action=action,
                user_id=user_id,
                old_data=old_data,
                new_data=new_data
            )
            
        except Exception as e:
            print(f"⚠️ ERROR AUDITORÍA: {str(e)}")

# ==========================================
# 1. DASHBOARD Y ESTADÍSTICAS (Lógica Diaria Estricta)
# ==========================================

def obtener_rango_dia_actual():
    """Retorna el inicio y fin del día actual en hora local."""
    now = timezone.localtime(timezone.now())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end

def obtener_resumen_dashboard():
    start_day, end_day = obtener_rango_dia_actual()
    
    # 1. Ventas de Hoy (Filtro por Rango Exacto)
    ventas = Sale.objects.filter(
        created_at__range=(start_day, end_day), 
        status='COMPLETED'
    )
    
    # Suma segura evitando errores de tipos
    resumen = ventas.aggregate(total=Sum('total'))
    total_ventas = resumen['total'] if resumen['total'] is not None else Decimal('0.00')
    
    # 2. Bajos en Stock (Esto es estado actual, no depende de la fecha)
    bajos_stock = InventoryStock.objects.filter(
        quantity__lte=F('product__min_stock_alert'),
        product__is_active=True,     # <--- LÍNEA NUEVA: Ignorar productos dados de baja
        product__is_service=False    # <--- LÍNEA NUEVA: Ignorar recargas y pago de recibos
    ).count()

    # --- ESTADÍSTICAS AVANZADAS ---

    # 3. Ticket Promedio
    conteo_ventas = ventas.count()
    ticket_promedio = total_ventas / conteo_ventas if conteo_ventas > 0 else Decimal('0.00')

    # 4. Ganancia Estimada y Producto Estrella
    # Usamos el mismo rango de fechas estricto para los detalles
    detalles_hoy = SaleDetail.objects.filter(
        sale__created_at__range=(start_day, end_day), 
        sale__status='COMPLETED'
    ).select_related('product')
    
    ganancia = Decimal('0.00')
    for detalle in detalles_hoy:
        costo = detalle.product.cost_price
        # Cálculo seguro con Decimales
        ganancia += (detalle.unit_price - costo) * detalle.quantity

    # 5. Producto Estrella
    top_producto = detalles_hoy.values('product__name')\
        .annotate(total_qty=Sum('quantity'))\
        .order_by('-total_qty').first()
    
    nombre_top = top_producto['product__name'] if top_producto else "Sin ventas"
    cantidad_top = top_producto['total_qty'] if top_producto else 0

    return {
        'ventas_hoy': total_ventas,
        'bajos_stock': bajos_stock,
        'ticket_promedio': ticket_promedio,
        'ganancia_estimada': ganancia,
        'top_producto': nombre_top,
        'top_cantidad': cantidad_top
    }

def obtener_top_productos_dia():
    """Top productos usando el rango horario estricto."""
    start_day, end_day = obtener_rango_dia_actual()
    
    top_products = Product.objects.filter(
        saledetail__sale__created_at__range=(start_day, end_day),
        saledetail__sale__status='COMPLETED'
    ).annotate(
        total_vendido=Sum('saledetail__quantity')
    ).order_by('-total_vendido')[:5]

    resultado = []
    for p in top_products:
        promo_obj = Promotion.objects.filter(product=p, is_active=True).first()
        stock_record = InventoryStock.objects.filter(product=p).first()
        stock_actual = float(stock_record.quantity) if stock_record else 0

        foto_url = None
        if p.photo:
            try: foto_url = p.photo.url 
            except: foto_url = str(p.photo) if str(p.photo).startswith('/media/') else f'/media/{p.photo}'

        resultado.append({
            'id': p.product_id,
            'name': p.name,
            'price': float(p.sale_price),
            'stock': stock_actual,
            'photo': foto_url,
            'is_weighted': p.is_weighted,
            'barcode': p.barcode,
            'is_returnable': getattr(p, 'is_returnable', False),
            'deposit_price': float(getattr(p, 'deposit_price', 0.00)),
            'promo': {
                'trigger': float(promo_obj.trigger_quantity),
                'price': float(promo_obj.promo_price),
                'desc': promo_obj.description
            } if promo_obj else None
        })
    
    return resultado

# ==========================================
# 2. GESTIÓN DE TURNOS (CAJA)
# ==========================================

def obtener_turno_activo(user_id):
    active_shift = Shift.objects.filter(user_id=user_id, is_closed=False).first()
    
    if active_shift:
        # Validación de fecha estricta
        if active_shift.start_time.date() < timezone.localtime(timezone.now()).date():
            cerrar_turno(active_shift, sistema_auto=True)
            return None 
        return active_shift
    return None

def abrir_turno(user_id, register_id, initial_cash):
    return Shift.objects.create(
        user_id=user_id,
        register_id=register_id,
        initial_cash=initial_cash,
        start_time=timezone.now(),
        is_closed=False
    )

def cerrar_turno(shift_obj, final_cash_counted=0, sistema_auto=False):
    final_cash_counted = Decimal(str(final_cash_counted))

    # Ventas del turno
    suma_ventas = Sale.objects.filter(
        shift=shift_obj, 
        status='COMPLETED'
    ).aggregate(total=Sum('total'))
    
    ventas_turno = suma_ventas['total'] if suma_ventas['total'] is not None else Decimal('0.00')

    shift_obj.end_time = timezone.now()
    shift_obj.is_closed = True
    shift_obj.final_cash_expected = shift_obj.initial_cash + ventas_turno
    
    if sistema_auto:
        shift_obj.final_cash_counted = shift_obj.final_cash_expected 
        shift_obj.difference = Decimal('0.00')
    else:
        shift_obj.final_cash_counted = final_cash_counted
        shift_obj.difference = final_cash_counted - shift_obj.final_cash_expected

    shift_obj.save()
    return shift_obj

# ==========================================
# 3. PROCESOS DE VENTA (POS) - INTACTO
# ==========================================

@transaction.atomic
def procesar_nueva_venta(user_id, shift_id, items, total, payment_data):
    shift = Shift.objects.get(shift_id=shift_id)
    
    sale = Sale.objects.create(
        shift=shift,
        user_id=user_id,
        subtotal=Decimal(str(total)),
        tax_amount=0,
        total=Decimal(str(total)),
        payment_method=payment_data['method'],
        amount_cash=Decimal(str(payment_data['cash'])),
        amount_card=Decimal(str(payment_data['card'])),
        card_commission=Decimal(str(payment_data['commission'])),
        
        # --- AÑADIMOS ESTAS DOS LÍNEAS PARA EL CAMBIO ---
        cash_received=Decimal(str(payment_data.get('cash_received', 0))),
        change_given=Decimal(str(payment_data.get('change_given', 0))),
        
        status='COMPLETED'
    )

    for item in items:
        product_id = item['id']
        qty = Decimal(str(item['quantity']))
        price = Decimal(str(item['price']))
        deposit = float(item.get('deposit_charged', 0.00))
        
        producto = Product.objects.get(product_id=product_id)
        
        # --- NUEVA LÓGICA DE COSTO Y COMISIONES ---
        if producto.is_service:
            # Calculamos el costo real usando la comisión
            comision_pct = producto.service_commission / Decimal('100')
            ganancia = price * comision_pct
            costo_congelado = price - ganancia
        else:
            costo_congelado = producto.cost_price
            
            # --- LÓGICA DE INVENTARIO NORMAL (Solo si no es servicio) ---
            try:
                stock_record = InventoryStock.objects.select_for_update().get(product_id=product_id)
            except InventoryStock.DoesNotExist:
                raise ValueError(f"El producto {item['name']} no tiene registro de inventario.")

            if stock_record.quantity < qty:
                raise ValueError(f"Stock insuficiente para '{item['name']}'. Quedan {stock_record.quantity}.")

            stock_record.quantity -= qty
            stock_record.save()

            InventoryMovement.objects.create(
                product_id=product_id, user_id=user_id, type='OUT_SALE',
                quantity=-qty, reference_id=sale.sale_id, reason='Venta POS'
            )

        # GUARDAR EL TICKET CON EL COSTO CALCULADO
        SaleDetail.objects.create(
            sale=sale,
            product_id=product_id,
            quantity=qty,
            unit_price=price,
            subtotal=qty * price,
            unit_cost=costo_congelado, # <-- AQUÍ ESTÁ LA MAGIA
            description=item.get('description', ''),
            deposit_charged=deposit
        )

    return sale

@transaction.atomic
def procesar_toma_interna(user_id, items, beneficiary):
    for item in items:
        product_id = item['id']
        qty = Decimal(str(item['quantity']))
        
        # --- CORRECCIÓN: Traer el producto de la BD para leer su costo ---
        producto = Product.objects.get(product_id=product_id)

        InternalWithdrawal.objects.create(
            product_id=product_id,
            user_id=user_id,
            beneficiary_name=beneficiary,
            quantity=qty,
            reason='CONSUMO_INTERNO',
            status='APPROVED', # Se añadió la coma que faltaba aquí
            # Congelamos el costo al momento de la toma
            unit_cost=producto.cost_price,
        )
        
        InventoryMovement.objects.create(
            product_id=product_id,
            user_id=user_id,
            type='OUT_INTERNAL_USE',
            quantity=-qty,
            reason=f'Toma Interna: {beneficiary}'
        )

        InventoryStock.objects.filter(product_id=product_id).update(
            quantity=F('quantity') - qty
        )
    
    return True

# ==========================================
# 4. GESTIÓN DE INVENTARIO
# ==========================================

def obtener_inventario_completo():
    return InventoryStock.objects.select_related('product', 'product__brand').all().order_by('product__name')

@transaction.atomic
def registrar_entrada_compra(product_id, user_id, quantity, cost_price, provider_name=None):
    quantity = Decimal(str(quantity))
    new_cost = Decimal(str(cost_price))
    
    product = Product.objects.get(product_id=product_id)
    
    if product.cost_price != new_cost:
        PriceHistory.objects.create(
            product=product,
            old_cost=product.cost_price,
            new_cost=new_cost,
            changed_by_id=user_id
        )
        product.cost_price = new_cost
        product.save()

    stock, created = InventoryStock.objects.get_or_create(product=product, defaults={'quantity': 0})
    stock.quantity += quantity
    stock.save()

    InventoryMovement.objects.create(
        product=product,
        user_id=user_id,
        type='IN_PURCHASE',
        quantity=quantity,
        reason=f"Compra - Prov: {provider_name or 'General'}"
    )
    return True

@transaction.atomic
def realizar_ajuste_inventario(product_id, user_id, quantity_diff, reason):
    quantity_diff = Decimal(str(quantity_diff)).quantize(Decimal("0.001"))
    
    InventoryMovement.objects.create(
        product_id=product_id,
        user_id=user_id,
        type='ADJUSTMENT', 
        quantity=abs(quantity_diff),
        reason=f"{reason} (Ajuste: {quantity_diff})"
    )

    stock, created = InventoryStock.objects.get_or_create(product=product_id, defaults={'quantity': 0})
    stock.quantity += quantity_diff
    stock.save()
    
    return True