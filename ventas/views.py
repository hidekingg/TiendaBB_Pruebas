# ventas/views.py
from datetime import datetime, timedelta
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q, F
from django.utils import timezone
from django.template.loader import render_to_string
from django.db import connection
import weasyprint

from .forms import PerfilForm
from django.shortcuts import get_object_or_404

# Modelos
from .models import (
    CashRegister, UsuarioPersonalizado, Product, Promotion, 
    Brand, Sale, SaleDetail, InternalWithdrawal,
    Category, UnitOfMeasure, Supplier, InventoryStock  # <--- AGREGAR AQUÍ
)

# Servicios
from .services import (
    obtener_turno_activo, abrir_turno, cerrar_turno,
    obtener_resumen_dashboard, obtener_inventario_completo
)

# ==========================================
# VISTAS DE AUTENTICACIÓN Y SISTEMA (HTML)
# ==========================================

def login_view(request):
    if request.method == 'POST':
        user_input = request.POST.get('username')
        pass_input = request.POST.get('password')
        try:
            usuario = UsuarioPersonalizado.objects.get(username=user_input)
            if not usuario.is_active:
                messages.error(request, "Usuario desactivado.")
                return render(request, 'login.html')
            
            if check_password(pass_input, usuario.password_hash):
                request.session['user_id'] = usuario.user_id
                request.session['user_role'] = usuario.role.name
                request.session['user_name'] = usuario.full_name
                request.session['user_photo'] = usuario.photo.url if usuario.photo else None
                return redirect('dashboard_admin' if usuario.role.name == 'ADMIN' else 'punto_venta')
            else:
                messages.error(request, "Contraseña incorrecta.")
        except UsuarioPersonalizado.DoesNotExist:
            messages.error(request, "El usuario no existe.")
    return render(request, 'login.html')

def logout_view(request):
    request.session.flush()
    return redirect('login')

def dashboard_admin(request):
    if 'user_id' not in request.session: return redirect('login')
    stats = obtener_resumen_dashboard()
    return render(request, 'dashboard.html', {
        'nombre_usuario': request.session.get('user_name'),
        'rol': request.session.get('user_role'),
        'ventas_hoy': stats['ventas_hoy'],
        'bajos_stock': stats['bajos_stock'],
    })

def punto_venta(request):
    if 'user_id' not in request.session: return redirect('login')
    turno = obtener_turno_activo(request.session['user_id'])
    if not turno: return redirect('abrir_caja')
    request.session['shift_id'] = turno.shift_id
    return render(request, 'pos.html', {'nombre_usuario': request.session.get('user_name'), 'turno_id': turno.shift_id})

def imprimir_ticket_view(request, sale_id):
    if 'user_id' not in request.session: 
        return HttpResponse('No autorizado', status=401)
    
    # Obtenemos la venta y sus detalles
    sale = get_object_or_404(Sale.objects.select_related('user'), sale_id=sale_id)
    detalles = SaleDetail.objects.filter(sale=sale).select_related('product')
    
    # Formateo de fecha seguro
    if timezone.is_aware(sale.created_at):
        fecha_str = timezone.localtime(sale.created_at).strftime('%d/%m/%Y %H:%M')
    else:
        fecha_str = sale.created_at.strftime('%d/%m/%Y %H:%M')
        
    context = {
        'sale': sale,
        'detalles': detalles,
        'fecha': fecha_str
    }
    
    # Renderizamos la plantilla de ticket que creamos
    return render(request, 'ticket_impresion.html', context)

def view_admin_proveedores(request):
    if 'user_id' not in request.session: return redirect('login')
    if request.session.get('user_role') != 'ADMIN': return redirect('punto_venta')
    
    query = request.GET.get('q', '').strip()
    page_number = request.GET.get('page', 1)
    
    qs = Supplier.objects.all().order_by('-is_active', 'company_name')
    if query:
        qs = qs.filter(Q(company_name__icontains=query) | Q(contact_name__icontains=query))
        
    page_obj = Paginator(qs, 50).get_page(page_number)
    
    return render(request, 'admin_proveedores.html', {
        'nombre_usuario': request.session.get('user_name'),
        'page_obj': page_obj, 
        'q': query
    })

def view_admin_marcas(request):
    if 'user_id' not in request.session: return redirect('login')
    if request.session.get('user_role') != 'ADMIN': return redirect('punto_venta')
    
    query = request.GET.get('q', '').strip()
    page_number = request.GET.get('page', 1)
    
    qs = Brand.objects.all().order_by('-is_active', 'name')
    if query:
        qs = qs.filter(name__icontains=query)
        
    page_obj = Paginator(qs, 50).get_page(page_number)
    
    return render(request, 'admin_marcas.html', {
        'nombre_usuario': request.session.get('user_name'),
        'page_obj': page_obj, 
        'q': query
    })

