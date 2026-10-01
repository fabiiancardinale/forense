"""Genera un historial ficticio de siniestros (CSV) para probar la importación y las métricas.

Contiene ~150 siniestros entre octubre 2025 y septiembre 2026:
  - La mayoría legítimos, con datos únicos.
  - Red A: 6 siniestros de distintos asegurados con cuenta, teléfono y correo compartidos,
    relatos copiados, pólizas recién contratadas y montos cerca del tope.
  - Red B: 4 siniestros con el mismo teléfono y dirección, y avisos tardíos.
  - Un par de siniestros con el mismo correo (uno fraude, otro legítimo: una falsa alarma).
  - Un cliente con siniestros repetidos.
  - 3 fraudes confirmados SIN señales detectables (Veritas no los encuentra: métricas honestas).
  - 3 siniestros legítimos con aumento de cobertura reciente (falsas alarmas esperables).
Los casos anteriores a agosto 2026 traen su resultado final; los recientes quedan pendientes.

Todos los nombres, RUT, teléfonos, correos, cuentas, patentes y talleres son inventados.
Uso: python demo/make_history_demo.py historial_demo.csv
"""
import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "historial_demo.csv")
rnd = random.Random(2026)
START, END, CLOSED = datetime(2025, 10, 1), datetime(2026, 9, 10), datetime(2026, 8, 1)
TALLERES = ["Automotriz Central", "Taller Demo Norte", "Servicio Técnico Andes", "Desabolladura Los Pinos",
            "Taller Mecánico Oriente", "Carrocerías del Valle", "Automotriz Costanera", "Taller Demo Poniente"]
COMUNAS = ["Providencia", "Ñuñoa", "Las Condes", "Maipú", "La Florida", "Santiago", "Puente Alto", "Vitacura", "Macul"]
rows, n = [], 0


def money(x):
    return f"{int(x):,}".replace(",", ".")


def person(tag=None):
    global n
    n += 1
    return {"asegurado": f"Asegurado demo {n:03d}", "rut": f"DEMO-{n:04d}",
            "telefono": f"+56 9 0{n:03d} {rnd.randint(1000, 9999)}", "email": f"asegurado{n:03d}@example.com",
            "direccion": f"Pasaje Demo {n}, {rnd.choice(COMUNAS)}", "cuenta_bancaria": f"DEMO-CTA-{100000 + n}",
            "patente": f"ZX{n:04d}"}


def claim(p, fecha, **kw):
    suma = kw.pop("suma", rnd.choice([4, 5, 6, 7, 8, 9]) * 1_000_000)
    inicio = kw.pop("inicio", fecha - timedelta(days=rnd.randint(60, 900)))
    fin = inicio + timedelta(days=730)
    while (fin - fecha).days <= 15:
        fin += timedelta(days=365)
    r = {**p, "fecha_siniestro": fecha.strftime("%d-%m-%Y %H:%M"),
         "fecha_denuncia": (fecha + timedelta(days=kw.pop("aviso", rnd.randint(0, 3)))).strftime("%d-%m-%Y"),
         "lugar": f"Av. Demo {rnd.randint(100, 9900)}, {rnd.choice(COMUNAS)}",
         "taller": kw.pop("taller", rnd.choice(TALLERES)), "testigos": kw.pop("testigos", rnd.randint(0, 2)),
         "poliza": f"AUT-D{rnd.randint(100000, 999999)}", "inicio_poliza": inicio.strftime("%d-%m-%Y"),
         "fin_poliza": fin.strftime("%d-%m-%Y"), "suma_asegurada": money(suma),
         "deducible": money(rnd.choice([0, 100_000, 150_000, 250_000])),
         "monto_reclamado": money(kw.pop("monto", rnd.randint(200, 2400) * 1000)),
         "cambio_cobertura": kw.pop("cambio", ""), "descripcion": kw.pop("relato", ""), "parte_policial": "",
         "resultado": kw.pop("resultado", None)}
    if r["resultado"] is None:
        r["resultado"] = ("rechazado" if rnd.random() < 0.05 else "pagado") if fecha < CLOSED else ""
    r.update(kw)
    rows.append(r)


def rand_date(a=START, b=END, night=False):
    d = a + timedelta(seconds=rnd.randint(0, int((b - a).total_seconds())))
    return d.replace(hour=rnd.choice([22, 23]) if night else rnd.randint(8, 21), minute=rnd.choice([0, 10, 20, 30, 40, 50]))


# ---- legítimos ------------------------------------------------------------------------
for _ in range(126):
    claim(person(), rand_date())

# falsas alarmas esperables: legítimos con aumento de cobertura reciente
for _ in range(3):
    f = rand_date(START, CLOSED)
    claim(person(), f, cambio=(f - timedelta(days=rnd.randint(5, 20))).strftime("%d-%m-%Y"), resultado="pagado")

