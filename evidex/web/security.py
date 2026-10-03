"""Session, CSRF and response protections shared by every route."""
import secrets
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
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'nonce-" + g.csp_nonce + "'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'; connect-src 'self'"
    )
    if current_app.config['PRODUCTION']:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response