def view_admin_categorias(request):
    if 'user_id' not in request.session: return redirect('login')
    if request.session.get('user_role') != 'ADMIN': return redirect('punto_venta')
    
    query = request.GET.get('q', '').strip()
    page_number = request.GET.get('page', 1)
    
    qs = Category.objects.select_related('parent').all().order_by('-is_active', 'name')
    if query:
        qs = qs.filter(name__icontains=query)
        
    page_obj = Paginator(qs, 50).get_page(page_number)
    
    return render(request, 'admin_categorias.html', {
        'nombre_usuario': request.session.get('user_name'),
        'page_obj': page_obj, 
        'q': query,
        'categorias_padre': Category.objects.filter(is_active=True, parent__isnull=True).order_by('name')
    })

def view_admin_ventas(request):
    if 'user_id' not in request.session: return redirect('login')
    if request.session.get('user_role') != 'ADMIN': return redirect('punto_venta')
    
    return render(request, 'admin_ventas.html', {
        'nombre_usuario': request.session.get('user_name')
    })

def perfil_view(request):
    if 'user_id' not in request.session: return redirect('login')
    usuario = UsuarioPersonalizado.objects.get(user_id=request.session['user_id'])
    if request.method == 'POST':
        form = PerfilForm(request.POST, request.FILES, instance=usuario)
        if form.is_valid():
            form.save()
            request.session['user_name'] = usuario.full_name
            if usuario.photo: request.session['user_photo'] = usuario.photo.url
            messages.success(request, 'Perfil actualizado')
            return redirect('perfil')
    else:
        form = PerfilForm(instance=usuario)
    return render(request, 'perfil.html', {'form': form, 'usuario': usuario})

def apertura_caja_view(request):
    if 'user_id' not in request.session: return redirect('login')
    if request.method == 'POST':
        monto_inicial = request.POST.get('monto_inicial', 0)
        caja = CashRegister.objects.first() 
        if not caja: caja = CashRegister.objects.create(name="Caja Principal")
        turno = abrir_turno(user_id=request.session['user_id'], register_id=caja.register_id, initial_cash=float(monto_inicial))
        request.session['shift_id'] = turno.shift_id
        return redirect('punto_venta')
    return render(request, 'abrir_caja.html')

def cierre_caja_view(request):
    if 'user_id' not in request.session: return redirect('login')
    turno = obtener_turno_activo(request.session['user_id'])
    if request.method == 'POST' and turno:
        cerrar_turno(turno, final_cash_counted=float(request.POST.get('dinero_fisico', 0)))
        if 'shift_id' in request.session: del request.session['shift_id']
        messages.success(request, 'Corte de caja realizado correctamente.')
        return redirect('dashboard_admin')
    return redirect('punto_venta')

def inventario_view(request):
    if 'user_id' not in request.session: return redirect('login')
    
    # 1. Leer parámetros de la URL
    query = request.GET.get('q', '').strip()
    brand = request.GET.get('brand', '')
    stock_filter = request.GET.get('filter', 'all')
    page_number = request.GET.get('page', 1)

    # 2. Consulta Base (Rápida y excluyendo servicios)
    inventario_qs = InventoryStock.objects.select_related('product', 'product__brand').filter(
        product__is_active=True,
        product__is_service=False
    ).order_by('product__name')

    # 3. Aplicar Filtros en BD
    if query:
        inventario_qs = inventario_qs.filter(
            Q(product__name__icontains=query) | Q(product__barcode__icontains=query)
        )
    if brand:
        inventario_qs = inventario_qs.filter(product__brand__name=brand)
    if stock_filter == 'low':
        inventario_qs = inventario_qs.filter(quantity__lte=F('product__min_stock_alert'))

    # 4. Paginación (50 elementos por página)
    paginator = Paginator(inventario_qs, 50)
    page_obj = paginator.get_page(page_number)

    return render(request, 'inventario.html', { 
        'nombre_usuario': request.session.get('user_name'), 
        'page_obj': page_obj,  # Pasamos la página en vez de todo el inventario
        'brands': Brand.objects.all().order_by('name'),
        'q': query,
        'brand_selected': brand,
        'filter_selected': stock_filter,
    })

def menu_administracion(request):
    if 'user_id' not in request.session: return redirect('login')
    if request.session.get('user_role') != 'ADMIN':
        messages.error(request, "Acceso no autorizado.")
        return redirect('punto_venta')
    return render(request, 'menu_admin.html', {'nombre_usuario': request.session.get('user_name')})

