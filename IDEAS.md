# Ideas para próximas versiones

Lista de mejoras conversadas, para retomarlas después. Esfuerzo: **rápida** (horas), **media** (días), **grande** (semanas).

## Prioridad para el piloto con BCI
- [ ] **Modo piloto con casos cerrados** (media): cargar siniestros ya resueltos con su resultado real y generar un informe con fraudes detectados, falsas alarmas, monto que se habría evitado pagar y tiempo por caso.
- [ ] **Anonimizador** (rápida): reemplazar nombres, RUT, teléfonos y correos por códigos antes de analizar.
- [ ] **Inicio de sesión obligatorio desde la primera vez** (rápida): hoy funciona abierto hasta crear el administrador.
- [ ] **Informe ejecutivo en PDF** (rápida): una página por caso, con el logo de la compañía.
- [ ] **Ajuste de umbrales desde la pantalla** (media): el jefe sube o baja la sensibilidad de cada prueba y ve cuántas alertas más o menos daría.

## Marca
- [ ] **Cambiar el nombre a "Evidex by Zelekpress"** (rápida): menú, títulos, informes, portal del asegurado, lanzador `iniciar_evidex.bat`. Ya está hecho y probado en la rama `evidex-renombre`; basta con fusionarla cuando se decida.

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
- [ ] Detector propio de imágenes hechas con IA, sin enviar fotos a terceros (grande).
- [ ] Huella del sensor: comprobar que varias fotos vienen del mismo teléfono aunque no tengan metadatos (grande).
- [ ] Revisión de videos (choque, cámara de tablero) (grande).

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
