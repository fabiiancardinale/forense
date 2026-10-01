"""Motores forenses: fotos, PDF, chats, OCR, validación chilena y servicios externos."""

import pytest

from helpers import ACTUAL, LIMPIO, analysis_of, textured_image
from veritas.forensics import documents


def test_pdf_metadata_detects_incremental_edit(demo_src, tmp_path):
    m = documents.pdf_metadata(demo_src / "actual/documentos/presupuesto_taller.pdf")
    assert m["is_pdf"] and m["revisions"] == 2 and "iLovePDF" in m["tools"]
    clean = documents.pdf_metadata(demo_src / "limpio/documentos/presupuesto_automotriz_central.pdf")
    assert clean["revisions"] == 1 and clean["created"].startswith("2026-09-22")
    fake = tmp_path / "factura.pdf"
    fake.write_bytes(b"esto no es un pdf")
    d = documents.Document("ab" * 32, "factura.pdf", documents.pdf_metadata(fake), "2026-09-21T00:00:00")
    assert [f.rule for f in documents.analyze({"numero": "N", "fecha_siniestro": "2026-09-20T10:00:00"}, "e:1", [d], [])] == ["not_pdf"]


def test_photo_metadata_tampering(tmp_path):
    """Fechas internas cambiadas, hora GPS que no calza y miniatura de otra imagen."""
    import io
    piexif = pytest.importorskip("piexif")
    from PIL import Image, ImageDraw
    from veritas.claims.analysis import quick_check

    def make(seed, dto, dt=None, thumb_from=None):
        img = Image.new("RGB", (800, 600), (90, 110, 130))
        d = ImageDraw.Draw(img)
        for i in range(20):
            x, y = (i * 37 * seed) % 700, (i * 53) % 500
            d.rectangle([x, y, x + 90, y + 70], fill=((i * 40) % 255, (i * 70 * seed) % 255, 60))
        img = Image.blend(img, Image.effect_noise((800, 600), 30).convert("RGB"), 0.1)  # textura de foto real
        t = (thumb_from or img).copy(); t.thumbnail((160, 120)); b = io.BytesIO(); t.save(b, "JPEG")
        ex = piexif.dump({
            "0th": {piexif.ImageIFD.Make: b"samsung", piexif.ImageIFD.DateTime: (dt or dto).encode()},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: dto.encode(), piexif.ExifIFD.DateTimeDigitized: (dt or dto).encode(),
                     piexif.ExifIFD.OffsetTimeOriginal: b"-03:00", piexif.ExifIFD.ExposureTime: (1, 120),
                     piexif.ExifIFD.FNumber: (18, 10), piexif.ExifIFD.ISOSpeedRatings: 100},
            "GPS": {piexif.GPSIFD.GPSDateStamp: b"2026:09:20", piexif.GPSIFD.GPSTimeStamp: ((15, 1), (30, 1), (0, 1))},
            "1st": {}, "thumbnail": b.getvalue()})
        return img, ex

    def rules(name, *a, **k):
        img, ex = make(*a, **k)
        img.save(tmp_path / name, exif=ex)
        return {f.rule for f in quick_check(tmp_path / name, name, "2026-09-20T12:00:00")[1]}

    assert rules("ok.jpg", 1, "2026:09:20 12:30:00") == set()
    assert {"exif_dates_mismatch", "exif_gps_time_mismatch"} <= rules("a.jpg", 1, "2026:09:25 18:10:00", dt="2026:09:20 12:30:00")
    assert "exif_gps_time_mismatch" in rules("b.jpg", 1, "2026:09:25 18:10:00")
    orig, _ = make(1, "2026:09:20 12:30:00")
    assert "thumbnail_mismatch" in rules("c.jpg", 3, "2026:09:20 12:30:00", thumb_from=orig)
    Image.new("RGB", (1080, 2400), (250, 250, 250)).save(tmp_path / "p.png")
    assert "screenshot" in {f.rule for f in quick_check(tmp_path / "p.png", "p.png")[1]}


