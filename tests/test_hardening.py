import io
import json
import re
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from evidex.accounts.users import Store, UserStorageError
from evidex.web import create_app
from evidex.inspection.jobs import Jobs
from evidex.inspection.worker import run_one
from evidex.inspection.validation import InvalidFile, validate

PW='a-very-long-password'

def app_users(tmp_path):
    app=create_app(tmp_path, {'TESTING':True})
    store=app.extensions['evidex']['store']
    assert store.add('admin','Admin','administrador',PW) is None
    assert store.add('alice','Alice','analista',PW) is None
    return app,store

def token(c, url='/ingresar'):
    c.get(url)
    with c.session_transaction() as s:
        return s['csrf']

def login(c,name='admin'):
    return c.post('/ingresar',data={'usuario':name,'clave':PW,'csrf_token':token(c)})

def png():
    b=io.BytesIO();Image.new('RGB',(64,64),'white').save(b,'PNG');return b.getvalue()

def upload(c,blob=None,name='sample.png',key='a'*32):
    return c.post('/analizar',data={'csrf_token':token(c,'/analizar'),'request_key':key,
                                  'archivo':(io.BytesIO(blob if blob is not None else png()),name)})

def test_default_closed_and_corruption_never_enables_demo(tmp_path):
    app,store=app_users(tmp_path)
    assert app.test_client().get('/analizar').status_code==302
    store.path.write_text('{broken')
    assert app.test_client().get('/ingresar').status_code==503
    app.config['DEMO_MODE']=True
    assert app.test_client().get('/usuarios').status_code==503
    store.path.unlink()
    with pytest.raises(UserStorageError): store.all()

def test_csrf_sessions_logout_and_password_revocation(tmp_path):
    app,store=app_users(tmp_path);c=app.test_client()
    assert c.post('/ingresar',data={'usuario':'admin','clave':PW}).status_code==400
    assert login(c).status_code==302
    with c.session_transaction() as s: old_sid=s['sid']
    assert c.get('/salir').status_code==405
    assert c.get('/analizar').status_code==200
    assert c.post('/salir',data={'csrf_token':token(c,'/analizar')}).status_code==302
    assert not store.state.valid(old_sid,store.get('admin'))
    login(c)
    store.add('admin','Admin','administrador','a-different-password')
    assert c.get('/analizar').status_code==302

def test_rate_limit_survives_store_restart(tmp_path):
    _,store=app_users(tmp_path)
    for _ in range(5): assert store.check('admin','wrong','1.2.3.4')[0] is None
    assert 'Demasiados' in Store(tmp_path).check('admin',PW,'another-ip')[1]

