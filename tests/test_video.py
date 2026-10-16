"""Videos: subida por partes, datos del archivo, cuadros clave, alertas y comparación con las fotos."""
import io
import json
import math
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from evidex.forensics import video

pytestmark = pytest.mark.skipif(not video.available(), reason="sin ffmpeg")


def _video_de(img: Image.Image, path: Path, seconds=4, created=None):
    """Video que muestra una imagen fija (con un leve paneo), como un video del daño."""
    src = path.with_suffix(".png")
    img.save(src)
    meta = ["-metadata", f"creation_time={created}"] if created else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(src), "-t", str(seconds), "-r", "10",
                    "-vf", "scale=960:-2,format=yuv420p", "-c:v", "libx264", *meta, str(path)], check=True)
    return path


def _escena():
    from test_views import _escena as e
    return e(21)


def test_datos_y_cuadros(tmp_path):
    p = _video_de(_escena(), tmp_path / "v.mp4", created="2026-09-20T15:00:00Z")
    info = video.probe(p)
    assert info["duration"] >= 3.5 and info["width"] == 960 and info["created"] == "2026-09-20T15:00:00Z"
    fr = video.frames(p, tmp_path / "fr", info["duration"], 4)
    assert len(fr) == 4 and all((tmp_path / "fr" / f["file"]).exists() for f in fr)
    with pytest.raises(ValueError):
        bad = tmp_path / "x.mp4"
        bad.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"0" * 200)
        video.probe(bad)


def _subir(client, url, data: bytes, name="video.mp4", campos=None, headers=None):
    from evidex.web.chunks import CHUNK_MAX
    total = max(1, math.ceil(len(data) / CHUNK_MAX))
    r = None
    for n in range(total):
        form = {"id": "a" * 32, "n": str(n), "total": str(total), "size": str(len(data)), "name": name, **(campos or {}),
                "parte": (io.BytesIO(data[n * CHUNK_MAX:(n + 1) * CHUNK_MAX]), name)}
        r = client.post(url, data=form, content_type="multipart/form-data", headers=headers or {})
    return r


def test_subida_por_partes_valida_cada_trozo(tmp_path):
    from werkzeug.datastructures import MultiDict
    from evidex.web import chunks
    wd = tmp_path / "casos"
    blob = b"\x00" * (chunks.CHUNK_MAX + 10)
    f = lambda n: MultiDict({"id": "b" * 32, "n": str(n), "total": "2", "size": str(len(blob)), "name": "a.mp4"})
    r0 = chunks.receive(wd, "s1", f(0), io.BytesIO(blob[:chunks.CHUNK_MAX]), {".mp4"}, 10 ** 9)
    assert r0 == {"done": False, "next": 1}
    with pytest.raises(chunks.ChunkError):                       # otra persona no puede seguir la subida
        chunks.receive(wd, "s2", f(1), io.BytesIO(blob[chunks.CHUNK_MAX:]), {".mp4"}, 10 ** 9)
    assert chunks.receive(wd, "s1", f(0), io.BytesIO(blob[:chunks.CHUNK_MAX]), {".mp4"}, 10 ** 9)["next"] == 1  # reintento
    r1 = chunks.receive(wd, "s1", f(1), io.BytesIO(blob[chunks.CHUNK_MAX:]), {".mp4"}, 10 ** 9)
    assert r1["done"] and Path(r1["path"]).read_bytes() == blob
    chunks.finish(r1)
    assert not Path(r1["path"]).exists()
    with pytest.raises(chunks.ChunkError):
        chunks.receive(wd, "s1", MultiDict({"id": "c" * 32, "n": "0", "total": "1", "size": "5", "name": "a.exe"}),
                       io.BytesIO(b"12345"), {".mp4"}, 10 ** 9)


