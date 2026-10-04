@echo off
rem Inicia Evidex con una direccion publica (https://...trycloudflare.com) para el portal del asegurado.
rem El asegurado puede abrir el enlace desde cualquier celular. Solo el portal queda en internet; el resto de Evidex sigue local.
cd /d "%~dp0"
call preparar.bat
if errorlevel 1 exit /b 1
if not exist cloudflared.exe (
  echo Descargando cloudflared, solo la primera vez...
  curl -L -s -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
)
if not exist cloudflared.exe (
  echo No se pudo descargar cloudflared. Revise la conexion a internet.
  pause
  exit /b 1
)
python -m evidex.web --dir casos --publico
pause
