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
- [x] Lectura completa de metadatos de cualquier marca: Samsung Galaxy AI y editor de galería, Google, Apple, XMP/IPTC «tipo de origen digital», C2PA (acciones y foto de origen), fechas de todas las secciones.
- [x] Marca visible "Contenido generado por IA" leída con OCR.
- [x] Foto recorte de otra del caso, y recorte que sacó la marca de IA.
- [x] Zona borrada o cambiada entre dos versiones de la misma foto.
- [x] Proporción que no es de cámara.

**Capa 3: modelo forense propio** (grande)
- [ ] Probar modelos de licencia libre con fotos reales: IML-ViT (MIT, ubica la zona editada) y SPAI (Apache 2.0, imágenes generadas completas). Revisar que los pesos también permitan uso comercial.
- [ ] No usar TruFor: su licencia prohíbe el uso comercial (se probó solo como referencia: marcó la foto con el logo borrado con 0,55 contra 0,09-0,25 de fotos normales).
- [x] **Vuelta 1 del entrenamiento en Kaggle** (5 de octubre de 2026): con fotos pasadas por WhatsApp, 4 falsas alarmas de 300 originales; detecta 69 de 300 ediciones de una zona (antes 2 de 100) y 215 de 300 regeneradas completas (antes 7 de 100).
- [x] **Vuelta 2** (descartada): falsas alarmas 33 de 300 (11 %), zona SD2 45, SDXL regenerada 165, SD2 regenerada 107, Photoshop zona 24 de 300. Peor que la vuelta 1: las regeneradas completas tenían la máscara solo en la zona (corregido en la vuelta 3) y probablemente faltaron épocas. Se sigue usando la vuelta 1.
- [x] **Primera prueba con fotos reales editadas con IA** (7 de octubre de 2026, 6 fotos editadas por Fabián y pasadas por WhatsApp, modelo de la vuelta 3 calibrado): detectó 1 de 6 (el parachoques del Kia, 0,9995 con umbral 0,9992); las otras quedaron entre 0,33 y 0,994. Coincide con lo medido en TGIF para zonas editadas (~22 %) y confirma que hacen falta fotos de autos para entrenar.
- [ ] **Captura segura obligatoria cuando no hay original** (rápida, la defensa más fuerte hoy): si las fotos llegan por WhatsApp sin metadatos, Evidex sugiere pedir fotos nuevas por el portal con la cámara en vivo (no se pueden editar antes de subirlas).
- [x] **Vuelta 3, mosaico a tamaño real** (6 de octubre de 2026, desde la vuelta 1, 25 épocas en 3,4 h). Prueba con 300 fotos por tipo pasadas por WhatsApp: falsas alarmas 9 (3 %), zona SD2 104 (35 %, antes 23 %), SD2 regenerada 195 (65 %), SDXL regenerada 295 (98 %, antes 72 %), Photoshop zona 18 (6 %). La validación se estancó desde la época 3 mientras la pérdida seguía bajando: el modelo memoriza; más datos ahora sí ayudarían.
- [x] **Umbral calibrado** (6 de octubre de 2026, 1.023 originales de «validation», meta 1,5 %, umbral 0,99922). Prueba (testing, WhatsApp): falsas alarmas 5 de 300 (1,7 %), zona SD2 22 %, SD2 regenerada 50 %, SDXL regenerada 95 %, Photoshop zona 2 %. Frente a la vuelta 1 con falsas alarmas parecidas: igual en zonas, mucho mejor en regeneradas. Ojo: en «validation» detectaba más (zona SD2 37 %, Photoshop 29 %) que en «testing»: el modelo generaliza peor a fotos de otros temas → hace falta más variedad (fotos de autos).
- [ ] **Photoshop (relleno generativo) casi no se detecta** (media): 6 %. Revisar sus máscaras y probar con más ejemplos y el canal de ruido.
- [ ] **Canal de ruido para el modelo** (media): además de los colores, darle una versión de la foto que muestre solo el grano del sensor (filtros SRM o una huella de ruido propia); la IA imita bien la forma pero no el grano de la cámara.
- [ ] **Modelo más grande** (después): efficientnet_b2 o similar si la vuelta 3 se queda corta; medir cuánto tarda por foto en el servidor.
- [ ] **Fotos de autos editadas para el entrenamiento** (lo que más ayudaría): ver la sección de juntar fotos.
- [ ] **Segundo modelo para imágenes 100% generadas** (media): Community Forensics (CC BY 4.0), misma ficha y mismo banco de pruebas.
- [ ] **Banco de pruebas en la pantalla** (media): subir una carpeta de originales y editadas y ver los números sin usar la consola.
- [x] Integrarlo como "análisis profundo" con mapa de calor, primero solo como apoyo ("revisar esta zona"), en segundo plano.
- [ ] Ajustarlo con fotos propias en GPU gratuita (Kaggle o Colab). Meta medida: 9 de cada 10 ediciones con menos de 2 falsas alarmas por 100 fotos normales.
- [x] Guardar los pesos en safetensors (no pickle: puede ejecutar código y se rompe entre versiones) y correrlo con ONNX + onnxruntime, sin instalar PyTorch. Cargar una vez al iniciar; el archivo se descarga al instalar con su huella digital, fuera de GitHub; cada versión nueva reanaliza los casos.
- [ ] Opción: huella del ruido propia (idea de Noiseprint del artículo de TruFor, con código y datos propios), entrenada solo con fotos sin editar.

