# MVP: garantías, operación y validación

## Alcance

El flujo predeterminado es login → `/analizar` → cola persistente → proceso de análisis → informe privado. Los módulos históricos de siniestros, captura pública, importación y peritajes se conservan detrás de `--legacy`; no forman parte del perímetro endurecido del MVP. No activarlos en un servicio público sin una revisión adicional.

No se emite un certificado «Original». Los estados distinguen cambio recuperable entre revisiones PDF, indicios heurísticos, ausencia de indicios y análisis no concluyente. La etiqueta y el estado de procesamiento son independientes: un archivo puede contener un hallazgo útil y tener comprobaciones pendientes. Generación completa por IA, edición localizada, procedencia firmada y fraude son conceptos diferentes.

## Arranque

Python 3.12; entorno virtual recomendado. Desde la raíz del repositorio:

```sh
python -m pip install -r requirements.txt
python -m evidex.accounts.setup --dir casos
python -m evidex.web --dir casos
```

El lanzador local inicia un worker; si se administra aparte, iniciar la web con `--sin-worker` y ejecutar `python -m evidex.inspection.worker --dir casos`. La carpeta debe coincidir y debe estar en disco local, no NFS/Dropbox. `--once` procesa como máximo un trabajo para operación y pruebas. Una interrupción se hace visible cuando otro worker recupera la cola; no se repiten automáticamente solicitudes potencialmente facturables.

La inicialización administrativa y la recuperación (`--reset`) requieren acceso local al servidor. La corrupción del registro bloquea acceso: restaurar el respaldo, no borrar archivos para «arreglar» el login. Conservar usuarios, marcador de inicialización, bases SQLite y clave de sesión al migrar; las sesiones anteriores a esta versión requieren reingreso. Para la demostración histórica explícita: `python -m evidex.web --demo --legacy`, solo localhost.

## Controles implementados

- CSRF en formularios y llamadas del portal; logout solo POST; CSP con nonce; no-store, nosniff y protección frente a iframes.
- Nuevas contraseñas de 15 a 256 caracteres, guardadas con hash; las cuentas existentes se conservan.
- Sesiones revocables persistentes: 30 minutos de inactividad y 8 horas máximas. Cambio de contraseña/rol o desactivación invalida sesiones previas.
- Limitación durable de intentos fallidos por cuenta (5/5 minutos) e IP (30/5 minutos), compartida entre procesos. No sustituye el control volumétrico del proxy.
- Cada análisis pertenece a un usuario; ni un administrador obtiene acceso implícito a los archivos de otro usuario por conocer su identificador.
- Carga por streaming con huella SHA-256, nombres generados y verificación del hash antes de procesar. Idempotencia por usuario/solicitud. No se sirven originales ejecutables ni HTML de usuario.
- 25 MB por archivo, 40 megapíxeles, una imagen por archivo, 20 páginas PDF; formato declarado debe concordar con decodificador. Cifrados, truncados y formatos no admitidos terminan rechazados, sin veredicto de originalidad.
- Cola SQLite con reclamación transaccional, leases y reintento manual máximo de tres intentos. Cuotas: 10 pendientes, 30 cargas/hora y 1 GB por usuario. Los archivos se conservan; administrar retención y espacio antes de un despliegue multiusuario.
- Proceso descartable por archivo: timeout de 120 segundos; en POSIX 110 segundos CPU, 3 GiB de espacio virtual y 64 MiB por archivo de salida. Windows requiere límites del sistema para memoria/CPU. No es un sandbox de seguridad del kernel.
- Red Python deshabilitada por defecto en el runner. Un SDK nativo no queda confinado por esa medida; aplicar una política de red del sistema operativo.
- Escrituras atómicas de usuarios/configuración y bloqueos entre procesos para ledger y registro. Se preserva la firma Ed25519 existente.

## Motores y cobertura

El análisis local conserva metadatos, recompresión, clonado y anomalías de ruido. Son heurísticas: compresión, recortes legítimos y exportaciones pueden producir señales. Falta de EXIF y recompresión aislada se presentan como observaciones. Los mapas señalan regiones sospechosas; no son máscaras verificadas de adulteración.

