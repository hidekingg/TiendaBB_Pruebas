# ventas/urls.py
from django.urls import path
from . import views
from . import apis  # <--- IMPORTAMOS EL NUEVO ARCHIVO DE APIS
from . import cotizador_views

urlpatterns = [
    # Login y Logout
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Dashboard y Perfil
    path('dashboard/', views.dashboard_admin, name='dashboard_admin'),
    path('perfil/', views.perfil_view, name='perfil'),
    
    # Punto de Venta e Inventario
    path('pos/', views.punto_venta, name='punto_venta'), 
    path('pos/abrir/', views.apertura_caja_view, name='abrir_caja'),
    path('pos/cerrar/', views.cierre_caja_view, name='cerrar_caja'),
    path('inventario/', views.inventario_view, name='inventario'),
    
    # Reportes (Vistas y PDF)
    path('reportes/compras/', views.generar_reporte_compras_pdf, name='reporte_compras_pdf'),
    path('reportes/finanzas/', views.view_reporte_finanzas, name='reporte_finanzas'),
    path('reportes/finanzas/pdf/', views.generar_pdf_financiero, name='pdf_finanzas'),

    # Administración
    path('administracion/', views.menu_administracion, name='menu_administracion'),
    path('administracion/productos/', views.view_admin_productos, name='admin_productos'),
    path('administracion/promociones/', views.view_admin_promociones, name='admin_promociones'),
    path('compras/libreta/', views.view_libreta_precios, name='libreta_precios'),
    path('administracion/proveedores/', views.view_admin_proveedores, name='admin_proveedores'),
    path('administracion/marcas/', views.view_admin_marcas, name='admin_marcas'),
    path('administracion/categorias/', views.view_admin_categorias, name='admin_categorias'),
    path('administracion/ventas/', views.view_admin_ventas, name='admin_ventas'),
    path('ticket/<int:sale_id>/', views.imprimir_ticket_view, name='imprimir_ticket'),
    path('administracion/auditoria/', views.admin_auditoria_view, name='admin_auditoria'),
    path('administracion/precios-historicos/', views.admin_historial_precios_view, name='admin_historial_precios'),
    path('administracion/movimientos-stock/', views.admin_movimientos_stock_view, name='admin_movimientos_stock'),
    path('administracion/roles/', views.admin_roles_view, name='admin_roles'),
    path('administracion/turnos/', views.admin_turnos_view, name='admin_turnos'),
    path('administracion/usuarios/', views.admin_usuarios_view, name='admin_usuarios'),
    path('administracion/conteo-fisico/', views.admin_conteo_view, name='admin_conteo'),

    # ==========================================
    # APIS (AQUÍ USAMOS 'apis.' EN LUGAR DE 'views.')
    # ==========================================
    path('api/products/search/', apis.api_search_products, name='api_search_products'),
    path('api/sale/process/', apis.api_process_sale, name='api_process_sale'),
    path('api/dashboard/stats/', apis.api_dashboard_stats, name='api_dashboard_stats'),
    path('api/inventory/add/', apis.api_add_stock, name='api_add_stock'),
    path('api/inventory/adjust/', apis.api_adjust_stock, name='api_adjust_stock'),
    path('api/products/top/', apis.api_top_selling_products, name='api_top_selling_products'),
    path('api/products/<int:product_id>/suppliers/', apis.api_get_product_suppliers, name='api_get_product_suppliers'),
    path('api/reportes/data/', apis.api_datos_finanzas, name='api_datos_finanzas'),
    path('api/admin/productos/accion/', apis.api_producto_accion, name='api_producto_accion'),
    path('api/admin/promociones/accion/', apis.api_promocion_accion, name='api_promocion_accion'),
    path('api/compras/libreta/buscar/', apis.api_libreta_buscar, name='api_libreta_buscar'),
    path('api/compras/libreta/actualizar/', apis.api_libreta_actualizar, name='api_libreta_actualizar'),
    path('api/admin/proveedores/accion/', apis.api_proveedor_accion, name='api_proveedor_accion'),
    path('api/admin/marcas/accion/', apis.api_marca_accion, name='api_marca_accion'),
    path('api/admin/categorias/accion/', apis.api_categoria_accion, name='api_categoria_accion'),
    path('api/admin/ventas/lista/', apis.api_get_sales, name='api_get_sales'),
    path('api/admin/ventas/<int:sale_id>/', apis.api_get_sale_details, name='api_get_sale_details'),
    path('api/admin/ventas/cancelar/', apis.api_cancel_sale, name='api_cancel_sale'),
    path('api/services/list/', apis.api_get_services, name='api_get_services'),
    path('api/admin/auditoria/logs/', apis.api_get_audit_logs, name='api_audit_logs'),
    path('api/admin/usuarios/lista/', apis.api_get_users_list, name='api_users_list'),
    path('api/admin/precios-historicos/lista/', apis.api_get_price_history, name='api_price_history'),
    path('api/admin/movimientos-stock/lista/', apis.api_get_stock_movements, name='api_stock_movements'),
    path('api/admin/roles/lista/', apis.api_get_roles, name='api_roles_list'),
    path('api/admin/roles/accion/', apis.api_role_accion, name='api_role_accion'),
    path('api/admin/turnos/lista/', apis.api_get_shifts, name='api_shifts_list'),
    path('api/admin/usuarios/lista_completa/', apis.api_get_usuarios, name='api_usuarios_lista_completa'),
    path('api/admin/usuarios/accion/', apis.api_usuario_accion, name='api_usuario_accion'),
    path('api/conteo/productos/', apis.api_conteo_productos, name='api_conteo_productos'),
    path('api/conteo/procesar/', apis.api_conteo_procesar, name='api_conteo_procesar'),
    path('api/conteo/historial/', apis.api_conteo_historial, name='api_conteo_historial'),
    path('api/pos/devolver-envase/', apis.api_devolver_envase, name='api_devolver_envase'),
    path('api/admin/ventas/cancelar-item/', apis.api_cancel_sale_item, name='api_cancel_sale_item'),
    path('api/reportes/gastos/', apis.api_reporte_gastos, name='api_reporte_gastos'),
    path('api/reportes/zombies/', apis.api_reporte_zombies, name='api_reporte_zombies'),
    path('api/reportes/proveedores/', apis.api_reporte_proveedores, name='api_reporte_proveedores'),
    path('api/reportes/horas/', apis.api_reporte_horas, name='api_reporte_horas'),

    #----------------------------
    path('herramientas/cotizador/', cotizador_views.view_cotizador, name='cotizador_impresiones'),
    path('api/cotizador/analizar/', cotizador_views.api_analyze_file, name='api_analyze_file'),
]