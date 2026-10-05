<#
.SYNOPSIS
Levanta el sistema completo —API, worker de ingesta y panel— con un solo comando.

.DESCRIPTION
Arranca los tres procesos que hacen falta para que el panel tenga datos y los sirva:

  * API      (uvicorn, puerto 8001)  — atiende a los usuarios
  * worker   (ingesta)               — es el único que habla con el SERCOP
  * panel    (vite, puerto 5174)     — la interfaz, que reenvía /v1 y /salud a la API

Cada proceso escribe su salida en `registros\`, y sus identificadores se guardan para poder
detenerlos todos después con `.\levantar.ps1 -Detener`.

Por qué existe este archivo: levantar el sistema son tres comandos en tres carpetas distintas, y
la forma de perder datos —que ya pasó— es olvidarse del worker. Como el worker *parece* opcional
(el panel funciona sin él), el olvido no se nota: el histórico simplemente se queda quieto y las
necesidades que se publican y se cierran ese día no se pueden recuperar después. Aquí los tres
arrancan juntos o no arranca ninguno.

.PARAMETER Detener
Detiene todo lo que levantó este script, en lugar de arrancarlo.

.PARAMETER ConLegado
Levanta además el sistema anterior (`main.py`, puerto 8000), que sigue en servicio durante la
migración. Va aparte porque no hace falta para el panel nuevo.

.PARAMETER SinMigraciones
No intenta poner al día el esquema de la base de datos (`alembic upgrade head`).

.EXAMPLE
.\levantar.ps1
Levanta todo y comprueba que responde.

.EXAMPLE
.\levantar.ps1 -Detener
Para todo.
#>

#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch] $Detener,
    [switch] $ConLegado,
    [switch] $SinMigraciones
)

$ErrorActionPreference = 'Stop'

# --- Rutas ------------------------------------------------------------------ #
# Se derivan del propio archivo y no del directorio actual: el script tiene que funcionar igual
# lanzado desde la raíz, desde el explorador de Windows o desde una tarea programada.
$Raiz = $PSScriptRoot
$Backend = Join-Path $Raiz 'backend'
$Frontend = Join-Path $Raiz 'frontend'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'
$Registros = Join-Path $Raiz 'registros'
$Ficha = Join-Path $Registros 'servicios.json'
$Entorno = Join-Path $Raiz '.env'

$PuertoApi = 8001
$PuertoPanel = 5174
$PuertoLegado = 8000
$UrlApi = "http://127.0.0.1:$PuertoApi"
$UrlPanel = "http://127.0.0.1:$PuertoPanel"

# --- Presentación ----------------------------------------------------------- #
function Titulo([string] $Texto) {
    Write-Host ''
    Write-Host "  $Texto" -ForegroundColor Cyan
    Write-Host ('  ' + ('-' * $Texto.Length)) -ForegroundColor DarkCyan
}

function Bien([string] $Texto) { Write-Host "  [ok]   $Texto" -ForegroundColor Green }
function Aviso([string] $Texto) { Write-Host "  [aviso] $Texto" -ForegroundColor Yellow }
function Mal([string] $Texto) { Write-Host "  [mal]  $Texto" -ForegroundColor Red }

function PuertoEnUso([int] $Puerto) {
    return [bool](Get-NetTCPConnection -LocalPort $Puerto -State Listen -ErrorAction SilentlyContinue)
}

# --- Detener ---------------------------------------------------------------- #
# Se mata el árbol de procesos (`/T`) y no solo el proceso padre: uvicorn con `--reload` y el panel
# se lanzan a través de un proceso intermedio, y matar solo al padre deja al hijo escuchando. El
# síntoma es un «el puerto está ocupado» que nadie entiende, porque el proceso que lo ocupa ya no
# aparece por ningún lado.
function Detener-Servicios {
    Titulo 'Deteniendo'

    # Igual que con alembic: un `taskkill` sobre un proceso que ya no está escribe por la salida de
    # error, y con el script en `Stop` eso sería un error terminante. Aquí el resultado se comprueba
    # a mano y se informa, que es más útil que abortar.
    $previo = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'

    if (-not (Test-Path $Ficha)) {
        Aviso 'No hay servicios apuntados por este script; no hay nada que detener.'
        $ErrorActionPreference = $previo
        return
    }

    $servicios = Get-Content $Ficha -Raw | ConvertFrom-Json
    foreach ($propiedad in $servicios.PSObject.Properties) {
        $identificador = [int] $propiedad.Value
        $estado = Get-Process -Id $identificador -ErrorAction SilentlyContinue
        if (-not $estado) {
            Aviso "$($propiedad.Name): ya no estaba corriendo"
            continue
        }
        & taskkill.exe /PID $identificador /T /F *> $null
        $sigue = Get-Process -Id $identificador -ErrorAction SilentlyContinue
        if ($sigue) { Mal "$($propiedad.Name): no se pudo detener" } else { Bien "$($propiedad.Name) detenido" }
    }

    Remove-Item $Ficha -Force -ErrorAction SilentlyContinue
    $ErrorActionPreference = $previo

    # Un cierre ordenado del worker puede tardar: el canal de presencia mantiene una conexión viva.
    # Si algún puerto se queda escuchando, se dice, en lugar de dejar que el siguiente arranque
    # falle con un error que parece del código.
    foreach ($puerto in @($PuertoApi, $PuertoPanel, $PuertoLegado)) {
        if (PuertoEnUso $puerto) {
            Aviso "El puerto $puerto sigue escuchando; ciérralo a mano si el siguiente arranque se queja."
        }
    }
    Write-Host ''
}

# --- Esperas ----------------------------------------------------------------- #
function Esperar-Http([string] $Url, [int] $Segundos = 90) {
    $limite = (Get-Date).AddSeconds($Segundos)
    while ((Get-Date) -lt $limite) {
        try {
            $respuesta = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($respuesta.StatusCode -eq 200) { return $true }
        } catch {
            # Un 503 significa «estoy vivo, pero una dependencia no»: es una respuesta, no un fallo
            # de arranque, y por eso se deja de esperar y se informa más abajo.
            if ($_.Exception.Response -and [int] $_.Exception.Response.StatusCode -eq 503) {
                return $false
            }
        }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Estado-Listo {
    param([string] $Url)
    try {
        $respuesta = Invoke-WebRequest -Uri "$Url/listo" -UseBasicParsing -TimeoutSec 20
        return @{ Codigo = $respuesta.StatusCode; Cuerpo = $respuesta.Content }
    } catch {
        $codigo = 0
        $cuerpo = ''
        if ($_.Exception.Response) {
            $codigo = [int] $_.Exception.Response.StatusCode
            try {
                $lector = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $cuerpo = $lector.ReadToEnd()
            } catch { $cuerpo = '' }
        }
        return @{ Codigo = $codigo; Cuerpo = $cuerpo }
    }
}

# --- Arranque ---------------------------------------------------------------- #
function Iniciar-Servicio {
    param(
        [string] $Nombre,
        [string] $Archivo,
        [string[]] $Argumentos,
        [string] $Directorio
    )

    $salida = Join-Path $Registros "$Nombre.out.log"
    $errores = Join-Path $Registros "$Nombre.err.log"

    $proceso = Start-Process -FilePath $Archivo -ArgumentList $Argumentos `
        -WorkingDirectory $Directorio -WindowStyle Hidden `
        -RedirectStandardOutput $salida -RedirectStandardError $errores -PassThru

    return $proceso.Id
}

if ($Detener) {
    Detener-Servicios
    exit 0
}

Write-Host ''
Write-Host '  Contratación pública — levantando el sistema' -ForegroundColor White

# --- Comprobaciones previas --------------------------------------------------- #
Titulo 'Comprobando el entorno'
$falta = $false

if (-not (Test-Path $Python)) {
    Mal "No está el entorno de Python del backend. Créalo con:"
    Write-Host '           cd backend; python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ".[dev]"'
    $falta = $true
} else { Bien 'Entorno de Python del backend' }

if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Mal 'Faltan las dependencias del panel. Instálalas con: cd frontend; npm install'
    $falta = $true
} else { Bien 'Dependencias del panel' }

if (-not (Test-Path $Entorno)) {
    Mal 'No hay archivo .env en la raíz (sin él no hay base de datos ni forma de arrancar).'
    $falta = $true
} else { Bien 'Archivo .env' }

if ($falta) { Write-Host ''; exit 1 }

if (-not (Test-Path $Registros)) { New-Item -ItemType Directory -Path $Registros | Out-Null }

# --- Esquema de la base ------------------------------------------------------- #
# Se pone al día antes de arrancar, y un fallo aquí **no** impide arrancar: si la base está caída, lo
# que hace falta es que los procesos levanten para poder ver el error por `/listo`, no que el script
# se rinda y deje la pantalla en blanco.
if (-not $SinMigraciones) {
    Titulo 'Poniendo al día el esquema de la base'
    # Alembic se ejecuta **desde backend/**, no desde donde se lanzó el script: busca `alembic.ini` en
    # el directorio actual y, sin él, falla con «No 'script_location' key found in configuration» —
    # un error que no dice nada de la base de datos y que parece un problema del esquema cuando solo
    # es una ruta.
    #
    # Y su salida va a un archivo en lugar de a la consola por un detalle de PowerShell que cuesta
    # entender: alembic escribe sus `INFO` por la salida de error, y con `$ErrorActionPreference`
    # en `Stop` —que es como está este script— un texto por la salida de error de un programa
    # externo se convierte en un error terminante. El resultado era que el arranque se abortaba en
    # un paso que había ido bien. El registro se queda en `registros\alembic.log` y solo se enseña
    # si de verdad falla.
    $logAlembic = Join-Path $Registros 'alembic.log'
    $previo = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $Backend
    try {
        & $Python -m alembic upgrade head *> $logAlembic
        $codigo = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previo
        Pop-Location
    }
    if ($codigo -eq 0) {
        $ultima = Get-Content $logAlembic | Where-Object { $_ } | Select-Object -Last 1
        Bien "Esquema al día ($ultima)"
    } else {
        Aviso 'No se pudo poner al día el esquema (¿la base no responde?). Se sigue arrancando.'
        Get-Content $logAlembic -Tail 3 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "           $_" -ForegroundColor DarkGray }
    }
}

# --- Los tres procesos -------------------------------------------------------- #
Titulo 'Arrancando los procesos'
$arrancados = [ordered]@{}

# 1 · API. Se arranca con recarga y con `--reload-dir src` a propósito: sin acotar el directorio,
# vigila también `pruebas/` y `scripts/`, y cada `pytest` reinicia el servidor.
if (PuertoEnUso $PuertoApi) {
    Aviso "El puerto $PuertoApi ya está escuchando: no se arranca otra API."
} else {
    $arrancados['api'] = Iniciar-Servicio -Nombre 'api' -Archivo $Python `
        -Argumentos @('-m', 'uvicorn', 'contratacion.asgi:app', '--host', '127.0.0.1',
                      '--port', "$PuertoApi", '--reload', '--reload-dir', 'src') `
        -Directorio $Backend
    Bien "API lanzada (pid $($arrancados['api']))"
}

# 2 · Worker. Es el que trae los datos; sin él el panel muestra lo último que hubiera en la base.
$arrancados['worker'] = Iniciar-Servicio -Nombre 'worker' -Archivo $Python `
    -Argumentos @('-m', 'contratacion.tareas.worker') -Directorio $Backend
