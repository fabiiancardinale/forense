"""Asistente con citas verificables: diferenciador central de Evidex.

Regla de oro: toda afirmación del asistente debe citar uno o más eventos reales con
la sintaxis [ev:ID]. El verificador rechaza cualquier oración sin cita o con una cita
que no exista en la línea de tiempo. Así el analista nunca recibe una conclusión
que no pueda comprobar con un clic, y el informe final no puede contener alucinaciones.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

CITE = re.compile(r"\[ev:([0-9a-f]{8}:\d+)\]")
# no corta después de abreviaturas comunes ("Av. Providencia", "Sr. Pérez")
SENTENCE = re.compile(r"(?<=[.!?])(?<!\bAv\.)(?<!\bSr\.)(?<!\bDr\.)(?<!\bSra\.)(?<!\bNro\.)(?<!\bDpto\.)\s+(?=[A-ZÁÉÍÓÚÑ\d])")


@dataclass
class Verified:
    accepted: list[str]
    rejected: list[tuple[str, str]]  # (oración, motivo)

    @property
    def text(self) -> str:
        return " ".join(self.accepted)


def verify_claims(text: str, timeline) -> Verified:
    """Separa oraciones respaldadas por evidencia de las que no lo están."""
    ok, bad = [], []
    for s in filter(None, (x.strip() for x in SENTENCE.split(text))):
        ids = CITE.findall(s)
        if not CITE.sub("", s).strip(" .,;"):
            bad.append((s, "cita sin afirmación"))
        elif not ids:
            bad.append((s, "sin cita a evidencia"))
        elif missing := [i for i in ids if not timeline.exists(i)]:
            bad.append((s, f"cita inexistente: {', '.join(missing)}"))
        else:
            ok.append(s)
    return Verified(ok, bad)


def offline_summary(findings) -> str:
    """Resumen determinista, siempre con citas. Funciona sin conexión ni API."""
    if not findings:
        return "No se detectaron patrones sospechosos con las reglas actuales."
    parts = []
    for f in findings:
        cites = " ".join(f"[ev:{i}]" for i in f.evidence[:6])
        # la cita va dentro de cada oración, antes del punto final
        for s in filter(None, (x.strip().rstrip(".") for x in SENTENCE.split(f.summary))):
            parts.append(f"{s} {cites}.")
    return " ".join(parts)


def llm_summary(findings, timeline, model: str = "claude-sonnet-4-5") -> str:
    """Resumen con LLM (opcional). Se le exige citar; luego pasa por verify_claims."""
    import anthropic  # pip install anthropic

    ctx = []
    for f in findings:
        for i in f.evidence[:8]:
            e = timeline.get(i)
            ctx.append(f"[ev:{i}] {e['ts']} host={e['host']} id={e['event_id']} user={e['user']} {e['message'][:200]}")
    prompt = (
        "Eres analista forense. Redacta un resumen breve del incidente usando SOLO estos eventos. "
        "Cada oración DEBE terminar citando al menos un evento con el formato [ev:ID]. "
        "No afirmes nada que no esté en los eventos.\n\n" + "\n".join(ctx)
    )
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(model=model, max_tokens=800, messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text


def summarize(findings, timeline, use_llm: bool = False) -> Verified:
    text = offline_summary(findings)
    if use_llm and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            text = llm_summary(findings, timeline)
        except Exception:  # sin red o error de API: caemos al resumen determinista
            pass
    return verify_claims(text, timeline)
