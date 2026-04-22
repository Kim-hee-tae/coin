@echo off
setlocal

if "%CLIENT_NAME%"=="" set CLIENT_NAME=AirBattleClient

python -m pip install --upgrade pyinstaller
if errorlevel 1 exit /b 1

python -m PyInstaller --onefile --name %CLIENT_NAME% client.py
if errorlevel 1 exit /b 1

echo [DONE] Executable generated at: dist\%CLIENT_NAME%.exe
