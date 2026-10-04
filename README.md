# Evidex by Zelekpress: forense de siniestros con conclusiones verificables

Prototipo funcional (v1.0). Analiza siniestros de seguros de autos cruzando cinco fuentes de evidencia
(fotos, documentos, datos de la póliza, relato del asegurado y la red de siniestros anteriores) y entrega
al liquidador una recomendación, un puntaje de riesgo y un informe donde cada afirmación enlaza a su evidencia.
Incluye además un módulo de respuesta a incidentes informáticos.

## MVP endurecido: login y análisis de archivos

El inicio predeterminado abre un MVP autenticado para imágenes y PDF, con procesamiento en un worker, acceso por propietario y resultados que distinguen hallazgos de análisis incompletos. Los módulos históricos descritos más abajo se habilitan con `--legacy`.

```sh
python -m pip install -r requirements.txt
python -m evidex.accounts.setup --dir casos
python -m evidex.web --dir casos
```

En Windows también puede usar `iniciar_evidex.bat`. Sin usuarios no hay acceso anónimo: se inicializa el administrador por consola. La demo requiere `--demo --legacy` explícitamente y solo funciona localmente.

**No se certifica «Original» por ausencia de indicios.** Se distinguen alteración detectada entre revisiones, indicios de alteración, sin indicios detectados y no concluyente. La detección/localización de IA no está validada contra un corpus real del negocio.

Consulte [alcance, límites, operación y verificación](docs/MVP_HARDENING.md) antes de un despliegue.

## Roles y flujo de trabajo

| Rol | Ve | Hace |
|---|---|---|
| **Analista** | Solo sus casos (*Mis casos*) | Registra siniestros, envía el enlace al asegurado, agrega o quita evidencia, deriva a un perito, decide |
| **Jefe de siniestros** | Todos los casos y el panel *Equipo* | Lo mismo que el analista, más reasignar casos, redes, métricas e importación |
| **Perito externo** | Solo los expedientes derivados a su empresa (*Mis encargos*) y las fotos y documentos de esos siniestros | Carga entrevistas y documentos, responde las alertas, escribe la conclusión y entrega el informe final |
| **Investigador interno** | Expedientes y auditorías | Crea expedientes y audita informes PDF |
| **Administrador** | Todo | Usuarios, empresas de peritaje y configuración |

1. El analista registra el siniestro (queda a su nombre) y envía el enlace al asegurado.
2. Lo que sube el asegurado entra solo al caso y Evidex lo reanaliza.
3. Si el riesgo lo amerita, el analista **deriva las entrevistas** a una empresa de peritaje (y, si quiere, a un perito en
   particular) con un plazo, instrucciones y las alertas que debe aclarar. Evidex crea el expediente del perito.
4. El perito entra con su usuario, ve solo sus encargos, carga las entrevistas, responde cada alerta y **entrega el informe final**.
5. El analista ve el avance en la pestaña *Peritaje* del caso, abre el informe final y registra la decisión.
6. El jefe ve en *Equipo* la carga de cada analista, los casos atrasados (sin movimiento por 7 días, enlace vencido o
   peritaje fuera de plazo), los resultados por analista y por empresa de peritaje, y reasigna casos marcándolos.

Quién tiene cada caso, cada derivación y cada reasignación quedan en la cadena de custodia del caso (no en un archivo editable).
Un caso ajeno no existe para el analista: la dirección responde "no encontrado".

## Dónde está cada cosa

Cada caso tiene las mismas pestañas, siempre en el mismo orden:

| Pestaña | Contenido |
|---|---|
| Resumen | Qué falta por hacer, las alertas principales con la foto a la que se refieren, los datos del siniestro, la decisión y el analista responsable |
| Fotos | Todas las fotos (del asegurado y del analista) con fecha, cámara, GPS y sus alertas; agregar o quitar |
| Documentos | PDF, documentos fotografiados y chats, con el programa que los generó, versiones ocultas recuperadas y alertas |
| Peritaje | Derivar a un perito, o el avance de la derivación: entrevistas, alertas respondidas, conclusión e informe final |
| Asegurado | Enlace del portal, botones de envío, avance y lo que subió |
| Informe | El informe completo de Evidex, verificación de integridad y línea de tiempo |
| Historial | Cadena de custodia en palabras simples y quién abrió el caso |