def test_origin_headers_and_production(tmp_path):
    app,_=app_users(tmp_path);c=app.test_client(); t=token(c)
    assert c.post('/ingresar',data={'csrf_token':t},headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/ingresar',data={'csrf_token':'inválido'}).status_code==400
    r=c.get('/ingresar')
    assert "'nonce-" in r.headers['Content-Security-Policy']
    assert "script-src 'self' 'unsafe-inline'" not in r.headers['Content-Security-Policy']
    with pytest.raises(ValueError): create_app(tmp_path,{'PRODUCTION':True,'DEMO_MODE':True})
    prod=create_app(tmp_path,{'PRODUCTION':True})
    assert prod.config['SESSION_COOKIE_SECURE']

def test_upload_owner_idempotency_and_real_worker(tmp_path):
    app,_=app_users(tmp_path);a=app.test_client();b=app.test_client();login(a);login(b,'alice')
    first=upload(a);assert first.status_code==303
    assert upload(a).location==first.location
    assert len(Jobs(tmp_path).list('admin'))==1
    assert b.get(first.location).status_code==404
    assert b.get(first.location+'/estado').status_code==404
    assert b.post(first.location+'/reintentar',data={'csrf_token':token(b,'/analizar')}).status_code==404
    assert run_one(tmp_path)
    job=Jobs(tmp_path).list('admin')[0]
    assert job['status']=='partial',job
    assert job['result']['verdict']=='inconclusive',job['result']
    assert job['result']['versions']['pillow']
    assert 'No concluyente' in a.get(first.location).get_data(as_text=True)
    assert a.get(first.location+'/archivo/original').status_code==404

def test_invalid_pdf_is_rejected_by_worker(tmp_path):
    app,_=app_users(tmp_path);c=app.test_client();login(c)
    assert upload(c,b'%PDF-1.7\nthis is not a PDF','bad.pdf').status_code==303
    run_one(tmp_path)
    row=Jobs(tmp_path).list('admin')[0]
    assert row['status']=='rejected'
    assert row['result']['verdict']=='inconclusive'

def test_formats_dimensions_and_truncation(tmp_path):
    p=tmp_path/'file';p.write_bytes(png())
    with pytest.raises(InvalidFile): validate(p,'file.jpg')
    p.write_bytes(png()[:25])
    with pytest.raises(InvalidFile): validate(p,'file.png')

def test_queue_claims_and_expired_worker_leases(tmp_path):
    q=Jobs(tmp_path)
    for i in range(4):q.add(str(i),'admin','a.png',str(i),1,str(i))
    with ThreadPoolExecutor(4) as pool: claims=list(pool.map(lambda _:Jobs(tmp_path).claim(), range(4)))
    assert len({j['id'] for j in claims})==4
    with q.db() as db: db.execute('UPDATE jobs SET started=? WHERE id=?',(time.time()-300,claims[0]['id']))
    q.claim()
    assert not q.finish(claims[0]['id'],claims[0]['lease'],'completed',{})
    assert q.get(claims[0]['id'],'admin')['status']=='failed'

def test_provider_missing_invalid_scores_are_errors(tmp_path,monkeypatch):
    from evidex.forensics import external
    p=tmp_path/'a';p.write_bytes(b'example')
    for score in (None,float('nan'),True,1.5,-.2):
        monkeypatch.setattr(external,'_post',lambda *a,s=score,**k:{'status':'success','type':{'ai_generated':s}})
        assert 'error' in external.ai_check(p,{'sightengine_user':'x','sightengine_secret':'y'})

def test_c2pa_absent_and_engine_failure_are_distinct(monkeypatch):
    from types import SimpleNamespace
    from evidex.forensics.image_content import c2pa_status
    class ManifestNotFoundError(Exception):pass
    from contextlib import nullcontext
    options={'Settings':SimpleNamespace(from_dict=lambda c:nullcontext()), 'Context':lambda **kw:nullcontext()}
    def absent(*a,**kw):raise ManifestNotFoundError()
    monkeypatch.setitem(sys.modules,'c2pa',SimpleNamespace(Reader=absent,**options))
    assert c2pa_status('a')['state']=='absent'
    def failed(*a,**kw):raise RuntimeError()
    monkeypatch.setitem(sys.modules,'c2pa',SimpleNamespace(Reader=failed,**options))
    assert c2pa_status('a')['valid'] is None
    assert c2pa_status('a')['state']=='error'

def test_ledger_concurrent_processes_remain_verifiable(tmp_path):
    import subprocess
    from evidex.core.ledger import Ledger, verify_chain
    script = 'from pathlib import Path; from evidex.core.ledger import Ledger; import sys; l=Ledger(Path(sys.argv[1])); [l.append("test","write",str(i)) for i in range(15)]'
    children=[subprocess.Popen([sys.executable,'-c',script,str(tmp_path)]) for _ in range(3)]
    assert all(p.wait(timeout=20)==0 for p in children)
    entries=Ledger(tmp_path).entries()
    assert len(entries)==45
    assert verify_chain(entries)[0]

def test_mvp_excludes_legacy_and_demo_is_local(tmp_path):
    app,_=app_users(tmp_path);c=app.test_client();login(c)
    assert c.get('/siniestros').status_code==404
    assert c.get('/c/'+'a'*32).status_code==404
    app.config['DEMO_MODE']=True
    assert c.get('/analizar',environ_overrides={'REMOTE_ADDR':'192.168.1.5'}).status_code==403

def test_worker_timeout_and_integrity_failure_are_not_original(tmp_path):
    q=Jobs(tmp_path);folder=q.root/'abc';folder.mkdir();(folder/'original').write_bytes(png())
    import hashlib
    q.add('abc','admin','sample.png',hashlib.sha256(png()).hexdigest(),len(png()),'first')
    run_one(tmp_path,timeout=.00001)
    assert q.get('abc','admin')['status']=='failed'
    assert q.get('abc','admin')['result']['verdict']=='inconclusive'
    assert q.retry('abc','admin')
    (folder/'original').write_bytes(b'changed')
    run_one(tmp_path)
    assert q.get('abc','admin')['status']=='failed'

def test_evaluator_counts_abstentions():
    from scripts.evaluate_predictions import evaluate
    result=evaluate([{'id':'1','label':'edited','verdict':'inconclusive'},
                     {'id':'2','label':'edited','verdict':'suspicious'},
                     {'id':'3','label':'original','verdict':'suspicious'}])
    assert result['recall_including_abstentions']==.5
    assert result['false_positive_rate_all_originals']==1
    assert result['coverage']==pytest.approx(2/3)

def test_idempotency_conflict_and_pending_quota(tmp_path):
    app,_=app_users(tmp_path);c=app.test_client();login(c)
    assert upload(c).status_code==303
    assert upload(c,blob=png()+b'different').status_code==400
    for i in range(9): assert upload(c,key=f'{i:032d}').status_code==303
    assert upload(c,key='z'*32).status_code==429
    assert len([p for p in Jobs(tmp_path).root.iterdir() if p.is_dir()])==10

def test_known_incremental_pdf_reports_actual_text_change(demo_src,tmp_path):
    from evidex.inspection.pipeline import analyze
    pdf=demo_src/'actual/documentos/presupuesto_taller.pdf'
    result=analyze(pdf,pdf.name,tmp_path)
    assert result['verdict']=='alteration_detected'
    changes=[f for f in result['findings'] if f['rule']=='pdf_revision']
    assert changes and changes[0]['removed'] and changes[0]['added']
    assert result['processing_status']=='partial'  # known edits do not establish full authenticity
    assert result['coverage']['pages_read']==result['coverage']['pages_total']


def test_native_login_policy_preserves_origin_without_relaxing_csrf(tmp_path):
    app,_=app_users(tmp_path)
    c=app.test_client()
    page=c.get('/ingresar')
    assert page.headers['Referrer-Policy']=='same-origin'
    with c.session_transaction() as session:
        csrf=session['csrf']
    credentials={'usuario':'admin','clave':PW,'csrf_token':csrf}
    # Opaque or foreign origins remain forbidden, even with a valid form token.
    for origin in ('null','https://evil.example','http://localhost:9999'):
        assert c.post('/ingresar',data=credentials,headers={'Origin':origin}).status_code==403
    assert c.post('/ingresar',data={'usuario':'admin','clave':PW},
                  headers={'Origin':'http://localhost'}).status_code==400
    response=c.post('/ingresar',data=credentials,headers={'Origin':'http://localhost'})
    assert response.status_code==302 and response.location.endswith('/analizar')
    assert c.get('/analizar').status_code==200
