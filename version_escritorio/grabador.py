"""Grabador de ratón y teclado basado en pynput.

Los listeners de pynput corren en hilos propios: este módulo NO toca ningún
widget de Tk. Quien lo use (bot.py) debe consultar ``num_eventos`` o recibir
el callback ``al_evento`` y pasar la información al hilo de la interfaz.
"""

import math
import threading
import time

from pynput import keyboard, mouse

import acciones as ac

# Teclas reservadas por el bot: no se graban (ni al pulsar ni al soltar).
TECLAS_IGNORADAS = frozenset({"Key.f9", "Key.f10", "Key.esc"})

# Filtro de movimientos: se guarda uno si pasaron >= 15 ms o >= 3 px desde el anterior.
INTERVALO_MIN_MOVER = 0.015
DISTANCIA_MIN_MOVER = 3


class Grabador:
    def __init__(self, grabar_movimientos=True, al_evento=None):
        """
        :param grabar_movimientos: si es False, no se guardan eventos ``mover``.
        :param al_evento: callback opcional ``f(n_eventos)`` llamado desde el
            hilo del listener (no toques Tk desde ahí).
        """
        self.grabar_movimientos = grabar_movimientos
        self.al_evento = al_evento
        self._eventos = []
        self._lock = threading.Lock()
        self._t0 = 0.0
        self._ultimo_mover = None   # (t, x, y) del último movimiento guardado
        self._raton = None
        self._teclado = None
        self._grabando = False

    # -- estado --
    @property
    def grabando(self):
        return self._grabando

    @property
    def num_eventos(self):
        return len(self._eventos)

    # -- control --
    def iniciar(self):
        if self._grabando:
            return
        with self._lock:
            self._eventos = []
        self._ultimo_mover = None
        self._t0 = time.perf_counter()
        self._grabando = True
        self._raton = mouse.Listener(on_move=self._al_mover, on_click=self._al_clic,
                                     on_scroll=self._al_scroll)
        self._teclado = keyboard.Listener(on_press=self._al_presionar, on_release=self._al_soltar)
        self._raton.start()
        self._teclado.start()

    def detener(self, normalizar=True):
        """Detiene la grabación y devuelve los eventos ordenados.

        Con ``normalizar=True`` el primer evento queda en t = 0. Con False se
        conserva el tiempo medido desde que arrancaron los listeners (útil tras
        abrir una URL, para respetar el instante real de la primera acción).
        """
        self._grabando = False
        for listener in (self._raton, self._teclado):
            if listener is not None:
                listener.stop()
        self._raton = self._teclado = None
        with self._lock:
            eventos = sorted(self._eventos, key=lambda e: e["t"])  # orden estable
            self._eventos = []
        if eventos and normalizar:
            base = eventos[0]["t"]
            for ev in eventos:
                ev["t"] = round(ev["t"] - base, 4)
        return eventos

    # -- utilidades --
    def _ahora(self):
        return time.perf_counter() - self._t0

    def _agregar(self, ev):
        with self._lock:
            if not self._grabando:
                return
            self._eventos.append(ev)
            n = len(self._eventos)
        if self.al_evento is not None:
            try:
                self.al_evento(n)
            except Exception:
                pass

    # -- callbacks de pynput (hilos de los listeners) --
    def _al_mover(self, x, y, inyectado=False):
        if not self.grabar_movimientos:
            return
        t = self._ahora()
        previo = self._ultimo_mover
        if previo is not None:
            if t - previo[0] < INTERVALO_MIN_MOVER and math.hypot(x - previo[1], y - previo[2]) < DISTANCIA_MIN_MOVER:
                return
        self._ultimo_mover = (t, x, y)
        self._agregar(ac.ev_mover(round(t, 4), int(x), int(y)))

    def _al_clic(self, x, y, boton, presionado, inyectado=False):
        self._agregar(ac.ev_clic(round(self._ahora(), 4), int(x), int(y),
                                 getattr(boton, "name", str(boton)), presionado))

    def _al_scroll(self, x, y, dx, dy, inyectado=False):
        self._agregar(ac.ev_scroll(round(self._ahora(), 4), int(x), int(y), int(dx), int(dy)))

    def _registrar_tecla(self, tecla, presionada):
        if tecla is None:
            return
        nombre = ac.serializar_tecla(tecla)
        if nombre in TECLAS_IGNORADAS:
            return
        self._agregar(ac.ev_tecla(round(self._ahora(), 4), nombre, presionada, ac.vk_de_tecla(tecla)))

    def _al_presionar(self, tecla, inyectada=False):
        self._registrar_tecla(tecla, True)

    def _al_soltar(self, tecla, inyectada=False):
        self._registrar_tecla(tecla, False)
