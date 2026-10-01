"""Genera un expediente de investigación FICTICIO y un informe PDF ficticio para auditar.

Salida (por defecto demo/investigacion_demo/):
  expediente.json, entrevista_1.json, entrevista_2.json   datos y transcripciones
  documentos/*.pdf                                        nota de venta, permiso, bono de atención
  informe_para_auditar.pdf                                informe terminado, con errores sembrados

Todas las personas, RUT, direcciones, vehículos y montos son inventados.
El PDF del informe requiere reportlab (pip install reportlab); el resto no.
"""
import json
import sys
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "investigacion_demo")
(out / "documentos").mkdir(parents=True, exist_ok=True)

EXPEDIENTE = {
    "numero": "SIN-DEMO-4471", "aseguradora": "Compañía de Seguros (demo)", "tipo": "Colisión",
    "fecha_ocurrencia": "2026-09-15T16:45:00", "direccion": "Av. Los Leones 1200", "comuna": "Providencia · Santiago",
    "vehiculo": "Hatchback 2021 - DEMO11", "patente": "DEMO11", "rut_asegurado": "11.111.111-1",
    "descripcion": "PÉRDIDA DE CONTROL DEL VEHÍCULO AL ESQUIVAR A OTRO AUTOMÓVIL, IMPACTANDO CONTRA UNA BARRERA. AIRBAGS ACTIVADOS: SÍ",
    "alertas": ["posible uso comercial", "indica que fue a dejar a su padre al médico: solicitar respaldo de la hora médica",
                "pedir carta app", "pedir direcciones de origen y destino"],
}

ASEGURADO = """1. ¿Me comunico con don Hernán Pérez?
Sí, con él.
2. Le hablamos por encargo de la compañía para recopilar antecedentes del siniestro. ¿Autoriza que la llamada sea grabada?
Sí, no hay problema.
3. ¿Cuál es su nombre completo?
Hernán Pérez Muñoz.
4. ¿Cuál es su RUT?
11.111.111-1.
5. ¿Cuál es su relación con el conductor, don Tomás Pérez?
Es mi hijo.
6. ¿Podría relatarnos cómo ocurrió el incidente?
Ese día mi hijo me llevó a la Clínica Demo Oriente. Yo fui a retirar un presupuesto. Cuando él se devolvió, otro auto se le cruzó y al esquivarlo chocó contra una barrera.
7. ¿Qué pasó con el otro vehículo?
Según lo que me contó Tomás, el otro vehículo se fugó de inmediato.
8. ¿Cuánto se demoró la grúa en llegar?
Más o menos una hora.
9. ¿Quién usaba habitualmente el vehículo?
Lo usamos los dos, yo y también mi hijo, según lo que necesite cada uno.
10. ¿El vehículo ha sido utilizado en alguna aplicación de transporte de pasajeros?
No sabría decirle.
11. ¿Autoriza a la compañía a consultar a las aplicaciones de transporte?
Sí, ningún problema."""

CONDUCTOR = """1. ¿Me comunico con don Tomás Pérez?
Sí, con él.
2. ¿Cuál es su RUT?
22.222.222-2.
3. ¿A qué hora aproximadamente ocurrió el siniestro?
A las 4 de la tarde.
4. ¿Podría contarnos qué sucedió ese día?
Llevé a mi papá a la Clínica Demo Oriente porque tenía una consulta médica. Al volver por Los Leones, un auto se me cruzó, lo esquivé y terminé contra la barrera.
5. ¿El otro vehículo se detuvo o siguió su marcha?
La verdad no tengo más información, no puedo aclarar ese punto.
6. ¿Hasta qué hora esperó la grúa?
Me quedé esperando hasta las 7 de la tarde a que llegara la grúa.
7. ¿En qué condiciones estaba el vehículo antes del siniestro?
Bien, tenía unos 31.000 kilómetros, lo compramos hace poco más de un mes.
8. ¿Quién utilizaba habitualmente el vehículo?
Solamente yo. Está a nombre de mi papá, pero el auto es mío.
9. ¿Ha usado el vehículo en alguna aplicación de transporte de pasajeros, como Uber o Cabify?
No, jamás.
10. ¿Autoriza a la compañía a consultar a las aplicaciones de transporte?
Sí, obvio."""

