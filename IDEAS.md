# Ideas para próximas versiones

Lista de mejoras conversadas, para retomarlas después. Esfuerzo: **rápida** (horas), **media** (días), **grande** (semanas).

## Prioridad para el piloto con BCI
- [ ] **Modo piloto con casos cerrados** (media): cargar siniestros ya resueltos con su resultado real y generar un informe con fraudes detectados, falsas alarmas, monto que se habría evitado pagar y tiempo por caso.
- [ ] **Anonimizador** (rápida): reemplazar nombres, RUT, teléfonos y correos por códigos antes de analizar.
- [ ] **Inicio de sesión obligatorio desde la primera vez** (rápida): hoy funciona abierto hasta crear el administrador.
- [ ] **Informe ejecutivo en PDF** (rápida): una página por caso, con el logo de la compañía.
- [ ] **Ajuste de umbrales desde la pantalla** (media): el jefe sube o baja la sensibilidad de cada prueba y ve cuántas alertas más o menos daría.

## Fotos editadas con IA (plan en 3 capas)
Ningún método solo detecta todo: se combinan las tres capas.

**Capa 1: que no lleguen fotos editadas** (la de más impacto)
- [ ] **Captura segura obligatoria en el portal** (rápida): las fotos del daño se toman con la cámara en el momento, sin subir desde la galería.
- [ ] **Pedir el original** (rápida): si una foto llega de galería o WhatsApp, sin datos o recortada, se marca "no verificable" y se le pide al asegurado el archivo original (WhatsApp como Documento o por el portal). El original trae la anotación de IA de Samsung o Google y la firma C2PA, que Evidex ya lee.

**Capa 2: reglas de Evidex** (hechas)
- [x] Marca visible "Contenido generado por IA" leída con OCR.
- [x] Foto recorte de otra del caso, y recorte que sacó la marca de IA.
- [x] Zona borrada o cambiada entre dos versiones de la misma foto.
- [x] Proporción que no es de cámara.

**Capa 3: modelo forense propio** (grande)
- [ ] Probar modelos de licencia libre con fotos reales: IML-ViT (MIT, ubica la zona editada) y SPAI (Apache 2.0, imágenes generadas completas). Revisar que los pesos también permitan uso comercial.
- [ ] No usar TruFor: su licencia prohíbe el uso comercial (se probó solo como referencia: marcó la foto con el logo borrado con 0,55 contra 0,09-0,25 de fotos normales).
- [ ] Integrarlo como "análisis profundo" con mapa de calor, primero solo como apoyo ("revisar esta zona"), en segundo plano.
- [ ] Ajustarlo con fotos propias en GPU gratuita (Kaggle o Colab). Meta medida: 9 de cada 10 ediciones con menos de 2 falsas alarmas por 100 fotos normales.
- [ ] Guardar los pesos en safetensors (no pickle: puede ejecutar código y se rompe entre versiones) y correrlo con ONNX + onnxruntime, sin instalar PyTorch. Cargar una vez al iniciar; el archivo se descarga al instalar con su huella digital, fuera de GitHub; cada versión nueva reanaliza los casos.
- [ ] Opción: huella del ruido propia (idea de Noiseprint del artículo de TruFor, con código y datos propios), entrenada solo con fotos sin editar.

**Banco de pruebas** (media)
- [ ] Sección en Evidex: se sube una carpeta con pares original/editada, Evidex los empareja, marca la zona cambiada (sirve de etiqueta para entrenar) y mide cada prueba.
- [ ] Juntar fotos: autos propios o de conocidos (nunca de asegurados), editados con Galaxy AI, Google Fotos, iPhone, Meta AI, ChatGPT y Gemini (borrar o agregar daño, cambiar patente o color, quitar objetos), cada editada también pasada por WhatsApp. Nombres 001_original.jpg, 001_editada.jpg, 001_whatsapp.jpg y una nota de qué se cambió y con qué app. Meta: 100 pares para medir, 500 a 1.000 para entrenar, más 300 fotos sin editar.

