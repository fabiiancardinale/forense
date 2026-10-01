"""Relato del asegurado: copias entre siniestros y contradicciones con los datos declarados.

La similitud se mide con fragmentos de tres palabras (shingles) y el índice de Jaccard:
detecta relatos copiados aunque cambien algunas palabras, nombres o números.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from functools import lru_cache

from veritas.core.detections import Finding
from veritas.forensics.policy import parse_int

COPY_ALERT, COPY_WARN = 0.5, 0.3
MIN_WORDS = 10

PERIODS = {"madrugada": [(0, 6)], "manana": [(6, 12)], "tarde": [(12, 20)], "noche": [(19, 24), (0, 6)]}
_PERIOD_RE = re.compile(r"\b(?:en|de|por|durante|a|esa)\s+la\s+(manana|tarde|noche|madrugada)\b"
                        r"|\bde\s+(noche|madrugada)\b|\b(anoche)\b")
_NO_WITNESS = re.compile(r"\b(sin testigos|no hubo testigos|no habia testigos|no habia nadie|nadie vio)\b")
_WITNESS = re.compile(r"\btestigos?\b")
_POLICE = re.compile(r"\b(carabineros|constancia|parte policial|comisaria|denuncia policial)\b")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t)


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", normalize(text))


def shingles(words: list[str], k: int = 3) -> set[tuple]:
    return {tuple(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


@lru_cache(maxsize=50000)
def shingle_set(text: str) -> frozenset:
    return frozenset(shingles(tokens(text)))


def similarity(a: str, b: str) -> float:
    sa, sb = shingle_set(a or ""), shingle_set(b or "")
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def analyze(decl: dict, decl_ev: str, other_claims: dict[str, dict]) -> list[Finding]:
    out: list[Finding] = []
    text = decl.get("descripcion", "") or ""
    ts = decl["fecha_siniestro"]

    def add(rule, sev, title, summary):
        out.append(Finding(rule, sev, title, summary, [decl_ev], ts, "Relato"))

    if not text.strip():  # muchos sistemas no registran el relato: su ausencia no es una alerta
        return out
    words = tokens(text)
    if len(words) < MIN_WORDS:
        add("short_narrative", "baja", "Relato muy breve",
            f"El relato tiene solo {len(words)} palabras, lo que dificulta contrastarlo con la evidencia.")

    best = sorted(((similarity(text, r.get("relato", "")), num) for num, r in other_claims.items()
                   if num != decl["numero"] and r.get("relato")), reverse=True)
    for sim, num in best[:3]:
        if sim >= COPY_WARN:
            add("copied_narrative", "alta" if sim >= COPY_ALERT else "media", "Relato similar al de otro siniestro",
                f"El relato coincide en un {100 * sim:.0f}% con el relato del siniestro {num}.")

    norm = normalize(text)
    hour = datetime.fromisoformat(ts).hour
    periods = {next(g for g in m.groups() if g) for m in _PERIOD_RE.finditer(norm)}
    periods = {"noche" if p == "anoche" else p for p in periods}
    if len(periods) == 1:
        p = periods.pop()
        if not any(a <= hour < b for a, b in PERIODS[p]):
            add("time_contradiction", "media", "El relato no coincide con la hora declarada",
                f"El relato sitúa el hecho en la {p}, pero la hora declarada es {datetime.fromisoformat(ts):%H:%M}.")

    testigos = parse_int(decl.get("testigos"))
    if _NO_WITNESS.search(norm) and testigos:
        add("witness_contradiction", "media", "Contradicción sobre testigos",
            f"El relato dice que no hubo testigos, pero la declaración indica {testigos}.")
    elif _WITNESS.search(norm) and not _NO_WITNESS.search(norm) and testigos == 0:
        add("witness_contradiction", "baja", "Contradicción sobre testigos",
            "El relato menciona testigos, pero la declaración indica que no hubo.")

    if _POLICE.search(norm) and not decl.get("parte_policial"):
        add("police_missing", "baja", "Constancia policial sin número de parte",
            "El relato menciona una constancia o denuncia policial, pero no se informó el número de parte.")
    return out
