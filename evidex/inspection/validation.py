"""Bounded structural validation, run inside the analysis subprocess."""
import warnings
from pathlib import Path
from PIL import Image

MAX_BYTES = 25_000_000
MAX_PIXELS = 40_000_000
MAX_PAGES = 20
MAX_MPO_FRAMES = 8          # foto principal + mapas HDR / profundidad
FORMATS = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP',
           '.heic': 'HEIF', '.heif': 'HEIF', '.pdf': 'PDF'}

class InvalidFile(ValueError):
    pass


def validate(path, name, max_pages=MAX_PAGES, formats=None):
    path = Path(path)
    ext = Path(name).suffix.lower()
    expected = (formats or FORMATS).get(ext)
    if not expected:
        raise InvalidFile('Formato no soportado. Use JPG, PNG, WebP, HEIC/HEIF o PDF.')
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise InvalidFile('Archivo vacío o mayor a 25 MB.')
    if expected == 'PDF':
        import pdfplumber
        try:
            with pdfplumber.open(path) as pdf:
                if getattr(pdf.doc, 'encryption', None):
                    raise InvalidFile('PDF cifrado: envíe una copia sin contraseña.')
                count = len(pdf.pages)
                if not 0 < count <= max_pages:
                    raise InvalidFile(f'El PDF debe tener entre 1 y {max_pages} páginas.')
                for page in pdf.pages:
                    if not (0 < float(page.width) <= 14400 and 0 < float(page.height) <= 14400):
                        raise InvalidFile('Dimensiones de página no soportadas.')
                    # Rendering at 144dpi must also fit the pixel budget.
                    if page.width * page.height * 4 > MAX_PIXELS:
                        raise InvalidFile('Página demasiado grande para analizar con seguridad.')
                return {'kind': 'pdf', 'pages': count, 'format': 'PDF'}
        except InvalidFile:
            raise
        except Exception as ex:
            raise InvalidFile('PDF inválido, cifrado o no legible.') from ex
    try:
        if expected == 'HEIF':
            from pillow_heif import register_heif_opener
            register_heif_opener()
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as im:
                # Las fotos HDR de iPhone y de muchos Android son JPEG con imágenes extra incrustadas (mapa de
                # ganancia, profundidad): Pillow las abre como MPO. Son fotos normales de cámara, no se rechazan.
                fmt = 'JPEG' if im.format == 'MPO' and expected == 'JPEG' else im.format
                frames = getattr(im, 'n_frames', 1)
                if (fmt != expected or im.width * im.height > MAX_PIXELS
                        or frames > (MAX_MPO_FRAMES if im.format == 'MPO' else 1)):
                    raise InvalidFile('Formato, dimensiones o número de imágenes no soportados.')
                info = {'kind': 'image', 'format': fmt, 'width': im.width, 'height': im.height}
                im.verify()
            with Image.open(path) as im:
                im.load()
            return info
    except InvalidFile:
        raise
    except ImportError as ex:
        raise InvalidFile('Soporte HEIC no instalado; envíe JPG/PNG o instale pillow-heif.') from ex
    except Exception as ex:
        raise InvalidFile('Imagen inválida, dañada o demasiado grande.') from ex
