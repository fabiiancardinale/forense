"""Genera siniestros de demostración con datos ficticios, fotos y PDF sintéticos.

Estructura creada en la carpeta indicada (se analizan en el orden de orden.json):
  historicos/SIN-2026-0412   siniestro anterior (su foto y su cuenta bancaria reaparecen después)
  historicos/SIN-2026-0533   otro asegurado, misma cuenta bancaria y relato copiado
  historicos/SIN-2026-0601   otro asegurado; su teléfono y su factura reaparecen después
  actual/                    SIN-2026-0987: junta señales en fotos, PDF, póliza, relato y red
  limpio/                    SIN-2026-0990: siniestro sin alertas, para comparar

El caso "actual" reúne todas las señales a propósito, para mostrar cada verificación.
Todas las personas, RUT, teléfonos, cuentas y talleres son inventados.
"""
import io
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PIL.PngImagePlugin import PngInfo

out = Path(sys.argv[1] if len(sys.argv) > 1 else "siniestro_demo")


# ---- fotos sintéticas -------------------------------------------------------------
def scene(seed: int, w=1280, h=960) -> Image.Image:
    """Escena sintética de un auto con daño; cada semilla produce una imagen distinta."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    top = [rnd.randint(110, 210) for _ in range(3)]
    bot = [rnd.randint(40, 110) for _ in range(3)]
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
    for _ in range(25):
        x = rnd.randint(0, w)
        d.rectangle([x, rnd.randint(80, 380), x + rnd.randint(40, 200), 560],
                    fill=tuple(rnd.randint(60, 170) for _ in range(3)))
    x0, y0 = rnd.randint(120, 420), rnd.randint(430, 540)
    cw, ch = rnd.randint(620, 780), rnd.randint(220, 280)
    color = tuple(rnd.randint(20, 235) for _ in range(3))
    d.rounded_rectangle([x0, y0, x0 + cw, y0 + ch], 40, fill=color)
    d.rounded_rectangle([x0 + cw * .2, y0 - ch * .55, x0 + cw * .78, y0 + 10], 50, fill=color)
    d.rectangle([x0 + cw * .27, y0 - ch * .45, x0 + cw * .71, y0 - 10], fill=(150, 185, 210))
    # ruedas con perspectiva (la más lejana se ve más chica), como en una foto real
    for wx, r in ((x0 + cw * .18, 66), (x0 + cw * .8, 57)):
        d.ellipse([wx - r, y0 + ch - r, wx + r, y0 + ch + r * .9], fill=(25, 25, 25))
        d.ellipse([wx - r * .45, y0 + ch - r * .45, wx + r * .45, y0 + ch + r * .4], fill=(120, 120, 125))
    dx, dy = x0 + rnd.randint(40, cw - 200), y0 + rnd.randint(30, ch - 90)
    d.polygon([(dx + rnd.randint(0, 160), dy + rnd.randint(0, 80)) for _ in range(7)], fill=(55, 50, 48))
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    # textura (asfalto, reflejos) y ruido de sensor: en una foto real no hay dos zonas idénticas
    texture = Image.effect_noise((w // 6, h // 6), 40).resize((w, h), Image.Resampling.BICUBIC).convert("RGB")
    noise = Image.effect_noise((w, h), 9).convert("RGB")
    return Image.blend(Image.blend(img, texture, 0.12), noise, 0.05)


def exif(make, model, when, gps=None, software=None):
    e = Image.Exif()
    e[0x010F], e[0x0110], e[0x0132] = make, model, when
    if software:
        e[0x0131] = software
    # fecha y datos de exposición, como los escribe cualquier cámara de teléfono
    e[0x8769] = {0x9003: when, 0x9004: when, 0x829A: 1 / 120, 0x829D: 1.8, 0x8827: 100}
    if gps:
        def dms(v):
            v = abs(v); d = int(v); m = int((v - d) * 60)
            return (float(d), float(m), round((v - d - m / 60) * 3600, 2))
        e[0x8825] = {1: "S" if gps[0] < 0 else "N", 2: dms(gps[0]), 3: "W" if gps[1] < 0 else "E", 4: dms(gps[1])}
    return e


def with_plate(img: Image.Image, text: str) -> Image.Image:
    """Dibuja una patente legible (para probar la lectura de patentes en las fotos)."""
    img = img.copy()
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=58)
    except TypeError:                       # Pillow antiguo
        font = ImageFont.load_default()
    x, y = img.width // 2 - 150, int(img.height * 0.72)
    d.rounded_rectangle([x, y, x + 300, y + 86], 8, fill=(245, 245, 245), outline=(20, 20, 20), width=4)
    d.text((x + 150, y + 43), text, fill=(15, 15, 15), font=font, anchor="mm")
    return img


def scanned_pdf(lines) -> bytes:
    """PDF que es solo una imagen (como un papel escaneado): no tiene texto digital."""
    img = Image.new("L", (1240, 1754), 250)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=36)
    except TypeError:
        font = ImageFont.load_default()
    for i, line in enumerate(lines):
        d.text((120, 160 + i * 74), line, fill=20, font=font)
    img = img.rotate(0.8, fillcolor=250)
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=150)
    return buf.getvalue()


# ---- PDF sintéticos (sin dependencias) -------------------------------------------------
def pdf_bytes(lines, info, edit=None) -> bytes:
    """PDF de una página. `edit=(nuevas_lineas, nueva_info)` agrega una actualización incremental,
    que es lo que ocurre cuando alguien modifica un PDF existente con un editor."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def stream(ls):
        body = "\n".join(["BT /F1 12 Tf 60 780 Td 18 TL"] + [f"({esc(x)}) '" for x in ls] + ["ET"]).encode("cp1252")
        return f"<< /Length {len(body)} >>\nstream\n".encode() + body + b"\nendstream"

    def info_obj(d):
        return ("<< " + " ".join(f"/{k} ({esc(v)})" for k, v in d.items()) + " >>").encode("cp1252")

    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
            4: stream(lines), 5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            6: info_obj(info)}
    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = {}
    for n in sorted(objs):
        offs[n] = len(buf)
        buf += f"{n} 0 obj\n".encode() + objs[n] + b"\nendobj\n"
    xref = len(buf)
    buf += b"xref\n0 7\n0000000000 65535 f \n" + b"".join(f"{offs[n]:010d} 00000 n \n".encode() for n in range(1, 7))
    buf += f"trailer\n<< /Size 7 /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    if edit:
        new_lines, new_info = edit
        o4 = len(buf); buf += b"4 0 obj\n" + stream(new_lines) + b"\nendobj\n"
        o6 = len(buf); buf += b"6 0 obj\n" + info_obj({**info, **new_info}) + b"\nendobj\n"
        x2 = len(buf)
        buf += f"xref\n0 1\n0000000000 65535 f \n4 1\n{o4:010d} 00000 n \n6 1\n{o6:010d} 00000 n \n".encode()
        buf += f"trailer\n<< /Size 7 /Root 1 0 R /Info 6 0 R /Prev {xref} >>\nstartxref\n{x2}\n%%EOF\n".encode()
    return bytes(buf)


