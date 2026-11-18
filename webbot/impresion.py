"""v3.9: imprimir en Windows sin instalar nada (paso «Imprimir» y botón «Imprimir» de los archivos descargados).

- `impresoras()`: las impresoras instaladas y la predeterminada (winspool: EnumPrintersW / GetDefaultPrinterW).
- `puede_imprimir(ruta)`: si Windows tiene un programa que sepa imprimir ese tipo de archivo (verbo «print» del
  registro: AssocQueryStringW; solo LEE).
- `imprimir_archivo(ruta, impresora)`: lo manda a imprimir con el programa asociado (ShellExecute «print» para la
  predeterminada, «printto» para una impresora concreta).  Es lo mismo que «clic derecho → Imprimir» del Explorador:
  el programa (Excel, el lector de PDF…) se abre un momento, imprime y se cierra.  No espera a que salga el papel.

Todo lo que toca Windows de verdad pasa por `_enumerar`, `_predeterminada`, `_programa_que_imprime` y `_lanzar`: las
pruebas los sustituyen (NUNCA se imprime de verdad en las pruebas).
"""

import os
import re

EXTENSIONES_IMPRIMIR = (".pdf", ".xlsx", ".xls", ".xlsm", ".csv", ".txt", ".doc", ".docx", ".htm", ".html", ".png",
                        ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".rtf", ".odt", ".ods", ".xps")


class ErrorImpresion(RuntimeError):
    """No se pudo mandar a imprimir (sin impresora, sin programa para ese tipo de archivo…)."""


# v3.9: impresoras que no sacan papel: preguntan dónde guardar el archivo.  Si se usan sin decirles el archivo, Windows
# abre una ventana «Guardar la salida de impresión como…» y el bot se queda esperando para siempre: se les pasa siempre
# un archivo de salida (al lado del PDF, con «(impreso)» en el nombre).
RX_IMPRESORA_A_ARCHIVO = re.compile(r"print to pdf|imprimir en pdf|xps document writer|escritor de documentos xps|"
                                    r"onenote|pdf24|bullzip|cutepdf|dopdf|pdfcreator|fax", re.IGNORECASE)


def imprime_a_un_archivo(impresora):
    """True si esa impresora guarda un archivo en vez de sacar papel («Microsoft Print to PDF»…)."""
    return bool(RX_IMPRESORA_A_ARCHIVO.search(str(impresora or "")))


def _salida_para(ruta, impresora):
    """Archivo donde escribe una impresora de las que guardan archivo: al lado del original, «… (impreso).pdf»."""
    base, _ext = os.path.splitext(os.path.abspath(ruta))
    nueva = ".xps" if re.search(r"xps", str(impresora or ""), re.IGNORECASE) else ".pdf"
    destino = base + " (impreso)" + nueva
    k = 2
    while os.path.exists(destino):
        destino = "%s (impreso %d)%s" % (base, k, nueva)
        k += 1
    return destino


