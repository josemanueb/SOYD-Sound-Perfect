@echo off
rem ---------------------------------------------------------------------------
rem  SOYD Sound Perfect - reparar / ampliar el motor
rem
rem  La aplicacion ya trae todo lo necesario en runtime\, asi que este archivo
rem  solo hace falta si:
rem    - borraste o moviste la carpeta runtime\ y tienes Python en el sistema
rem    - quieres volver a generar el icono (necesita Pillow)
rem ---------------------------------------------------------------------------
setlocal
set "AQUI=%~dp0"
set "PY="

if exist "%AQUI%runtime\python.exe" set "PY=%AQUI%runtime\python.exe"
if not defined PY (
    where python >nul 2>&1
    if %errorlevel%==0 set "PY=python"
)
if not defined PY (
    echo.
    echo   No hay motor portatil ni Python en el sistema.
    echo   Copia de nuevo la aplicacion completa.
    echo.
    pause
    exit /b 1
)

echo Instalando dependencias con: %PY%
"%PY%" -m pip install --upgrade -r "%AQUI%requirements.txt"
echo.
echo Hecho. Ya puedes abrir la aplicacion con INICIAR.bat
pause