**Excel:** la cola de trabajo, las redes y las métricas se descargan en Excel con el botón *Excel* de cada pantalla.

Secciones de la interfaz (menú lateral):

- **Panel / Mis casos:** lo primero que se ve (el analista ve solo lo suyo). Casos derivados sin decisión, casos en peritaje, revisión manual pendiente, redes detectadas, monto en revisión,
  la lista de prioridad, el estado de la cartera, las redes principales, las investigaciones en curso y accesos rápidos.

- **Cola de trabajo:** los siniestros ordenados por riesgo, con búsqueda, filtros con conteo, monto, lo que está en curso (asegurado o peritaje) y la decisión. El jefe ve la columna Analista y puede filtrar por analista.
- **Equipo** (jefe): carga por analista, casos atrasados, empresas de peritaje y reasignación.
- **Redes:** todas las redes de la cartera, con su grafo, los datos compartidos, los asegurados involucrados y el monto reclamado.
- **Métricas:** cuántos fraudes confirmados detecta Evidex, qué porcentaje de sus alertas resulta fraude, las falsas alarmas,
  el monto detectado, las señales más frecuentes y los casos a revisar para ajustar umbrales.
- **Importar:** carga masiva del historial desde Excel o CSV (encabezados flexibles, fechas chilenas). Cada fila queda como un caso
  con cadena de custodia, y el archivo original se guarda con su hash. La columna `resultado` (fraude, pagado, rechazado) se
  registra como decisión y alimenta las métricas. Incluye plantilla descargable e historial de ejemplo (`demo/historial_demo.csv`,
  147 siniestros ficticios con dos redes escondidas).
- **Revisar foto:** se sube una foto suelta (sin crear caso) y Evidex muestra sus metadatos y las señales de manipulación:
  fechas internas que no coinciden, hora del GPS que contradice la fecha, miniatura interna de otra imagen, cámara sin datos
  de exposición, rastros de herramientas que reescriben metadatos (ExifTool, editores de EXIF) y capturas de pantalla.
- **Portal del asegurado (registro con enlace):** al registrar un siniestro, el analista marca *Pedirle al asegurado que suba
  todo por un enlace* y elige qué documentos pedir (licencia, padrón, constancia, presupuesto, cédula, boletas). Evidex crea
  el enlace y el caso muestra botones **Enviar por WhatsApp** (con el número del asegurado y el mensaje ya escrito),
  **Enviar por correo** y **Copiar mensaje**. Por WhatsApp viaja solo el enlace; las fotos y documentos llegan por el portal.
  En el portal, desde el celular, el asegurado tiene solo dos botones: **Fotos** (elige de la galería o toma
  una foto) y **Documentos** (PDF o foto de un papel). Cada archivo exige un **título** escrito por el asegurado (por ejemplo
  "Parachoques trasero" o "Licencia de conducir"), que se ve en el caso y en el informe. Las fotos de la galería llegan byte a
  byte, con su fecha, cámara y GPS originales (sirve cuando avisa días después del choque); las fotos de papeles subidas como
  documento se leen con OCR para revisar RUT, fechas y patentes. Los documentos que pidió el analista aparecen como lista
  ("Le pedimos: ..."). Además puede escribir su relato y presiona *Enviar todo*; Evidex reanaliza el caso. Puede avanzar por
  partes durante 7 días. Cada archivo entra a la cadena de custodia al llegar. El analista ve el avance en el caso (paso a paso) y en el Panel
  (*Esperando al asegurado*: sin abrir, abierto, vencido) y puede renovar el enlace o pedir más documentos; lo ya recibido se
  conserva. Para que el asegurado abra el enlace desde su celular, inicie Evidex con `iniciar_publico.bat`: descarga
  cloudflared y crea una dirección temporal https://…trycloudflare.com (WhatsApp la muestra como enlace). Por esa dirección solo
  se abre el portal; el resto de Evidex sigue local. Si el enlace apunta a 127.0.0.1, el caso muestra un aviso, porque el
  asegurado no podrá abrirlo. En producción se configura el dominio de la compañía en Configuración > Dirección pública.
  `iniciar_captura.bat` sigue disponible para probar con un celular en la misma red wifi.
