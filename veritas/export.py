"""Exporta un paquete que un tercero puede verificar sin instalar Veritas ni confiar en nosotros."""
from __future__ import annotations

import zipfile
from pathlib import Path

VERIFIER = '''#!/usr/bin/env python3
"""Verificador independiente de paquetes Veritas.

Uso:  python verify.py            (dentro de la carpeta del paquete extraído)
Requiere Python 3.9+. La firma requiere: pip install cryptography
"""
import base64, hashlib, json, sys
from pathlib import Path

GENESIS = "0" * 64
here = Path(__file__).parent

def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
def h(e): return hashlib.sha256(canon({k: v for k, v in e.items() if k != "hash"})).hexdigest()

entries = [json.loads(l) for l in (here / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
ok = True
prev = GENESIS
for i, e in enumerate(entries):
    if e["seq"] != i or e["prev"] != prev or h(e) != e["hash"]:
        print(f"[FALLA] cadena rota en la entrada {i}"); ok = False; break
    prev = e["hash"]
else:
    print(f"[OK] cadena de custodia íntegra ({len(entries)} entradas)")

for e in entries:
    if e["action"] != "evidence_added":
        continue
    f = here / "evidence" / e["subject"]
    if not f.exists():
        print(f"[FALLA] falta evidencia {e['data']['original_name']}"); ok = False; continue
    if hashlib.sha256(f.read_bytes()).hexdigest() != e["subject"]:
        print(f"[FALLA] evidencia alterada: {e['data']['original_name']}"); ok = False
    else:
        print(f"[OK] evidencia {e['data']['original_name']} ({e['subject'][:12]}…)")

try:
    from cryptography.hazmat.primitives import serialization
    seal = json.loads((here / "seal.json").read_text(encoding="utf-8"))
    head = entries[-1]["hash"] if entries else GENESIS
    if seal["head"] != head or seal["length"] != len(entries):
        print("[FALLA] el sello no corresponde al estado actual"); ok = False
    else:
        pub = serialization.load_pem_public_key((here / "public_key.pem").read_bytes())
        pub.verify(base64.b64decode(seal["signature"]), head.encode())
        print("[OK] firma digital válida")
except ImportError:
    print("[AVISO] instale 'cryptography' para verificar la firma")
except Exception as ex:
    print(f"[FALLA] firma inválida ({type(ex).__name__})"); ok = False

sys.exit(0 if ok else 1)
'''


def export_bundle(case, report_html: str, out_zip: Path) -> Path:
    case.ledger.seal()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("ledger.jsonl", "seal.json", "public_key.pem", "case.json"):
            z.write(case.root / name, name)
        for f in case.evidence_dir.iterdir():
            z.write(f, f"evidence/{f.name}")
        z.writestr("informe.html", report_html)
        z.writestr("verify.py", VERIFIER)
    return Path(out_zip)