WORD = {"Creator": "Microsoft Word 2021", "Producer": "Microsoft Word 2021"}


def budget(taller, numero, patente, monto, fecha, rut="76.543.210-3"):
    return [f"{taller}", f"RUT: {rut}", "PRESUPUESTO DE REPARACION", f"Siniestro: {numero}", f"Patente: {patente}", f"Fecha: {fecha}",
            "Parachoques trasero, desabolladura y pintura", "Mano de obra", f"TOTAL: ${monto}", "Documento ficticio de prueba"]


# ---- chat de WhatsApp exportado (ficticio) -----------------------------------------------
CHAT = """19/09/26, 21:14 - Asegurado de prueba: Mañana lo hacemos, el seguro paga todo. Ya hablé con el del taller por el presupuesto
19/09/26, 21:15 - Primo: dale. Al liquidador dile que fue en el semáforo y que el otro se arrancó
19/09/26, 21:16 - Primo: y acuérdate que no hubo testigos
20/09/26, 18:05 - Asegurado de prueba: voy saliendo de Viña, llego tipo 8
20/09/26, 18:52 - Asegurado de prueba: Se eliminó este mensaje
20/09/26, 19:05 - Primo: cualquier cosa llama al de la otra vez, +56 9 5555 1212
21/09/26, 10:30 - Taller Los Aromos: el presupuesto queda en 4.650.000, el otro lo boto
21/09/26, 10:31 - Asegurado de prueba: perfecto
"""