def test_video_en_el_caso_alertas_y_comparacion(tmp_path):
    from test_empresas import _app, _login
    from test_views import _girada
    from evidex.claims import service
    app, store, wd = _app(tmp_path)
    c = _login(app, "fabian")
    escena = _escena()
    foto = escena.copy()
    ImageDraw.Draw(foto).ellipse([420, 260, 600, 420], fill=(25, 25, 25))     # daño "agregado" a la foto
    b = io.BytesIO()
    _girada(foto, 1.5).save(b, "JPEG", quality=88)
    b.seek(0)
    r = c.post("/nuevo", data={"numero": "SIN-VID", "fecha_siniestro": "2026-10-01T10:00", "asegurado": "Ana",
                               "fotos": [(b, "foto_daño.jpg")], "cliente": ""}, content_type="multipart/form-data")
    assert r.status_code == 302
    case = service.find_case(wd, "SIN-VID")
    vid = _video_de(escena, tmp_path / "daño.mp4", created="2026-09-20T15:00:00Z").read_bytes()
    with c.session_transaction() as s:
        s["csrf"] = "t"
    r = _subir(c, f"/caso/{case.root.name}/video", vid, "daño.mp4")
    assert r.status_code == 200 and r.get_json()["done"], r.get_data(as_text=True)
    (case.root / service.SNAPSHOT).write_text('{"photos": [], "docs": [], "findings": []}')   # video aún sin analizar
    assert c.get(f"/caso/{case.root.name}?tab=fotos").status_code == 200
    service.analyze_claim(case)
    snap = service.snapshot(case)
    rules = {f["rule"] for f in snap["findings"]}
    assert "video_before_claim" in rules and "photo_differs_from_video" in rules
    assert snap["videos"][0]["frames"] and snap["videos"][0]["recorded"].startswith("2026-09-20")
    page = c.get(f"/caso/{case.root.name}?tab=fotos").get_data(as_text=True)
    assert "<video" in page and "Cuadros clave" in page
    vd = snap["videos"][0]["digest"]
    fr = snap["videos"][0]["frames"][0]["file"]
    assert c.get(f"/caso/{case.root.name}/video/{vd}/cuadro/{fr}").mimetype == "image/jpeg"
    assert c.get(f"/caso/{case.root.name}/video/{vd}/cuadro/..%2fcase.json").status_code == 404
    assert c.get(f"/caso/{case.root.name}/archivo/{vd}?mini=1").mimetype == "image/jpeg"
    resumen = c.get(f"/caso/{case.root.name}").get_data(as_text=True)
    assert "Comparar con el video" in resumen
    import re
    url = re.search(r'href="(/caso/[^"]+/comparar-video/[0-9a-f]{64}/[0-9a-f]{64}\.png)"', resumen).group(1)
    assert c.get(url).mimetype == "image/png"
    linea = c.get(f"/caso/{case.root.name}?tab=linea").get_data(as_text=True)
    assert "Video daño.mp4" in linea or "Video da" in linea


def test_portal_recibe_video(tmp_path):
    from test_empresas import _app, _login
    from evidex.claims import service
    from evidex.portal import links
    app, store, wd = _app(tmp_path)
    c = _login(app, "fabian")
    b = io.BytesIO()
    _escena().save(b, "JPEG")
    b.seek(0)
    c.post("/nuevo", data={"numero": "SIN-PV", "fecha_siniestro": "2026-10-01T10:00", "asegurado": "Ana",
                           "fotos": [(b, "f.jpg")], "cliente": ""}, content_type="multipart/form-data")
    case = service.find_case(wd, "SIN-PV")
    token = links.create_link(case, actor="fabian")["token"]
    p = app.test_client()
    p.get(f"/c/{token}")
    with p.session_transaction() as s:
        s["csrf"] = "t"
    vid = _video_de(_escena(), tmp_path / "v.mov", 3).read_bytes()
    r = _subir(p, f"/c/{token}/video", vid, "v.mov", {"titulo": ""}, {"X-CSRF-Token": "t"})
    assert r.status_code == 400 and "título" in r.get_json()["error"]
    r = _subir(p, f"/c/{token}/video", vid, "v2.mov", {"titulo": "Daño lateral"}, {"X-CSRF-Token": "t"})
    assert r.status_code == 200 and r.get_json()["tipo"] == "video", r.get_data(as_text=True)
    assert any(e["data"].get("note") == "video" for e in case.ledger.entries() if e["action"] == "evidence_added")
