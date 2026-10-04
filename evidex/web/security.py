"""Session, CSRF and response protections shared by every route."""
import secrets
import threading as _threading
import time as _time
from collections import defaultdict as _defaultdict, deque as _deque
from flask import abort, current_app, g, request, session


def demo_open():
    from evidex.web.common import cx
    return bool(current_app.config['DEMO_MODE'] and not cx.store.all() and not cx.store.marker.exists())


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def protect_mutations():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    origin = request.headers.get('Origin')
    if origin and origin != request.host_url.rstrip('/'):
        abort(403, 'Origen no permitido.')
    if current_app.config['CSRF_ENABLED']:
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
        expected = session.get('csrf')
        if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
            abort(400, 'La sesión del formulario venció. Recargue la página e intente nuevamente.')


def start_session(user):
    from evidex.web.common import cx
    cx.store.state.revoke(session.get('sid'))
    session.clear()
    session['user'] = user['username']
    session['sid'] = cx.store.state.issue(user)
    session.permanent = True
    csrf_token()


def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # SAMEORIGIN: la pestaña Informe muestra el informe del caso en un marco de la misma página;
    # ningún otro sitio puede enmarcar Evidex
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    # 'same-origin' y no 'no-referrer': con 'no-referrer' el navegador envía 'Origin: null' en los formularios
    # (POST) y la revisión de origen rechaza hasta el inicio de sesión. Así no se filtra la dirección a otros sitios.
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'nonce-" + g.csp_nonce + "'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'self'; form-action 'self'; connect-src 'self'"
    )
    if current_app.config['PRODUCTION']:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


# ---- portal del asegurado: límite de solicitudes por dirección ----------------------------------
# El portal es lo único de Evidex abierto a internet. Su enlace secreto no se puede adivinar, pero
# sin límite alguien podría probar enlaces sin parar o saturar el servidor subiendo archivos.
_PORTAL_LOCK = _threading.Lock()
_PORTAL_HITS = _defaultdict(_deque)
_PORTAL_MISSES = _defaultdict(_deque)


def _client_ip():
    # a través del túnel de Cloudflare todas las visitas llegan desde 127.0.0.1: la IP real viene en la cabecera
    if request.remote_addr in ('127.0.0.1', '::1') and request.headers.get('Cf-Connecting-Ip'):
        return request.headers['Cf-Connecting-Ip'][:64]
    return request.remote_addr or '?'


def _prune(q, window, now):
    while q and now - q[0] > window:
        q.popleft()


def portal_rate_limit():
    if not request.path.startswith('/c/'):
        return None
    cfg = current_app.config
    window, now, ip = cfg.get('PORTAL_WINDOW', 600), _time.monotonic(), _client_ip()
    with _PORTAL_LOCK:
        hits, misses = _PORTAL_HITS[ip], _PORTAL_MISSES[ip]
        _prune(hits, window, now)
        _prune(misses, window, now)
        if len(misses) >= cfg.get('PORTAL_MAX_MISSES', 20) or len(hits) >= cfg.get('PORTAL_MAX_HITS', 300):
            return ('Demasiadas solicitudes. Espere unos minutos e intente de nuevo.', 429,
                    {'Retry-After': str(int(window))})
        hits.append(now)
    return None


def portal_count_miss(response):
    """Un enlace que no existe cuenta como intento fallido (alguien probando enlaces)."""
    if request.path.startswith('/c/') and response.status_code == 404:
        with _PORTAL_LOCK:
            _PORTAL_MISSES[_client_ip()].append(_time.monotonic())
    return response


def portal_limits_reset():
    with _PORTAL_LOCK:
        _PORTAL_HITS.clear()
        _PORTAL_MISSES.clear()
