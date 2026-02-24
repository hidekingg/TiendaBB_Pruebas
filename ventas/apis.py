# ventas/apis.py
import json
import unicodedata
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.db.models import Q, F
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.core.files.storage import FileSystemStorage
from django.contrib.auth.hashers import check_password
from django.utils.dateformat import format
from django.db import transaction
from django.core.paginator import Paginator
from django.contrib.auth.hashers import check_password, make_password

# Modelos y Servicios
# Modelos y Servicios
from .models import (
    Product, Promotion, InventoryStock, Sale, SaleDetail, 
    InternalWithdrawal, InventoryMovement, ProductSupplier, Supplier,
    UsuarioPersonalizado, Brand, Category, UnitOfMeasure, AuditLog,
    PriceHistory, Role, Shift, PhysicalCount, PhysicalCountDetail  # <--- Agregamos Shift aquí
)

from .services import (
    obtener_resumen_dashboard, procesar_nueva_venta, 
    procesar_toma_interna, registrar_entrada_compra, 
    realizar_ajuste_inventario, obtener_top_productos_dia, 
    AuditLogger
)

def normalizar_texto(texto):
    """Quita acentos y convierte a minúsculas para comparaciones"""
    if not texto: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) != 'Mn').lower()

def api_get_product_suppliers(request, product_id):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    from django.db import connection
    sql = """
        SELECT s.supplier_id, s.company_name, ps.is_primary
        FROM product_suppliers ps 
        JOIN suppliers s ON ps.supplier_id = s.supplier_id
        WHERE ps.product_id = %s
        ORDER BY ps.is_primary DESC, s.company_name ASC
    """
    results = []
    with connection.cursor() as cursor:
        cursor.execute(sql, [product_id])
        rows = cursor.fetchall()
        for row in rows:
            results.append({'id': row[0], 'name': row[1], 'is_primary': row[2]})
    return JsonResponse(results, safe=False)

