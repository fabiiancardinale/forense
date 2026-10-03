"""Authenticated, owner-scoped file inspection; parsers run in the worker."""
import hashlib
import secrets
import shutil
from pathlib import Path
from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename
from evidex.inspection.jobs import Jobs, QueueFull
from evidex.inspection.validation import MAX_BYTES
from evidex.web.common import cx

bp = Blueprint('inspection', __name__)

def owner():
    return g.user['username'] if g.user else '__demo__'

def owned(job_id):
    jobs = Jobs(cx.workdir)
    job = jobs.get(job_id, owner())
    if not job:
        abort(404)
    return jobs, job

@bp.route('/analizar', methods=['GET','POST'])
def index():
    jobs = Jobs(cx.workdir)
    if request.method == 'POST':
        up = request.files.get('archivo')
        if not up or not up.filename:
            abort(400, 'Seleccione un archivo.')
        name = secure_filename(up.filename)[:180]
        if Path(name).suffix.lower() not in ('.jpg','.jpeg','.png','.webp','.heic','.heif','.pdf'):
            abort(400, 'Formato no admitido.')
        key = request.form.get('request_key','')
        if not 16 <= len(key) <= 128:
            abort(400, 'Clave de solicitud inválida.')
        job_id = secrets.token_hex(16)
        folder = jobs.root/job_id
        folder.mkdir(mode=0o700)
        try:
            size = 0; digest = hashlib.sha256()
            with (folder/'original').open('xb') as f:
                while chunk := up.stream.read(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        abort(413)
                    digest.update(chunk); f.write(chunk)
            (folder/'original').chmod(0o600)
            if not size:
                abort(400, 'Archivo vacío.')
            chosen = jobs.add(job_id, owner(), name, digest.hexdigest(), size, key,
                              request.form.get('external_consent') == 'yes')
            if chosen != job_id:
                shutil.rmtree(folder)
            return redirect(url_for('inspection.result', job_id=chosen), code=303)
        except QueueFull:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        except ValueError as ex:
            shutil.rmtree(folder, ignore_errors=True)
            abort(400, str(ex))
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
    return render_template('tools/inspection.html', jobs=jobs.list(owner()), request_key=secrets.token_hex(24), active='analizar')

@bp.get('/analizar/<job_id>')
def result(job_id):
    jobs, job = owned(job_id)
    return render_template('tools/inspection_result.html', job=job, active='analizar')

@bp.get('/analizar/<job_id>/estado')
def status(job_id):
    _, job = owned(job_id)
    return jsonify(status=job['status'], result=job['result'])

@bp.get('/analizar/<job_id>/archivo/<name>')
def artifact(job_id,name):
    jobs, job = owned(job_id)
    allowed = {a['file'] for a in (job['result'] or {}).get('artifacts',[])}
    if name not in allowed or name != 'regions.png':
        abort(404)
    return send_file(jobs.root/job_id/name, mimetype='image/png')

@bp.post('/analizar/<job_id>/reintentar')
def retry(job_id):
    jobs, _ = owned(job_id)
    if not jobs.retry(job_id, owner()):
        abort(409)
    return redirect(url_for('inspection.result',job_id=job_id),code=303)

@bp.errorhandler(QueueFull)
def full(ex):
    return str(ex), 429