**Datasets con licencia que permite uso comercial** (revisar la letra chica con un abogado antes de vender)
- [ ] **TGIF / TGIF2** (Universidad de Gante, CC BY 4.0 / CC BY-SA 4.0): ~271.000 fotos reales editadas localmente con IA (SD2, SDXL, Firefly, FLUX) con la máscara de la zona cambiada. Base para entrenar el modelo que marca la zona editada. Cuidado: fotos de MS-COCO (licencias de Flickr mezcladas) y parte hecha con FLUX.1 dev (licencia propia): preferir la parte de SD2/SDXL o confirmar con los autores. https://github.com/IDLabMedia/tgif-dataset
- [ ] **Community Forensics** (CVPR 2025, CC BY 4.0, versión base, no la "Small" que es no comercial): imágenes reales y generadas por miles de modelos. Para el detector de imágenes 100% inventadas con IA.
- [ ] **Fotos de daños de autos** (Roboflow Universe, revisar licencia de cada uno; muchos CC BY 4.0): fotos base para el generador propio (borrar o agregar daños con IA).
- Descartados: CASIA v2, DEFACTO, DocTamper (solo investigación o no comercial), Semi-Truths (licencia no especificada), InfImagine (comercial solo con permiso escrito). Sirven solo para pruebas internas si su licencia lo permite.
- [x] Código del plan listo (`training/`: descarga parcial de TGIF, manifiesto con licencias que rechaza las no comerciales, aumentos tipo WhatsApp, entrenamiento, exportación ONNX + ficha). Falta correrlo en GPU (Kaggle/Colab).
- [ ] **Plan de entrenamiento:** 1) TGIF2 pasado por compresión tipo WhatsApp para aprender a ubicar zonas editadas; 2) ajuste con fotos de autos editadas automáticamente y con las fotos propias (Galaxy AI, Google, iPhone); 3) detector aparte con Community Forensics; 4) medir siempre con fotos propias que no se usan para entrenar. Guardar el modelo en safetensors/ONNX con la lista de datasets y licencias usadas (BCI lo va a preguntar).
- [x] **Medición del punto de partida** (rápida, hecha con TGIF: sin la firma de la app, Evidex de hoy detecta 2-7 de cada 100 editadas pasadas por WhatsApp; ver training/README.md; falta repetirla con fotos propias): 200 fotos editadas con IA y pasadas por WhatsApp (TGIF2 + propias) y 200 normales por Evidex de hoy; repetir con el modelo entrenado. El número para BCI: "de 100 fotos editadas con IA mandadas por WhatsApp, Evidex detecta X, con Y falsas alarmas por cada 100 normales".
- Qué mejora: la foto editada con IA que llega sola por WhatsApp (hoy casi no se detecta) y las imágenes inventadas sin marcas. Qué no cambia: lo que ya detectan los metadatos, fotos repetidas, documentos y redes. Límites: la compresión de WhatsApp borra huellas, las IA nuevas obligan a reentrenar y habrá falsas alarmas (mostrar como "revisar esta zona").

**Heredar la marca de IA a las copias** (rápida)
- [x] Si una foto es copia, recorte o versión achicada de otra del caso con marcas de IA, alerta alta "Copia de una foto editada con IA".
- [x] Lo mismo entre siniestros: guardar en el registro si la foto tenía marcas de IA.

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

