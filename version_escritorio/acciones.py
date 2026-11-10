"""Modelo de acciones del Bot Copión.

Este módulo es Python puro: NO importa pynput, así que se puede probar sin
tocar el ratón ni el teclado.

Conceptos
---------
* **Evento crudo**: un diccionario ``{"tipo": ..., "t": segundos, ...}``.
  Se guardan intactos para que la reproducción sea exacta.

  - ``mover``   -> ``x, y``
  - ``clic``    -> ``x, y, boton, presionado``
  - ``scroll``  -> ``x, y, dx, dy``
  - ``tecla``   -> ``tecla, presionada`` (y opcionalmente ``vk``)
  - ``esperar`` -> ``segundos`` (añadido a mano; el tiempo ya está reflejado
    en las marcas ``t`` de los eventos siguientes)
  - ``abrir_url`` -> ``url`` (abre la página en el navegador predeterminado; la
    espera de carga queda reflejada en las marcas ``t`` de los eventos siguientes)

* **Paso**: vista legible derivada de los eventos crudos mediante
  :func:`agrupar`. Un paso abarca uno o varios eventos.

* **Nota**: texto libre del usuario. Se guarda dentro del propio evento crudo
  (clave ``"nota"`` en el primer evento del paso, o ``"nota_espera"`` en el
  evento que sigue a una pausa automática). Así las notas sobreviven a
  cualquier reagrupación y viajan en el JSON sin estructuras aparte.
"""

import enum
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime

VERSION_FORMATO = 1

# Pausas mayores a este valor (s) se muestran como un paso "Esperar N s".
UMBRAL_ESPERA = 1.0
# Distancia máxima (px) entre pulsar y soltar para considerarlo un clic.
TOLERANCIA_CLIC = 5
# Tiempo máximo (s) entre dos clics para considerarlos doble clic.
INTERVALO_DOBLE_CLIC = 0.5
# Tiempo máximo (s) entre repeticiones de una misma tecla especial para fusionarlas.
INTERVALO_REPETICION = 0.35

TIPOS_EVENTO = ("mover", "clic", "scroll", "tecla", "esperar", "abrir_url")

NOMBRES_BOTON = {"left": "izquierdo", "right": "derecho", "middle": "central"}

# Nombres en español de las teclas especiales de pynput (Key.xxx).
NOMBRES_TECLAS = {
    "enter": "Enter", "space": "Espacio", "tab": "Tab", "backspace": "Retroceso",
    "delete": "Supr", "esc": "Esc", "up": "Flecha arriba", "down": "Flecha abajo",
    "left": "Flecha izquierda", "right": "Flecha derecha", "home": "Inicio",
    "end": "Fin", "page_up": "Re Pág", "page_down": "Av Pág", "insert": "Insert",
    "caps_lock": "Bloq Mayús", "num_lock": "Bloq Num", "scroll_lock": "Bloq Despl",
    "print_screen": "Impr Pant", "pause": "Pausa", "menu": "Menú",
    "ctrl": "Ctrl", "ctrl_l": "Ctrl", "ctrl_r": "Ctrl",
    "alt": "Alt", "alt_l": "Alt", "alt_r": "Alt", "alt_gr": "AltGr",
    "shift": "Mayús", "shift_l": "Mayús", "shift_r": "Mayús",
    "cmd": "Win", "cmd_l": "Win", "cmd_r": "Win",
    "media_play_pause": "Reproducir/Pausa", "media_stop": "Detener multimedia",
    "media_volume_mute": "Silenciar", "media_volume_up": "Subir volumen",
    "media_volume_down": "Bajar volumen", "media_next": "Pista siguiente",
    "media_previous": "Pista anterior",
}

# Códigos de tecla virtual de Windows que no son letras ni dígitos.
NOMBRES_VK = {
    0x08: "Retroceso", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x20: "Espacio",
    0x21: "Re Pág", 0x22: "Av Pág", 0x23: "Fin", 0x24: "Inicio",
    0x25: "Flecha izquierda", 0x26: "Flecha arriba", 0x27: "Flecha derecha",
    0x28: "Flecha abajo", 0x2D: "Insert", 0x2E: "Supr",
    0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -", 0x6E: "Num .", 0x6F: "Num /",
    186: ";", 187: "+", 188: ",", 189: "-", 190: ".", 191: "/", 192: "`",
    219: "[", 220: "\\", 221: "]", 222: "'",
}

