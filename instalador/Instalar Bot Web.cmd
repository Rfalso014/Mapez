<# : Bot Web - instalador. Haz doble clic en este archivo.
@echo off
setlocal
chcp 65001 >nul
title Instalar Bot Web
set "BOTWEB_SCRIPT=%~f0"
set "BOTWEB_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "BOTWEB_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%BOTWEB_PS%" -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create([IO.File]::ReadAllText($env:BOTWEB_SCRIPT, [Text.Encoding]::UTF8)))"
set "BOTWEB_CODIGO=%errorlevel%"
endlocal & exit /b %BOTWEB_CODIGO%
#>

# ============================================================================================================
#  Instalador de Bot Web (un solo archivo: arriba, unas lineas para Windows; aqui, el instalador en PowerShell).
#  No necesita permisos de administrador: todo se instala para tu usuario.
#
#  Variables de prueba (ocultas; el usuario no las necesita):
#    BOTWEB_DESTINO=C:\carpeta     instalar en otra carpeta (en vez de %USERPROFILE%\BotWeb)
#    BOTWEB_SIN_ACCESOS=1          no crear accesos directos
#    BOTWEB_NO_PREGUNTAR=1         no preguntar nada ni esperar a que se pulse Intro
#    BOTWEB_FUENTE=local|github    de donde sacar el codigo (por defecto: la carpeta de al lado si la hay)
#    BOTWEB_URL_CODIGO=http://...  otro .zip del codigo (en vez del de GitHub)
#    BOTWEB_SOLO_FUNCIONES=1       solo define las funciones (para probarlas) y no instala nada
#
#  Modo actualización (lo usa el botón «Actualizar» del bot; v3.9):
#    BOTWEB_ACTUALIZAR=1           no pregunta nada, espera a que Bot Web se cierre y al terminar lo vuelve a abrir
#    BOTWEB_ESPERAR_PID=N          el proceso del bot que pidió la actualización (se espera a que termine)
# ============================================================================================================

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

$VersionPython = '3.13.16'
$UrlPython = "https://www.python.org/ftp/python/$VersionPython/python-$VersionPython-amd64.exe"
$UrlCodigo = 'https://github.com/Rfalso014/Mapez/archive/refs/heads/New-tool.zip'
if ($env:BOTWEB_URL_CODIGO) { $UrlCodigo = $env:BOTWEB_URL_CODIGO }

# Carpeta: %USERPROFILE%\BotWeb (y no %LOCALAPPDATA%): si el Python del equipo es el de la Microsoft Store, todo lo que
# ese Python escribe dentro de AppData se desvia a una carpeta oculta del paquete, y los reportes descargados no se
# verian en el Explorador.  En la carpeta del usuario no pasa, y es facil de encontrar.
if ($env:BOTWEB_DESTINO) { $Base = [IO.Path]::GetFullPath($env:BOTWEB_DESTINO) } else { $Base = Join-Path $env:USERPROFILE 'BotWeb' }
$App = Join-Path $Base 'app'
$Log = Join-Path $Base 'instalacion.log'
$VenvPy = Join-Path $App '.venv\Scripts\python.exe'
$VenvPyw = Join-Path $App '.venv\Scripts\pythonw.exe'
$Marca = '.instalado-por-botweb'
$Actualizando = ($env:BOTWEB_ACTUALIZAR -eq '1')
$NoPreguntar = ($env:BOTWEB_NO_PREGUNTAR -eq '1') -or $Actualizando
$SinAccesos = ($env:BOTWEB_SIN_ACCESOS -eq '1')
$Fuente = "$env:BOTWEB_FUENTE".Trim().ToLower()
$Script = $env:BOTWEB_SCRIPT
$Pasos = 7
$script:MensajeAmigable = $null

# Lo que NUNCA se copia (datos de quien comparte el bot) y lo que se conserva al actualizar.
$CarpetasNoCopiar = @('.git', '.github', '.claude', '.vscode', '.idea', '.venv', 'venv', '__pycache__', 'tests', 'node_modules')
$CarpetasDatos = @('datos', 'perfiles', 'registros', 'descargas')
$Conservar = @('datos', 'perfiles', 'registros', 'descargas', 'flujos', '.venv')

