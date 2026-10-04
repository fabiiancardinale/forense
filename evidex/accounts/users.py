"""Usuarios, roles, permisos y registro de accesos.

Roles:
  administrador  todo, más usuarios, empresas de peritaje y configuración
  jefe           ve todos los casos y el panel de equipo; reasigna casos; redes, métricas e importación
  analista       sus propios casos: registrar, agregar evidencia, portal del asegurado, derivar a perito, decidir
  investigador   investigador interno: expedientes y auditorías de informes
  perito         perito o empresa externa: solo los expedientes derivados a su empresa

Sin usuarios, el acceso queda bloqueado hasta inicializar un administrador por consola.
La demo anónima requiere activación explícita y solo debe usarse localmente.

Contraseñas: se guardan solo como hash (werkzeug: scrypt/pbkdf2), nunca en texto. Tras 5 intentos
fallidos, el usuario queda bloqueado 5 minutos. Cada ingreso, salida y apertura de un caso queda
en accesos.jsonl (quién, cuándo, qué, desde qué equipo).
"""
from __future__ import annotations

import json
import re
import time
import secrets
from evidex.core.storage import atomic_json, atomic_bytes, serialized
from evidex.accounts.state import AuthState
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

ROLES = {"administrador": "Administrador", "jefe": "Jefe de siniestros", "analista": "Analista",
         "investigador": "Investigador interno", "perito": "Perito externo"}
LEGACY_ROLES = {"liquidador": "analista"}          # nombres de rol de versiones anteriores
PERMS = {
    "ver_siniestros": {"administrador", "jefe", "analista", "investigador"},
    "editar_siniestros": {"administrador", "jefe", "analista"},
    "ver_todos": {"administrador", "jefe", "investigador"},        # sin esto, solo los casos propios
    "equipo": {"administrador", "jefe"},                           # panel de equipo y reasignar casos
    "investigaciones": {"administrador", "jefe", "investigador"},  # crear expedientes, auditorías, ver todos
    "peritaje": {"administrador", "jefe", "investigador", "perito"},  # trabajar un expediente
    "redes": {"administrador", "jefe", "analista"},
    "cartera": {"administrador", "jefe"},
    "admin": {"administrador"},
}
# endpoint -> permiso necesario (los que no están aquí son públicos: ingreso y portal del asegurado)
ENDPOINTS = {
    **{f"inspection.{e}": "ver_siniestros" for e in ("index","result","status","artifact","retry")},
    "panel.dashboard": None, "panel.team": "equipo", "panel.reassign": "equipo",
    "claims.index": "ver_siniestros", "claims.case_view": "ver_siniestros", "claims.analysis_status": "ver_siniestros", "claims.report": "ver_siniestros",
    "claims.doc_version": "ver_siniestros", "claims.evidence_file": "ver_siniestros", "claims.export_zip": "ver_siniestros",
    "claims.verify": "ver_siniestros", "claims.new_claim": "editar_siniestros", "claims.add_photos": "editar_siniestros",
    "claims.reanalyze": "editar_siniestros", "claims.decide": "editar_siniestros", "claims.capture_link": "editar_siniestros",
    "claims.capture_sent": "editar_siniestros",
    "claims.load_demo": "editar_siniestros", "claims.evidence_exclude": "editar_siniestros",
    "claims.evidence_restore": "editar_siniestros", "claims.derive": "editar_siniestros",
    "claims.derive_cancel": "editar_siniestros", "claims.dossier_report": "ver_siniestros",
    "investigations.investigations": "peritaje", "investigations.inv_view": "peritaje",
    "investigations.inv_response": "peritaje", "investigations.inv_conclusion": "peritaje",
    "investigations.inv_report": "peritaje", "investigations.inv_export": "peritaje",
    "investigations.inv_interview": "peritaje", "investigations.inv_document": "peritaje",
    "investigations.inv_deliver": "peritaje", "investigations.inv_file": "peritaje",
    "investigations.inv_settings": "investigaciones", "investigations.inv_demo": "investigaciones",
    "investigations.inv_new": "investigaciones", "investigations.audit_upload": "investigaciones",
    "investigations.audit_view": "investigaciones",
    "portfolio.networks": "redes", "portfolio.metrics_view": "cartera", "portfolio.import_view": "cartera",
    "portfolio.import_demo": "cartera", "portfolio.template_download": "cartera", "portfolio.export_xlsx": "cartera",
    "tools.photo_check": "ver_siniestros",
    "admin.settings": "admin", "admin.users_view": "admin", "admin.user_toggle": "admin", "admin.firm_add": "admin",
}
ROLE_HELP = {"administrador": "Todo, más usuarios, empresas de peritaje y configuración.",
             "jefe": "Ve todos los casos y el panel de equipo, reasigna casos; redes, métricas e importación.",
             "analista": "Sus propios casos: registrar, evidencia, portal del asegurado, derivar a perito y decidir.",
             "investigador": "Investigador interno: expedientes y auditorías de informes.",
             "perito": "Perito o empresa externa: solo los expedientes derivados a su empresa."}
