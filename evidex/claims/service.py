"""Operaciones de siniestros compartidas por la línea de comandos y la interfaz web."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from evidex.paths import DEMO_DIR
from evidex.core import assistant
from evidex.forensics import chile
from evidex.claims import analysis as claims
from evidex.forensics import documents
from evidex.forensics import forensic_timeline
from evidex.forensics import narrative
from evidex.forensics import network
from evidex.forensics import policy
from evidex.claims import report
from evidex.forensics import whatsapp
from evidex.core.case import Case
from evidex.core.timeline import Timeline

SEV_ORDER = {"alta": 0, "media": 1, "baja": 2}
CATEGORIES = ["Red de siniestros", "Línea de tiempo", "Póliza y siniestro", "Documentos", "Fotos", "Comunicaciones",
              "Relato", "Datos del asegurado"]
DEMO_SCRIPT = DEMO_DIR / "make_claim_demo.py"


DECISIONS = {"en_revision": "En revisión", "fraude": "Fraude confirmado", "legitimo": "Legítimo (pagado)",
             "rechazado": "Rechazado por otra causa"}


def case_id(numero: str) -> str:
    """Nombre de carpeta seguro para un número de siniestro."""
    return re.sub(r"[^\w\-.]", "_", str(numero).strip()).strip("._") or "siniestro"


def claim_cases(workdir: Path) -> list[Case]:
    out = []
    for d in sorted(Path(workdir).iterdir()) if Path(workdir).is_dir() else []:
        c = Case(d)
        if c.meta_path.exists() and c.kind == "claim":
            out.append(c)
    return out


def declaration(case: Case) -> dict | None:
    for e in case.ledger.entries():
        if e["action"] == "evidence_added" and e["data"].get("note") == "declaracion":
            return claims.read_declaration(case.evidence_dir / e["subject"])
    return None


def last_analysis(case: Case) -> dict | None:
    for e in reversed(case.ledger.entries()):
        if e["action"] == "claim_analyzed":
            return {**e["data"], "ts": e["ts"]}
    return None


def has_evidence(case: Case, digest: str) -> bool:
    return any(e["action"] == "evidence_added" and e["subject"] == digest for e in case.ledger.entries())


def evidence_note(filename) -> str | None:
    """Clasifica un archivo: 'foto', 'documento', 'chat' o None si no se admite.
    Los .txt y .zip solo se aceptan si el archivo existe y es un chat de WhatsApp exportado."""
    ext = Path(filename).suffix.lower()
    if ext in claims.IMAGE_EXT:
        return "foto"
    if ext in documents.DOC_EXT:
        return "documento"
    if ext in whatsapp.CHAT_EXT:
        return "chat" if Path(filename).is_file() and whatsapp.looks_like_chat(Path(filename)) else None
    return None


def load_config(workdir: Path) -> dict:
    try:
        return json.loads((Path(workdir) / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _cached_external(case: Case) -> dict:
    """Resultados ya pagados de servicios externos, aunque hoy no estén configurados."""
    try:
        return json.loads((case.root / "servicios_externos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_chats(case: Case, tl, t0) -> list:
    """Chats exportados del caso: [(prefijo, Chat, mensajes relevantes)], registrados en la línea de tiempo."""
    out = []
    for e in case.active_evidence():
        if e["data"].get("note") != "chat":
            continue
        chat = whatsapp.read(case.evidence_dir / e["subject"], e["data"]["original_name"])
        if chat is None:
            continue
        prefix = e["subject"][:8]
        msgs = whatsapp.relevant(chat, t0)
        tl.add_events((f"{prefix}:{m.line}", m.ts.isoformat(), chat.name, "chat", None, m.sender,
                       f"{m.sender}: {'(mensaje eliminado)' if m.deleted else m.text[:300]}") for m in chat.messages)
        out.append((prefix, chat, msgs))
    return out


def run_analysis(case: Case, registry_path: Path | None = None, use_llm: bool = False):
    """Ejecuta todos los análisis. Devuelve (decl, decl_ev, fotos, documentos, hallazgos, red, resumen verificado)."""
    db = case.root / "timeline.db"
    tl = Timeline(db, fresh=True)
    try:
        decl, decl_ev, photos = claims.load_case(case, tl)
        docs = documents.load(case, tl)
        registry = claims.load_registry(registry_path)
        others = claims.registry_claims(registry)
        findings = claims.analyze(decl, decl_ev, photos, registry)
        findings += documents.analyze(decl, decl_ev, docs, registry)
        findings += policy.analyze(decl, decl_ev)
        findings += narrative.analyze(decl, decl_ev, others)
        net_findings, net = network.analyze(decl, decl_ev, photos, docs, registry)
        findings += net_findings
        from datetime import datetime as _dt
        chats = load_chats(case, tl, _dt.fromisoformat(decl["fecha_siniestro"]))
        findings += whatsapp.analyze(decl, decl_ev, [(p, c) for p, c, _ in chats], registry)
        findings += chile.analyze(decl, decl_ev, docs)
        events = forensic_timeline.build(decl, decl_ev, photos, docs, chats)
        findings += forensic_timeline.impossibilities(decl, decl_ev, events, docs)
        from evidex.forensics import external
        findings += external.findings(photos, external.run(case, photos, load_config(case.root.parent))
                                      or _cached_external(case))
        net["timeline"] = events          # la línea de tiempo forense viaja con el resto del análisis
        net["chats"] = chats
        findings.sort(key=lambda f: (SEV_ORDER[f.severity], CATEGORIES.index(f.category) if f.category in CATEGORIES else 9))
        # el resumen destaca lo más grave; el detalle completo va en la sección de hallazgos
        key = [f for f in findings if f.severity == "alta"] or [f for f in findings if f.severity == "media"]
        verified = assistant.summarize(key, tl, use_llm=use_llm)
    finally:
        tl.close()
    return decl, decl_ev, photos, docs, findings, net, verified


def find_case(workdir: Path, numero: str) -> Case | None:
    """Busca en la carpeta de casos el siniestro con ese número."""
    direct = Case(Path(workdir) / case_id(numero))
    if direct.meta_path.exists():
        return direct
    for d in Path(workdir).iterdir() if Path(workdir).is_dir() else []:
        c = Case(d)
        if c.meta_path.exists() and c.kind == "claim" and (declaration(c) or {}).get("numero") == numero:
            return c
    return None


import threading as _threading
_LOCKS: dict[str, _threading.RLock] = {}
_LOCKS_GUARD = _threading.Lock()


def _case_lock(case: Case) -> _threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(case.root.resolve()), _threading.RLock())


def analyze_claim(case: Case, registry_path: Path | None = None, use_llm: bool = False,
                  cascade: bool = True, trigger: str | None = None) -> dict:
    """Un solo análisis a la vez por caso (dos pestañas abiertas no chocan)."""
    with _case_lock(case):
        return _analyze_claim(case, registry_path, use_llm, cascade, trigger)


def _analyze_claim(case: Case, registry_path: Path | None = None, use_llm: bool = False,
                   cascade: bool = True, trigger: str | None = None) -> dict:
    """Analiza el siniestro, registra el resultado en la custodia y escribe informe.html.

    Con `cascade`, los siniestros ya existentes que quedan vinculados a este se reanalizan una vez,
    para que un caso antiguo que parecía limpio refleje la nueva evidencia de la red."""
    decl, decl_ev, photos, docs, findings, net, verified = run_analysis(case, registry_path, use_llm)
    rec = claims.recommendation(findings)
    score = claims.risk_score(findings)
    if not photos and not docs and (case.root / "captura.json").exists():
        # caso recién registrado que espera lo que suba el asegurado por el portal
        rec = ("Esperando evidencia del asegurado", "none")
    by_cat: dict[str, int] = {}
    for f in findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    result = {
        "photos": len(photos), "documents": len(docs), "findings": len(findings),
        "high": sum(1 for f in findings if f.severity == "alta"), "linked": len(net["neighbors"]),
        "score": score, "recommendation": rec[0], "level": rec[1],
        "categories": by_cat, "rules": sorted({f.rule for f in findings}),
    }
    if trigger:
        result["trigger"] = f"reanálisis por vínculo con {trigger}"
    case.ledger.append("evidex", "claim_analyzed", decl["numero"], result)
    case.ledger.seal()
    write_snapshot(case, photos, docs, findings)
    (case.root / "informe.html").write_text(
        report.build_claim(case, decl, decl_ev, photos, findings, verified, rec, docs=docs, net=net, score=score),
        encoding="utf-8")
    if registry_path:
        claims.update_registry(Path(registry_path), decl["numero"], photos, docs, decl, rec[1])
        if cascade:
            result["reanalyzed"] = []
            for nb in sorted(set(net["neighbors"]) | set(net["group"])):
                other = find_case(Path(registry_path).parent, nb)
                if other is not None and other.root != case.root:
                    analyze_claim(other, registry_path, use_llm, cascade=False, trigger=decl["numero"])
                    result["reanalyzed"].append(nb)
    return result


# ---- resumen para la ficha del caso ----------------------------------------------------
SNAPSHOT = "analisis.json"
ANALYSIS_VERSION = "2026-10-04b"   # súbalo al agregar pruebas: los casos abiertos se reanalizan


def write_snapshot(case: Case, photos, docs, findings) -> None:
    """Guarda fotos, documentos y hallazgos del último análisis, para mostrarlos sin volver a analizar.
    Es un derivado del análisis (la fuente de verdad es la evidencia y la cadena de custodia)."""
    def ev_of(f):
        return sorted({e.split(":")[0] for e in f.evidence})

    def photo(p):
        m = p.meta
        portal = m.get("portal") or {}
        return {"digest": p.digest, "name": p.name, "title": portal.get("title") or p.name, "taken": m.get("taken"),
                "camera": " ".join(filter(None, [m.get("make"), m.get("model")])) or None, "gps": m.get("gps"),
                "received": m.get("received"), "origin": "asegurado (portal)" if portal or m.get("secure_capture") else "analista",
                "secure": bool(m.get("secure_capture"))}

    def doc(d):
        m = d.meta
        return {"digest": d.digest, "name": d.name, "title": m.get("title") or d.name, "producer": m.get("producer") or
                m.get("creator"), "versions": len(m.get("versions") or []), "scanned": bool(m.get("ocr"))}

    from evidex.claims import photo_checks
    cited: dict[str, list] = {}
    for f in findings:
        for e in ev_of(f):
            cited.setdefault(e, []).append(f)
    shots = []
    for p in photos:
        row = photo(p)
        row["checks"] = photo_checks.run(p.meta, cited.get(p.digest[:8], []))
        shots.append(row)
    data = {"photos": shots, "docs": [doc(d) for d in docs],
            "findings": [{"rule": f.rule, "severity": f.severity, "title": f.title, "summary": f.summary,
                          "category": f.category, "evidence": ev_of(f)} for f in findings]}
    (case.root / SNAPSHOT).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def snapshot(case: Case) -> dict:
    try:
        return json.loads((case.root / SNAPSHOT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"photos": [], "docs": [], "findings": []}


# ---- decisiones del liquidador --------------------------------------------------
def set_decision(case: Case, value: str, actor: str, note: str = "", source: str = "liquidador") -> dict:
    if value not in DECISIONS:
        raise ValueError(f"decisión no válida: {value}")
    return case.ledger.append(actor or "liquidador", "decision", value,
                              {"label": DECISIONS[value], "note": note, "source": source})


def decision_history(case: Case) -> list[dict]:
    return [e for e in case.ledger.entries() if e["action"] == "decision"]


def current_decision(case: Case) -> dict | None:
    h = decision_history(case)
    return h[-1] if h else None


# ---- métricas ------------------------------------------------------------------
def metrics(workdir: Path) -> dict:
    """Desempeño de Evidex contra las decisiones finales de los liquidadores.

    Se considera "alerta" la recomendación de derivar a investigación. Solo cuentan los casos
    con decisión final de fraude confirmado o legítimo; los demás quedan como pendientes."""
    from collections import Counter

    from evidex.forensics.policy import parse_amount
    rows = []
    for c in claim_cases(workdir):
        last = last_analysis(c) or {}
        dec = current_decision(c)
        decl = declaration(c) or {}
        rows.append({"numero": decl.get("numero", c.root.name), "id": c.root.name, "level": last.get("level"),
                     "score": last.get("score", 0), "decision": dec["subject"] if dec else None,
                     "monto": parse_amount(decl.get("monto_reclamado")) or 0,
                     "rules": last.get("rules", []), "categories": last.get("categories", {})})
    fraud = [r for r in rows if r["decision"] == "fraude"]
    legit = [r for r in rows if r["decision"] == "legitimo"]
    tp = [r for r in fraud if r["level"] == "bad"]
    fn = [r for r in fraud if r["level"] != "bad"]
    fp = [r for r in legit if r["level"] == "bad"]
    tn = [r for r in legit if r["level"] != "bad"]

    def pct(a, b):
        return round(100 * a / b) if b else None

    rules, cats = Counter(), Counter()
    for r in rows:
        rules.update(r["rules"])
        cats.update(r["categories"])
    return {
        "total": len(rows),
        "levels": Counter(r["level"] for r in rows),
        "decisions": Counter(r["decision"] or "pendiente" for r in rows),
        "tp": len(tp), "fn": len(fn), "fp": len(fp), "tn": len(tn),
        "precision": pct(len(tp), len(tp) + len(fp)), "recall": pct(len(tp), len(fraud)),
        "false_alarm": pct(len(fp), len(legit)),
        "monto_detectado": sum(r["monto"] for r in tp), "monto_fraude": sum(r["monto"] for r in fraud),
        "monto_pendiente_alerta": sum(r["monto"] for r in rows if r["level"] == "bad" and r["decision"] in (None, "en_revision")),
        "pendientes_alerta": [r for r in sorted(rows, key=lambda r: -r["score"]) if r["level"] == "bad" and r["decision"] in (None, "en_revision")],
        "missed": fn, "false_alarms": fp,
        "rules": rules.most_common(), "categories": cats.most_common(),
    }


def create_claim(workdir: Path, cid: str, decl_path: Path, files: list[Path]) -> Case:
    case = Case.create(Path(workdir) / cid, f"Siniestro {cid}", kind="claim")
    case.add_evidence(decl_path, note="declaracion")
    for f in files:
        note = evidence_note(f)
        if note:
            case.add_evidence(f, note=note)
    return case


def load_demo(workdir: Path) -> list[tuple[str, dict]]:
    """Genera el ejemplo (siniestros históricos + uno sospechoso + uno limpio) y lo analiza en orden."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    registry = workdir / "registro.jsonl"
    results = []
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "demo"
        subprocess.run([sys.executable, str(DEMO_SCRIPT), str(d)], check=True, capture_output=True)
        for folder in json.loads((d / "orden.json").read_text(encoding="utf-8")):
            src = d / folder
            numero = claims.read_declaration(src / "declaracion.json")["numero"]
            if (workdir / numero / "case.json").exists():
                continue
            files = sorted(p for sub in ("fotos", "documentos") if (src / sub).exists() for p in (src / sub).iterdir())
            case = create_claim(workdir, numero, src / "declaracion.json", files)
            results.append((numero, analyze_claim(case, registry)))
    return results
