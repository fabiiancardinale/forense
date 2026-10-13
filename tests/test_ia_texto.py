"""Asistente de texto con IA (Groq): datos mínimos, activación explícita, constancia en la cadena, audios."""
import io
import json

import pytest

from helpers import textured_image
from evidex.claims import ia_texto, service


def test_tapar_saca_datos_personales():
    t = ia_texto.tapar("Soy 12.345.678-5, mi fono +56 9 8765 4321, correo ana@ejemplo.cl, cuenta 000123456789. Km 45000.")
    assert "12.345.678-5" not in t and "8765" not in t and "ana@" not in t and "000123456789" not in t
    assert "[RUT]" in t and "[TELÉFONO]" in t and "[CORREO]" in t and "Km 45000" in t


class Falso:
    """Reemplaza las llamadas a Groq y guarda lo que se habría enviado."""
    def __init__(self):
        self.enviado = []

    def __call__(self, url, data, headers):
        self.enviado.append((url, data))
        if url.endswith("/audio/transcriptions"):
            return {"text": "Iba por Apoquindo y me chocaron por atrás, eran como las nueve de la noche."}
        content = json.loads(data)["messages"][1]["content"]
        if "preguntas" in content[:200]:
            res = {"preguntas": [{"para": "asegurado", "pregunta": "¿Dónde estaba estacionado?", "por_que": "lugar"}]}
        elif "Resume" in content[:200]:
            res = {"resumen": "Choque trasero declarado en Apoquindo.", "puntos_clave": ["sin testigos"],
                   "falta_para_decidir": ["parte policial"]}
        else:
            res = {"datos_del_relato": {"lugar": "Apoquindo", "partes_danadas": ["parachoques trasero"]},
                   "inconsistencias": [{"tema": "Hora", "dice_el_relato": "21:00", "dice_otra_fuente": "10:00",
                                        "fuente": "formulario", "importancia": "media", "que_revisar": "la hora real"}]}
        return {"choices": [{"message": {"content": json.dumps(res)}}]}


