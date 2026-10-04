# Modelo aprendido de Evidex (opcional)

Copie aquí los tres archivos que deja `training/entrenar.py`:

- `evidex_ia.onnx` (el modelo)
- `evidex_ia.json` (su ficha: umbral, conjuntos y licencias, sha256)
- `evidex_ia.safetensors` (opcional, solo para seguir entrenando)

Evidex lo detecta solo al abrir un caso y vuelve a analizar los siniestros. Sin estos archivos funciona igual que antes.
No se carga si el sha256 no coincide con la ficha o si algún conjunto de entrenamiento tiene licencia no comercial.
Los archivos del modelo no se suben a GitHub (están en .gitignore): guárdelos aparte.
