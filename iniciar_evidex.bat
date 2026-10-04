@echo off
rem Inicia Evidex solo en este computador (nadie desde afuera puede entrar).
cd /d "%~dp0"
call preparar.bat
if errorlevel 1 exit /b 1
python -m evidex.web --dir casos
pause
