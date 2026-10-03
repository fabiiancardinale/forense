"""Nuevas pruebas de fraude en fotos: grano del sensor, recortes, iPhone sin nota del fabricante,
tamaños de IA, fotos espejadas, mismo teléfono entre siniestros y lista de pruebas por foto."""
import io

import numpy as np
from PIL import Image, ImageOps

from helpers import textured_image
from evidex.claims import photo_checks
from evidex.claims.analysis import Photo, analyze, photo_metadata, photo_set_findings, registry_findings
from evidex.forensics.image_content import ela_map, noise_inconsistency, noise_map

DECL = {"numero": "SIN-T", "fecha_siniestro": "2026-09-20T18:30:00", "rut": "11.111.111-1"}


def _jpeg(img, path, exif=None, quality=92):
    kw = {"quality": quality}
    if exif is not None:
        kw["exif"] = exif
    img.save(path, "JPEG", **kw)
    return path


def _camera_exif(make="samsung", model="SM-S921B", when="2026:09:20 18:40:00", dims=None, serial=None, uid=None):
    e = Image.Exif()
    e[0x010F], e[0x0110], e[0x0132] = make, model, when
    sub = {0x9003: when, 0x9004: when, 0x829A: 1 / 120, 0x829D: 1.8, 0x8827: 100}
    if dims:
        sub[0xA002], sub[0xA003] = dims
    if serial:
        sub[0xA431] = serial
    if uid:
        sub[0xA420] = uid
    e[0x8769] = sub
    return e


def _photo(path, name=None, digest="a" * 64):
    meta = photo_metadata(path, name or path.name, content=False)
    meta["content"] = {}
    meta["received"] = "2026-09-21T10:00:00"
    return Photo(digest, name or path.name, meta, meta.get("taken") or meta["received"])


def test_noise_inconsistency_finds_patch_with_other_grain(tmp_path):
    base = textured_image(3, 1280, 960)
    assert noise_inconsistency(base) == {}
    a = np.asarray(base, np.float32).copy()
    a[300:620, 400:820] += np.random.RandomState(3).normal(0, 14, (320, 420, 3))   # zona pegada con otro grano
    fake = _jpeg(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), tmp_path / "f.jpg")
    region = noise_inconsistency(Image.open(fake))["region"]
    x0, y0, x1, y1 = region["bbox"]
    assert x0 < 450 and y0 < 350 and x1 > 780 and y1 > 580 and region["kind"] == "más"
    assert ela_map(fake)[:4] == b"\x89PNG" and noise_map(fake)[:4] == b"\x89PNG"


def test_resized_and_iphone_without_makernote(tmp_path):
    img = textured_image(1, 800, 600)
    p = _jpeg(img, tmp_path / "IMG_1.jpg", _camera_exif(dims=(4000, 3000)))
    rules = {f.rule for f in analyze(DECL, "d:1", [_photo(p)], [])}
    assert "resized_after_capture" in rules and "makernote_missing" not in rules
    p2 = _jpeg(img, tmp_path / "IMG_2.jpg", _camera_exif("Apple", "iPhone 15", dims=(800, 600)))
    rules = {f.rule for f in analyze(DECL, "d:1", [_photo(p2)], [])}
    assert "makernote_missing" in rules and "resized_after_capture" not in rules


def test_ai_size_and_edit_filename(tmp_path):
    p = tmp_path / "danio_editado.png"
    textured_image(2, 1024, 1024).save(p)
    rules = {f.rule for f in analyze(DECL, "d:1", [_photo(p)], [])}
    assert {"ai_dimensions", "edit_filename"} <= rules


def test_mirrored_and_duplicate_inside_claim(tmp_path):
    img = textured_image(5, 900, 600)
    a = _photo(_jpeg(img, tmp_path / "trasera.jpg", _camera_exif()), digest="1" * 64)
    b = _photo(_jpeg(ImageOps.mirror(img), tmp_path / "otro_lado.jpg", _camera_exif()), digest="2" * 64)
    c = _photo(_jpeg(textured_image(9, 900, 600), tmp_path / "frente.jpg", _camera_exif("Apple", "iPhone 13")),
               digest="3" * 64)
    rules = [f.rule for f in photo_set_findings([a, b, c])]
    assert "mirrored_in_claim" in rules and "multiple_devices" in rules


