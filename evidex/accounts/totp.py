"""Verificación en dos pasos: códigos de 6 dígitos que cambian cada 30 segundos (TOTP, RFC 6238).

Funciona con Google Authenticator, Microsoft Authenticator, Authy y similares. El secreto se crea en el
servidor, se muestra una sola vez como código QR y queda guardado junto al usuario. Un código ya usado no
se acepta de nuevo (para que nadie lo reutilice si lo ve).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, step: int) -> str:
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return str(n).zfill(DIGITS)


def now_step(t: float | None = None) -> int:
    return int((time.time() if t is None else t) // STEP)


def verify(secret: str, code: str, last_step: int | None = None, window: int = 1, t: float | None = None) -> int | None:
    """Devuelve el paso de tiempo aceptado (para no aceptarlo de nuevo) o None si el código no sirve.
    Acepta un paso antes y uno después, por si el reloj del teléfono está algo corrido."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    now = now_step(t)
    for step in range(now - window, now + window + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def uri(secret: str, username: str, issuer: str = "Evidex") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def qr_svg(text: str) -> str:
    """Código QR en SVG (sin imágenes externas). Vacío si la librería qrcode no está instalada."""
    try:
        import io
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode()
    except Exception:
        return ""
