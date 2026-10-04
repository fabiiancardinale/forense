@echo off
rem Inicia Evidex permitiendo que celulares de la misma red wifi abran los enlaces de captura segura.
cd /d "%~dp0"
call preparar.bat
if errorlevel 1 exit /b 1
echo Si Windows pregunta por el firewall, permita el acceso en redes privadas.
echo En el celular, el navegador mostrara un aviso de certificado: toque Avanzado y Continuar.
python -m evidex.web --dir casos --red
pause
