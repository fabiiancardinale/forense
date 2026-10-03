"""Red de siniestros vinculados: detecta personas, cuentas, fotos y documentos compartidos.

El fraude organizado rara vez se ve en un siniestro aislado; aparece cuando distintos
asegurados comparten un teléfono, una cuenta para el pago, un correo, las mismas fotos,
el mismo documento o un relato copiado. Este módulo:
  1. Normaliza los datos de contacto de cada siniestro y los guarda en el registro.
  2. Marca los datos compartidos con siniestros de OTROS asegurados.
  3. Cuenta siniestros previos del mismo RUT o patente en los últimos 12 meses.
  4. Arma el grafo de vínculos fuertes y detecta grupos de 3 o más siniestros conectados.
  5. Encuentra todas las redes de la cartera (vista global).

El grafo usa índices por dato compartido y calcula los vecinos de cada siniestro solo cuando
se necesitan, para que funcione con miles de siniestros.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta

from evidex.claims.analysis import DUP_MAX_DISTANCE, hamming
from evidex.core.detections import Finding
from evidex.forensics.narrative import COPY_ALERT, similarity

LABELS = {"rut": "RUT", "telefono": "teléfono", "email": "correo", "cuenta_bancaria": "cuenta bancaria",
          "direccion": "dirección", "taller": "taller", "patente": "patente"}
SAME = {"rut": "el mismo RUT", "telefono": "el mismo teléfono", "email": "el mismo correo",
        "cuenta_bancaria": "la misma cuenta bancaria", "direccion": "la misma dirección",
        "taller": "el mismo taller", "patente": "la misma patente"}
STRONG = ("telefono", "email", "cuenta_bancaria")   # compartidos entre personas distintas: señal fuerte
FREQ_WINDOW = timedelta(days=365)
FREQ_WARN, FREQ_ALERT = 2, 3
RING_MIN = 3


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


def normalize(key: str, value) -> str:
    if value in (None, ""):
        return ""
    v = str(value).strip()
    if key == "rut":
        return re.sub(r"[^0-9kK]", "", v).upper()
    if key == "telefono":
        return re.sub(r"\D", "", v)[-8:]
    if key == "email":
        return v.lower()
    if key == "cuenta_bancaria":
        return re.sub(r"[^0-9A-Za-z]", "", v).upper()
    if key == "patente":
        return re.sub(r"[^A-Z0-9]", "", v.upper())
    return _plain(v)


def entities(decl: dict) -> dict[str, str]:
    return {k: n for k in LABELS if (n := normalize(k, decl.get(k)))}


def claim_record(decl: dict, level: str | None) -> dict:
    """Ficha del siniestro que se guarda en el registro compartido."""
    from evidex.forensics.policy import parse_amount
    return {"type": "claim", "claim": decl["numero"], "fecha": decl.get("fecha_siniestro"),
            "asegurado": decl.get("asegurado", ""), "level": level, "relato": decl.get("descripcion", ""),
            "monto": parse_amount(decl.get("monto_reclamado")),
            "display": {k: str(decl[k]) for k in LABELS if decl.get(k)}, **{"e_" + k: v for k, v in entities(decl).items()}}


def _ent(rec: dict) -> dict[str, str]:
    return {k[2:]: v for k, v in rec.items() if k.startswith("e_")}


class Graph:
    """Grafo de vínculos fuertes entre siniestros, con vecinos calculados bajo demanda."""

    def __init__(self, nodes: dict[str, dict], photos: list[dict], docs: list[dict]):
        self.nodes = nodes
        self.ent = {n: _ent(r) for n, r in nodes.items()}
        self.index: dict[tuple, set[str]] = defaultdict(set)
        for n, e in self.ent.items():
            for k in STRONG:
                if e.get(k):
                    self.index[(k, e[k])].add(n)
        self.relatos = [(n, r["relato"]) for n, r in nodes.items() if r.get("relato")]
        self.photos = photos
        self.photos_of: dict[str, list[dict]] = defaultdict(list)
        for p in photos:
            self.photos_of[p["claim"]].append(p)
        self.docs_by_sha: dict[str, set[str]] = defaultdict(set)
        self.docs_of: dict[str, list[str]] = defaultdict(list)
        for d in docs:
            self.docs_by_sha[d["sha256"]].add(d["claim"])
            self.docs_of[d["claim"]].append(d["sha256"])
        self._cache: dict[str, dict[str, set[str]]] = {}

    def neighbors(self, a: str) -> dict[str, set[str]]:
        if a in self._cache:
            return self._cache[a]
        out: dict[str, set[str]] = defaultdict(set)
        ea = self.ent.get(a, {})
        for k in STRONG:
            if not ea.get(k):
                continue
            for b in self.index[(k, ea[k])]:
                eb = self.ent.get(b, {})
                if b != a and ea.get("rut") and eb.get("rut") and ea["rut"] != eb["rut"]:
                    out[b].add(SAME[k].split(" ", 1)[1])
        ra = self.nodes.get(a, {}).get("relato")
        if ra:
            for b, rb in self.relatos:
                if b != a and similarity(ra, rb) >= COPY_ALERT:
                    out[b].add("relato copiado")
        for p in self.photos_of.get(a, []):
            for q in self.photos:
                if q["claim"] != a and (q["sha256"] == p["sha256"] or hamming(q["dhash"], p["dhash"]) <= DUP_MAX_DISTANCE):
                    out[q["claim"]].add("misma foto")
        for sha in self.docs_of.get(a, []):
            for b in self.docs_by_sha[sha]:
                if b != a:
                    out[b].add("mismo documento")
        self._cache[a] = out
        return out

    def component(self, start: str) -> set[str]:
        seen, queue = {start}, deque([start])
        while queue:
            for nb in self.neighbors(queue.popleft()):
                if nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        return seen

    def edges_within(self, members: set[str]) -> list[tuple[str, str, str]]:
        return sorted({tuple(sorted((a, b))) + (", ".join(sorted(w)),)
                       for a in members for b, w in self.neighbors(a).items() if b in members})


def _registry_parts(registry: list[dict]):
    from evidex.claims.analysis import registry_claims
    nodes = registry_claims(registry)
    photos = [r for r in registry if r.get("type", "photo") == "photo" and "dhash" in r]
    docs = [r for r in registry if r.get("type") == "doc"]
    return nodes, photos, docs


def analyze(decl: dict, decl_ev: str, photos, docs, registry: list[dict]) -> tuple[list[Finding], dict]:
    """Devuelve hallazgos y la estructura de la red para el informe."""
    numero = decl["numero"]
    ts = decl["fecha_siniestro"]
    t0 = datetime.fromisoformat(ts)
    nodes, reg_photos, reg_docs = _registry_parts(registry)
    others = {k: v for k, v in nodes.items() if k != numero}
    me = claim_record(decl, None)
    ent = _ent(me)
    out: list[Finding] = []

    def add(rule, sev, title, summary):
        out.append(Finding(rule, sev, title, summary, [decl_ev], ts, "Red de siniestros"))

    # 1. datos compartidos con siniestros de otros asegurados (búsqueda por índice)
    by_value: dict[tuple, set[str]] = defaultdict(set)
    for num, rec in others.items():
        for k, v in _ent(rec).items():
            if k in ("telefono", "email", "cuenta_bancaria", "direccion", "rut", "patente"):
                by_value[(k, v)].add(num)
    direct: dict[str, list[str]] = {}
    candidates = set().union(*(by_value.get((k, ent[k]), set())
                               for k in ("telefono", "email", "cuenta_bancaria", "direccion") if ent.get(k))) \
        if ent else set()
    for num in sorted(candidates):
        eo = _ent(others[num])
        if not (ent.get("rut") and eo.get("rut") and ent["rut"] != eo["rut"]):
            continue
        shared = [k for k in ("telefono", "email", "cuenta_bancaria", "direccion") if ent.get(k) and ent[k] == eo.get(k)]
        direct[num] = [SAME[k].split(" ", 1)[1] for k in shared]
        strong = [k for k in shared if k in STRONG]
        labels = " y ".join(f"{SAME[k]} ({me['display'].get(k, '')})" for k in shared)
        add("shared_contact", "alta" if strong else "media", f"Datos compartidos con otro asegurado ({num})",
            f"El siniestro {num}, de otro asegurado, tiene {labels}.")

    # 2. frecuencia del mismo RUT o patente
    for key in ("rut", "patente"):
        if not ent.get(key):
            continue
        prev = []
        for num in by_value.get((key, ent[key]), ()):
            f = others[num].get("fecha")
            if f and timedelta(0) <= t0 - datetime.fromisoformat(f) <= FREQ_WINDOW:
                prev.append(num)
        if len(prev) >= FREQ_WARN:
            add(f"frequency_{key}", "alta" if len(prev) >= FREQ_ALERT else "media",
                f"Siniestros repetidos con {SAME[key]}",
                f"{SAME[key].capitalize()} registra {len(prev)} siniestro(s) en los 12 meses anteriores ({', '.join(sorted(prev))}).")

    # 3. grafo y grupo conectado
    all_nodes = {**others, numero: me}
    reg_photos = [p for p in reg_photos if p["claim"] != numero]
    reg_photos += [{"claim": numero, "sha256": p.digest, "dhash": p.meta["dhash"]} for p in photos if "dhash" in p.meta]
    reg_docs = [d for d in reg_docs if d["claim"] != numero] + [{"claim": numero, "sha256": d.digest} for d in docs]
    g = Graph(all_nodes, reg_photos, reg_docs)
    seen = g.component(numero)
    group = sorted(seen - {numero})
    if len(seen) >= RING_MIN:
        add("fraud_ring", "alta", "Posible red organizada",
            f"Este siniestro está conectado, directa o indirectamente, con {len(group)} siniestros de distintos asegurados "
            f"({', '.join(group)}) mediante datos de contacto, fotos, documentos o relatos compartidos.")

    first = g.neighbors(numero)
    neighbors = {nb: sorted(first.get(nb, set()) | set(direct.get(nb, []))) for nb in set(first) | set(direct)}
    net = {
        "center": numero,
        "neighbors": {nb: {"why": why, "level": all_nodes.get(nb, {}).get("level"), "fecha": all_nodes.get(nb, {}).get("fecha"),
                           "asegurado": all_nodes.get(nb, {}).get("asegurado", "")} for nb, why in sorted(neighbors.items())},
        "group": group,
        "group_edges": g.edges_within(seen),
        "group_info": {n: {"level": all_nodes.get(n, {}).get("level"), "asegurado": all_nodes.get(n, {}).get("asegurado", "")}
                       for n in group},
    }
    return out, net


def components(registry: list[dict], min_size: int = 2) -> list[dict]:
    """Todas las redes de la cartera: grupos de siniestros conectados, del más grande al más chico."""
    nodes, photos, docs = _registry_parts(registry)
    g = Graph(nodes, photos, docs)
    seen: set[str] = set()
    out = []
    for n in sorted(nodes):
        if n in seen:
            continue
        comp = g.component(n)
        seen |= comp
        if len(comp) < min_size:
            continue
        edges = g.edges_within(comp)
        reasons = Counter(w.strip() for _, _, ws in edges for w in ws.split(","))
        members = sorted(comp, key=lambda m: nodes[m].get("fecha") or "")
        out.append({
            "members": members,
            "edges": edges,
            "reasons": reasons.most_common(),
            "people": len({_ent(nodes[m]).get("rut") or m for m in comp}),
            "monto": sum(nodes[m].get("monto") or 0 for m in comp),
            "first": nodes[members[0]].get("fecha"), "last": nodes[members[-1]].get("fecha"),
            "info": {m: {"asegurado": nodes[m].get("asegurado", ""), "level": nodes[m].get("level"),
                         "fecha": nodes[m].get("fecha"), "monto": nodes[m].get("monto")} for m in members},
        })
    out.sort(key=lambda c: (len(c["members"]), c["monto"]), reverse=True)
    return out