def view_admin_productos(request):
    if 'user_id' not in request.session: return redirect('login')
    if request.session.get('user_role') != 'ADMIN': return redirect('punto_venta')
    
    query = request.GET.get('q', '').strip()
    cat_id = request.GET.get('category', '')
    hide_services = request.GET.get('hide_services', 'true') == 'true'
    page_number = request.GET.get('page', 1)
    
    qs = Product.objects.select_related('brand').all().order_by('-is_active', 'name')
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(barcode__icontains=query))
    if cat_id:
        qs = qs.filter(category_id=cat_id)
    if hide_services:
        qs = qs.filter(is_service=False)
        
    page_obj = Paginator(qs, 50).get_page(page_number)
    
    return render(request, 'admin_productos.html', {
        'nombre_usuario': request.session.get('user_name'),
        'page_obj': page_obj, 
        'q': query, 
        'category_selected': cat_id, 
        'hide_services': hide_services,
        'categorias': Category.objects.all(),
        'marcas': Brand.objects.all(),
        'unidades': UnitOfMeasure.objects.all()
    })

def view_admin_promociones(request):
    if 'user_id' not in request.session: return redirect('login')
    if request.session.get('user_role') != 'ADMIN': return redirect('punto_venta')
    return render(request, 'admin_promociones.html', {
        'nombre_usuario': request.session.get('user_name'),
        'promociones': Promotion.objects.select_related('product', 'product__brand').all().order_by('-is_active', 'product__name')
    })

def view_libreta_precios(request):
    if 'user_id' not in request.session: return redirect('login')
    return render(request, 'libreta_precios.html', {
        'nombre_usuario': request.session.get('user_name'),
        'proveedores': Supplier.objects.all().order_by('company_name')
    })

def view_reporte_finanzas(request):
    if 'user_id' not in request.session: return redirect('login')
    return render(request, 'reportes/ventas_finanzas.html', {
        'nombre_usuario': request.session.get('user_name'),
        'fecha_fin': timezone.localtime(timezone.now()).strftime('%Y-%m-%d'),
        'fecha_inicio': (timezone.localtime(timezone.now()) - timedelta(days=30)).strftime('%Y-%m-%d')
    })

# ==========================================
# REPORTES Y PDF
# ==========================================

def generar_reporte_compras_pdf(request):
    if 'user_id' not in request.session: return redirect('login')

    query = request.GET.get('q', '')
    brand_filter = request.GET.get('brand', '')
    
    # --- LA MAGIA ESTÁ AQUÍ: Agregamos is_service=False ---
    products = Product.objects.filter(is_active=True, is_service=False).select_related('inventorystock', 'brand', 'uom')
    
    if query: products = products.filter(Q(name__icontains=query) | Q(barcode__icontains=query))
    if brand_filter: products = products.filter(brand__name=brand_filter)
    products = products.filter(inventorystock__quantity__lte=F('min_stock_alert'))

    product_ids = list(products.values_list('product_id', flat=True))
    suppliers_map = {}
    if product_ids:
        ids_tuple = tuple(product_ids)
        ids_sql = f"({ids_tuple[0]})" if len(ids_tuple) == 1 else str(ids_tuple)
        sql = f"SELECT ps.product_id, s.company_name FROM product_suppliers ps JOIN suppliers s ON ps.supplier_id = s.supplier_id WHERE ps.product_id IN {ids_sql}"
        with connection.cursor() as cursor:
            cursor.execute(sql)
            for pid, company in cursor.fetchall():
                if pid not in suppliers_map: suppliers_map[pid] = []
                suppliers_map[pid].append(company)

    items_reporte = []
    for p in products:
        stock_actual = p.inventorystock.quantity if hasattr(p, 'inventorystock') else 0
        deficit = p.min_stock_alert - stock_actual
        lista_provs = suppliers_map.get(p.product_id, [])
        items_reporte.append({
            'producto': p.name, 'marca': p.brand.name if p.brand else 'Genérico', 'barcode': p.barcode,
            'stock': stock_actual, 'minimo': p.min_stock_alert, 'faltante': deficit if deficit > 0 else 0,
            'ultimo_costo': p.cost_price, 'proveedores': ", ".join(lista_provs) if lista_provs else "Sin asignar"
        })

    html_string = render_to_string('reportes/lista_compras.html', {
        'items': items_reporte, 'fecha': timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
        'filtro_marca': brand_filter if brand_filter else "Todas", 'usuario': request.session.get('user_name')
    }, request=request)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="lista_compras.pdf"'
    weasyprint.HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf(response)
    return response

