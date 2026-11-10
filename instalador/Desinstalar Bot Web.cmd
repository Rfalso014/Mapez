<# : Bot Web - desinstalador. Haz doble clic en este archivo.
@echo off
setlocal
chcp 65001 >nul
title Desinstalar Bot Web
rem Se ejecuta desde una copia en TEMP para poder borrar la carpeta del bot (donde puede estar este archivo).
if not defined BOTWEB_COPIA (
    set "BOTWEB_COPIA=1"
    set "BOTWEB_ORIGEN=%~dp0"
    copy /y "%~f0" "%TEMP%\BotWeb-desinstalar.cmd" >nul 2>nul && (
        cd /d "%TEMP%"
        "%TEMP%\BotWeb-desinstalar.cmd"
    )
)
set "BOTWEB_SCRIPT=%~f0"
set "BOTWEB_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "BOTWEB_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
cd /d "%TEMP%"
"%BOTWEB_PS%" -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create([IO.File]::ReadAllText($env:BOTWEB_SCRIPT, [Text.Encoding]::UTF8)))"
set "BOTWEB_CODIGO=%errorlevel%"
if /i "%~f0"=="%TEMP%\BotWeb-desinstalar.cmd" (goto) 2>nul & del "%~f0" & exit /b %BOTWEB_CODIGO%
endlocal & exit /b %BOTWEB_CODIGO%
#>

# ============================================================================================================
#  Desinstalador de Bot Web.  Quita los accesos directos, las tareas programadas del bot (carpeta \BotWeb\ del
#  Programador de tareas) y el programa.  Tus datos (reportes, descargas, contraseñas) se CONSERVAN salvo que digas
#  que si a la segunda pregunta.  Python no se desinstala.
#
#  Variables de prueba (ocultas):
#    BOTWEB_DESTINO=C:\carpeta   la carpeta instalada (en vez de %USERPROFILE%\BotWeb)
#    BOTWEB_NO_PREGUNTAR=1       contesta «si» a quitar el bot y «no» a borrar los datos (salvo BOTWEB_BORRAR_DATOS=1)
#    BOTWEB_SIN_ACCESOS=1        no toca los accesos directos
#    BOTWEB_SIN_TAREAS=1         solo lista las tareas programadas, no las borra
#    BOTWEB_SERVICIO=Nombre      otro nombre en el Administrador de credenciales (en vez de BotWeb)
# ============================================================================================================

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
Set-Location -LiteralPath $env:TEMP
[Environment]::CurrentDirectory = $env:TEMP

$Origen = "$env:BOTWEB_ORIGEN".TrimEnd('\')
if ($env:BOTWEB_DESTINO) {
    $Base = [IO.Path]::GetFullPath($env:BOTWEB_DESTINO); $App = Join-Path $Base 'app'
} elseif ($Origen -and (Test-Path -LiteralPath (Join-Path $Origen 'bot.py'))) {
    $App = $Origen; $Base = Split-Path -Parent $App           # el desinstalador de la carpeta instalada
} else {
    $Base = Join-Path $env:USERPROFILE 'BotWeb'; $App = Join-Path $Base 'app'
}
$Marca = Join-Path $App '.instalado-por-botweb'
$NoPreguntar = ($env:BOTWEB_NO_PREGUNTAR -eq '1')
$SinAccesos = ($env:BOTWEB_SIN_ACCESOS -eq '1')
$SinTareas = ($env:BOTWEB_SIN_TAREAS -eq '1')
$Servicio = 'BotWeb'
if ($env:BOTWEB_SERVICIO) { $Servicio = $env:BOTWEB_SERVICIO }
$Datos = @('datos', 'perfiles', 'registros', 'descargas', 'flujos')

function Info([string]$t) { Write-Host "      $t" }
function Aviso([string]$t) { Write-Host "      $t" -ForegroundColor Yellow }
function Pausa { if (-not $NoPreguntar) { Write-Host ''; [void](Read-Host 'Pulsa Intro para cerrar esta ventana') } }
function Preguntar([string]$texto, [bool]$defecto, [bool]$respuestaSinPreguntar) {
    if ($NoPreguntar) { return $respuestaSinPreguntar }
    while ($true) {
        $r = ("" + (Read-Host "$texto (S/N)")).Trim().ToLower()
        if ($r -eq '') { return $defecto }
        if ($r -in @('s', 'si', 'sí', 'y', 'yes')) { return $true }
        if ($r -in @('n', 'no')) { return $false }
        Write-Host '      Escribe S (si) o N (no).'
    }
}

function Ejecutar([string]$exe, [string]$argumentos) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe; $psi.Arguments = $argumentos
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $p = [Diagnostics.Process]::Start($psi)
    $salida = $p.StandardOutput.ReadToEndAsync(); $errores = $p.StandardError.ReadToEndAsync()
    $p.WaitForExit()
    return @{ Codigo = $p.ExitCode; Salida = ($salida.Result + $errores.Result) }
}