_FAMILIAS = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt",
    "alt_gr": "altgr",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
}
_ORDEN_FAMILIAS = ("ctrl", "alt", "altgr", "shift", "cmd")
_NOMBRE_FAMILIA = {"ctrl": "Ctrl", "alt": "Alt", "altgr": "AltGr", "shift": "Mayús", "cmd": "Win"}


# ---------------------------------------------------------------------------
# Utilidades de Windows
# ---------------------------------------------------------------------------

def activar_dpi_awareness():
    """Activa la *DPI awareness* del proceso (solo Windows).

    Debe llamarse ANTES de crear Tk o cualquier objeto de pynput, para que las
    coordenadas grabadas y reproducidas coincidan con los píxeles reales aunque
    la pantalla tenga escalado (125 %, 150 %...). Devuelve True si se activó.
    """
    if not sys.platform.startswith("win"):
        return False
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # por monitor
        return True
    except Exception:
        try:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Constructores de eventos crudos
# ---------------------------------------------------------------------------

def ev_mover(t, x, y):
    return {"tipo": "mover", "t": t, "x": x, "y": y}


def ev_clic(t, x, y, boton, presionado):
    return {"tipo": "clic", "t": t, "x": x, "y": y, "boton": boton, "presionado": bool(presionado)}


def ev_scroll(t, x, y, dx, dy):
    return {"tipo": "scroll", "t": t, "x": x, "y": y, "dx": dx, "dy": dy}


def ev_tecla(t, tecla, presionada, vk=None):
    ev = {"tipo": "tecla", "t": t, "tecla": tecla, "presionada": bool(presionada)}
    if vk is not None:
        ev["vk"] = vk
    return ev


def ev_esperar(t, segundos):
    return {"tipo": "esperar", "t": t, "segundos": segundos}


def ev_abrir_url(t, url):
    return {"tipo": "abrir_url", "t": t, "url": url}


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------

_ESQUEMA = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


def normalizar_url(texto):
    """Limpia una URL escrita por el usuario; si no tiene esquema, antepone ``https://``.

    Devuelve ``""`` si el texto está vacío. No abre nada ni usa la red.
    """
    texto = (texto or "").strip()
    if not texto:
        return ""
    if _ESQUEMA.match(texto) or texto.lower().startswith(("mailto:", "about:", "file:")):
        return texto
    return "https://" + texto.lstrip("/")


def anteponer_abrir_url(eventos, url, espera_carga):
    """Devuelve una lista nueva con ``abrir_url`` (t = 0) al principio.

    Los eventos grabados se desplazan ``espera_carga`` segundos, de modo que la
    reproducción espera lo mismo que se esperó al grabar.
    """
    url = normalizar_url(url)
    if not url:
        raise ValueError("La URL está vacía.")
    espera = max(0.0, float(espera_carga))
    nuevos = [ev_abrir_url(0.0, url)]
    for ev in eventos:
        copia = dict(ev)
        copia["t"] = round(ev["t"] + espera, 6)
        nuevos.append(copia)
    return nuevos


# ---------------------------------------------------------------------------
# Teclas: serialización y nombres
# ---------------------------------------------------------------------------

def serializar_tecla(tecla):
    """Convierte una tecla de pynput en texto (sin importar pynput).

    * ``Key.enter``            -> ``"Key.enter"``
    * ``KeyCode`` con carácter -> el carácter (``"a"``)
    * ``KeyCode`` solo con vk  -> ``"vk:65"``

    Cuando Ctrl está pulsado, Windows entrega caracteres de control (p. ej.
    ``'\\x03'`` para Ctrl+C); en ese caso se usa el código vk para poder
    recuperar la letra al mostrarla y al reproducirla.
    """
    # Teclas especiales: Key.enter, Key.ctrl_l... (enum de pynput)
    if isinstance(tecla, enum.Enum):
        return "Key." + tecla.name
    char = getattr(tecla, "char", None)
    vk = getattr(tecla, "vk", None)
    if char is not None and len(char) == 1 and char.isprintable():
        return char
    if vk is not None:
        return "vk:%d" % vk
    if char is not None:
        return char
    return "vk:0"


