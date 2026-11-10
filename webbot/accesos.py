"""Datos de acceso por sitio («perfil de acceso»): usuario, licencia… y el nombre de la contraseña.

- Los valores que no son secretos (usuario, licencia…) se guardan en la base de datos (tabla `accesos`,
  ver `almacen.py`) por host + clave del campo.  Las contraseñas van SIEMPRE al Administrador de
  credenciales (`secretos.py`); la tabla solo guarda su nombre («host:campo»).
- `AccesosMemoria` tiene la misma interfaz que el almacén (para pruebas y para ejecutar sin base de datos).
- `PeticionAcceso`: petición del hilo de trabajo a la ventana («la página pide iniciar sesión»): el hilo
  espera al `evento`; la ventana llama a `responder()` desde el hilo principal.

No importa playwright ni tkinter.
"""

import copy
import re
import threading

from .flujo import host_de  # noqa: F401  (se reexporta para quien use este módulo)

MAX_INTENTOS_POR_SITIO = 2

MENSAJE_SIN_VENTANA = ("Falta la contraseña de «%s» (o fue rechazada). Abre el bot y ejecútalo una vez con la "
                       "ventana para guardarla.")
MENSAJE_RECHAZADA = "La contraseña fue rechazada por la página. Revisa los datos y vuelve a escribirlos."
# v3.0
TITULO_CLAVE_CAMBIO = "La contraseña de «%s» cambió: actualízala en Accesos"
MENSAJE_RECHAZADA_SIN_VENTANA = ("La página «%s» rechazó la contraseña guardada. No se volverá a probar la misma (para no "
                                 "bloquear la cuenta): actualízala en Accesos o abre el aviso «La contraseña de «%s» "
                                 "cambió».")
MENSAJE_YA_RECHAZADA = ("La contraseña guardada de «%s» ya fue rechazada el %s y no se ha cambiado: no se vuelve a enviar "
                        "(para no bloquear la cuenta). Actualízala en Accesos.")
MENSAJE_GUARDADOS = "Se guardaron los datos de acceso de «%s»"
MENSAJE_ACTUALIZADOS = "Se actualizaron los datos de acceso de «%s»"


def nombre_secreto(host, clave):
    """Nombre de la contraseña de un campo en el Administrador de credenciales: «host:campo» (como el grabador)."""
    return "%s:%s" % (host or "sitio", clave or "clave")


# --- v3.3.1: identidad de un campo y motivo de un inicio de sesión fallido -----------------------------------------

def identidad_campo(texto, host=None):
    """Clave normalizada de un campo de inicio de sesión, para reconocer el mismo campo escrito de varias formas:
    «ctl00$formContent$txtContrasenia» (name), «ctl00_formContent_txtContrasenia_I» (id del campo real de DevExpress),
    «…_I_CLND» (su «clon» visible), «#…» (selector) y «erp.ejemplo.com:ctl00$formContent$txtContrasenia» (nombre de la
    contraseña guardada) → «ctl00_formcontent_txtcontrasenia».  "" si no hay nada."""
    t = str(texto or "").strip()
    if host and t.lower().startswith(str(host).lower() + ":"):
        t = t[len(host) + 1:]
    t = t.lstrip("#").replace("\\", "")
    t = t.replace("$", "_").replace(":", "_")
    for _ in range(2):
        t = re.sub(r"_(I_CLND|CLND|I|Input|input)$", "", t)
    return t.lower()


def identidades_de_selectores(selectores):
    """Identidades de los campos a los que apuntan unos selectores (`#id`, `[id="…"]`, `[name="…"]`)."""
    res = []
    for sel in selectores or []:
        for m in re.finditer(r'^#([\w\-\\.$:]+)$|\[(?:id|name)="([^"]+)"\]', str(sel)):
            ident = identidad_campo(m.group(1) or m.group(2))
            if ident and ident not in res:
                res.append(ident)
    return res


# Mensajes de la página tras enviar el formulario: un campo obligatorio vacío NO es una contraseña rechazada.
RX_CAMPO_OBLIGATORIO = re.compile(
    r"vac[ií]o|vac[ií]a|obligatori|requerid|required|es necesari|son necesari|debe (?:ingresar|introducir|escribir|"
    r"indicar|completar|llenar)|no puede (?:estar|quedar) (?:vac|en blanco)|en blanco|complete (?:este|el|los) campo|"
    r"falta(?:n)? (?:el|la|los|las) (?:campo|dato)", re.IGNORECASE)
