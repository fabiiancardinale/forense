@echo off
rem Prepara Evidex: instala lo necesario y, la primera vez, crea el administrador.
rem Lo usan iniciar_evidex.bat, iniciar_publico.bat e iniciar_captura.bat, para que los tres instalen lo mismo.
cd /d "%~dp0"
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo No se pudieron instalar las librerias. Revise que Python este instalado y en el PATH.
  pause
  exit /b 1
)
rem Extras (lector de texto/OCR, fotos HEIC de iPhone, firmas C2PA y de PDF). Si alguno falla, Evidex funciona igual.
rem La primera vez pueden tardar unos minutos.
for /f "usebackq eol=- tokens=*" %%p in ("requirements-optional.txt") do (
  python -m pip install --disable-pip-version-check -q %%p >nul 2>&1 || echo Aviso: no se pudo instalar el extra %%p
)
if not exist "casos\usuarios.json" (
  echo Primera vez: cree el usuario administrador de Evidex.
  python -m evidex.accounts.setup --dir casos
  if errorlevel 1 (
    echo No se creo el administrador. Revise el mensaje de arriba: la contrasena debe tener al menos 15 caracteres.
    pause
    exit /b 1
  )
)
exit /b 0
