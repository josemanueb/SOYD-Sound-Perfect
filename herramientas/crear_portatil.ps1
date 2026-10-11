# ---------------------------------------------------------------------------
#  SOYD Sound Perfect - construye la version portatil
#
#  Copia un Python completo junto al codigo, le quita lo que la app no usa y
#  deja la carpeta lista (y opcionalmente un ZIP) para publicar en Releases.
#
#  Uso:
#     powershell -ExecutionPolicy Bypass -File herramientas\crear_portatil.ps1
#     powershell -ExecutionPolicy Bypass -File herramientas\crear_portatil.ps1 -Zip
#
#  Requisitos: un Python 3.12 con numpy, scipy, soundfile, lameenc, mutagen y
#  Pillow instalados. Es el que se copia dentro.
# ---------------------------------------------------------------------------

[CmdletBinding()]
param(
    [string] $Origen,                       # instalacion de Python a copiar
    [string] $Destino,                      # donde crear la carpeta runtime
    [switch] $Zip,                          # crear tambien el ZIP
    [switch] $Precompilar,                  # ver la nota de abajo
    [switch] $Forzar                        # sobrescribir un runtime existente
)

# NOTA SOBRE -Precompilar:
# Compilar el bytecode (.pyc) anade unos 58 MB a la carpeta (268 MB frente a
# 210 MB) y en las pruebas NO mejoro el tiempo de arranque: el coste lo domina
# la carga de las DLL de scipy, no la compilacion de los .py. Por eso esta
# desactivado por defecto. Activalo solo si prefieres no compilar nada en el
# primer arranque y no te importa el tamano.

$ErrorActionPreference = "Stop"

# --- 1. Localizar la aplicacion y el Python de origen ----------------------
$raiz = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $raiz "app.py"))) {
    throw "No encuentro app.py en $raiz. Ejecuta el script desde la carpeta del proyecto."
}
if (-not $Destino) { $Destino = Join-Path $raiz "runtime" }

if (-not $Origen) {
    $candidatos = @()
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { $candidatos += (Split-Path -Parent $py.Source) }
    if ($env:PYTHONHOME) { $candidatos += $env:PYTHONHOME }
    foreach ($c in $candidatos) {
        if (Test-Path (Join-Path $c "python.exe")) { $Origen = $c; break }
    }
}
if (-not $Origen -or -not (Test-Path (Join-Path $Origen "python.exe"))) {
    throw "No encuentro un Python de origen. Indica la carpeta con -Origen 'C:\ruta\a\python'"
}

$pyOrigen = Join-Path $Origen "python.exe"
Write-Host "Origen  : $Origen"
Write-Host "Destino : $Destino"

