"""Revisión de archivos subidos, en un proceso aparte con tiempo y memoria limitados.

Todas las cargas de Evidex (evidencia del caso, portal del asegurado, documentos de investigación,
informe del perito, importación de historial) pasan por aquí antes de guardarse:

  - la extensión tiene que estar permitida para esa carga;
  - el contenido tiene que ser de verdad lo que dice la extensión (una foto que se abre, un PDF sano y
    sin contraseña, un ZIP sin rutas raras ni "bomba" de compresión, un texto legible);
  - tamaño, páginas y píxeles dentro de límites.

La revisión abre el archivo con los mismos lectores que después usa el análisis, por eso corre en un
proceso desechable: si un archivo malicioso cuelga o revienta el lector, se rechaza el archivo y la web
sigue funcionando para todos.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from evidex.inspection.validation import FORMATS, InvalidFile, validate

IMAGES = {**{k: v for k, v in FORMATS.items() if k != ".pdf"}, ".tif": "TIFF", ".tiff": "TIFF"}
PDF = {".pdf": "PDF"}
CHAT = {".txt", ".zip"}
TABLE = {".csv", ".xlsx", ".xlsm"}

# qué se acepta en cada carga
PURPOSES = {
    "evidencia": set(IMAGES) | set(PDF) | CHAT,     # fotos, documentos y chats de WhatsApp del caso
    "portal": set(IMAGES) | set(PDF),               # lo que sube el asegurado
    "documento": set(IMAGES) | set(PDF),            # documentos de una investigación
    "informe": set(PDF),                            # informe del perito para auditar
    "historial": TABLE,                             # importación de siniestros anteriores
}
DOC_MAX_PAGES = 100            # un expediente o informe de perito puede ser largo
MAX_TEXT = 5_000_000
MAX_TABLE = 10_000_000
MAX_ZIP = 25_000_000
ZIP_MAX_ENTRIES = 300
ZIP_MAX_TOTAL = 100_000_000    # tamaño descomprimido total
ZIP_MAX_RATIO = 100            # más que eso es una "bomba" de compresión
TIMEOUT = 30


def _zip(path: Path, needs: tuple[str, ...] = ()) -> None:
    if path.stat().st_size > MAX_ZIP:
        raise InvalidFile("Archivo comprimido mayor a 25 MB.")
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if not infos or len(infos) > ZIP_MAX_ENTRIES:
                raise InvalidFile("El archivo comprimido está vacío o tiene demasiados archivos.")
            total = 0
            for i in infos:
                name = i.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/") or ":" in name.split("/")[0]:
                    raise InvalidFile("El archivo comprimido tiene rutas no permitidas.")
                if i.flag_bits & 0x1:
                    raise InvalidFile("El archivo comprimido tiene contraseña.")
                total += i.file_size
                if i.compress_size and i.file_size / i.compress_size > ZIP_MAX_RATIO and i.file_size > 1_000_000:
                    raise InvalidFile("El archivo comprimido tiene una compresión anómala.")
            if total > ZIP_MAX_TOTAL:
                raise InvalidFile("El archivo comprimido es demasiado grande al descomprimirlo.")
            names = {i.filename for i in infos}
            for n in needs:
                if n not in names:
                    raise InvalidFile("El archivo no tiene el formato esperado.")
            if z.testzip() is not None:
                raise InvalidFile("El archivo comprimido está dañado.")
    except zipfile.BadZipFile as ex:
        raise InvalidFile("El archivo comprimido está dañado o no es un ZIP.") from ex


def _text(path: Path, limit: int) -> None:
    if path.stat().st_size > limit:
        raise InvalidFile("Archivo de texto demasiado grande.")
    raw = path.read_bytes()
    if b"\x00" in raw[:65536]:
        raise InvalidFile("El archivo no es texto.")
    for enc in ("utf-8-sig", "latin-1"):
        try:
            raw.decode(enc)
            return
        except UnicodeDecodeError:
            continue
    raise InvalidFile("El archivo de texto no se puede leer.")


def inspect(path, name: str, purpose: str) -> dict:
    """Revisa el archivo en este mismo proceso. Usar `check`, que lo hace en un proceso aparte."""
    path = Path(path)
    ext = Path(name).suffix.lower()
    if purpose not in PURPOSES:
        raise ValueError(f"carga desconocida: {purpose}")
    if ext not in PURPOSES[purpose]:
        raise InvalidFile("Tipo de archivo no permitido aquí.")
    if not path.is_file() or path.stat().st_size == 0:
        raise InvalidFile("El archivo está vacío.")
    if ext in IMAGES:
        return validate(path, name, formats=IMAGES)
    if ext in PDF:
        return validate(path, name, max_pages=DOC_MAX_PAGES)
    if ext == ".txt":
        _text(path, MAX_TEXT)
        return {"kind": "text"}
    if ext == ".zip":
        _zip(path)
        return {"kind": "zip"}
    if ext == ".csv":
        _text(path, MAX_TABLE)
        return {"kind": "table"}
    if ext in (".xlsx", ".xlsm"):
        if path.stat().st_size > MAX_TABLE:
            raise InvalidFile("Planilla mayor a 10 MB.")
        _zip(path, needs=("[Content_Types].xml",))
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            wb.close()
        except Exception as ex:
            raise InvalidFile("La planilla está dañada o no es un Excel válido.") from ex
        return {"kind": "table"}
    raise InvalidFile("Tipo de archivo no permitido aquí.")


def check(path, name: str, purpose: str, timeout: int = TIMEOUT) -> dict:
    """Revisa el archivo en un proceso desechable. Devuelve datos del archivo o lanza InvalidFile."""
    ext = Path(name).suffix.lower()
    if purpose in PURPOSES and ext not in PURPOSES[purpose]:      # rechazo rápido, sin abrir nada
        raise InvalidFile("Tipo de archivo no permitido aquí.")
    payload = json.dumps({"path": str(Path(path).resolve()), "name": name, "purpose": purpose})
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    try:
        proc = subprocess.run([sys.executable, "-m", "evidex.core.upload_guard"], input=payload, text=True,
                              capture_output=True, timeout=timeout, env=env,
                              cwd=Path(__file__).resolve().parents[2])
    except subprocess.TimeoutExpired as ex:
        raise InvalidFile("El archivo tardó demasiado en revisarse y se rechazó por seguridad.") from ex
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as ex:
        raise InvalidFile("El archivo no se pudo revisar y se rechazó por seguridad.") from ex
    if not out.get("ok"):
        raise InvalidFile(out.get("error") or "Archivo rechazado.")
    return out["info"]


def _limits() -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT, TIMEOUT + 2))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))          # revisar no escribe nada
    except (ImportError, ValueError, OSError):
        pass                                                       # Windows: rige el tiempo máximo del padre

    def offline(event, args):
        if event in ("socket.connect", "socket.getaddrinfo"):
            raise PermissionError("sin red al revisar archivos")
    sys.addaudithook(offline)


def main() -> None:
    payload = json.loads(sys.stdin.read())
    _limits()
    try:
        info = inspect(payload["path"], payload["name"], payload["purpose"])
        out = {"ok": True, "info": info}
    except InvalidFile as ex:
        out = {"ok": False, "error": str(ex)}
    except Exception as ex:                                       # cualquier otra falla = rechazo
        out = {"ok": False, "error": f"El archivo no se pudo revisar ({type(ex).__name__})."}
    sys.stdout.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
