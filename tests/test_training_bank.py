"""Enseñar al modelo: marcar fotos, calcular la zona con la original, exportar para Kaggle, permisos y borrado."""
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from helpers import ROOT, textured_image
from evidex.claims import service
from evidex.forensics import training_bank as TB


def _jpeg(img, q=88) -> bytes:
    b = io.BytesIO()
    img.save(b, "JPEG", quality=q)
    return b.getvalue()


def _pair(tmp_path):
    """Original y editada (un parche cambiado en 300..420 x 200..300), cada una con su compresión."""
    orig = textured_image(7, 960, 720)
    ed = orig.copy()
    ed.paste(textured_image(99, 120, 100), (300, 200))
    po, pe = tmp_path / "orig.jpg", tmp_path / "editada.jpg"
    po.write_bytes(_jpeg(orig, 92))
    pe.write_bytes(_jpeg(ed, 75))
    return po, pe


def test_change_mask_finds_the_edited_zone(tmp_path):
    po, pe = _pair(tmp_path)
    m = np.asarray(TB.change_mask(po, pe)) > 127
    assert m.shape == (720, 960)
    inside = m[210:290, 310:410].mean()
    outside = np.concatenate([m[:150].ravel(), m[400:].ravel(), m[:, :200].ravel()]).mean()
    assert inside > .9 and outside < .01
    # rehecha completa (como ChatGPT): todo cambia un poco y una zona mucho -> toda la foto
    o = np.asarray(Image.open(po), np.float32)
    regen = np.clip((o - 128) * 1.5 + 128 + np.random.RandomState(3).normal(0, 25, o.shape), 0, 255).astype(np.uint8)
    pr = tmp_path / "rehecha.jpg"
    Image.fromarray(regen).save(pr, "JPEG", quality=85)
    assert (np.asarray(TB.change_mask(po, pr)) > 127).all()
    # la misma foto con otra compresión: no hay cambio, no se inventa una zona
    po2 = tmp_path / "otra_compresion.jpg"
    po2.write_bytes(_jpeg(Image.open(po), 60))
    assert TB.change_mask(po, po2) is None
    # recortada unos píxeles abajo, como la edición de Samsung: se busca dónde calza y la zona sigue bien
    pc = tmp_path / "editada_recortada.jpg"
    Image.open(pe).crop((0, 0, 960, 690)).save(pc, "JPEG", quality=85)
    mc = np.asarray(TB.change_mask(po, pc)) > 127
    assert mc.shape == (690, 960) and mc[210:290, 310:410].mean() > .9 and mc[:150].mean() < .01
    # recortada a otra forma muy distinta: no se adivina
    crop = tmp_path / "recorte.jpg"
    Image.open(pe).crop((0, 0, 700, 700)).save(crop, "JPEG")
    assert TB.change_mask(po, crop) is None