# --- 2. Comprobar que el Python de origen tiene lo necesario ---------------
$necesarios = @("numpy", "scipy", "soundfile", "lameenc", "mutagen", "PIL", "tkinter")
$falta = @()
foreach ($m in $necesarios) {
    & $pyOrigen -c "import $m" 2>$null
    if ($LASTEXITCODE -ne 0) { $falta += $m }
}
if ($falta.Count -gt 0) {
    throw ("Al Python de origen le faltan modulos: " + ($falta -join ", ") +
           "`nInstalalos con: `"$pyOrigen`" -m pip install -r requirements.txt")
}
Write-Host "Modulos comprobados: $($necesarios -join ', ')" -ForegroundColor Green

# --- 3. Copiar el runtime quitando lo que no se usa ------------------------
if (Test-Path $Destino) {
    if (-not $Forzar) { throw "Ya existe $Destino . Usa -Forzar para reemplazarlo." }
    Remove-Item $Destino -Recurse -Force
}

# Paquetes de otras herramientas que la app no necesita (ahorra ~90 MB)
$excluir = @(
    "pandas", "pandas.libs", "pandas-3.0.1.dist-info",
    "lxml", "docx", "pptx", "openpyxl", "xlsxwriter", "et_xmlfile",
    "dateutil", "tzdata", "six.py", "python_docx-1.2.0.dist-info",
    "python_pptx-1.0.2.dist-info", "openpyxl-3.1.5.dist-info",
    "xlsxwriter-3.2.9.dist-info", "xlsxwriter-3.2.9.data",
    "lxml-6.1.3.dist-info", "et_xmlfile-2.0.0.dist-info",
    "python_dateutil-2.9.0.post0.dist-info", "tzdata-2025.2.dist-info",
    "six-1.17.0.dist-info"
) | ForEach-Object { Join-Path $Origen "Lib\site-packages\$_" }

Write-Host "Copiando el motor..." -ForegroundColor Cyan
$roboArgs = @($Origen, $Destino, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
foreach ($e in $excluir) { $roboArgs += "/XD"; $roboArgs += $e }
& robocopy @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy fallo con codigo $LASTEXITCODE" }

# Archivos que solo sirven para desarrollar (no hacen falta en ejecucion)
foreach ($patron in @("*.pyi", "*.h", "*.c", "*.pxd", "*.pyx", "*.cxx", "*.cpp")) {
    Get-ChildItem $Destino -Recurse -File -Filter $patron -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}
Get-ChildItem $Destino -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

# A partir de aqui trabajamos con el Python ya copiado
$pyDestino = Join-Path $Destino "python.exe"
if (-not (Test-Path $pyDestino)) {
    throw "La copia no ha producido un python.exe en $Destino. Copia interrumpida?"
}

# --- 4. Precompilar el bytecode (opcional, ver la nota de arriba) ----------
if ($Precompilar) {
    Write-Host "Precompilando el bytecode (anade ~58 MB)..." -ForegroundColor Cyan
    & $pyDestino -m compileall -q -j 0 (Join-Path $Destino "Lib") 2>&1 | Out-Null
} else {
    Get-ChildItem $Destino -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force
}

# --- 5. Comprobar que el motor funciona ------------------------------------
Write-Host "Comprobando el motor portatil..." -ForegroundColor Cyan
& $pyDestino -c "import sys, numpy, scipy.signal, scipy.ndimage, soundfile, lameenc, mutagen, tkinter; print('  OK', sys.version.split()[0], '| prefix:', sys.prefix)" 2>&1 |
    ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { throw "El motor copiado no arranca." }

# --- 6. Resumen (y ZIP opcional) -------------------------------------------
$archivosApp = Get-ChildItem $raiz -Recurse -File -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -notmatch "\\runtime\\" -and
                              $_.FullName -notmatch "\\__pycache__\\" }
$archivosMotor = Get-ChildItem $Destino -Recurse -File -ErrorAction SilentlyContinue
$mbApp = ($archivosApp | Measure-Object Length -Sum).Sum / 1MB
$mbMotor = ($archivosMotor | Measure-Object Length -Sum).Sum / 1MB
Write-Host ""
Write-Host ("Codigo de la app : {0,6:N2} MB  ({1} archivos)" -f $mbApp, $archivosApp.Count)
Write-Host ("Motor portatil   : {0,6:N1} MB  ({1} archivos)" -f $mbMotor, $archivosMotor.Count)
Write-Host ("TOTAL            : {0,6:N1} MB" -f ($mbApp + $mbMotor)) -ForegroundColor Green

if ($Zip) {
    $zip = Join-Path (Split-Path -Parent $raiz) "SOYD-Sound-Perfect-portatil.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Write-Host "Creando el ZIP (puede tardar un minuto)..." -ForegroundColor Cyan
    Compress-Archive -Path $raiz -DestinationPath $zip -CompressionLevel Optimal
    Write-Host ("  ZIP: {0} ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB)) -ForegroundColor Green
    Write-Host "  Sube ese ZIP a la seccion Releases de GitHub."
} else {
    Write-Host "Para empaquetarlo: vuelve a ejecutar con -Zip"
}