def vk_de_tecla(tecla):
    """Devuelve el código vk de una tecla de pynput (o None)."""
    vk = getattr(tecla, "vk", None)
    if vk is None:
        valor = getattr(tecla, "value", None)  # Key.xxx -> KeyCode
        vk = getattr(valor, "vk", None)
    return vk


def analizar_vk(texto):
    """``"vk:65"`` -> 65; cualquier otra cosa -> None."""
    if isinstance(texto, str) and texto.startswith("vk:"):
        try:
            return int(texto[3:])
        except ValueError:
            return None
    return None


def nombre_vk(vk):
    """Nombre legible de un código de tecla virtual de Windows."""
    if vk is None:
        return "?"
    if 65 <= vk <= 90:
        return chr(vk)
    if 48 <= vk <= 57:
        return chr(vk)
    if 96 <= vk <= 105:
        return "Num %d" % (vk - 96)
    if 112 <= vk <= 135:
        return "F%d" % (vk - 111)
    return NOMBRES_VK.get(vk, "Tecla %d" % vk)


def nombre_tecla(tecla, vk=None):
    """Nombre legible (en español) de una tecla serializada."""
    if tecla.startswith("Key."):
        clave = tecla[4:]
        if clave in NOMBRES_TECLAS:
            return NOMBRES_TECLAS[clave]
        if len(clave) >= 2 and clave[0] == "f" and clave[1:].isdigit():
            return clave.upper()
        return clave.replace("_", " ").capitalize()
    vk_texto = analizar_vk(tecla)
    if vk_texto is not None:
        return nombre_vk(vk_texto)
    if len(tecla) == 1:
        if tecla == " ":
            return "Espacio"
        if tecla.isprintable():
            return tecla.upper() if tecla.isalpha() else tecla
        # carácter de control (Ctrl+letra): recuperar la letra con el vk
        return nombre_vk(vk)
    return tecla


def familia_modificador(tecla):
    """'ctrl', 'alt', 'altgr', 'shift', 'cmd' o None si no es modificadora."""
    if isinstance(tecla, str) and tecla.startswith("Key."):
        return _FAMILIAS.get(tecla[4:])
    return None


def es_modificador(tecla):
    return familia_modificador(tecla) is not None


def texto_de_evento(ev):
    """Carácter que produce un evento de tecla, o None si no es "de texto"."""
    tecla = ev.get("tecla")
    if tecla == "Key.space":
        return " "
    if isinstance(tecla, str) and len(tecla) == 1 and tecla.isprintable():
        return tecla
    return None


def _clave(ev):
    """Identificador para emparejar pulsar/soltar de la misma tecla física."""
    vk = ev.get("vk")
    if vk is not None:
        return vk
    return ev["tecla"].lower()


def _fin_efectivo(ev):
    """Instante en que 'termina' un evento (los 'esperar' duran su tiempo)."""
    if ev["tipo"] == "esperar":
        return ev["t"] + ev.get("segundos", 0.0)
    return ev["t"]


def fmt_seg(valor):
    """Formatea segundos: 1.2, 12.0 ..."""
    return "%.1f" % valor


# ---------------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------------

@dataclass
class Paso:
    """Un paso legible de la lista (vista derivada de los eventos crudos)."""

    tipo: str            # clic, doble_clic, arrastre, texto, tecla, atajo, mover,
                         # scroll, esperar, espera_auto, otro
    descripcion: str
    indices: list = field(default_factory=list)   # índices de eventos crudos
    t: float = 0.0
    nota: str = ""
    hueco: float = 0.0   # solo espera_auto: duración de la pausa
    antes_de: int = -1   # solo espera_auto: índice del evento que sigue a la pausa

    @property
    def indice_nota(self):
        """Índice del evento crudo donde se guarda la nota de este paso."""
        return self.antes_de if self.tipo == "espera_auto" else self.indices[0]

    @property
    def clave_nota(self):
        return "nota_espera" if self.tipo == "espera_auto" else "nota"


