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

Los usuarios viven en la base de datos (evidex.core.db, tabla usuarios).
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from evidex.core.db import USER_COLS, DatabaseError, open_db
from evidex.core.storage import atomic_bytes
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
    "eliminar_evidencia": {"administrador", "jefe"},                # borrar definitivamente (no se puede deshacer)
    "ensenar_modelo": {"administrador", "jefe", "analista"},        # marcar fotos para el banco de entrenamiento
    "ver_todos": {"administrador", "jefe", "investigador"},        # sin esto, solo los casos propios
    "equipo": {"administrador", "jefe"},                           # panel de equipo y reasignar casos
    "investigaciones": {"administrador", "jefe", "investigador"},  # crear expedientes, auditorías, ver todos
    "peritaje": {"administrador", "jefe", "investigador", "perito"},  # trabajar un expediente
    "redes": {"administrador", "jefe", "analista"},
    "cartera": {"administrador", "jefe"},
    "admin": {"administrador"},
    "usuarios": {"administrador", "jefe"},                         # el jefe crea a la gente de su empresa
}
# roles que un jefe puede crear (solo dentro de su propia empresa)
JEFE_CREA = ("analista", "investigador")
# endpoint -> permiso necesario (los que no están aquí son públicos: ingreso y portal del asegurado)
ENDPOINTS = {
    **{f"inspection.{e}": "ver_siniestros" for e in ("index","result","status","artifact","retry")},
    "panel.dashboard": None, "panel.team": "equipo", "panel.reassign": "equipo",
    "claims.index": "ver_siniestros", "claims.case_view": "ver_siniestros", "claims.case_preview": "ver_siniestros", "claims.comment_add": "ver_siniestros", "claims.analysis_status": "ver_siniestros", "claims.report": "ver_siniestros",
    "claims.doc_version": "ver_siniestros", "claims.evidence_file": "ver_siniestros", "claims.evidence_metadata": "ver_siniestros",
    "claims.evidence_zones": "ver_siniestros", "claims.evidence_zones_image": "ver_siniestros", "claims.export_zip": "ver_siniestros",
    "claims.verify": "ver_siniestros", "claims.new_claim": "editar_siniestros", "claims.add_photos": "editar_siniestros",
    "claims.reanalyze": "editar_siniestros", "claims.decide": "editar_siniestros", "claims.capture_link": "editar_siniestros",
    "claims.capture_sent": "editar_siniestros", "claims.ia_tarea": "editar_siniestros", "claims.ia_transcribir": "editar_siniestros",
    "claims.load_demo": "editar_siniestros", "claims.evidence_exclude": "editar_siniestros",
    "claims.evidence_restore": "editar_siniestros", "claims.evidence_purge": "eliminar_evidencia", "claims.derive": "editar_siniestros",
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
    "training.mark": "ensenar_modelo", "training.index": "ensenar_modelo", "training.preview": "ensenar_modelo",
    "training.remove": "ensenar_modelo", "training.export": "admin", "training.remask_all": "admin",
    "auth.account": None, "claims.set_client": "admin", "admin.user_reset_2fa": "usuarios", "admin.client_add": "admin",
    "admin.settings": "admin", "admin.users_view": "usuarios", "admin.user_toggle": "usuarios", "admin.firm_add": "admin",
}
ROLE_HELP = {"administrador": "Zelekpress: todas las empresas, empresas cliente, peritos y configuración.",
             "jefe": "Todos los siniestros de su empresa; crea a sus analistas e investigadores; reasigna; redes y métricas de su empresa.",
             "analista": "Solo los siniestros que tiene asignados: evidencia, portal del asegurado, derivar a perito y decidir.",
             "investigador": "Investigador interno de su empresa: expedientes y auditorías de informes.",
             "perito": "Perito o empresa externa: solo los expedientes derivados a su empresa."}