def generar_pdf_financiero(request):
    if 'user_id' not in request.session: return redirect('login')

    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    
    if not start_date or not end_date:
        hoy = timezone.localtime(timezone.now())
        fecha_inicio = hoy.replace(day=1, hour=0, minute=0, second=0)
        fecha_fin = hoy
    else:
        fecha_inicio = datetime.strptime(start_date, '%Y-%m-%d')
        fecha_fin = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)

    ventas = Sale.objects.filter(created_at__range=(fecha_inicio, fecha_fin), status='COMPLETED')
    total_ventas = sum(float(v.total) for v in ventas)

    detalles = SaleDetail.objects.filter(sale__created_at__range=(fecha_inicio, fecha_fin), sale__status='COMPLETED').select_related('product')
    costo_ventas = sum(float(d.unit_cost * d.quantity) for d in detalles)
    monto_precio_lista = sum(float(d.subtotal) for d in detalles)

    tomas = InternalWithdrawal.objects.filter(created_at__range=(fecha_inicio, fecha_fin), status='APPROVED').select_related('product')
    costo_gastos = sum(float(t.unit_cost * t.quantity) for t in tomas)

    descuento_promos = max(0, monto_precio_lista - total_ventas)
    utilidad_bruta = total_ventas - costo_ventas
    utilidad_neta = utilidad_bruta - costo_gastos
    margen = (utilidad_neta / total_ventas * 100) if total_ventas > 0 else 0

    dias_reporte = {}
    def obtener_fecha_segura(dt):
        return timezone.localtime(dt).strftime('%Y-%m-%d') if timezone.is_aware(dt) else dt.strftime('%Y-%m-%d')

    for v in ventas:
        fecha_str = obtener_fecha_segura(v.created_at)
        if fecha_str not in dias_reporte: dias_reporte[fecha_str] = {'fecha': fecha_str, 'venta': 0.0, 'costo': 0.0, 'gastos': 0.0, 'tickets': 0}
        dias_reporte[fecha_str]['venta'] += float(v.total)
        dias_reporte[fecha_str]['tickets'] += 1

    for d in detalles:
        fecha_str = obtener_fecha_segura(d.sale.created_at)
        if fecha_str in dias_reporte: dias_reporte[fecha_str]['costo'] += float(d.unit_cost * d.quantity)

    for t in tomas:
        fecha_str = obtener_fecha_segura(t.created_at)
        if fecha_str not in dias_reporte: dias_reporte[fecha_str] = {'fecha': fecha_str, 'venta': 0.0, 'costo': 0.0, 'gastos': 0.0, 'tickets': 0}
        dias_reporte[fecha_str]['gastos'] += float(t.unit_cost * t.quantity)

    lista_dias = []
    for key, datos in dias_reporte.items():
        datos['utilidad_bruta'] = datos['venta'] - datos['costo']
        datos['utilidad_neta'] = datos['utilidad_bruta'] - datos['gastos']
        lista_dias.append(datos)
    lista_dias.sort(key=lambda x: x['fecha'])

    html_string = render_to_string('reportes/finanzas_pdf.html', {
        'rango': f"{fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}",
        'usuario': request.session.get('user_name'),
        'fecha_impresion': timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
        'ventas_netas': total_ventas, 'descuento_promos': descuento_promos, 'costo_ventas': costo_ventas,
        'utilidad_bruta': utilidad_bruta, 'gastos_op': costo_gastos, 'utilidad_neta': utilidad_neta,
        'margen': margen, 'tabla_diaria': lista_dias
    }, request=request)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Reporte_Financiero_{fecha_inicio.strftime("%Y%m%d")}.pdf"'
    weasyprint.HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf(response)
    return response

def admin_auditoria_view(request):
    if 'user_id' not in request.session: return redirect('login')
    return render(request, 'admin_auditoria.html')

def admin_historial_precios_view(request):
    if 'user_id' not in request.session: 
        return redirect('login')
    return render(request, 'admin_historial_precios.html')

def admin_movimientos_stock_view(request):
    if 'user_id' not in request.session: 
        return redirect('login')
    return render(request, 'admin_movimientos_stock.html')

def admin_roles_view(request):
    if 'user_id' not in request.session: 
        return redirect('login')
    return render(request, 'admin_roles.html')

def admin_turnos_view(request):
    if 'user_id' not in request.session: 
        return redirect('login')
    return render(request, 'admin_turnos.html')

def admin_usuarios_view(request):
    if 'user_id' not in request.session: 
        return redirect('login')
    return render(request, 'admin_usuarios.html')

def admin_conteo_view(request):
    if 'user_id' not in request.session: 
        return redirect('login')
    # Mandamos las categorías para el select
    categorias = Category.objects.filter(is_active=True).order_by('name')
    return render(request, 'admin_conteo.html', {'categorias': categorias})