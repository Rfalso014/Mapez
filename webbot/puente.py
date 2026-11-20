"""Puente de errores entre equipos (v4.0): los fallos de varios equipos llegan al equipo central.

El usuario tiene el bot en varias computadoras de la MISMA red local y quiere ver en una sola («la principal») lo que
falla en las demás.  Aquí está todo lo del puente:

- En el equipo central: `Receptor` (un servidor HTTP propio, aparte del de la interfaz) que SOLO entiende
  `POST /api/errores` y `GET /api/errores/salud`.  Cualquier otra ruta o método responde 404: por este puente no se
  pueden ejecutar reportes, ni leer archivos, ni consultar nada.
- En los demás equipos: `anotar_fallo()` mete el fallo en la cola de la base de datos (tabla `errores_salida`) y
  `vaciar_cola()` lo manda cuando se puede.  Si el equipo central está apagado, el fallo se queda en la cola y se
  manda más tarde; cada fallo lleva un `uuid`, y la bandeja del central tiene ese `uuid` como único, así que un
  reenvío NO crea una entrada repetida.

Seguridad (a propósito, y vale la pena leerlo):

- Recibir está APAGADO de fábrica.  Mientras está apagado no se abre ningún puerto a la red.
- Al encenderlo NO se escucha en 0.0.0.0 (todas las tarjetas de red): se escucha en UNA dirección privada de este
  equipo (192.168.x.x, 10.x.x.x o 172.16–31.x.x).  Si el equipo no tiene ninguna dirección privada, no se enciende y
  se dice por qué.  Además, se rechaza toda peticíón que no venga de una dirección privada o del propio equipo.
- Hace falta la CLAVE del equipo central en la cabecera `X-Bot-Clave` (se compara con `hmac.compare_digest`).  Sin
  clave o con otra clave, la respuesta es 401 y una línea escueta; lo que se rechaza se apunta en la consola con la
  dirección y el motivo, NUNCA con la clave (ni la buena ni la que mandaron).
- Tamaño: como mucho `MAX_CUERPO` (64 KB) por fallo; más grande = 413 y no se lee.  La bandeja guarda como mucho
  `almacen.MAX_ERRORES_RECIBIDOS` y la cola de salida `almacen.MAX_ERRORES_COLA` (se tiran los más viejos).
- Las claves se guardan en `meta` (`almacen.clave`/`guardar_clave`), NO en los ajustes, para que no salgan por
  `/api/ajustes` ni en una copia de los ajustes.

Qué se manda (y qué NO).  Se manda: el nombre del equipo que el usuario escribió, el nombre del reporte, la fecha y
hora, el paso que falló, el mensaje del error, la versión del bot y el FINAL del registro de esa ejecución
(`MAX_REGISTRO` caracteres).  NO se manda nunca: contraseñas (las del registro ya salen como «********»), el
Administrador de credenciales, las cookies o el perfil del navegador (no se leen), ni los archivos descargados.
Además `ocultar()` tacha del texto, por si acaso:

  1. los datos de acceso de un paso «Iniciar sesión» (ahí va el USUARIO);
  2. el texto de los pasos «Escribir» (puede ser el usuario o un dato personal);
  3. todo lo que venga detrás de «usuario», «user», «contraseña», «password», «clave», «token», «cookie»,
     «authorization», «bearer», «api-key» o «secreto»;
  4. las direcciones de correo;
  5. los parámetros de las direcciones web (`?...`), que suelen llevar identificadores y permisos;
  6. el nombre de la cuenta de Windows en las rutas (`C:\\Users\\Pepe` → `C:\\Users\\(usuario)`);
  7. los números largos (6 cifras o más): se deja solo el final, como en «••••1234» (números de comercio o de cuenta).

No importa playwright ni tkinter.
"""

import datetime
import hmac
import http.server
import ipaddress
import json
import os
import re
import socket
import socketserver
import threading
import time
import urllib.error
import urllib.request
import uuid as mod_uuid

from . import VERSION

PUERTO_DEFECTO = 8765
RUTA = "/api/errores"
RUTA_SALUD = "/api/errores/salud"
MAX_CUERPO = 64 * 1024            # por fallo
MAX_REGISTRO = 8000               # caracteres del final del registro que se mandan
ESPERA_ENVIO = 6.0                # segundos de espera al mandar
CADA = 120.0                      # cada cuánto reintenta la cola el hilo de reenvío


class ErrorPuente(Exception):
    """No se pudo encender el receptor o mandar un fallo (el mensaje ya está en español, para el usuario)."""


