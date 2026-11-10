"""v3.5: ventanas de Windows para ELEGIR una carpeta o un archivo (el explorador de siempre).

La interfaz es una página web y el navegador no deja saber la ruta completa de una carpeta del disco (por seguridad), así
que hasta ahora había que escribirla a mano.  Pero el servidor del bot corre en el mismo PC que el usuario: puede abrir
el explorador de Windows y devolver la ruta elegida (como hace Octopus en `octopus/utils/dialogos.py`).

- Se usa tkinter (viene con Python; nada que instalar).  El servidor atiende cada petición en su propio hilo, y Tk tiene
  que crearse, usarse y destruirse en el MISMO hilo: cada diálogo va en un hilo propio con su raíz de Tk oculta y «siempre
  encima» (si no, la ventana puede salir detrás de la del bot y parecer que el botón no hizo nada).
- Un cerrojo hace que solo haya un diálogo a la vez (un segundo clic espera a que se cierre el primero).
- Cancelar → None.  Si el PC no puede abrir ventanas → `ErrorDialogo` con un mensaje para el usuario.
- No importa playwright.  Las pruebas inyectan un elegidor falso en `Aplicacion(elegir_ruta=…)`: nunca se abre un diálogo
  de verdad.
"""

import os
import threading

TIPOS = ("carpeta", "archivo", "guardar")
TITULOS = {"carpeta": "Elegir carpeta", "archivo": "Elegir archivo", "guardar": "Elegir dónde guardar el archivo"}
MENSAJE_SIN_EXPLORADOR = "No se pudo abrir el explorador de Windows. Escribe la ruta a mano."

_cerrojo = threading.Lock()


class ErrorDialogo(RuntimeError):
    pass


def carpeta_existente(ruta):
    """La carpeta más cercana que existe (la misma, o la de un archivo, o una de sus carpetas de arriba); o ''."""
    r = os.path.abspath(os.path.expanduser(os.path.expandvars(ruta))) if ruta else ""
    while r:
        if os.path.isdir(r):
            return r
        padre = os.path.dirname(r)
        if padre == r:
            return ""
        r = padre
    return ""


def normalizar_filtros(filtros):
    """[[«Excel», «*.xlsx»], …] → [(«Excel», «*.xlsx»), …] + «Todos los archivos» al final."""
    res = []
    for f in filtros or []:
        if isinstance(f, (list, tuple)) and len(f) == 2 and all(isinstance(x, str) for x in f) and f[1].strip():
            res.append((f[0].strip()[:60] or f[1], f[1].strip()[:80]))
    if res:
        res.append(("Todos los archivos", "*.*"))
    return res


def _dialogo_tk(tipo, inicial, filtros, titulo):
    """Abre el diálogo con una raíz de Tk propia (en el hilo que lo llama) y la destruye al terminar."""
    import tkinter as tk
    from tkinter import filedialog
    raiz = tk.Tk()
    try:
        raiz.withdraw()
        raiz.attributes("-topmost", True)
        raiz.update()
        carpeta = carpeta_existente(inicial) or os.path.expanduser("~")
        archivo = os.path.basename(inicial) if inicial and not os.path.isdir(inicial) else ""
        comunes = {"parent": raiz, "title": titulo, "initialdir": carpeta}
        if tipo == "carpeta":
            r = filedialog.askdirectory(mustexist=False, **comunes)
        elif tipo == "archivo":
            r = filedialog.askopenfilename(initialfile=archivo, filetypes=filtros or [("Todos los archivos", "*.*")],
                                           **comunes)
        else:
            ext = filtros[0][1].lstrip("*") if filtros and filtros[0][1].startswith("*.") else ""
            # (sin «¿reemplazar?»: elegir un Excel que ya existe es lo normal: el bot AÑADE filas)
            r = filedialog.asksaveasfilename(initialfile=archivo, filetypes=filtros or [("Todos los archivos", "*.*")],
                                             defaultextension=ext, confirmoverwrite=False, **comunes)
    finally:
        try:
            raiz.destroy()
        except Exception:              # noqa: BLE001
            pass
    if not r or not isinstance(r, str):
        return None
    return os.path.normpath(r)


def elegir(tipo="carpeta", inicial="", filtros=None, titulo=None, abrir=None):
    """Abre el explorador de Windows y devuelve la ruta elegida (None si se cancela).  Bloquea hasta que se cierra.
    `abrir(tipo, inicial, filtros, titulo)` sustituye al diálogo de Tk (pruebas)."""
    if tipo not in TIPOS:
        raise ErrorDialogo("Tipo de diálogo desconocido: %s" % tipo)
    filtros = normalizar_filtros(filtros)
    titulo = (titulo or TITULOS[tipo])[:120]
    abrir = abrir or _dialogo_tk
    resultado = {}

    def correr():
        try:
            resultado["ruta"] = abrir(tipo, inicial or "", filtros, titulo)
        except Exception as e:         # noqa: BLE001 (sin escritorio, Tk roto…)
            resultado["error"] = e

    with _cerrojo:                      # uno a la vez
        hilo = threading.Thread(target=correr, name="dialogo-" + tipo, daemon=True)
        hilo.start()
        hilo.join()
    if "error" in resultado:
        raise ErrorDialogo("%s (%s)" % (MENSAJE_SIN_EXPLORADOR, resultado["error"]))
    return resultado.get("ruta")