def _punto(ev):
    return "(%d, %d)" % (ev["x"], ev["y"])


def _dist(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _nombre_boton(boton):
    return NOMBRES_BOTON.get(boton, "botón %s" % boton)


def _recortar(texto, maximo=50):
    return texto if len(texto) <= maximo else texto[: maximo - 1] + "…"


# --- ratón ----------------------------------------------------------------

def _buscar_suelta(eventos, i):
    """Dado un 'pulsar' en i, busca su 'soltar' saltando solo movimientos.

    Devuelve ``(j, distancia_maxima)`` o None si no hay soltar.
    """
    n = len(eventos)
    pulsar = eventos[i]
    maxima = 0.0
    j = i + 1
    while j < n:
        ev = eventos[j]
        if ev["tipo"] == "mover":
            maxima = max(maxima, _dist(ev, pulsar))
            j += 1
            continue
        if ev["tipo"] == "clic" and ev["boton"] == pulsar["boton"] and not ev["presionado"]:
            maxima = max(maxima, _dist(ev, pulsar))
            return j, maxima
        return None
    return None


def _paso_clic(eventos, i, umbral):
    pulsar = eventos[i]
    boton = pulsar["boton"]
    nb = _nombre_boton(boton)
    if not pulsar["presionado"]:
        return i, Paso("clic", "Soltar botón %s en %s" % (nb, _punto(pulsar)), [i], pulsar["t"])
    encontrado = _buscar_suelta(eventos, i)
    if encontrado is None:
        return i, Paso("clic", "Mantener botón %s en %s" % (nb, _punto(pulsar)), [i], pulsar["t"])
    j, maxima = encontrado
    soltar = eventos[j]
    if maxima > TOLERANCIA_CLIC:
        extra = "" if boton == "left" else " con botón %s" % nb
        desc = "Arrastrar%s de %s a %s" % (extra, _punto(pulsar), _punto(soltar))
        return j, Paso("arrastre", desc, list(range(i, j + 1)), pulsar["t"])
    # ¿doble clic?
    k = j + 1
    if (k < len(eventos) and eventos[k]["tipo"] == "clic" and eventos[k]["boton"] == boton
            and eventos[k]["presionado"]
            and eventos[k]["t"] - soltar["t"] <= INTERVALO_DOBLE_CLIC
            and _dist(eventos[k], pulsar) <= TOLERANCIA_CLIC):
        segundo = _buscar_suelta(eventos, k)
        if segundo is not None and segundo[1] <= TOLERANCIA_CLIC:
            j2 = segundo[0]
            desc = "Doble clic %s en %s" % (nb, _punto(pulsar))
            return j2, Paso("doble_clic", desc, list(range(i, j2 + 1)), pulsar["t"])
    return j, Paso("clic", "Clic %s en %s" % (nb, _punto(pulsar)), list(range(i, j + 1)), pulsar["t"])


def _paso_mover(eventos, i, umbral):
    j = i
    while (j + 1 < len(eventos) and eventos[j + 1]["tipo"] == "mover"
           and eventos[j + 1]["t"] - eventos[j]["t"] <= umbral):
        j += 1
    primero, ultimo = eventos[i], eventos[j]
    if j == i:
        desc = "Mover ratón a %s" % _punto(ultimo)
    else:
        desc = "Mover ratón de %s a %s (%d movimientos)" % (_punto(primero), _punto(ultimo), j - i + 1)
    return j, Paso("mover", desc, list(range(i, j + 1)), primero["t"])


def _paso_scroll(eventos, i, umbral):
    j = i
    while (j + 1 < len(eventos) and eventos[j + 1]["tipo"] == "scroll"
           and eventos[j + 1]["t"] - eventos[j]["t"] <= umbral):
        j += 1
    dx = sum(eventos[k]["dx"] for k in range(i, j + 1))
    dy = sum(eventos[k]["dy"] for k in range(i, j + 1))
    partes = []
    if dy:
        partes.append("%s %d" % ("arriba" if dy > 0 else "abajo", abs(dy)))
    if dx:
        partes.append("%s %d" % ("derecha" if dx > 0 else "izquierda", abs(dx)))
    detalle = ", ".join(partes) if partes else "sin desplazamiento"
    desc = "Rueda del ratón: %s en %s" % (detalle, _punto(eventos[j]))
    return j, Paso("scroll", desc, list(range(i, j + 1)), eventos[i]["t"])


# --- teclado --------------------------------------------------------------

def _bloque_modificadores(eventos, i, umbral):
    """Analiza un bloque 'modificador pulsado ... todos los modificadores soltados'.

    ``eventos[i]`` debe ser la pulsación de una tecla modificadora. Devuelve
    None si el bloque no termina (p. ej. hay un clic de ratón en medio, o el
    registro termina con la tecla pulsada). Si no, un diccionario con:
    ``fin`` (último índice), ``familias`` (set) y ``pulsaciones``
    (lista de ``(evento, familias_activas)`` de las teclas no modificadoras).
    """
    n = len(eventos)
    abiertos = {}        # clave -> familia (modificadores pulsados ahora)
    familias = set()
    pulsaciones = []
    pendientes = set()   # teclas normales pulsadas sin soltar aún
    k = i
    prev_t = eventos[i]["t"]
    cerrado = False
    while k < n:
        ev = eventos[k]
        if ev["tipo"] != "tecla" or ev["t"] - prev_t > umbral:
            break
        prev_t = ev["t"]
        fam = familia_modificador(ev["tecla"])
        clave = _clave(ev)
        if fam:
            if ev["presionada"]:
                abiertos[clave] = fam
                familias.add(fam)
            else:
                abiertos.pop(clave, None)
        elif ev["presionada"]:
            pulsaciones.append((ev, frozenset(abiertos.values())))
            pendientes.add(clave)
        else:
            pendientes.discard(clave)
        k += 1
        if not abiertos:
            cerrado = True
            break
    if not cerrado:
        return None
    # absorber la suelta de teclas normales que se soltaron después del modificador
    while (pendientes and k < n and eventos[k]["tipo"] == "tecla"
           and not eventos[k]["presionada"] and _clave(eventos[k]) in pendientes
           and eventos[k]["t"] - eventos[k - 1]["t"] <= umbral):
        pendientes.discard(_clave(eventos[k]))
        k += 1
    return {"fin": k - 1, "familias": familias, "pulsaciones": pulsaciones}


def _bloque_es_texto(bloque):
    """True si el bloque es escritura normal (Mayús, AltGr...) y no un atajo."""
    if not bloque["pulsaciones"]:
        return False
    familias = bloque["familias"]
    if familias - {"shift", "altgr", "ctrl"}:
        return False
    if "ctrl" in familias and "altgr" not in familias:
        return False  # Ctrl+tecla es un atajo (AltGr se reporta como Ctrl+Alt Gr)
    return all(texto_de_evento(ev) is not None for ev, _ in bloque["pulsaciones"])


def _nombres_familias(familias):
    return "+".join(_NOMBRE_FAMILIA[f] for f in _ORDEN_FAMILIAS if f in familias)


def _paso_texto(eventos, i, umbral):
    """Agrupa teclas de carácter seguidas. Devuelve (último_índice, texto)."""
    n = len(eventos)
    k = i
    ultimo = i - 1
    texto = []
    prev_t = eventos[i]["t"]
    while k < n:
        ev = eventos[k]
        if ev["tipo"] != "tecla" or ev["t"] - prev_t > umbral:
            break
        car = texto_de_evento(ev)
        if car is not None:
            if ev["presionada"]:
                texto.append(car)
            ultimo = k
            prev_t = ev["t"]
            k += 1
            continue
        if es_modificador(ev["tecla"]) and ev["presionada"]:
            bloque = _bloque_modificadores(eventos, k, umbral)
            if bloque is not None and _bloque_es_texto(bloque):
                texto.extend(texto_de_evento(e) for e, _ in bloque["pulsaciones"])
                ultimo = bloque["fin"]
                prev_t = eventos[ultimo]["t"]
                k = ultimo + 1
                continue
        break
    return ultimo, "".join(texto)


def _paso_tecla_especial(eventos, i):
    """Tecla no modificadora ni de texto (Enter, Tab, F5...). Fusiona repeticiones."""
    n = len(eventos)
    clave = _clave(eventos[i])
    nombre = nombre_tecla(eventos[i]["tecla"], eventos[i].get("vk"))

    def es(k, presionada):
        return (k < n and eventos[k]["tipo"] == "tecla" and eventos[k]["presionada"] == presionada
                and _clave(eventos[k]) == clave)

    veces = 0
    j = i            # índice de la pulsación actual
    fin = i
    liberada = False
    while True:
        veces += 1
        k = j + 1
        while es(k, True) and eventos[k]["t"] - eventos[k - 1]["t"] <= INTERVALO_REPETICION:
            veces += 1     # autorrepetición al mantener la tecla
            k += 1
        if es(k, False):
            fin = k
            liberada = True
            k += 1
            if es(k, True) and eventos[k]["t"] - eventos[k - 1]["t"] <= INTERVALO_REPETICION:
                j = k
                continue
        else:
            fin = k - 1
            liberada = False
        break
    sufijo = " ×%d" % veces if veces > 1 else ""
    if liberada:
        desc = "Tecla %s%s" % (nombre, sufijo)
    else:
        desc = "Presionar tecla %s%s" % (nombre, sufijo)
    return fin, Paso("tecla", desc, list(range(i, fin + 1)), eventos[i]["t"])


def _paso_tecla(eventos, i, umbral):
    ev = eventos[i]
    tecla = ev["tecla"]
    nombre = nombre_tecla(tecla, ev.get("vk"))
    if not ev["presionada"]:
        return i, Paso("tecla", "Soltar tecla %s" % nombre, [i], ev["t"])

    if es_modificador(tecla):
        bloque = _bloque_modificadores(eventos, i, umbral)
        if bloque is None:
            return i, Paso("tecla", "Presionar tecla %s" % nombre, [i], ev["t"])
        fin = bloque["fin"]
        if not bloque["pulsaciones"]:
            desc = "Tecla %s" % _nombres_familias(bloque["familias"])
            return fin, Paso("tecla", desc, list(range(i, fin + 1)), ev["t"])
        if _bloque_es_texto(bloque):
            return _paso_de_texto(eventos, i, umbral)
        combos = []
        for e, activas in bloque["pulsaciones"]:
            partes = [_NOMBRE_FAMILIA[f] for f in _ORDEN_FAMILIAS if f in activas]
            partes.append(nombre_tecla(e["tecla"], e.get("vk")))
            combos.append("+".join(partes))
        desc = "Atajo " + ", ".join(combos)
        return fin, Paso("atajo", desc, list(range(i, fin + 1)), ev["t"])

    if texto_de_evento(ev) is not None:
        return _paso_de_texto(eventos, i, umbral)
    return _paso_tecla_especial(eventos, i)


def _paso_de_texto(eventos, i, umbral):
    ultimo, texto = _paso_texto(eventos, i, umbral)
    if ultimo < i:  # no debería ocurrir; evita bucles infinitos
        ultimo, texto = i, texto_de_evento(eventos[i]) or ""
    desc = "Escribir '%s'" % _recortar(texto)
    return ultimo, Paso("texto", desc, list(range(i, ultimo + 1)), eventos[i]["t"])


# --- agrupación general ---------------------------------------------------

def _paso_en(eventos, i, umbral):
    ev = eventos[i]
    tipo = ev["tipo"]
    if tipo == "mover":
        return _paso_mover(eventos, i, umbral)
    if tipo == "clic":
        return _paso_clic(eventos, i, umbral)
    if tipo == "scroll":
        return _paso_scroll(eventos, i, umbral)
    if tipo == "tecla":
        return _paso_tecla(eventos, i, umbral)
    if tipo == "esperar":
        return i, Paso("esperar", "Esperar %s s" % fmt_seg(ev.get("segundos", 0.0)), [i], ev["t"])
    if tipo == "abrir_url":
        return i, Paso("abrir_url", "Abrir URL %s" % _recortar(ev.get("url", ""), 90), [i], ev["t"])
    return i, Paso("otro", "Evento desconocido (%s)" % tipo, [i], ev.get("t", 0.0))


def agrupar(eventos, umbral_espera=UMBRAL_ESPERA):
    """Convierte eventos crudos en una lista de :class:`Paso` legibles.

    Los eventos NO se modifican. Las notas se leen de los propios eventos.
    """
    pasos = []
    n = len(eventos)
    i = 0
    fin_previo = None
    while i < n:
        ev = eventos[i]
        if fin_previo is not None and ev["t"] - fin_previo > umbral_espera:
            hueco = ev["t"] - fin_previo
            pasos.append(Paso("espera_auto", "Esperar %s s" % fmt_seg(hueco), [], fin_previo,
                              nota=ev.get("nota_espera", ""), hueco=hueco, antes_de=i))
        fin, paso = _paso_en(eventos, i, umbral_espera)
        paso.nota = eventos[i].get("nota", "")
        pasos.append(paso)
        fin_previo = _fin_efectivo(eventos[fin])
        i = fin + 1
    return pasos


# ---------------------------------------------------------------------------
# Grabación (eventos + operaciones de edición + JSON)
# ---------------------------------------------------------------------------

class Grabacion:
    """Lista de eventos crudos con operaciones de edición y persistencia."""

    def __init__(self, eventos=None):
        self.eventos = list(eventos) if eventos else []

    # -- consulta --
    def __len__(self):
        return len(self.eventos)

    @property
    def duracion(self):
        return _fin_efectivo(self.eventos[-1]) if self.eventos else 0.0

    def pasos(self, umbral_espera=UMBRAL_ESPERA):
        return agrupar(self.eventos, umbral_espera)

    # -- edición --
    def poner_nota(self, paso, texto):
        """Guarda (o borra, si está vacía) la nota de un paso."""
        ev = self.eventos[paso.indice_nota]
        texto = (texto or "").strip()
        if texto:
            ev[paso.clave_nota] = texto
        else:
            ev.pop(paso.clave_nota, None)
        paso.nota = texto

    def eliminar_pasos(self, pasos):
        """Elimina los eventos crudos de los pasos dados.

        El tiempo que ocupaban se descuenta de los eventos posteriores para no
        dejar huecos artificiales. Devuelve cuántos eventos se quitaron.
        """
        n = len(self.eventos)
        quitar = set()
        delta = [0.0] * (n + 2)
        for p in pasos:
            if p.tipo == "espera_auto":
                delta[p.antes_de] += p.hueco
                continue
            quitar.update(p.indices)
            a, b = min(p.indices), max(p.indices)
            delta[b + 1] += _fin_efectivo(self.eventos[b]) - self.eventos[a]["t"]
        nuevos = []
        acumulado = 0.0
        for k, ev in enumerate(self.eventos):
            acumulado += delta[k]
            if k in quitar:
                continue
            copia = dict(ev)
            copia["t"] = round(max(0.0, ev["t"] - acumulado), 6)
            nuevos.append(copia)
        # garantiza orden no decreciente tras restar
        for k in range(1, len(nuevos)):
            if nuevos[k]["t"] < nuevos[k - 1]["t"]:
                nuevos[k]["t"] = nuevos[k - 1]["t"]
        quitados = n - len(nuevos)
        self.eventos = nuevos
        return quitados

    def insertar_espera(self, segundos, posicion=None):
        """Inserta una espera manual antes del evento ``posicion`` (por defecto, al final).

        Los eventos posteriores se desplazan ``segundos`` en el tiempo.
        Devuelve el índice del evento nuevo.
        """
        if segundos <= 0:
            raise ValueError("La espera debe ser mayor que 0 segundos.")
        n = len(self.eventos)
        pos = n if posicion is None else max(0, min(posicion, n))
        t = _fin_efectivo(self.eventos[pos - 1]) if pos > 0 else 0.0
        for ev in self.eventos[pos:]:
            ev["t"] = round(ev["t"] + segundos, 6)
        self.eventos.insert(pos, ev_esperar(round(t, 6), segundos))
        return pos

    def insertar_espera_despues_de(self, paso, segundos):
        """Inserta una espera justo después del paso (o al principio si es None)."""
        if paso is None:
            return self.insertar_espera(segundos, 0 if not self.eventos else None)
        if paso.tipo == "espera_auto":
            pos = paso.antes_de
            # la nueva espera va tras la pausa: arranca en el instante del evento siguiente
            t = self.eventos[pos]["t"]
            for ev in self.eventos[pos:]:
                ev["t"] = round(ev["t"] + segundos, 6)
            self.eventos.insert(pos, ev_esperar(t, segundos))
            return pos
        return self.insertar_espera(segundos, max(paso.indices) + 1)

    def insertar_abrir_url_despues_de(self, paso, url, espera_carga=0.0):
        """Inserta un paso "Abrir URL" tras ``paso`` (o al final si es None).

        Los eventos posteriores se desplazan ``espera_carga`` segundos para que la
        página tenga tiempo de cargar. Devuelve el índice del evento nuevo.
        """
        url = normalizar_url(url)
        if not url:
            raise ValueError("La URL está vacía.")
        espera = max(0.0, float(espera_carga))
        if paso is None:
            pos = len(self.eventos)
            t = _fin_efectivo(self.eventos[-1]) if self.eventos else 0.0
        elif paso.tipo == "espera_auto":
            pos = paso.antes_de
            t = self.eventos[pos]["t"]
        else:
            pos = max(paso.indices) + 1
            t = _fin_efectivo(self.eventos[pos - 1])
        for ev in self.eventos[pos:]:
            ev["t"] = round(ev["t"] + espera, 6)
        self.eventos.insert(pos, ev_abrir_url(round(t, 6), url))
        return pos

    def indice_primera_url(self):
        """Índice del primer evento ``abrir_url`` o None."""
        for k, ev in enumerate(self.eventos):
            if ev["tipo"] == "abrir_url":
                return k
        return None

    # -- JSON --
    def a_dict(self):
        return {
            "version": VERSION_FORMATO,
            "creado": datetime.now().isoformat(timespec="seconds"),
            "eventos": self.eventos,
        }

    @classmethod
    def desde_dict(cls, datos):
        if not isinstance(datos, dict) or "eventos" not in datos:
            raise ValueError("El archivo no tiene el formato de una grabación del bot.")
        version = datos.get("version", 1)
        if not isinstance(version, int) or version > VERSION_FORMATO:
            raise ValueError("Versión de formato no soportada: %r" % (version,))
        eventos = datos["eventos"]
        if not isinstance(eventos, list):
            raise ValueError("La lista de eventos no es válida.")
        for k, ev in enumerate(eventos):
            if not isinstance(ev, dict) or ev.get("tipo") not in TIPOS_EVENTO:
                raise ValueError("Evento %d con tipo desconocido." % k)
            if not isinstance(ev.get("t"), (int, float)):
                raise ValueError("Evento %d sin marca de tiempo válida." % k)
            if ev["tipo"] == "abrir_url" and not isinstance(ev.get("url"), str):
                raise ValueError("Evento %d (abrir_url) sin URL válida." % k)
        return cls(eventos)

    def guardar(self, ruta):
        """Guarda en JSON de forma atómica (archivo temporal + reemplazo)."""
        carpeta = os.path.dirname(os.path.abspath(ruta))
        os.makedirs(carpeta, exist_ok=True)
        temporal = ruta + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(self.a_dict(), f, ensure_ascii=False, indent=1)
        os.replace(temporal, ruta)

    @classmethod
    def cargar(cls, ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            try:
                datos = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError("El archivo no es un JSON válido: %s" % e)
        return cls.desde_dict(datos)