# ------------------------------------------------------------------------------------------------ mensajes
function Escribir-Log([string]$texto) {
    try {
        if (-not (Test-Path -LiteralPath $Base)) { New-Item -ItemType Directory -Force -Path $Base | Out-Null }
        Add-Content -LiteralPath $Log -Value ('[{0:yyyy-MM-dd HH:mm:ss}] {1}' -f (Get-Date), $texto) -Encoding UTF8
    } catch { }
}
function Paso([int]$n, [string]$texto) {
    Write-Host ''
    Write-Host ("[{0}/{1}] {2}" -f $n, $Pasos, $texto) -ForegroundColor Cyan
    Escribir-Log ("[{0}/{1}] {2}" -f $n, $Pasos, $texto)
}
function Info([string]$texto) { Write-Host "      $texto"; Escribir-Log "      $texto" }
function Aviso([string]$texto) { Write-Host "      $texto" -ForegroundColor Yellow; Escribir-Log "      AVISO: $texto" }
function Fallar([string]$texto) { $script:MensajeAmigable = $texto; throw $texto }
function Pausa {
    if (-not $NoPreguntar) { Write-Host ''; [void](Read-Host 'Pulsa Intro para cerrar esta ventana') }
}
function Preguntar([string]$texto, [bool]$defecto) {
    if ($NoPreguntar) { return $defecto }
    while ($true) {
        $r = ("" + (Read-Host "$texto (S/N)")).Trim().ToLower()
        if ($r -eq '') { return $defecto }
        if ($r -in @('s', 'si', 'sí', 'y', 'yes')) { return $true }
        if ($r -in @('n', 'no')) { return $false }
        Write-Host '      Escribe S (si) o N (no).'
    }
}