- **Decisión del liquidador** en cada caso (en revisión, fraude confirmado, legítimo, rechazado), registrada en la cadena de custodia con su autor.

## Investigaciones (expedientes y auditoría de informes)

Pensado para el trabajo de las consultoras que investigan siniestros por encargo de la aseguradora.

- **Expediente:** se cargan los datos del siniestro, las alertas de la compañía (una por línea), las entrevistas
  transcritas (preguntas numeradas o formato P:/R:) y los documentos. Evidex:
  - detecta contradicciones entre declarantes (quién usa el vehículo, qué hizo el otro vehículo, uso en aplicaciones,
    hora, motivo del viaje, espera de la grúa) y contra los documentos (kilometraje menor al de la nota de venta,
    documentos con RUT de un tercero), citando la pregunta exacta de cada entrevista;
  - muestra "qué dice cada declarante" por tema;
  - sugiere la evidencia relacionada con cada alerta para responderla con estado y hallazgo;
  - hace una **revisión previa** antes de enviar: alertas sin responder o sin evidencia, contradicciones que ninguna
    respuesta aborda, y rechazos sin un hecho acreditado;
  - genera el informe (portada, datos, entrevistas, contradicciones, respuesta a alertas, conclusión, documentos,
    metodología) con el nombre de su empresa. Se guarda como PDF desde el navegador (Ctrl+P).
- **Auditar un informe:** se sube un PDF terminado con la estructura habitual y Evidex revisa contradicciones entre
  entrevistados (indicando si el informe ya las aborda), secciones que se contradicen, respuestas del entrevistado
  marcadas como preguntas, preguntas sin respuesta, alertas sin respuesta, rechazos fundados solo en que una alerta
  "no pudo descartarse", filas vacías y nombres escritos de dos formas.
- Todo queda en la cadena de custodia (entrevistas, documentos, cada respuesta y conclusión con su autor) y se puede
  exportar como paquete verificable.

Ejemplo ficticio: botón **Cargar ejemplo ficticio** en Investigaciones (archivos en `demo/investigacion_demo/`).

Límites: las reglas reconocen expresiones habituales del español de Chile, no todo matiz; son alertas para revisar.
Los PDF escaneados (imagen) requieren OCR antes de auditarlos. La observación sobre la carga de la prueba en los
rechazos es orientativa y debe validarse con el área legal.

## Qué analiza

