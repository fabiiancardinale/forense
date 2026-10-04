"""Exercise the asynchronous upload contract and safe presentation of results."""
import io
from test_hardening import app_users, login, token, png
from evidex.inspection.jobs import Jobs


def test_async_upload_is_idempotent_and_returns_owned_destination(tmp_path):
    app,_=app_users(tmp_path);c=app.test_client();login(c)
    csrf=token(c,'/analizar')
    def send(blob):
        return c.post('/analizar',headers={'Accept':'application/json'},data={
            'csrf_token':csrf,'request_key':'ui-request-key-12345',
            'archivo':(io.BytesIO(blob),'documento.png')})
    first=send(png());assert first.status_code==201
    assert send(png()).json==first.json
    assert len(Jobs(tmp_path).list('admin'))==1
    conflict=send(png()+b'changed')
    assert conflict.status_code==400 and conflict.json['error']
    page=c.get(first.json['url']).get_data(as_text=True)
    assert 'Tu archivo está en espera' in page
    assert 'El worker debe estar activo' not in page
    assert 'data-status-url=' in page


def test_result_explains_partial_review_and_escapes_evidence(tmp_path):
    app,_=app_users(tmp_path);c=app.test_client();login(c)
    q=Jobs(tmp_path);q.add('sample','admin','documento.pdf','a'*64,12,'example-key')
    j=q.claim();q.finish(j['id'],j['lease'],'partial',{
        'verdict':'alteration_detected','summary':'Cambios entre revisiones',
        'findings':[{'title':'Texto modificado','detail':'Comparación',
                     'removed':['Anterior <script>alert(1)</script>'],'added':['Posterior']}],
        'detectors':[{'name':'texto/OCR','status':'not_run','detail':'Texto no legible'}]})
    html=c.get('/analizar/sample').get_data(as_text=True)
    assert 'Revisión parcial' in html and 'Alteración detectada' in html
    assert 'En la revisión anterior' in html and 'No realizado' in html
    assert 'Información técnica del archivo' in html and '<details' in html
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html