# ------------------------------------------------------------------------------------------------ utilidades
function Citar([string]$a) {
    # Un argumento para la linea de comandos de Windows (con comillas si hace falta).
    if ($a -ne '' -and $a -notmatch '[\s"]') { return $a }
    $r = '"'; $barras = 0
    foreach ($c in $a.ToCharArray()) {
        if ($c -eq '\') { $barras++ }
        elseif ($c -eq '"') { $r += ('\' * ($barras * 2 + 1)) + '"'; $barras = 0 }
        else { $r += ('\' * $barras) + $c; $barras = 0 }
    }
    return $r + ('\' * ($barras * 2)) + '"'
}

function Ejecutar([string]$exe, [string[]]$argumentos, [int]$segundos = 0, [string]$carpeta = '') {
    # Ejecuta un programa sin ventana, guarda lo que escribe en el registro y devuelve @{Codigo; Salida}.
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = (@($argumentos) | ForEach-Object { Citar $_ }) -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
    if ($carpeta) { $psi.WorkingDirectory = $carpeta }
    Escribir-Log ("      > {0} {1}" -f $exe, $psi.Arguments)
    $p = [Diagnostics.Process]::Start($psi)
    $salida = $p.StandardOutput.ReadToEndAsync()
    $errores = $p.StandardError.ReadToEndAsync()
    if ($segundos -gt 0) {
        if (-not $p.WaitForExit($segundos * 1000)) {
            try { $p.Kill() } catch { }
            Escribir-Log '      (tiempo agotado)'
            return @{ Codigo = -1; Salida = '(tiempo agotado)' }
        }
    }
    $p.WaitForExit()
    $texto = ($salida.Result + $errores.Result).Trim()
    if ($texto) { Escribir-Log ($texto -replace '(?m)^', '        ') }
    Escribir-Log ("      (codigo de salida {0})" -f $p.ExitCode)
    return @{ Codigo = $p.ExitCode; Salida = $texto }
}

function Nueva-Conexion([string]$url, [string]$metodo) {
    $req = [Net.WebRequest]::Create($url)
    $req.Method = $metodo
    $req.Timeout = 20000
    try { $req.UserAgent = 'BotWeb-Instalador' } catch { }
    try { $req.Proxy = [Net.WebRequest]::GetSystemWebProxy(); $req.Proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials } catch { }
    return $req
}

function Hay-Conexion([string]$url) {
    # True si el sitio contesta (cualquier respuesta HTTP vale: lo importante es llegar).
    try {
        $resp = (Nueva-Conexion $url 'HEAD').GetResponse()
        $resp.Close()
        return $true
    } catch {
        $e = $_.Exception
        while ($e) { if ($e -is [Net.WebException] -and $e.Response) { return $true }; $e = $e.InnerException }
        Escribir-Log ("      Sin respuesta de {0}: {1}" -f $url, $_.Exception.Message)
        return $false
    }
}

function Descargar([string]$url, [string]$destino) {
    for ($i = 1; $i -le 3; $i++) {
        try {
            Escribir-Log "      Descargando $url"
            $wc = New-Object Net.WebClient
            $wc.Headers['User-Agent'] = 'BotWeb-Instalador'
            try { $wc.Proxy = [Net.WebRequest]::GetSystemWebProxy(); $wc.Proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials } catch { }
            $wc.DownloadFile($url, $destino)
            return
        } catch {
            Escribir-Log ("      Intento {0} fallido: {1}" -f $i, $_.Exception.Message)
            if ($i -eq 3 -or "$($_.Exception.Message)" -match '\(404\)') { throw }
            Start-Sleep -Seconds (5 * $i)
        }
    }
}

# ------------------------------------------------------------------------------------------------ Python
$CodigoVersion = "import sys,struct,importlib.util as u;print('BOTWEB|%d.%d.%d|%d|%d|%s' % (sys.version_info[0],sys.version_info[1],sys.version_info[2],struct.calcsize('P')*8,u.find_spec('_tkinter') is not None,sys.executable))"

function Es-AliasTienda([string]$exe) {
    # El python.exe de %LOCALAPPDATA%\Microsoft\WindowsApps es un acceso de la Microsoft Store.  Si no hay ningun
    # Python de la Tienda instalado, es solo el «anzuelo» que abre la Tienda: no sirve.
    try { $ruta = [IO.Path]::GetFullPath($exe) } catch { return $false }
    try { $tienda = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps')) } catch { return $false }
    if ((Split-Path -Parent $ruta).TrimEnd('\') -ne $tienda.TrimEnd('\')) { return $false }
    $paquetes = @(Get-ChildItem -LiteralPath $tienda -Directory -Filter 'PythonSoftwareFoundation.Python.3*' -ErrorAction SilentlyContinue)
    return ($paquetes.Count -eq 0)
}

function Probar-Python([string]$exe, [string[]]$prefijo) {
    # Devuelve los datos de ese Python (version, 64 bits, tkinter, ruta) o $null si no sirve o no arranca.
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { return $null }
    if (Es-AliasTienda $exe) { Escribir-Log "      Se ignora $exe (solo abre la Microsoft Store)"; return $null }
    $argumentos = @()
    if ($prefijo) { $argumentos += $prefijo }
    $argumentos += @('-c', $CodigoVersion)
    try { $r = Ejecutar $exe $argumentos 60 } catch { Escribir-Log "      No arranca $exe : $($_.Exception.Message)"; return $null }
    if ($r.Codigo -ne 0) { return $null }
    $m = [regex]::Match($r.Salida, 'BOTWEB\|(\d+)\.(\d+)\.(\d+)\|(\d+)\|(\d)\|(.+)')
    if (-not $m.Success) { return $null }
    $ruta = $m.Groups[6].Value.Trim()
    return [pscustomobject]@{
        Exe = $exe; Prefijo = $prefijo
        Version = [version]('{0}.{1}.{2}' -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value)
        Bits = [int]$m.Groups[4].Value; Tkinter = ($m.Groups[5].Value -eq '1')
        Ruta = $ruta; Tienda = ($ruta -like '*\WindowsApps\*')
    }
}

function Candidatos-Python {
    # En orden: «py -3», cada python.exe del PATH y las carpetas donde lo deja el instalador de python.org.
    $py = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($py) { [pscustomobject]@{ Exe = $py.Source; Prefijo = @('-3') } }
    foreach ($c in @(Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
        [pscustomobject]@{ Exe = $c.Source; Prefijo = @() }
    }
    $sitios = @()
    if ($env:LOCALAPPDATA) { $sitios += Join-Path $env:LOCALAPPDATA 'Programs\Python' }
    if ($env:ProgramFiles) { $sitios += $env:ProgramFiles }
    foreach ($s in $sitios) {
        foreach ($d in @(Get-ChildItem -LiteralPath $s -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
            [pscustomobject]@{ Exe = (Join-Path $d.FullName 'python.exe'); Prefijo = @() }
        }
    }
}

function Buscar-Python {
    # El primer Python 3.10 o superior, de 64 bits y con tkinter.  Mejor uno normal (python.org) que el de la Tienda.
    $vistos = @{}
    $buenos = @()
    foreach ($c in @(Candidatos-Python)) {
        $p = Probar-Python $c.Exe $c.Prefijo
        if (-not $p) { continue }
        if ($vistos.ContainsKey($p.Ruta.ToLower())) { continue }
        $vistos[$p.Ruta.ToLower()] = $true
        Escribir-Log ("      Python {0} ({1} bits, tkinter={2}) en {3}" -f $p.Version, $p.Bits, $p.Tkinter, $p.Ruta)
        if ($p.Version -lt [version]'3.10' -or $p.Bits -ne 64 -or -not $p.Tkinter) { continue }
        $buenos += $p
    }
    $elegido = $buenos | Where-Object { -not $_.Tienda } | Select-Object -First 1
    if (-not $elegido) { $elegido = $buenos | Select-Object -First 1 }
    return $elegido
}

function Instalar-Python {
    if (-not (Hay-Conexion 'https://www.python.org/')) {
        Fallar 'No hay Python en este equipo y no se puede llegar a python.org para descargarlo. Revisa la conexion a Internet.'
    }
    $exe = Join-Path $env:TEMP ("python-{0}-amd64.exe" -f $VersionPython)
    Info "Descargando Python $VersionPython de python.org (unos 30 MB)..."
    try { Descargar $UrlPython $exe } catch { Fallar 'No se pudo descargar Python de python.org. Revisa la conexion a Internet.' }
    $firma = Get-AuthenticodeSignature -LiteralPath $exe
    Escribir-Log ("      Firma del instalador: {0} / {1}" -f $firma.Status, $firma.SignerCertificate.Subject)
    if ($firma.Status -ne 'Valid' -or $firma.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        Remove-Item -LiteralPath $exe -Force -ErrorAction SilentlyContinue
        Fallar 'El instalador de Python descargado no tiene la firma de python.org. No se instala.'
    }
    Info 'Instalando Python (solo para tu usuario; tarda unos minutos)...'
    $p = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @('/quiet', 'InstallAllUsers=0', 'PrependPath=1',
        'Include_tcltk=1', 'Include_launcher=1', 'InstallLauncherAllUsers=0', 'Include_test=0', 'Include_pip=1')
    Escribir-Log ("      El instalador de Python termino con el codigo {0}" -f $p.ExitCode)
    Remove-Item -LiteralPath $exe -Force -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        Fallar ("La instalacion de Python fallo (codigo {0})." -f $p.ExitCode)
    }
}

# ------------------------------------------------------------------------------------------------ codigo del bot
function Buscar-FuenteLocal {
    # Una copia del bot junto a este archivo (bot.py y la carpeta webbot aqui, en la carpeta "programa" del paquete para
    # compartir o una carpeta mas arriba).
    if (-not $Script) { return $null }
    $dir = Split-Path -Parent $Script
    foreach ($d in @($dir, (Join-Path $dir 'programa'), (Split-Path -Parent $dir))) {
        if ($d -and (Test-Path -LiteralPath (Join-Path $d 'bot.py')) -and (Test-Path -LiteralPath (Join-Path $d 'webbot') -PathType Container)) {
            return (Resolve-Path -LiteralPath $d).ProviderPath.TrimEnd('\')
        }
    }
    return $null
}

function Carpeta-Excluida([string]$relativa, [string]$nombre) {
    if ($CarpetasNoCopiar -contains $nombre) { return $true }
    if ($relativa -notmatch '\\' -and $CarpetasDatos -contains $nombre) { return $true }
    return $false
}

function Archivo-Excluido([string]$relativa, [string]$nombre) {
    if ($nombre -like '*.pyc' -or $nombre -like '*.pyo' -or $nombre -eq $Marca) { return $true }
    if ($relativa -like 'flujos\*.json') { return $true }                        # flujos guardados de quien comparte
    if ($relativa -like 'version_escritorio\grabaciones\*.json') { return $true }
    return $false
}

function Copiar-Carpeta([string]$origen, [string]$destino, [string]$relativa) {
    New-Item -ItemType Directory -Force -Path $destino | Out-Null
    foreach ($item in @(Get-ChildItem -LiteralPath $origen -Force)) {
        if ($relativa) { $r = "$relativa\$($item.Name)" } else { $r = $item.Name }
        if ($item.PSIsContainer) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
            if (Carpeta-Excluida $r $item.Name) { continue }
            Copiar-Carpeta $item.FullName (Join-Path $destino $item.Name) $r
        } else {
            if (Archivo-Excluido $r $item.Name) { continue }
            Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $destino $item.Name) -Force
            $script:Copiados++
        }
    }
}

function Procesos-DelBot {
    # Procesos que usan el Python o el bot.py de la carpeta instalada (el bot abierto o una tarea en marcha).
    $app = $App.ToLower()
    try {
        return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            ("" + $_.ExecutablePath).ToLower().StartsWith($app + '\') -or ("" + $_.CommandLine).ToLower().Contains($app + '\bot.py')
        })
    } catch { return @() }
}

function Esperar-BotCerrado([int]$segundosPid = 120, [int]$segundosTareas = 300) {
    # Modo actualización: espera a que se cierre el bot que pidió actualizar y, si hay una tarea programada del bot en
    # marcha, a que termine (como mucho unos minutos); lo que quede abierto despues lo cierra Cerrar-BotAbierto.
    $id = 0
    if ([int]::TryParse("$env:BOTWEB_ESPERAR_PID", [ref]$id) -and $id -gt 0 -and (Get-Process -Id $id -ErrorAction SilentlyContinue)) {
        Info 'Esperando a que Bot Web se cierre...'
        try { Wait-Process -Id $id -Timeout $segundosPid -ErrorAction Stop } catch { Escribir-Log "      El proceso $id sigue abierto." }
    }
    $limite = (Get-Date).AddSeconds($segundosTareas)
    $dicho = $false
    while ((Procesos-DelBot).Count -gt 0 -and (Get-Date) -lt $limite) {
        if (-not $dicho) { Info 'Bot Web está terminando una tarea: se espera a que acabe...'; $dicho = $true }
        Start-Sleep -Seconds 3
    }
}

function Url-Api([string]$urlZip) {
    # La direccion de la API de GitHub con el ultimo cambio de esa rama (o $null si el .zip no es de GitHub).
    $m = [regex]::Match($urlZip, '^https://github\.com/([^/]+)/([^/]+)/archive/refs/heads/(.+)\.zip$')
    if (-not $m.Success) { return $null }
    return 'https://api.github.com/repos/{0}/{1}/commits/{2}' -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value
}

function Leer-Commit([string]$url) {
    # @{sha; fecha; mensaje} del ultimo cambio (para saber luego si hay una version nueva) o $null.  Nunca falla.
    if (-not $url) { return $null }
    try {
        $req = Nueva-Conexion $url 'GET'
        $resp = $req.GetResponse()
        try { $lector = New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8); $json = $lector.ReadToEnd() } finally { $resp.Close() }
        $d = $json | ConvertFrom-Json
        $sha = ("" + $d.sha).Trim().ToLower()
        if ($sha -notmatch '^[0-9a-f]{40}$') { return $null }
        $fecha = "" + $d.commit.committer.date
        if ($d.commit.committer.date -is [datetime]) { $fecha = $d.commit.committer.date.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
        $mensaje = (("" + $d.commit.message) -split "`r?`n")[0]
        return @{ sha = $sha; fecha = $fecha; mensaje = $mensaje }
    } catch {
        Escribir-Log ("      No se pudo leer la version de GitHub: {0}" -f $_.Exception.Message)
        return $null
    }
}

function Escribir-Version([string]$carpeta, $commit) {
    # actualizacion.json: la version instalada (la usa el aviso «Hay una nueva actualización» del bot).
    $datos = [ordered]@{ sha = $commit.sha; fecha = $commit.fecha; mensaje = $commit.mensaje; rama = 'New-tool'; origen = 'instalador' }
    [IO.File]::WriteAllText((Join-Path $carpeta 'actualizacion.json'), ($datos | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
}

function Abrir-Bot {
    Start-Process -FilePath $VenvPyw -ArgumentList (Citar (Join-Path $App 'bot.py')) -WorkingDirectory $App
}

function Cerrar-BotAbierto {
    $procesos = Procesos-DelBot
    if ($procesos.Count -eq 0) { return }
    Aviso 'Bot Web esta abierto (o haciendo una tarea programada).'
    if (-not (Preguntar '      ¿Cerrarlo para poder seguir?' $true)) { Fallar 'Cierra Bot Web y vuelve a abrir este instalador.' }
    foreach ($p in $procesos) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { } }
    Start-Sleep -Seconds 2
}

function Poner-Codigo([string]$nuevo) {
    # Cambia el codigo de la carpeta instalada por el nuevo, conservando los datos del usuario y el entorno.
    New-Item -ItemType Directory -Force -Path $App | Out-Null
    foreach ($item in @(Get-ChildItem -LiteralPath $App -Force)) {
        if ($Conservar -contains $item.Name) { continue }
        Remove-Item -LiteralPath $item.FullName -Recurse -Force
    }
    $script:Copiados = 0
    Copiar-Carpeta $nuevo $App ''
    Set-Content -LiteralPath (Join-Path $App $Marca) -Value ('Instalado por «Instalar Bot Web» el {0:yyyy-MM-dd HH:mm}' -f (Get-Date)) -Encoding UTF8
}

function Escribir-Desinstalador([string]$origen) {
    # Copia «Desinstalar Bot Web.cmd» a la carpeta instalada con finales de linea de Windows (CRLF).
    $candidatos = @((Join-Path $origen 'instalador\Desinstalar Bot Web.cmd'))
    if ($Script) { $candidatos += Join-Path (Split-Path -Parent $Script) 'Desinstalar Bot Web.cmd' }
    foreach ($c in $candidatos) {
        if (Test-Path -LiteralPath $c) {
            $texto = [IO.File]::ReadAllText($c, [Text.Encoding]::UTF8) -replace "`r?`n", "`r`n"
            [IO.File]::WriteAllText((Join-Path $App 'Desinstalar Bot Web.cmd'), $texto, (New-Object Text.UTF8Encoding($false)))
            return $true
        }
    }
    return $false
}

# ------------------------------------------------------------------------------------------------ navegadores
function Buscar-Navegador([string]$empresa, [string]$producto, [string]$exe) {
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432, $env:LOCALAPPDATA)) {
        if ($base) {
            $ruta = Join-Path $base "$empresa\$producto\Application\$exe"
            if (Test-Path -LiteralPath $ruta) { return $ruta }
        }
    }
    foreach ($clave in @("HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe",
                         "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe",
                         "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\$exe")) {
        try {
            $ruta = (Get-Item -LiteralPath $clave -ErrorAction Stop).GetValue('')
            if ($ruta) { $ruta = [Environment]::ExpandEnvironmentVariables($ruta.Trim('"')) }
            if ($ruta -and (Test-Path -LiteralPath $ruta)) { return $ruta }
        } catch { }
    }
    return $null
}

# ------------------------------------------------------------------------------------------------ accesos directos
function Crear-Acceso([string]$ruta, [string]$destino, [string]$argumentos, [string]$carpeta, [string]$descripcion, [string]$icono) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ruta) | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $acceso = $shell.CreateShortcut($ruta)
    $acceso.TargetPath = $destino
    $acceso.Arguments = $argumentos
    $acceso.WorkingDirectory = $carpeta
    $acceso.Description = $descripcion
    if ($icono) { $acceso.IconLocation = $icono }
    $acceso.Save()
    Escribir-Log "      Acceso directo: $ruta"
}

if ($env:BOTWEB_SOLO_FUNCIONES -eq '1') { return }

# ============================================================================================================ pasos
function Principal {
    New-Item -ItemType Directory -Force -Path $Base | Out-Null
    Escribir-Log '================================================================'
    Escribir-Log ("Instalar Bot Web - {0} - Windows {1} - instalador: {2}" -f (Get-Date), [Environment]::OSVersion.Version, $Script)
    Write-Host ''
    if ($Actualizando) { Write-Host '  Actualizando Bot Web (tus reportes y datos se conservan)' -ForegroundColor White }
    else { Write-Host '  Instalador de Bot Web' -ForegroundColor White }
    Write-Host '  Se instala solo para tu usuario. No cierres esta ventana hasta que termine.'

    # ---------------------------------------------------------------------------------------------- 1
    Paso 1 'Comprobando Windows y la conexión a Internet...'
    if ([Environment]::OSVersion.Version.Major -lt 10) { Fallar 'Bot Web necesita Windows 10 u 11.' }
    if (-not [Environment]::Is64BitOperatingSystem) { Fallar 'Bot Web necesita Windows de 64 bits.' }
    Info ("Windows {0} de 64 bits: bien." -f [Environment]::OSVersion.Version)
    $local = $null
    if ($Fuente -ne 'github') { $local = Buscar-FuenteLocal }
    if ($Fuente -eq 'local' -and -not $local) { Fallar 'No se encontró el bot junto al instalador (BOTWEB_FUENTE=local).' }
    if ($local -and ($local.ToLower() -eq $App.ToLower())) {
        Escribir-Log '      El instalador está dentro de la carpeta instalada: se actualiza desde Internet.'
        $local = $null
    }
    if (-not (Hay-Conexion 'https://pypi.org/simple/')) {
        Fallar 'No hay conexión a Internet (no se llega a pypi.org, de donde se descargan las piezas del bot). Conéctate y vuelve a intentarlo.'
    }
    if (-not $local -and -not (Hay-Conexion 'https://github.com/')) {
        Fallar 'No se llega a github.com, de donde se descarga el bot. Revisa la conexión a Internet.'
    }
    Info 'Conexión a Internet: bien.'
    if (Test-Path -LiteralPath (Join-Path $App 'bot.py')) { Info "Bot Web ya estaba instalado en $App : se actualiza (tus datos se conservan)." }

    # ---------------------------------------------------------------------------------------------- 2
    Paso 2 'Buscando Python...'
    $python = Buscar-Python
    if (-not $python) {
        Info 'No hay un Python que sirva (hace falta 3.10 o más nuevo, de 64 bits). Se instala uno.'
        Instalar-Python
        $python = Buscar-Python
        if (-not $python) { Fallar 'Python se instaló pero no se encuentra. Reinicia el equipo y vuelve a abrir este instalador.' }
    }
    $nombrePython = "Python $($python.Version)"
    if ($python.Tienda) { $nombrePython += ' (Microsoft Store)' }
    Info "$nombrePython : bien."

    # ---------------------------------------------------------------------------------------------- 3
    $temporal = Join-Path $env:TEMP ('BotWeb_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $commit = $null
    try {
        if ($local) {
            Paso 3 'Copiando el bot...'
            Info "Desde: $local"
            $origen = $local
        } else {
            Paso 3 'Descargando el bot de Internet...'
            New-Item -ItemType Directory -Force -Path $temporal | Out-Null
            $zip = Join-Path $temporal 'bot.zip'
            $commit = Leer-Commit (Url-Api $UrlCodigo)          # (antes de descargar: la version que se instala)
            try { Descargar $UrlCodigo $zip } catch {
                if ("$($_.Exception.Message)" -match '\(404\)') {
                    Fallar 'GitHub dice que el bot no existe (404): el repositorio no es público o la rama New-tool no existe. Pide a quien te pasó el bot la carpeta completa y abre el instalador desde ella.'
                }
                Fallar 'No se pudo descargar el bot de github.com. Revisa la conexión a Internet.'
            }
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [IO.Compression.ZipFile]::ExtractToDirectory($zip, (Join-Path $temporal 'zip'))
            $raiz = Get-ChildItem -LiteralPath (Join-Path $temporal 'zip') -Directory |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bot.py') } | Select-Object -First 1
            if (-not $raiz) { Fallar 'Lo descargado de github.com no es el bot (falta bot.py).' }
            $origen = $raiz.FullName
        }
        # Primero a una carpeta aparte (sin datos de nadie); despues se cambia el codigo instalado por ese.
        $nuevo = Join-Path $temporal 'nuevo'
        $script:Copiados = 0
        Copiar-Carpeta $origen $nuevo ''
        foreach ($necesario in @('bot.py', 'requirements.txt', 'webbot', 'ui')) {
            if (-not (Test-Path -LiteralPath (Join-Path $nuevo $necesario))) { Fallar "Al bot le falta «$necesario». La copia no está completa." }
        }
        if ($commit) { Escribir-Version $nuevo $commit }
        if ($Actualizando) { Esperar-BotCerrado }
        Cerrar-BotAbierto
        try { Poner-Codigo $nuevo } catch { Fallar ('No se pudo copiar el bot a {0}. Cierra Bot Web y vuelve a intentarlo. ({1})' -f $App, $_.Exception.Message) }
        Info ("{0} archivos en {1}" -f $script:Copiados, $App)
        if (-not (Escribir-Desinstalador $origen)) { Aviso 'No se encontró «Desinstalar Bot Web.cmd»: no habrá acceso para desinstalar.' }
    } finally {
        Remove-Item -LiteralPath $temporal -Recurse -Force -ErrorAction SilentlyContinue
    }

    # ---------------------------------------------------------------------------------------------- 4
    Paso 4 'Preparando las piezas del bot (puede tardar unos minutos)...'
    Remove-Item Env:PYTHONHOME, Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONUTF8 = '1'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    if (Test-Path -LiteralPath $VenvPy) {
        $actual = Probar-Python $VenvPy @()
        if (-not $actual -or $actual.Version -lt [version]'3.10' -or -not $actual.Tkinter) {
            Info 'El entorno anterior no funciona: se crea de nuevo.'
            Remove-Item -LiteralPath (Join-Path $App '.venv') -Recurse -Force
        }
    }
    if (-not (Test-Path -LiteralPath $VenvPy)) {
        $argumentos = @()
        if ($python.Prefijo) { $argumentos += $python.Prefijo }
        $r = Ejecutar $python.Exe ($argumentos + @('-m', 'venv', (Join-Path $App '.venv'))) 600 $App
        if ($r.Codigo -ne 0 -or -not (Test-Path -LiteralPath $VenvPy)) { Fallar 'No se pudo crear el entorno de Python del bot (.venv).' }
        Info 'Entorno de Python creado.'
    }
    $instalado = $false
    for ($i = 1; $i -le 3 -and -not $instalado; $i++) {
        if ($i -gt 1) { Info "Reintentando ($i de 3)..."; Start-Sleep -Seconds (5 * $i) }
        $r = Ejecutar $VenvPy @('-m', 'pip', 'install', '--no-input', '--retries', '5', '--timeout', '60',
                                '-r', (Join-Path $App 'requirements.txt')) 1800 $App
        $instalado = ($r.Codigo -eq 0)
    }
    if (-not $instalado) { Fallar 'No se pudieron descargar las piezas del bot (playwright, keyring, openpyxl). Revisa la conexión a Internet.' }
    foreach ($modulo in @('playwright', 'keyring', 'openpyxl')) {         # (por si el requirements.txt es antiguo)
        if ((Ejecutar $VenvPy @('-c', "import $modulo") 120 $App).Codigo -ne 0) {
            if ((Ejecutar $VenvPy @('-m', 'pip', 'install', '--no-input', '--retries', '5', $modulo) 900 $App).Codigo -ne 0) {
                Fallar "No se pudo instalar «$modulo». Revisa la conexión a Internet."
            }
        }
    }
    if ((Ejecutar $VenvPy @('-c', 'import tkinter, playwright, keyring, openpyxl') 120 $App).Codigo -ne 0) {
        Fallar 'Faltan piezas del bot después de instalarlas (mira el registro).'
    }
    Info 'Piezas instaladas: playwright, keyring y openpyxl.'

    # ---------------------------------------------------------------------------------------------- 5
    Paso 5 'Buscando Chrome o Edge...'
    $chrome = Buscar-Navegador 'Google' 'Chrome' 'chrome.exe'
    $edge = Buscar-Navegador 'Microsoft' 'Edge' 'msedge.exe'
    if ($chrome) { Info "Chrome: $chrome" }
    if ($edge) { Info "Edge: $edge" }
    if (-not $chrome -and -not $edge) {
        Fallar 'No hay Chrome ni Edge en este equipo. Instala Google Chrome o Microsoft Edge y vuelve a abrir este instalador.'
    }
    $navegador = 'chrome'
    if (-not $chrome) { $navegador = 'msedge'; Info 'No hay Chrome: el bot usará Edge.' }

    # ---------------------------------------------------------------------------------------------- 6
    Paso 6 'Creando los accesos directos...'
    $icono = Get-ChildItem -LiteralPath $App -Filter '*.ico' -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $icono) { $icono = Get-ChildItem -LiteralPath (Join-Path $App 'ui') -Filter '*.ico' -File -ErrorAction SilentlyContinue | Select-Object -First 1 }
    $rutaIcono = ''
    if ($icono) { $rutaIcono = $icono.FullName }
    if ($SinAccesos) {
        Info '(Prueba: no se crean accesos directos.)'
    } else {
        $escritorio = [Environment]::GetFolderPath('Desktop')
        $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Bot Web'
        $argBot = Citar (Join-Path $App 'bot.py')
        Crear-Acceso (Join-Path $escritorio 'Bot Web.lnk') $VenvPyw $argBot $App 'Abrir Bot Web' $rutaIcono
        Crear-Acceso (Join-Path $menu 'Bot Web.lnk') $VenvPyw $argBot $App 'Abrir Bot Web' $rutaIcono
        $desinstalar = Join-Path $App 'Desinstalar Bot Web.cmd'
        if (Test-Path -LiteralPath $desinstalar) {
            Crear-Acceso (Join-Path $menu 'Desinstalar Bot Web.lnk') $desinstalar '' $env:TEMP 'Quitar Bot Web de este equipo' ''
        }
        Info 'En el Escritorio y en el menú Inicio: «Bot Web».'
    }

    # ---------------------------------------------------------------------------------------------- 7
    Paso 7 'Comprobando que todo funciona (tarda menos de un minuto)...'
    $r = Ejecutar $VenvPy @('-c', 'from webbot import programador; print(programador.ejecutable_python())') 120 $App
    Escribir-Log ("      Las tareas programadas usarán: {0}" -f $r.Salida)
    $argumentos = @('-X', 'utf8', (Join-Path $App 'bot.py'), '--smoke-web')
    if ($navegador -eq 'msedge') { $argumentos += @('--navegador', 'msedge') }
    $r = Ejecutar $VenvPy $argumentos 400 $App
    if ($r.Codigo -ne 0) {
        $ultimas = (($r.Salida -split "`r?`n") | Select-Object -Last 3) -join ' '
        Fallar ("La comprobación final falló: {0}" -f $ultimas)
    }
    Info 'OK: Bot Web funciona.'

    Write-Host ''
    if ($Actualizando) { Write-Host '  ¡Listo! Bot Web quedó actualizado.' -ForegroundColor Green }
    else { Write-Host '  ¡Listo! Bot Web quedó instalado.' -ForegroundColor Green }
    Write-Host "  Carpeta del bot: $App"
    Write-Host "  Tus reportes descargados irán a: $(Join-Path $App 'descargas')"
    if (-not $SinAccesos) { Write-Host '  Para abrirlo: «Bot Web» en el Escritorio o en el menú Inicio.' }
    Escribir-Log 'Instalación terminada: OK'
    Write-Host ''
    if ($Actualizando) {
        Write-Host '  Se abre Bot Web...'
        Abrir-Bot
        Start-Sleep -Seconds 3
    } elseif (-not $NoPreguntar -and (Preguntar '  ¿Abrir Bot Web ahora?' $true)) {
        Abrir-Bot
    }
}

try {
    Principal
    Pausa
    exit 0
} catch {
    Escribir-Log ("ERROR: {0}" -f $_.Exception.Message)
    Escribir-Log ("       {0}" -f $_.ScriptStackTrace)
    Write-Host ''
    Write-Host '  No se pudo terminar la instalación.' -ForegroundColor Red
    if ($script:MensajeAmigable) { Write-Host "  $($script:MensajeAmigable)" -ForegroundColor Red }
    else { Write-Host "  Algo salió mal: $($_.Exception.Message)" -ForegroundColor Red }
    Write-Host ''
    Write-Host '  Puedes volver a abrir el instalador: sigue donde se quedó y no borra nada tuyo.'
    Write-Host "  Detalles en: $Log"
    if ($Actualizando) {
        # (modo actualización: se vuelve a abrir el bot que habia y se deja leer el mensaje)
        if ((Test-Path -LiteralPath $VenvPyw) -and (Test-Path -LiteralPath (Join-Path $App 'bot.py'))) {
            Write-Host '  Se vuelve a abrir Bot Web.'
            try { Abrir-Bot } catch { Escribir-Log ("      No se pudo abrir el bot: {0}" -f $_.Exception.Message) }
        }
        Write-Host ''
        try { [void](Read-Host 'Pulsa Intro para cerrar esta ventana') } catch { }
    }
    Pausa
    exit 1
}