Bien "Worker de ingesta lanzado (pid $($arrancados['worker']))"

# 3 · Panel. Se arranca a través de `cmd` porque npm es un `.cmd` y `Start-Process` no lo resolvería.
if (PuertoEnUso $PuertoPanel) {
    Aviso "El puerto $PuertoPanel ya está escuchando: no se arranca otro panel."
} else {
    $arrancados['panel'] = Iniciar-Servicio -Nombre 'panel' -Archivo "$env:ComSpec" `
        -Argumentos @('/c', 'npm run dev') -Directorio $Frontend
    Bien "Panel lanzado (pid $($arrancados['panel']))"
}

if ($ConLegado) {
    if (PuertoEnUso $PuertoLegado) {
        Aviso "El puerto $PuertoLegado ya está escuchando: no se arranca el sistema anterior."
    } else {
        $arrancados['legado'] = Iniciar-Servicio -Nombre 'legado' -Archivo $Python `
            -Argumentos @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', "$PuertoLegado") `
            -Directorio $Raiz
        Bien "Sistema anterior lanzado (pid $($arrancados['legado']))"
    }
}

$arrancados | ConvertTo-Json | Set-Content -Path $Ficha -Encoding UTF8

# --- Comprobación ------------------------------------------------------------- #
Titulo 'Comprobando que responde'

