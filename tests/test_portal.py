"""Portal del asegurado: enlaces, subida con título, quitar archivos y dirección pública."""


from helpers import LIMPIO, textured_image, web_client
from veritas.claims import service
from veritas.core.case import Case


def test_secure_capture_flow(tmp_path):
    import io
    from veritas.portal import links as capture
    from veritas.web import create_app

    service.load_demo(tmp_path)
    case = service.find_case(tmp_path, LIMPIO)
    decl = service.declaration(case)
    app = create_app(tmp_path)
    c = app.test_client()
    assert c.post(f"/caso/{case.root.name}/captura").status_code == 302
    data = capture.load(case)
    tok = data["token"]
    assert c.get(f"/c/{tok}").status_code == 200
    assert c.get("/c/" + "x" * 30).status_code == 404
    buf = io.BytesIO(); textured_image(5).save(buf, "JPEG", quality=92)
    r = c.post(f"/c/{tok}/foto", content_type="multipart/form-data", data={
        "shot": "frontal", "lat": str(decl["lat"]), "lon": str(decl["lon"]), "acc": "10",
        "foto": (io.BytesIO(buf.getvalue()), "x.jpg")})
    assert r.status_code == 200 and r.get_json()["ok"]
    bad = c.post(f"/c/{tok}/foto", content_type="multipart/form-data",
                 data={"shot": "otra", "foto": (io.BytesIO(buf.getvalue()), "x.jpg")})
    assert bad.status_code == 400
    entry = [e for e in case.ledger.entries() if e["action"] == "evidence_added"][-1]
    assert entry["data"]["capture"]["server_time"] and entry["data"]["capture"]["lat"] == decl["lat"]
    _, _, photos, _, findings, _, _ = service.run_analysis(case)
    cap = [p for p in photos if p.meta.get("secure_capture")]
    assert cap and cap[0].meta["taken"] == entry["data"]["capture"]["server_time"]
    assert not [f for f in findings if f.rule == "no_metadata" and cap[0].ev in f.evidence]
    # en modo red, desde otro equipo solo se puede abrir el enlace de captura
    app.config["LAN"] = True
    assert c.get("/", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 403
    assert c.get(f"/c/{tok}", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 200


def test_register_case_and_portal_for_insured(tmp_path):
    """El analista registra el caso sin evidencia, se genera el enlace y el asegurado sube fotos y documentos con título."""
    import io as _io
    from PIL import Image
    from veritas.portal import links as capture
    c = web_client(tmp_path)
    work = tmp_path / "casos"
    form = {"numero": "SIN-2026-2001", "fecha_siniestro": "2026-09-30T19:10", "asegurado": "Ana Pérez",
            "telefono": "+56 9 8123 4567", "email": "ana@example.com", "enviar_enlace": "1",
            "docs": ["licencia", "presupuesto"], "docs_sent": "1"}
    assert c.post("/nuevo", data=form, content_type="multipart/form-data").status_code == 302
    case = Case(work / "SIN-2026-2001")
    tok = capture.load(case)["token"]
    page = c.get("/caso/SIN-2026-2001?tab=asegurado").get_data(as_text=True)
    assert "https://wa.me/56981234567?text=" in page and "mailto:ana@example.com" in page
    assert "Esperando al asegurado" in c.get("/").get_data(as_text=True)
    portal = c.get(f"/c/{tok}").get_data(as_text=True)
    assert "Elegir o tomar fotos" in portal and "Elegir documentos" in portal and "Licencia de conducir" in portal

    def up(kind, name, blob, title):
        return c.post(f"/c/{tok}/archivo", data={"kind": kind, "titulo": title, "archivo": (_io.BytesIO(blob), name)},
                      content_type="multipart/form-data")
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    exif = Image.Exif(); exif[0x010F] = "Apple"; exif[0x0110] = "iPhone 14"; exif[0x8769] = {0x9003: "2026:09:30 19:14:00"}
    g = _io.BytesIO(); Image.new("RGB", (640, 480), (120, 110, 100)).save(g, "JPEG", exif=exif)
    raw = g.getvalue()
    r = up("photo", "IMG_1023.JPG", raw, "")
    assert r.status_code == 400 and "título" in r.get_json()["error"]          # el título es obligatorio
    assert not capture.progress(capture.load(case))["photos_ok"]
    r = up("photo", "IMG_1023.JPG", raw, "Parachoques trasero")
    assert r.status_code == 200 and r.get_json()["tipo"] == "photo" and r.get_json()["titulo"] == "Parachoques trasero"
    assert up("doc", "lic.pdf", pdf, "Licencia de conducir").get_json()["tipo"] == "doc"
    assert up("photo", "boleta.pdf", pdf, "Boleta grúa").get_json()["tipo"] == "doc"   # un PDF siempre es documento
    for kind, name, blob in (("photo", "virus.exe", b"MZ"), ("doc", "falso.pdf", b"hola"), ("otro", "x.pdf", pdf)):
        assert up(kind, name, blob, "Algo").status_code == 400
    pr = capture.progress(capture.load(case))
    assert pr["photos_ok"] and pr["docs_ok"] and (pr["done"], pr["total"]) == (2, 2)
    assert c.post(f"/c/{tok}/relato", data={"texto": "Iba por Apoquindo y me chocaron por atrás."}).status_code == 200
    assert c.post(f"/c/{tok}/terminar").status_code == 200
    assert c.post(f"/c/{tok}/terminar").status_code == 400                    # ya enviado: el enlace se cierra
    assert "Ya envió todo" in c.get(f"/c/{tok}").get_data(as_text=True)
    stored = next(e for e in case.ledger.entries() if e["action"] == "evidence_added"
                  and e["data"].get("portal", {}).get("title") == "Parachoques trasero")
    assert "parachoques_trasero" in stored["data"]["original_name"]
    assert (case.evidence_dir / stored["subject"]).read_bytes() == raw      # archivo original, byte a byte
    photo = next(p for p in service.run_analysis(case)[2] if "parachoques" in p.name)
    assert photo.meta["make"] == "Apple" and photo.meta["taken"] == "2026-09-30T19:14:00"
    case_page = c.get("/caso/SIN-2026-2001?tab=asegurado").get_data(as_text=True)
    assert "Entregado" in case_page and "Parachoques trasero" in case_page and "Licencia de conducir" in case_page
    assert "Parachoques trasero" in (work / "SIN-2026-2001" / "informe.html").read_text(encoding="utf-8")
    assert c.get("/c/" + "z" * 30).status_code == 404
    r = c.post("/nuevo", data={"numero": "X9", "fecha_siniestro": "2026-09-30T19:10"}, content_type="multipart/form-data")
    assert r.status_code == 400                                                 # sin archivos y sin enlace


def test_portal_paper_document_photo_is_read_as_document(tmp_path):
    """Una foto subida como documento (un papel) se lee como documento: RUT y fechas."""
    import io as _io
    from PIL import Image, ImageDraw, ImageFont
    from veritas.portal import links as capture
    from veritas.forensics import ocr
    c = web_client(tmp_path)
    form = {"numero": "SIN-2026-3001", "fecha_siniestro": "2026-09-30T19:10", "patente": "KXTR-45", "enviar_enlace": "1",
            "docs": ["presupuesto"], "docs_sent": "1", "docs_custom": "Carta del empleador; "}
    assert c.post("/nuevo", data=form, content_type="multipart/form-data").status_code == 302
    case = Case(tmp_path / "casos" / "SIN-2026-3001")
    tok = capture.load(case)["token"]
    assert "Carta del empleador" in c.get(f"/c/{tok}").get_data(as_text=True)
    img = Image.new("RGB", (1200, 1600), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=44)
    except TypeError:
        font = ImageFont.load_default()
    for i, line in enumerate(["TALLER EL ROBLE", "RUT: 76.543.210-9", "PRESUPUESTO", "Fecha: 25-09-2026", "TOTAL: $2.300.000"]):
        d.text((100, 150 + i * 90), line, fill="black", font=font)
    b = _io.BytesIO(); img.save(b, "JPEG", quality=90)
    r = c.post(f"/c/{tok}/archivo", data={"kind": "doc", "titulo": "Presupuesto en papel",
                                          "archivo": (_io.BytesIO(b.getvalue()), "IMG_3001.jpg")},
               content_type="multipart/form-data")
    assert r.status_code == 200
    _, _, photos, docs, findings, _, _ = service.run_analysis(case)
    assert photos == []                                        # la foto del papel no se trata como foto del vehículo
    paper = docs[0]
    assert paper.meta.get("image_doc") and paper.meta.get("title") == "Presupuesto en papel"
    if ocr.available():
        assert "76.543.210-9" in paper.meta["text"]
        assert {"doc_rut_invalid", "doc_dated_before"} <= {f.rule for f in findings}


def test_public_link_warning_and_guard(tmp_path):
    from veritas.portal import tunnel
    from veritas.portal import links as capture
    assert tunnel.is_local("http://127.0.0.1:8765/c/x") and tunnel.is_local("https://192.168.1.5:8765/c/x")
    assert not tunnel.is_local("https://abc-def.trycloudflare.com/c/x")
    msg = capture.share_message("SIN-1", "Ana Pérez", "https://abc.trycloudflare.com/c/tok", "2026-10-08T10:00:00")
    assert "\nhttps://abc.trycloudflare.com/c/tok\n" in msg
    from veritas.web import create_app
    app = create_app(tmp_path / "casos")
    app.config.update(TESTING=True, PUBLIC=True, PUBLIC_BASE="https://abc.trycloudflare.com")
    cl = app.test_client()
    assert cl.get("/", headers={"Cf-Ray": "1"}).status_code == 404          # por el túnel solo se ve el portal
    assert cl.get("/siniestros", base_url="https://abc.trycloudflare.com").status_code == 404
    assert cl.get("/", base_url="http://127.0.0.1:8765").status_code in (200, 302)


def test_portal_uploads_show_in_case_and_report(tmp_path):
    import io, json
    from PIL import Image
    from veritas.web import create_app
    app = create_app(tmp_path / "casos"); app.config["TESTING"] = True
    cl = app.test_client(); B = "http://127.0.0.1:8765"; H = {"Origin": B}
    cl.post("/demo", base_url=B, headers=H)
    cid = [p.name for p in (tmp_path / "casos").iterdir() if (p / "ledger.jsonl").exists()][0]
    cl.post(f"/caso/{cid}/captura", data={"docs_sent": "1", "docs": ["presupuesto"]}, base_url=B, headers=H)
    cl.get(f"/caso/{cid}", base_url=B)
    root = tmp_path / "casos" / cid
    tok = json.loads((root / "captura.json").read_text())["token"]
    buf = io.BytesIO(); Image.new("RGB", (400, 300), (120, 90, 60)).save(buf, "JPEG")
    cl.post(f"/c/{tok}/archivo", data={"kind": "photo", "titulo": "parachoque", "archivo": (io.BytesIO(buf.getvalue()), "a.jpg")},
            content_type="multipart/form-data")
    h = cl.get(f"/caso/{cid}?tab=asegurado", base_url=B).get_data(as_text=True)      # sin que el asegurado presione Terminar
    assert "capthumbs" in h and "parachoque" in (root / "informe.html").read_text(encoding="utf-8")
    import re
    mini = re.search(r'/caso/[^"]+/archivo/[0-9a-f]{64}\?mini=1', h).group(0)
    assert cl.get(mini, base_url=B).mimetype == "image/jpeg"


def test_remove_wrong_file_keeps_custody(tmp_path):
    import io, json, re
    from PIL import Image
    from veritas.web import create_app
    from veritas.core.case import Case
    app = create_app(tmp_path / "casos"); app.config["TESTING"] = True
    cl = app.test_client(); B = "http://127.0.0.1:8765"; H = {"Origin": B}
    cl.post("/demo", base_url=B, headers=H)
    cid = [p.name for p in (tmp_path / "casos").iterdir() if (p / "ledger.jsonl").exists()][0]
    cl.post(f"/caso/{cid}/captura", data={"docs_sent": "1", "docs": ["presupuesto"]}, base_url=B, headers=H)
    root = tmp_path / "casos" / cid
    tok = json.loads((root / "captura.json").read_text())["token"]
    ids = []
    for t, c in (("foto equivocada", (10, 200, 10)), ("parachoque", (120, 90, 60))):
        buf = io.BytesIO(); Image.new("RGB", (400, 300), c).save(buf, "JPEG")
        r = cl.post(f"/c/{tok}/archivo", data={"kind": "photo", "titulo": t, "archivo": (io.BytesIO(buf.getvalue()), "a.jpg")},
                    content_type="multipart/form-data")
        ids.append(r.get_json()["id"])
    # el asegurado quita la equivocada
    assert cl.post(f"/c/{tok}/quitar", data={"id": ids[0]}).status_code == 200
    assert "foto equivocada" not in cl.get(f"/c/{tok}").get_data(as_text=True)
    case = Case(root)
    assert ids[0] in case.excluded() and (case.evidence_dir / ids[0]).exists()      # no se borra
    cl.get(f"/caso/{cid}", base_url=B)
    rep = (root / "informe.html").read_text(encoding="utf-8")
    assert "Archivo quitado del análisis" in rep and "parachoque" in rep
    assert 'class="photo"' in rep and "foto equivocada</b>" not in rep
    # el analista quita otra y luego la restaura
    cl.post(f"/caso/{cid}/archivo/{ids[1]}/quitar", data={"motivo": "Es de otro siniestro"}, base_url=B, headers=H)
    assert ids[1] in Case(root).excluded()
    assert "parachoque" not in cl.get(f"/c/{tok}").get_data(as_text=True)
    cl.post(f"/caso/{cid}/archivo/{ids[1]}/restaurar", base_url=B, headers=H)
    assert ids[1] not in Case(root).excluded()
    ok, _ = Case(root).verify_evidence(); assert ok
