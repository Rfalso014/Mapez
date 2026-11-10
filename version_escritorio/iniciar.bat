@echo off
chcp 65001 >nul
title Bot Copión
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo No se encontro Python. Instala Python 3.10 o superior desde https://www.python.org/downloads/
    echo y marca la casilla "Add python.exe to PATH" durante la instalacion.
    pause
    exit /b 1
)

echo Comprobando dependencias...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo No se pudieron instalar las dependencias. Revisa tu conexion a Internet.
    pause
    exit /b 1
)

python bot.py
if errorlevel 1 (
    echo.
    echo El bot se cerro con un error. Revisa el mensaje de arriba.
    pause
)