# ------------------------------------------------------------------ lo que toca Windows (las pruebas lo sustituyen)
def _enumerar():
    """Nombres de las impresoras instaladas (locales y de red conectadas)."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    PRINTER_ENUM_LOCAL, PRINTER_ENUM_CONNECTIONS = 0x2, 0x4

    class PRINTER_INFO_4(ctypes.Structure):
        _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR),
                    ("Attributes", wintypes.DWORD)]
    enum = winspool.EnumPrintersW
    enum.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                     ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    enum.restype = wintypes.BOOL
    necesarios, cuantos = wintypes.DWORD(0), wintypes.DWORD(0)
    flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    enum(flags, None, 4, None, 0, ctypes.byref(necesarios), ctypes.byref(cuantos))
    if not necesarios.value:
        return []
    buf = ctypes.create_string_buffer(necesarios.value)
    if not enum(flags, None, 4, buf, necesarios, ctypes.byref(necesarios), ctypes.byref(cuantos)):
        return []
    info = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4))
    return [info[i].pPrinterName for i in range(cuantos.value) if info[i].pPrinterName]


def _predeterminada():
    """Nombre de la impresora predeterminada de Windows, o ""."""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    fn = winspool.GetDefaultPrinterW
    fn.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL
    n = wintypes.DWORD(0)
    fn(None, ctypes.byref(n))
    if not n.value:
        return ""
    buf = ctypes.create_unicode_buffer(n.value)
    return buf.value if fn(buf, ctypes.byref(n)) else ""


def _programa_que_imprime(ext, verbo="print"):
    """El comando que usa Windows para imprimir archivos `ext` («.pdf») con ese verbo, o "" si no hay ninguno."""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes
    shlwapi = ctypes.WinDLL("shlwapi.dll")
    fn = shlwapi.AssocQueryStringW
    fn.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPWSTR,
                   ctypes.POINTER(wintypes.DWORD)]
    fn.restype = ctypes.c_long
    ASSOCF_NOTRUNCATE, ASSOCSTR_COMMAND = 0x20, 1
    n = wintypes.DWORD(2048)
    buf = ctypes.create_unicode_buffer(n.value)
    if fn(ASSOCF_NOTRUNCATE, ASSOCSTR_COMMAND, ext, verbo, buf, ctypes.byref(n)) != 0:
        return ""
    return buf.value


# PDF sin programa que lo imprima (lo normal en Windows 11: los PDF se abren con Edge, que no imprime desde el Explorador):
# Windows trae su propio lector de PDF (Windows.Data.Pdf, el de las apps de la tienda).  Este PowerShell dibuja cada página
# como imagen (200 ppp) y la manda a la impresora con .NET (System.Drawing.Printing), sin ventanas.  Los datos llegan por
# variables de entorno (sin problemas de comillas).  BOTWEB_SALIDA (solo para comprobarlo a mano con «Microsoft Print to
# PDF»): imprime a ese archivo.
PS_IMPRIMIR_PDF = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'      # v3.9: sin esto el progreso de PowerShell llega como CLIXML y el mensaje
$WarningPreference = 'SilentlyContinue'       # de error que veía el usuario era ilegible
try {
$ruta = $env:BOTWEB_PDF; $impresora = $env:BOTWEB_IMPRESORA; $salida = $env:BOTWEB_SALIDA
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$metodos = [System.WindowsRuntimeSystemExtensions].GetMethods()
$conResultado = $metodos | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$sinResultado = $metodos | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
function Esperar($op, [Type]$tipo) { $t = $conResultado.MakeGenericMethod($tipo).Invoke($null, @($op)); $null = $t.Wait(-1); $t.Result }
function EsperarAccion($op) { $t = $sinResultado.Invoke($null, @($op)); $null = $t.Wait(-1) }
$archivo = Esperar ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ruta)) ([Windows.Storage.StorageFile])
$pdf = Esperar ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($archivo)) ([Windows.Data.Pdf.PdfDocument])
if ($pdf.PageCount -lt 1) { throw 'El PDF no tiene páginas' }
$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.DocumentName = [System.IO.Path]::GetFileName($ruta)
$doc.PrinterSettings.PrinterName = $impresora
if (-not $doc.PrinterSettings.IsValid -or $doc.PrinterSettings.PrinterName -ne $impresora) { throw ('No existe la impresora ' + $impresora) }
if ($salida) { $doc.PrinterSettings.PrintToFile = $true; $doc.PrinterSettings.PrintFileName = $salida }
$doc.PrintController = New-Object System.Drawing.Printing.StandardPrintController
$script:k = 0
$doc.add_QueryPageSettings({ param($s, $e)
  $p = $pdf.GetPage([uint32]$script:k); $e.PageSettings.Landscape = $p.Size.Width -gt $p.Size.Height; $p.Dispose() })
$doc.add_PrintPage({ param($s, $e)
  $p = $pdf.GetPage([uint32]$script:k)
  $flujo = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
  $op = New-Object Windows.Data.Pdf.PdfPageRenderOptions
  $op.DestinationWidth = [uint32][math]::Max(1, [math]::Round($p.Size.Width * 200 / 96))
  EsperarAccion ($p.RenderToStreamAsync($flujo, $op))
  $img = [System.Drawing.Image]::FromStream([System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($flujo))
  $a = $e.MarginBounds
  $f = [math]::Min($a.Width / $img.Width, $a.Height / $img.Height)
  $w = [int]($img.Width * $f); $h = [int]($img.Height * $f)
  $e.Graphics.DrawImage($img, [int]($a.X + ($a.Width - $w) / 2), [int]($a.Y + ($a.Height - $h) / 2), $w, $h)
  $img.Dispose(); $p.Dispose()
  $script:k++
  $e.HasMorePages = $script:k -lt $pdf.PageCount })
$doc.Print()
Write-Output ('PAGINAS=' + $pdf.PageCount)
} catch {
  Write-Output ('ERROR=' + $_.Exception.Message)
  exit 1
}
"""


