@echo off
rem Inicia Evidex con una direccion publica (https://...trycloudflare.com) para el portal del asegurado.
rem El asegurado puede abrir el enlace desde cualquier celular. Solo el portal queda en internet; el resto de Evidex sigue local.
cd /d "%~dp0"
python -m pip install --disable-pip-version-check -q flask cryptography pillow openpyxl pdfplumber numpy qrcode
if errorlevel 1 (
  echo No se pudieron instalar las librerias. Revise que Python este instalado y en el PATH.
  pause
  exit /b 1
)
rem Opcional: valida firmas de autenticidad C2PA de las fotos (si falla, Evidex funciona igual)
python -m pip install --disable-pip-version-check -q c2pa-python >nul 2>&1
rem Opcional: lectura de escaneados y patentes (OCR). La primera vez puede tardar unos minutos.
python -m pip install --disable-pip-version-check -q rapidocr_onnxruntime >nul 2>&1
rem Opcional: fotos HEIC de iPhone
python -m pip install --disable-pip-version-check -q pillow-heif >nul 2>&1
if not exist cloudflared.exe (
  echo Descargando cloudflared, solo la primera vez...
  curl -L -s -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
)
if not exist cloudflared.exe (
  echo No se pudo descargar cloudflared. Revise la conexion a internet.
  pause
  exit /b 1
)
if not exist "casos\usuarios.json" python -m evidex.accounts.setup --dir casos
if errorlevel 1 exit /b 1
python -m evidex.web --legacy --publico
pause
