"""Eliminación definitiva: solo archivos ya quitados, solo administrador o jefe, con motivo y confirmación;
el archivo se borra pero la cadena de custodia sigue íntegra y deja constancia."""
import io
import json
import subprocess
import sys
import zipfile

from helpers import textured_image
from evidex.claims import analysis, service


def _login(c, usuario, clave):
    c.post("/salir")
    assert c.post("/ingresar", data={"usuario": usuario, "clave": clave}).status_code == 302


def _client(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/usuarios", data={"usuario": "admin", "nombre": "Admin", "rol": "administrador", "clave": "clave-segura-001"})
    c.post("/usuarios", data={"usuario": "ana", "nombre": "Ana", "rol": "analista", "clave": "clave-segura-002"})
    _login(c, "admin", "clave-segura-001")
    return c


def test_purge_deletes_file_keeps_custody_and_registry_clean(tmp_path):
    c = _client(tmp_path)
    fotos = []
    for i in range(2):
        p = tmp_path / f"foto_{i}.jpg"
        textured_image(10 + i, 800, 600).save(p, "JPEG", quality=90)
        fotos.append(p)
    hs = [(open(p, "rb"), p.name) for p in fotos]
    r = c.post("/nuevo", data={"numero": "SIN-2026-9100", "fecha_siniestro": "2026-10-01T10:00", "fotos": hs},
               content_type="multipart/form-data")
    [h.close() for h, _ in hs]
    assert r.status_code == 302
    case = service.find_case(tmp_path / "casos", "SIN-2026-9100")
    cid = case.root.name
    digest = next(e["subject"] for e in case.active_evidence() if e["data"]["original_name"] == "foto_0.jpg")
    reg = tmp_path / "casos" / "registro.jsonl"
    assert any(json.loads(x).get("sha256") == digest for x in reg.read_text().splitlines())
    url = f"/caso/{cid}/archivo/{digest}/eliminar"
    # todavía activa: no se puede eliminar sin quitarla antes
    c.post(url, data={"motivo": "Datos de prueba", "confirmar": "ELIMINAR"})
    assert (case.evidence_dir / digest).exists()
    c.post(f"/caso/{cid}/archivo/{digest}/quitar", data={"motivo": "Se agregó por error"})
    # sin escribir ELIMINAR, o con un motivo inventado: no pasa nada
    c.post(url, data={"motivo": "Datos de prueba", "confirmar": "si"})
    c.post(url, data={"motivo": "porque sí", "confirmar": "ELIMINAR"})
    assert (case.evidence_dir / digest).exists()
    # un analista no puede
    _login(c, "ana", "clave-segura-002")
    assert c.post(url, data={"motivo": "Datos de prueba", "confirmar": "ELIMINAR"}).status_code == 403
    _login(c, "admin", "clave-segura-001")
    assert "Eliminar definitivamente" in c.get(f"/caso/{cid}?tab=fotos").get_data(as_text=True)
    r = c.post(url, data={"motivo": "Datos de prueba", "confirmar": "eliminar"}, follow_redirects=True)
    assert "eliminado definitivamente" in r.get_data(as_text=True)
    assert not (case.evidence_dir / digest).exists()
    assert not any(json.loads(x).get("sha256") == digest for x in reg.read_text().splitlines() if x.strip())
    # la foto ya no aparece; el historial sí lo registra; la integridad sigue bien; no se puede restaurar
    fotos_tab = c.get(f"/caso/{cid}?tab=fotos").get_data(as_text=True)
    assert "foto_0.jpg" not in fotos_tab and "foto_1.jpg" in fotos_tab
    hist = c.get(f"/caso/{cid}?tab=historial").get_data(as_text=True)
    assert "Archivo eliminado definitivamente" in hist and "foto_0.jpg" in hist and "Datos de prueba" in hist
    assert case.verify_evidence() == (True, [])
    assert "Integridad verificada" in c.post(f"/caso/{cid}/verificar", follow_redirects=True).get_data(as_text=True)
    c.post(f"/caso/{cid}/archivo/{digest}/restaurar")
    assert not (case.evidence_dir / digest).exists() and digest in case.excluded()
    assert c.get(f"/caso/{cid}/archivo/{digest}").status_code == 404
    for cache in ("analisis_imagen.json", "analisis_pares.json"):
        p = case.root / cache
        assert not p.exists() or digest not in p.read_text()
    # el paquete exportado se verifica solo y dice que el archivo se eliminó
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/caso/{cid}/exportar").data))
    out = tmp_path / "export"
    z.extractall(out)
    verify = next(out.rglob("verify.py"))
    res = subprocess.run([sys.executable, str(verify)], capture_output=True, text=True, cwd=verify.parent)
    assert "FALLA" not in res.stdout and "eliminada definitivamente: foto_0.jpg" in res.stdout, res.stdout
    # si la misma foto vuelve a llegar después (por ejemplo, por el portal), es evidencia nueva: se muestra y analiza
    with open(fotos[0], "rb") as fh:
        r = c.post(f"/caso/{cid}/fotos", data={"fotos": [(fh, "foto_0_otra_vez.jpg")]},
                   content_type="multipart/form-data", follow_redirects=True)
    assert "ya estaban en el caso" not in r.get_data(as_text=True)
    assert (case.evidence_dir / digest).exists() and digest not in case.excluded() and digest not in case.purged()
    assert "foto_0_otra_vez.jpg" in c.get(f"/caso/{cid}?tab=fotos").get_data(as_text=True)
    assert any(e["subject"] == digest for e in case.active_evidence())
    assert case.verify_evidence() == (True, [])


def test_purge_from_registry_only_touches_that_claim_and_file(tmp_path):
    reg = tmp_path / "registro.jsonl"
    rows = [{"claim": "A", "sha256": "x"}, {"claim": "B", "sha256": "x"}, {"claim": "A", "sha256": "y"}]
    reg.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert analysis.purge_from_registry(reg, "A", "x") == 1
    left = [json.loads(x) for x in reg.read_text().splitlines()]
    assert left == rows[1:]