def test_reuse_detected_when_mirrored_or_by_unique_id_and_same_phone(tmp_path):
    img = textured_image(6, 900, 600)
    p = _photo(_jpeg(ImageOps.mirror(img), tmp_path / "x.jpg", _camera_exif(serial="R58N91ABC", uid="A1B2C3D4E5")))
    from evidex.claims.analysis import dhash
    reg = [{"type": "claim", "claim": "SIN-OTRO", "rut": "22.222.222-2"},
           {"type": "photo", "claim": "SIN-OTRO", "photo": "vieja.jpg", "sha256": "f" * 64, "dhash": dhash(img)}]
    found = registry_findings(p, DECL, reg, ["x:1"])
    assert found and found[0].rule == "reused_photo" and "espejada" in found[0].summary
    # foto editada (otro hash), pero con el mismo identificador único y el mismo teléfono
    reg = [{"type": "claim", "claim": "SIN-OTRO", "rut": "22.222.222-2"},
           {"type": "photo", "claim": "SIN-OTRO", "photo": "vieja.jpg", "sha256": "f" * 64, "dhash": "0" * 16,
            "uid": "A1B2C3D4E5", "serial": "R58N91ABC"}]
    rules = {f.rule for f in registry_findings(p, DECL, reg, ["x:1"])}
    assert rules == {"reused_photo", "same_device_other_claim"}
    # mismo teléfono del mismo asegurado: normal
    reg[0]["rut"] = DECL["rut"]
    assert {f.rule for f in registry_findings(p, DECL, reg, ["x:1"])} == {"reused_photo"}


def test_portal_file_date_before_photo_date(tmp_path):
    p = _photo(_jpeg(textured_image(4, 640, 480), tmp_path / "f.jpg", _camera_exif(when="2026:09:20 18:40:00")))
    p.meta["portal"] = {"title": "Trasera", "last_modified": 1_757_000_000_000}        # septiembre 2025
    assert "saved_before_taken" in {f.rule for f in analyze(DECL, "d:1", [p], [])}
    p.meta["portal"]["last_modified"] = 1_790_000_000_000                             # elegido después: normal
    assert "saved_before_taken" not in {f.rule for f in analyze(DECL, "d:1", [p], [])}


def test_checklist_lists_every_test_with_result(tmp_path):
    img = textured_image(7, 800, 600)
    p = _photo(_jpeg(img, tmp_path / "IMG_9.jpg", _camera_exif(dims=(4000, 3000))))
    found = analyze(DECL, "d:1", [p], [])
    checks = photo_checks.run(p.meta, found)
    by = {c["name"]: c for c in checks}
    assert len(checks) == len(photo_checks.CHECKS)
    assert by["Tamaño original de la cámara (recortes)"]["status"] == "alerta"
    assert by["Nota del fabricante (iPhone)"]["status"] == "no aplica"
    assert by["Partes clonadas dentro de la foto"]["status"] == "ok"
    s = photo_checks.summary(checks)
    assert s["alert"] >= 1 and s["ok"] + s["alert"] + s["na"] == s["total"]


def test_photo_check_page_shows_tests_and_maps(tmp_path):
    from helpers import web_client
    c = web_client(tmp_path)
    buf = io.BytesIO()
    textured_image(8, 800, 600).save(buf, "JPEG", quality=90)
    page = c.post("/foto", data={"fotos": (io.BytesIO(buf.getvalue()), "x.jpg")},
                  content_type="multipart/form-data").get_data(as_text=True)
    assert "Pruebas aplicadas" in page and "Grano del sensor parejo" in page and "Mapa ELA" in page


def test_visible_ai_label_and_crop_that_hides_it(tmp_path):
    from evidex.forensics.derived import ai_label, crop_relation, odd_ratio
    assert ai_label("CTRL | ALT | Contenido generado por IA") == "Contenido generado por IA"
    assert ai_label("AI-generated content") and not ai_label("KXTR45 | Taller Central")
    full = textured_image(11, 1200, 1600)
    a = _jpeg(full, tmp_path / "WhatsApp Image 1.jpeg")
    cut = full.crop((0, 0, 1200, 1420)).resize((1352, 1600))          # se quita la franja de abajo con la marca
    b = _jpeg(cut, tmp_path / "WhatsApp Image 2.jpeg", quality=80)
    rel = crop_relation(a, b)
    assert rel and rel["base"] == "a" and set(rel["cut"]) == {"abajo"}
    assert crop_relation(a, _jpeg(textured_image(12, 1200, 1600), tmp_path / "otra.jpg")) is None
    assert odd_ratio(1352, 1600) and odd_ratio(1200, 1600) is None and odd_ratio(1080, 1920) is None

    pa, pb = _photo(a, digest="a" * 64), _photo(b, digest="b" * 64)
    pa.path, pb.path = a, b
    pa.meta["content"] = {"ocr": {"text": "CTRL | Contenido generado por IA", "plates": []}}
    pb.meta["content"] = {"ocr": {"text": "CTRL", "plates": []}}
    rules = [f.rule for f in analyze(DECL, "d:1", [pa, pb], [])]
    assert "ai_label_visible" in rules and "ai_mark_cropped" in rules and "odd_ratio" in rules
    assert "duplicate_in_claim" not in rules
    pa.meta["content"]["ocr"]["text"] = "CTRL"                          # sin marca: solo un recorte
    rules = [f.rule for f in photo_set_findings([pa, pb])]
    assert rules == ["cropped_in_claim"]