## Prioridad de revisión de siniestros (riesgo del caso, no de la persona)
Idea central: no decir «quién es estafador», sino «qué siniestro conviene revisar primero y por qué». Siempre decide un analista; Evidex solo ordena la bandeja y explica.

- [ ] **Puntaje de prioridad explicable** (media, se puede hacer ya, sin datos de BCI): de 0 a 100 por siniestro, sumando lo que Evidex ya calcula y las circunstancias del caso, con cada punto a la vista («+25 foto editada con IA», «+15 póliza contratada hace 5 días»). Ordena la bandeja del analista; nunca rechaza un siniestro por sí solo.
  - Señales de la evidencia: fotos editadas o reutilizadas, documentos alterados, fechas o GPS que no calzan, copias de fotos con marca de IA.
  - Señales del siniestro: póliza muy reciente, aviso tardío, monto alto para el tipo de daño, varios siniestros seguidos, mismo taller, testigos o teléfono en casos distintos (Redes).
  - Pesos ajustables por el jefe (ver «Ajuste de umbrales desde la pantalla») y registro de cada cambio.
- [ ] **Modelo entrenado con siniestros cerrados de BCI** (grande, después): reemplaza los pesos a mano por un modelo (por ejemplo, árboles de decisión potenciados) entrenado con casos antiguos y su resultado real (fraude confirmado o no). Requiere autorización escrita de BCI y datos anonimizados. Se mide igual que el detector de fotos: cuántos fraudes encuentra en el 10 % de casos con puntaje más alto y cuántas falsas alarmas da.
- [ ] **Explicación obligatoria** (rápida): cada puntaje muestra sus razones en el informe. Lo exige la Ley 21.719 (vigente desde diciembre de 2026) para decisiones con apoyo automatizado: derecho a explicación y a revisión humana.
- [ ] **Datos que nunca se usan** (regla fija): edad, sexo, nacionalidad, comuna, nivel de ingresos ni nada que funcione como reflejo de ellos. Revisar cada señal nueva antes de agregarla.
- [ ] **Control de sesgo** (media): revisar cada cierto tiempo si el puntaje marca más a algún grupo sin que haya más fraude confirmado en ese grupo, y que el modelo no aprenda solo de quién fue investigado antes (eso repite las sospechas del pasado).
- [ ] **Revisión legal antes de usarlo con casos reales** (con abogado): base legal del tratamiento, aviso al asegurado, derecho de oposición a decisiones automatizadas y evaluación de impacto.

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

## Datos personales: quién ve qué y cuánto tiempo se guardan (Ley 21.719)
Zelekpress es el encargado y BCI el responsable de los datos. Revisar todo con abogado y dejarlo en el contrato.

- [ ] **Nivel 1: datos ocultos según el rol** (media, para el piloto): el admin de Zelekpress ve códigos («ASEG-7F3A», «12.***.***-5», «PAT-91C2»); los usuarios de BCI ven los datos reales. Las fotos y los documentos del caso no se abren con rol de Zelekpress.
- [ ] **Nivel 2: cifrado con clave de BCI** (grande, antes de producción en Hostinger): nombres, RUT, teléfonos, direcciones y documentos se guardan cifrados; la clave se abre solo con la sesión de un usuario de BCI. Ni Zelekpress ni quien entre al servidor puede leerlos. Clave de respaldo guardada por BCI (si se pierden todas, los datos no se recuperan).
- [ ] **Cruces sin ver el dato** (media): mismo RUT, teléfono o patente en varios siniestros se detecta con una huella con clave (HMAC), sin mostrar el dato.
- [ ] **Acceso de soporte temporal** (media): si Zelekpress necesita entrar a un caso, BCI da un permiso por tiempo limitado; queda registrado quién entró, cuándo y qué vio.
- [ ] **Plazo de conservación** (media): al cerrar un caso, Evidex calcula su fecha de borrado (plazo fijado por BCI). Durante el plazo, el caso queda cifrado y con acceso restringido al jefe.
- [ ] **Borrar o anonimizar al vencer el plazo** (media): aviso al jefe con botón para borrar o anonimizar (reemplazar nombre, RUT, teléfono y patente por códigos; quitar GPS y metadatos de las fotos; borrar documentos), con registro de quién lo hizo. Lo anonimizado de verdad deja de ser dato personal y sirve para estadísticas.
- [ ] **Pedido de borrado del asegurado** (rápida): procedimiento para cuando una persona pide borrar sus datos antes del plazo (lo decide BCI).

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