def api_top_selling_products(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    raw_products = obtener_top_productos_dia() 
    
    # Obtenemos los IDs de todos los productos que son servicios
    service_ids = set(Product.objects.filter(is_service=True).values_list('product_id', flat=True))
    
    products = []
    for p in raw_products:
        if p['id'] in service_ids:
            continue
            
        promos_qs = Promotion.objects.filter(product_id=p['id'], is_active=True).order_by('-trigger_quantity')
        p['promotions'] = [
            {'id': promo.promo_id, 'trigger': float(promo.trigger_quantity), 'price': float(promo.promo_price), 'desc': promo.description}
            for promo in promos_qs
        ]
        p['promo'] = p['promotions'][0] if p['promotions'] else None
        products.append(p)
        
    return JsonResponse(products, safe=False)

def api_dashboard_stats(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    stats = obtener_resumen_dashboard()
    return JsonResponse({
        'sales_today': float(stats['ventas_hoy']),
        'low_stock': stats['bajos_stock'],
        'avg_ticket': float(stats['ticket_promedio']),
        'profit': float(stats['ganancia_estimada']),
        'top_product': stats['top_producto'],
        'top_qty': float(stats['top_cantidad'])
    })

def api_search_products(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    query = request.GET.get('q', '').strip()
    if len(query) < 2 and not query.isdigit(): return JsonResponse([], safe=False)

    all_products = Product.objects.filter(is_active=True, is_service=False).select_related('brand')
    query_norm = normalizar_texto(query)
    
    matches = []
    for p in all_products:
        if query_norm in normalizar_texto(p.name) or query_norm in normalizar_texto(p.barcode):
            matches.append(p)
            if len(matches) >= 15: break
            
    results = []
    for p in matches:
        stock_record = InventoryStock.objects.filter(product=p).first()
        stock_actual = float(stock_record.quantity) if stock_record else 0
        promos_qs = Promotion.objects.filter(product=p, is_active=True).order_by('-trigger_quantity')
        lista_promos = [
            {'id': pr.promo_id, 'trigger': float(pr.trigger_quantity), 'price': float(pr.promo_price), 'desc': pr.description}
            for pr in promos_qs
        ]
        results.append({
            'id': p.product_id, 'name': p.name, 'barcode': p.barcode,
            'price': float(p.sale_price), 'stock': stock_actual, 'is_weighted': p.is_weighted,
            'photo': p.photo.url if p.photo else None,
            'promotions': lista_promos, 'promo': lista_promos[0] if lista_promos else None,
            'is_returnable': p.is_returnable,
            'deposit_price': float(p.deposit_price),
        })
    return JsonResponse(results, safe=False)

@csrf_exempt
def api_process_sale(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    try:
        data = json.loads(request.body)
        items = data.get('items', [])
        if not items: return JsonResponse({'error': 'Vacío'}, status=400)
        
        if data.get('action') == 'SALE':
            sale = procesar_nueva_venta(
                user_id=request.session['user_id'], shift_id=request.session.get('shift_id'), items=items,
                total=float(data.get('total_products', 0)), 
                payment_data={
                    'method': data.get('payment_method', 'CASH'), 
                    'cash': float(data.get('amount_cash', 0)),
                    'card': float(data.get('amount_card', 0)), 
                    'commission': float(data.get('card_commission', 0)),
                    'cash_received': float(data.get('cash_received', 0)),
                    'change_given': float(data.get('change_given', 0))
                }
            )
            return JsonResponse({'status': 'success', 'sale_id': sale.sale_id})
        elif data.get('action') == 'WITHDRAWAL':
            procesar_toma_interna(user_id=request.session['user_id'], items=items, beneficiary=data.get('beneficiary'))
            return JsonResponse({'status': 'success'})
        return JsonResponse({'error': 'Acción inválida'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def api_add_stock(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    try:
        data = json.loads(request.body)
        user_id = request.session['user_id']
        product_id = data['product_id']
        stock_record, _ = InventoryStock.objects.get_or_create(product_id=product_id, defaults={'quantity': 0})
        snapshot_antiguo = AuditLogger.get_snapshot(stock_record)

        registrar_entrada_compra(
            product_id=product_id, user_id=user_id, quantity=data['quantity'],
            cost_price=data['cost'], provider_name=data.get('provider')
        )
        stock_record.refresh_from_db() 
        AuditLogger.log_action(user_id, stock_record, 'UPDATE', old_data=snapshot_antiguo)
        return JsonResponse({'status': 'success'})
    except Exception as e: return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def api_adjust_stock(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    try:
        data = json.loads(request.body)
        user_id = request.session['user_id']
        product_id = data['product_id']
        stock_record = InventoryStock.objects.get(product_id=product_id)
        snapshot_antiguo = AuditLogger.get_snapshot(stock_record)

        realizar_ajuste_inventario(product_id=product_id, user_id=user_id, quantity_diff=data['quantity'], reason=data['reason'])
        stock_record.refresh_from_db()
        AuditLogger.log_action(user_id, stock_record, 'UPDATE', old_data=snapshot_antiguo)
        return JsonResponse({'status': 'success'})
    except Exception as e: return JsonResponse({'error': str(e)}, status=500)

def api_datos_finanzas(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    fecha_inicio = datetime.strptime(start_date, '%Y-%m-%d')
    fecha_fin = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    
    ventas_qs = Sale.objects.filter(created_at__range=(fecha_inicio, fecha_fin), status='COMPLETED').values('created_at', 'total', 'payment_method')
    ventas_por_dia = {}
    ingreso_ventas_netas = 0 
    pagos_map = {}

    for v in ventas_qs:
        monto = float(v['total'])
        ingreso_ventas_netas += monto
        fecha_obj = timezone.localtime(v['created_at']).date() if timezone.is_aware(v['created_at']) else v['created_at'].date()
        key_fecha = fecha_obj.strftime('%d/%m')
        if key_fecha not in ventas_por_dia: ventas_por_dia[key_fecha] = {'date': fecha_obj, 'total': 0.0}
        ventas_por_dia[key_fecha]['total'] += monto
        
        metodo = v['payment_method']
        pagos_map[metodo] = pagos_map.get(metodo, 0.0) + monto
    
    lista_ordenada = sorted(ventas_por_dia.values(), key=lambda x: x['date'])
    labels_a = [item['date'].strftime('%d/%m') for item in lista_ordenada]
    data_a = [item['total'] for item in lista_ordenada]
    pagos_ordenados = sorted(pagos_map.items(), key=lambda x: x[1], reverse=True)

    detalles = SaleDetail.objects.filter(sale__created_at__range=(fecha_inicio, fecha_fin), sale__status='COMPLETED').select_related('product')
    costo_ventas = 0
    monto_precio_lista = 0
    for d in detalles:
        costo_ventas += float(d.unit_cost * d.quantity) 
        monto_precio_lista += float(d.subtotal)

    tomas = InternalWithdrawal.objects.filter(created_at__range=(fecha_inicio, fecha_fin), status='APPROVED').select_related('product')
    costo_usos_internos = 0
    for toma in tomas: costo_usos_internos += float(toma.unit_cost * toma.quantity)

    descuento_promos = max(0, monto_precio_lista - ingreso_ventas_netas)
    utilidad_bruta = ingreso_ventas_netas - costo_ventas
    utilidad_neta = utilidad_bruta - costo_usos_internos
    margen_neto = (utilidad_neta / ingreso_ventas_netas * 100) if ingreso_ventas_netas > 0 else 0

    return JsonResponse({
        'reporte_a': {'labels': labels_a, 'data': data_a},
        'reporte_c': {'labels': [p[0] for p in pagos_ordenados], 'data': [p[1] for p in pagos_ordenados]},
        'reporte_b': {
            'ventas_netas': ingreso_ventas_netas, 'costo_ventas': costo_ventas, 'utilidad_bruta': utilidad_bruta,
            'gastos_operativos': costo_usos_internos, 'utilidad_neta': utilidad_neta,
            'margen': round(margen_neto, 2), 'descuento_promos': descuento_promos
        }
    })

@csrf_exempt
def api_producto_accion(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        accion = request.POST.get('accion')
        product_id = request.POST.get('product_id')
        user_id = request.session['user_id']
        
        if accion in ['deactivate', 'activate']:
            if accion == 'deactivate':
                password_confirm = request.POST.get('password_confirm')
                usuario = UsuarioPersonalizado.objects.get(user_id=user_id)
                if not check_password(password_confirm, usuario.password_hash): return JsonResponse({'status': 'error', 'message': 'Contraseña incorrecta.'})
                is_active_val = False
                msg = 'Producto dado de baja.'
            else:
                is_active_val = True
                msg = 'Producto reactivado exitosamente.'

            producto = Product.objects.get(product_id=product_id)
            snapshot_antiguo = AuditLogger.get_snapshot(producto)
            producto.is_active = is_active_val
            producto.save()
            AuditLogger.log_action(user_id, producto, 'UPDATE', old_data=snapshot_antiguo)
            return JsonResponse({'status': 'success', 'message': msg})
        else:
            nombre = request.POST.get('name', '').strip()
            barcode = request.POST.get('barcode', '').strip()
            descripcion = request.POST.get('description', '').strip()
            costo = request.POST.get('cost_price')
            precio = request.POST.get('sale_price')
            stock_min = request.POST.get('min_stock')
            cat_id = request.POST.get('category')
            brand_id = request.POST.get('brand')
            uom_id = request.POST.get('uom')
            is_returnable = request.POST.get('is_returnable') == 'true'
            deposit_price = request.POST.get('deposit_price', 0)
            
            errores = []
            if not nombre: errores.append("El Nombre es obligatorio.")
            if not descripcion: errores.append("La Descripción es obligatoria.")
            if not costo: errores.append("El Costo es obligatorio.")
            if not precio: errores.append("El Precio es obligatorio.")
            if not stock_min: errores.append("El Stock Mínimo es obligatorio.")
            if not cat_id: errores.append("Selecciona una Categoría.")
            if not brand_id: errores.append("Selecciona una Marca.")
            if not uom_id: errores.append("Selecciona una Unidad de Medida.")

            if barcode and Product.objects.filter(barcode=barcode).exclude(product_id=product_id if product_id else None).exists():
                errores.append(f"El código de barras '{barcode}' ya existe.")
            if errores: return JsonResponse({'status': 'error', 'message': "<br>".join(errores)})

            snapshot_antiguo = None
            is_new = False
            if accion == 'create':
                producto = Product()
                producto.is_active = True
                is_new = True 
            elif accion == 'update':
                producto = Product.objects.get(product_id=product_id)
                snapshot_antiguo = AuditLogger.get_snapshot(producto)

            producto.name = nombre
            producto.barcode = barcode if barcode else None
            producto.description = descripcion
            producto.cost_price = costo
            producto.sale_price = precio
            producto.min_stock_alert = stock_min
            producto.is_weighted = request.POST.get('is_weighted') == 'true'
            producto.is_service = request.POST.get('is_service') == 'true'
            producto.category_id = cat_id
            producto.brand_id = brand_id
            producto.uom_id = uom_id
            producto.is_returnable = is_returnable
            producto.deposit_price = deposit_price
            
            if producto.is_service:
                producto.service_commission = request.POST.get('service_commission', 0)
                producto.cost_price = 0
                producto.sale_price = 0
            else:
                producto.service_commission = 0
                producto.cost_price = costo
                producto.sale_price = precio

            if 'photo' in request.FILES:
                image = request.FILES['photo']
                fs = FileSystemStorage()
                filename = fs.save(f"products/{int(datetime.now().timestamp())}_{image.name}", image)
                producto.photo = filename

            producto.save()
            producto.refresh_from_db()

            if is_new:
                AuditLogger.log_action(user_id, producto, 'CREATE')
                InventoryStock.objects.get_or_create(product=producto, defaults={'quantity': 0})
            else:
                AuditLogger.log_action(user_id, producto, 'UPDATE', old_data=snapshot_antiguo)
            return JsonResponse({'status': 'success', 'message': "Producto guardado correctamente."})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)})

@csrf_exempt
def api_promocion_accion(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': 'Método no permitido'}, status=405)
    try:
        accion = request.POST.get('accion')
        promo_id = request.POST.get('promo_id')
        user_id = request.session['user_id']

        if accion in ['deactivate', 'activate']:
            promo = Promotion.objects.get(promo_id=promo_id)
            snapshot_antiguo = AuditLogger.get_snapshot(promo)
            promo.is_active = (accion == 'activate')
            promo.save()
            AuditLogger.log_action(user_id, promo, 'UPDATE', old_data=snapshot_antiguo)
            return JsonResponse({'status': 'success', 'message': 'Estatus actualizado.'})
        else:
            product_id = request.POST.get('product_id')
            trigger_qty = request.POST.get('trigger_quantity')
            promo_price = request.POST.get('promo_price')
            description = request.POST.get('description')

            if not product_id: return JsonResponse({'status': 'error', 'message': 'Debes seleccionar un producto.'})
            if not trigger_qty or float(trigger_qty) <= 0: return JsonResponse({'status': 'error', 'message': 'Cantidad activadora inválida.'})
            if not promo_price or float(promo_price) < 0: return JsonResponse({'status': 'error', 'message': 'Precio de oferta inválido.'})

            snapshot_antiguo = None
            if accion == 'create':
                promo = Promotion()
                promo.is_active = True
            elif accion == 'update':
                promo = Promotion.objects.get(promo_id=promo_id)
                snapshot_antiguo = AuditLogger.get_snapshot(promo)

            promo.product_id = product_id
            promo.trigger_quantity = trigger_qty
            promo.promo_price = promo_price
            promo.description = description
            promo.save()
            promo.refresh_from_db()
            
            if accion == 'create': AuditLogger.log_action(user_id, promo, 'CREATE')
            else: AuditLogger.log_action(user_id, promo, 'UPDATE', old_data=snapshot_antiguo)
            return JsonResponse({'status': 'success', 'message': 'Promoción guardada.'})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)})

def api_libreta_buscar(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    query = request.GET.get('q', '').strip()
    if len(query) < 2 and not query.isdigit(): return JsonResponse([], safe=False)

    all_products = Product.objects.filter(is_active=True)
    query_norm = normalizar_texto(query)
    
    matches = []
    for p in all_products:
        if query_norm in normalizar_texto(p.name) or query_norm in normalizar_texto(p.barcode):
            matches.append(p)
            if len(matches) >= 15: break

    results = []
    for p in matches:
        proveedores_qs = ProductSupplier.objects.filter(product=p).select_related('supplier').order_by('-is_primary', 'supplier__company_name')
        lista_proveedores = []
        for prov in proveedores_qs:
            fecha_str = format(prov.last_updated, 'd/m/Y') if prov.last_updated else 'Sin fecha'
            lista_proveedores.append({
                'supplier_id': prov.supplier.supplier_id, 'name': prov.supplier.company_name,
                'cost': float(prov.current_cost), 'notes': prov.purchase_notes or '',
                'last_updated': fecha_str, 'is_primary': prov.is_primary
            })
        results.append({
            'id': p.product_id, 'name': p.name, 'barcode': p.barcode,
            'photo': p.photo.url if p.photo else None, 'suppliers': lista_proveedores
        })
    return JsonResponse(results, safe=False)

@csrf_exempt
def api_libreta_actualizar(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    try:
        ps, created = ProductSupplier.objects.update_or_create(
            product_id=request.POST.get('product_id'),
            supplier_id=request.POST.get('supplier_id'),
            defaults={'current_cost': request.POST.get('cost', 0), 'purchase_notes': request.POST.get('notes', '')}
        )
        return JsonResponse({'status': 'success', 'message': 'Precio actualizado'})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)})

@csrf_exempt
def api_proveedor_accion(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        accion = request.POST.get('accion')
        supplier_id = request.POST.get('supplier_id')
        user_id = request.session['user_id']
        
        if accion in ['deactivate', 'activate']:
            if accion == 'deactivate':
                password_confirm = request.POST.get('password_confirm')
                usuario = UsuarioPersonalizado.objects.get(user_id=user_id)
                if not check_password(password_confirm, usuario.password_hash): 
                    return JsonResponse({'status': 'error', 'message': 'Contraseña incorrecta.'})
                is_active_val = False
                msg = 'Proveedor dado de baja.'
            else:
                is_active_val = True
                msg = 'Proveedor reactivado.'

            proveedor = Supplier.objects.get(supplier_id=supplier_id)
            snapshot_antiguo = AuditLogger.get_snapshot(proveedor)
            proveedor.is_active = is_active_val
            proveedor.save()
            AuditLogger.log_action(user_id, proveedor, 'UPDATE', old_data=snapshot_antiguo)
            return JsonResponse({'status': 'success', 'message': msg})
            
        else:
            company_name = request.POST.get('company_name', '').strip()
            contact_name = request.POST.get('contact_name', '').strip()
            phone = request.POST.get('phone', '').strip()
            email = request.POST.get('email', '').strip()
            
            if not company_name: 
                return JsonResponse({'status': 'error', 'message': 'El nombre de la empresa es obligatorio.'})

            snapshot_antiguo = None
            is_new = False
            if accion == 'create':
                proveedor = Supplier()
                proveedor.is_active = True
                is_new = True 
            elif accion == 'update':
                proveedor = Supplier.objects.get(supplier_id=supplier_id)
                snapshot_antiguo = AuditLogger.get_snapshot(proveedor)

            proveedor.company_name = company_name
            proveedor.contact_name = contact_name
            proveedor.phone = phone
            proveedor.email = email

            if 'photo' in request.FILES:
                image = request.FILES['photo']
                fs = FileSystemStorage()
                filename = fs.save(f"suppliers/{int(datetime.now().timestamp())}_{image.name}", image)
                proveedor.photo = filename

            proveedor.save()
            proveedor.refresh_from_db()

            if is_new:
                AuditLogger.log_action(user_id, proveedor, 'CREATE')
            else:
                AuditLogger.log_action(user_id, proveedor, 'UPDATE', old_data=snapshot_antiguo)
                
            return JsonResponse({'status': 'success', 'message': "Proveedor guardado correctamente."})

    except Exception as e: 
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@csrf_exempt
def api_marca_accion(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)

    try:
        accion = request.POST.get('accion')
        brand_id = request.POST.get('brand_id')
        user_id = request.session['user_id']
        
        if accion in ['deactivate', 'activate']:
            marca = Brand.objects.get(brand_id=brand_id)
            snapshot = AuditLogger.get_snapshot(marca)
            marca.is_active = (accion == 'activate')
            marca.save()
            AuditLogger.log_action(user_id, marca, 'UPDATE', old_data=snapshot)
            return JsonResponse({'status': 'success', 'message': 'Estatus actualizado.'})
        else:
            name = request.POST.get('name', '').strip()
            if not name: return JsonResponse({'status': 'error', 'message': 'El nombre es obligatorio.'})

            snapshot = None
            if accion == 'create':
                marca = Brand(is_active=True)
            else:
                marca = Brand.objects.get(brand_id=brand_id)
                snapshot = AuditLogger.get_snapshot(marca)

            marca.name = name
            marca.save()
            
            AuditLogger.log_action(user_id, marca, 'CREATE' if accion == 'create' else 'UPDATE', old_data=snapshot)
            return JsonResponse({'status': 'success', 'message': 'Marca guardada correctamente.'})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)})

@csrf_exempt
def api_categoria_accion(request):
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)

    try:
        accion = request.POST.get('accion')
        category_id = request.POST.get('category_id')
        user_id = request.session['user_id']
        
        if accion in ['deactivate', 'activate']:
            categoria = Category.objects.get(category_id=category_id)
            snapshot = AuditLogger.get_snapshot(categoria)
            categoria.is_active = (accion == 'activate')
            categoria.save()
            AuditLogger.log_action(user_id, categoria, 'UPDATE', old_data=snapshot)
            return JsonResponse({'status': 'success', 'message': 'Estatus actualizado.'})
        else:
            name = request.POST.get('name', '').strip()
            desc = request.POST.get('description', '').strip()
            parent_id = request.POST.get('parent_id')

            if not name: return JsonResponse({'status': 'error', 'message': 'El nombre es obligatorio.'})

            snapshot = None
            if accion == 'create':
                categoria = Category(is_active=True)
            else:
                categoria = Category.objects.get(category_id=category_id)
                snapshot = AuditLogger.get_snapshot(categoria)

            categoria.name = name
            categoria.description = desc
            categoria.parent_id = parent_id if parent_id else None
            categoria.save()
            
            AuditLogger.log_action(user_id, categoria, 'CREATE' if accion == 'create' else 'UPDATE', old_data=snapshot)
            return JsonResponse({'status': 'success', 'message': 'Categoría guardada correctamente.'})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)})


