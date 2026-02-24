# ventas/forms.py
from django import forms
from .models import UsuarioPersonalizado

class PerfilForm(forms.ModelForm):
    class Meta:
        model = UsuarioPersonalizado
        fields = ['full_name', 'photo'] # Permitimos editar nombre y foto
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-[#ff4f4f] focus:ring-[#ff4f4f] sm:text-sm'
            }),
            'photo': forms.FileInput(attrs={
                'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-[#3e1717] file:text-white hover:file:bg-[#2a1010]'
            }),
        }