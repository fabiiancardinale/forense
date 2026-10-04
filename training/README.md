# Entrenar el detector de ediciones con IA

Hoy Evidex reconoce una edición con IA cuando la foto todavía trae la «firma» de la app: los metadatos de Samsung Galaxy AI, Google, Apple o C2PA (ChatGPT), o la marca visible. Cuando la foto pasa por WhatsApp esa firma se borra. Con las copias que heredan la marca se cubre el caso en que la misma foto llegó antes con su firma, pero no el caso en que solo llega la copia.

Para ese caso hace falta un modelo que mire los píxeles. Esta carpeta lo entrena y lo deja listo para Evidex.

## Línea base medida (4 de octubre de 2026)

Muestra de TGIF (`testing`): 60 originales de MS-COCO y 60 editadas con IA. Se midió con `scripts/benchmark.py`, usando nombres de archivo neutros.

| Caso | Editadas detectadas | Originales con alarma |
|---|---|---|
| SD2, zona reemplazada, sin WhatsApp | 6 de 60 (10 %) | 0 de 60 (sin contar `ai_dimensions`) |
| SD2, zona reemplazada, **pasada por WhatsApp** | 1 de 60 (2 %) | 0 de 60 |
| SDXL, imagen regenerada, **pasada por WhatsApp** | 4 de 60 (7 %) | 0 de 60 |

La regla `ai_dimensions` (tamaño típico de IA) marcó 20 originales. Lo hizo porque TGIF trae originales recortadas a 512 o 1024 px; con fotos de celular no pasa. En esta muestra se mide con `--ignorar ai_dimensions`.

Conclusión: sin la firma, las heurísticas actuales casi no ven la edición. El modelo tiene que superar estos números en el mismo banco de pruebas antes de activarse en producción.

## Pasos (Kaggle o Colab gratis, con GPU)

**Lo más fácil:** importe `training/evidex_kaggle.ipynb` en Kaggle (*Create → New Notebook → File → Import Notebook*), active GPU e Internet en *Settings* y apriete **Run all**. El notebook hace los pasos de abajo solo y, al final, mide con fotos que el modelo nunca vio. Si cambia algo en `training/*.py`, regenere el notebook con `python training/hacer_notebook.py`.

Paso a paso a mano:

1. Datos (unos 30 GB entre las particiones de entrenamiento y validación):

   ```bash
   git clone <URL de su repositorio> evidex && cd evidex
   pip install timm safetensors onnx
   python training/descargar_tgif.py --destino /kaggle/temp/tgif --n 3000 --particion training
   ```

2. Fotos propias (lo que más mejora el resultado en siniestros reales): ponga las fotos en `datos/propias/originales/` y `datos/propias/editadas/`. Para las editadas sirven, por ejemplo, autos con daño agregado o borrado con Galaxy AI, Magic Editor o ChatGPT. Si puede, agregue también `datos/propias/mascaras/` con el mismo nombre, en blanco donde se cambió. Use solo fotos suyas o con permiso escrito. Las fotos reales de BCI requieren su autorización.

3. Manifiesto y entrenamiento:

   ```bash
   python training/datos.py --tgif /kaggle/temp/tgif --propias datos/propias --salida manifiesto.csv
   python training/entrenar.py --manifiesto manifiesto.csv --salida modelos/ --epocas 15 --preentrenado
   ```

   Con 15 000 imágenes en una GPU T4, cuente unas 3 a 5 horas.

4. Medición con el mismo banco de pruebas: copie los tres archivos a `modelos/` y ejecute

   ```bash
   python scripts/benchmark.py --originales <orig> --editadas <editadas> --whatsapp --ignorar ai_dimensions
   ```

   Use imágenes que **no** estuvieron en el entrenamiento, por ejemplo la partición `testing`. Si mejora la línea base sin subir las falsas alarmas, copie `modelos/` al servidor.

## Qué queda guardado y por qué

- `evidex_ia.onnx` es lo que usa Evidex. Corre con onnxruntime (ya instalado por el OCR), sin torch ni GPU en el servidor.
- `evidex_ia.safetensors` guarda los pesos para seguir entrenando. No se usa pickle: un pickle puede ejecutar código al abrirse.
- `evidex_ia.json` es la ficha del modelo: conjuntos y licencias, umbral, métricas de validación, fecha y el sha256 del `.onnx`.

Evidex no carga el modelo en estos casos:

- el sha256 no coincide con la ficha;
- algún conjunto tiene una licencia no comercial o desconocida.

## Licencias de los datos

| Conjunto | Licencia | ¿Se usa? |
|---|---|---|
| TGIF (IDLab, imec) | CC BY 4.0: hay que citar el artículo | Sí |
| TGIF2 (variantes SD) | CC BY-SA 4.0 | Sí (revisar si el «compartir igual» alcanza al modelo) |
| TGIF2 variantes FLUX.1 dev | No comercial (licencia de FLUX.1 dev) | **No** (`datos.py` las excluye) |
| Imágenes base MS-COCO | CC BY (según cada foto de Flickr) | Vienen dentro de TGIF |
| Community Forensics (completo) | CC BY 4.0 | Opcional para una versión 2 |
| Community Forensics *Small* | No comercial | **No** |
| CASIA, DEFACTO, DocTamper, TruFor | No comerciales | **No** |
| Pesos ImageNet de timm (`--preentrenado`) | El código es Apache 2.0; los pesos dependen de ImageNet | Revisar con un abogado antes de vender |

Esto no es asesoría legal; antes de vender, confírmelo con un abogado.

## Límites

- Es una estimación: marca «revisar esta zona» con severidad media y no se presenta como prueba.
- Un modelo entrenado con COCO puede fallar con fotos de autos. Por eso importan las fotos propias y la medición con el banco de pruebas.
- Los editores nuevos de IA dejan huellas distintas: hay que volver a entrenar cada cierto tiempo con ediciones nuevas.