# cliente frecuente (mismo RUT y patente)
freq = person()
for f in (datetime(2025, 11, 8, 12, 30), datetime(2026, 3, 14, 17, 10), datetime(2026, 7, 2, 9, 40)):
    claim(freq, f, resultado="pagado")

# fraudes sin señales detectables
for _ in range(3):
    claim(person(), rand_date(START, CLOSED), resultado="fraude")

# ---- red A ------------------------------------------------------------------------------
BASE_A = ("Dejé el auto estacionado frente a mi domicilio durante la noche y al volver encontré el parachoques "
          "trasero y el costado izquierdo dañados, sin que nadie dejara sus datos. Solicito la reparación en el "
          "taller de mi confianza.")
variants = [BASE_A, BASE_A.replace("Dejé el auto", "Dejé mi vehículo"), BASE_A.replace("izquierdo", "derecho"),
            BASE_A.replace("sin que nadie dejara sus datos", "sin que nadie dejara datos"),
            BASE_A.replace("Solicito la reparación", "Pido la reparación"), BASE_A]
ring_a = [person() for _ in range(6)]
shared = {"cuenta_bancaria": "DEMO-CTA-777001", "telefono": "+56 9 0777 1212", "email": "contacto.reparaciones@example.com"}
ring_a[0]["cuenta_bancaria"] = ring_a[1]["cuenta_bancaria"] = ring_a[2]["cuenta_bancaria"] = shared["cuenta_bancaria"]
ring_a[2]["telefono"] = ring_a[3]["telefono"] = shared["telefono"]
ring_a[3]["email"] = ring_a[4]["email"] = ring_a[5]["email"] = shared["email"]
dates_a = [datetime(2025, 11, 20), datetime(2026, 1, 9), datetime(2026, 2, 27), datetime(2026, 4, 18),
           datetime(2026, 6, 5), datetime(2026, 8, 22)]
for p, d, rel in zip(ring_a, dates_a, variants):
    f = d.replace(hour=23, minute=15)
    suma = 6_000_000
    claim(p, f, taller="Taller Demo Sur", testigos=0, relato=rel, suma=suma, monto=rnd.randint(88, 96) * suma // 100,
          inicio=f - timedelta(days=rnd.randint(6, 25)), resultado="fraude" if f < CLOSED else "")

# ---- red B ------------------------------------------------------------------------------
BASE_B = ("Un vehículo me impactó en el cruce y huyó del lugar. Tengo daños en el tapabarro delantero y en el foco, "
          "y no alcancé a ver la patente del otro auto.")
ring_b = [person() for _ in range(4)]
for p in ring_b:
    p["telefono"], p["direccion"] = "+56 9 0888 3434", "Los Aromos 2020, La Florida"
dates_b = [datetime(2026, 2, 3, 14, 20), datetime(2026, 3, 30, 11, 0), datetime(2026, 5, 16, 16, 45), datetime(2026, 7, 11, 13, 5)]
for i, (p, f) in enumerate(zip(ring_b, dates_b)):
    claim(p, f, aviso=rnd.randint(9, 20), taller="Carrocerías del Valle",
          relato=BASE_B if i in (0, 2) else "", resultado="fraude" if i < 3 else "rechazado")

# ---- par con el mismo correo: uno fraude, el otro legítimo (falsa alarma) -----------------
pa, pb = person(), person()
pa["email"] = pb["email"] = "gestiones.siniestros@example.com"
claim(pa, datetime(2026, 1, 22, 10, 30), resultado="fraude")
claim(pb, datetime(2026, 5, 2, 18, 0), resultado="pagado")

# ---- número de siniestro correlativo por fecha y escritura -------------------------------------
rows.sort(key=lambda r: datetime.strptime(r["fecha_siniestro"], "%d-%m-%Y %H:%M"))
for i, r in enumerate(rows, 1):
    r["numero"] = f"HIS-{r['fecha_siniestro'][6:10]}-{i:04d}"
cols = ["numero", "fecha_siniestro", "fecha_denuncia", "asegurado", "rut", "telefono", "email", "direccion",
        "cuenta_bancaria", "patente", "lugar", "taller", "testigos", "parte_policial", "poliza", "inicio_poliza",
        "fin_poliza", "cambio_cobertura", "suma_asegurada", "deducible", "monto_reclamado", "descripcion", "resultado"]
headers = ["N° Siniestro", "Fecha", "Fecha denuncia", "Asegurado", "RUT", "Teléfono", "Correo", "Dirección",
           "Cuenta pago", "Patente", "Lugar", "Taller", "Testigos", "Parte policial", "Póliza", "Inicio vigencia",
           "Fin vigencia", "Cambio cobertura", "Suma asegurada", "Deducible", "Monto", "Relato", "Resultado"]
with out.open("w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh, delimiter=";")
    w.writerow(headers)
    for r in rows:
        w.writerow([r[c] for c in cols])
print(f"{len(rows)} siniestros -> {out}")