ACTION_LABELS = {"ingreso": "Ingresó", "ingreso_fallido": "Ingreso fallido", "salida": "Salió", "ver_caso": "Abrió el caso",
                 "decision": "Registró decisión", "descarga": "Descargó", "ver_expediente": "Abrió expediente",
                 "usuario": "Cambió un usuario", "exporta_excel": "Exportó a Excel", "reasignar": "Reasignó un caso",
                 "derivar": "Derivó a perito", "entregar_informe": "Entregó informe final", "quitar_archivo": "Quitó un archivo"}
MAX_FAILS, LOCK_SECONDS = 5, 300
DUMMY_HASH = generate_password_hash("not-a-user-password")
USERNAME = re.compile(r"^[a-z0-9._-]{3,32}$")


class UserStorageError(RuntimeError):
    pass


class Store:
    def __init__(self, workdir: Path):
        self.path = Path(workdir) / "usuarios.json"
        self.log_path = Path(workdir) / "accesos.jsonl"
        self.marker = Path(workdir) / ".auth_initialized"
        if self.path.exists():
            self.all()
            atomic_bytes(self.marker, b"initialized")
        self.state = AuthState(Path(workdir) / "auth.sqlite3")

    def all(self) -> dict:
        if not self.path.exists() and not self.marker.exists():
            return {}
        try:
            users = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(users, dict) or not users:
                raise ValueError("empty user store")
            for u in users.values():
                u["role"] = LEGACY_ROLES.get(u.get("role"), u.get("role"))
                if u["role"] not in ROLES or not isinstance(u.get("pw"), str):
                    raise ValueError("invalid user")
            return users
        except (OSError, ValueError, TypeError, AttributeError) as ex:
            raise UserStorageError("No se puede leer el registro de usuarios. Acceso bloqueado; restaure el respaldo.") from ex

    def by_role(self, *roles: str) -> list[dict]:
        return sorted(({**u, "username": k} for k, u in self.all().items() if u.get("role") in roles and u.get("active", True)),
                      key=lambda u: u["name"].lower())

    def display_name(self, username: str) -> str:
        u = self.all().get(username or "")
        return u["name"] if u else (username or "")

    def _save(self, users: dict) -> None:
        atomic_bytes(self.marker, b"initialized")
        atomic_json(self.path, users)

    def enabled(self) -> bool:
        return any(u.get("active", True) for u in self.all().values())

    def get(self, username: str) -> dict | None:
        u = self.all().get(username)
        return {**u, "username": username} if u else None

    @serialized(lambda self, *a, **kw: self.path)
    def add(self, username: str, name: str, role: str, password: str, empresa: str = "") -> str | None:
        """Crea o actualiza un usuario. Devuelve un mensaje de error o None."""
        username = username.strip().lower()
        role = LEGACY_ROLES.get(role, role)
        if not USERNAME.fullmatch(username):
            return "El usuario debe tener 3 a 32 letras minúsculas, números, punto, guion o guion bajo."
        if len(password) > 256:
            return "La contraseña no puede superar 256 caracteres."
        if role not in ROLES:
            return "Rol desconocido."
        users = self.all()
        if not users and role != "administrador":
            return "El primer usuario debe ser administrador."
        if username not in users and len(password) < 15:
            return "La contraseña debe tener al menos 15 caracteres."
        if password and len(password) < 15:
            return "La contraseña debe tener al menos 15 caracteres."
        u = users.get(username, {"created": _now()})
        if role == "perito" and not empresa.strip():
            return "Un perito debe pertenecer a una empresa de peritaje."
        u["auth_version"] = secrets.token_hex(16)
        u.update({"name": name.strip() or username, "role": role, "active": True,
                  "empresa": empresa.strip() if role == "perito" else ""})
        if password:
            u["pw"] = generate_password_hash(password)
        users[username] = u
        if not any(x.get("role") == "administrador" and x.get("active", True) for x in users.values()):
            return "Debe quedar al menos un administrador activo."
        self._save(users)
        return None

    @serialized(lambda self, *a, **kw: self.path)
    def set_active(self, username: str, active: bool) -> str | None:
        users = self.all()
        if username not in users:
            return "No existe ese usuario."
        users[username]["active"] = active
        users[username]["auth_version"] = secrets.token_hex(16)
        if not any(x.get("role") == "administrador" and x.get("active", True) for x in users.values()):
            return "Debe quedar al menos un administrador activo."
        self._save(users)
        return None

    def check(self, username: str, password: str, ip: str = "local"):
        username = (username or "").strip().lower()[:128]
        def verify():
            u = self.get(username)
            # Fixed dummy hash avoids the cheap unknown-account path.
            digest = u.get("pw") if u else DUMMY_HASH
            valid = check_password_hash(digest, (password or "")[:1024])
            return u if valid and u and u.get("active", True) else None
        return self.state.check(username, ip, verify)

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
    if endpoint not in ENDPOINTS:
        return endpoint == "static"          # una vista nueva sin permiso declarado queda cerrada
    perm = ENDPOINTS[endpoint]
    return perm is None or role in PERMS[perm]


def can(role: str | None, perm: str) -> bool:
    return role in PERMS.get(perm, set())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