## Documentos
- [ ] **Timbre electrónico de facturas y boletas** (media): leer el código de barras del SII (PDF417), comparar RUT, folio, fecha y monto con lo impreso, y verificar su firma sin internet. Si se editó el monto en el PDF, el timbre sigue diciendo el original.
- [ ] **Que las cuentas cuadren** (rápida): suma de líneas, IVA 19%, total = neto + IVA.
- [ ] **Texto tapado y reescrito** (media): rectángulo blanco sobre un monto con texto nuevo encima, o un número con otra fuente o tamaño que el resto.
- [ ] **Documentos que llegan como foto o escaneo** (rápida): aplicarles las pruebas de imagen (zona pegada, clonada, grano distinto, dígito copiado).
- [ ] **Cruces entre siniestros** (rápida): mismo folio en dos casos; mismo taller con presupuestos idénticos para daños distintos; misma firma o timbre (imagen idéntica) en documentos de distintas personas.
- [ ] **Códigos de verificación** (media): certificados del Registro Civil (anotaciones vigentes), constancias de Carabineros, permisos de circulación y revisión técnica traen un código o QR para validar en línea; revisar que el QR apunte al dominio oficial y que el documento exista.
- [ ] **Taller real** (media): RUT del emisor con actividad de taller o venta de repuestos en el SII, y que estuviera vigente en la fecha de la factura.
- [ ] **Folios fuera de orden** (rápida): facturas del mismo taller en distintos siniestros cuyo folio no avanza con la fecha (una factura "antigua" con folio nuevo se hizo después).
- [ ] **Plantilla del taller** (media): comparar fuente, programa y formato con documentos anteriores del mismo taller; uno distinto puede ser fabricado.
- [ ] **Fuentes más nuevas que el documento** (rápida): un PDF fechado en 2023 que usa una fuente publicada en 2025 se hizo después.
- [ ] **Contenido oculto** (rápida): texto blanco, texto fuera de la página, capas ocultas o código JavaScript dentro del PDF.

## Inteligencia artificial de texto (Groq u otro)
No sirve para detectar ediciones en fotos (adivina con buena redacción). Sí para:
- [ ] Coherencia entre relato y fotos (dice choque trasero, las fotos muestran la puerta delantera).
- [ ] Mismo color, modelo y patente del auto en todas las fotos.
- [ ] Preguntas para la entrevista según las alertas.
- [ ] Resumen del caso para el jefe.
- Requiere clave de API en la configuración (nunca en GitHub) y aprobación de BCI, porque las fotos y datos salen a un servidor externo.

## Ideas novedosas (diferenciadoras)
- [ ] **Los dos autos deben calzar** (grande): el daño del asegurado y el del otro auto tienen que corresponder en altura, forma y pintura transferida (restos del color del otro auto en el golpe). Un golpe a 80 cm del suelo no lo hace el parachoques de un auto bajo; pintura blanca en el golpe no viene de un auto rojo.
- [ ] **Sombras contra la hora** (media): calcular hacia dónde debía caer la sombra según el sol en ese lugar y hora, y compararlo con las sombras de la foto. Extiende la prueba de "foto de día con hora de noche" a cualquier hora del día.
- [ ] **Edad del daño** (grande): óxido, polvo o barro dentro de la abolladura, o bordes de pintura gastados, indican un daño de semanas o meses, no del día declarado.
- [ ] **Auto comprado ya chocado** (media): buscar las fotos del auto y la patente en avisos de venta (Marketplace, Yapo, Chileautos) y remates de vehículos siniestrados. Patrón conocido: comprar barato un auto chocado, asegurarlo y declarar el choque.
- [ ] **Conflicto de interés con el taller** (media): cruzar el RUT del dueño del taller con el asegurado usando el Registro de Empresas y Sociedades (público): mismo apellido, misma dirección o socios en común.
- [ ] **Medir el daño en 3D** (grande): con el video alrededor del auto, reconstruir la abolladura en 3D, medir su profundidad y comparar con lo que cobra el presupuesto.
- [ ] **Avisar en vivo** (media): mientras el asegurado llena el portal, Evidex ya revisa; si algo no cuadra (foto antigua, sin el código al azar), le pide otra foto en ese momento, antes de que el caso llegue al analista.

## Ranking de talleres (en Cartera, junto a Redes y Métricas)
No es "taller externo = sospechoso": se mira cada taller, en convenio o no, sobre todos sus casos.
- Porcentaje de sus siniestros con alertas, comparado con el promedio de los talleres.
- Presupuestos muy por sobre el promedio para daños parecidos.
- Mismas piezas caras cobradas una y otra vez.
- Mismas personas, teléfonos o cuentas repitiéndose entre sus siniestros.
- Fechas raras en presupuestos o facturas (anteriores al choque).
- Sirve para auditar la red de talleres y negociar convenios, no solo para detectar fraude del asegurado.
- Por confirmar con BCI: qué pólizas permiten elegir taller (autos nuevos, servicio de la marca).

