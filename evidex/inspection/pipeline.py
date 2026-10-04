"""Conservative evidence aggregation. No score is represented as a probability."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
from pathlib import Path
from evidex.inspection import PIPELINE_VERSION
from evidex.inspection.validation import validate

LABELS = {'alteration_detected': 'Alteración detectada', 'suspicious': 'Indicios de alteración',
          'no_indications': 'Sin indicios detectados', 'inconclusive': 'No concluyente'}


def analyze(path, name, output, config=None):
    config = config or {}
    output = Path(output)
    info = validate(path, name)
    result = {'pipeline_version': PIPELINE_VERSION, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
              'coverage': info, 'findings': [], 'detectors': [], 'artifacts': [],
              'limitations': ['La ausencia de señales no certifica originalidad. Una edición no implica fraude.'],
              'versions': {}}
    for package in ('pillow','numpy','pdfplumber','c2pa-python','rapidocr_onnxruntime','pyHanko'):
        try:
            result['versions'][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result['versions'][package] = None
    # Never persist credential-derived values in public result metadata.
    result['config_hash'] = hashlib.sha256(json.dumps({'external_ai':bool(config.get('external_ai')),
                                      'pipeline':PIPELINE_VERSION},sort_keys=True).encode()).hexdigest()
    if info['kind'] == 'image':
        image_analysis(path, name, output, config, result)
    else:
        pdf_analysis(path, output, result)
    detectors = result['detectors']
    pending = [d for d in detectors if d['status'] in ('error','not_run','partial')]
    incomplete = any(d.get('required', True) for d in pending)
    result['pending_checks'] = [d['name'] for d in pending]
    result['assessment_scope'] = 'Comprobaciones locales de edición' if info['kind'] == 'image' else 'Revisiones recuperables, lectura y firmas disponibles del PDF'
    if any(f.get('confirmed_change') for f in result['findings']):
        verdict = 'alteration_detected'
    elif result['findings']:
        verdict = 'suspicious'
    elif incomplete:
        verdict = 'inconclusive'
    else:
        verdict = 'no_indications'
    result['verdict'] = verdict
    result['label'] = LABELS[verdict]
    result['summary'] = {'alteration_detected':'Se encontró un cambio de contenido verificable; revise la evidencia.',
                         'suspicious':'Existen indicios que requieren revisión; no prueban por sí solos adulteración.',
                         'inconclusive':'Faltan comprobaciones o evidencia suficiente para evaluar el archivo completo.',
                         'no_indications':'No se encontraron indicios en los métodos ejecutados; no certifica originalidad.'}[verdict]
    if verdict == 'no_indications':
        if info['kind'] == 'image' and any(d['name'] == 'IA global' and d['status'] == 'not_run' for d in detectors):
            result['summary'] += ' La generación por IA no se evaluó.'
        elif info['kind'] == 'pdf':
            result['summary'] += ' Una edición puede no dejar revisiones recuperables en el PDF.'
    result['processing_status'] = 'partial' if pending else 'completed'
    return result


def detector(result, name, status, detail='', required=True):
    result['detectors'].append({'name':name,'status':status,'detail':detail,'required':required})


def image_analysis(path, name, output, config, result):
    from evidex.claims.analysis import quick_check
    from evidex.forensics import image_content, external
    meta, findings = quick_check(Path(path), name)
    content = meta.get('content') or {}
    if meta.get('error'):
        detector(result,'imagen','error',meta['error']); return
    detector(result,'metadatos','completed','Los metadatos pueden ser modificados.')
    detector(result,'pixeles','error' if not content or content.get('error') else 'completed',
             content.get('error','') if content else 'El motor no devolvió resultados.')
    cp = content.get('c2pa') or {'state':'not_run'}
    result['provenance'] = cp
    detector(result,'C2PA', 'not_run' if cp['state']=='not_run' else 'error' if cp['state']=='error' else 'completed',
             cp.get('note',''), required=False)
    # Context of insurance is not file tampering. Weak metadata cues stay separate.
    ignore = {'taken_before','taken_late','taken_future','taken_future_portal','odd_ratio','no_metadata','recompressed','daylight_at_night'}
    result['observations'] = [{'rule':f.rule, 'detail':f.summary} for f in findings if f.rule in ignore]
    result['findings'] = [{'rule':f.rule,'title':f.title,'detail':f.summary,'severity':f.severity,
                           'evidence_type':'heuristic','confirmed_change':False}
                          for f in findings if f.rule not in ignore]
    if content and not content.get('error'):
        image = image_content.overlay(path, content)
        if image:
            (output/'regions.png').write_bytes(image)
            result['artifacts'].append({'file':'regions.png','label':'Regiones sospechosas (heurística, no máscara confirmada)'})
    if config.get('external_ai'):
        response = external.ai_check(Path(path), config)
        if 'error' in response:
            detector(result,'IA global','error',response['error'])
        else:
            detector(result,'IA global','completed','Score de proveedor no calibrado para este dominio.')
            result['ai_score'] = response['score']
            # Conservative triage only; never a confirmed alteration.
            if response['score'] >= .8:
                result['findings'].append({'rule':'external_ai','title':'Señal de generación por IA',
                    'detail':f"Score del proveedor: {response['score']:.3f}. No localiza cambios ni identifica con certeza la herramienta.",
                    'confirmed_change':False,'evidence_type':'model'})
    else:
        detector(result,'IA global','not_run','No se habilitó un detector de IA con autorización para este archivo.',required=False)
    detector(result,'localización aprendida','not_run','No hay un modelo de localización validado y con licencia incorporado.',required=False)
    result['limitations'].append('Las regiones marcadas son indicios de heurísticas; no reconstruyen el contenido anterior.')


def pdf_analysis(path, output, result):
    import pdfplumber
    from evidex.forensics import pdf_versions, ocr
    raw = Path(path).read_bytes()
    ends = pdf_versions.eof_offsets(raw)
    if len(ends) > 20:
        detector(result,'versiones PDF','partial','Más de 20 marcadores de revisión; comparación omitida por seguridad.')
        versions = {'changes':[]}
    else:
        versions = pdf_versions.extract(raw)
    for change in versions.get('changes', []):
        result['findings'].append({'rule':'pdf_revision','title':'Cambio entre revisiones recuperables',
            'detail':f"Versión {change['from']} → {change['to']}", 'confirmed_change':True,
            'evidence_type':'version_comparison','removed':change['removed'],'added':change['added'],
            'amounts':change['amounts'],'dates':change['dates']})
    if len(ends) <= 20:
        detector(result,'versiones PDF','completed','Solo se recuperan revisiones que permanezcan en el archivo; no implica que la primera sea original.')
    text_pages, scanned, read = [], [], 0
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ''
            if text.strip():
                read += 1
                text_pages.append({'page':i+1,'method':'text','text':text[:15000]})
            else:
                scanned.append(i)
    if scanned and ocr.available():
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(str(path)) as pdf:
            for i in scanned:
                try:
                    page = pdf[i]
                    bitmap = page.render(scale=2)
                    try:
                        lines = ocr.read_image(bitmap.to_pil())
                    finally:
                        bitmap.close(); page.close()
                    text = '\n'.join(t for t, confidence in lines if confidence >= .6)
                    if text.strip():
                        read += 1
                    text_pages.append({'page':i+1,'method':'ocr','text':text[:15000]})
                except Exception:
                    text_pages.append({'page':i+1,'method':'error','text':''})
    result['coverage'].update({'pages_read':read, 'pages_total':result['coverage']['pages']})
    detector(result,'texto/OCR','completed' if read == result['coverage']['pages'] else 'partial',f"{read} de {result['coverage']['pages']} páginas legibles")
    result['text_pages'] = text_pages
    # An OCR transcript is not a document authenticity detector.
    detector(result,'autenticidad documental','not_run','Sin original de referencia ni localizador documental validado; OCR no prueba autenticidad.',required=False)
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError:
        detector(result,'firmas PDF','not_run','Instale pyHanko para inspeccionar firmas.',required=False)
    else:
        with open(path,'rb') as fh:
            reader = PdfFileReader(fh)
            signatures = []
            for sig in reader.embedded_signatures:
                try:
                    status = validate_pdf_signature(sig, signer_validation_context=ValidationContext(allow_fetching=False))
                    signatures.append({'field':sig.field_name,'intact':status.intact,'valid':status.valid,
                        'trusted':status.trusted,'modification':str(status.modification_level),'docmdp_ok':status.docmdp_ok})
                except Exception as ex:
                    signatures.append({'field':sig.field_name,'error':type(ex).__name__})
        for signature in signatures:
            if signature.get('intact') is False or signature.get('valid') is False:
                result['findings'].append({'rule':'pdf_signature_invalid','title':'Firma PDF inválida',
                    'detail':f"El campo {signature['field']} no supera la validación criptográfica. No identifica por sí solo qué contenido cambió.",
                    'confirmed_change':False,'evidence_type':'signature'})
        result['pdf_signatures'] = signatures
        detector(result,'firmas PDF','error' if any('error' in s for s in signatures) else 'completed',
                 'Sin consultas externas; confianza depende de certificados disponibles.',required=False)
    result['limitations'].append('Un cambio entre revisiones no demuestra intención fraudulenta ni uso de IA. El OCR puede equivocarse.')
