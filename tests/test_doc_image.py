"""Imágenes que son documentos (presupuesto, formulario, captura): se reconocen por su texto y se revisan como
documento, sin las pruebas de una foto de cámara."""
import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from evidex.claims import service


def _documento() -> bytes:
    im = Image.new("RGB", (1240, 1754), (250, 248, 240))
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        f = ImageFont.load_default(size=34)
    lines = ["TALLER LOS AROMOS LTDA", "PRESUPUESTO DE REPARACION N 4512", "Fecha: 10/09/2026",
             "Cliente: Ana Perez Soto", "Patente: KXTR-45", "Marca: Hyundai  Modelo: Accent",
             "Parachoques trasero    $ 320.000", "Foco trasero derecho   $ 95.000", "Pintura y mano de obra $ 410.000",
             "Subtotal               $ 825.000", "IVA                    $ 156.750", "TOTAL                  $ 981.750",
             "Validez de la oferta: 15 dias"]
    for i, t in enumerate(lines):
        d.text((90, 120 + i * 95), t, fill=(30, 40, 90), font=f)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=88)
    return b.getvalue()


def test_imagen_de_documento_se_revisa_como_documento(tmp_path):
    from evidex.forensics import ocr
    if not ocr.available():
        pytest.skip("OCR no instalado (pip install rapidocr)")
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/nuevo", data={"numero": "SIN-2026-9600", "fecha_siniestro": "2026-09-26T10:00", "asegurado": "Ana Pérez Soto",
                           "patente": "BBCD42", "fotos": [(io.BytesIO(_documento()), "presupuesto_whatsapp.jpg")]},
           content_type="multipart/form-data")
    case = service.find_case(tmp_path / "casos", "SIN-2026-9600")
    service.run_analysis(case, tmp_path / "casos" / "registro.jsonl")
    snap = service.snapshot(case)
    assert snap["photos"][0]["doc_image"] and "PRESUPUESTO" in snap["photos"][0]["doc_text"]
    rules = {f["rule"] for f in snap["findings"]}
    assert {"doc_dated_before", "doc_plate_mismatch"} <= rules          # fecha 10/09 antes del choque; otra patente
    assert not rules & {"no_metadata", "odd_ratio", "ai_dimensions"}   # no se le piden datos de cámara
    fotos = c.get(f"/caso/{case.root.name}?tab=fotos").get_data(as_text=True)
    assert "Imagen de documento" in fotos and "Texto leído" in fotos
