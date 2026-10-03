"""Lista de todas las pruebas que Evidex aplica a una foto, con su resultado.

Sirve para mostrar al liquidador (y a la compañía) qué se revisó, no solo lo que salió mal:
cada prueba queda como "alerta", "sin hallazgos" o "no aplica" (con el motivo).
"""
from __future__ import annotations

# (grupo, nombre, reglas que la hacen fallar, función que dice si aplica -> motivo o None)
CHECKS = [
    ("Origen", "Marcas de imágenes generadas con IA", ("ai_generated",), None),
    ("Origen", "Tamaño típico de generadores de IA", ("ai_dimensions",), None),
    ("Origen", "Texto «generado por IA» en la imagen", ("ai_label_visible",),
     lambda m: None if "text" in ((m.get("content") or {}).get("ocr") or {}) else "el lector de texto no está instalado"),
    ("Origen", "Proporción de cámara (recortes a mano)", ("odd_ratio",),
     lambda m: None if not m.get("make") else "trae datos de cámara (se revisa el tamaño anotado)"),
    ("Origen", "Captura de pantalla en vez de foto", ("screenshot",), None),
    ("Origen", "Firma de autenticidad de la cámara (C2PA)", ("c2pa_invalid",),
     lambda m: None if (m.get("content") or {}).get("c2pa") else "la foto no trae firma C2PA"),
    ("Metadatos", "Fecha, cámara y ubicación presentes", ("no_metadata",), None),
    ("Metadatos", "Programas de edición", ("edited",), None),
    ("Metadatos", "Herramientas para cambiar metadatos", ("metadata_tool",), None),
    ("Metadatos", "Fechas internas coherentes", ("exif_dates_mismatch", "exif_resaved"),
     lambda m: None if (m.get("forensics") or {}).get("dates") else "sin fechas internas"),
    ("Metadatos", "Hora del GPS contra la fecha", ("exif_gps_time_mismatch",),
     lambda m: None if (m.get("forensics") or {}).get("gps_utc") else "sin hora de GPS"),
    ("Metadatos", "Miniatura interna igual a la foto", ("thumbnail_mismatch", "thumbnail_ratio"),
     lambda m: None if (m.get("forensics") or {}).get("thumb_dhash") else "sin miniatura interna"),
    ("Metadatos", "Datos de exposición de la cámara", ("exif_no_exposure",),
     lambda m: None if m.get("make") else "sin datos de cámara"),
    ("Metadatos", "Nota del fabricante (iPhone)", ("makernote_missing",),
     lambda m: None if (m.get("make") or "").strip().lower() == "apple" else "no es iPhone"),
    ("Metadatos", "Tamaño original de la cámara (recortes)", ("resized_after_capture",),
     lambda m: None if (m.get("forensics") or {}).get("pixel_dims") else "la cámara no anotó el tamaño"),
    ("Metadatos", "Nombre del archivo", ("edit_filename",), None),
    ("Metadatos", "Fecha del archivo en el teléfono", ("saved_before_taken", "taken_future"),
     lambda m: None if (m.get("portal") or {}).get("last_modified") else "solo para fotos subidas por el portal"),
    ("Píxeles", "Doble compresión y zonas pegadas", ("pasted_region", "recompressed"),
     lambda m: None if m.get("format") == "JPEG" else "solo para fotos JPEG"),
    ("Píxeles", "Partes clonadas dentro de la foto", ("cloned_region",), None),
    ("Píxeles", "Grano del sensor parejo", ("noise_inconsistent",), None),
    ("Píxeles", "Luz del cielo contra la hora", ("daylight_at_night",),
     lambda m: None if (m.get("content") or {}).get("sky_day") else "no se ve cielo de día"),
    ("Contexto", "Fecha de la foto contra la del siniestro", ("taken_before", "taken_late", "photo_before_policy"),
     lambda m: None if m.get("taken") else "la foto no tiene fecha"),
    ("Contexto", "Ubicación contra el lugar declarado", ("gps_mismatch", "impossible_travel"),
     lambda m: None if m.get("gps") else "la foto no tiene ubicación"),
    ("Contexto", "Patente visible contra la declarada", ("plate_photo_mismatch",),
     lambda m: None if ((m.get("content") or {}).get("ocr") or {}).get("plates") else "no se lee ninguna patente"),
    ("Otros siniestros", "Foto ya usada (también recortada o espejada)", ("reused_photo",), None),
    ("Otros siniestros", "Mismo teléfono en siniestros de otros asegurados", ("same_device_other_claim",),
     lambda m: None if (m.get("forensics") or {}).get("serial") else "la cámara no graba número de serie"),
    ("Este siniestro", "Misma foto repetida o espejada", ("duplicate_in_claim", "mirrored_in_claim"), None),
    ("Este siniestro", "Recorte de otra foto del caso (y marca de IA quitada)", ("cropped_in_claim", "ai_mark_cropped"),
     None),
    ("Este siniestro", "Fotos de varios teléfonos", ("multiple_devices",), None),
]


def run(meta: dict, findings_for_photo: list, case_level: bool = True) -> list[dict]:
    """findings_for_photo: hallazgos que citan esta foto (objetos con .rule y .severity, o dicts)."""
    if "error" in meta:
        return []
    got: dict[str, str] = {}
    for f in findings_for_photo:
        rule, sev = (f["rule"], f["severity"]) if isinstance(f, dict) else (f.rule, f.severity)
        if rule not in got or {"alta": 0, "media": 1, "baja": 2}[sev] < {"alta": 0, "media": 1, "baja": 2}[got[rule]]:
            got[rule] = sev
    out = []
    for group, name, rules, applies in CHECKS:
        if not case_level and group in ("Otros siniestros", "Este siniestro"):
            continue
        hit = [got[r] for r in rules if r in got]
        if hit:
            sev = min(hit, key=lambda s: {"alta": 0, "media": 1, "baja": 2}[s])
            out.append({"group": group, "name": name, "status": "alerta", "severity": sev})
            continue
        why = applies(meta) if applies else None
        out.append({"group": group, "name": name, "status": "no aplica" if why else "ok", "why": why or ""})
    return out


def summary(checks: list[dict]) -> dict:
    return {"total": len(checks), "ok": sum(c["status"] == "ok" for c in checks),
            "alert": sum(c["status"] == "alerta" for c in checks),
            "na": sum(c["status"] == "no aplica" for c in checks)}
