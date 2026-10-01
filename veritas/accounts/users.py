"""Usuarios, roles y registro de accesos.

Roles:
  administrador  todo, más usuarios y configuración
  jefe           todo lo de siniestros e investigaciones, redes, métricas e importación
  liquidador     siniestros: ver, crear, agregar evidencia, decidir, pedir captura segura; ver redes
  investigador   investigaciones y auditorías; ver siniestros (sin decidir)

Mientras no exista ningún usuario, Veritas funciona abierto en este equipo (modo demo). Al crear
el primer usuario (que debe ser administrador) se exige iniciar sesión para todo.

Contraseñas: se guardan solo como hash (werkzeug: scrypt/pbkdf2), nunca en texto. Tras 5 intentos
fallidos, el usuario queda bloqueado 5 minutos. Cada ingreso, salida y apertura de un caso queda
en accesos.jsonl (quién, cuándo, qué, desde qué equipo).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

ROLES = {"administrador": "Administrador", "jefe": "Jefe de siniestros", "liquidador": "Liquidador",
         "investigador": "Investigador"}
PERMS = {
    "ver_siniestros": {"administrador", "jefe", "liquidador", "investigador"},
    "editar_siniestros": {"administrador", "jefe", "liquidador"},
    "investigaciones": {"administrador", "jefe", "investigador"},
    "redes": {"administrador", "jefe", "liquidador"},
    "cartera": {"administrador", "jefe"},
    "admin": {"administrador"},
}
# endpoint -> permiso necesario (los que no están aquí son públicos: ingreso y enlace de captura)
ENDPOINTS = {
    "panel.dashboard": "ver_siniestros", "claims.index": "ver_siniestros", "claims.case_view": "ver_siniestros", "claims.report": "ver_siniestros",
    "claims.doc_version": "ver_siniestros", "claims.evidence_file": "ver_siniestros", "claims.export_zip": "ver_siniestros", "claims.verify": "ver_siniestros", "tools.photo_check": "ver_siniestros",
    "claims.new_claim": "editar_siniestros", "claims.add_photos": "editar_siniestros", "claims.reanalyze": "editar_siniestros",
    "claims.decide": "editar_siniestros", "claims.evidence_exclude": "editar_siniestros", "claims.evidence_restore": "editar_siniestros", "claims.capture_link": "editar_siniestros", "claims.load_demo": "editar_siniestros",
    "investigations.investigations": "investigaciones", "investigations.inv_settings": "investigaciones", "investigations.inv_demo": "investigaciones",
    "investigations.inv_new": "investigaciones", "investigations.inv_view": "investigaciones", "investigations.inv_response": "investigaciones",
    "investigations.inv_conclusion": "investigaciones", "investigations.inv_report": "investigaciones", "investigations.inv_export": "investigaciones",
    "investigations.audit_upload": "investigaciones", "investigations.audit_view": "investigaciones",
    "portfolio.networks": "redes", "portfolio.metrics_view": "cartera", "portfolio.import_view": "cartera", "portfolio.import_demo": "cartera",
    "portfolio.template_download": "cartera", "portfolio.export_xlsx": "cartera",
    "admin.settings": "admin", "admin.users_view": "admin", "admin.user_toggle": "admin",
}
ROLE_HELP = {"administrador": "Todo, más usuarios y configuración.",
             "jefe": "Siniestros, investigaciones, redes, métricas e importación.",
             "liquidador": "Siniestros: ver, crear, agregar evidencia, decidir y pedir captura segura; ver redes.",
             "investigador": "Expedientes y auditorías; ver siniestros sin decidir."}
ACTION_LABELS = {"ingreso": "Ingresó", "ingreso_fallido": "Ingreso fallido", "salida": "Salió", "ver_caso": "Abrió el caso",
                 "decision": "Registró decisión", "descarga": "Descargó", "ver_expediente": "Abrió expediente",
                 "usuario": "Cambió un usuario", "exporta_excel": "Exportó a Excel"}
MAX_FAILS, LOCK_SECONDS = 5, 300
USERNAME = re.compile(r"^[a-z0-9._-]{3,32}$")


class Store:
    def __init__(self, workdir: Path):
        self.path = Path(workdir) / "usuarios.json"
        self.log_path = Path(workdir) / "accesos.jsonl"
        self.fails: dict[str, list[float]] = {}

    def all(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, users: dict) -> None:
        self.path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

    def enabled(self) -> bool:
        return any(u.get("active", True) for u in self.all().values())

    def get(self, username: str) -> dict | None:
        u = self.all().get(username)
        return {**u, "username": username} if u else None

    def add(self, username: str, name: str, role: str, password: str) -> str | None:
        """Crea o actualiza un usuario. Devuelve un mensaje de error o None."""
        username = username.strip().lower()
        if not USERNAME.fullmatch(username):
            return "El usuario debe tener 3 a 32 letras minúsculas, números, punto, guion o guion bajo."
        if role not in ROLES:
            return "Rol desconocido."
        users = self.all()
        if not users and role != "administrador":
            return "El primer usuario debe ser administrador."
        if username not in users and len(password) < 10:
            return "La contraseña debe tener al menos 10 caracteres."
        if password and len(password) < 10:
            return "La contraseña debe tener al menos 10 caracteres."
        u = users.get(username, {"created": _now()})
        u.update({"name": name.strip() or username, "role": role, "active": True})
        if password:
            u["pw"] = generate_password_hash(password)
        users[username] = u
        if not any(x.get("role") == "administrador" and x.get("active", True) for x in users.values()):
            return "Debe quedar al menos un administrador activo."
        self._save(users)
        return None

    def set_active(self, username: str, active: bool) -> str | None:
        users = self.all()
        if username not in users:
            return "No existe ese usuario."
        users[username]["active"] = active
        if not any(x.get("role") == "administrador" and x.get("active", True) for x in users.values()):
            return "Debe quedar al menos un administrador activo."
        self._save(users)
        return None

    def check(self, username: str, password: str) -> tuple[dict | None, str | None]:
        username = (username or "").strip().lower()
        now = time.time()
        recent = [t for t in self.fails.get(username, []) if now - t < LOCK_SECONDS]
        self.fails[username] = recent
        if len(recent) >= MAX_FAILS:
            return None, "Demasiados intentos fallidos. Espere 5 minutos e intente de nuevo."
        u = self.get(username)
        if not u or not u.get("active", True) or not check_password_hash(u.get("pw", ""), password or ""):
            self.fails[username].append(now)
            return None, "Usuario o contraseña incorrectos."
        self.fails.pop(username, None)
        return u, None

    def log(self, user: str, action: str, subject: str = "", ip: str = "") -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _now(), "user": user, "action": action, "subject": subject, "ip": ip},
                               ensure_ascii=False) + "\n")

    def entries(self, subject: str | None = None, limit: int = 300) -> list[dict]:
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = [json.loads(x) for x in lines if x.strip()]
        if subject:
            out = [e for e in out if e.get("subject") == subject]
        return out[-limit:][::-1]


def allowed(role: str | None, endpoint: str | None) -> bool:
    perm = ENDPOINTS.get(endpoint or "")
    return perm is None or (role in PERMS[perm])


def can(role: str | None, perm: str) -> bool:
    return role in PERMS.get(perm, set())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
