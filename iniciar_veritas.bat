@echo off
rem Inicia la interfaz de Veritas. Doble clic en este archivo.
cd /d "%~dp0"
python -m pip install --disable-pip-version-check -q flask cryptography pillow openpyxl pdfplumber numpy qrcode
if errorlevel 1 (
  echo No se pudieron instalar las librerias. Revise que Python este instalado y en el PATH.
  pause
  exit /b 1
)
rem Opcional: valida firmas de autenticidad C2PA de las fotos (si falla, Veritas funciona igual)
python -m pip install --disable-pip-version-check -q c2pa-python >nul 2>&1
rem Opcional: lectura de escaneados y patentes (OCR). La primera vez puede tardar unos minutos.
python -m pip install --disable-pip-version-check -q rapidocr_onnxruntime >nul 2>&1
rem Opcional: fotos HEIC de iPhone
python -m pip install --disable-pip-version-check -q pillow-heif >nul 2>&1
python -m veritas.web
pause
