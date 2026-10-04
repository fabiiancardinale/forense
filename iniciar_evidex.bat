@echo off
cd /d "%~dp0"
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1
if not exist "casos\usuarios.json" python -m evidex.accounts.setup --dir casos
if errorlevel 1 exit /b 1
python -m evidex.web --dir casos
pause
