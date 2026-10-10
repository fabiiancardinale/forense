"""Banco de entrenamiento: fotos que una persona marcó como «editada con IA» o «sin editar» para enseñarle al modelo.

Cada marca guarda una COPIA de la foto fuera del caso (carpeta `entrenamiento/` junto a los casos), con quién la
marcó, cuándo, de qué caso salió, qué decía el modelo en ese momento y el origen de la foto:

  prueba      foto propia de prueba, o de un tercero con permiso escrito
  autorizada  foto real de un siniestro, con autorización escrita de la aseguradora para entrenar (Ley 21.719)

Si además se indica la foto ORIGINAL sin editar (otra foto del mismo caso), se calcula la máscara de la zona que
cambió comparando las dos. Sin máscara, una editada solo sirve si la IA rehízo la foto completa («completa»); si
no, se exporta aparte («editadas_sin_zona/») y el entrenamiento no la usa hasta que tenga zona.

El modelo NUNCA se reentrena ni se instala solo: «exportar» arma el zip para el notebook de Kaggle; el modelo nuevo
se calibra, se mide con el mismo conjunto de prueba y se instala a mano solo si mejora.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from evidex.core.storage import atomic_bytes, locked

ORIGENES = {"prueba": "Foto de prueba (propia o con permiso escrito)",
            "autorizada": "Siniestro real con autorización escrita de la aseguradora para entrenar"}
ETIQUETAS = {"editada": "Sí, está editada con IA", "original": "No, la foto no está editada"}
APPS = ("Samsung Galaxy AI", "Google Fotos (Magic Editor / Reimagine)", "Apple (Limpiar)", "ChatGPT", "Gemini",
        "Meta AI", "Photoshop / Firefly", "Otra app", "No sé")
ALCANCES = {"zona": "Una zona de la foto", "completa": "Toda la foto (la IA la rehízo completa)"}
DIGEST = re.compile(r"[0-9a-f]{64}")
LICENCIA = ("propia (fotos de prueba de Zelekpress o de terceros con permiso escrito; las de siniestros reales solo "
            "con autorización escrita de la aseguradora)")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Bank:
    def __init__(self, workdir: Path):
        self.root = Path(workdir) / "entrenamiento"
        self.fotos = self.root / "fotos"
        self.mascaras = self.root / "mascaras"
        self.log = self.root / "banco.jsonl"

    # ---- lectura ---------------------------------------------------------------------------------
    def _events(self) -> list[dict]:
        try:
            return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines() if x.strip()]
        except OSError:
            return []

    def entries(self) -> list[dict]:
        """Marcas vigentes, la última por foto (marcar de nuevo reemplaza; «quitar» la saca)."""
        out: dict[str, dict] = {}
        for e in self._events():
            if e.get("accion") == "quitar":
                out.pop(e.get("digest"), None)
            elif e.get("accion") == "marcar":
                out[e["digest"]] = e
        return sorted(out.values(), key=lambda e: e["ts"], reverse=True)

    def get(self, digest: str) -> dict | None:
        return next((e for e in self.entries() if e["digest"] == digest), None)

    def summary(self) -> dict:
        es = self.entries()
        ed = [e for e in es if e["etiqueta"] == "editada"]
        return {"total": len(es), "editadas": len(ed), "originales": len(es) - len(ed),
                "con_zona": sum(1 for e in ed if e.get("mascara") or e.get("alcance") == "completa"),
                "sin_zona": sum(1 for e in ed if not e.get("mascara") and e.get("alcance") != "completa"),
                "errores_modelo": sum(1 for e in es if e.get("modelo_acerto") is False),
                "por_app": _count(e.get("app") or "No sé" for e in ed)}

    def photo(self, digest: str) -> Path | None:
        return next(iter(sorted(self.fotos.glob(digest + ".*"))), None) if DIGEST.fullmatch(digest or "") else None

    def mask(self, digest: str) -> Path | None:
        p = self.mascaras / f"{digest}.png"
        return p if DIGEST.fullmatch(digest or "") and p.exists() else None

    # ---- escritura -------------------------------------------------------------------------------
    def _append(self, row: dict) -> None:
        with locked(self.log):
            self.root.mkdir(parents=True, exist_ok=True)
            with self.log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def mark(self, src: Path, digest: str, *, etiqueta: str, origen: str, actor: str, caso: str, nombre: str,
             app: str = "", alcance: str = "zona", original: Path | None = None, original_digest: str = "",
             modelo: dict | None = None, nota: str = "") -> dict:
        if etiqueta not in ETIQUETAS:
            raise ValueError("Indique si la foto está editada o no.")
        if origen not in ORIGENES:
            raise ValueError("Indique de dónde sale la foto (prueba o siniestro autorizado).")
        if not DIGEST.fullmatch(digest or ""):
            raise ValueError("Archivo desconocido.")
        alcance = alcance if alcance in ALCANCES else "zona"
        ext = Path(nombre).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            raise ValueError("Por ahora el banco acepta solo fotos JPG, PNG o WEBP (no se convierten: se perdería la huella).")
        self.fotos.mkdir(parents=True, exist_ok=True)
        dest = self.fotos / f"{digest}{ext}"
        if not dest.exists():
            atomic_bytes(dest, Path(src).read_bytes())
        mascara, cobertura = False, None
        old = self.mascaras / f"{digest}.png"
        if etiqueta == "editada" and original is not None and original_digest != digest:
            m = change_mask(original, src)
            if m is not None:
                cobertura = round(float((np.asarray(m) > 127).mean()), 4)
                if cobertura >= .5:
                    alcance = "completa"
                self.mascaras.mkdir(parents=True, exist_ok=True)
                buf = io.BytesIO()
                m.save(buf, "PNG")
                atomic_bytes(old, buf.getvalue())
                mascara = True
        if not mascara and old.exists():
            old.unlink()                                   # una marca nueva sin original no hereda la zona vieja
        modelo = modelo or {}
        score, thr = modelo.get("score"), modelo.get("threshold")
        dijo = None if score is None or thr is None else bool(score >= thr)
        row = {"accion": "marcar", "ts": _now(), "actor": actor, "digest": digest, "caso": caso, "nombre": nombre,
               "archivo": dest.name, "etiqueta": etiqueta, "origen": origen,
               "app": (app if app in APPS else "") if etiqueta == "editada" else "",
               "alcance": alcance if etiqueta == "editada" else "", "original": original_digest if mascara else "",
               "mascara": mascara, "cobertura": cobertura, "nota": nota.strip()[:300],
               "modelo": {"id": modelo.get("model"), "score": score, "threshold": thr},
               "modelo_acerto": None if dijo is None else dijo == (etiqueta == "editada")}
        self._append(row)
        return row

    def remove(self, digest: str, actor: str, motivo: str = "") -> bool:
        """Saca la foto del banco y borra su copia (no toca el caso)."""
        if not self.get(digest):
            return False
        self._append({"accion": "quitar", "ts": _now(), "actor": actor, "digest": digest, "motivo": motivo[:200]})
        for p in list(self.fotos.glob(digest + ".*")) + [self.mascaras / f"{digest}.png"]:
            if p.exists():
                p.unlink()
        return True

    def purge(self, digest: str, actor: str) -> bool:
        """Cuando el archivo se elimina definitivamente de un caso (por ejemplo, pedido de borrado del asegurado),
        también sale del banco."""
        return self.remove(digest, actor, "eliminado definitivamente del caso")

    # ---- exportar para Kaggle --------------------------------------------------------------------
    def export_zip(self) -> bytes:
        """originales/, editadas/, mascaras/ (mismo nombre que la editada, .png), editadas_sin_zona/, licencia.txt
        y banco.csv. El notebook de entrenamiento toma las carpetas con originales/ como «fotos propias»."""
        buf = io.BytesIO()
        filas = ["archivo,etiqueta,carpeta,app,alcance,origen,caso,marcada_por,fecha,puntaje_modelo,umbral,modelo_acerto"]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for e in self.entries():
                p = self.fotos / e["archivo"]
                if not p.exists():
                    continue
                if e["etiqueta"] == "original":
                    carpeta = "originales"
                elif e.get("mascara") and self.mask(e["digest"]):
                    carpeta = "editadas"
                    z.write(self.mask(e["digest"]), f"mascaras/{p.stem}.png")
                elif e.get("alcance") == "completa":
                    carpeta = "editadas"                  # sin máscara = toda la foto, que es lo correcto aquí
                else:
                    carpeta = "editadas_sin_zona"
                z.write(p, f"{carpeta}/{p.name}")
                m = e.get("modelo") or {}
                filas.append(",".join(_csv(x) for x in (p.name, e["etiqueta"], carpeta, e.get("app"), e.get("alcance"),
                                                        e["origen"], e.get("caso"), e["actor"], e["ts"],
                                                        m.get("score"), m.get("threshold"), e.get("modelo_acerto"))))
            z.writestr("licencia.txt", LICENCIA + "\n")
            z.writestr("banco.csv", "\n".join(filas) + "\n")
            z.writestr("LEEME.txt", LEEME)
        return buf.getvalue()


LEEME = """Banco de entrenamiento exportado desde Evidex.

