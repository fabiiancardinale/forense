"""Comparar fotos alineándolas punto a punto: una zona cambiada aparece; un giro o una recompresión, no."""
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from evidex.forensics import views

pytestmark = pytest.mark.skipif(not views.available(), reason="sin OpenCV")


def _escena(seed=3, w=1200, h=900):
    """Una escena con estructura (rectángulos, líneas, textura), como un estacionamiento."""
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (w, h), (120, 124, 130))
    d = ImageDraw.Draw(im)
    for _ in range(140):
        x, y = rng.integers(0, w), rng.integers(0, h)
        c = tuple(int(v) for v in rng.integers(20, 235, 3))
        if rng.random() < .5:
            d.rectangle([x, y, x + rng.integers(15, 120), y + rng.integers(15, 120)], fill=c)
        else:
            d.line([x, y, x + rng.integers(-200, 200), y + rng.integers(-200, 200)], fill=c, width=int(rng.integers(2, 8)))
    noise = rng.normal(0, 6, (h, w, 3))
    return Image.fromarray(np.clip(np.asarray(im, float) + noise, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(.8))


def _save(im, path, q=88):
    im.save(path, "JPEG", quality=q)
    return path


def _girada(im, ang=2.5):
    w, h = im.size
    return im.rotate(ang, resample=Image.BICUBIC).crop((int(w * .07), int(h * .07), int(w * .93), int(h * .93)))


def test_zona_cambiada_en_version_girada(tmp_path):
    base = _escena()
    a = _save(base, tmp_path / "original.jpg")
    edit = base.copy()
    ImageDraw.Draw(edit).ellipse([700, 380, 860, 520], fill=(40, 40, 44))            # "daño" agregado
    b = _save(_girada(edit), tmp_path / "editada.jpg", q=75)
    r = views.compare(a, b)
    assert r and r["kind"] == "misma_toma" and r["zones"]
    x0, y0, x1, y1 = r["zones"][0]["box"]
    assert x0 < 860 / 1200 and x1 > 700 / 1200 and y0 < 520 / 900 and y1 > 380 / 900
    png = views.side_by_side(a, b, r["zones"])
    assert Image.open(io.BytesIO(png)).width > 1000


def test_sin_edicion_no_hay_zonas(tmp_path):
    base = _escena(5)
    a = _save(base, tmp_path / "a.jpg")
    b = _save(_girada(base, -2).resize((700, 530)), tmp_path / "b.jpg", q=70)       # girada, achicada, recomprimida
    r = views.compare(a, b)
    assert r and r["zones"] == []
    c = _save(_escena(9), tmp_path / "otra.jpg")
    assert views.compare(a, c) is None                                                # otra escena


def test_en_el_analisis_del_caso(tmp_path):
    from evidex.claims.analysis import Photo, photo_metadata, photo_set_findings
    base = _escena(7)
    ev = tmp_path / "evidence"
    ev.mkdir()
    edit = base.copy()
    ImageDraw.Draw(edit).rectangle([300, 300, 460, 420], fill=(200, 30, 30))
    ps = []
    for name, im in (("foto_1.jpg", base), ("foto_2.jpg", _girada(edit))):
        p = _save(im, ev / name)
        m = photo_metadata(p, name, content=False)
        m["content"] = {}
        ps.append(Photo(name.ljust(64, "0")[:64].replace(".", "0"), name, m, "2026-10-01T10:00:00", p))
    found = [f for f in photo_set_findings(ps) if f.rule == "changed_between_versions"]
    assert found and "Comparar las dos fotos" in found[0].summary


def test_boton_comparar_en_el_resumen(tmp_path):
    import re
    from test_empresas import PW, _app, _login
    from evidex.claims import service
    app, store, wd = _app(tmp_path)
    c = _login(app, "fabian")
    base = _escena(11)
    edit = base.copy()
    ImageDraw.Draw(edit).ellipse([500, 300, 680, 460], fill=(30, 30, 30))
    files = []
    for name, im in (("foto_1.jpg", base), ("foto_2.jpg", _girada(edit))):
        b = io.BytesIO()
        im.save(b, "JPEG", quality=85)
        b.seek(0)
        files.append((b, name))
    r = c.post("/nuevo", data={"numero": "SIN-V1", "fecha_siniestro": "2026-10-01T10:00", "asegurado": "Ana",
                               "fotos": files, "cliente": ""}, content_type="multipart/form-data")
    assert r.status_code == 302
    cid = service.find_case(wd, "SIN-V1").root.name
    service.analyze_claim(service.find_case(wd, "SIN-V1"))
    page = c.get(f"/caso/{cid}").get_data(as_text=True)
    assert "Comparar las dos fotos" in page
    url = re.search(r'href="(/caso/[^"]+/comparar/[0-9a-f]{64}/[0-9a-f]{64}\.png)"', page).group(1)
    r = c.get(url)
    assert r.status_code == 200 and r.mimetype == "image/png"
