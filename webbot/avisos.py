"""Avisos al usuario: notificaciones dentro de la aplicación (tabla `notificaciones`) y de Windows («toast»).

- `notificar(titulo, texto)`: notificación de Windows con el notificador actual (inyectable).
- `usar_notificador(funcion)`: cambia el notificador (las pruebas pasan una lista: `usar_notificador(lista_append)`);
  None = el de Windows.
- `avisar(almacen, tipo, titulo, texto, datos)`: crea la notificación de la aplicación (si `almacen` las admite) y
  muestra la de Windows.  Nunca lanza excepciones (un aviso que falla no debe tumbar una ejecución).

Seguridad para las pruebas: el notificador de Windows no hace NADA si la variable de entorno BOTWEB_SIN_AVISOS=1 o
si se está ejecutando `unittest` (así ninguna prueba muestra notificaciones reales).
No importa playwright ni tkinter.
"""

import os
import subprocess
import sys

APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

_SCRIPT_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [Security.SecurityElement]::Escape($env:BOTWEB_AVISO_TITULO)
$b = [Security.SecurityElement]::Escape($env:BOTWEB_AVISO_TEXTO)
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
$n = New-Object Windows.UI.Notifications.ToastNotification $x
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:BOTWEB_AVISO_APP).Show($n)
"""


def avisos_desactivados():
    return os.environ.get("BOTWEB_SIN_AVISOS") == "1" or "unittest" in sys.modules


def toast_windows(titulo, texto):
    """Muestra una notificación de Windows (sin esperar).  No hace nada en pruebas ni fuera de Windows."""
    if avisos_desactivados() or os.name != "nt":
        return False
    entorno = dict(os.environ, BOTWEB_AVISO_TITULO="Bot Web — " + (titulo or "")[:120],
                   BOTWEB_AVISO_TEXTO=(texto or "")[:300], BOTWEB_AVISO_APP=APP_ID)
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                          _SCRIPT_TOAST], env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except OSError:
        return False


_notificador = None


def usar_notificador(funcion):
    """Inyecta el notificador `funcion(titulo, texto)` (None = notificaciones de Windows)."""
    global _notificador
    _notificador = funcion


def notificar(titulo, texto):
    try:
        return (_notificador or toast_windows)(titulo, texto)
    except Exception:                  # noqa: BLE001 (un aviso nunca debe tumbar nada)
        return False


def avisar(almacen, tipo, titulo, texto, datos=None, windows=True):
    """Notificación de la aplicación (si `almacen` la admite) + de Windows.  Devuelve el id de la notificación o None."""
    nid = None
    crear = getattr(almacen, "crear_notificacion", None)
    if crear is not None:
        try:
            nid = crear(tipo, titulo, texto, datos or {})
        except Exception:              # noqa: BLE001
            nid = None
    if windows:
        notificar(titulo, texto)
    return nid