def api_get_sales(request):
    """Obtiene las ventas paginadas de 30 en 30, con filtros por usuario y fecha"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    try:
        # 1. Recibir los parámetros desde el frontend
        page_number = request.GET.get('page', 1)
        user_id = request.GET.get('user')
        start_date = request.GET.get('start')
        end_date = request.GET.get('end')

        sales_qs = Sale.objects.select_related('user').all().order_by('-created_at')
        
        # 2. Aplicar los filtros si el usuario los mandó
        if user_id:
            sales_qs = sales_qs.filter(user_id=user_id)
        if start_date:
            sales_qs = sales_qs.filter(created_at__date__gte=datetime.strptime(start_date, '%Y-%m-%d'))
        if end_date:
            sales_qs = sales_qs.filter(created_at__date__lte=datetime.strptime(end_date, '%Y-%m-%d'))

        # 3. Paginación configurada a 30 elementos
        paginator = Paginator(sales_qs, 30)
        page_obj = paginator.get_page(page_number)
        
        data = []
        for s in page_obj:
            if timezone.is_aware(s.created_at):
                fecha_str = timezone.localtime(s.created_at).strftime('%d/%m/%Y %H:%M')
            else:
                fecha_str = s.created_at.strftime('%d/%m/%Y %H:%M')

            data.append({
                'id': s.sale_id,
                'date': fecha_str,
                'total': float(s.total),
                'method': s.payment_method,
                'status': s.status,
                'cashier': s.user.full_name if s.user else 'Desconocido'
            })
            
        return JsonResponse({
            'sales': data,
            'pagination': {
                'current_page': page_obj.number,
                'num_pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'total_records': paginator.count
            }
        }, safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def api_get_sale_details(request, sale_id):
    """Obtiene los detalles de una venta específica (para armar el ticket virtual)"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    try:
        sale = Sale.objects.select_related('user').get(sale_id=sale_id)
        details = SaleDetail.objects.filter(sale=sale).select_related('product')
        
        items = []
        for d in details:
            items.append({
                'detail_id': d.detail_id, # <--- ENVIAMOS EL ID DEL DETALLE AL FRONTEND
                'name': d.product.name,
                'qty': float(d.quantity),
                'price': float(d.unit_price),
                'subtotal': float(d.subtotal),
                'deposit_charged': float(d.deposit_charged) # Enviamos el importe también
            })
            
        if timezone.is_aware(sale.created_at):
            fecha_str = timezone.localtime(sale.created_at).strftime('%d/%m/%Y %H:%M')
        else:
            fecha_str = sale.created_at.strftime('%d/%m/%Y %H:%M')
            
        return JsonResponse({
            'id': sale.sale_id,
            'date': fecha_str,
            'total': float(sale.total),
            'method': sale.payment_method,
            'status': sale.status,
            'cashier': sale.user.full_name if sale.user else 'Desconocido',
            'amount_cash': float(sale.amount_cash),
            'amount_card': float(sale.amount_card),
            'commission': float(sale.card_commission),
            'cash_received': float(sale.cash_received) if sale.cash_received else 0,
            'change_given': float(sale.change_given) if sale.change_given else 0,
            'items': items
        })
    except Sale.DoesNotExist:
        return JsonResponse({'error': 'Venta no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@transaction.atomic
def api_cancel_sale(request):
    """Cancela la venta y devuelve el stock al inventario"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    
    try:
        sale_id = request.POST.get('sale_id')
        password = request.POST.get('password')
        user_id = request.session['user_id']
        
        usuario = UsuarioPersonalizado.objects.get(user_id=user_id)
        if not check_password(password, usuario.password_hash):
            return JsonResponse({'status': 'error', 'message': 'Contraseña incorrecta.'})
            
        sale = Sale.objects.get(sale_id=sale_id)
        if sale.status == 'CANCELLED':
            return JsonResponse({'status': 'error', 'message': 'La venta ya estaba cancelada.'})
            
        snapshot = AuditLogger.get_snapshot(sale)
        sale.status = 'CANCELLED'
        sale.save()
        
        details = SaleDetail.objects.filter(sale=sale)
        for d in details:
            InventoryStock.objects.filter(product=d.product).update(
                quantity=F('quantity') + d.quantity
            )
            InventoryMovement.objects.create(
                product=d.product,
                user_id=user_id,
                type='RETURN',
                quantity=d.quantity,
                reference_id=sale.sale_id,
                reason=f'Cancelación Venta #{sale.sale_id}'
            )
            
        AuditLogger.log_action(user_id, sale, 'UPDATE', old_data=snapshot)
        return JsonResponse({'status': 'success', 'message': 'Venta cancelada y stock devuelto.'})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

def api_get_services(request):
    """Devuelve los productos marcados como servicio (Ej: Telcel, Movistar)"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    services = Product.objects.filter(is_active=True, is_service=True).order_by('name')
    results = [{'id': p.product_id, 'name': p.name, 'photo': p.photo.url if p.photo else None} for p in services]
    return JsonResponse(results, safe=False)

def api_get_users_list(request):
    """Devuelve la lista de usuarios para el filtro select"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    users = UsuarioPersonalizado.objects.values('user_id', 'full_name', 'username').order_by('full_name')
    return JsonResponse(list(users), safe=False)

def api_get_audit_logs(request):
    """Obtiene los logs de auditoría filtrados y paginados de 50 en 50"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    # Recibir filtros y número de página
    user_id = request.GET.get('user')
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    page_number = request.GET.get('page', 1)
    
    logs_qs = AuditLog.objects.all().order_by('-timestamp')
    
    # Aplicar Filtros
    if user_id:
        logs_qs = logs_qs.filter(user_id=user_id)
    if start_date:
        logs_qs = logs_qs.filter(timestamp__date__gte=datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        logs_qs = logs_qs.filter(timestamp__date__lte=datetime.strptime(end_date, '%Y-%m-%d'))
        
    # --- APLICAR PAGINACIÓN (50 POR PÁGINA) ---
    paginator = Paginator(logs_qs, 30)
    page_obj = paginator.get_page(page_number)
    
    users_map = {u['user_id']: u['full_name'] for u in UsuarioPersonalizado.objects.values('user_id', 'full_name')}
    
    data = []
    for log in page_obj:
        # Usa forzar_hora_local si la tienes, o usa timezone.localtime normal
        dt = log.timestamp
        if timezone.is_naive(dt): dt = timezone.make_aware(dt, timezone.utc)
        fecha_str = timezone.localtime(dt).strftime('%d/%m/%Y %I:%M %p')
        
        data.append({
            'id': log.log_id,
            'date': fecha_str,
            'table': log.table_name,
            'record_id': log.record_id,
            'action': log.action,
            'user_name': users_map.get(log.user_id, 'Sistema / Desconocido'),
            'old_data': log.old_data if log.old_data else {},
            'new_data': log.new_data if log.new_data else {}
        })
        
    # Devolver JSON estructurado con datos de paginación
    return JsonResponse({
        'logs': data,
        'pagination': {
            'current_page': page_obj.number,
            'num_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'total_records': paginator.count
        }
    }, safe=False)

def api_get_price_history(request):
    """Obtiene el historial de cambios de precios/costos paginado"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    search = request.GET.get('q', '').strip()
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    page_number = request.GET.get('page', 1)
    
    # Consultamos la tabla PriceHistory uniendo Producto y Usuario
    qs = PriceHistory.objects.select_related('product', 'changed_by').all().order_by('-changed_at')
    
    # Aplicar Filtros
    if search:
        query_norm = normalizar_texto(search)
        qs = qs.filter(Q(product__name__icontains=query_norm) | Q(product__barcode__icontains=search))
    if start_date:
        qs = qs.filter(changed_at__date__gte=datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        qs = qs.filter(changed_at__date__lte=datetime.strptime(end_date, '%Y-%m-%d'))
        
    # Paginación (50 elementos)
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(page_number)
    
    data = []
    for h in page_obj:
        # --- MANEJO DE FECHA LIMPIO (Sin el parche, confiando en la BD) ---
        dt = h.changed_at
        if timezone.is_aware(dt):
            fecha_str = timezone.localtime(dt).strftime('%d/%m/%Y %I:%M %p')
        else:
            fecha_str = dt.strftime('%d/%m/%Y %I:%M %p')
        
        data.append({
            'id': h.history_id,
            'date': fecha_str,
            'product_name': h.product.name,
            'barcode': h.product.barcode or 'S/C',
            'old_cost': float(h.old_cost) if h.old_cost is not None else None,
            'new_cost': float(h.new_cost) if h.new_cost is not None else None,
            'old_price': float(h.old_price) if h.old_price is not None else None,
            'new_price': float(h.new_price) if h.new_price is not None else None,
            'user': h.changed_by.full_name if h.changed_by else 'Sistema'
        })
        
    return JsonResponse({
        'history': data,
        'pagination': {
            'current_page': page_obj.number,
            'num_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'total_records': paginator.count
        }
    }, safe=False)

def api_get_stock_movements(request):
    """Obtiene el historial de movimientos de inventario paginado"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    search = request.GET.get('q', '').strip()
    mov_type = request.GET.get('type', '')
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    page_number = request.GET.get('page', 1)
    
    # Consultamos la tabla InventoryMovement uniendo Producto y Usuario
    qs = InventoryMovement.objects.select_related('product', 'user').all().order_by('-created_at')
    
    # Aplicar Filtros
    if search:
        query_norm = normalizar_texto(search)
        qs = qs.filter(Q(product__name__icontains=query_norm) | Q(product__barcode__icontains=search))
    if mov_type:
        qs = qs.filter(type=mov_type)
    if start_date:
        qs = qs.filter(created_at__date__gte=datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        qs = qs.filter(created_at__date__lte=datetime.strptime(end_date, '%Y-%m-%d'))
        
    # Paginación (50 elementos)
    from django.core.paginator import Paginator
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(page_number)
    
    data = []
    for m in page_obj:
        dt = m.created_at
        if timezone.is_aware(dt):
            fecha_str = timezone.localtime(dt).strftime('%d/%m/%Y %I:%M %p')
        else:
            fecha_str = dt.strftime('%d/%m/%Y %I:%M %p')
        
        data.append({
            'id': m.movement_id,
            'date': fecha_str,
            'product_name': m.product.name,
            'barcode': m.product.barcode or 'S/C',
            'type': m.type,
            'quantity': float(m.quantity),
            'user': m.user.full_name if m.user else 'Sistema',
            'reason': m.reason or 'Sin detalles',
            'reference': m.reference_id or '-'
        })
        
    return JsonResponse({
        'movements': data,
        'pagination': {
            'current_page': page_obj.number,
            'num_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'total_records': paginator.count
        }
    }, safe=False)

def api_get_roles(request):
    """Obtiene la lista de roles y cuántos usuarios activos tienen asignados"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    roles = Role.objects.all().order_by('role_id')
    data = []
    for r in roles:
        # Cuenta cuántos usuarios activos pertenecen a este rol
        users_count = UsuarioPersonalizado.objects.filter(role_id=r.role_id, is_active=True).count()
        data.append({
            'id': r.role_id,
            'name': r.name,
            'description': r.description or '',
            # Detectamos si es el rol maestro (ID 1 o llamado Administrador)
            'is_admin': r.role_id == 1 or r.name.lower() == 'administrador',
            'users_count': users_count
        })
    return JsonResponse(data, safe=False)

@csrf_exempt
def api_role_accion(request):
    """Crea, edita o elimina roles con protección estricta para el Administrador"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    
    try:
        accion = request.POST.get('accion')
        role_id = request.POST.get('role_id')
        user_id = request.session['user_id']
        
        if accion == 'delete':
            role = Role.objects.get(role_id=role_id)
            
            # 🛡️ SEGURIDAD: Bloquear eliminación de Admin
            if role.role_id == 1 or role.name.lower() == 'administrador':
                return JsonResponse({'status': 'error', 'message': 'Acceso Denegado: El rol de Administrador es inamovible del sistema.'})
            
            # 🛡️ SEGURIDAD: No borrar si hay usuarios usándolo
            if UsuarioPersonalizado.objects.filter(role_id=role_id).exists():
                return JsonResponse({'status': 'error', 'message': 'No puedes eliminar este rol porque tiene usuarios asignados. Cambia los usuarios a otro rol primero.'})
                
            snapshot = AuditLogger.get_snapshot(role)
            role.delete()
            AuditLogger.log_action(user_id, role, 'DELETE', old_data=snapshot)
            return JsonResponse({'status': 'success', 'message': 'Rol eliminado exitosamente.'})
            
        else:
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            
            if not name: return JsonResponse({'status': 'error', 'message': 'El nombre del rol es obligatorio.'})
            
            if accion == 'update':
                role = Role.objects.get(role_id=role_id)
                
                # 🛡️ SEGURIDAD: Evitar que le cambien el nombre al Admin
                if role.role_id == 1 or role.name.lower() == 'administrador':
                    if name.lower() != 'administrador':
                        return JsonResponse({'status': 'error', 'message': 'No puedes cambiar el nombre del rol maestro.'})
                        
                snapshot = AuditLogger.get_snapshot(role)
                role.name = name
                role.description = description
                role.save()
                AuditLogger.log_action(user_id, role, 'UPDATE', old_data=snapshot)
                return JsonResponse({'status': 'success', 'message': 'Rol actualizado correctamente.'})
                
            elif accion == 'create':
                if Role.objects.filter(name__iexact=name).exists():
                    return JsonResponse({'status': 'error', 'message': 'Ya existe un rol con ese mismo nombre.'})
                    
                role = Role(name=name, description=description)
                role.save()
                AuditLogger.log_action(user_id, role, 'CREATE')
                return JsonResponse({'status': 'success', 'message': 'Nuevo rol creado exitosamente.'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    

def api_get_shifts(request):
    """Obtiene el historial de turnos y cortes de caja paginado"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    # Recibir filtros
    user_id = request.GET.get('user')
    status = request.GET.get('status')
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    page_number = request.GET.get('page', 1)
    
    # Consultar los turnos (Shifts)
    qs = Shift.objects.select_related('user').all().order_by('-start_time')
    
    # Aplicar Filtros
    if user_id: qs = qs.filter(user_id=user_id)
    if status == 'OPEN': qs = qs.filter(is_closed=False)
    elif status == 'CLOSED': qs = qs.filter(is_closed=True)
    if start_date: qs = qs.filter(start_time__date__gte=datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date: qs = qs.filter(start_time__date__lte=datetime.strptime(end_date, '%Y-%m-%d'))
        
    from django.core.paginator import Paginator
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(page_number)
    
    data = []
    for s in page_obj:
        # Formateo de horas de apertura y cierre
        st = s.start_time
        et = s.end_time
        if timezone.is_aware(st): st = timezone.localtime(st)
        start_str = st.strftime('%d/%m/%Y %I:%M %p')
        
        end_str = 'Turno Activo'
        if et:
            if timezone.is_aware(et): et = timezone.localtime(et)
            end_str = et.strftime('%d/%m/%Y %I:%M %p')
            
        data.append({
            'id': s.shift_id,
            'user': s.user.full_name if s.user else 'Desconocido',
            'start_time': start_str,
            'end_time': end_str,
            'initial_cash': float(s.initial_cash),
            'final_expected': float(s.final_cash_expected) if s.final_cash_expected is not None else None,
            'final_counted': float(s.final_cash_counted) if s.final_cash_counted is not None else None,
            'difference': float(s.difference) if s.difference is not None else None,
            'is_closed': s.is_closed
        })
        
    return JsonResponse({
        'shifts': data,
        'pagination': {
            'current_page': page_obj.number,
            'num_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'total_records': paginator.count
        }
    }, safe=False)

def api_get_usuarios(request):
    """Obtiene la lista de usuarios del sistema con sus roles"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    # Excluimos contraseñas por seguridad
    usuarios = UsuarioPersonalizado.objects.select_related('role').all().order_by('user_id')
    
    data = []
    for u in usuarios:
        fecha_str = u.created_at.strftime('%d/%m/%Y') if u.created_at else ''
        data.append({
            'id': u.user_id,
            'username': u.username,
            'full_name': u.full_name,
            'role_id': u.role_id,
            'role_name': u.role.name if u.role else 'Sin Rol',
            'is_active': u.is_active,
            'created_at': fecha_str
        })
    return JsonResponse(data, safe=False)

@csrf_exempt
def api_usuario_accion(request):
    """Crear, editar, activar o desactivar usuarios"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    
    try:
        accion = request.POST.get('accion')
        target_user_id = request.POST.get('user_id')
        current_user_id = request.session['user_id']
        
        from django.contrib.auth.hashers import make_password
        
        # --- BAJA / ALTA ---
        if accion in ['deactivate', 'activate']:
            if str(target_user_id) == str(current_user_id) and accion == 'deactivate':
                return JsonResponse({'status': 'error', 'message': 'No puedes darte de baja a ti mismo.'})
                
            usuario_obj = UsuarioPersonalizado.objects.get(user_id=target_user_id)
            
            # 🛡️ Proteger Admin Maestro (Usuario 1)
            if str(target_user_id) == '1' and accion == 'deactivate':
                 return JsonResponse({'status': 'error', 'message': 'El administrador principal es inamovible.'})
            
            snapshot = AuditLogger.get_snapshot(usuario_obj)
            usuario_obj.is_active = (accion == 'activate')
            usuario_obj.save()
            AuditLogger.log_action(current_user_id, usuario_obj, 'UPDATE', old_data=snapshot)
            msg = 'Usuario reactivado.' if accion == 'activate' else 'Usuario dado de baja.'
            return JsonResponse({'status': 'success', 'message': msg})
            
        # --- CREAR / EDITAR ---
        else:
            username = request.POST.get('username', '').strip()
            full_name = request.POST.get('full_name', '').strip()
            role_id = request.POST.get('role_id')
            password = request.POST.get('password', '')
            
            if not username or not full_name or not role_id:
                return JsonResponse({'status': 'error', 'message': 'Faltan datos obligatorios.'})

            snapshot = None
            is_new = False
            
            if accion == 'create':
                if not password:
                    return JsonResponse({'status': 'error', 'message': 'La contraseña es obligatoria para nuevos usuarios.'})
                if UsuarioPersonalizado.objects.filter(username__iexact=username).exists():
                    return JsonResponse({'status': 'error', 'message': 'El nombre de usuario ya está en uso.'})
                    
                usuario_obj = UsuarioPersonalizado()
                usuario_obj.is_active = True
                is_new = True 
                
            elif accion == 'update':
                usuario_obj = UsuarioPersonalizado.objects.get(user_id=target_user_id)
                
                # 🛡️ Proteger admin maestro para que no le quiten el rol
                if str(target_user_id) == '1' and str(role_id) != '1':
                    return JsonResponse({'status': 'error', 'message': 'No puedes quitarle el rol maestro al usuario principal.'})
                
                if UsuarioPersonalizado.objects.filter(username__iexact=username).exclude(user_id=target_user_id).exists():
                    return JsonResponse({'status': 'error', 'message': 'El nombre de usuario ya está en uso por otra persona.'})
                    
                snapshot = AuditLogger.get_snapshot(usuario_obj)

            usuario_obj.username = username
            usuario_obj.full_name = full_name
            usuario_obj.role_id = role_id
            
            # Si escribieron una contraseña nueva, la encriptamos y la guardamos
            if password: 
                usuario_obj.password_hash = make_password(password)

            usuario_obj.save()

            if is_new:
                AuditLogger.log_action(current_user_id, usuario_obj, 'CREATE')
                msg = 'Usuario creado exitosamente.'
            else:
                AuditLogger.log_action(current_user_id, usuario_obj, 'UPDATE', old_data=snapshot)
                msg = 'Usuario actualizado correctamente.'
                
            return JsonResponse({'status': 'success', 'message': msg})

    except Exception as e: 
        return JsonResponse({'status': 'error', 'message': str(e)})
    

def api_conteo_productos(request):
    """Obtiene los productos de una categoría para el conteo físico"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    cat_id = request.GET.get('category_id')
    if not cat_id: return JsonResponse([], safe=False)
    
    # Solo productos físicos y activos
    productos = Product.objects.filter(category_id=cat_id, is_active=True, is_service=False).select_related('category')
    
    data = []
    for p in productos:
        stock_record = InventoryStock.objects.filter(product=p).first()
        stock_qty = float(stock_record.quantity) if stock_record else 0.0
        
        data.append({
            'id': p.product_id,
            'name': p.name,
            'barcode': p.barcode or 'S/C',
            'category': p.category.name if p.category else 'Sin Categoría',
            'photo': p.photo.url if p.photo else None,
            'system_qty': stock_qty
        })
    return JsonResponse(data, safe=False)

@csrf_exempt
@transaction.atomic
def api_conteo_procesar(request):
    """Procesa el conteo, actualiza el stock y genera los movimientos"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    
    try:
        data = json.loads(request.body)
        cat_id = data.get('category_id')
        items = data.get('items', []) # Solo trae los que tuvieron diferencias
        user_id = request.session['user_id']
        
        if not items:
            return JsonResponse({'status': 'error', 'message': 'No se enviaron diferencias para ajustar.'})
            
        # 1. Crear el registro del Conteo (Auditoría)
        conteo = PhysicalCount.objects.create(
            user_id=user_id,
            category_id=cat_id
        )
        
        # 2. Procesar cada diferencia
        for item in items:
            p_id = item['id']
            sys_qty = float(item['system_qty'])
            real_qty = float(item['counted_qty'])
            diff = real_qty - sys_qty
            
            # Solo guardamos si realmente hay diferencia
            if diff != 0:
                # Guardar en detalle del conteo
                PhysicalCountDetail.objects.create(
                    count=conteo, product_id=p_id,
                    system_qty=sys_qty, counted_qty=real_qty, difference=diff
                )
                
                # Actualizar Stock Real
                InventoryStock.objects.filter(product_id=p_id).update(quantity=real_qty)
                
                # Registrar el Movimiento en el Kardex General
                m_type = 'ADJ_ADD' if diff > 0 else 'ADJ_SUB'
                InventoryMovement.objects.create(
                    product_id=p_id, user_id=user_id,
                    type=m_type, quantity=abs(diff),
                    reference_id=conteo.count_id,
                    reason=f'Verificación Física #{conteo.count_id}'
                )
                
        return JsonResponse({'status': 'success', 'count_id': conteo.count_id})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

def api_conteo_historial(request):
    """Obtiene el historial de conteos y el detalle de un conteo específico si se pide"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    count_id = request.GET.get('count_id')
    
    # Si piden el detalle de un conteo para imprimir el reporte:
    if count_id:
        conteo = PhysicalCount.objects.select_related('user', 'category').get(count_id=count_id)
        detalles = PhysicalCountDetail.objects.filter(count=conteo).select_related('product')
        
        dt = timezone.localtime(conteo.created_at) if timezone.is_aware(conteo.created_at) else conteo.created_at
        
        data = {
            'id': conteo.count_id,
            'date': dt.strftime('%d/%m/%Y %I:%M %p'),
            'user': conteo.user.full_name,
            'category': conteo.category.name if conteo.category else 'General',
            'items': [{
                'name': d.product.name,
                'barcode': d.product.barcode,
                'system_qty': float(d.system_qty),
                'counted_qty': float(d.counted_qty),
                'diff': float(d.difference)
            } for d in detalles]
        }
        return JsonResponse(data)
    
    # Si no, devolvemos la lista general de conteos pasados
    conteos = PhysicalCount.objects.select_related('user', 'category').all().order_by('-created_at')[:50]
    data = []
    for c in conteos:
        dt = timezone.localtime(c.created_at) if timezone.is_aware(c.created_at) else c.created_at
        data.append({
            'id': c.count_id,
            'date': dt.strftime('%d/%m/%Y %I:%M %p'),
            'user': c.user.full_name,
            'category': c.category.name if c.category else 'General',
        })
    return JsonResponse(data, safe=False)


@csrf_exempt
@transaction.atomic
def api_devolver_envase(request):
    """Registra la salida de dinero por devolución de un envase vacío"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    
    try:
        amount = float(request.POST.get('amount', 0))
        user_id = request.session['user_id']
        
        if amount <= 0: return JsonResponse({'status': 'error', 'message': 'Monto inválido.'})
        
        # Buscar el turno activo del cajero
        shift = Shift.objects.filter(user_id=user_id, is_closed=False).first()
        if not shift:
            return JsonResponse({'status': 'error', 'message': 'No tienes un turno de caja abierto.'})
            
        # Registrar la devolución en la base de datos
        from .models import BottleReturn
        BottleReturn.objects.create(
            shift=shift,
            user_id=user_id,
            amount=amount
        )
        
        # Guardar en auditoría
        AuditLogger.log_action(user_id, shift, 'UPDATE', old_data={'action': 'Devolución de Envase', 'amount': amount})
        
        return JsonResponse({'status': 'success', 'message': f'Se registraron ${amount} de devolución.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    
from decimal import Decimal

@csrf_exempt
@transaction.atomic
def api_cancel_sale_item(request):
    """Cancela una cantidad específica de un artículo de una venta y devuelve el stock"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    if request.method != 'POST': return JsonResponse({'error': '405'}, status=405)
    
    try:
        sale_id = request.POST.get('sale_id')
        detail_id = request.POST.get('detail_id')
        password = request.POST.get('password')
        
        # Leemos la cantidad exacta a devolver (por defecto 1 si no se envía)
        return_qty = Decimal(request.POST.get('return_qty', 1)) 
        user_id = request.session['user_id']
        
        # Validación de contraseña
        usuario = UsuarioPersonalizado.objects.get(user_id=user_id)
        if not check_password(password, usuario.password_hash):
            return JsonResponse({'status': 'error', 'message': 'Contraseña incorrecta.'})
            
        sale = Sale.objects.get(sale_id=sale_id)
        if sale.status == 'CANCELLED':
            return JsonResponse({'status': 'error', 'message': 'La venta completa ya estaba cancelada.'})
            
        # Obtener el detalle específico
        try:
            detail = SaleDetail.objects.get(detail_id=detail_id, sale=sale)
        except SaleDetail.DoesNotExist:
             return JsonResponse({'status': 'error', 'message': 'El artículo no pertenece a esta venta.'})

        # Validaciones de cantidad
        if detail.quantity <= 0:
            return JsonResponse({'status': 'error', 'message': 'Este artículo ya fue devuelto en su totalidad.'})
        
        if return_qty <= 0 or return_qty > detail.quantity:
            return JsonResponse({'status': 'error', 'message': 'La cantidad a devolver es mayor a la comprada.'})

        # --- CÁLCULOS PROPORCIONALES ---
        # Calculamos cuánto importe por envase corresponde a cada unidad
        deposit_unit = detail.deposit_charged / detail.quantity if detail.quantity > 0 else Decimal('0.00')
        
        qty_to_return = return_qty
        subtotal_to_subtract = detail.unit_price * qty_to_return
        deposit_to_subtract = deposit_unit * qty_to_return

        snapshot_sale = AuditLogger.get_snapshot(sale)
        
        # 1. Devolver el stock (solo si no es servicio)
        if not detail.product.is_service:
            InventoryStock.objects.filter(product=detail.product).update(
                quantity=F('quantity') + qty_to_return
            )
            
        # 2. Registrar el movimiento de inventario (Retorno)
        InventoryMovement.objects.create(
            product=detail.product,
            user_id=user_id,
            type='RETURN',
            quantity=qty_to_return,
            reference_id=sale.sale_id,
            reason=f'Devolución parcial Venta #{sale.sale_id}'
        )

        # 3. Ajustar los totales de la venta
        sale.subtotal -= subtotal_to_subtract
        sale.total -= (subtotal_to_subtract + deposit_to_subtract)
        
        total_a_restar = subtotal_to_subtract + deposit_to_subtract
        
        # Descontar del método de pago
        if sale.amount_cash >= total_a_restar:
             sale.amount_cash -= total_a_restar
        else:
             restante = total_a_restar - sale.amount_cash
             sale.amount_cash = 0
             sale.amount_card -= restante
             
        sale.save()

        # 4. Actualizar la línea del ticket
        detail.quantity -= qty_to_return
        detail.subtotal -= subtotal_to_subtract
        detail.deposit_charged -= deposit_to_subtract
        detail.save()

        # Si la venta se queda totalmente vacía, la cancelamos completa
        detalles_restantes = SaleDetail.objects.filter(sale=sale, quantity__gt=0).count()
        if detalles_restantes == 0:
             sale.status = 'CANCELLED'
             sale.save()

        AuditLogger.log_action(user_id, sale, 'UPDATE', old_data=snapshot_sale)
        
        return JsonResponse({
            'status': 'success', 
            'message': f'Se devolvieron {qty_to_return} unidades. Se restaron ${total_a_restar} de la venta.',
            'sale_total': float(sale.total),
            'sale_status': sale.status
        })
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    

def api_reporte_gastos(request):
    """Genera el reporte detallado de gastos operativos (Tomas Internas)"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    
    try:
        fecha_inicio = datetime.strptime(start_date, '%Y-%m-%d')
        fecha_fin = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    except Exception:
        return JsonResponse({'error': 'Fechas inválidas'}, status=400)

    # Buscar tomas aprobadas, ordenadas de la más reciente a la más antigua
    tomas = InternalWithdrawal.objects.filter(
        created_at__range=(fecha_inicio, fecha_fin), 
        status='APPROVED'
    ).select_related('product').order_by('-created_at')

    total_gastos = 0
    total_tomas = 0
    productos_count = {}
    dias_count = {}
    agrupado = {}

    dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

    for toma in tomas:
        costo_total = float(toma.unit_cost * toma.quantity)
        total_gastos += costo_total
        total_tomas += 1

        p_name = toma.product.name
        productos_count[p_name] = productos_count.get(p_name, 0) + float(toma.quantity)

        # Fecha y día de la semana
        dt = timezone.localtime(toma.created_at) if timezone.is_aware(toma.created_at) else toma.created_at
        dia_str = dias_semana[dt.weekday()]
        dias_count[dia_str] = dias_count.get(dia_str, 0) + 1

        # Agrupar por fecha
        fecha_str = dt.strftime('%d/%m/%Y')
        if fecha_str not in agrupado:
            agrupado[fecha_str] = {'fecha': fecha_str, 'dia_semana': dia_str, 'total_dia': 0, 'tomas': []}

        agrupado[fecha_str]['total_dia'] += costo_total
        agrupado[fecha_str]['tomas'].append({
            'hora': dt.strftime('%I:%M %p'),
            'producto': p_name,
            'cantidad': float(toma.quantity),
            'costo_unitario': float(toma.unit_cost),
            'total': costo_total,
            'beneficiario': toma.beneficiary_name or 'General',
            'motivo': toma.reason
        })

    # Calcular los TOPs
    producto_top = max(productos_count, key=productos_count.get) if productos_count else 'Ninguno'
    dia_frecuente = max(dias_count, key=dias_count.get) if dias_count else 'Ninguno'

    return JsonResponse({
        'kpis': {
            'total_gastos': total_gastos,
            'total_tomas': total_tomas,
            'producto_top': producto_top,
            'dia_frecuente': dia_frecuente
        },
        'dias': list(agrupado.values())
    })

# ==========================================
# NUEVOS REPORTES AVANZADOS
# ==========================================

def api_reporte_zombies(request):
    """Busca productos que NO se han vendido en el rango de fechas seleccionado (dinero congelado)"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    try:
        fecha_inicio = datetime.strptime(request.GET.get('start'), '%Y-%m-%d')
        fecha_fin = datetime.strptime(request.GET.get('end'), '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    except: return JsonResponse({'error': 'Fechas inválidas'}, status=400)

    # 1. Obtenemos los IDs de los productos que SÍ se vendieron en este periodo
    vendidos_ids = SaleDetail.objects.filter(
        sale__created_at__range=(fecha_inicio, fecha_fin),
        sale__status='COMPLETED'
    ).values_list('product_id', flat=True).distinct()

    # 2. Filtramos el inventario: Activos, físicos, con stock > 0, y que NO están en los vendidos
    zombies_stock = InventoryStock.objects.filter(
        product__is_active=True,
        product__is_service=False,
        quantity__gt=0
    ).exclude(product_id__in=vendidos_ids).select_related('product')

    data = []
    total_congelado = 0
    for stock in zombies_stock:
        p = stock.product
        inversion = float(stock.quantity * p.cost_price)
        total_congelado += inversion
        data.append({
            'name': p.name,
            'barcode': p.barcode or 'S/C',
            'stock': float(stock.quantity),
            'cost': float(p.cost_price),
            'inversion': inversion
        })

    # Ordenar del que tiene más dinero congelado al que tiene menos
    data.sort(key=lambda x: x['inversion'], reverse=True)

    return JsonResponse({
        'zombies': data,
        'kpis': {
            'total_congelado': total_congelado,
            'total_productos': len(data)
        }
    })

def api_reporte_proveedores(request):
    """Suma las compras realizadas a proveedores en el rango de fechas"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    try:
        fecha_inicio = datetime.strptime(request.GET.get('start'), '%Y-%m-%d')
        fecha_fin = datetime.strptime(request.GET.get('end'), '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    except: return JsonResponse({'error': 'Fechas inválidas'}, status=400)

    compras = InventoryMovement.objects.filter(
        type='IN_PURCHASE',
        created_at__range=(fecha_inicio, fecha_fin)
    ).select_related('product')

    proveedores_dict = {}
    total_invertido = 0

    for compra in compras:
        # Extraemos el proveedor de la nota del movimiento
        reason = compra.reason or ""
        prov_name = reason.replace("Compra - Prov: ", "").strip() if "Prov:" in reason else "General / Sin Proveedor"
        
        if prov_name not in proveedores_dict:
            proveedores_dict[prov_name] = {'nombre': prov_name, 'cantidad': 0, 'monto': 0}
        
        # Calcular monto (cantidad ingresada * costo del producto)
        monto = float(compra.quantity * compra.product.cost_price)
        proveedores_dict[prov_name]['cantidad'] += float(compra.quantity)
        proveedores_dict[prov_name]['monto'] += monto
        total_invertido += monto

    # Convertir a lista y ordenar por mayor gasto
    lista = list(proveedores_dict.values())
    lista.sort(key=lambda x: x['monto'], reverse=True)

    return JsonResponse({
        'proveedores': lista,
        'kpis': {
            'total_compras': total_invertido,
            'top_proveedor': lista[0]['nombre'] if lista else '-'
        }
    })

def api_reporte_horas(request):
    """Mapea en qué horario del día suceden las ventas"""
    if 'user_id' not in request.session: return JsonResponse({'error': '401'}, status=401)
    
    try:
        fecha_inicio = datetime.strptime(request.GET.get('start'), '%Y-%m-%d')
        fecha_fin = datetime.strptime(request.GET.get('end'), '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    except: return JsonResponse({'error': 'Fechas inválidas'}, status=400)

    ventas = Sale.objects.filter(
        created_at__range=(fecha_inicio, fecha_fin),
        status='COMPLETED'
    )

    # Inicializar diccionario con las 24 horas del día (00 a 23)
    horas_dict = {str(i).zfill(2): {'hora': f"{str(i).zfill(2)}:00", 'tickets': 0, 'ingresos': 0} for i in range(24)}

    for v in ventas:
        dt = timezone.localtime(v.created_at) if timezone.is_aware(v.created_at) else v.created_at
        h_str = dt.strftime('%H') # Saca solo la hora "14", "09", etc
        horas_dict[h_str]['tickets'] += 1
        horas_dict[h_str]['ingresos'] += float(v.total)

    lista_horas = list(horas_dict.values())
    
    # Calcular KPIs
    hora_top_tk = max(lista_horas, key=lambda x: x['tickets'])
    hora_top_ing = max(lista_horas, key=lambda x: x['ingresos'])
    
    return JsonResponse({
        'labels': [h['hora'] for h in lista_horas],
        'tickets': [h['tickets'] for h in lista_horas],
        'ingresos': [h['ingresos'] for h in lista_horas],
        'kpis': {
            'hora_pico_tickets': hora_top_tk['hora'] if hora_top_tk['tickets'] > 0 else '-',
            'hora_pico_ingresos': hora_top_ing['hora'] if hora_top_ing['ingresos'] > 0 else '-'
        }
    })