| Área | Señales |
|---|---|
| **Red de siniestros** | Teléfono, correo, cuenta bancaria o dirección compartidos con siniestros de **otros** asegurados; siniestros repetidos del mismo RUT o patente en 12 meses; grupos de 3 o más siniestros conectados por datos, fotos, documentos o relatos (posible red organizada). Cuando un siniestro nuevo se vincula con uno anterior, el anterior se reanaliza. |
| **Línea de tiempo forense** | Todos los hechos con fecha en una sola secuencia (declaración, póliza, fotos con su GPS, documentos y cada versión, mensajes del chat), indicando de dónde sale cada hora. Marca lo imposible: **traslado imposible** entre dos hechos (más de 130 km/h promedio), **daño fotografiado antes de la póliza**, presupuesto o factura con **fecha impresa anterior al choque**. |
| **Versiones ocultas de PDF** | Recupera revisiones anteriores que quedan dentro de un PDF (actualizaciones incrementales), muestra qué líneas cambiaron (montos, fechas) y permite descargar cada versión. |
| **Chats de WhatsApp** | Lee el chat exportado (.txt o .zip). Detecta mensajes que hablan del choque o del seguro **antes** de que ocurriera, frases que acuerdan qué decir ("dile que", "acuérdate que"), mensajes eliminados cerca del siniestro y teléfonos de otros siniestros. Cada mensaje queda citable en el informe. |
| **Datos chilenos** | RUT con dígito verificador incorrecto (en la declaración o dentro de un presupuesto/factura: un sistema de facturación nunca lo emite mal), patentes con formato inválido o distintas a la del vehículo declarado. |
| **Lugares en chats** | Reconoce ciudades y comunas de Chile en frases como "voy saliendo de Viña" o "estoy en Rancagua" (no basta con nombrar la ciudad). Si quien escribe es el asegurado, ese lugar entra a la línea de tiempo y se revisa el traslado imposible contra el choque y las fotos. |
| **OCR (opcional)** | Lee PDF escaneados (sin texto digital) para que las revisiones de RUT, patentes y fechas funcionen con documentos en papel, y lee la patente en las fotos: si no es la del vehículo asegurado, alerta (alta si es la foto de la patente). Funciona sin internet. |
| **Servicios externos (opcional)** | Detector de imágenes generadas con IA (Sightengine) y búsqueda inversa en internet (Google Cloud Vision), configurables con sus claves en Configuración. Envían la foto al proveedor: requieren autorización. |
| **Póliza y siniestro** | Siniestro a pocos días de contratar la póliza o cerca del vencimiento; fuera de vigencia; aumento de cobertura poco antes; aviso tardío o denuncia con fecha anterior; monto reclamado cercano a la suma asegurada; madrugada sin testigos ni parte policial. |
| **Documentos (PDF)** | Paso por editores de PDF (iLovePDF, Smallpdf, Sejda...); modificaciones posteriores a la creación (versiones guardadas, fechas); presupuestos o facturas creados antes del siniestro; el mismo documento presentado en otro siniestro. |
| **Contenido de la imagen** (funciona sin metadatos) | Doble compresión JPEG: la foto se abrió y volvió a guardar; **zona pegada** desde otra imagen (sin la huella de compresión del resto), marcada en rojo; **clonado** de una parte de la foto en otro lugar; cielo de día en una foto con hora de noche (altura del sol en ese lugar y hora); firma de autenticidad **C2PA** rota (Pixel 10/11 y otras cámaras firman sus fotos); **grano del sensor** distinto en una zona (pegada de otra foto o retocada), marcada en morado. El nuevo flujo de análisis muestra regiones sospechosas cuando las heurísticas las detectan. |
| **Fotos** | Marcas de generación por IA; edición con software; sin metadatos; metadatos manipulados (fechas internas distintas, hora GPS que no calza, miniatura de otra imagen, cámara sin datos de exposición, ExifTool); capturas de pantalla; fecha anterior o muy posterior al siniestro; GPS lejos del lugar declarado; foto **recortada o achicada** después de tomarla (la cámara anota el tamaño original); iPhone sin la nota del fabricante (metadatos copiados o escritos a mano); tamaño exacto de generadores de IA; nombre de archivo de edición; en el portal, fecha del archivo anterior a la fecha de la foto. |
| **Fotos entre siniestros** | Foto idéntica, casi idéntica (recortada, recomprimida) o **espejada** a la de otro siniestro; la misma toma reconocida por el **identificador único** que graban algunas cámaras, aunque la imagen se haya editado; el **mismo teléfono** (número de serie de la cámara) en siniestros de distintos asegurados. |
| **Fotos del mismo siniestro** | La misma foto presentada dos veces o **espejada** para simular el otro costado; una foto que es **recorte de otra** del caso (y qué bordes se quitaron), con alerta alta si el recorte **sacó la marca «Contenido generado por IA»**; fotos tomadas con varios teléfonos distintos. |
| **Marcas visibles de IA** | El lector de texto busca en la imagen marcas como «Contenido generado por IA» o «AI-generated» (Samsung, Google, Meta). Una foto sin datos de cámara con proporción que ningún teléfono usa se marca como recortada a mano. |
| **Relato** | Relato copiado o muy similar al de otro siniestro; contradicciones con la hora declarada, los testigos o el parte policial; relato ausente o muy breve. |

