"""Reproductor fiel de grabaciones (ratón y teclado) basado en pynput.

Corre en un hilo propio para no congelar la ventana. Los callbacks
(``al_paso``, ``al_cuenta``, ``al_fin``) se llaman desde ese hilo: quien los
use (bot.py) debe pasarlos al hilo de Tk con una cola / ``root.after``.
"""

import sys
import threading
import time

from pynput import keyboard, mouse

import acciones as ac

# Pausa (s) entre una repetición y la siguiente.
PAUSA_ENTRE_REPETICIONES = 0.5


class Abortado(Exception):
    """Se lanza internamente para cortar la reproducción."""


def deserializar_tecla(texto, vk=None):
    """Convierte el texto guardado en una tecla de pynput (o None si no se reconoce).

    * ``"Key.enter"`` -> ``Key.enter``
    * ``"vk:67"``     -> ``KeyCode.from_vk(67)``
    * ``"a"``         -> ``KeyCode`` de esa letra, o por su ``vk`` si se grabó
      (más fiel: respeta Ctrl+letra, teclado numérico, distribuciones, etc.).
    """
    if texto.startswith("Key."):
        return getattr(keyboard.Key, texto[4:], None)
    if vk is None:
        vk = ac.analizar_vk(texto)
    if vk is not None:
        return keyboard.KeyCode.from_vk(vk)
    if len(texto) == 1:
        return keyboard.KeyCode.from_char(texto)
    return None


def _identificador(tecla):
    """Clave estable para recordar qué teclas están pulsadas."""
    if isinstance(tecla, keyboard.Key):
        return ("key", tecla.name)
    vk = getattr(tecla, "vk", None)
    if vk is not None:
        return ("vk", vk)
    return ("char", getattr(tecla, "char", None))


class _Tiempo:
    """Resolución de reloj de 1 ms en Windows mientras se reproduce."""

    def __enter__(self):
        self._activo = False
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.winmm.timeBeginPeriod(1)
                self._activo = True
            except Exception:
                pass
        return self

    def __exit__(self, *args):
        if self._activo:
            try:
                import ctypes
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass


