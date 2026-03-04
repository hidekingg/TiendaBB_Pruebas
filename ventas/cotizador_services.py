# ventas/cotizador_services.py
import fitz  # PyMuPDF
from PIL import Image, ImageChops, ImageStat
import io

def analyze_ink_coverage(file_bytes, filename):
    """
    Calcula la cobertura CMYK real utilizando extracción de negros (UCR)
    para un cálculo de costos hiper-preciso.
    """
    images = []
    
    # 1. Extraer imágenes
    if filename.lower().endswith('.pdf'):
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # colorspace=fitz.csRGB fuerza a que lo lea a todo color
            pix = page.get_pixmap(dpi=72, colorspace=fitz.csRGB)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            images.append(img)
    else:
        images.append(Image.open(io.BytesIO(file_bytes)))

    results = []
    for i, img in enumerate(images):
        
        # 2. Manejar transparencias (PNGs sin fondo)
        # Si tiene partes transparentes, le ponemos un fondo blanco (papel) para que no las cuente como negro.
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            img = img.convert('RGBA')
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert('RGB')
        
        # 3. Separar Canales RGB
        r, g, b = img.split()
        
        # 4. Fórmula CMYK Real (Under Color Removal)
        # Paso A: Convertir RGB a CMY crudo (Invertir los colores)
        c_prime = ImageChops.invert(r)
        m_prime = ImageChops.invert(g)
        y_prime = ImageChops.invert(b)
        
        # Paso B: Extraer el Negro (K) -> Es la intersección (lo más oscuro) de los 3 colores
        k = ImageChops.darker(ImageChops.darker(c_prime, m_prime), y_prime)
        
        # Paso C: Restar el negro a los colores para no doble-gastar tinta
        c = ImageChops.subtract(c_prime, k)
        m = ImageChops.subtract(m_prime, k)
        y = ImageChops.subtract(y_prime, k)
        
        # 5. Calcular Coberturas usando ImageStat (Matemáticas en C, extremadamente rápido)
        total_pixels = img.width * img.height
        max_intensity = 255.0 * total_pixels
        
        c_cov = (ImageStat.Stat(c).sum[0] / max_intensity) * 100
        m_cov = (ImageStat.Stat(m).sum[0] / max_intensity) * 100
        y_cov = (ImageStat.Stat(y).sum[0] / max_intensity) * 100
        k_cov = (ImageStat.Stat(k).sum[0] / max_intensity) * 100
        
        results.append({
            'page': i + 1,
            'c': round(c_cov, 2),
            'm': round(m_cov, 2),
            'y': round(y_cov, 2),
            'k': round(k_cov, 2)
        })
    
    return results