def _client(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/usuarios", data={"usuario": "admin", "nombre": "Admin", "rol": "administrador", "clave": "clave-segura-001"})
    c.post("/usuarios", data={"usuario": "pepe", "nombre": "Pepe", "rol": "perito", "clave": "clave-segura-003",
                              "empresa": "Peritos SA"})
    c.post("/salir")
    c.post("/ingresar", data={"usuario": "admin", "clave": "clave-segura-001"})
    return c


def test_asistente_relato_preguntas_resumen_y_audio(tmp_path, monkeypatch):
    falso = Falso()
    monkeypatch.setattr(ia_texto, "_post", falso)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    c = _client(tmp_path)
    foto = io.BytesIO()
    textured_image(5, 640, 480).save(foto, "JPEG")
    foto.seek(0)
    r = c.post("/nuevo", data={"numero": "SIN-2026-9300", "fecha_siniestro": "2026-10-01T10:00", "rut": "12.345.678-5",
                               "telefono": "+56987654321", "asegurado": "Ana Pérez", "patente": "JSGG71",
                               "descripcion": "Me chocaron por atrás en Apoquindo. Mi RUT 12.345.678-5, fono 987654321.",
                               "fotos": [(foto, "trasera.jpg")]}, content_type="multipart/form-data")
    assert r.status_code == 302
    case = service.find_case(tmp_path / "casos", "SIN-2026-9300")
    cid = case.root.name
    # sin clave: no se llama a nadie
    r = c.post(f"/caso/{cid}/ia/relato", follow_redirects=True)
    assert "Falta la clave de Groq" in r.get_data(as_text=True) and not falso.enviado
    # con clave pero apagado en Configuración: tampoco
    monkeypatch.setenv("GROQ_API_KEY", "gsk_prueba")
    r = c.post(f"/caso/{cid}/ia/relato", follow_redirects=True)
    assert "está apagado" in r.get_data(as_text=True) and not falso.enviado
    assert "Clave en el servidor" in c.get("/configuracion").get_data(as_text=True)
    c.post("/configuracion", data={"empresa": "", "ia_texto": "1"})
    # revisar el relato
    r = c.post(f"/caso/{cid}/ia/relato", follow_redirects=True)
    page = r.get_data(as_text=True)
    assert "Revisión del relato lista" in page and "dice «21:00»" in page.replace("&#34;", '"')
    url, data = falso.enviado[-1]
    enviado = json.loads(data)["messages"][1]["content"]
    assert url.endswith("/chat/completions")
    for secreto in ("12.345.678-5", "987654321", "Ana Pérez", "+56987654321"):
        assert secreto not in enviado, secreto
    assert "Apoquindo" in enviado and "JSGG71" in enviado
    # resumen y preguntas
    c.post(f"/caso/{cid}/ia/resumen")
    assert "Choque trasero declarado en Apoquindo." in c.get(f"/caso/{cid}").get_data(as_text=True)
    c.post(f"/caso/{cid}/ia/preguntas")
    assert "¿Dónde estaba estacionado?" in c.get(f"/caso/{cid}?tab=peritaje").get_data(as_text=True)
    # constancia en la cadena de custodia y en el historial
    usos = [e for e in case.ledger.entries() if e["action"] == "llm_used"]
    assert [u["data"]["tarea"] for u in usos] == ["relato", "resumen", "preguntas"]
    assert "Texto enviado a la IA (Groq)" in c.get(f"/caso/{cid}?tab=historial").get_data(as_text=True)
    assert case.verify_evidence() == (True, [])
    # un audio (nota de voz de WhatsApp): se agrega, se escucha y se transcribe
    audio = io.BytesIO(b"OggS" + bytes(2000))
    r = c.post(f"/caso/{cid}/fotos", data={"fotos": [(audio, "nota_de_voz.opus")], "tab": "documentos"},
               content_type="multipart/form-data", follow_redirects=True)
    assert "agregado" in r.get_data(as_text=True)
    d_audio = next(e["subject"] for e in case.active_evidence() if e["data"]["original_name"] == "nota_de_voz.opus")
    docs = c.get(f"/caso/{cid}?tab=documentos").get_data(as_text=True)
    assert "<audio" in docs and "Transcribir con IA" in docs
    assert c.get(f"/caso/{cid}/archivo/{d_audio}").mimetype == "audio/ogg"
    r = c.post(f"/caso/{cid}/archivo/{d_audio}/transcribir", follow_redirects=True)
    assert "transcrito" in r.get_data(as_text=True)
    assert falso.enviado[-1][0].endswith("/audio/transcriptions")
    assert "me chocaron por atrás" in c.get(f"/caso/{cid}?tab=documentos").get_data(as_text=True)
    # la transcripción entra al relato que se revisa
    c.post(f"/caso/{cid}/ia/relato")
    assert "me chocaron por atrás" in json.loads(falso.enviado[-1][1])["messages"][1]["content"]
    # un perito externo no puede usarlo
    c.post("/salir")
    c.post("/ingresar", data={"usuario": "pepe", "clave": "clave-segura-003"})
    assert c.post(f"/caso/{cid}/ia/resumen").status_code == 403
    # eliminar definitivamente el audio borra también su transcripción
    c.post("/salir")
    c.post("/ingresar", data={"usuario": "admin", "clave": "clave-segura-001"})
    c.post(f"/caso/{cid}/archivo/{d_audio}/quitar", data={"motivo": "Se agregó por error"})
    c.post(f"/caso/{cid}/archivo/{d_audio}/eliminar", data={"motivo": "Datos de prueba", "confirmar": "ELIMINAR"})
    assert d_audio not in (ia_texto.cargar(case).get("transcripciones") or {})


def test_errores_de_groq(monkeypatch, tmp_path):
    import urllib.error
    monkeypatch.setenv("GROQ_API_KEY", "gsk_mala")

    def falla(*a, **k):
        raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b'{"error":{"message":"Invalid API Key"}}'))
    monkeypatch.setattr(ia_texto.urllib.request, "urlopen", falla)
    with pytest.raises(ia_texto.IAError, match="no es válida"):
        ia_texto.chat_json("s", "u")


def test_user_agent_propio(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    visto = {}

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"{}"}}]}'

    def abrir(req, timeout):
        visto.update({k.lower(): v for k, v in req.header_items()})
        return R()
    monkeypatch.setattr(ia_texto.urllib.request, "urlopen", abrir)
    assert ia_texto.chat_json("s", "u") == {}
    assert visto["user-agent"] == "Evidex/1.0" and visto["authorization"] == "Bearer gsk_x"

    def prohibido(*a, **k):
        raise urllib_error().HTTPError("u", 403, "no", {}, io.BytesIO(b"<html><b>Access denied</b> error 1010</html>"))
    monkeypatch.setattr(ia_texto.urllib.request, "urlopen", prohibido)
    with pytest.raises(ia_texto.IAError, match="403.*Access denied"):
        ia_texto.chat_json("s", "u")


def urllib_error():
    import urllib.error
    return urllib.error


def test_modelo_no_disponible_usa_otro(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.delenv("GROQ_MODELO", raising=False)
    ia_texto._elegido.clear()
    pedidos = []

    def post(url, data, headers):
        m = json.loads(data)["model"]
        pedidos.append(m)
        if m == "llama-3.3-70b-versatile":
            raise ia_texto.IAError("Groq respondió con un error (404). The model `llama-3.3-70b-versatile` does not exist", 404)
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}
    monkeypatch.setattr(ia_texto, "_post", post)
    monkeypatch.setattr(ia_texto, "modelos_disponibles", lambda: ["whisper-large-v3", "openai/gpt-oss-120b", "llama-3.1-8b-instant"])
    assert ia_texto.chat_json("s", "u") == {"ok": True}
    assert pedidos == ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"] and ia_texto.modelo() == "openai/gpt-oss-120b"
    ia_texto.chat_json("s", "u")
    assert pedidos[-1] == "openai/gpt-oss-120b"            # ya no vuelve a probar el que no existe
    ia_texto._elegido.clear()
