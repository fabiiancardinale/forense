@echo off
rem Inicia Evidex permitiendo que celulares de la misma red wifi abran los enlaces de captura segura.
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
echo Si Windows pregunta por el firewall, permita el acceso en redes privadas.
echo En el celular, el navegador mostrara un aviso de certificado: toque Avanzado y Continuar.
if not exist "casos\usuarios.json" python -m evidex.accounts.setup --dir casos
if errorlevel 1 exit /b 1
python -m evidex.web --legacy --red
pause