Cada foto muestra la lista de **las 26 pruebas** que se le aplicaron, agrupadas (origen, metadatos, píxeles, contexto,
otros siniestros, este siniestro), con su resultado: alerta, sin hallazgos o no aplica (y por qué). Así el liquidador y la
compañía ven todo lo que se revisó, no solo lo que salió mal.

Cada alerta tiene severidad (alta, media, baja). El puntaje de 0 a 100 ordena la cola de trabajo según
cantidad y gravedad de alertas: **no es una probabilidad de fraude**.

## Lo que lo distingue

1. **Asistente que no puede inventar.** Toda afirmación del resumen cita evidencia real; lo que no cita, o cita algo inexistente, se descarta automáticamente. Funciona sin IA y, opcionalmente, con un modelo de lenguaje que pasa por el mismo verificador.
2. **Evidencia verificable por terceros.** Cadena de custodia con hash encadenado y firma Ed25519. El paquete exportado incluye `verify.py`: un juez, auditor o perito contraparte comprueba la integridad sin instalar Evidex ni confiar en quien lo emitió.
3. **Análisis cruzado.** Las señales débiles por separado (una cuenta compartida, un relato parecido, un PDF editado) se vuelven evidentes al verse juntas y conectadas con otros casos.

## Estructura del código

```
evidex/
  core/            cadena de custodia (ledger), casos y evidencia, línea de tiempo, verificador de citas, paquete verificable
  forensics/       motores de análisis, sin dependencia de la web: metadatos y píxeles de fotos, OCR, PDF y sus versiones,
                   chats de WhatsApp, lugares, validación chilena (RUT, patentes), póliza, relato, red de siniestros
  claims/          siniestros: análisis (analysis.py), orquestación (service.py), informe (report.py), guía por alerta,
                   asignación y derivación (assignment.py), importación del historial, Excel
  portal/          enlace del asegurado (links.py) y dirección pública con cloudflared (tunnel.py)
  investigations/  expedientes de peritos (dossier.py), entrevistas y auditoría de informes PDF
  accounts/        usuarios, roles, permisos por vista y registro de accesos
  web/             interfaz: app.py (fábrica y seguridad), common.py (acceso a casos), views/ (una sección por archivo),
                   templates/ (una carpeta por sección), static/ (estilos)
  cli.py           línea de comandos
tests/             una prueba por área (test_core, test_claims, test_forensics, test_portal, test_team, ...)
demo/              generadores de datos ficticios
```

Las dependencias van en una sola dirección: `web` usa `claims`, `investigations`, `portal` y `accounts`; estos usan
`forensics` y `core`; `core` no depende de nadie. Cada vista declara su permiso en `accounts/users.py` (`ENDPOINTS`);
una vista nueva sin permiso declarado queda cerrada.

## Línea de comandos

```bash
python -m evidex.cli demo casos                                   # carga el ejemplo completo
python -m evidex.web --dir casos                                  # interfaz (Importar > historial de ejemplo)
python -m evidex.cli siniestro-init casos/SIN-1 declaracion.json foto1.jpg presupuesto.pdf
python -m evidex.cli siniestro-analizar casos/SIN-1 --registro casos/registro.jsonl
python -m evidex.cli export casos/SIN-1 SIN-1.zip
python -m pytest
```