def _limpiar_powershell(texto):
    """v3.9: deja legible lo que escribe PowerShell en el canal de errores (quita el CLIXML del progreso)."""
    texto = re.sub(r"#<\s*CLIXML", " ", str(texto or ""))
    texto = re.sub(r"<[^>]{1,400}>", " ", texto, flags=re.S)
    texto = texto.replace("_x000D_", " ").replace("_x000A_", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _motivo_impresion(texto, impresora):
    """v3.9: el error de Windows, en español y con qué hacer."""
    t = _limpiar_powershell(texto)
    if re.search(r"no existe la impresora|not found|InvalidPrinter|no válida|not valid", t, re.IGNORECASE):
        return ("Windows no pudo usar la impresora «%s» (puede que esté apagada, desconectada o que haya cambiado de "
                "nombre). Mírala en Configuración → Impresoras y escáneres." % impresora)
    if re.search(r"handle is invalid|controlador|driver|spool|cola de impresi", t, re.IGNORECASE):
        return ("Windows dio un error con la impresora «%s»: comprueba que está encendida y conectada, y que no tiene "
                "trabajos atascados en la cola." % impresora)
    if re.search(r"Windows\.Data\.Pdf|PdfDocument|no tiene p|password|contrase", t, re.IGNORECASE):
        return "El archivo no se pudo leer como PDF (puede estar incompleto o protegido con contraseña)."
    return "Windows no pudo imprimir en «%s»%s" % (impresora, (": " + t[:200]) if t else "")


def _imprimir_pdf_windows(ruta, impresora, salida=None, tiempo=300):
    """Imprime un PDF con el lector de PDF de Windows (ver PS_IMPRIMIR_PDF).  Devuelve el número de páginas."""
    import base64
    import subprocess
    entorno = dict(os.environ, BOTWEB_PDF=os.path.abspath(ruta), BOTWEB_IMPRESORA=impresora,
                   BOTWEB_SALIDA=os.path.abspath(salida) if salida else "")
    codificado = base64.b64encode(PS_IMPRIMIR_PDF.encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-EncodedCommand", codificado], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=tiempo, env=entorno,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise ErrorImpresion(
            "La impresora «%s» no contestó en %d minutos: si es una impresora que guarda un archivo (como «Microsoft "
            "Print to PDF»), Windows está esperando que alguien diga dónde guardarlo; elige una impresora de papel."
            % (impresora, max(1, tiempo // 60))) from None
    except OSError as e:
        raise ErrorImpresion("No se pudo imprimir el PDF con el lector de Windows: %s" % type(e).__name__) from None
    lineas = (r.stdout or "").splitlines()
    m = [x for x in lineas if x.startswith("PAGINAS=")]
    if r.returncode != 0 or not m:
        suyo = [x[len("ERROR="):] for x in lineas if x.startswith("ERROR=")]
        raise ErrorImpresion(_motivo_impresion(suyo[0] if suyo else (r.stderr or r.stdout), impresora))
    return int(m[-1].split("=", 1)[1])


def _lanzar(ruta, verbo, parametros=None):
    """ShellExecuteW(verbo) sobre el archivo.  Devuelve el código (> 32 = bien)."""
    import ctypes
    from ctypes import wintypes
    fn = ctypes.windll.shell32.ShellExecuteW
    fn.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                   ctypes.c_int]
    fn.restype = ctypes.c_void_p
    r = fn(None, verbo, ruta, parametros, os.path.dirname(ruta) or None, 0)     # 0 = SW_HIDE
    return int(r or 0)


# ------------------------------------------------------------------ lo que usa el bot
def impresoras():
    """{"impresoras": [nombres], "predeterminada": nombre o ""}.  Si no se puede leer, listas vacías."""
    try:
        lista = list(dict.fromkeys(_enumerar()))
    except OSError:
        lista = []
    try:
        defecto = _predeterminada() or ""
    except OSError:
        defecto = ""
    if defecto and defecto not in lista:
        lista.insert(0, defecto)
    return {"impresoras": lista, "predeterminada": defecto}


def puede_imprimir(ruta):
    """True si hay un programa en Windows que sepa imprimir ese tipo de archivo."""
    ext = os.path.splitext(ruta or "")[1].lower()
    return bool(ext) and bool(_programa_que_imprime(ext, "print"))


_ERRORES = {0: "Windows se quedó sin memoria", 2: "no se encontró el archivo", 3: "no se encontró la carpeta",
            5: "Windows no dejó abrir el archivo (acceso denegado)", 8: "Windows se quedó sin memoria",
            26: "el archivo está abierto en otro programa", 32: "falta una parte del programa que imprime"}


def imprimir_archivo(ruta, impresora="", log=None, salida=None):
    """Manda `ruta` a imprimir.  `impresora` vacío = la predeterminada.  Devuelve el nombre de la impresora usada.
    Lanza ErrorImpresion con un mensaje que se entiende (en español) si no hay impresora o programa para imprimirlo.
    v3.9: con una impresora que guarda un archivo («Microsoft Print to PDF»…) se le dice dónde guardarlo (`salida`, o
    uno al lado del original): si no, Windows se queda esperando en una ventana que nadie ve."""
    log = log or (lambda texto: None)
    ruta = os.path.abspath(ruta or "")
    if not os.path.isfile(ruta):
        raise ErrorImpresion("No existe el archivo que hay que imprimir: %s" % ruta)
    info = impresoras()
    lista, defecto = info["impresoras"], info["predeterminada"]
    if not lista:
        raise ErrorImpresion("No hay ninguna impresora instalada en Windows: instala una (Configuración → "
                             "Impresoras y escáneres) y vuelve a probar")
    pedida = (impresora or "").strip()
    if pedida:
        exacta = next((p for p in lista if p.lower() == pedida.lower()), None)
        if exacta is None:
            raise ErrorImpresion("No existe la impresora «%s». Impresoras instaladas: %s" % (
                pedida, ", ".join("«%s»" % p for p in lista)))
        pedida = exacta
    elif not defecto:
        raise ErrorImpresion("Windows no tiene impresora predeterminada: elige una en el paso «Imprimir» (impresoras: "
                             "%s)" % ", ".join("«%s»" % p for p in lista))
    destino = pedida or defecto
    ext = os.path.splitext(ruta)[1].lower()
    nombre = os.path.basename(ruta)
    sin_programa = ("Windows no tiene ningún programa que sepa imprimir archivos %s («%s»). Instala uno (p. ej. un lector "
                    "de PDF para los .pdf, o Excel para los .xlsx) y ponlo como programa predeterminado para ese tipo de "
                    "archivo." % (ext or "sin extensión", nombre))
    usar_printto = bool(pedida) and pedida != defecto
    verbo = "printto" if usar_printto else "print"
    a_archivo = imprime_a_un_archivo(destino)
    if ext == ".pdf" and (a_archivo or not _programa_que_imprime(ext, verbo)):
        # Windows trae su propio lector de PDF: se imprime con él (y así se puede decir dónde guardar el archivo)
        guardar = salida or (_salida_para(ruta, destino) if a_archivo else None)
        paginas = _imprimir_pdf_windows(ruta, destino, salida=guardar)
        if guardar:
            log("«%s» se imprimió en «%s»: %d página%s en %s" % (
                nombre, destino, paginas, "" if paginas == 1 else "s", guardar))
        else:
            log("enviado a la impresora «%s»: %s (%d página%s, con el lector de PDF de Windows)" % (
                destino, nombre, paginas, "" if paginas == 1 else "s"))
        return destino
    if a_archivo:
        raise ErrorImpresion(
            "La impresora «%s» no saca papel: pregunta dónde guardar el archivo, y eso el bot no lo puede contestar. "
            "Con archivos %s elige una impresora de papel (impresoras: %s)." % (
                destino, ext or "sin extensión", ", ".join("«%s»" % x for x in lista)))
    if not _programa_que_imprime(ext, verbo):
        if not _programa_que_imprime(ext, "print"):
            raise ErrorImpresion(sin_programa)
        raise ErrorImpresion("El programa que imprime los archivos %s no deja elegir la impresora. Quita la impresora del "
                             "paso (se usará la predeterminada, «%s») o pon «%s» como predeterminada en Windows."
                             % (ext, defecto or "ninguna", pedida))
    codigo = _lanzar(ruta, "printto", '"%s"' % destino) if usar_printto else _lanzar(ruta, "print")
    if codigo <= 32:
        if codigo in (27, 31):
            raise ErrorImpresion(sin_programa)
        raise ErrorImpresion("No se pudo mandar «%s» a la impresora «%s»: %s (código %d)" % (
            nombre, destino, _ERRORES.get(codigo, "error de Windows"), codigo))
    log("enviado a la impresora «%s»: %s" % (destino, nombre))
    return destino