class Reproductor:
    def __init__(self, al_paso=None, al_cuenta=None, al_fin=None, raton=None, teclado=None,
                 abridor=None):
        """
        :param al_paso: ``f(indice_paso, repeticion, total_repeticiones)`` al empezar cada paso.
        :param al_cuenta: ``f(segundos_restantes)`` durante la cuenta regresiva (0 = empieza).
        :param al_fin: ``f(resultado, mensaje)``; resultado: ``"completado"``,
            ``"abortado"``, ``"vacio"`` o ``"error"``.
        :param raton, teclado: controladores (por defecto los de pynput); se
            pueden inyectar falsos para probar sin mover nada.
        :param abridor: función ``f(url)`` que abre una URL (por defecto
            ``webbrowser.open``); se inyecta uno falso en las pruebas.
        """
        self.al_paso = al_paso
        self.al_cuenta = al_cuenta
        self.al_fin = al_fin
        self._raton = raton
        self._teclado = teclado
        self._abridor = abridor
        self._url_previa = None
        self._espera_carga = 0.0
        self._abortar = threading.Event()
        self._hilo = None
        self._teclas = {}        # identificador -> tecla pulsada por nosotros
        self._botones = {}       # nombre -> Button pulsado por nosotros
        self._esquina_esperada = False
        self.motivo_abortar = ""

    # -- estado / control --
    @property
    def en_ejecucion(self):
        return self._hilo is not None and self._hilo.is_alive()

    def iniciar(self, eventos, pasos=None, velocidad=1.0, repeticiones=1, cuenta=3,
                url=None, espera_carga=5.0):
        """Arranca la reproducción en un hilo. ``pasos`` (de ``acciones.agrupar``)
        sirve solo para avisar del paso en curso.

        ``url``: dirección escrita en el campo URL. Si la grabación tiene un
        evento ``abrir_url``, el PRIMERO usa esta dirección en lugar de la
        grabada. Si no lo tiene, se abre ``url`` al principio de cada pasada y
        se esperan ``espera_carga`` segundos antes de los eventos grabados.
        """
        if self.en_ejecucion:
            return False
        eventos = [dict(e) for e in eventos]
        url = ac.normalizar_url(url)
        self._url_previa = None
        self._espera_carga = max(0.0, float(espera_carga))
        if url:
            for ev in eventos:
                if ev["tipo"] == "abrir_url":
                    ev["url"] = url
                    break
            else:
                self._url_previa = url
        self._abortar.clear()
        self.motivo_abortar = ""
        self._hilo = threading.Thread(
            target=self._ejecutar, name="reproductor", daemon=True,
            args=(eventos, list(pasos or []), max(0.05, float(velocidad)),
                  max(1, int(repeticiones)), max(0, int(cuenta))))
        self._hilo.start()
        return True

    def abortar(self, motivo=""):
        if motivo and not self.motivo_abortar:
            self.motivo_abortar = motivo
        self._abortar.set()

    def esperar(self, timeout=None):
        if self._hilo is not None:
            self._hilo.join(timeout)

    # -- hilo --
    def _ejecutar(self, eventos, pasos, velocidad, repeticiones, cuenta):
        resultado, mensaje = "completado", ""
        with _Tiempo():
            try:
                if self._raton is None:
                    self._raton = mouse.Controller()
                if self._teclado is None:
                    self._teclado = keyboard.Controller()
                if not eventos:
                    resultado, mensaje = "vacio", "No hay acciones que reproducir."
                else:
                    self._cuenta_regresiva(cuenta)
                    for rep in range(1, repeticiones + 1):
                        self._pasada(eventos, pasos, velocidad, rep, repeticiones)
                        if rep < repeticiones:
                            self._dormir_hasta(time.perf_counter() + PAUSA_ENTRE_REPETICIONES)
            except Abortado:
                resultado, mensaje = "abortado", self.motivo_abortar
            except Exception as e:  # cualquier fallo inesperado
                resultado, mensaje = "error", "%s: %s" % (type(e).__name__, e)
            finally:
                self._soltar_todo()
        self._avisar(self.al_fin, resultado, mensaje)

    def _avisar(self, callback, *args):
        if callback is not None:
            try:
                callback(*args)
            except Exception:
                pass

    def _cuenta_regresiva(self, cuenta):
        for restante in range(cuenta, 0, -1):
            self._avisar(self.al_cuenta, restante)
            self._dormir_hasta(time.perf_counter() + 1.0)
        self._avisar(self.al_cuenta, 0)

    def _pasada(self, eventos, pasos, velocidad, rep, total):
        paso_de_evento = {}
        espera_antes = {}
        for i, p in enumerate(pasos):
            if p.tipo == "espera_auto":
                espera_antes[p.antes_de] = i
            else:
                for k in p.indices:
                    paso_de_evento[k] = i
        actual = None
        if self._url_previa:
            self._abrir_url(self._url_previa)
            self._dormir_hasta(time.perf_counter() + self._espera_carga)
        inicio = time.perf_counter()
        for k, ev in enumerate(eventos):
            self._comprobar()
            if k in espera_antes:
                self._avisar(self.al_paso, espera_antes[k], rep, total)
                actual = None
            self._dormir_hasta(inicio + ev["t"] / velocidad)
            p = paso_de_evento.get(k)
            if p is not None and p != actual:
                actual = p
                self._avisar(self.al_paso, p, rep, total)
            self._ejecutar_evento(ev)

    # -- tiempo y seguridad --
    def _comprobar(self):
        """Lanza Abortado si se pidió abortar o el ratón está en la esquina (failsafe)."""
        if self._abortar.is_set():
            raise Abortado()
        try:
            x, y = self._raton.position
        except Exception:
            return
        if x <= 1 and y <= 1 and not self._esquina_esperada:
            self.abortar("Ratón en la esquina superior izquierda")
            raise Abortado()

    def _dormir_hasta(self, objetivo):
        while True:
            self._comprobar()
            resto = objetivo - time.perf_counter()
            if resto <= 0:
                return
            if resto > 0.002:
                time.sleep(min(resto - 0.001, 0.01))

    # -- ejecución de eventos --
    def _abrir_url(self, url):
        if not url:
            return
        if self._abridor is None:
            import webbrowser
            self._abridor = webbrowser.open
        self._abridor(url)

    def _poner_posicion(self, x, y):
        self._esquina_esperada = x <= 1 and y <= 1
        self._raton.position = (x, y)

    def _ejecutar_evento(self, ev):
        tipo = ev["tipo"]
        if tipo == "mover":
            self._poner_posicion(ev["x"], ev["y"])
        elif tipo == "clic":
            self._poner_posicion(ev["x"], ev["y"])
            boton = getattr(mouse.Button, ev["boton"], None)
            if boton is None:
                return
            if ev["presionado"]:
                self._raton.press(boton)
                self._botones[ev["boton"]] = boton
            else:
                self._raton.release(boton)
                self._botones.pop(ev["boton"], None)
        elif tipo == "scroll":
            self._poner_posicion(ev["x"], ev["y"])
            self._raton.scroll(ev.get("dx", 0), ev.get("dy", 0))
        elif tipo == "tecla":
            tecla = deserializar_tecla(ev["tecla"], ev.get("vk"))
            if tecla is None:
                return
            ident = _identificador(tecla)
            if ev["presionada"]:
                self._teclado.press(tecla)
                self._teclas[ident] = tecla
            else:
                self._teclado.release(tecla)
                self._teclas.pop(ident, None)
        elif tipo == "abrir_url":
            self._abrir_url(ac.normalizar_url(ev.get("url", "")))
        # "esperar": el tiempo ya está reflejado en las marcas t; no hay nada que hacer

    def _soltar_todo(self):
        """Suelta teclas y botones que hayan quedado pulsados (al terminar o abortar)."""
        for tecla in reversed(list(self._teclas.values())):
            try:
                self._teclado.release(tecla)
            except Exception:
                pass
        self._teclas.clear()
        for boton in list(self._botones.values()):
            try:
                self._raton.release(boton)
            except Exception:
                pass
        self._botones.clear()