La declaración es un JSON con `numero` y `fecha_siniestro` obligatorios, y opcionalmente: `asegurado`, `rut`,
`telefono`, `email`, `direccion`, `cuenta_bancaria`, `patente`, `lugar`, `lat`, `lon`, `taller`, `testigos`,
`parte_policial`, `fecha_denuncia`, `poliza`, `inicio_poliza`, `fin_poliza`, `cambio_cobertura`,
`suma_asegurada`, `deducible`, `monto_reclamado`, `descripcion`. Ver `demo/make_claim_demo.py`.

Respuesta a incidentes informáticos: `init`, `add`, `ingest`, `report`, `verify` (ver `python -m evidex.cli -h`).

## Calibración del análisis de imagen

Con 26 fotos reales de muestra (cámaras y fotos de dominio público) y falsificaciones de prueba:

| Prueba | Resultado |
|---|---|
| Falsas alarmas de zona pegada o clonado en fotos limpias | 0 de 52 |
| Fotos guardadas dos veces detectadas | 25 de 26 |
| Zonas pegadas detectadas | 21 de 26 |
| Clonados detectados (zonas de textura suave, como carrocería) | 20 de 26 |
| Falsas alarmas de grano distinto (49 fotos reales y 26 recomprimidas, más la demo) | 1 de 84 (una macro con fondo desenfocado) |
| Zonas pegadas desde otra foto real detectadas solo por el grano | 11 de 78 (prueba complementaria) |
| Recortes reconocidos (40 fotos reales recortadas de 5% a 30% por uno o más bordes y recomprimidas) | 39 de 40 |
| Falsos recortes entre fotos distintas (1.176 pares de fotos reales) | 0 |
| Fotos recortadas o achicadas detectadas por el tamaño anotado por la cámara | 8 de 8 en la muestra pública |

No es una medición con fotos reales de siniestros: los umbrales deben validarse en el piloto. No se incluyó detección de
fotos tomadas a una pantalla por análisis de frecuencia, porque en la calibración confundía texturas reales (ladrillos,
rejillas); el enlace de captura segura y el código en papel cubren ese caso.

## Estado y límites

- Ninguna señal prueba fraude por sí sola, y la ausencia de señales no prueba autenticidad. Las alertas priorizan la revisión humana.
- Los umbrales (días, montos, similitud) son valores iniciales razonables y **deben calibrarse con datos reales** de la aseguradora.
- Metadatos de fotos y PDF se pueden borrar o falsificar; una edición cuidadosa (o un retoque con IA generativa guardado a la misma calidad) puede no dejar huellas en los píxeles. Una imagen generada por IA sin marcas no se detecta (falta un detector por contenido). La extracción de texto y el OCR no demuestran autenticidad documental.
- La red solo ve los siniestros cargados en Evidex; su valor crece con el historial (use Importar).
- Las métricas del historial de ejemplo (detección 75%, precisión 69%) son de datos inventados para mostrar el funcionamiento;
  las cifras reales solo se conocen con un piloto sobre datos de la aseguradora.
- Todos los datos, fotos y documentos del ejemplo son sintéticos e inventados.
- La firma usa una clave local por caso; para peso probatorio fuerte conviene sellado de tiempo externo (RFC 3161) y claves en HSM/KMS. No se ha validado legalmente en tribunales chilenos.
- Corre en un equipo (o en un servidor de la red interna). Datos personales: en producción requiere cifrado en disco, respaldo y cumplimiento de la ley de protección de datos.

## Hoja de ruta sugerida

1. Ajuste de umbrales asistido a partir de las métricas (qué pasa con la detección si se cambia cada umbral).
2. Extracción de texto y OCR de documentos: montos, RUT del taller, patentes en fotos.
3. Detección de imágenes generadas por IA con un modelo propio (sin enviar fotos a terceros).
4. API para que el sistema de siniestros de la aseguradora envíe los casos automáticamente.
5. Sellado de tiempo externo (RFC 3161) y despliegue en un servidor de la compañía con su dominio.
6. Piloto con BCI Seguros: lote de siniestros cerrados y anonimizados, con fraudes confirmados, para medir detección y falsas alarmas.