C2PA distingue ausencia, error, credencial inválida e integridad válida con/sin confianza del firmante. Una firma válida no establece verdad visual. Sin validador instalado se muestra «no ejecutado». PDF recupera cambios textuales entre revisiones legibles que permanezcan en el archivo; más de 20 marcadores de revisión limita la comparación. No puede recuperar lo borrado al reexportar un documento. OCR informa páginas legibles y cobertura; no detecta falsificación por sí mismo.

Opcionales fijados en `requirements-optional.txt`: `python -m pip install -r requirements-optional.txt`. Incluye `c2pa-python`, `pillow-heif`, `rapidocr_onnxruntime` y `pyHanko`. HEIC sin decodificador se rechaza explícitamente. Firmas PDF se validan sin consultas de red: confianza/revocación no equivalen a una validación PKI completa en línea. No se han instalado pesos de un modelo local de IA ni un localizador aprendido.

Sightengine se configura en Configuración y se usa solo con autorización por archivo en el MVP. Se envía la imagen al proveedor y puede tener coste. Respuestas sin score numérico finito 0–1 son errores. Un score ≥0,8 se usa exclusivamente como indicio de triaje, no como probabilidad calibrada ni prueba de edición localizada. No se afirma identificar con certeza una herramienta de edición.

## Despliegue

El servidor Flask del lanzador es local. Para internet, usar un servidor WSGI mantenido con HTTPS en un proxy y una fábrica que pase `PRODUCTION=True`; así se fuerzan cookies Secure, HSTS, autenticación y CSRF. Configurar hosts permitidos (`TRUSTED_HOSTS`) y límites del proxy; no confiar indiscriminadamente en encabezados reenviados. La protección histórica contra túneles bloquea `X-Forwarded-For`: el proxy del MVP debe retirarlo y preservar Host/esquema HTTPS mediante una configuración de confianza explícita. La IP puede entonces ser la del proxy: dimensionar el límite por IP o integrarlo con un proxy de confianza antes de abrir al público.

Ejecutar web y worker como usuarios sin privilegios, con volumen privado, copias consistentes de SQLite y monitorización de trabajos atascados/espacio. Aislar el worker con contenedor/VM, memoria/CPU/PIDs limitados, sin secretos ajenos al análisis y sin salida a red salvo los destinos explícitamente autorizados. Un proceso hijo bajo el mismo usuario no protege los datos frente a una vulnerabilidad nativa del parser. No se ha desplegado ni verificado una infraestructura productiva en este cambio.

## Verificación y criterios de lanzamiento

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/evaluate_predictions.py conjunto_etiquetado.jsonl
```

Los tests de endurecimiento cubren corrupción, CSRF, revocación, bloqueo persistente, acceso ajeno, duplicados, worker real, formatos, leases y errores de proveedores/C2PA. CI define Linux y Windows; un resultado local no demuestra que la matriz remota haya pasado.

Antes de prometer detección fiable, reunir un conjunto de referencia con permiso: originales verificables de cámaras diversas, edición clásica localizada, generación IA de varias familias, edición IA, recodificación/WhatsApp, PDFs digitales e incrementales, escaneados y documentos legítimamente corregidos. Separar familias de origen entre entrenamiento/calibración/prueba; conservar máscaras de edición y referencias para evaluar localización. Medir precisión, recuperación, falsos positivos y abstención por grupo, incluyendo archivos dañados y desconocidos. El evaluador JSONL cuenta abstenciones en los denominadores y rechaza IDs duplicados; no inventa resultados ni fija un umbral clínico/legal/comercial universal.

Pendiente para ese lanzamiento: corpus real etiquetado y métricas, modelo/localizador con licencia apta y calibración del dominio, revisión independiente, aislamiento operativo, retención/borrado y monitorización. El cambio endurece el software; no demuestra exactitud forense universal ni atribución inequívoca a IA.
