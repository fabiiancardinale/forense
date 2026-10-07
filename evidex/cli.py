"""CLI de Evidex.

  evidex init  CASO "Nombre"
  evidex add   CASO archivo [--note ...]     # agrega evidencia (hash + custodia)
  evidex ingest CASO                          # construye la línea de tiempo
  evidex report CASO [--llm] [--ovi]          # análisis + informe HTML
  evidex export CASO salida.zip               # paquete verificable por terceros
  evidex verify CASO                          # comprueba integridad

Siniestros (seguros de autos):
  evidex demo casos                           # carga el ejemplo completo
  evidex siniestro-init CASO declaracion.json foto1.jpg presupuesto.pdf ...
  evidex add CASO foto3.jpg --note foto       # agregar fotos después
  evidex siniestro-analizar CASO --registro registro.jsonl
  evidex export CASO salida.zip
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evidex.core import assistant
from evidex.claims import analysis as claims
from evidex.core import detections
from evidex.core import export
from evidex.claims import report
from evidex.claims import service
from evidex.core.case import Case
from evidex.core.ledger import verify_chain
from evidex.core.timeline import Timeline


def _timeline(case: Case, rebuild=False) -> Timeline:
    db = case.root / "timeline.db"
    return Timeline(db, fresh=rebuild)


def cmd_init(a):
    Case.create(Path(a.case), a.name)
    print(f"Caso creado en {a.case}")


def cmd_add(a):
    d = _open_case(a.case).add_evidence(Path(a.file), note=a.note)
    print(f"Evidencia registrada: {d}")


def cmd_ingest(a):
    case = _open_case(a.case)
    tl = _timeline(case, rebuild=True)
    total = 0
    for e in case.ledger.entries():
        if e["action"] == "evidence_added" and e["subject"] not in case.purged():
            n = tl.ingest(case.evidence_dir / e["subject"], e["subject"], e["data"]["original_name"])
            total += n
            print(f"  {e['data']['original_name']}: {n} eventos")
    case.ledger.append("evidex", "timeline_built", "timeline.db", {"events": total})
    print(f"Línea de tiempo: {total} eventos")


def cmd_report(a):
    case = _open_case(a.case)
    tl = _timeline(case)
    findings = detections.run_all(tl.all())
    verified = assistant.summarize(findings, tl, use_llm=a.llm)
    case.ledger.append("evidex", "analysis_run", "findings", {"count": len(findings)})
    case.ledger.seal()
    out = case.root / "informe.html"
    out.write_text(report.build(case, tl, findings, verified, ovi=a.ovi), encoding="utf-8")
    print(f"{len(findings)} hallazgos. Informe: {out}")


def _open_case(path) -> Case:
    case = Case(Path(path))
    if not case.meta_path.exists():
        sys.exit(f"No existe el caso '{path}'. Créelo primero (init o siniestro-init).")
    return case


def cmd_claim_init(a):
    if (Path(a.case) / "case.json").exists():
        sys.exit(f"El caso '{a.case}' ya existe. Use otro nombre o bórrelo antes de crearlo de nuevo.")
    for f in [a.declaracion, *a.fotos]:
        if not Path(f).is_file():
            sys.exit(f"No se encuentra el archivo '{f}'.")
    if bad := [f for f in a.fotos if service.evidence_note(f) is None]:
        sys.exit("Estos archivos no son fotos ni PDF ni chats de WhatsApp: " + ", ".join(bad))
    try:
        decl = claims.read_declaration(Path(a.declaracion))
    except (ValueError, json.JSONDecodeError) as ex:
        sys.exit(f"La declaración no es un JSON válido: {ex}")
    for k in ("numero", "fecha_siniestro"):
        if k not in decl:
            sys.exit(f"falta el campo '{k}' en la declaración")
    case = Case.create(Path(a.case), f"Siniestro {decl['numero']}", kind="claim")
    case.add_evidence(Path(a.declaracion), note="declaracion")
    for f in a.fotos:
        case.add_evidence(Path(f), note=service.evidence_note(f))
    n_docs = sum(1 for f in a.fotos if service.evidence_note(f) == "documento")
    print(f"Siniestro {decl['numero']} creado con {len(a.fotos) - n_docs} foto(s) y {n_docs} documento(s) en {a.case}")


def cmd_demo(a):
    work = Path(a.carpeta)
    loaded = service.load_demo(work)
    if not loaded:
        print("El ejemplo ya estaba cargado en esa carpeta.")
    for numero, _ in loaded:  # estado final, después de los reanálisis por vínculo
        r = service.last_analysis(service.find_case(work, numero))
        print(f"  {numero}: riesgo {r['score']:>3}, {r['findings']:>2} hallazgo(s), {r['linked']} vinculado(s) · {r['recommendation']}")
    print(f"Casos en {Path(a.carpeta).resolve()} · abra la interfaz con: python -m evidex.web --dir {a.carpeta}")


def cmd_claim_analyze(a):
    case = _open_case(a.case)
    r = service.analyze_claim(case, Path(a.registro) if a.registro else None, a.llm)
    print(f"{r['photos']} fotos, {r['findings']} hallazgos. Recomendación: {r['recommendation']}")
    print(f"Informe: {case.root / 'informe.html'}")


def cmd_export(a):
    case = _open_case(a.case)
    if case.kind == "claim":
        # usa el informe ya generado para no perder hallazgos que dependen del registro
        rep = case.root / "informe.html"
        if not rep.exists():
            sys.exit("primero ejecute: evidex siniestro-analizar")
        case.ledger.seal()
        print(f"Paquete: {export.export_bundle(case, rep.read_text(encoding='utf-8'), Path(a.out))}")
        return
    tl = _timeline(case)
    findings = detections.run_all(tl.all())
    verified = assistant.summarize(findings, tl)
    case.ledger.seal()
    html = report.build(case, tl, findings, verified)
    print(f"Paquete: {export.export_bundle(case, html, Path(a.out))}")


def cmd_verify(a):
    case = _open_case(a.case)
    ok, msg = verify_chain(case.ledger.entries())
    ev_ok, problems = case.verify_evidence()
    print(("OK  " if ok else "FALLA ") + msg)
    print("OK  evidencia íntegra" if ev_ok else "FALLA " + "; ".join(problems))
    sys.exit(0 if ok and ev_ok else 1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="evidex")
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("init"); x.add_argument("case"); x.add_argument("name"); x.set_defaults(f=cmd_init)
    x = s.add_parser("add"); x.add_argument("case"); x.add_argument("file"); x.add_argument("--note", default=""); x.set_defaults(f=cmd_add)
    x = s.add_parser("ingest"); x.add_argument("case"); x.set_defaults(f=cmd_ingest)
    x = s.add_parser("report"); x.add_argument("case"); x.add_argument("--llm", action="store_true"); x.add_argument("--ovi", action="store_true"); x.set_defaults(f=cmd_report)
    x = s.add_parser("siniestro-init", help="crea un caso de siniestro con su declaración, fotos y documentos PDF")
    x.add_argument("case"); x.add_argument("declaracion"); x.add_argument("fotos", nargs="*"); x.set_defaults(f=cmd_claim_init)
    x = s.add_parser("siniestro-analizar", help="analiza las fotos y genera el informe para el liquidador")
    x.add_argument("case"); x.add_argument("--registro", help="registro compartido entre siniestros (.jsonl)")
    x.add_argument("--llm", action="store_true"); x.set_defaults(f=cmd_claim_analyze)
    x = s.add_parser("demo", help="crea siniestros de ejemplo (red de fraude, uno sospechoso y uno limpio)")
    x.add_argument("carpeta", nargs="?", default="casos"); x.set_defaults(f=cmd_demo)
    x = s.add_parser("export"); x.add_argument("case"); x.add_argument("out"); x.set_defaults(f=cmd_export)
    x = s.add_parser("verify"); x.add_argument("case"); x.set_defaults(f=cmd_verify)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
