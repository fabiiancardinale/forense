"""Word (.docx) del asegurado: se acepta, se sacan sus fotos, se leen sus datos y se rechazan los peligrosos."""
import io
import zipfile

import pytest

from helpers import textured_image
from evidex.claims import service
from evidex.core import upload_guard
from evidex.inspection.validation import InvalidFile

CT = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="xml" ContentType="application/xml"/></Types>')
DOC = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
       '<w:p><w:r><w:t>Fotos del choque, patente JSGG71</w:t></w:r></w:p><w:p><w:r><w:t>Atte. Juan</w:t></w:r></w:p>'
       '</w:body></w:document>')
CORE = ('<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>Taller Rápido Ltda</dc:creator>'
        '<cp:lastModifiedBy>Taller Rápido Ltda</cp:lastModifiedBy>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">2026-09-01T10:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-10-02T09:00:00Z</dcterms:modified></cp:coreProperties>')
APP = ('<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
       '<Application>Microsoft Office Word</Application><AppVersion>16.0000</AppVersion></Properties>')


def _docx(extra=None, doc=DOC) -> bytes:
    def img(fmt, seed):
        b = io.BytesIO()
        textured_image(seed, 640, 480).save(b, fmt)
        return b.getvalue()
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("word/document.xml", doc)
        z.writestr("docProps/core.xml", CORE)
        z.writestr("docProps/app.xml", APP)
        z.writestr("word/media/image1.jpeg", img("JPEG", 1))
        z.writestr("word/media/image2.png", img("PNG", 2))
        z.writestr("word/media/image3.emf", b"no es una foto")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return b.getvalue()


def test_word_peligrosos_se_rechazan(tmp_path):
    for name, data in (("macros.docx", _docx({"word/vbaProject.bin": b"x"})),
                       ("entidad.docx", _docx(doc='<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')),
                       ("falso.docx", b"PK no es zip")):
        p = tmp_path / name
        p.write_bytes(data)
        with pytest.raises(InvalidFile):
            upload_guard.inspect(p, name, "evidencia")
    ok = tmp_path / "ok.docx"
    ok.write_bytes(_docx())
    assert upload_guard.inspect(ok, "ok.docx", "evidencia") == {"kind": "word"}
    with pytest.raises(InvalidFile):
        upload_guard.inspect(ok, "ok.docx", "portal")             # el portal no recibe Word (por ahora)


def test_word_en_el_caso(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    c = app.test_client()
    r = c.post("/nuevo", data={"numero": "SIN-2026-9400", "fecha_siniestro": "2026-10-01T10:00", "asegurado": "Ana Pérez",
                               "patente": "JSGG71", "fotos": [(io.BytesIO(_docx()), "fotos_choque.docx")]},
               content_type="multipart/form-data")
    assert r.status_code == 302
    case = service.find_case(tmp_path / "casos", "SIN-2026-9400")
    ev = {e["data"]["original_name"]: e for e in case.active_evidence()}
    assert ev["fotos_choque.docx"]["data"]["note"] == "word"
    sacadas = [e for e in ev.values() if e["data"].get("from_word")]
    assert sorted(e["data"]["original_name"] for e in sacadas) == ["fotos_choque_imagen1.jpg", "fotos_choque_imagen2.png"]
    assert all(e["data"]["from_word"] == ev["fotos_choque.docx"]["subject"] and e["data"]["note"] == "foto" for e in sacadas)
    # la imagen sacada es idéntica a la que traía el Word (no se recomprime)
    with zipfile.ZipFile(io.BytesIO((case.evidence_dir / ev["fotos_choque.docx"]["subject"]).read_bytes())) as z:
        assert z.read("word/media/image1.jpeg") == (case.evidence_dir / ev["fotos_choque_imagen1.jpg"]["subject"]).read_bytes()
    service.run_analysis(case, tmp_path / "casos" / "registro.jsonl")
    reglas = {f["rule"] for f in (service.snapshot(case) or {})["findings"]}
    assert {"word_before_claim", "word_other_author", "word_photos_no_data"} <= reglas
    cid = case.root.name
    docs = c.get(f"/caso/{cid}?tab=documentos").get_data(as_text=True)
    assert "Creado por Taller Rápido Ltda" in docs and "2 imagen(es), en la pestaña Fotos" in docs
    fotos = c.get(f"/caso/{cid}?tab=fotos").get_data(as_text=True)
    assert "sacada de fotos_choque.docx" in fotos
    assert case.verify_evidence() == (True, [])
    # agregar otro Word después, desde la pestaña Documentos, también saca sus fotos
    r = c.post(f"/caso/{cid}/fotos", data={"fotos": [(io.BytesIO(_docx({"word/media/image9.jpeg": b""})), "otro.docx")]},
               content_type="multipart/form-data", follow_redirects=True)
    assert "agregado" in r.get_data(as_text=True)
    nombres = [e["data"]["original_name"] for e in case.active_evidence()]
    assert "otro.docx" in nombres and nombres.count("fotos_choque_imagen1.jpg") == 1
    assert not any(n.startswith("otro_imagen") for n in nombres)      # mismas fotos: no se repiten
