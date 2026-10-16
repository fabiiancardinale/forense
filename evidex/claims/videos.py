"""Videos del siniestro: datos, cuadros clave, alertas y comparación con las fotos.

Lo que se revisa de cada video (evidex.forensics.video):
  - fecha de grabación: antes del siniestro (alta) o sin fecha (baja: WhatsApp la borra);
  - lugar (GPS) lejos del lugar declarado;
  - app de edición o recodificación que dejó su nombre en el archivo;
  - cuadros clave contra las fotos del caso: si una foto muestra el mismo lugar que el video pero una zona
    no calza, la foto pudo editarse (editar un video entero es mucho más difícil que editar una foto).

Todo se guarda en videos.json del caso (datos, cuadros y comparaciones) para no repetir el trabajo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evidex.core.detections import Finding

CACHE = "videos.json"
FRAMES_DIR = "video_cuadros"
VERSION = 1
MAX_COMPARES = 1500          # fotos × cuadros por video; más que eso no se compara (tardaría demasiado)
TIME_BUDGET = 120            # segundos de comparación por análisis; lo que falte se hace en el siguiente
LOCAL_TZ = "America/Santiago"


@dataclass
class Video:
    digest: str
    name: str
    path: Path
    info: dict | None = None
    frames: list[dict] = field(default_factory=list)       # [{"file", "t"}]
    title: str = ""

    @property
    def ev(self) -> str:
        return f"{self.digest[:8]}:1"

    def frame_path(self, case_root: Path, f: dict) -> Path:
        return case_root / FRAMES_DIR / self.digest[:16] / f["file"]


def _load_cache(case) -> dict:
    try:
        data = json.loads((case.root / CACHE).read_text(encoding="utf-8"))
        return data if data.get("version") == VERSION else {"version": VERSION}
    except (OSError, ValueError):
        return {"version": VERSION}


def _save_cache(case, data: dict) -> None:
    try:
        (case.root / CACHE).write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    except (OSError, TypeError):
        pass


def load(case) -> list[Video]:
    """Videos activos del caso, con sus datos y cuadros (se calculan una vez)."""
    from evidex.forensics import video
    data = _load_cache(case)
    items, dirty = data.setdefault("videos", {}), False
    out = []
    for e in case.active_evidence():
        if e["data"].get("note") != "video":
            continue
        d = e["subject"]
        path = case.evidence_dir / d
        v = Video(d, e["data"].get("original_name", d[:12]), path,
                  title=(e["data"].get("portal") or {}).get("title") or "")
        row = items.get(d)
        if row is None and video.available() and path.exists():
            try:
                info = video.probe(path)
                fr = video.frames(path, case.root / FRAMES_DIR / d[:16], info["duration"])
                row = {"info": info, "frames": fr}
            except ValueError as ex:
                row = {"info": None, "frames": [], "error": str(ex)}
            items[d], dirty = row, True
        if row:
            v.info, v.frames = row.get("info"), row.get("frames") or []
        out.append(v)
    if dirty:
        _save_cache(case, data)
    return out


def recorded_local(v: Video) -> datetime | None:
    """Fecha de grabación en hora de Chile (sin zona), comparable con la fecha declarada del siniestro."""
    info = v.info or {}
    if info.get("created_local"):
        try:
            d = datetime.fromisoformat(info["created_local"].replace("Z", "+00:00"))
            return d.replace(tzinfo=None) if d.tzinfo is None else _to_local(d)
        except ValueError:
            pass
    if info.get("created"):
        return _to_local(datetime.fromisoformat(info["created"].replace("Z", "+00:00")))
    return None


def _to_local(d: datetime) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return d.astimezone(ZoneInfo(LOCAL_TZ)).replace(tzinfo=None)
    except Exception:
        return (d.astimezone(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)


def analyze(case, decl: dict, decl_ev: str, vids: list[Video], photos) -> list[Finding]:
    from evidex.claims.analysis import BEFORE_TOLERANCE, GPS_ALERT_KM, GPS_WARN_KM, LATE_AFTER, _fmt, km_between
    out: list[Finding] = []
    t0 = datetime.fromisoformat(decl["fecha_siniestro"])
    place = (decl["lat"], decl["lon"]) if decl.get("lat") is not None else None
    for v in vids:
        info = v.info
        cite = [v.ev]
        if not info:
            continue
        rec = recorded_local(v)
        if rec is None:
            out.append(Finding("video_no_date", "baja", f"Video sin fecha de grabación ({v.name})",
                               f"El video {v.name} no dice cuándo se grabó. Pasa al reenviarlo por WhatsApp o redes "
                               "sociales. Pida el original desde la galería del teléfono (por el portal del asegurado).",
                               cite, ""))
        else:
            delta = rec - t0
            if delta < -BEFORE_TOLERANCE:
                out.append(Finding("video_before_claim", "alta", f"Video grabado antes del siniestro ({v.name})",
                                   f"El video {v.name} se grabó el {_fmt(rec)}, {abs(delta.days) or 'menos de 1'} día(s) "
                                   f"antes de la fecha declarada del siniestro ({_fmt(t0)}).", cite + [decl_ev],
                                   rec.isoformat()))
            elif delta > LATE_AFTER:
                out.append(Finding("video_late", "media", f"Video muy posterior al siniestro ({v.name})",
                                   f"El video {v.name} se grabó {delta.days} días después del siniestro declarado.",
                                   cite + [decl_ev], rec.isoformat()))
        if place and info.get("gps"):
            km = km_between(place, tuple(info["gps"]))
            if km > GPS_WARN_KM:
                out.append(Finding("video_far", "alta" if km > GPS_ALERT_KM else "media",
                                   f"Video grabado lejos del lugar declarado ({v.name})",
                                   f"El video {v.name} se grabó a {km:.0f} km del lugar declarado ({decl.get('lugar', '')}).",
                                   cite + [decl_ev], ""))
        ed = info.get("editor")
        if ed and not ed.startswith("FFmpeg"):
            out.append(Finding("video_edited", "media", f"Video editado o exportado con {ed} ({v.name})",
                               f"El archivo {v.name} lo escribió {ed}, una app de edición de video: no es el archivo que "
                               "grabó la cámara. Pueden haberse cortado partes, cambiado la velocidad o agregado efectos. "
                               "Pida el video original desde la galería.", cite, ""))
        elif ed:
            out.append(Finding("video_reencoded", "baja", f"Video recodificado ({v.name})",
                               f"El archivo {v.name} fue reescrito con FFmpeg, que usan muchas apps de edición y algunas "
                               "redes sociales: no es el archivo que grabó la cámara.", cite, ""))
    out += _photo_vs_video(case, vids, photos)
    for f in out:
        f.category = "Fotos"
    return out


def _photo_vs_video(case, vids: list[Video], photos) -> list[Finding]:
    """Cada foto contra los cuadros del video: si muestran lo mismo y una zona no calza, la foto pudo editarse."""
    from evidex.claims.analysis import _ai_evidence, _zones_text
    from evidex.forensics import views
    if not views.available():
        return []
    shots = [p for p in photos if p.path and Path(p.path).exists() and not p.meta.get("doc_image")]
    import time
    data = _load_cache(case)
    pairs, dirty = data.setdefault("pairs", {}), 0
    out, start = [], time.monotonic()

    def flush():
        fresh = _load_cache(case)
        fresh.setdefault("pairs", {}).update(pairs)
        fresh.setdefault("videos", data.get("videos", {}))
        _save_cache(case, fresh)
    for v in vids:
        frames = [f for f in v.frames if v.frame_path(case.root, f).exists()]
        if not frames or len(frames) * len(shots) > MAX_COMPARES:
            continue
        for p in shots:
            best = None
            for f in frames:
                key = f"{p.digest}:{v.digest}:{f['file']}"
                if key not in pairs:
                    if time.monotonic() - start > TIME_BUDGET:
                        continue                  # se sigue en el próximo análisis (lo hecho queda guardado)
                    try:
                        pairs[key] = views.compare(v.frame_path(case.root, f), p.path)
                    except Exception:
                        pairs[key] = None
                    dirty += 1
                    if dirty % 50 == 0:
                        flush()
                r = pairs.get(key)
                if r and (best is None or r["inliers"] > best[1]["inliers"]):
                    best = (f, r)
            if not best or not best[1]["zones"]:
                continue
            f, r = best
            mark = _ai_evidence(p)
            out.append(Finding("photo_differs_from_video", "alta" if mark else "media",
                               f"La foto no calza con el video ({p.name})",
                               f"La foto {p.name} muestra el mismo lugar que el video {v.name} (segundo {f['t']:.0f}), "
                               f"pero en {'una zona' if len(r['zones']) == 1 else str(len(r['zones'])) + ' zonas'} "
                               f"({_zones_text(r['zones'])}) se ve distinta. Editar un video entero es mucho más difícil "
                               "que editar una foto: si la zona es el daño, la foto pudo editarse para agrandarlo, "
                               "agregarlo o borrarlo. También puede ser algo que se movió entre la foto y el video."
                               + (f" La foto declara uso de IA ({mark})." if mark else "")
                               + " Use «Comparar con el video» para ver la zona marcada en ambos.",
                               [p.ev, v.ev], p.ts))
    if dirty:
        flush()
    return out


def best_frame(case, photo_digest: str, video_digest: str) -> tuple[str, dict] | None:
    """El cuadro del video que mejor calza con la foto, con su comparación (para el botón Comparar)."""
    pairs = _load_cache(case).get("pairs", {})
    best = None
    prefix = f"{photo_digest}:{video_digest}:"
    for k, r in pairs.items():
        if k.startswith(prefix) and r and (best is None or r["inliers"] > best[1]["inliers"]):
            best = (k[len(prefix):], r)
    return best


def events(vids: list[Video]):
    """Eventos para la línea de tiempo forense."""
    from evidex.forensics.forensic_timeline import Event
    from evidex.forensics.video import phone
    out = []
    for v in vids:
        rec = recorded_local(v)
        if not rec:
            continue
        info = v.info or {}
        gps = tuple(info["gps"]) if info.get("gps") else None
        detail = ", ".join(filter(None, [phone(info), f"{info.get('duration', 0):.0f} s",
                                         f"GPS {gps[0]:.4f}, {gps[1]:.4f}" if gps else "sin GPS"]))
        out.append(Event(rec, "video", f"Video {v.name}", detail, v.ev, gps, "fecha de grabación del video"))
    return out


def summary(v: Video) -> dict:
    """Lo que muestra la pestaña Fotos de cada video."""
    from evidex.forensics.video import phone
    info = v.info or {}
    rec = recorded_local(v)
    return {"digest": v.digest, "name": v.name, "title": v.title or v.name, "duration": info.get("duration"),
            "size": f"{info.get('width', 0)}×{info.get('height', 0)}" if info else "",
            "recorded": rec.isoformat(timespec="minutes") if rec else None, "phone": phone(info) or None,
            "gps": info.get("gps"), "editor": info.get("editor"), "frames": v.frames, "analyzed": bool(info)}