# ============================================================== limpiar el texto
_TACHA = "(oculto)"
_RX = [
    # 1. «Iniciar sesión en «Portal» (si hace falta) — Usuario: «pepe»; contraseña «clave»»  → se quita el detalle
    (re.compile(r"(Iniciar sesi[óo]n en .{0,80}?\(si hace falta\))\s+—.*", re.IGNORECASE), r"\1 — (datos de acceso ocultos)"),
    # 2. el texto de los pasos «Escribir»
    (re.compile(r"(Escribir)\s+«[^»]*»"), r"\1 «%s»" % _TACHA),
    # 3. «usuario: pepe», «token=abc», «Cookie: x=y»…
    (re.compile(r"\b(usuarios?|user(?:name)?|login|contrase[ñn]as?|password|passwd|clave|claves|token|cookies?|"
                r"authorization|bearer|api[-_]?key|secreto|secret)\b\s*[:=]\s*\S+", re.IGNORECASE),
     lambda m: "%s: %s" % (m.group(1), _TACHA)),
    # 4. direcciones de correo
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "(correo oculto)"),
    # 5. los parámetros de una dirección web
    (re.compile(r"(https?://[^\s«»]+?)\?[^\s«»]*"), r"\1?(parámetros ocultos)"),
    # 6. la cuenta de Windows en las rutas
    (re.compile(r"([A-Za-z]:\\+Users\\+)[^\\\s«»]+", re.IGNORECASE), r"\1(usuario)"),
]
_RX_NUMERO = re.compile(r"\d{6,}")


def ocultar(texto):
    """Tacha del texto lo que no debe salir de este equipo (ver la cabecera del módulo)."""
    t = str(texto or "")
    for rx, con in _RX:
        t = rx.sub(con, t)
    return _RX_NUMERO.sub(lambda m: "••••" + m.group(0)[-4:], t)


def final_del_registro(ruta_o_texto, maximo=MAX_REGISTRO):
    """El FINAL del registro (donde está el fallo), ya limpio.  Acepta la ruta del archivo o el texto."""
    texto = ruta_o_texto or ""
    if texto and os.path.sep in texto and os.path.isfile(texto):
        try:
            with open(texto, encoding="utf-8", errors="replace") as f:
                texto = f.read()
        except OSError:
            texto = ""
    if len(texto) > maximo:
        texto = "(…solo el final del registro…)\n" + texto[-maximo:]
    return ocultar(texto)


def paso_del_mensaje(mensaje):
    """«Error en el paso 3: No apareció …» → «paso 3».  Si no se puede saber, «»."""
    m = re.search(r"paso\s+(\d+)", str(mensaje or ""), re.IGNORECASE)
    return ("paso %s" % m.group(1)) if m else ""


def armar(equipo, reporte, mensaje, registro="", cuando=None, paso="", version=None):
    """El cuerpo que se manda, YA LIMPIO.  `registro` puede ser la ruta del archivo o su texto."""
    return {
        "uuid": mod_uuid.uuid4().hex,
        "equipo": ocultar(str(equipo or "")[:60]) or nombre_de_este_equipo(),
        "reporte": ocultar(str(reporte or "")[:80]),
        "cuando": str(cuando or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))[:40],
        "paso": ocultar(str(paso or paso_del_mensaje(mensaje))[:300]),
        "mensaje": ocultar(str(mensaje or "")[:1000]),
        "registro": final_del_registro(registro),
        "version": str(version or VERSION)[:20],
    }


def nombre_de_este_equipo():
    """El nombre que Windows le da al equipo (solo como último recurso: el usuario pone el suyo en Ajustes)."""
    try:
        return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "")[:60]
    except OSError:
        return ""


# ============================================================== direcciones de red
def es_privada(ip, con_local=True):
    """¿Es una dirección de red local (192.168.x, 10.x, 172.16–31.x) o de este propio equipo?"""
    try:
        d = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    if d.is_unspecified:
        return False                 # 0.0.0.0 = TODAS las tarjetas de red: eso es justo lo que no queremos
    if d.is_loopback:
        return bool(con_local)
    return bool(d.is_private and not d.is_link_local)


def direcciones_de_este_equipo():
    """Las direcciones privadas IPv4 de este equipo (sin 127.0.0.1), para enseñarlas y para escuchar en una."""
    res = []
    for nombre in (socket.gethostname(), ""):
        try:
            for info in socket.getaddrinfo(nombre or None, None, socket.AF_INET):
                ip = info[4][0]
                if es_privada(ip, con_local=False) and ip not in res:
                    res.append(ip)
        except (OSError, ValueError):
            continue
    return res


