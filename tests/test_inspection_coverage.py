"""Missing optional capabilities must not hide successful local checks or failures."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
from test_hardening import png
from evidex.inspection.pipeline import analyze
from evidex.inspection.jobs import Jobs
from evidex.inspection.worker import run_one


def test_local_findings_and_failures_keep_their_meaning(tmp_path,monkeypatch):
    from evidex.claims import analysis
    from evidex.forensics import image_content, external
    p=tmp_path/'image.png';p.write_bytes(png())
    monkeypatch.setattr(image_content,'overlay',lambda *a:None)
    content={'clone':{},'noise':{},'c2pa':{'state':'not_run'}}
    monkeypatch.setattr(analysis,'quick_check',lambda *a:({'content':content},[]))
    result=analyze(p,p.name,tmp_path)
    assert result['verdict']=='no_indications' and result['processing_status']=='partial'
    assert 'La generación por IA no se evaluó' in result['summary']
    assert 'IA global' in result['pending_checks']
    monkeypatch.setattr(external,'ai_check',lambda *a:{'error':'provider unavailable'})
    assert analyze(p,p.name,tmp_path,{'external_ai':True})['verdict']=='inconclusive'
    for broken in ({},{'error':'decoder failure'}):
        monkeypatch.setattr(analysis,'quick_check',lambda *a,c=broken:({'content':c},[]))
        assert analyze(p,p.name,tmp_path)['verdict']=='inconclusive'
    finding=SimpleNamespace(rule='cloned_region',title='Posible clonado',summary='Regiones similares',severity='media')
    monkeypatch.setattr(analysis,'quick_check',lambda *a:({'content':content},[finding]))
    assert analyze(p,p.name,tmp_path)['verdict']=='suspicious'


def test_pdf_without_reference_keeps_local_result_and_limits(demo_src,tmp_path):
    p=demo_src/'limpio/documentos/presupuesto_automotriz_central.pdf'
    r=analyze(p,p.name,tmp_path)
    assert r['verdict']=='no_indications'
    assert r['processing_status']=='partial'
    assert 'autenticidad documental' in r['pending_checks']
    assert 'no certifica originalidad' in r['summary']


def test_worker_reads_utf8_under_windows_style_locale(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path);folder=jobs.root/'unicode';folder.mkdir()
    raw=png();(folder/'original').write_bytes(raw)
    jobs.add('unicode','admin','imagen.png',hashlib.sha256(raw).hexdigest(),len(raw),'unicode-key')
    original_read=Path.read_text
    def windows_read(self,encoding=None,errors=None,**kwargs):
        return original_read(self,encoding=encoding or 'cp1252',errors=errors,**kwargs)
    with monkeypatch.context() as m:
        m.setattr(Path,'read_text',windows_read)
        run_one(tmp_path)
    result=jobs.get('unicode','admin')['result']
    assert 'localización aprendida' in result['pending_checks']
    assert result['limitations'][0]=='La ausencia de señales no certifica originalidad. Una edición no implica fraude.'