def test_pasted_region_and_clone_detected(tmp_path):
    import io
    from PIL import Image
    from veritas.forensics.image_content import analyze_image

    a = textured_image(1)
    buf = io.BytesIO(); a.save(buf, "JPEG", quality=70); buf.seek(0)
    first = Image.open(buf).convert("RGB")
    clean = tmp_path / "limpia.jpg"; first.save(clean, quality=92)
    pasted = first.copy(); pasted.paste(textured_image(2).crop((0, 0, 300, 240)), (330, 260))
    forged = tmp_path / "pegada.jpg"; pasted.save(forged, quality=92)
    cloned = a.copy(); cloned.paste(a.crop((60, 60, 260, 260)), (600, 380))
    clone_path = tmp_path / "clonada.jpg"; cloned.save(clone_path, quality=92)

    c = analyze_image(clean)
    assert not c["ghost"].get("region") and not c["clone"].get("src")
    r = analyze_image(forged)["ghost"].get("region")
    assert r, "no detectó la zona pegada"
    x0, y0, x1, y1 = r["bbox"]
    assert x0 < 630 and x1 > 330 and y0 < 500 and y1 > 260          # la zona marcada cae sobre lo pegado
    assert analyze_image(clone_path)["clone"].get("src"), "no detectó el clonado"


def test_solar_elevation_santiago():
    from datetime import datetime
    from veritas.forensics.image_content import solar_elevation
    # 20-09-2026 en Santiago: mediodía solar cerca de las 16:45 UTC, noche a las 02:00 UTC
    assert solar_elevation(-33.45, -70.66, datetime(2026, 9, 20, 16, 45)) > 50
    assert solar_elevation(-33.45, -70.66, datetime(2026, 9, 21, 2, 0)) < -20


def test_chilean_validation():
    from veritas.forensics.chile import plate_format, plates_in, rut_dv, rut_valid, ruts_in
    assert rut_dv(12345678) == "5" and rut_valid("12.345.678-5") and rut_valid("12.345.678-9") is False
    assert rut_valid("sin rut") is None
    assert ruts_in("Taller RUT 76.543.210-3, cliente 12345678-9") == [("76.543.210-3", True), ("12.345.678-9", False)]
    assert plate_format("KXTR-45") == "nueva" and plate_format("AB1234") == "antigua" and plate_format("AEIO12") is None
    assert plates_in("patente KXTR·45 y BB-1234") == ["KXTR45", "BB1234"]


def test_whatsapp_parsing_android_and_iphone(tmp_path):
    import zipfile as zf
    from veritas.forensics.whatsapp import read
    text = ("19/09/26, 21:14 - Ana: mañana chocamos y\nle decimos al seguro\n"
            "[20/09/2026, 6:41:12 p. m.] Pedro: Se eliminó este mensaje\n"
            "20/09/26, 19:05 - Pedro: <Multimedia omitido>\n")
    p = tmp_path / "chat.txt"; p.write_text(text, encoding="utf-8")
    chat = read(p)
    assert [m.sender for m in chat.messages] == ["Ana", "Pedro", "Pedro"]
    assert chat.messages[0].text.endswith("le decimos al seguro")          # mensaje de varias líneas
    assert chat.messages[1].ts.hour == 18 and chat.messages[1].deleted     # 6:41 p. m.
    assert chat.messages[2].media
    z = tmp_path / "chat.zip"
    with zf.ZipFile(z, "w") as f:
        f.writestr("_chat.txt", text)
    assert len(read(z).messages) == 3
    (tmp_path / "nota.txt").write_text("hola, esto no es un chat", encoding="utf-8")
    assert read(tmp_path / "nota.txt") is None


def test_pdf_hidden_version_recovered(demo_src):
    from veritas.forensics.pdf_versions import extract, version_bytes
    raw = (demo_src / "actual" / "documentos" / "presupuesto_taller.pdf").read_bytes()
    r = extract(raw)
    assert [v["readable"] for v in r["versions"]] == [True, True]
    ch = r["changes"][0]
    assert ch["amounts"] == [["$1.850.000"], ["$4.650.000"]] and ch["dates"] == [["14-09-2026"], ["21-09-2026"]]
    assert ch["producer"] == "iLovePDF"
    v1 = version_bytes(raw, 1)
    assert v1.endswith(b"%%EOF\n") and len(v1) < len(raw)
    clean = (demo_src / "limpio" / "documentos" / "presupuesto_automotriz_central.pdf").read_bytes()
    assert extract(clean)["changes"] == []