# ============================================================== el equipo central: recibir
class _Manejador(http.server.BaseHTTPRequestHandler):
    server_version = "BotWebPuente"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    @property
    def receptor(self):
        return self.server.receptor

    def log_message(self, formato, *args):          # el registro propio de http.server: no hace falta
        return

    cerrar_luego = False
    cuerpo_leido = False

    def _responder(self, codigo, texto):
        cuerpo = json.dumps({"ok": codigo == 200, "mensaje": texto}, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            if self.cerrar_luego:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(cuerpo)
        except (ConnectionError, OSError):
            pass

    def _rechazar(self, codigo, motivo):
        """Rechaza y lo apunta (con la dirección y el motivo; la clave NUNCA se apunta).

        Antes de contestar se traga lo que el otro ya estaba mandando, pero COMO MUCHO `2 * MAX_CUERPO`: así se le
        puede decir por qué (si no, la conexión se corta en seco y solo ve «se cortó»), sin tragarse nunca un envío
        enorme."""
        self.receptor.rechazado(self.client_address[0] if self.client_address else "?", motivo)
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            largo = 0
        if not self.cuerpo_leido and 0 < largo <= 2 * MAX_CUERPO:
            try:
                self.rfile.read(largo)
            except (ConnectionError, OSError):
                pass
        self.cerrar_luego = True
        return self._responder(codigo, "No")

    def do_GET(self):
        if self.path != RUTA_SALUD:
            return self._rechazar(404, "ruta que no existe")
        if not self._permitido():
            return
        return self._responder(200, "Aquí está el equipo central de Bot Web")

    def do_POST(self):
        if self.path.rstrip("/") != RUTA:
            return self._rechazar(404, "ruta que no existe")
        if not self._permitido():
            return
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            largo = -1
        if largo <= 0:
            return self._rechazar(400, "sin contenido")
        if largo > MAX_CUERPO:
            return self._rechazar(413, "demasiado grande (%d bytes)" % largo)
        try:
            crudo = self.rfile.read(largo)
            self.cuerpo_leido = True
            datos = json.loads(crudo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, OSError):
            self.cuerpo_leido = True
            return self._rechazar(400, "no es JSON")
        if not isinstance(datos, dict):
            return self._rechazar(400, "no es JSON")
        try:
            nuevo = self.receptor.recibir(datos)
        except Exception:                      # noqa: BLE001 (nada de lo que llega puede tumbar el servidor)
            return self._responder(500, "No se pudo guardar")
        return self._responder(200, "Guardado" if nuevo else "Ya estaba")

    def do_PUT(self):
        return self._rechazar(404, "método que no se admite")

    do_DELETE = do_PUT
    do_HEAD = do_PUT
    do_PATCH = do_PUT
    do_OPTIONS = do_PUT

    def _permitido(self):
        """La petición viene de la red local Y trae la clave del equipo central."""
        quien = self.client_address[0] if self.client_address else ""
        if not es_privada(quien):
            self._rechazar(403, "dirección de fuera de la red local")
            return False
        clave = self.headers.get("X-Bot-Clave") or ""
        buena = self.receptor.clave or ""
        if not buena or not hmac.compare_digest(clave.encode("utf-8"), buena.encode("utf-8")):
            self._rechazar(401, "clave que no coincide" if clave else "sin clave")
            return False
        return True


class _Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    timeout = 10


class Receptor:
    """El equipo central escuchando los fallos de los demás.  `al_llegar(datos)` se llama con cada fallo nuevo."""

    def __init__(self, almacen, clave, puerto=PUERTO_DEFECTO, direccion="", al_llegar=None, apuntar=None):
        self.almacen = almacen
        self.clave = str(clave or "")
        self.al_llegar = al_llegar
        self.apuntar = apuntar or (lambda texto: print(texto, flush=True))
        self.rechazos = 0
        if not self.clave:
            raise ErrorPuente("Primero hace falta una clave para que los otros equipos puedan mandar sus errores.")
        self.direccion = str(direccion or "") or (direcciones_de_este_equipo() or [""])[0]
        if not self.direccion:
            raise ErrorPuente("Este equipo no tiene una dirección de red local (192.168.x.x, 10.x.x.x o 172.16-31.x.x). "
                              "Conéctalo a la red y vuelve a intentarlo.")
        # Se admite 127.0.0.1 (entonces solo llega desde este propio equipo: más cerrado todavía, y lo usan las
        # pruebas), pero NUNCA 0.0.0.0 ni una dirección pública.
        if not es_privada(self.direccion, con_local=True):
            raise ErrorPuente("«%s» no es una dirección de la red local: Bot Web solo escucha en la red local "
                              "(nunca en todas las tarjetas de red)." % self.direccion)
        try:
            self.servidor = _Servidor((self.direccion, int(puerto or PUERTO_DEFECTO)), _Manejador)
        except OSError as e:
            raise ErrorPuente("No se pudo escuchar en %s:%s (%s). Prueba con otro puerto." % (
                self.direccion, puerto, getattr(e, "strerror", None) or e))
        self.servidor.receptor = self
        self.puerto = self.servidor.server_address[1]
        self._hilo = threading.Thread(target=self.servidor.serve_forever, name="puente-errores", daemon=True)
        self._hilo.start()

    @property
    def url(self):
        return "http://%s:%d" % (self.direccion, self.puerto)

    def recibir(self, datos):
        """Guarda un fallo que ha llegado.  Devuelve True si es nuevo (False = ya estaba: no se guarda dos veces)."""
        d = {k: datos.get(k) for k in ("uuid", "equipo", "reporte", "cuando", "paso", "mensaje", "version")}
        d["uuid"] = str(d.get("uuid") or "").strip() or mod_uuid.uuid4().hex
        d["registro"] = str(datos.get("registro") or "")[:MAX_REGISTRO]
        eid = self.almacen.guardar_error_recibido(d)
        if eid and self.al_llegar is not None:
            try:
                self.al_llegar(dict(d, id=eid))
            except Exception:                  # noqa: BLE001
                pass
        return bool(eid)

    def rechazado(self, quien, motivo):
        """Apunta un intento rechazado.  Sin la clave: ni la buena ni la que mandaron."""
        self.rechazos += 1
        self.apuntar("[puente] rechazado un envío de %s: %s" % (quien, motivo))

    def parar(self):
        try:
            self.servidor.shutdown()
        finally:
            self.servidor.server_close()


# ============================================================== los otros equipos: enviar
def _abrir(url, datos, clave, espera=ESPERA_ENVIO):
    """Manda el JSON.  La clave va SOLO en la cabecera (nunca en la dirección, que sí puede acabar en un registro)."""
    pet = urllib.request.Request(url, data=datos, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8", "X-Bot-Clave": clave, "User-Agent": "BotWeb"})
    return urllib.request.urlopen(pet, timeout=espera)        # noqa: S310 (dirección http de la red local del usuario)


def direccion_completa(base):
    base = str(base or "").strip().rstrip("/")
    if not base:
        return ""
    if "://" not in base:
        base = "http://" + base
    return base if base.endswith(RUTA) else base + RUTA


def enviar(base, clave, cuerpo, abrir=None):
    """Manda UN fallo.  Devuelve (ok, motivo): ok=False y el motivo en español si no se pudo."""
    url = direccion_completa(base)
    if not url:
        return False, "Falta la dirección del equipo que recibe los errores."
    if not clave:
        return False, "Falta la clave del equipo que recibe los errores."
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    if len(datos) > MAX_CUERPO:
        cuerpo = dict(cuerpo, registro="(el registro era demasiado grande y no se manda)")
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    try:
        with (abrir or _abrir)(url, datos, str(clave)) as r:
            codigo = getattr(r, "status", None) or r.getcode()
            if int(codigo) == 200:
                return True, ""
            return False, "El equipo central contestó %s." % codigo
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "La clave no coincide con la del equipo que recibe los errores."
        if e.code == 413:
            return False, "El error era demasiado grande para mandarlo."
        if e.code == 404:
            return False, "Esa dirección responde, pero no es un Bot Web esperando errores."
        if e.code == 403:
            return False, "El equipo central no acepta envíos desde esta red."
        return False, "El equipo central contestó %s." % e.code
    except urllib.error.URLError as e:
        return False, "No se pudo conectar con %s (%s). Se guarda y se manda cuando se pueda." % (
            base, getattr(e, "reason", None) or e)
    except (OSError, ValueError) as e:
        return False, "No se pudo mandar (%s). Se guarda y se manda cuando se pueda." % e


def probar(base, clave, equipo="", abrir=None):
    """«Probar el envío»: manda un aviso de prueba.  Devuelve (ok, texto para el usuario)."""
    cuerpo = armar(equipo, "Prueba de envío", "Esto es una prueba: el envío de errores funciona.",
                   registro="(prueba)")
    ok, motivo = enviar(base, clave, cuerpo, abrir=abrir)
    if ok:
        return True, "Funciona: el aviso de prueba ha llegado al equipo central."
    return False, motivo


def vaciar_cola(almacen, base=None, clave=None, abrir=None, limite=50):
    """Manda lo que haya en la cola de este equipo.  Para en cuanto uno no se puede mandar (el central está apagado):
    lo que queda se intentará más tarde.  Devuelve (mandados, pendientes, motivo)."""
    ajustes = almacen.ajustes()
    base = base if base is not None else (ajustes.get("enviar_errores_a") or "")
    clave = clave if clave is not None else almacen.clave("enviar")
    cola = almacen.errores_en_cola(limite=limite)
    if not cola:
        return 0, 0, ""
    if not base or not clave:
        return 0, len(cola), "Falta la dirección o la clave del equipo que recibe los errores."
    mandados, motivo = 0, ""
    for fila in cola:
        ok, motivo = enviar(base, clave, fila["cuerpo"], abrir=abrir)
        if not ok:
            almacen.fallo_envio_error(fila["id"], motivo)
            break
        almacen.quitar_error_de_cola(fila["id"])
        mandados += 1
        motivo = ""
    return mandados, len(almacen.errores_en_cola(limite=limite + 1)), motivo


def anotar_fallo(almacen, reporte, mensaje, registro="", cuando=None, paso="", abrir=None, mandar=True):
    """Un reporte (o el programa) ha fallado en ESTE equipo: se guarda en la cola y, si se puede, se manda ya.

    No hace nada si en Ajustes no se ha puesto una dirección a la que mandar.  Nunca lanza excepciones: un aviso que
    falla no debe tumbar una ejecución."""
    try:
        ajustes = almacen.ajustes()
        if not (ajustes.get("enviar_errores_a") or ""):
            return False
        cuerpo = armar(ajustes.get("nombre_equipo") or "", reporte, mensaje, registro=registro, cuando=cuando, paso=paso)
        almacen.encolar_error(cuerpo["uuid"], cuerpo)
        if mandar:
            vaciar_cola(almacen, abrir=abrir)
        return True
    except Exception:                          # noqa: BLE001
        return False


def enganchar(almacen, abrir=None):
    """Hace que TODA ejecución que acabe mal en este equipo se mande al central (un solo punto: `registrar_ejecucion`).

    Se llama una vez al arrancar (bot.py).  Si en Ajustes no hay dirección, `anotar_fallo` no hace nada."""
    def al_fallar(datos):
        anotar_fallo(almacen, datos.get("nombre") or "", datos.get("mensaje") or "",
                     registro=datos.get("registro") or "", cuando=datos.get("cuando") or "", abrir=abrir)
    almacen.al_registrar = al_fallar
    return al_fallar


class Reenviador:
    """Hilo que cada `CADA` segundos intenta vaciar la cola (el equipo central pudo estar apagado)."""

    def __init__(self, almacen, cada=CADA, abrir=None):
        self.almacen = almacen
        self.cada = float(cada)
        self.abrir = abrir
        self.parar_ya = threading.Event()
        self._hilo = None

    def arrancar(self):
        if self._hilo is not None:
            return self
        self._hilo = threading.Thread(target=self._bucle, name="puente-reenvio", daemon=True)
        self._hilo.start()
        return self

    def _bucle(self):
        while not self.parar_ya.is_set():
            try:
                if (self.almacen.ajustes().get("enviar_errores_a") or ""):
                    vaciar_cola(self.almacen, abrir=self.abrir)
            except Exception:                  # noqa: BLE001
                pass
            finally:
                try:
                    self.almacen.liberar_hilo()
                except Exception:              # noqa: BLE001
                    pass
            self.parar_ya.wait(self.cada)

    def parar(self):
        self.parar_ya.set()


def clave_nueva():
    """Una clave nueva, fácil de copiar a mano a los otros equipos (grupos de 4, sin letras que se confunden)."""
    import secrets
    letras = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(letras) for _ in range(4)) for _ in range(4))


def esperar_a_que_responda(base, clave, segundos=3.0, abrir=None):
    """(pruebas) Espera a que el equipo central conteste."""
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        ok, _m = probar(base, clave, abrir=abrir)
        if ok:
            return True
        time.sleep(0.1)
    return False
