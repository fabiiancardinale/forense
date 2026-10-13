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
    assert upload_guard.inspect(ok, "ok.docx", "portal") == {"kind": "word"}      # el asegurado también puede subirlo


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
    assert "Del Word: fotos_choque.docx" in fotos
    assert case.verify_evidence() == (True, [])
    # agregar otro Word después, desde la pestaña Documentos, también saca sus fotos
    r = c.post(f"/caso/{cid}/fotos", data={"fotos": [(io.BytesIO(_docx({"word/media/image9.jpeg": b""})), "otro.docx")]},
               content_type="multipart/form-data", follow_redirects=True)
    assert "agregado" in r.get_data(as_text=True)
    nombres = [e["data"]["original_name"] for e in case.active_evidence()]
    assert "otro.docx" in nombres and nombres.count("fotos_choque_imagen1.jpg") == 1
    assert not any(n.startswith("otro_imagen") for n in nombres)      # mismas fotos: no se repiten


def test_word_desde_el_portal(tmp_path):
    from evidex.portal import links
    from evidex.core.case import Case
    case = Case.create(tmp_path / "casos" / "SIN-1", "Siniestro SIN-1", kind="claim")
    data = links.create_link(case, actor="prueba") if hasattr(links, "create_link") else None
    data = links.load(case)
    rec = links.receive_file(case, data, "fotos.docx", _docx(), "documento", title="Fotos del choque")
    assert rec["kind"] == "doc"
    ev = {e["data"]["original_name"]: e for e in case.active_evidence()}
    assert ev[rec["name"]]["data"]["note"] == "word"
    sacadas = [e for e in ev.values() if e["data"].get("from_word") == rec["sha256"]]
    assert len(sacadas) == 2 and all(e["actor"] == "asegurado (portal)" for e in sacadas)


def _drawing(rid, n, name, descr=""):
    return (f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="5400000" cy="4050000"/>'
            f'<wp:docPr id="{n}" name="{name}" descr="{descr}"/><a:graphic><a:graphicData><pic:pic><pic:nvPicPr>'
            f'<pic:cNvPr id="0" name="{name}"/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/></pic:blipFill>'
            '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def _docx_real(t0_name="IMG_20260801_101500.jpg"):
    """Un Word como lo guarda Microsoft Word: las imágenes van en <w:drawing> con su nombre y descripción."""
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
    doc = (f'<?xml version="1.0"?><w:document {ns}><w:body>'
           '<w:p><w:r><w:t>Parachoques trasero</w:t></w:r></w:p>' + _drawing("rId5", 1, t0_name) +
           _drawing("rId6", 2, "Imagen 2", "C:\\Users\\tallerlosaromos\\Pictures\\WhatsApp Image 2026-10-01 at 18.40.12.jpeg") +
           _drawing("rId7", 3, "Imagen 3") + '</w:body></w:document>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId5" Type="image" Target="media/image1.jpeg"/>'
            '<Relationship Id="rId6" Type="image" Target="media/image2.jpeg"/>'
            '<Relationship Id="rId7" Type="image" Target="media/image3.png"/></Relationships>')

    def img(fmt, seed, w, h, **kw):
        b = io.BytesIO()
        textured_image(seed, w, h).save(b, fmt, **kw)
        return b.getvalue()
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("docProps/core.xml", CORE)
        z.writestr("word/media/image1.jpeg", img("JPEG", 11, 1600, 1200, quality=70, dpi=(220, 220)))
        z.writestr("word/media/image2.jpeg", img("JPEG", 12, 1280, 960, quality=80))
        z.writestr("word/media/image3.png", img("PNG", 13, 1080, 2340))
    return b.getvalue()


def test_word_guarda_pistas_de_cada_imagen(tmp_path):
    from evidex.forensics import word
    p = tmp_path / "fotos.docx"
    p.write_bytes(_docx_real())
    d = list(word.image_details(p).values())
    assert d[0]["original_name"] == "IMG_20260801_101500.jpg" and d[0]["name_date"] == "2026-08-01T10:15:00"
    assert d[0]["texts"] == ["Parachoques trasero"] and tuple(d[0]["cm"]) == (15.0, 11.2)
    assert any("220 ppp" in c for c in d[0]["clues"]) and any("WhatsApp" in c for c in d[0]["clues"])
    assert d[1]["original_name"].startswith("WhatsApp Image 2026-10-01") and d[1]["name_date_origin"] == "WhatsApp"
    assert "tallerlosaromos" in d[1]["original_path"]
    assert d[2].get("original_name") is None and any("captura de pantalla" in c for c in d[2]["clues"])


def test_word_imagen_con_fecha_anterior_por_su_nombre(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/nuevo", data={"numero": "SIN-2026-9401", "fecha_siniestro": "2026-10-01T10:00", "asegurado": "Ana Pérez",
                           "patente": "JSGG71", "fotos": [(io.BytesIO(_docx_real()), "fotos.docx")]},
           content_type="multipart/form-data")
    case = service.find_case(tmp_path / "casos", "SIN-2026-9401")
    service.run_analysis(case, tmp_path / "casos" / "registro.jsonl")
    fs = (service.snapshot(case) or {})["findings"]
    rules = [f["rule"] for f in fs]
    assert "word_photo_name_before" in rules                      # IMG_20260801: dos meses antes del choque
    assert "no_metadata" not in rules                              # sin una alerta «sin fecha» por cada imagen del Word
    fotos = c.get(f"/caso/{case.root.name}?tab=fotos").get_data(as_text=True)
    assert "Lo que guardó el Word de esta imagen" in fotos and "IMG_20260801_101500.jpg" in fotos
    assert "01-08-2026 10:15" in fotos and "Parachoques trasero" in fotos
