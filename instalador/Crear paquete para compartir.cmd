@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python instalador\crear_paquete.py
echo.
pause
