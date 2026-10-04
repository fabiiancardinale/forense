"""Lectura completa de metadatos: Samsung (SEF), XMP/IPTC de IA, PNG de generadores, fechas y explicaciones."""
import io
import json
import struct

from PIL import Image

from helpers import textured_image
from evidex.claims.analysis import Photo, analyze, photo_metadata
from evidex.claims.guide import explain
from evidex.forensics.deep_meta import read_all

DECL = {"numero": "SIN-M", "fecha_siniestro": "2026-10-04T10:00:00"}


def _exif(when="2026:10:04 12:19:56", make="samsung", model="SM-S938B"):
    e = Image.Exif()
    e[0x010F], e[0x0110], e[0x0132] = make, model, when
    e[0x8769] = {0x9003: when, 0x9004: when}
    return e


def _sef(entries: dict) -> bytes:
    """Sección SEF de Samsung, como la escribe el teléfono al final del JPEG."""
    blocks, table, data = [], [], b""
    for name, value in entries.items():
        blk = b"\x00\x00\x01\x0a" + struct.pack("<I", len(name)) + name.encode() + value
        blocks.append(blk)
    offsets, pos = [], 0
    for blk in blocks:
        offsets.append(pos)
        data += blk
        pos += len(blk)
    total = len(data)
    head = b"SEFH" + struct.pack("<I", 106) + struct.pack("<I", len(blocks))
    for blk, off in zip(blocks, offsets):
        head += b"\x00\x00\x01\x0a" + struct.pack("<II", total - off, len(blk))
    return data + head + struct.pack("<I", len(head)) + b"SEFT"


def _samsung_jpeg(path, sef_entries, when="2026:10:04 12:19:56"):
    b = io.BytesIO()
    textured_image(2, 800, 600).save(b, "JPEG", quality=92, exif=_exif(when))
    path.write_bytes(b.getvalue() + _sef(sef_entries))
    return path


def _photo(path):
    m = photo_metadata(path, path.name, content=False)
    m["content"], m["received"] = {}, "2026-10-04T13:00:00"
    return Photo("a" * 64, path.name, m, m.get("taken") or m["received"], path)


def test_samsung_galaxy_ai_crop_and_watermark(tmp_path):
    re_edit = {"clipInfoValue": json.dumps({"mWidth": 1, "mHeight": 0.958}),
               "toneValue": json.dumps({"brightness": 100, "contrast": 120}),
               "portraitEffectValue": json.dumps({"waterMarkRemoved": True}), "isScaleAI": False}
    p = _samsung_jpeg(tmp_path / "flor.jpg", {
        "Image_UTC_Data": b"1791127196246",
        "PEg_Info": json.dumps({"genImageVersion": "v1", "genAIType": 1}).encode(),
        "PhotoEditor_Re_Edit_Data": json.dumps(re_edit).encode()})
    r = read_all(p)
    assert any("Galaxy AI" in a for a in r["ai"])
    assert any("Recorte" in e and "96%" in e for e in r["edits"]) and any("contrast" in e for e in r["edits"])
    assert r["flags"]["ai_watermark_removed"] and r["dates"]["Samsung: hora UTC"] == "2026-10-04T15:19:56"
    rules = {f.rule for f in analyze(DECL, "d:1", [_photo(p)], [])}
    assert {"ai_edited", "ai_watermark_removed", "phone_edit"} <= rules
    assert "meta_dates_conflict" not in rules                       # 15:19 UTC y 12:19 hora de Chile: coinciden


def test_samsung_utc_contradicts_changed_exif_date(tmp_path):
    p = _samsung_jpeg(tmp_path / "f.jpg", {"Image_UTC_Data": b"1791127196246"}, when="2026:09:20 18:30:00")
    found = [f for f in analyze(DECL, "d:1", [_photo(p)], []) if f.rule == "meta_dates_conflict"]
    assert found and "Samsung: hora UTC" in found[0].summary


def test_xmp_digital_source_type_and_png_generator(tmp_path):
    xmp = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
           '<rdf:Description xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
           'Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia" '
           'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:CreatorTool="Google Photos Magic Editor"/></rdf:RDF></x:xmpmeta>')
    p = tmp_path / "pixel.jpg"
    textured_image(3, 640, 480).save(p, "JPEG", quality=90, exif=_exif(make="Google", model="Pixel 9"), xmp=xmp.encode())
    r = read_all(p)
    assert any("partes generadas o cambiadas por IA" in a for a in r["ai"])
    assert "ai_edited" in {f.rule for f in analyze(DECL, "d:1", [_photo(p)], [])}
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "a car with a dent, Steps: 30, Sampler: Euler")
    q = tmp_path / "sd.png"
    textured_image(4, 512, 512).save(q, "PNG", pnginfo=info)
    assert any("generador" in a for a in read_all(q)["ai"])