def test_external_services_with_mocked_provider(tmp_path, monkeypatch):
    from veritas.forensics import external
    from veritas.claims.analysis import Photo
    img = tmp_path / "evidence"; img.mkdir()
    (img / ("a" * 64)).write_bytes(b"\xff\xd8 imagen")

    class FakeCase:
        root, evidence_dir = tmp_path, img
    calls = []

    def fake_post(url, data, headers):
        calls.append(url)
        if "sightengine" in url:
            return {"status": "success", "type": {"ai_generated": 0.93, "ai_generators": {"midjourney": 0.9}}}
        return {"responses": [{"webDetection": {"fullMatchingImages": [{"url": "https://ejemplo.cl/auto.jpg"}],
                                                "pagesWithMatchingImages": [{"url": "https://ejemplo.cl/venta", "pageTitle": "Venta"}]}}]}
    monkeypatch.setattr(external, "_post", fake_post)
    photo = Photo("a" * 64, "foto.jpg", {}, "2026-09-20T18:00:00")
    cfg = {"sightengine_user": "u", "sightengine_secret": "s", "google_vision_key": "k"}
    res = external.run(FakeCase(), [photo], cfg)
    external.run(FakeCase(), [photo], cfg)                       # segunda vez: usa lo guardado, no vuelve a pagar
    assert len(calls) == 2
    rules = {f.rule: f for f in external.findings([photo], res)}
    assert rules["ai_detected"].severity == "alta" and "midjourney" in rules["ai_detected"].summary
    assert rules["found_online"].severity == "alta" and "ejemplo.cl/venta" in rules["found_online"].summary
    assert external.run(FakeCase(), [photo], {}) == {}


def test_places_in_chat_text():
    from veritas.forensics.places import mention
    assert mention("voy saliendo de Viña, llego tipo 8")[:1] == ("Viña del Mar",)
    assert mention("estoy en Rancagua con el auto")[0] == "Rancagua"
    assert mention("llegando a Temuco")[3] == "rumbo a"
    assert mention("Santiago me dijo que sí") is None and mention("el taller de Maipú cobra caro") is None


def test_chat_place_contradicts_crash(loaded):
    work, _ = loaded
    fs = [f for f in analysis_of(work, ACTUAL)[4] if f.rule == "impossible_travel"]
    assert any("dice estar en Viña del Mar" in f.summary for f in fs)


def test_ocr_reads_plate_and_scanned_document(loaded):
    from veritas.forensics import ocr
    if not ocr.available():
        pytest.skip("OCR no instalado (pip install rapidocr_onnxruntime)")
    work, _ = loaded
    _, _, photos, docs, findings, _, _ = analysis_of(work, ACTUAL)
    rules = {f.rule: f for f in findings}
    assert "HJKL·21" in rules["plate_photo_mismatch"].summary and rules["plate_photo_mismatch"].severity == "alta"
    scanned = next(d for d in docs if d.name == "boleta_grua_escaneada.pdf")
    assert scanned.meta.get("ocr") and "18-09-2026" in scanned.meta["text"]
    assert any(f.rule == "doc_dated_before" and "boleta_grua" in f.summary for f in findings)
    assert not [f for f in analysis_of(work, LIMPIO)[4] if f.rule == "plate_photo_mismatch"]


def test_heic_from_iphone_keeps_date(tmp_path):
    pytest.importorskip("pillow_heif")
    from PIL import Image
    from veritas.claims.analysis import photo_metadata
    exif = Image.Exif(); exif[0x010F] = "Apple"; exif[0x8769] = {0x9003: "2026:09:28 08:15:00"}
    p = tmp_path / "IMG_2001.HEIC"
    Image.new("RGB", (640, 480), (100, 110, 120)).save(p, format="HEIF", exif=exif.tobytes())
    m = photo_metadata(p, "IMG_2001.HEIC", content=False)
    assert m["make"] == "Apple" and m["taken"] == "2026-09-28T08:15:00"


def test_ocr_ignores_dates_that_look_like_plates():
    from veritas.forensics.ocr import plates
    assert plates([("DE 2026", 0.95), ("30 de septiembre de 2026", 0.9), ("AL1990", 0.9)]) == []
    assert plates([("KX·TR45", 0.95), ("HJ 1234", 0.9)]) == ["KXTR45", "HJ1234"]
