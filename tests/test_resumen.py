"""Resumen del caso: veredicto arriba y alertas de la misma regla agrupadas en una línea."""
from evidex.web.views.claims.case import _group_findings, _verdict


def _f(rule, sev, title):
    return {"rule": rule, "severity": sev, "title": title, "summary": "x", "evidence": []}


def test_agrupa_y_ordena():
    fs = [_f("no_metadata", "media", f"Foto sin fecha, cámara ni ubicación (foto{i}.jpg)") for i in range(3)]
    fs += [_f("edited", "alta", "Foto editada (a.jpg)"), _f("short_narrative", "baja", "Relato muy breve")]
    g = _group_findings(sorted(fs, key=lambda f: {"alta": 0, "media": 1, "baja": 2}[f["severity"]]), {})
    assert [x["rule"] for x in g] == ["edited", "no_metadata", "short_narrative"]
    assert g[1]["count"] == 3 and g[1]["title"] == "Foto sin fecha, cámara ni ubicación"
    assert [f["label"] for f in g[1]["findings"]] == ["foto0.jpg", "foto1.jpg", "foto2.jpg"]
    assert g[0]["title"] == "Foto editada (a.jpg)"          # una sola: el título completo
    v = _verdict({"level": "warn"}, fs, g)
    assert v["counts"] == {"alta": 1, "media": 3, "baja": 1}
    assert v["detail"] == "5 alertas de 3 tipos (1 alta, 3 medias, 1 baja)."