def test_plain_camera_photo_has_no_ai_or_edits(tmp_path):
    p = tmp_path / "cam.jpg"
    textured_image(5, 640, 480).save(p, "JPEG", quality=93, exif=_exif(make="Apple", model="iPhone 15"))
    r = read_all(p)
    assert not r["ai"] and not r["edits"] and r["exif"]["Principal: Make"] == "Apple"
    assert not {"ai_edited", "phone_edit", "meta_dates_conflict"} & {f.rule for f in analyze(DECL, "d:1", [_photo(p)], [])}


def test_every_alert_explains_what_why_and_what_to_do():
    for rule, sev in (("ai_edited", "alta"), ("phone_edit", "media"), ("meta_dates_conflict", "media"),
                      ("no_metadata", "baja"), ("una_regla_nueva", "media")):
        x = explain(rule, sev)
        assert x["why"], rule
    assert explain("ai_edited", "alta")["what"] and explain("ai_edited", "alta")["todo"]


def test_case_shows_explanations_and_full_metadata_page(tmp_path):
    from helpers import web_client
    c = web_client(tmp_path)
    p = _samsung_jpeg(tmp_path / "flor.jpg", {"PEg_Info": json.dumps({"genAIType": 1}).encode()})
    with open(p, "rb") as fh:
        r = c.post("/nuevo", data={"numero": "SIN-M1", "fecha_siniestro": "2026-10-04T10:00",
                                    "fotos": [(fh, "flor.jpg")]}, content_type="multipart/form-data")
    assert r.status_code == 302
    page = c.get("/caso/SIN-M1?tab=fotos").get_data(as_text=True)
    assert "Editada con IA según el propio archivo" in page and "Por qué es alta" in page and "Qué hacer" in page
    import re
    meta_url = re.search(r'href="(/caso/SIN-M1/archivo/[0-9a-f]{64}/metadatos)"', page).group(1)
    md = c.get(meta_url).get_data(as_text=True)
    assert "Samsung: datos propios del teléfono" in md and "Galaxy AI" in md and "EXIF (todas las carpetas)" in md
    resumen = c.get("/caso/SIN-M1").get_data(as_text=True)
    assert "por qué es alta" in resumen.lower()


def test_case_with_cropped_pair_saves_cache_and_reanalyzes(tmp_path):
    """Regresión: la caché de pares de fotos fallaba al guardar booleanos de numpy (TypeError) y el análisis no terminaba."""
    from helpers import web_client
    c = web_client(tmp_path)
    full = textured_image(8, 1200, 1600)
    a, b = io.BytesIO(), io.BytesIO()
    full.save(a, "JPEG", quality=92)
    full.crop((0, 0, 1200, 1400)).resize((1371, 1600)).save(b, "JPEG", quality=80)
    r = c.post("/nuevo", data={"numero": "SIN-P1", "fecha_siniestro": "2026-10-04T10:00",
                                "fotos": [(io.BytesIO(a.getvalue()), "completa.jpg"), (io.BytesIO(b.getvalue()), "recorte.jpg")]},
               content_type="multipart/form-data")
    assert r.status_code == 302
    cache = tmp_path / "casos" / "SIN-P1" / "analisis_pares.json"
    assert cache.exists() and json.loads(cache.read_text())["pairs"]
    page = c.post("/caso/SIN-P1/analizar", follow_redirects=True).get_data(as_text=True)
    assert "Análisis actualizado" in page and "recorte" in page.lower()


def test_whatsapp_copy_inherits_ai_mark_in_claim_and_across_claims(tmp_path):
    """La foto editada con Galaxy AI tiene marcas; su copia por WhatsApp no. La copia hereda la alerta."""
    from evidex.claims.analysis import photo_set_findings, registry_findings, update_registry
    orig = _samsung_jpeg(tmp_path / "regfri.jpg", {"PEg_Info": json.dumps({"genAIType": 1}).encode()})
    wa = tmp_path / "WhatsApp Image 1.jpeg"
    Image.open(orig).convert("RGB").resize((600, 450)).save(wa, "JPEG", quality=70)   # sin metadatos, achicada
    po, pw = _photo(orig), _photo(wa)
    po.digest, pw.digest = "a" * 64, "b" * 64
    assert not pw.meta["deep"]["ai"]                                   # la copia ya no dice nada de IA
    found = [f for f in photo_set_findings([po, pw]) if f.rule == "copy_of_ai_photo"]
    assert found and "regfri.jpg" in found[0].summary and "Galaxy AI" in found[0].summary
    reg = tmp_path / "registro.jsonl"
    update_registry(reg, "SIN-A", [po])
    from evidex.claims.analysis import load_registry
    rows = load_registry(reg)
    assert rows[0]["ai"]
    rules = [f.rule for f in registry_findings(pw, {"numero": "SIN-B", "rut": ""}, rows, ["x:1"])]
    assert rules == ["reused_photo", "copy_of_ai_photo"]
