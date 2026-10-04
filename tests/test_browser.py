"""Pruebas con un navegador real (Chromium): lo que el cliente de pruebas de Flask no ve.

El cliente de pruebas no aplica la política de seguridad de contenido (CSP), no envía la cabecera Origin
como un navegador y no ejecuta JavaScript. Por eso el error de "Origen no permitido" en el login pasó
todas las pruebas. Aquí se recorre Evidex completo como lo haría un analista y se revisan los errores de
consola. Se omiten si Playwright no está instalado (pip install playwright; playwright install chromium).
"""
import threading

import pytest

from helpers import real_pdf, textured_image

pw = pytest.importorskip("playwright.sync_api")

PW = "una-clave-de-prueba-larga"


@pytest.fixture
def server(tmp_path):
    from werkzeug.serving import make_server
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"LEGACY_MODULES": True})
    assert app.extensions["evidex"]["store"].add("fabian", "Fabián", "administrador", PW) is None
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", tmp_path
    srv.shutdown()


@pytest.fixture
def page(server):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as ex:                       # navegador no instalado
            pytest.skip(f"Chromium no disponible: {ex}")
        pg = browser.new_page()
        errors = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        yield pg, server[0], errors, server[1]
        browser.close()


def _login(pg, base):
    pg.goto(base + "/ingresar")
    pg.fill("input[name=usuario]", "fabian")
    pg.fill("input[name=clave]", PW)
    pg.click("form button")
    pg.wait_for_load_state("networkidle")


def test_login_and_every_menu_page_works(page):
    pg, base, errors, _ = page
    _login(pg, base)
    assert "/ingresar" not in pg.url and "Origen no permitido" not in pg.content()
    links = sorted({a.get_attribute("href") for a in pg.query_selector_all("nav a[href^='/'], aside a[href^='/']")
                    if a.get_attribute("href")})
    assert len(links) >= 8, links                     # el menú completo, no solo «Analizar archivos»
    for href in links:
        resp = pg.goto(base + href)
        assert resp.status < 400, (href, resp.status)
        assert "Forbidden" not in pg.content(), href
    csp = [e for e in errors if "Content Security Policy" in e or "Refused" in e]
    assert not csp, csp


def test_create_claim_with_photo_and_open_every_tab(page, tmp_path):
    pg, base, errors, _ = page
    _login(pg, base)
    foto = tmp_path / "trasera.jpg"
    textured_image(4, 800, 600).save(foto, "JPEG", quality=90)
    falsa = tmp_path / "falsa.jpg"
    falsa.write_bytes(b"<html>no soy foto</html>")
    pg.goto(base + "/nuevo")
    pg.fill("input[name=numero]", "SIN-2026-7001")
    pg.fill("input[name=fecha_siniestro]", "2026-09-20T18:30")
    pg.set_input_files("input[name=fotos]", [str(falsa)])
    pg.click("button:has-text('Registrar siniestro')")
    pg.wait_for_load_state("networkidle")
    assert "Imagen inválida" in pg.content()          # el archivo falso se rechaza con el motivo
    pg.fill("input[name=numero]", "SIN-2026-7001")
    pg.fill("input[name=fecha_siniestro]", "2026-09-20T18:30")
    pg.set_input_files("input[name=fotos]", [str(foto)])
    pg.click("button:has-text('Registrar siniestro')")
    pg.wait_for_load_state("networkidle")
    assert "/caso/SIN-2026-7001" in pg.url, pg.url
    for tab in ("resumen", "fotos", "documentos", "peritaje", "asegurado", "informe", "historial"):
        resp = pg.goto(f"{base}/caso/SIN-2026-7001?tab={tab}")
        assert resp.status == 200, tab
    pg.goto(f"{base}/caso/SIN-2026-7001?tab=resumen")
    pg.click("form[action$='/analizar'] button")       # volver a analizar (formulario con CSRF real)
    pg.wait_for_load_state("networkidle")
    assert "Análisis actualizado" in pg.content()
    assert not [e for e in errors if "Content Security Policy" in e or "Refused" in e]


def test_insured_portal_upload_from_browser(page, tmp_path):
    from evidex.claims import service
    from evidex.portal import links as capture
    pg, base, errors, root = page
    _login(pg, base)
    pg.goto(base + "/nuevo")
    pg.fill("input[name=numero]", "SIN-2026-7002")
    pg.fill("input[name=fecha_siniestro]", "2026-09-20T18:30")
    pg.click("button:has-text('Registrar siniestro')")
    pg.wait_for_load_state("networkidle")
    case = service.find_case(root / "casos", "SIN-2026-7002")
    capture.create_link(case, actor="prueba")
    tok = capture.load(case)["token"]
    portal = pg.context.browser.new_page()            # el asegurado: sin sesión de Evidex
    resp = portal.goto(f"{base}/c/{tok}")
    assert resp.status == 200
    foto = tmp_path / "parachoques.jpg"
    textured_image(6, 800, 600).save(foto, "JPEG", quality=90)
    doc = tmp_path / "licencia.pdf"
    doc.write_bytes(real_pdf())
    portal.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    for kind, path, title in (("photo", foto, "Parachoques trasero"), ("doc", doc, "Licencia de conducir")):
        portal.set_input_files(f"input[type=file][data-kind={kind}]", str(path))
        portal.fill(f"#pend-{kind} input", title)
        portal.click(f"#up-{kind}")
        portal.wait_for_selector(f"#sent-{kind} li", timeout=20000)
    portal.click("#finish")
    portal.wait_for_selector("#done:not([hidden])", timeout=60000)   # el análisis corre en un proceso aparte
    data = capture.load(case)
    assert [f["title"] for f in data["files"]] == ["Parachoques trasero", "Licencia de conducir"] and data["finished"]
    assert not [e for e in errors if "Content Security Policy" in e or "Refused" in e]


def test_send_buttons_record_address(page):
    from evidex.claims import service
    from evidex.portal import links as capture
    pg, base, errors, root = page
    _login(pg, base)
    pg.goto(base + "/nuevo")
    pg.fill("input[name=numero]", "SIN-2026-7003")
    pg.fill("input[name=fecha_siniestro]", "2026-09-20T18:30")
    pg.click("button:has-text('Registrar siniestro')")
    pg.wait_for_load_state("networkidle")
    pg.goto(f"{base}/caso/SIN-2026-7003?tab=asegurado")
    if pg.query_selector("button:has-text('Crear enlace para el asegurado')"):
        pg.click("button:has-text('Crear enlace para el asegurado')")
        pg.wait_for_load_state("networkidle")
    pg.click("[data-copy-message]")
    pg.wait_for_timeout(800)
    case = service.find_case(root / "casos", "SIN-2026-7003")
    assert capture.load(case).get("sent_base") == base
    assert not [e for e in errors if "Content Security Policy" in e or "Refused" in e]