RX_CREDENCIAL = re.compile(
    r"contrase|clave|password|credencial|usuario o|incorrect|inv[aá]lid|invalid|no coincide|denegad|wrong|"
    r"no autorizad|unauthori|bloquead|locked", re.IGNORECASE)


def es_mensaje_obligatorio(texto):
    """True si el mensaje de la página habla de un campo obligatorio vacío («El campo LICENCIA esta vacio (es un dato
    obligatorio)»), no de datos incorrectos."""
    return bool(texto) and bool(RX_CAMPO_OBLIGATORIO.search(texto))


def tipo_de_fallo(texto):
    """«obligatorio» (falta un dato), «credencial» (la página dice que los datos no valen) o "" (no dice nada)."""
    if es_mensaje_obligatorio(texto):
        return "obligatorio"
    if texto and RX_CREDENCIAL.search(texto):
        return "credencial"
    return ""


def _sin_acentos(texto):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def palabras_de_campo(*nombres):
    """Palabras con las que una página puede nombrar un campo: su etiqueta y su id/name legible («txtLicencia» →
    «licencia»), sin acentos y en minúsculas."""
    from .flujo import etiqueta_bonita
    res = []
    for n in nombres:
        if not n:
            continue
        for t in (n, etiqueta_bonita(n) if re.search(r"[$_]|^txt|^ctl\d", str(n)) else ""):
            t = _sin_acentos(t).strip(" :*")
            t = re.sub(r"^(txt|tb|inp|input)(?=[a-z])", "", t)
            if len(t) >= 3 and t not in res:
                res.append(t)
    return res


def nombra_campo(mensaje, *nombres):
    """True si el mensaje de la página nombra el campo («El campo LICENCIA esta vacio» nombra «Licencia»)."""
    m = " " + re.sub(r"[^a-z0-9ñ]+", " ", _sin_acentos(mensaje)) + " "
    for p in palabras_de_campo(*nombres):
        p2 = re.sub(r"[^a-z0-9ñ]+", " ", p).strip()
        if p2 and (" %s " % p2) in m:
            return True
    return False


class AccesosMemoria:
    """Datos de acceso en memoria (misma interfaz que `Almacen`: accesos_de, guardar_acceso…)."""

    def __init__(self):
        self.datos = {}         # (host, clave) -> dict

    def accesos_de(self, host):
        return [copy.deepcopy(v) for (h, _), v in sorted(self.datos.items(), key=lambda kv: kv[1].get("orden", 0))
                if h == (host or "").lower()]

    def guardar_acceso(self, host, clave, etiqueta="", tipo="texto", valor=None, secreto=None, selectores=None):
        host = (host or "").lower()
        previo = self.datos.get((host, clave), {})
        self.datos[(host, clave)] = {
            "host": host, "clave": clave, "etiqueta": etiqueta or previo.get("etiqueta") or clave,
            "tipo": tipo, "valor": valor if tipo == "texto" else None,
            "secreto": secreto if tipo == "clave" else None,
            "selectores": list(selectores or previo.get("selectores") or []),
            "orden": previo.get("orden", len(self.datos))}

    def listar_accesos(self):
        return [copy.deepcopy(v) for _, v in sorted(self.datos.items())]

    def borrar_acceso(self, host, clave=None):
        host = (host or "").lower()
        for k in [k for k in self.datos if k[0] == host and (clave is None or k[1] == clave)]:
            del self.datos[k]


class PeticionAcceso:
    """Pregunta del hilo de trabajo a la ventana: «la página pide iniciar sesión».

    `solicitud` = {host, url, rechazada, mensaje, error_pagina, campos: [{clave, etiqueta, tipo, valor, requerido}]}
    `respuesta` = {"valores": {clave: valor}, "recordar": bool} o None (Cancelar)."""

    def __init__(self, solicitud):
        self.solicitud = solicitud
        self.evento = threading.Event()
        self.respuesta = None
        self.cancelada = False       # se detuvo la ejecución: la ventana ya no debe preguntar

    def responder(self, respuesta):
        if not self.evento.is_set():
            self.respuesta = respuesta
            self.evento.set()

    def cancelar(self):
        self.cancelada = True
        self.responder(None)