def _client(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/usuarios", data={"usuario": "admin", "nombre": "Admin", "rol": "administrador", "clave": "clave-segura-001"})
    c.post("/usuarios", data={"usuario": "ana", "nombre": "Ana", "rol": "analista", "clave": "clave-segura-002"})
    c.post("/usuarios", data={"usuario": "pepe", "nombre": "Pepe", "rol": "perito", "clave": "clave-segura-003",
                              "empresa": "Peritos SA"})
    return c


def _login(c, usuario, clave):
    c.post("/salir")
    assert c.post("/ingresar", data={"usuario": usuario, "clave": clave}).status_code == 302


def test_mark_export_permissions_and_purge(tmp_path):
    c = _client(tmp_path)
    _login(c, "admin", "clave-segura-001")
    po, pe = _pair(tmp_path)
    hs = [(open(po, "rb"), "auto_original.jpg"), (open(pe, "rb"), "auto_editada.jpg")]
    assert c.post("/nuevo", data={"numero": "SIN-2026-9200", "fecha_siniestro": "2026-10-01T10:00", "fotos": hs},
                  content_type="multipart/form-data").status_code == 302
    [h.close() for h, _ in hs]
    case = service.find_case(tmp_path / "casos", "SIN-2026-9200")
    cid = case.root.name
    dig = {e["data"]["original_name"]: e["subject"] for e in case.active_evidence()}
    d_ed, d_or = dig["auto_editada.jpg"], dig["auto_original.jpg"]
    assert "Enseñar al modelo" in c.get(f"/caso/{cid}?tab=fotos").get_data(as_text=True)
    url = f"/caso/{cid}/archivo/{d_ed}/entrenar"
    base = {"etiqueta": "editada", "origen": "prueba", "app": "Samsung Galaxy AI", "alcance": "zona", "original": d_or}
    # sin confirmar el uso para entrenar, no se guarda
    c.post(url, data=base)
    bank = TB.Bank(tmp_path / "casos")
    assert bank.entries() == []
    # una original que no es del caso: no
    c.post(url, data={**base, "confirmo": "si", "original": "f" * 64})
    assert bank.entries() == []
    r = c.post(url, data={**base, "confirmo": "si", "nota": "borré un rayón"}, follow_redirects=True)
    assert "Zona calculada con la original" in r.get_data(as_text=True)
    e = bank.get(d_ed)
    assert e["mascara"] and 0 < e["cobertura"] < .05 and e["app"] == "Samsung Galaxy AI" and e["actor"] == "Admin"
    assert e["original"] == d_or and e["caso"] == "SIN-2026-9200"
    # recalcular la zona con la original (que está en el caso): misma zona, queda la constancia
    assert "Zonas recalculadas: 1" in c.post("/entrenamiento/recalcular", follow_redirects=True).get_data(as_text=True)
    e2 = bank.get(d_ed)
    assert e2["recalculada"] and e2["mascara"] and abs(e2["cobertura"] - e["cobertura"]) < .005 and e2["app"] == e["app"]
    assert any(x["action"] == "training_marked" and x["subject"] == d_ed for x in case.ledger.entries())
    assert case.verify_evidence() == (True, [])
    assert "Foto marcada para enseñar al modelo" in c.get(f"/caso/{cid}?tab=historial").get_data(as_text=True)
    # la original, marcada sin editar
    c.post(f"/caso/{cid}/archivo/{d_or}/entrenar", data={"etiqueta": "original", "origen": "prueba", "confirmo": "si"})
    s = bank.summary()
    assert s["total"] == 2 and s["editadas"] == 1 and s["con_zona"] == 1 and s["sin_zona"] == 0
    page = c.get("/entrenamiento").get_data(as_text=True)
    assert "auto_editada.jpg" in page and "Exportar para entrenar" in page
    assert c.get(f"/entrenamiento/{d_ed}.jpg").mimetype == "image/jpeg"
    # exportar: formato del notebook y licencia que el entrenamiento acepta
    z = zipfile.ZipFile(io.BytesIO(c.get("/entrenamiento/exportar").data))
    names = set(z.namelist())
    assert {f"editadas/{d_ed}.jpg", f"mascaras/{d_ed}.png", f"originales/{d_or}.jpg", "licencia.txt", "banco.csv"} <= names
    out = tmp_path / "export"
    z.extractall(out)
    sys.path.insert(0, str(ROOT / "training"))
    import datos
    filas = datos.manifiesto_propias(out)
    assert {(Path(f["ruta"]).name, f["etiqueta"], bool(f["mascara"])) for f in filas} == {
        (f"{d_or}.jpg", 0, False), (f"{d_ed}.jpg", 1, True)}
    assert all(datos.licencia_permitida(f["licencia"]) for f in filas)
    # el analista marca pero no exporta; el perito no entra
    _login(c, "ana", "clave-segura-002")
    assert c.get("/entrenamiento").status_code == 200
    assert c.get("/entrenamiento/exportar").status_code == 403
    _login(c, "pepe", "clave-segura-003")
    assert c.get("/entrenamiento").status_code == 403
    assert c.post(url, data={**base, "confirmo": "si"}).status_code == 403
    # una editada sin original ni «completa» queda aparte: el entrenamiento no la usa
    _login(c, "admin", "clave-segura-001")
    c.post(url, data={"etiqueta": "editada", "origen": "prueba", "alcance": "zona", "confirmo": "si"})
    assert not bank.get(d_ed)["mascara"] and bank.summary()["sin_zona"] == 1
    z = zipfile.ZipFile(io.BytesIO(c.get("/entrenamiento/exportar").data))
    assert f"editadas_sin_zona/{d_ed}.jpg" in z.namelist() and f"mascaras/{d_ed}.png" not in z.namelist()
    # eliminar definitivamente del caso también lo saca del banco y borra la copia
    c.post(f"/caso/{cid}/archivo/{d_ed}/quitar", data={"motivo": "Se agregó por error"})
    c.post(f"/caso/{cid}/archivo/{d_ed}/eliminar", data={"motivo": "Datos de prueba", "confirmar": "ELIMINAR"})
    assert bank.get(d_ed) is None and not list(bank.fotos.glob(d_ed + ".*"))
    assert bank.get(d_or) is not None
    # quitar a mano desde el banco
    c.post(f"/entrenamiento/{d_or}/quitar", data={"motivo": "x"})
    assert bank.entries() == [] and not list(bank.fotos.glob("*"))
    log = [json.loads(x) for x in bank.log.read_text().splitlines()]
    assert [x["accion"] for x in log].count("quitar") == 2


def test_model_mistake_is_recorded(tmp_path):
    po, pe = _pair(tmp_path)
    bank = TB.Bank(tmp_path)
    d = "a" * 64
    r = bank.mark(pe, d, etiqueta="editada", origen="prueba", actor="x", caso="C", nombre="f.jpg",
                  modelo={"score": .80, "threshold": .9995, "model": "m1"})
    assert r["modelo_acerto"] is False and bank.summary()["errores_modelo"] == 1
    r = bank.mark(pe, d, etiqueta="original", origen="prueba", actor="x", caso="C", nombre="f.jpg",
                  modelo={"score": .80, "threshold": .9995})
    assert r["modelo_acerto"] is True and len(bank.entries()) == 1
    for bad in ({"etiqueta": "quizas", "origen": "prueba"}, {"etiqueta": "editada", "origen": "asegurado"}):
        try:
            bank.mark(pe, d, actor="x", caso="C", nombre="f.jpg", **bad)
            raise AssertionError("debía rechazar")
        except ValueError:
            pass
    try:
        bank.mark(pe, d, etiqueta="editada", origen="prueba", actor="x", caso="C", nombre="f.heic")
        raise AssertionError("debía rechazar HEIC")
    except ValueError:
        pass
