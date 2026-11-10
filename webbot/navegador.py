"""Apertura del navegador (Chrome o Edge ya instalados) con un perfil persistente.

Importante: los objetos de la API síncrona de Playwright solo se pueden usar desde el
hilo que los creó.  Quien llame a `abrir_contexto` debe seguir usando el contexto
(y sus páginas) en ese mismo hilo.

v3.7 (instalador): si el navegador elegido no está instalado en este equipo (p. ej. un PC sin Chrome), se usa el otro
(Edge) con una línea en el registro, y se recuerda para el resto del proceso.
"""

import os

NAVEGADORES = {"chrome": "Chrome", "msedge": "Edge"}
OTRO = {"chrome": "msedge", "msedge": "chrome"}
EJECUTABLES = {"chrome": ("Google", "Chrome", "chrome.exe"), "msedge": ("Microsoft", "Edge", "msedge.exe")}

_sustituto = {}        # {"chrome": "msedge"} cuando se vio que Chrome no está instalado


class ErrorNavegador(RuntimeError):
    pass


def buscar_ejecutable(navegador):
    """Ruta de chrome.exe / msedge.exe en este equipo (Archivos de programa, AppData\\Local o «App Paths» del
    registro), o None."""
    empresa, producto, exe = EJECUTABLES[navegador]
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            ruta = os.path.join(base, empresa, producto, "Application", exe)
            if os.path.isfile(ruta):
                return ruta
    try:
        import winreg
    except ImportError:            # (no es Windows)
        return None
    clave = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s" % exe
    for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for vista in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(raiz, clave, 0, winreg.KEY_READ | vista) as k:
                    ruta = os.path.expandvars(str(winreg.QueryValue(k, None) or "").strip('"'))
            except OSError:
                continue
            if ruta and os.path.isfile(ruta):
                return ruta
    return None


def falta_navegador(error):
    """True si el error de Playwright dice que ese navegador no está instalado («Chromium distribution 'chrome' is
    not found at …»)."""
    texto = str(error).lower()
    return "is not found at" in texto or ("distribution" in texto and "not found" in texto)


def _con_respaldo(lanzar, navegador, log=None):
    """Llama a `lanzar(canal)`; si el navegador no está instalado, prueba con el otro.  Devuelve (resultado, canal)."""
    canal = _sustituto.get(navegador, navegador)
    try:
        return lanzar(canal), canal
    except Exception as e:
        if not falta_navegador(e):
            raise
        otro = OTRO[canal]
        _sustituto[navegador] = otro
        try:
            (log or print)("%s no está instalado en este equipo: se usa %s." % (NAVEGADORES[canal], NAVEGADORES[otro]))
        except Exception:          # noqa: BLE001 (sin consola: pythonw)
            pass
        try:
            return lanzar(otro), otro
        except Exception as e2:
            if falta_navegador(e2):
                _sustituto.pop(navegador, None)
                raise ErrorNavegador("No se encontró Chrome ni Edge en este equipo. Instala uno de los dos "
                                     "(Edge viene con Windows).") from e
            raise


def canal_efectivo(navegador):
    """El canal que se usa de verdad para `navegador` (el otro si ya se vio que este no está instalado)."""
    return _sustituto.get(navegador, navegador)


def lanzar(playwright, navegador="chrome", log=None, **opciones):
    """`playwright.chromium.launch(channel=…)` con el mismo respaldo Chrome ↔ Edge."""
    if navegador not in NAVEGADORES:
        raise ErrorNavegador("Navegador no válido: %s (usa chrome o msedge)" % navegador)
    return _con_respaldo(lambda canal: playwright.chromium.launch(channel=canal, **opciones), navegador, log)[0]


def abrir_contexto(playwright, carpeta_perfil, navegador="chrome", oculto=False, lento_ms=0, log=None):
    """Abre un contexto persistente (cookies y sesión se conservan en `carpeta_perfil`)."""
    if navegador not in NAVEGADORES:
        raise ErrorNavegador("Navegador no válido: %s (usa chrome o msedge)" % navegador)
    os.makedirs(carpeta_perfil, exist_ok=True)
    opciones = dict(
        headless=bool(oculto),
        accept_downloads=True,
        slow_mo=lento_ms or 0,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
        locale="es-ES",
    )
    if oculto:
        opciones["viewport"] = {"width": 1366, "height": 850}
    else:
        opciones["no_viewport"] = True
        opciones["args"].append("--start-maximized")
    try:
        return _con_respaldo(
            lambda c: playwright.chromium.launch_persistent_context(carpeta_perfil, channel=c, **opciones),
            navegador, log)[0]
    except ErrorNavegador:
        raise
    except Exception as e:
        msg = str(e).splitlines()[0] if str(e) else type(e).__name__
        raise ErrorNavegador(
            "No se pudo abrir %s: %s. Comprueba que está instalado y que no hay otra ventana del bot "
            "usando el mismo perfil (%s)." % (NAVEGADORES[canal_efectivo(navegador)], msg, carpeta_perfil)) from e