INTERVIEWS = [
    {"declarante": "Hernán Pérez Muñoz", "rol": "Asegurado", "fecha": "18/09/2026 11:20", "texto": ASEGURADO},
    {"declarante": "Tomás Pérez Rojas", "rol": "Conductor", "fecha": "17/09/2026 16:05", "texto": CONDUCTOR},
]
(out / "expediente.json").write_text(json.dumps(EXPEDIENTE, indent=2, ensure_ascii=False), encoding="utf-8")
for i, iv in enumerate(INTERVIEWS, 1):
    (out / f"entrevista_{i}.json").write_text(json.dumps(iv, indent=2, ensure_ascii=False), encoding="utf-8")


def simple_pdf(lines):
    """PDF de una página con texto (sin dependencias)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = "\n".join(["BT /F1 12 Tf 60 780 Td 18 TL"] + [f"({esc(x)}) '" for x in lines] + ["ET"]).encode("cp1252")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(body)} >>\nstream\n".encode() + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    buf, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    buf += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(buf)


DOCS = {
    "nota_de_venta_NV1188.pdf": ["AUTOMOTORA DEMO", "NOTA DE VENTA N 1188", "Fecha: 04/08/2026", "Comprador: Hernan Perez Munoz",
                                  "RUT comprador: 11.111.111-1", "Vehiculo: Hatchback 2021 - DEMO11",
                                  "Kilometraje al momento de la venta: 48.210 km", "Documento ficticio de prueba"],
    "permiso_de_circulacion_DEMO11.pdf": ["PERMISO DE CIRCULACION 2026", "Placa: DEMO11", "Propietario: Propietario Anterior Demo",
                                           "RUT: 33.333.333-3", "Documento ficticio de prueba"],
    "bono_atencion_15-09-2026.pdf": ["CENTRO MEDICO DEMO", "BONO DE ATENCION AMBULATORIA", "Paciente: Hernan Perez Munoz",
                                      "RUT: 11.111.111-1", "Fecha: 15/09/2026 17:30", "Prestacion: Kinesiologia", "Documento ficticio de prueba"],
}
for name, lines in DOCS.items():
    (out / "documentos" / name).write_bytes(simple_pdf(lines))


# ---- informe para auditar (formato habitual, con errores sembrados) --------------------------
def build_report_pdf(path: Path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    body = ParagraphStyle("b", fontName="Helvetica", fontSize=10.5, leading=14, spaceAfter=8)
    bold = ParagraphStyle("q", parent=body, fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=bold, fontSize=13, spaceBefore=14, spaceAfter=10)
    title = ParagraphStyle("t", parent=bold, fontSize=18, alignment=1, leading=24, spaceBefore=120)

    def table(rows, widths):
        t = Table([[Paragraph(str(c), body) for c in r] for r in rows], colWidths=widths)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    s = [Paragraph("INFORME DE INVESTIGACIÓN DE SINIESTRO VEHICULAR", title),
         Paragraph("Siniestro N° SIN-DEMO-4471", ParagraphStyle("c", parent=body, alignment=1)), Spacer(1, 20),
         table([["Aseguradora", "Compañía de Seguros (demo)"], ["Tipo de siniestro", "Colisión"],
                ["Fecha de ocurrencia", "15/09/2026 16:45"], ["Vehículo", "Hatchback 2021 - DEMO11"],
                ["Fecha de emisión", "24/09/2026 17:00"]], [150, 300]),
         Paragraph("Documento ficticio de prueba. Todas las personas y datos son inventados.", body), PageBreak(),
         Paragraph("1. DATOS DEL SINIESTRO", h1),
         table([["Fecha de ocurrencia", "15/09/2026 16:45"], ["Dirección", "Av. Los Leones 1200"], ["Patente", "DEMO11"]], [150, 300]),
         Paragraph("Alertas de la compañía", bold),
         table([["N°", "Alerta"]] + [[str(i), a] for i, a in enumerate(EXPEDIENTE["alertas"], 1)], [40, 410]),
         Paragraph("Coherencia del trayecto declarado", bold),
         Paragraph("Resultado: Coherente con el trayecto declarado. El lugar del siniestro se ubica a menos de 350 m de una ruta razonable.", body),
         Paragraph("2. ENTREVISTAS REALIZADAS", h1)]
    for iv in INTERVIEWS:
        name = iv["declarante"].replace("Pérez", "Perez") if iv["rol"] == "Conductor" else iv["declarante"]
        s += [Paragraph(f"{name} — {iv['rol']}", bold), Paragraph(f"Fecha de entrevista: {iv['fecha']}", body)]
        lines = iv["texto"].splitlines()
        for q, a in zip(lines[0::2], lines[1::2]):
            s += [Paragraph(q, bold), Paragraph(a, body)]
        if iv["rol"] == "Asegurado":  # error de transcripción sembrado: respuesta marcada como pregunta
            s += [Paragraph("12. Sí, de acuerdo.", bold), Paragraph("Muchas gracias por su tiempo.", body)]
    s += [Paragraph("3. RESUMEN DEL CASO", h1),
          Paragraph("El conductor declara que llevó a su padre a una consulta médica y que al regresar esquivó a otro vehículo. "
                    "El asegurado señala que ambos usan el vehículo y que no sabe si fue utilizado en aplicaciones.", body),
          Paragraph("4. RESPUESTA A LAS ALERTAS", h1),
          table([["Alerta", "Hallazgo"],
                 ["Posible uso comercial", "No descartado. Ambos firmaron la carta APP marcando \"No autorizo\"."],
                 ["Fue a dejar a su padre al médico", "Acreditado. El bono de atención del 15/09/2026 confirma la atención."],
                 ["Pedir carta APP", "No descartado. Firmaron \"No autorizo\" pese a autorizar verbalmente."],
                 ["Pedir direcciones", "Indeterminado. El análisis de trayecto no pudo realizarse por falta de coordenadas precisas."]], [170, 280]),
          Paragraph("5. HALLAZGOS E INCONSISTENCIAS", h1),
          table([["Hallazgo", "Evidencia"], ["----------", "----------"],
                 ["El conductor declaró 31.000 km, pero la nota de venta registra 48.210 km.", "Nota de venta N° 1188"]], [300, 150]),
          Paragraph("6. CONCLUSIÓN Y RECOMENDACIÓN", h1), Paragraph("SE RECOMIENDA RECHAZAR EL RECLAMO", bold),
          Paragraph("La alerta de uso comercial no pudo ser descartada con los antecedentes disponibles, por lo que se mantiene la recomendación de rechazo.", body),
          Paragraph("7. DOCUMENTACIÓN REVISADA", h1),
          table([["N°", "Documento", "Tipo"]] + [[str(i), n, ".pdf"] for i, n in enumerate(DOCS, 1)], [40, 330, 80])]

    def footer(canvas, doc):
        canvas.setFont("Helvetica-Oblique", 8)
        canvas.drawRightString(560, 760, "Informe de investigación de siniestro · N° SIN-DEMO-4471")
        canvas.drawCentredString(306, 30, f"Página {doc.page}")

    SimpleDocTemplate(str(path), pagesize=letter, title="Informe ficticio SIN-DEMO-4471").build(s, onFirstPage=footer, onLaterPages=footer)


try:
    build_report_pdf(out / "informe_para_auditar.pdf")
except ImportError:
    print("reportlab no está instalado: se omite informe_para_auditar.pdf")
print(f"Expediente ficticio en {out}")
