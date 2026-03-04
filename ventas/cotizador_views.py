# ventas/cotizador_views.py
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .cotizador_services import analyze_ink_coverage

def view_cotizador(request):
    """Renderiza la página del cotizador inteligente"""
    if 'user_id' not in request.session: 
        return redirect('login')
    return render(request, 'cotizador.html')

@csrf_exempt
def api_analyze_file(request):
    """Recibe el archivo por AJAX y devuelve los porcentajes de tinta"""
    if 'user_id' not in request.session: 
        return JsonResponse({'error': '401'}, status=401)
        
    if request.method == 'POST' and request.FILES.get('file'):
        file_obj = request.FILES['file']
        
        # Validar tipo de archivo
        valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
        if not any(file_obj.name.lower().endswith(ext) for ext in valid_extensions):
            return JsonResponse({'status': 'error', 'message': 'Solo se permiten archivos PDF, JPG o PNG.'})
            
        try:
            file_bytes = file_obj.read()
            coverages = analyze_ink_coverage(file_bytes, file_obj.name)
            return JsonResponse({'status': 'success', 'pages': coverages})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Error procesando archivo: {str(e)}'})
            
    return JsonResponse({'status': 'error', 'message': 'No se recibió ningún archivo.'})