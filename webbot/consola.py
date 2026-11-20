"""Los mensajes del programa cuando NO hay ventana negra (v4.0).

Bot Web se abre con `Bot Web.vbs` (o con el acceso directo que crea el instalador), que usa **pythonw.exe**: así no
aparece ninguna consola.  Con pythonw, `sys.stdout` y `sys.stderr` NO existen (son `None`), y cualquier `print` del
programa daría un error.  `preparar()` los cambia por el archivo `registros/consola.log`, de modo que:

- nada de lo que el programa cuenta se pierde: queda en ese archivo (es lo que antes se leía en la ventana negra);
- `print` nunca falla, ni cuando el archivo no se puede abrir (entonces los mensajes se tiran a un sumidero).

El archivo se usa en modo «añadir» y, cuando pasa de `MAX_BYTES`, se renombra a `.1` y se empieza otro (así no crece
sin fin).  Con consola (ejecutando `iniciar.bat`, «ver los mensajes», o desde una terminal) no se toca nada: los
mensajes salen por la pantalla como siempre.

No importa playwright ni tkinter.
"""

import os
import sys

NOMBRE = "consola.log"
MAX_BYTES = 2 * 1024 * 1024


class _Sumidero:
    """Por si no se puede escribir en ningún sitio: `print` no debe fallar nunca."""

    def write(self, texto):
        return len(texto or "")

    def flush(self):
        return None

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("sin consola")


def hay_consola():
    """¿Hay una salida de verdad donde escribir (ventana negra o terminal)?"""
    for flujo in (sys.stdout, sys.stderr):
        if flujo is None or not hasattr(flujo, "write"):
            return False
    return True


def _rotar(ruta):
    try:
        if os.path.isfile(ruta) and os.path.getsize(ruta) > MAX_BYTES:
            viejo = ruta + ".1"
            if os.path.exists(viejo):
                os.remove(viejo)
            os.replace(ruta, viejo)
    except OSError:
        pass


def preparar(carpeta_registros=None):
    """Si no hay consola (pythonw), manda `print` y los errores a `registros/consola.log`.

    Devuelve la ruta del archivo, o «» si no hacía falta (o si no se pudo abrir)."""
    if hay_consola():
        for flujo in (sys.stdout, sys.stderr):
            try:
                flujo.reconfigure(encoding="utf-8", errors="replace")
            except Exception:              # noqa: BLE001 (una salida que no se puede reconfigurar: da igual)
                pass
        return ""
    if carpeta_registros is None:
        from . import carpeta
        carpeta_registros = carpeta("registros")
    ruta = os.path.join(carpeta_registros, NOMBRE)
    _rotar(ruta)
    try:
        os.makedirs(carpeta_registros, exist_ok=True)
        archivo = open(ruta, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        sys.stdout = sys.stderr = _Sumidero()
        return ""
    sys.stdout = sys.stderr = archivo
    return ruta
