"""Base de datos: los archivos anteriores pasan solos a SQLite, sin perder nada; respaldo e índice de casos."""
import json
import sqlite3

from werkzeug.security import generate_password_hash

from evidex.accounts import clients
from evidex.accounts.users import Store
from evidex.claims import assignment
from evidex.core import db

PW = "clave-segura-0001"


def _legacy(wd):
    wd.mkdir(parents=True)
    (wd / "clientes.json").write_text(json.dumps({"bci-seguros": {"nombre": "BCI Seguros", "creada": "2026-10-01T00:00:00Z"}}), encoding="utf-8")
    (wd / "usuarios.json").write_text(json.dumps({
        "fabian": {"name": "Fabián", "role": "administrador", "active": True, "pw": generate_password_hash(PW),
                   "auth_version": "v1", "created": "2026-01-01T00:00:00Z", "totp": "JBSWY3DPEHPK3PXP",
                   "totp_since": "2026-02-01T00:00:00Z", "totp_step": 123, "empresa": "", "cliente": None},
        "ana": {"name": "Ana", "role": "liquidador", "active": False, "pw": generate_password_hash(PW),
                "auth_version": "v2", "created": "2026-01-02T00:00:00Z", "cliente": "bci-seguros", "nota": "dato viejo"},
    }), encoding="utf-8")
    (wd / "empresas.json").write_text(json.dumps([{"nombre": "Peritajes Sur", "rut": "76.000.000-0", "contacto": "a@b.invalid"}]),
                                      encoding="utf-8")


def test_migra_archivos_anteriores_sin_perder_nada(tmp_path):
    wd = tmp_path / "casos"
    _legacy(wd)
    store = Store(wd)
    users = store.all()
    assert set(users) == {"fabian", "ana"}
    f = users["fabian"]
    assert f["totp"] == "JBSWY3DPEHPK3PXP" and f["totp_step"] == 123 and f["auth_version"] == "v1"
    a = users["ana"]
    assert a["role"] == "analista" and a["active"] is False and a["cliente"] == "bci-seguros" and a["nota"] == "dato viejo"
    assert store.check("fabian", PW)[0]["username"] == "fabian"            # la contraseña sigue sirviendo
    assert clients.all_clients(wd)["bci-seguros"]["nombre"] == "BCI Seguros"
    assert assignment.firms(wd)[0]["rut"] == "76.000.000-0"
    # los archivos quedan como respaldo, renombrados, y no se vuelven a importar
    assert not (wd / "usuarios.json").exists() and (wd / "usuarios.json.migrado").exists()
    assert (wd / "clientes.json.migrado").exists() and (wd / "empresas.json.migrado").exists()
    db.forget(wd)
    assert set(Store(wd).all()) == {"fabian", "ana"}


def test_cambios_quedan_en_la_base(tmp_path):
    wd = tmp_path / "casos"
    store = Store(wd)
    assert store.add("fabian", "Fabián", "administrador", PW) is None
    assert store.add("xavi", "X", "analista", PW, cliente="no-existe") == "Esa empresa cliente no existe."
    assert store.set_active("fabian", False) == "Debe quedar al menos un administrador activo."
    assert store.get("fabian")["active"] is True                           # el error no dejó nada a medias
    store.set_totp("fabian", "JBSWY3DPEHPK3PXP")
    assert store.get("fabian")["totp"] == "JBSWY3DPEHPK3PXP"
    store.set_totp("fabian", None)
    assert "totp" not in store.get("fabian")
    assignment.save_firm(wd, "Peritajes Sur")
    assignment.save_firm(wd, "PERITAJES SUR", "1-9")                       # mismo nombre: se reemplaza
    assert [f["rut"] for f in assignment.firms(wd)] == ["1-9"]
    assert clients.add(wd, "BCI Seguros") == ("bci-seguros", None)
    assert clients.add(wd, "bci seguros")[1].startswith("Ya existe")


def test_respaldo_en_caliente_e_indice_de_casos(tmp_path):
    from evidex.claims import service
    from helpers import textured_image
    wd = tmp_path / "casos"
    store = Store(wd)
    store.add("fabian", "Fabián", "administrador", PW)
    clients.add(wd, "BCI Seguros")
    img = tmp_path / "f.jpg"
    textured_image(3, 320, 240).save(img, "JPEG")
    decl = tmp_path / "d.json"
    decl.write_text(json.dumps({"numero": "SIN-1", "fecha_siniestro": "2026-10-01T10:00", "asegurado": "Ana"}), encoding="utf-8")
    case = service.create_claim(wd, "SIN-1", decl, [img], cliente="bci-seguros")
    assignment.assign(case, "ana", "Ana", "fabian")
    rows = db.cases(wd, cliente="bci-seguros")
    assert [(r["id"], r["analista"]) for r in rows] == [(case.root.name, "ana")]
    with db.open_db(wd).tx() as con:
        con.execute("DELETE FROM casos")
    assert db.reindex_cases(wd) == 1 and db.cases(wd, analista="ana")[0]["cliente"] == "bci-seguros"
    copia = db.open_db(wd).backup(tmp_path / "resp" / "evidex.sqlite3")
    con = sqlite3.connect(copia)
    assert con.execute("SELECT username FROM usuarios").fetchall() == [("fabian",)]
    con.close()