originales/          fotos marcadas «no editada»
editadas/            fotos editadas con IA que tienen zona (máscara) o que la IA rehízo completas
mascaras/            blanco = zona que cambió (mismo nombre que la editada, en .png)
editadas_sin_zona/   editadas de una zona sin la foto original: el entrenamiento NO las usa (falta la zona)
banco.csv            quién marcó cada foto, cuándo, de qué caso, y qué dijo el modelo

Uso: suba este zip a Kaggle como Dataset y agréguelo con «+ Add Input» en el notebook de entrenamiento.
El modelo nuevo se calibra y se mide con el mismo conjunto de prueba; se instala solo si mejora.
"""


def _count(xs) -> dict:
    out: dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _csv(x) -> str:
    s = "" if x is None else str(x)
    return '"' + s.replace('"', '""') + '"' if any(c in s for c in ',"\n') else s


def _load(path: Path) -> Image.Image:
    with Image.open(path) as im:
        im.load()
        return ImageOps.exif_transpose(im).convert("RGB")


def change_mask(original: Path, edited: Path, min_area: float = .0005) -> Image.Image | None:
    """Máscara (L, tamaño de la editada) de la zona que cambió entre la foto original y la editada.

    Las dos se llevan al mismo tamaño (WhatsApp reduce ambas igual). Si la forma es distinta (recorte), no se
    adivina: devuelve None. Se suaviza para no confundir la compresión JPEG con un cambio."""
    try:
        a, b = _load(original), _load(edited)
    except (OSError, ValueError):
        return None
    if abs(a.width / a.height - b.width / b.height) > .02:
        return None
    w, h = b.size
    f = min(1.0, 1024 / max(w, h))                       # se compara a 1024 px como máximo
    sw, sh = max(1, round(w * f)), max(1, round(h * f))
    x = np.asarray(a.resize((sw, sh), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.5)), np.float32)
    y = np.asarray(b.resize((sw, sh), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.5)), np.float32)
    x = x - x.mean((0, 1)) + y.mean((0, 1))             # mismo brillo medio (por si el editor tocó la exposición)
    d = np.abs(x - y).max(2)
    if (d > 14).mean() > .5:
        return Image.new("L", (w, h), 255)              # cambió más de la mitad: la IA rehízo la foto entera (ChatGPT)
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med))) or 1.0
    t = min(max(14.0, med + 8 * mad), 35.0)             # tope: si el editor retocó todo un poco, igual se ve la zona
    m = Image.fromarray(((d > t) * 255).astype(np.uint8))
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(9))     # sin puntos sueltos, zona continua
    if (np.asarray(m) > 127).mean() < min_area:
        return None                                      # no hay diferencia visible: no se inventa una zona
    return m.resize((w, h), Image.NEAREST)


def overlay(photo: Path, mask: Path | None, maxside: int = 900) -> bytes:
    """La foto con la zona de la máscara pintada, para revisar a ojo antes de exportar."""
    im = _load(photo)
    im.thumbnail((maxside, maxside), Image.LANCZOS)
    if mask is not None and mask.exists():
        with Image.open(mask) as mm:
            m = mm.convert("L").resize(im.size, Image.NEAREST)
        red = Image.new("RGB", im.size, (220, 38, 38))
        im = Image.composite(Image.blend(im, red, .55), im, m)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()
