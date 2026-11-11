"""v3.9: «Hay una nueva actualización» (el código nuevo sale de la rama New-tool del repositorio público en GitHub).

- Qué versión está instalada: el archivo `actualizacion.json` de la carpeta del programa ({"sha", "fecha", …}).  Lo
  escriben el instalador (al descargar de GitHub), el paquete para compartir (`crear_paquete.py`) y este módulo (al
  actualizar).  Si no existe (una instalación antigua), la primera comprobación toma la última versión de GitHub como
  punto de partida y lo apunta: no se avisa de nada hasta que salga otra más nueva (nunca avisa sin fin).
- Comprobar: una sola petición a la API de GitHub (sin cuenta: 60 por hora y por equipo), al abrir el bot y luego cada
  6 horas.  Sin Internet, o si GitHub no contesta o pone límite, no pasa nada: se calla.
- Actualizar: se niega si el bot está trabajando.  Si no, copia de seguridad de la base de datos (en su misma carpeta,
  con la fecha), descarga el .zip a una carpeta temporal NUEVA, lo descomprime en otra carpeta vacía y abre el
  instalador descargado en modo actualización (espera a que este programa se cierre, cambia solo el código —los datos
  se conservan— y vuelve a abrir el bot).  El programa se cierra solo.
- Una copia de desarrollo (con la carpeta .git) NUNCA se sobrescribe: el aviso puede salir, pero «Actualizar» explica
  que esa copia se actualiza con git y no hace nada.
- Las tareas programadas (bot.py sin ventana) no comprueban ni actualizan: solo `servidor_ui.abrir_aplicacion` crea el
  `Actualizador`.
"""

import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

from . import RAIZ

REPO = "Rfalso014/Mapez"
RAMA = "New-tool"
URL_API = "https://api.github.com/repos/%s/commits/%s" % (REPO, RAMA)
URL_ZIP = "https://github.com/%s/archive/refs/heads/%s.zip" % (REPO, RAMA)
AGENTE = "BotWeb"                       # (sin datos de nadie)
ARCHIVO = "actualizacion.json"
MARCA_INSTALADOR = ".instalado-por-botweb"      # la deja «Instalar Bot Web.cmd» en la carpeta instalada
INSTALADOR = os.path.join("instalador", "Instalar Bot Web.cmd")
PREFIJO_TEMPORAL = "BotWeb_actualizar_"
INTERVALO = 6 * 3600                    # cada cuánto se vuelve a mirar (segundos)
ESPERA_INICIAL = 15                     # al abrir, se espera un poco para no frenar el arranque
MIN_ENTRE_MANUALES = 60                 # «Buscar actualizaciones» seguido: se usa lo de hace menos de un minuto
TIEMPO_API = 8
TIEMPO_ZIP = 60
MAX_ZIP = 150 * 1024 * 1024
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


class ErrorActualizar(Exception):
    """Algo que impide actualizar, con el mensaje para el usuario."""


# ------------------------------------------------------------------------------------------------ GitHub
def _abrir(url, timeout):
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(pedido, timeout=timeout)       # noqa: S310 (solo https de GitHub)


def consultar_remoto(abrir=None, timeout=TIEMPO_API):
    """La última versión de la rama en GitHub: {"sha", "mensaje" (la primera línea), "fecha"} o None si no se pudo
    saber (sin Internet, GitHub no contesta, límite de peticiones…).  Nunca lanza."""
    try:
        with (abrir or _abrir)(URL_API, timeout) as r:
            datos = json.loads(r.read(1024 * 1024).decode("utf-8"))
        sha = str(datos["sha"]).strip().lower()
        if not _SHA.match(sha):
            return None
        commit = datos.get("commit") or {}
        mensaje = str(commit.get("message") or "").strip().splitlines()
        fecha = (commit.get("committer") or {}).get("date") or (commit.get("author") or {}).get("date") or ""
        return {"sha": sha, "mensaje": (mensaje[0] if mensaje else "")[:200], "fecha": str(fecha)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, urllib.error.URLError):
        return None


