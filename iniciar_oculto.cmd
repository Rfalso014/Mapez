@echo off
rem ===========================================================================
rem  Bot Web - arranque SIN ventana negra (v4.0)
rem  --------------------------------------------------------------------------
rem  No lo abras con doble clic: usa "Bot Web.vbs", que llama a este archivo en
rem  una ventana escondida.  Aqui se comprueban las dependencias y se arranca el
rem  programa con pythonw.exe (sin consola).
rem
rem  Lo que cuenta este archivo va a  registros\arranque.log  y lo que cuenta el
rem  programa a  registros\consola.log.  Para verlo en pantalla: "iniciar.bat".
rem ===========================================================================
chcp 65001 >nul
cd /d "%~dp0"
if not exist "registros" mkdir "registros" >nul 2>&1
set "LOG=%~dp0registros\arranque.log"

rem --- python de la carpeta .venv (lo que crea el instalador) o el del sistema
set "PY="
set "PYW="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PY for /f "delims=" %%i in ('where python.exe 2^>nul') do if not defined PY set "PY=%%i"
if not defined PYW for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW set "PYW=%PY%"

if not defined PY (
    >>"%LOG%" echo [%DATE% %TIME%] No se encontro Python. Instala Python 3.10 o superior desde https://www.python.org/downloads/ y marca "Add python.exe to PATH".
    exit /b 2
)

>>"%LOG%" echo [%DATE% %TIME%] Abriendo Bot Web sin ventana (%PYW%)
"%PY%" -m pip install -r requirements.txt --quiet --disable-pip-version-check >>"%LOG%" 2>&1
if errorlevel 1 >>"%LOG%" echo [%DATE% %TIME%] Aviso: no se pudieron comprobar las dependencias (se intenta abrir igual).

rem Los mensajes del programa van al archivo: aqui la consola esta escondida y se perderian.
rem (Cuando se abre con el acceso directo del instalador no hay consola ninguna y de eso se encarga webbot\consola.py.)
set "CONSOLA=%~dp0registros\consola.log"
for %%A in ("%CONSOLA%") do if exist "%CONSOLA%" if %%~zA GTR 2000000 move /y "%CONSOLA%" "%CONSOLA%.1" >nul 2>&1

rem El bot usa el Chrome o Edge que ya tienes instalado: no se descarga ningun navegador.
"%PYW%" "%~dp0bot.py" %* >>"%CONSOLA%" 2>&1
set "CODIGO=%ERRORLEVEL%"
if not "%CODIGO%"=="0" >>"%LOG%" echo [%DATE% %TIME%] Bot Web se cerro con el codigo %CODIGO% (mira registros\consola.log).
exit /b %CODIGO%