ACTION_LABELS = {"ingreso": "Ingresó", "ingreso_fallido": "Ingreso fallido", "salida": "Salió", "ver_caso": "Abrió el caso",
                 "decision": "Registró decisión", "descarga": "Descargó", "ver_expediente": "Abrió expediente",
                 "usuario": "Cambió un usuario", "exporta_excel": "Exportó a Excel", "reasignar": "Reasignó un caso",
                 "derivar": "Derivó a perito", "entregar_informe": "Entregó informe final", "quitar_archivo": "Quitó un archivo",
                 "ensenar_modelo": "Marcó una foto para el modelo", "exporta_entrenamiento": "Exportó el banco de entrenamiento",
                 "ia_texto": "Usó el asistente de texto (IA)", "2fa_activada": "Activó la verificación en dos pasos",
                 "2fa_quitada": "Quitó la verificación en dos pasos", "2fa_fallida": "Código de verificación incorrecto"}
MAX_FAILS, LOCK_SECONDS = 5, 300
DUMMY_HASH = generate_password_hash("not-a-user-password")
USERNAME = re.compile(r"^[a-z0-9._-]{3,32}$")


class UserStorageError(RuntimeError):
    pass


class _Rejected(Exception):
    pass


class Store:
    """Usuarios en la base de datos de Evidex (tabla usuarios). Misma interfaz que cuando era usuarios.json."""

    def __init__(self, workdir: Path):
        self.workdir = Path(workdir)
        self.log_path = self.workdir / "accesos.jsonl"
        self.marker = self.workdir / ".auth_initialized"
        try:
            self.db = open_db(self.workdir)          # la primera vez importa usuarios.json
        except DatabaseError as ex:
            raise UserStorageError(f"{ex} Acceso bloqueado.") from ex
        self.path = self.db.path
        if self.all():
            atomic_bytes(self.marker, b"initialized")
        self.state = AuthState(self.workdir / "auth.sqlite3")

    def _load(self, db) -> dict:
        users = {}
        for r in db.execute("SELECT * FROM usuarios"):
            u = dict(r)
            name = u.pop("username")
            extra = json.loads(u.pop("extra") or "{}")
            u = {**extra, **{k: v for k, v in u.items() if v is not None or k == "cliente"}}
            u["active"] = bool(u["active"])
            u["role"] = LEGACY_ROLES.get(u.get("role"), u.get("role"))
            if u["role"] not in ROLES or not isinstance(u.get("pw"), str):
                raise ValueError("invalid user")
            users[name] = u
        return users

    def all(self) -> dict:
        if not self.path.exists():
            if self.marker.exists():
                raise UserStorageError("Falta la base de datos de usuarios. Acceso bloqueado; restaure el respaldo.")
            return {}
        try:
            with self.db.read() as db:
                users = self._load(db)
        except (sqlite3.DatabaseError, DatabaseError, ValueError, TypeError) as ex:
            raise UserStorageError("No se puede leer el registro de usuarios. Acceso bloqueado; restaure el respaldo.") from ex
        if not users and self.marker.exists():
            raise UserStorageError("El registro de usuarios está vacío. Acceso bloqueado; restaure el respaldo.")
        return users

    def _mutate(self, change, need_admin: bool = True) -> str | None:
        """Aplica `change(users)` dentro de una transacción. Si devuelve un texto, es un error y no se guarda nada."""
        try:
            with self.db.tx() as db:
                users = self._load(db)
                before = {k: dict(v) for k, v in users.items()}
                err = change(users)
                if not err and need_admin and not any(x.get("role") == "administrador" and x.get("active", True)
                                                      for x in users.values()):
                    err = "Debe quedar al menos un administrador activo."
                if err:
                    raise _Rejected(err)                 # deshace la transacción
                for k, u in users.items():
                    if before.get(k) != u:
                        self._upsert(db, k, u)
        except _Rejected as r:
            return str(r)
        except (sqlite3.DatabaseError, DatabaseError, ValueError) as ex:
            raise UserStorageError("No se pudo guardar el usuario. Reintente; si sigue, restaure el respaldo.") from ex
        atomic_bytes(self.marker, b"initialized")
        return None

    @staticmethod
    def _upsert(db, username: str, u: dict) -> None:
        extra = {k: v for k, v in u.items() if k not in USER_COLS}
        vals = [username] + [u.get(c) for c in USER_COLS] + [json.dumps(extra, ensure_ascii=False)]
        vals[USER_COLS.index("active") + 1] = 1 if u.get("active", True) else 0
        cols = ("username",) + USER_COLS + ("extra",)
        db.execute(f"INSERT INTO usuarios ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                   f"ON CONFLICT(username) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols[1:])}", vals)

    def by_role(self, *roles: str) -> list[dict]:
        return sorted(({**u, "username": k} for k, u in self.all().items() if u.get("role") in roles and u.get("active", True)),
                      key=lambda u: u["name"].lower())

    def display_name(self, username: str) -> str:
        u = self.all().get(username or "")
        return u["name"] if u else (username or "")

    def enabled(self) -> bool:
        return any(u.get("active", True) for u in self.all().values())

    def get(self, username: str) -> dict | None:
        u = self.all().get(username)
        return {**u, "username": username} if u else None

    def add(self, username: str, name: str, role: str, password: str, empresa: str = "",
            cliente: str | None = None) -> str | None:
        """Crea o actualiza un usuario. Devuelve un mensaje de error o None."""
        username = username.strip().lower()
        role = LEGACY_ROLES.get(role, role)
        if not USERNAME.fullmatch(username):
            return "El usuario debe tener 3 a 32 letras minúsculas, números, punto, guion o guion bajo."
        if len(password) > 256:
            return "La contraseña no puede superar 256 caracteres."
        if role not in ROLES:
            return "Rol desconocido."
        if role == "perito" and not empresa.strip():
            return "Un perito debe pertenecer a una empresa de peritaje."
        cliente = (cliente or None) if role not in ("administrador", "perito") else None
        if cliente and not self._client_exists(cliente):
            return "Esa empresa cliente no existe."
        pw_hash = generate_password_hash(password) if password else None

        def change(users):
            if not users and role != "administrador":
                return "El primer usuario debe ser administrador."
            if username not in users and len(password) < 15:
                return "La contraseña debe tener al menos 15 caracteres."
            if password and len(password) < 15:
                return "La contraseña debe tener al menos 15 caracteres."
            u = users.get(username, {"created": _now()})
            u["auth_version"] = secrets.token_hex(16)
            u.update({"name": name.strip() or username, "role": role, "active": True,
                      "empresa": empresa.strip() if role == "perito" else "", "cliente": cliente})
            if pw_hash:
                u["pw"] = pw_hash
            users[username] = u
        return self._mutate(change)

    def _client_exists(self, slug: str) -> bool:
        with self.db.read() as db:
            return db.execute("SELECT 1 FROM empresas WHERE slug=?", (slug,)).fetchone() is not None

    def set_active(self, username: str, active: bool) -> str | None:
        def change(users):
            if username not in users:
                return "No existe ese usuario."
            users[username]["active"] = active
            users[username]["auth_version"] = secrets.token_hex(16)
        return self._mutate(change)

    def set_totp(self, username: str, secret: str | None) -> None:
        """Activa (con su secreto) o quita la verificación en dos pasos de un usuario."""
        def change(users):
            u = users.get(username)
            if u is None:
                return
            if secret:
                u.update({"totp": secret, "totp_since": _now()})
            else:
                for k in ("totp", "totp_since", "totp_step"):
                    u.pop(k, None)
            u["auth_version"] = secrets.token_hex(16)            # cierra las sesiones abiertas
        self._mutate(change, need_admin=False)

    def check_totp(self, username: str, code: str, ip: str = "local"):
        """Segundo paso del ingreso. Mismos límites de intentos que la contraseña."""
        from evidex.accounts import totp
        username = (username or "").strip().lower()[:128]

        def verify():
            u = self.get(username)
            if not u or not u.get("totp") or not u.get("active", True):
                return None
            step = totp.verify(u["totp"], code, u.get("totp_step"))
            if step is None:
                return None
            self._save_step(username, step)
            return self.get(username)
        u, err = self.state.check(username + "#2fa", ip, verify)
        return u, (err.replace("Usuario o contraseña incorrectos.", "Código incorrecto o vencido.") if err else None)

    def _save_step(self, username: str, step: int) -> None:
        def change(users):
            if username in users:
                users[username]["totp_step"] = step
        self._mutate(change, need_admin=False)

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