# ------------------------------------------------------------------------------------------------ lo instalado
def leer_instalado(raiz=RAIZ):
    """Lo apuntado en `actualizacion.json` ({"sha", "fecha", …}) o None."""
    try:
        with open(os.path.join(raiz, ARCHIVO), encoding="utf-8-sig") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict) or not _SHA.match(str(datos.get("sha") or "").strip().lower()):
        return None
    datos["sha"] = datos["sha"].strip().lower()
    return datos


def guardar_instalado(raiz, datos):
    with open(os.path.join(raiz, ARCHIVO), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def es_copia_git(raiz=RAIZ):
    """True si es una copia de desarrollo (con .git): esa nunca se sobrescribe."""
    return os.path.exists(os.path.join(raiz, ".git"))


def es_instalada(raiz=RAIZ):
    """True si la instaló «Instalar Bot Web» (solo esa se puede actualizar con el botón)."""
    return os.path.isfile(os.path.join(raiz, MARCA_INSTALADOR))


def sha_git(raiz=RAIZ):
    """El commit de una copia de desarrollo (leyendo .git, sin ejecutar git) o None."""
    git = os.path.join(raiz, ".git")
    try:
        with open(os.path.join(git, "HEAD"), encoding="utf-8") as f:
            cabeza = f.read().strip()
        if not cabeza.startswith("ref:"):
            return cabeza.lower() if _SHA.match(cabeza.lower()) else None
        ref = cabeza[4:].strip()
        ruta = os.path.join(git, *ref.split("/"))
        if os.path.isfile(ruta):
            with open(ruta, encoding="utf-8") as f:
                sha = f.read().strip().lower()
                return sha if _SHA.match(sha) else None
        with open(os.path.join(git, "packed-refs"), encoding="utf-8") as f:
            for linea in f:
                partes = linea.strip().split(" ")
                if len(partes) == 2 and partes[1] == ref and _SHA.match(partes[0].lower()):
                    return partes[0].lower()
    except OSError:
        pass
    return None


def git_tiene(raiz, sha):
    """True si la copia de desarrollo ya contiene ese commit (p. ej. lo acaba de subir quien desarrolla)."""
    try:
        r = subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=raiz, capture_output=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def mismo_sha(a, b):
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if len(a) < 7 or len(b) < 7:
        return False
    return a.startswith(b) or b.startswith(a)


def _fecha(texto):
    """«2026-11-10T12:00:00Z» o «…-05:00» → datetime con zona (UTC si no la dice) o None."""
    try:
        d = datetime.datetime.fromisoformat(str(texto).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def hay_novedad(instalado, remoto):
    """¿La versión de GitHub es otra y más nueva que la instalada?  Sin saber la instalada, no (no se avisa a ciegas).
    Si las dos tienen fecha, solo cuenta si la de GitHub es posterior (un paquete hecho con cambios aún sin subir no
    pide «actualizar» a una versión más vieja)."""
    if not remoto or not remoto.get("sha") or not instalado or not instalado.get("sha"):
        return False
    if mismo_sha(instalado["sha"], remoto["sha"]):
        return False
    fi, fr = _fecha(instalado.get("fecha")), _fecha(remoto.get("fecha"))
    if fi and fr:
        return fr > fi
    return True


def fecha_corta(texto):
    """«2026-11-10T15:04:00Z» → «10/11/2026» (en la hora de este equipo)."""
    d = _fecha(texto)
    if d is None:
        return ""
    try:
        d = d.astimezone()
    except (OverflowError, OSError, ValueError):
        pass
    return d.strftime("%d/%m/%Y")


# ------------------------------------------------------------------------------------------------ actualizar
def respaldar_bd(ruta_db, ahora=None):
    """Copia de seguridad de la base de datos en su misma carpeta («bot_antes_de_actualizar_20261111_0930.db»).
    Devuelve la ruta de la copia (None si aún no hay base de datos).  Lanza ErrorActualizar si no se pudo."""
    if not ruta_db or not os.path.isfile(ruta_db):
        return None
    marca = (ahora or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    base = os.path.splitext(os.path.basename(ruta_db))[0]
    destino = os.path.join(os.path.dirname(ruta_db), "%s_antes_de_actualizar_%s.db" % (base, marca))
    try:
        origen = sqlite3.connect(ruta_db)
        try:
            copia = sqlite3.connect(destino)
            try:
                origen.backup(copia)              # (copia coherente aunque el bot la esté usando)
            finally:
                copia.close()
        finally:
            origen.close()
    except (sqlite3.Error, OSError) as e:
        try:
            os.remove(destino)
        except OSError:
            pass
        raise ErrorActualizar("No se pudo hacer la copia de seguridad de tus datos (%s). No se ha cambiado nada." % e)
    return destino


def descargar(url, destino, abrir=None, timeout=TIEMPO_ZIP, maximo=MAX_ZIP):
    """Descarga `url` a `destino` (un archivo nuevo)."""
    total = 0
    with (abrir or _abrir)(url, timeout) as r, open(destino, "xb") as f:
        while True:
            trozo = r.read(256 * 1024)
            if not trozo:
                break
            total += len(trozo)
            if total > maximo:
                raise ErrorActualizar("Lo descargado de GitHub es demasiado grande: no se usa.")
            f.write(trozo)
    return total


def extraer_zip(ruta_zip, destino):
    """Descomprime en `destino`, que se crea nuevo y vacío (si ya existe, error).  Nada puede salirse de esa carpeta."""
    os.makedirs(destino)
    base = os.path.realpath(destino)
    try:
        with zipfile.ZipFile(ruta_zip) as z:
            for info in z.infolist():
                ruta = os.path.realpath(os.path.join(base, info.filename))
                if os.path.commonpath([base, ruta]) != base:
                    raise ErrorActualizar("El archivo descargado no es válido (rutas fuera de su carpeta).")
            z.extractall(base)
    except (zipfile.BadZipFile, OSError) as e:
        raise ErrorActualizar("El archivo descargado no es válido (%s)." % e)
    return base


def buscar_codigo(extraido):
    """La carpeta del bot dentro de lo descomprimido (con bot.py, webbot/ y el instalador) o None."""
    for nombre in sorted(os.listdir(extraido)):
        d = os.path.join(extraido, nombre)
        if (os.path.isdir(d) and os.path.isfile(os.path.join(d, "bot.py")) and os.path.isdir(os.path.join(d, "webbot"))
                and os.path.isfile(os.path.join(d, INSTALADOR))):
            return d
    return None


def lanzar_instalador(instalador, destino, pid, popen=None):
    """Abre el instalador descargado en modo actualización, en su propia ventana (sigue vivo cuando este programa se
    cierre): espera a que termine el proceso `pid`, cambia el código de `destino`\\app y vuelve a abrir el bot."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("BOTWEB_")}   # (sin variables de prueba)
    env.update(BOTWEB_DESTINO=destino, BOTWEB_FUENTE="local", BOTWEB_ACTUALIZAR="1", BOTWEB_ESPERAR_PID=str(int(pid)))
    comando = 'cmd.exe /d /s /c ""%s""' % instalador
    (popen or subprocess.Popen)(comando, cwd=os.path.dirname(instalador), env=env, close_fds=True,
                                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def limpiar_temporales(carpeta=None, dias=1.0):
    """Borra las carpetas temporales de actualizaciones anteriores (de más de `dias`)."""
    carpeta = carpeta or tempfile.gettempdir()
    limite = time.time() - dias * 86400
    try:
        nombres = os.listdir(carpeta)
    except OSError:
        return
    for n in nombres:
        ruta = os.path.join(carpeta, n)
        try:
            if n.startswith(PREFIJO_TEMPORAL) and os.path.isdir(ruta) and os.path.getmtime(ruta) < limite:
                shutil.rmtree(ruta, ignore_errors=True)
        except OSError:
            pass


class Actualizador:
    """El estado del aviso (lo que enseña la interfaz) y la actualización.  Todo se puede cambiar en las pruebas:
    `consultar` (GitHub), `abrir` (descargas), `popen` (lanzar el instalador), `git_tiene`, `pid`."""

    def __init__(self, raiz=RAIZ, consultar=None, abrir=None, popen=None, git_tiene=None, registrar=None, emitir=None,
                 pid=None, temporal=None):
        self.raiz = raiz
        self._consultar = consultar or consultar_remoto
        self._abrir = abrir
        self._popen = popen
        self._git_tiene = git_tiene or globals()["git_tiene"]
        self._registrar = registrar or (lambda linea: None)
        self._emitir = emitir
        self.pid = os.getpid() if pid is None else pid
        self.temporal = temporal
        self._cerrojo = threading.Lock()
        self._remoto = None
        self._base = None                  # punto de partida apuntado en memoria (si no se pudo escribir el archivo)
        self._cuando = 0.0
        self._ultimo_avisado = None
        self._parar = threading.Event()
        self.pospuesta = False
        self.estado_actual = {"activo": True, "disponible": False, "comprobado": False}

    # ------------------------------------------------------------------ comprobar
    def _instalado(self, remoto):
        """Lo instalado ({"sha", "fecha"}).  Sin saberlo (instalación antigua), la versión de GitHub de ahora pasa a ser
        el punto de partida (se apunta en actualizacion.json y en el registro)."""
        if es_copia_git(self.raiz):
            sha = sha_git(self.raiz)
            return {"sha": sha} if sha else None
        inst = leer_instalado(self.raiz) or self._base
        if inst is None and remoto:
            inst = {"sha": remoto["sha"], "fecha": remoto.get("fecha", ""), "rama": RAMA, "origen": "supuesto",
                    "apuntado": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
            self._base = inst
            try:
                guardar_instalado(self.raiz, inst)
            except OSError:
                pass
            self._registrar("Actualizaciones: no se sabía qué versión está instalada; se toma la última de GitHub "
                            "(%s) como punto de partida." % remoto["sha"][:7])
        return inst

    def comprobar(self, manual=False):
        """Mira GitHub (una petición) y devuelve el estado.  Con `manual`, si se miró hace menos de un minuto, se usa
        aquello (pulsar el botón varias veces no gasta peticiones).  Nunca lanza."""
        with self._cerrojo:
            if manual and self.estado_actual.get("comprobado") and time.monotonic() - self._cuando < MIN_ENTRE_MANUALES:
                if self.estado_actual.get("disponible"):
                    self.pospuesta = False
                return self.estado()
            remoto = self._consultar()
            self._cuando = time.monotonic()
            copia_git = es_copia_git(self.raiz)
            est = {"activo": True, "comprobado": True, "copia_git": copia_git, "sin_conexion": remoto is None,
                   "disponible": False, "hora": time.strftime("%H:%M")}
            if remoto is not None:
                self._remoto = remoto
                inst = self._instalado(remoto)
                disponible = hay_novedad(inst, remoto)
                if disponible and copia_git and self._git_tiene(self.raiz, remoto["sha"]):
                    disponible = False             # (esta copia ya tiene ese commit: va por delante)
                est.update(disponible=disponible, sha=remoto["sha"][:7], novedades=remoto.get("mensaje", ""),
                           fecha=fecha_corta(remoto.get("fecha")), instalado=((inst or {}).get("sha") or "")[:7])
            elif self.estado_actual.get("disponible"):
                est = dict(self.estado_actual, sin_conexion=True)    # (lo que ya se sabía sigue valiendo)
            if manual and est.get("disponible"):
                self.pospuesta = False
            self.estado_actual = est
            return self.estado()

    def estado(self):
        """Lo último que se sabe (sin mirar GitHub)."""
        return dict(self.estado_actual, pospuesta=self.pospuesta)

    def posponer(self):
        """«Más tarde»: no se vuelve a enseñar hasta que se abra el bot otra vez."""
        self.pospuesta = True
        return self.estado()

    def _vuelta(self):
        if self._parar.wait(ESPERA_INICIAL):
            return
        limpiar_temporales(self.temporal)
        while True:
            est = self.comprobar()
            if est.get("disponible") and est.get("sha") != self._ultimo_avisado:
                self._ultimo_avisado = est.get("sha")
                self._registrar("Actualizaciones: hay una versión nueva en GitHub (%s)." % est.get("sha"))
                if self._emitir is not None:
                    try:
                        self._emitir("actualizacion", info=self.estado())
                    except Exception:          # noqa: BLE001
                        pass
            if self._parar.wait(INTERVALO):
                return

    def iniciar_periodico(self):
        """Comprueba al poco de abrir y luego cada 6 horas, en un hilo aparte."""
        threading.Thread(target=self._vuelta, name="actualizaciones", daemon=True).start()
        return self

    def parar(self):
        self._parar.set()

    # ------------------------------------------------------------------ actualizar
    def actualizar(self, ruta_db):
        """Prepara y lanza la actualización (ver arriba).  Devuelve {"ok", "copia", "carpeta"}; lanza ErrorActualizar
        con el motivo si no se puede (sin haber tocado nada del programa)."""
        if es_copia_git(self.raiz):
            raise ErrorActualizar("Esta copia del bot es la de desarrollo (tiene la carpeta .git): se actualiza con git "
                                  "(git pull), no con este botón. No se ha cambiado nada.")
        if not es_instalada(self.raiz):
            raise ErrorActualizar("Esta copia del bot no se instaló con «Instalar Bot Web», así que no se puede "
                                  "actualizar sola. Pide el instalador y ábrelo: tus datos se conservan.")
        base_instalada = os.path.dirname(self.raiz)
        remoto = self._consultar() or self._remoto
        if remoto is None:
            raise ErrorActualizar("No se pudo llegar a GitHub. Revisa la conexión a Internet y vuelve a intentarlo.")
        copia = respaldar_bd(ruta_db)
        if copia:
            self._registrar("Actualizaciones: copia de seguridad de los datos en %s" % copia)
        carpeta = tempfile.mkdtemp(prefix=PREFIJO_TEMPORAL, dir=self.temporal)    # (nueva y vacía)
        try:
            zip_ = os.path.join(carpeta, "codigo.zip")
            try:
                descargar(URL_ZIP, zip_, abrir=self._abrir)
            except ErrorActualizar:
                raise
            except (OSError, ValueError, urllib.error.URLError) as e:
                raise ErrorActualizar("No se pudo descargar la actualización de GitHub (%s). Revisa la conexión a "
                                      "Internet y vuelve a intentarlo." % e)
            codigo = buscar_codigo(extraer_zip(zip_, os.path.join(carpeta, "codigo")))
            if codigo is None:
                raise ErrorActualizar("Lo descargado de GitHub no es el bot (falta bot.py o el instalador). No se ha "
                                      "cambiado nada.")
            guardar_instalado(codigo, {"sha": remoto["sha"], "fecha": remoto.get("fecha", ""), "rama": RAMA,
                                       "mensaje": remoto.get("mensaje", ""), "origen": "actualizacion"})
            try:
                lanzar_instalador(os.path.join(codigo, INSTALADOR), base_instalada, self.pid, popen=self._popen)
            except OSError as e:
                raise ErrorActualizar("No se pudo abrir el instalador de la actualización (%s). No se ha cambiado "
                                      "nada." % e)
        except BaseException:
            shutil.rmtree(carpeta, ignore_errors=True)
            raise
        self._registrar("Actualizaciones: se abre el instalador de la versión %s (%s)." % (remoto["sha"][:7], carpeta))
        self.parar()
        return {"ok": True, "copia": copia, "carpeta": carpeta, "sha": remoto["sha"][:7]}