function Tareas-DelBot {
    # Nombres «BotWeb\…» de las tareas de la carpeta \BotWeb\ del Programador de tareas.
    if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
        $tareas = @(Get-ScheduledTask -TaskPath '\BotWeb\' -ErrorAction SilentlyContinue)   # (nada si no hay ninguna)
        return @($tareas | ForEach-Object { 'BotWeb\' + $_.TaskName } | Sort-Object -Unique)
    }
    $r = Ejecutar "$env:SystemRoot\System32\schtasks.exe" '/Query /FO CSV /NH'
    $nombres = @()
    foreach ($fila in @($r.Salida -split "`r?`n" | Where-Object { $_.Trim() } | ConvertFrom-Csv -Header 'Nombre', 'Proxima', 'Estado')) {
        if ($fila.Nombre -like '\BotWeb\*') { $nombres += $fila.Nombre.Substring(1) }
    }
    return @($nombres | Sort-Object -Unique)
}

$CodigoCredenciales = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class BotWebCredenciales {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct CREDENTIAL {
        public int Flags; public int Type; public string TargetName; public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public int CredentialBlobSize; public IntPtr CredentialBlob; public int Persist;
        public int AttributeCount; public IntPtr Attributes; public string TargetAlias; public string UserName;
    }
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredEnumerateW(string filter, int flags, out int count, out IntPtr credentials);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredDeleteW(string target, int type, int flags);
    [DllImport("advapi32.dll")]
    private static extern void CredFree(IntPtr buffer);
    public static string[] Genericas() {
        int n; IntPtr lista; var nombres = new List<string>();
        if (!CredEnumerateW(null, 0, out n, out lista)) return nombres.ToArray();
        try {
            for (int i = 0; i < n; i++) {
                IntPtr p = Marshal.ReadIntPtr(lista, i * IntPtr.Size);
                var c = (CREDENTIAL)Marshal.PtrToStructure(p, typeof(CREDENTIAL));
                if (c.Type == 1 && c.TargetName != null) nombres.Add(c.TargetName);
            }
        } finally { CredFree(lista); }
        return nombres.ToArray();
    }
    public static bool Borrar(string target) { return CredDeleteW(target, 1, 0); }
}
'@

function Borrar-Credenciales {
    # keyring guarda cada contraseña del bot como «BotWeb» o «<nombre>@BotWeb» (credenciales genéricas).
    Add-Type -TypeDefinition $CodigoCredenciales -Language CSharp
    $borradas = 0
    foreach ($t in [BotWebCredenciales]::Genericas()) {
        if ($t -eq $Servicio -or $t.EndsWith('@' + $Servicio)) {
            if ([BotWebCredenciales]::Borrar($t)) { $borradas++ }
        }
    }
    return $borradas
}

function Procesos-DelBot {
    $app = $App.ToLower()
    try {
        return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            ("" + $_.ExecutablePath).ToLower().StartsWith($app + '\') -or ("" + $_.CommandLine).ToLower().Contains($app + '\bot.py')
        })
    } catch { return @() }
}

function Quitar-Acceso([string]$ruta) {
    if (-not (Test-Path -LiteralPath $ruta)) { return }
    try {
        $destino = (New-Object -ComObject WScript.Shell).CreateShortcut($ruta).TargetPath
        if ($destino -and -not $destino.ToLower().StartsWith($App.ToLower() + '\')) { return }   # no es de este bot
    } catch { }
    Remove-Item -LiteralPath $ruta -Force
    Info "Quitado: $ruta"
}

function Principal {
    Write-Host ''
    Write-Host '  Desinstalar Bot Web' -ForegroundColor White
    Write-Host "  Carpeta del bot: $App"
    Write-Host '  Se quitan los accesos directos, las tareas programadas del bot y el programa.'
    Write-Host '  Python no se desinstala (lo pueden usar otros programas).'
    Write-Host ''
    if (Test-Path -LiteralPath $App) {
        if (Test-Path -LiteralPath (Join-Path $App '.git')) { throw "La carpeta $App es una copia de trabajo (tiene .git): no se borra." }
        if ((Test-Path -LiteralPath (Join-Path $App 'bot.py')) -and -not (Test-Path -LiteralPath $Marca)) {
            throw "La carpeta $App no la creó el instalador de Bot Web: no se borra."
        }
    } else {
        Aviso 'El bot ya no está en esa carpeta; se quitan solo los accesos directos y las tareas.'
    }
    if (-not (Preguntar '  ¿Quitar Bot Web de este equipo?' $false $true)) { Write-Host '  No se ha quitado nada.'; return }

    $procesos = Procesos-DelBot
    if ($procesos.Count -gt 0) {
        Aviso 'Bot Web está abierto (o haciendo una tarea).'
        if (-not (Preguntar '      ¿Cerrarlo para seguir?' $true $true)) { Write-Host '  No se ha quitado nada.'; return }
        foreach ($p in $procesos) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { } }
        Start-Sleep -Seconds 2
    }

    Write-Host ''
    Write-Host '[1/3] Tareas programadas del bot...' -ForegroundColor Cyan
    $tareas = Tareas-DelBot
    if ($tareas.Count -eq 0) { Info 'No hay ninguna.' }
    foreach ($t in $tareas) {
        if ($SinTareas) { Info "(Prueba: no se borra) $t"; continue }
        $r = Ejecutar "$env:SystemRoot\System32\schtasks.exe" ('/Delete /TN "{0}" /F' -f $t)
        if ($r.Codigo -eq 0) { Info "Borrada: $t" } else { Aviso "No se pudo borrar: $t" }
    }
    if (-not $SinTareas) {
        try { $s = New-Object -ComObject Schedule.Service; $s.Connect(); $s.GetFolder('\').DeleteFolder('BotWeb', 0) } catch { }   # (solo si quedó vacía)
    }

    Write-Host ''
    Write-Host '[2/3] Accesos directos...' -ForegroundColor Cyan
    if ($SinAccesos) { Info '(Prueba: no se tocan.)' }
    else {
        Quitar-Acceso (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Bot Web.lnk')
        $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Bot Web'
        Quitar-Acceso (Join-Path $menu 'Bot Web.lnk')
        Quitar-Acceso (Join-Path $menu 'Desinstalar Bot Web.lnk')
        if ((Test-Path -LiteralPath $menu) -and -not (Get-ChildItem -LiteralPath $menu -Force)) { Remove-Item -LiteralPath $menu -Force }
    }

    Write-Host ''
    Write-Host '[3/3] Programa...' -ForegroundColor Cyan
    Write-Host '      Tus datos son: los reportes guardados, lo descargado, los registros y las contraseñas guardadas.'
    $borrarDatos = Preguntar '      ¿Borrar TAMBIÉN tus datos? Si dices que no, se quedan por si vuelves a instalarlo.' $false ($env:BOTWEB_BORRAR_DATOS -eq '1')
    if ($borrarDatos) {
        $n = Borrar-Credenciales
        Info "Contraseñas guardadas borradas: $n"
        if (Test-Path -LiteralPath $App) { Remove-Item -LiteralPath $App -Recurse -Force }
        Remove-Item -LiteralPath (Join-Path $Base 'instalacion.log') -Force -ErrorAction SilentlyContinue
        if ((Test-Path -LiteralPath $Base) -and -not (Get-ChildItem -LiteralPath $Base -Force)) { Remove-Item -LiteralPath $Base -Force }
        Info 'Bot Web y tus datos se han borrado.'
    } elseif (Test-Path -LiteralPath $App) {
        foreach ($item in @(Get-ChildItem -LiteralPath $App -Force)) {
            if ($Datos -contains $item.Name) { continue }
            Remove-Item -LiteralPath $item.FullName -Recurse -Force
        }
        Info 'Bot Web se ha quitado. Tus datos se quedan en:'
        Info "  $App"
        Info '(Si vuelves a instalarlo, los encontrará ahí. Las contraseñas siguen en el Administrador de credenciales.)'
    }
    Write-Host ''
    Write-Host '  Listo.' -ForegroundColor Green
}

try {
    Principal
    Pausa
    exit 0
} catch {
    Write-Host ''
    Write-Host "  No se pudo terminar: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '  Cierra Bot Web si está abierto y vuelve a intentarlo.'
    Pausa
    exit 1
}