# ---- siniestros ------------------------------------------------------------------------
def claim(folder, decl, photos=(), docs=()):
    base = out / folder
    (base / "fotos").mkdir(parents=True, exist_ok=True)
    (base / "documentos").mkdir(exist_ok=True)
    (base / "declaracion.json").write_text(json.dumps(decl, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, img, kw in photos:
        img.save(base / "fotos" / name, **kw)
    for name, data in docs:
        (base / "documentos" / name).write_bytes(data)
    return base


RELATO_BASE = ("Me encontraba detenido en el semáforo de la avenida cuando un vehículo que venía por detrás me "
               "impactó en el parachoques trasero. El otro conductor se dio a la fuga sin dejar sus datos. "
               "Revisé los daños y tomé fotografías en el lugar.")
TALLER = "Taller Los Aromos"
CUENTA_COMPARTIDA = "00-123-45678-90"
TEL_COMPARTIDO = "+56 9 4444 9090"

factura = pdf_bytes(["Repuestos Automotrices del Sur", "FACTURA ELECTRONICA N 88213", "Parachoques trasero original",
                     "Foco trasero derecho", "TOTAL: $980.000", "Documento ficticio de prueba"],
                    {"Creator": "Sistema de Facturacion Electronica", "Producer": "Sistema de Facturacion Electronica",
                     "CreationDate": "D:20260625113000-04'00'"})

claim("historicos/SIN-2026-0412", {
    "numero": "SIN-2026-0412", "poliza": "AUT-40110021", "asegurado": "Asegurado histórico A", "rut": "11.111.111-1",
    "telefono": "+56 9 8765 4321", "email": "cliente.a@example.com", "direccion": "Los Olmos 450, Maipú",
    "cuenta_bancaria": CUENTA_COMPARTIDA, "patente": "HJKL-21", "taller": TALLER,
    "fecha_siniestro": "2026-04-12T21:10:00", "fecha_denuncia": "2026-04-13", "lugar": "Av. Pajaritos 3000, Maipú",
    "lat": -33.5100, "lon": -70.7570, "inicio_poliza": "2025-01-10", "fin_poliza": "2027-01-10",
    "suma_asegurada": "6.000.000", "monto_reclamado": "1.200.000", "testigos": 0, "descripcion": RELATO_BASE,
}, photos=[("IMG_4471.jpg", scene(33), {"quality": 92, "exif": exif("samsung", "SM-A546E", "2026:04:12 21:15:40", (-33.51012, -70.75690))})],
   docs=[("presupuesto_0412.pdf", pdf_bytes(budget(TALLER, "SIN-2026-0412", "HJKL-21", "1.200.000", "14-04-2026"),
                                            {**WORD, "CreationDate": "D:20260414100000-04'00'"}))])

claim("historicos/SIN-2026-0533", {
    "numero": "SIN-2026-0533", "poliza": "AUT-40220987", "asegurado": "Asegurado histórico B", "rut": "22.222.222-2",
    "telefono": "+56 9 5555 1212", "email": "cliente.b@example.com", "direccion": "Pasaje Las Rosas 12, La Florida",
    "cuenta_bancaria": CUENTA_COMPARTIDA, "patente": "PRTS-77", "taller": TALLER,
    "fecha_siniestro": "2026-05-30T20:45:00", "fecha_denuncia": "2026-05-31", "lugar": "Av. Vicuña Mackenna 7100, La Florida",
    "lat": -33.5227, "lon": -70.5983, "inicio_poliza": "2026-05-20", "fin_poliza": "2027-05-20",
    "suma_asegurada": "5.500.000", "monto_reclamado": "1.900.000", "testigos": 0,
    "descripcion": RELATO_BASE.replace("Me encontraba", "Estaba").replace("tomé", "saqué"),
}, photos=[("foto_trasera.jpg", scene(88), {"quality": 90, "exif": exif("Xiaomi", "Redmi Note 13", "2026:05:30 20:52:10", (-33.52280, -70.59815))})],
   docs=[("presupuesto_0533.pdf", pdf_bytes(budget(TALLER, "SIN-2026-0533", "PRTS-77", "1.900.000", "02-06-2026"),
                                            {**WORD, "CreationDate": "D:20260602093000-04'00'"}))])

claim("historicos/SIN-2026-0601", {
    "numero": "SIN-2026-0601", "poliza": "AUT-39880410", "asegurado": "Asegurado histórico C", "rut": "33.333.333-3",
    "telefono": TEL_COMPARTIDO, "email": "cliente.c@example.com", "direccion": "Av. Grecia 2100, Ñuñoa",
    "cuenta_bancaria": "00-987-65432-10", "patente": "WXYZ-10", "taller": TALLER,
    "fecha_siniestro": "2026-06-21T13:20:00", "fecha_denuncia": "2026-06-22", "lugar": "Av. Irarrázaval 3400, Ñuñoa",
    "lat": -33.4540, "lon": -70.5960, "inicio_poliza": "2024-11-02", "fin_poliza": "2026-11-02",
    "suma_asegurada": "7.000.000", "monto_reclamado": "980.000", "testigos": 1,
    "descripcion": ("Al salir del estacionamiento del supermercado otro auto retrocedió y golpeó la puerta del conductor. "
                    "Intercambiamos datos, pero después el número del otro conductor no contestaba."),
}, photos=[("puerta.jpg", scene(99), {"quality": 90, "exif": exif("Apple", "iPhone 13", "2026:06:21 13:31:05", (-33.45410, -70.59590))})],
   docs=[("factura_repuestos.pdf", factura)])

# ---- siniestro actual (sospechoso) -----------------------------------------------------
ai = PngInfo()
ai.add_text("parameters", "photo of a white sedan with a dented rear bumper, parked on a street, realistic, 35mm\n"
            "Steps: 30, Sampler: DPM++ 2M, CFG scale: 7, Seed: 118822, Model: sdxl_base")
reused = scene(33).crop((20, 15, 1260, 945)).resize((1100, 825))
presupuesto = pdf_bytes(budget(TALLER, "SIN-2026-0987", "KXTR-45", "1.850.000", "14-09-2026", rut="76.543.210-9"),
                        {**WORD, "CreationDate": "D:20260914101500-03'00'", "ModDate": "D:20260914101500-03'00'"},
                        edit=(budget(TALLER, "SIN-2026-0987", "KXTR-45", "4.650.000", "21-09-2026", rut="76.543.210-9"),
                              {"Producer": "iLovePDF", "ModDate": "D:20260925223000-03'00'"}))
claim("actual", {
    "numero": "SIN-2026-0987", "poliza": "AUT-55120034", "asegurado": "Asegurado de prueba", "rut": "44.444.444-4",
    "telefono": TEL_COMPARTIDO, "email": "contacto.d@example.com", "direccion": "Av. Providencia 2200, Providencia",
    "cuenta_bancaria": CUENTA_COMPARTIDA, "patente": "KXTR-45", "taller": TALLER,
    "fecha_siniestro": "2026-09-20T18:30:00", "fecha_denuncia": "2026-09-28",
    "lugar": "Av. Providencia 1234, Providencia, Santiago", "lat": -33.4263, "lon": -70.6167,
    "inicio_poliza": "2026-09-08", "fin_poliza": "2027-09-08", "cambio_cobertura": "2026-09-15",
    "suma_asegurada": "5.000.000", "deducible": "150.000", "monto_reclamado": "4.650.000", "testigos": 0,
    "descripcion": ("Me encontraba detenido en el semáforo de la avenida de noche cuando un vehículo que venía por detrás me "
                    "impactó en el parachoques trasero. El otro conductor se dio a la fuga sin dejar sus datos. "
                    "Revisé los daños, tomé fotografías en el lugar y dejé constancia en Carabineros."),
}, photos=[
    ("01_trasera.jpg", scene(11), {"quality": 90, "exif": exif("samsung", "SM-S921B", "2026:09:20 18:41:12", (-33.42648, -70.61702))}),
    ("02_costado_derecho.jpg", scene(22), {"quality": 90, "exif": exif("samsung", "SM-S921B", "2026:09:20 18:43:05", (-33.42651, -70.61699),
                                                                        software="Adobe Photoshop 25.9 (Windows)")}),
    ("03_parachoques.jpg", reused, {"quality": 78}),
    ("04_detalle_danio.png", scene(44), {"pnginfo": ai}),
    # la foto "de la patente" muestra la patente de otro vehículo (HJKL-21, del siniestro SIN-2026-0412)
    ("05_patente.jpg", with_plate(scene(55), "HJKL·21"), {"quality": 90, "exif": exif("Apple", "iPhone 15", "2026:08:11 10:02:47", (-33.0245, -71.5518))}),
    # 9 minutos después de la foto 02 en Providencia, pero con GPS en Rancagua (85 km): traslado imposible
    ("06_lateral_izquierdo.jpg", scene(68), {"quality": 90, "exif": exif("samsung", "SM-S921B", "2026:09:20 18:52:30", (-34.1701, -70.7406))}),
    # la foto 01 invertida de izquierda a derecha, presentada como otro costado del auto
    ("07_costado_trasero_izq.jpg", scene(11).transpose(Image.Transpose.FLIP_LEFT_RIGHT),
     {"quality": 88, "exif": exif("samsung", "SM-S921B", "2026:09:20 18:44:40", None)}),
], docs=[("presupuesto_taller.pdf", presupuesto), ("factura_repuestos.pdf", factura),
         ("chat_whatsapp_asegurado.txt", CHAT.encode("utf-8")),
         # boleta en papel escaneada: sin texto digital, solo se puede leer con OCR; fechada antes del choque
         ("boleta_grua_escaneada.pdf", scanned_pdf(["GRUAS EL TREBOL SPA", "RUT: 77.812.345-2", "BOLETA N 004512",
                                                     "Servicio de grua y traslado", "Patente: KXTR-45",
                                                     "Fecha: 18-09-2026", "TOTAL: $95.000"]))])

# ---- siniestro limpio -------------------------------------------------------------------
claim("limpio", {
    "numero": "SIN-2026-0990", "poliza": "AUT-31007788", "asegurado": "Asegurado de prueba 2", "rut": "55.555.555-5",
    "telefono": "+56 9 3131 7070", "email": "cliente.e@example.com", "direccion": "Marchant Pereira 180, Providencia",
    "cuenta_bancaria": "00-555-11122-33", "patente": "LPWS-81", "taller": "Automotriz Central",
    "fecha_siniestro": "2026-09-20T18:30:00", "fecha_denuncia": "2026-09-21",
    "lugar": "Av. Providencia 1234, Providencia, Santiago", "lat": -33.4263, "lon": -70.6167,
    "inicio_poliza": "2025-03-01", "fin_poliza": "2027-03-01", "suma_asegurada": "5.000.000", "deducible": "150.000",
    "monto_reclamado": "850.000", "testigos": 1,
    "descripcion": ("Iba saliendo de mi edificio en la tarde y, al girar hacia Avenida Providencia, un camión de reparto "
                    "rozó el costado de mi auto. El conductor se detuvo, intercambiamos datos y un vecino presenció lo ocurrido."),
}, photos=[
    ("a_frontal.jpg", scene(66), {"quality": 90, "exif": exif("motorola", "moto g84", "2026:09:20 18:36:40", (-33.42630, -70.61690))}),
    ("b_lateral.jpg", with_plate(scene(77), "LPWS·81"), {"quality": 90, "exif": exif("motorola", "moto g84", "2026:09:20 18:37:02", (-33.42633, -70.61688))}),
], docs=[("presupuesto_automotriz_central.pdf",
          pdf_bytes(budget("Automotriz Central", "SIN-2026-0990", "LPWS-81", "850.000", "22-09-2026"),
                    {**WORD, "CreationDate": "D:20260922120000-03'00'"}))])

(out / "orden.json").write_text(json.dumps(
    ["historicos/SIN-2026-0412", "historicos/SIN-2026-0533", "historicos/SIN-2026-0601", "actual", "limpio"]), encoding="utf-8")
print(f"Demo creada en {out}")
