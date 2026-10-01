"""Genera un caso sintético: fuerza bruta -> acceso -> PowerShell ofuscado -> persistencia -> borrado de logs."""
import json
import sys
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_events.jsonl")
ev = []
def add(ts, eid, user, msg, host="SRV-FIN-01", src="Security"):
    ev.append({"ts": ts, "host": host, "source": src, "event_id": eid, "user": user, "message": msg})

add("2026-09-28T02:10:00Z", 4624, "mperez", "Logon normal interactivo")
for m in range(0, 7):
    add(f"2026-09-28T03:1{m}:00Z", 4625, "admin.contab", "Logon fallido desde 203.0.113.50")
add("2026-09-28T03:18:30Z", 4624, "admin.contab", "Logon exitoso desde 203.0.113.50")
add("2026-09-28T03:22:10Z", 4104, "admin.contab", "powershell.exe -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA", src="PowerShell")
add("2026-09-28T03:25:44Z", 4732, "admin.contab", "Miembro agregado al grupo Administradores: soporte_tmp")
add("2026-09-28T03:31:02Z", 7045, "SYSTEM", "Servicio instalado: UpdSvcHost", src="System")
add("2026-09-28T03:40:00Z", 1102, "admin.contab", "Se borró el registro de auditoría")
out.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in ev) + "\n", encoding="utf-8")
print(f"{len(ev)} eventos -> {out}")