## Más detección
- [ ] Comparar el daño con fotos del mismo auto (por patente) en siniestros anteriores (media).
- [ ] Clima real del día y lugar contra lo que muestra la foto (media, requiere internet).
- [ ] Montos fuera de rango para ese daño y ese modelo (media).
- [ ] Coherencia entre las fotos del siniestro: color, modelo y patente del auto (media).
- [ ] Huella del sensor: comprobar que varias fotos vienen del mismo teléfono aunque no tengan metadatos (grande).
- [ ] **Revisión de videos** (grande), por partes:
  - Metadatos del video: fecha, GPS, teléfono y programa con que se grabó o editó (sirven igual que en las fotos).
  - Cortes y empalmes: saltos de imagen, cuadros repetidos o insertados, cambios de calidad a mitad del video.
  - Mismo auto en una sola toma: patente y daño visibles sin corte, lo que prueba que el daño es de ese auto.
  - Cuadros clave: sacar imágenes del video y pasarles todas las pruebas de foto (reuso, internet, IA, zonas pegadas).
  - Video generado con IA: marcas C2PA y de los generadores (Sora, Veo y otros), y señales típicas como reflejos o letras que cambian entre cuadros.
  - Sonido: ambiente que no calza con el lugar o la hora (lluvia en un día seco, ruido de autopista en un pasaje).
  - Cámara de tablero: velocidad y hora del choque según el video contra lo declarado.
- [ ] **Código al azar en la foto** (rápida): el portal muestra un código (por ejemplo "K7P2") y el asegurado lo escribe en un papel junto al daño. Prueba que la foto se tomó en ese momento; una foto antigua o editada no lo trae.
- [ ] **Video corto alrededor del auto** (media): en la captura segura, 10 segundos rodeando el vehículo con la patente visible. Un video es mucho más difícil de editar con IA que una foto y confirma que el daño es de ese auto.
- [ ] **Mismo teléfono en el portal para distintos asegurados** (rápida): huella del navegador y red desde donde se suben las fotos; si coinciden entre asegurados distintos, puede ser la misma persona o el mismo taller armando los casos.
- [ ] **Odómetro** (media): leer el kilometraje en la foto del tablero y compararlo con siniestros o revisiones técnicas anteriores del mismo auto.
- [ ] **Fraude interno** (media): analistas o peritos que cierran como legítimos, una y otra vez, casos con alertas altas, o que siempre derivan al mismo taller.
- [ ] **Inspección al contratar** (media): comparar las fotos del siniestro con las de la inspección que se hizo al contratar la póliza; si el daño ya estaba, es un daño previo cobrado como nuevo.
- [ ] **Contraparte relacionada** (rápida): el otro conductor del choque comparte apellido, dirección, teléfono o correo con el asegurado (choque arreglado entre conocidos).
- [ ] **Testigos repetidos** (rápida): la misma persona aparece como testigo o contraparte en varios siniestros.
- [ ] **Cuenta de pago de otra persona** (rápida): el RUT del titular de la cuenta bancaria no es el del asegurado.
- [ ] **Contacto desechable** (rápida): correo de dominios temporales o teléfono recién creado en los datos del siniestro.
- [ ] **Documentos del auto vencidos** (rápida): revisión técnica o permiso de circulación vencidos a la fecha del choque (posible motivo para inventar fecha o circunstancias).
- [ ] **Riesgo que aprende de las decisiones** (grande): con los casos ya cerrados como fraude o legítimos, ajustar el peso de cada alerta según cuánto acertó en la cartera de BCI.
- [ ] **Explicar el puntaje** (rápida): mostrar qué alertas suman cuánto al riesgo del caso, para que el analista entienda y pueda justificar la decisión.

## Para el analista y el jefe
- [ ] Notificaciones por correo o WhatsApp: el asegurado subió algo, el perito entregó, un caso se atrasó (media).
- [ ] Recordatorio automático al asegurado si no sube nada en 2 días (rápida).
- [ ] Comentarios internos en el caso entre analista, jefe y perito, en la cadena de custodia (rápida).
- [ ] Preguntas sugeridas para la entrevista según las alertas del caso (rápida).
- [ ] Búsqueda global por RUT, patente, teléfono o taller (rápida).
- [ ] Panel de tendencias: fraudes por mes, comuna, taller y tipo de señal (media).

## Seguridad y requisitos de TI
- [ ] Cifrado de los casos en el disco (media).
- [ ] Inicio de sesión con las cuentas corporativas (Microsoft o Google) (media).
- [ ] Respaldo automático y auditoría exportable (rápida).
- [ ] Sello de tiempo externo (RFC 3161) para la evidencia (media).
- [ ] Instalación en un servidor de la compañía con su dominio (media).

## Para crecer después de BCI
- [ ] Conexión con el sistema de siniestros de la aseguradora (grande).
- [ ] Varias compañías en una instalación, con detección de redes entre compañías si lo autorizan (grande).
- [ ] Otros ramos: hogar, salud, robo (grande).
- [ ] App para el perito: entrevistas grabadas y transcritas desde el celular (grande).

## Para ofrecerlo
- Piloto de 60 a 90 días con siniestros cerrados y anonimizados, gratis o a bajo costo, con informe de resultados en números de BCI.
- Antes: confirmar de quién es la propiedad del software según el contrato de trabajo (consultar abogado).
- Lo que pedirán: empresa formal, NDA, revisión de TI y cumplimiento (ley de datos personales), contrato con nivel de servicio.
