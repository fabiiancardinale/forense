"""Videos del siniestro: datos del archivo y cuadros clave.

Datos (ffprobe): duración, resolución, fecha de grabación, lugar (GPS), marca y modelo del teléfono y el
programa que escribió el archivo. Una app de edición (CapCut, InShot, VN...) o un archivo recodificado deja
su nombre ahí; WhatsApp borra la fecha y el lugar.

Cuadros clave (ffmpeg): una imagen cada pocos segundos, repartidas en todo el video, para verlas en el caso y
compararlas con las fotos (una foto editada deja de calzar con el mismo lugar visto en el video).

ffmpeg y ffprobe se usan como programas aparte (no se incorporan al código de Evidex). Sin ellos, el video se
guarda y se puede ver, pero no se analiza.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp"}
MAX_BYTES = 300_000_000
MAX_SECONDS = 15 * 60
FRAMES = 16                    # cuadros clave por video (repartidos en toda su duración)
FRAME_SIDE = 1600
PROBE_TIMEOUT, FRAMES_TIMEOUT = 30, 180

# apps y programas que reescriben el video: su nombre queda en el archivo
EDITORS = [
    (r"capcut|jianying", "CapCut"), (r"inshot", "InShot"), (r"\bvn\b|vlognow", "VN"), (r"kinemaster", "KineMaster"),
    (r"premiere|adobe", "Adobe"), (r"imovie", "iMovie"), (r"final cut", "Final Cut"), (r"davinci|resolve", "DaVinci Resolve"),
    (r"filmora", "Filmora"), (r"powerdirector", "PowerDirector"), (r"canva", "Canva"), (r"tiktok", "TikTok"),
    (r"snapchat", "Snapchat"), (r"instagram", "Instagram"), (r"handbrake", "HandBrake"), (r"lavf|ffmpeg", "FFmpeg (recodificado)"),
    (r"clipchamp", "Clipchamp"), (r"videoleap", "Videoleap"), (r"splice", "Splice"),
]


def available() -> bool:
    return bool(shutil.which("ffprobe") and shutil.which("ffmpeg"))


def header_ok(path: Path) -> bool:
    """MP4, MOV, M4V y 3GP empiezan con una caja 'ftyp' (o 'moov'/'wide'/'mdat' en MOV antiguos)."""
    with open(path, "rb") as f:
        head = f.read(16)
    return len(head) >= 12 and head[4:8] in (b"ftyp", b"moov", b"wide", b"mdat", b"free", b"skip")


def probe(path) -> dict:
    """Lee el contenedor con ffprobe. ValueError si no es un video que se pueda leer."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                              str(path)], capture_output=True, timeout=PROBE_TIMEOUT, check=False)
        data = json.loads(out.stdout or b"{}")
    except (OSError, subprocess.TimeoutExpired, ValueError) as ex:
        raise ValueError("No se pudo leer el video.") from ex
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    if not v:
        raise ValueError("El archivo no tiene imagen de video.")
    fmt = data.get("format") or {}
    tags = {k.lower(): str(val) for k, val in (fmt.get("tags") or {}).items()}
    vtags = {k.lower(): str(val) for k, val in (v.get("tags") or {}).items()}
    rot = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    rot = rot or int(float(vtags.get("rotate", 0) or 0))
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if abs(rot) in (90, 270):
        w, h = h, w
    try:
        num, den = (v.get("avg_frame_rate") or "0/1").split("/")
        fps = round(float(num) / float(den), 2) if float(den) else 0
    except ValueError:
        fps = 0
    dur = float(fmt.get("duration") or v.get("duration") or 0)
    info = {
        "duration": round(dur, 1), "width": w, "height": h, "fps": fps, "codec": v.get("codec_name", ""),
        "audio": any(s.get("codec_type") == "audio" for s in streams), "size": int(fmt.get("size") or 0),
        "brand": tags.get("major_brand", ""), "created": _date(tags.get("creation_time") or vtags.get("creation_time")),
        "created_local": tags.get("com.apple.quicktime.creationdate", ""),
        "make": tags.get("com.apple.quicktime.make") or tags.get("com.android.manufacturer") or tags.get("make", ""),
        "model": tags.get("com.apple.quicktime.model") or tags.get("com.android.model") or tags.get("model", ""),
        "software": tags.get("com.apple.quicktime.software") or tags.get("software") or "",
        "encoder": tags.get("encoder") or vtags.get("encoder") or "",
        "android": tags.get("com.android.version", ""),
        "handler": vtags.get("handler_name", ""),
        "gps": _iso6709(tags.get("com.apple.quicktime.location.iso6709") or tags.get("location") or
                        tags.get("location-eng") or ""),
        "tags": {k: val[:200] for k, val in list(tags.items())[:60]},
    }
    info["editor"] = editor(info)
    return info


def _date(v) -> str | None:
    """creation_time en UTC. 1970 o 1904 (fecha vacía) cuenta como sin fecha."""
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.year < 2000:
        return None
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso6709(s: str) -> tuple[float, float] | None:
    m = re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", s or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat or lon) else None


def editor(info: dict) -> str | None:
    """Programa de edición que dejó su nombre en el archivo, si lo hay."""
    text = " ".join(str(info.get(k, "")) for k in ("software", "encoder", "handler")).lower()
    text += " " + " ".join(f"{k} {v}" for k, v in (info.get("tags") or {}).items()).lower()
    for pat, name in EDITORS:
        if re.search(pat, text):
            return name
    return None


def phone(info: dict) -> str:
    return " ".join(x for x in (info.get("make"), info.get("model")) if x).strip()


def frames(path, out_dir: Path, duration: float, n: int = FRAMES) -> list[dict]:
    """Saca n cuadros repartidos en el video (ya girados como se ven). Devuelve [{"file", "t"}]."""
    out_dir.mkdir(parents=True, exist_ok=True)
    done = sorted(out_dir.glob("c*.jpg"))
    if done:
        return [{"file": p.name, "t": float(p.stem.split("_")[1]) / 10} for p in done]
    if duration <= 0:
        return []
    n = max(1, min(n, int(duration) + 1))
    step = duration / n
    res = []
    for i in range(n):
        t = round(min(duration - 0.05, step * (i + 0.5)), 1)
        name = f"c{i:02d}_{int(t * 10):05d}.jpg"
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                            "-vf", f"scale='min({FRAME_SIDE},iw)':-2", "-q:v", "3", "-y", str(out_dir / name)],
                           capture_output=True, timeout=FRAMES_TIMEOUT / max(n, 1) + 10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if (out_dir / name).exists() and (out_dir / name).stat().st_size > 0:
            res.append({"file": name, "t": t})
    return res
