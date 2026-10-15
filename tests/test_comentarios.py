"""Comentarios internos: quedan en la cadena de custodia, @menciones avisan en Inicio y respetan quién ve el caso."""
from test_empresas import PW, _app, _login, _nuevo

from evidex.claims import comments, service
from evidex.core.ledger import verify_chain


def test_comentar_mencionar_y_leer(tmp_path):
    app, store, wd = _app(tmp_path)
    jb = _login(app, "jefe.bci")
    jb.post("/usuarios", data={"usuario": "ana", "nombre": "Ana", "rol": "analista", "clave": PW})
    jb.post("/usuarios", data={"usuario": "beto", "nombre": "Beto", "rol": "analista", "clave": PW})
    _nuevo(jb, "SIN-B1", analista="ana")
    case = service.find_case(wd, "SIN-B1")
    page = jb.get(f"/caso/{case.root.name}?tab=comentarios").get_data(as_text=True)
    assert "Sin comentarios" in page and "@ana" in page and "@beto" not in page and "@jefe.otra" not in page
    # beto no tiene el caso y jefe.otra es de otra empresa: no se les avisa
    r = jb.post(f"/caso/{case.root.name}/comentar", data={"texto": "@ana revisa la foto 3 <b>ya</b>\nY @beto, @jefe.otra"},
                follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "No se avisó a @beto, @jefe.otra" in html and "&lt;b&gt;ya&lt;/b&gt;" in html and '<span class="at">@ana</span>' in html
    e = [x for x in case.ledger.entries() if x["action"] == "comentario"][-1]
    assert e["actor"] == "Jefe BCI" and e["data"]["menciones"] == ["ana"] and verify_chain(case.ledger.entries())[0]
    # ana lo ve en Inicio; beto no
    ana = _login(app, "ana")
    inicio = ana.get("/").get_data(as_text=True)
    assert "Te mencionaron" in inicio and "revisa la foto 3" in inicio
    assert "Te mencionaron" not in _login(app, "beto").get("/").get_data(as_text=True)
    # al abrir los comentarios queda leído
    assert "te mencionó" in ana.get(f"/caso/{case.root.name}?tab=comentarios").get_data(as_text=True)
    assert "Te mencionaron" not in ana.get("/").get_data(as_text=True)
    # el historial resume el texto
    assert "revisa la foto 3" in ana.get(f"/caso/{case.root.name}?tab=historial").get_data(as_text=True)


def test_comentarios_validan_y_respetan_empresa(tmp_path):
    app, store, wd = _app(tmp_path)
    jb, jo = _login(app, "jefe.bci"), _login(app, "jefe.otra")
    _nuevo(jb, "SIN-B1")
    cid = service.find_case(wd, "SIN-B1").root.name
    assert jo.post(f"/caso/{cid}/comentar", data={"texto": "hola"}).status_code == 404     # otra empresa
    jb.post(f"/caso/{cid}/comentar", data={"texto": "   "})
    jb.post(f"/caso/{cid}/comentar", data={"texto": "x" * 2001})
    assert comments.count(service.find_case(wd, "SIN-B1")) == 0
    # el administrador (Zelekpress) puede ver y ser mencionado
    jb.post(f"/caso/{cid}/comentar", data={"texto": "@fabian mira esto"})
    assert [m["caso"] for m in comments.pending(wd, "fabian")] == [cid]
