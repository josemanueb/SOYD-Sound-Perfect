@echo off
rem ---------------------------------------------------------------------------
rem  SOYD Sound Perfect - lanzador
rem
rem  Usa el Python que viaja dentro de esta misma carpeta (runtime\), asi que
rem  funciona en cualquier PC, desde cualquier ruta y sin instalar nada.
rem  No borres la carpeta "runtime": es el motor de la aplicacion.
rem ---------------------------------------------------------------------------
setlocal
set "AQUI=%~dp0"

rem 1) El Python portatil que va con la aplicacion (lo normal)
if exist "%AQUI%runtime\pythonw.exe" (
    start "" "%AQUI%runtime\pythonw.exe" "%AQUI%app.py"
    exit /b 0
)

rem 2) Si falta runtime\, se intenta el Python del sistema
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%AQUI%app.py"
    exit /b 0
)
where python >nul 2>&1
if %errorlevel%==0 (
    start "" python "%AQUI%app.py"
    exit /b 0
)

echo.
echo   No se ha encontrado el motor de la aplicacion.
echo.
echo   Lo normal es que exista una carpeta "runtime" junto a este archivo.
echo   Si no esta, vuelve a copiar la aplicacion completa.
echo.
pause
