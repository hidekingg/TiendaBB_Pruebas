from django.contrib import admin
from django.urls import path, include  # <--- Asegúrate de importar include
from django.conf import settings               # <--- ¡AGREGA ESTA!
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('ventas.urls')),  # <--- Redirige todo el tráfico a la app 'ventas'
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)