if (Esperar-Http "$UrlApi/salud" 90) {
    Bien "API viva en $UrlApi"
} else {
    Mal "La API no responde en $UrlApi. Mira registros\api.err.log"
}

if (Esperar-Http $UrlPanel 120) {
    Bien "Panel disponible en $UrlPanel"
} else {
    Mal "El panel no responde en $UrlPanel. Mira registros\panel.err.log"
}

$listo = Estado-Listo -Url $UrlApi
if ($listo.Codigo -eq 200) {
    Bien 'Dependencias en pie: base de datos y caché responden.'
} elseif ($listo.Codigo -eq 503) {
    Mal 'La API está viva, pero una dependencia no responde (503). El panel abrirá sin datos.'
    if ($listo.Cuerpo) { Write-Host "           $($listo.Cuerpo)" -ForegroundColor DarkGray }
} elseif ($listo.Codigo -eq 0) {
    Aviso 'No se pudo preguntar por el estado de las dependencias.'
} else {
    Aviso "El estado de las dependencias respondió $($listo.Codigo)."
}

# El worker tarda unos segundos en cerrar el primer ciclo: aquí solo se enseña lo que ya haya dicho.
$logWorker = Join-Path $Registros 'worker.err.log'
if (Test-Path $logWorker) {
    $lineas = Get-Content $logWorker -Tail 6 -ErrorAction SilentlyContinue
    if ($lineas) {
        Write-Host ''
        Write-Host '  Primeras señales del worker:' -ForegroundColor DarkGray
        $lineas | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
}

# --- Resumen ------------------------------------------------------------------ #
Titulo 'Listo'
Write-Host "  Panel      $UrlPanel" -ForegroundColor White
Write-Host "  API        $UrlApi   (/salud y /listo para comprobar)" -ForegroundColor White
Write-Host "  Registros  $Registros" -ForegroundColor White
Write-Host ''
Write-Host '  El worker consulta el listado de necesidades cada 2 minutos y medio, y el ciclo' -ForegroundColor DarkGray
Write-Host '  completo (búsquedas por palabra clave y fichas) cada 15. Para seguirlo:' -ForegroundColor DarkGray
Write-Host '    Get-Content registros\worker.err.log -Tail 20 -Wait' -ForegroundColor DarkGray
Write-Host ''
Write-Host '  Para detenerlo todo:' -ForegroundColor DarkGray
Write-Host '    .\levantar.ps1 -Detener' -ForegroundColor DarkGray
Write-Host ''
