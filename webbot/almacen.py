"""Almacén de reportes dentro de la aplicación (SQLite, `datos/bot.db`).

Guarda los reportes (flujos) y el historial de ejecuciones.  No importa playwright ni tkinter.

Tablas:
- `reportes`  (id, nombre único entre los activos, url, flujo = JSON del flujo, creado, modificado,
  eliminado = fecha en que se envió a la papelera o NULL, origen = archivo .json del que se importó).
- `ejecuciones` (reporte_id, cuando, resultado ok|error|detenido, mensaje, archivos, duracion).
- `versiones` (reporte_id, cuando, motivo, nombre, flujo): copias de seguridad de un reporte antes de que la
  aplicación lo cambie sola (p. ej. al actualizar de versión); se pueden restaurar.
- `accesos` (host, clave, etiqueta, tipo texto|clave, valor, secreto, selectores, orden): datos de acceso por
  sitio.  Las contraseñas NUNCA se guardan aquí: solo el nombre con el que están en el Administrador de
  credenciales (`secreto`).
- v3.0: `estado_claves` (secreto, host, rechazada, ultimo_ok, usuario): si la página rechazó una contraseña
  guardada y cuándo funcionó por última vez (sin la contraseña); `notificaciones` (avisos de la aplicación);
  `vigilancias` (qué filtro de un reporte se vigila y cada cuánto); `opciones_vistas` (opciones de ese filtro ya
  vistas y si ya se descargaron); `mapas` (filtros encontrados al «Mapear la página»); `meta.ajustes` (ajustes).
- v3.1: `opciones_filtro` (reporte_id, paso, padres, firma, opciones, actualizado, fuente): las opciones conocidas de
  cada filtro de un reporte (panel «Usar filtros»), por combinación de los valores elegidos en los filtros anteriores
  (`padres`, JSON); se llenan desde el mapa, cada ejecución, la vigilancia y «Actualizar opciones».
  `opciones_vistas.novedad` = cuándo se detectó como más reciente que todo lo anterior; `sin_orden` = nueva sin fecha,
  año ni número (no se sabe si es más reciente); `vigilancias.descargar_sin_fecha` = descargarlas también.
- v3.2 «Páginas» (`webbot/paginas.py`): `paginas` (id, nombre único, host, url, creado, modificado, data = JSON con la
  llegada, los filtros, la acción, la plantilla del nombre de archivo y los favoritos); `opciones_pagina` (pagina_id,
  filtro, padres, opciones, actualizado, fuente): opciones de cada filtro por combinación de los filtros anteriores;
  `vigilancias_paginas` y `opciones_vistas_paginas` (como `vigilancias` / `opciones_vistas`, por filtro de una página).
  `ejecuciones` admite `pagina_id` (y `reporte_id` vacío): el historial es el mismo para reportes y páginas (las bases
  de datos anteriores se convierten solas, conservando todas las filas).
- v3.4 «programación completa» (`webbot/horario.py`): `vigilancias.programacion` (JSON con días, horas, «cada N horas»
  en un horario, mensual…; vacío = la de su frecuencia antigua) y `programaciones` (clave «reporte:3», «pagina:2:Fav»…,
  programacion JSON, tarea de Windows, actualizado): la última programación con la que se creó la tarea de un reporte,
  una Página (o, después, un correo), para volver a mostrarla.
- v3.4 «Correo» (`webbot/correo.py`): `cuentas_correo` (Outlook/Gmail en el navegador o IMAP, estado de la sesión;
  la contraseña IMAP NUNCA va aquí), `busquedas_correo` (cuenta, criterios JSON, acciones JSON, máximo por revisión,
  programación) y `correos_procesados` (búsqueda + clave del correo: estado ok|error|descartado, archivos, valores
  copiados, acciones hechas, intentos).  `ejecuciones.correo_id` = la revisión de una búsqueda (historial).
- v3.7 «Avisos y vista»: `en_curso` (tipo, nombre, objetivo_id, paso, total, texto, inicio, actualizado, pid, estado
  esperando|en_curso|ok|error|detenido|cancelado, resumen, visible, empieza, pedido): lo que se está ejecutando FUERA de
  la interfaz (tareas de Windows), con su progreso; la interfaz y la ventanita lo leen y piden «Detener» con `pedido`.
  Las filas de procesos que ya no existen se borran solas (`lista_en_curso`).

API principal (`Almacen`):
    listar(), obtener(id), obtener_por_nombre(nombre), cargar_flujo(id), guardar(flujo, id=None),
    renombrar(id, nombre), duplicar(id), eliminar(id) → papelera, papelera(), restaurar(id),
    borrar_definitivo(id), registrar_ejecucion(...), registrar_resultado(id, res), historial(...),
    importar_flujo(flujo), importar_archivo(ruta), exportar(id, ruta), migrar_carpeta(carpeta).

Hilos: cada hilo usa su propia conexión (sqlite3 no comparte conexiones entre hilos con
seguridad) y las escrituras van bajo un cerrojo, así que la ventana y el hilo de trabajo pueden
usar el mismo `Almacen` a la vez.  `liberar_hilo()` cierra la conexión del hilo actual.
"""

import datetime
import json
import os
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager

from . import horario
from .flujo import VERSION_FORMATO, ErrorFlujo, Flujo, clave_reciente, es_reconocible, migrar_flujo, slug

FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"
MAX_HISTORIAL_POR_REPORTE = 200
LARGO_MAX_NOMBRE = 80
CARPETA_IMPORTADOS = "_importados"
VERSION_ESQUEMA = 3

ESQUEMA = """
CREATE TABLE IF NOT EXISTS reportes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    flujo TEXT NOT NULL,
    creado TEXT NOT NULL,
    modificado TEXT NOT NULL,
    eliminado TEXT,
    origen TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS reportes_nombre_activo ON reportes(nombre COLLATE NOCASE) WHERE eliminado IS NULL;
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporte_id INTEGER REFERENCES reportes(id) ON DELETE CASCADE,
    cuando TEXT NOT NULL,
    resultado TEXT NOT NULL,
    mensaje TEXT NOT NULL DEFAULT '',
    archivos TEXT NOT NULL DEFAULT '[]',
    duracion REAL,
    registro TEXT NOT NULL DEFAULT '',
    captura TEXT NOT NULL DEFAULT '',
    pagina_id INTEGER
);
CREATE INDEX IF NOT EXISTS ejecuciones_por_reporte ON ejecuciones(reporte_id, id);
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS versiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporte_id INTEGER NOT NULL,
    cuando TEXT NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    nombre TEXT NOT NULL DEFAULT '',
    flujo TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS versiones_por_reporte ON versiones(reporte_id, id);
CREATE TABLE IF NOT EXISTS accesos (
    host TEXT NOT NULL,
    clave TEXT NOT NULL,
    etiqueta TEXT NOT NULL DEFAULT '',
    tipo TEXT NOT NULL DEFAULT 'texto',
    valor TEXT,
    secreto TEXT,
    selectores TEXT NOT NULL DEFAULT '[]',
    orden INTEGER NOT NULL DEFAULT 0,
    modificado TEXT NOT NULL,
    PRIMARY KEY (host, clave)
);
CREATE TABLE IF NOT EXISTS estado_claves (
    secreto TEXT PRIMARY KEY,
    host TEXT NOT NULL DEFAULT '',
    usuario TEXT NOT NULL DEFAULT '',
    rechazada TEXT,
    ultimo_ok TEXT
);
CREATE TABLE IF NOT EXISTS notificaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuando TEXT NOT NULL,
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL DEFAULT '',
    datos TEXT NOT NULL DEFAULT '{}',
    leida INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS opciones_filtro (
    reporte_id INTEGER NOT NULL,
    paso INTEGER NOT NULL,
    padres TEXT NOT NULL DEFAULT '[]',
    firma TEXT NOT NULL DEFAULT '',
    opciones TEXT NOT NULL DEFAULT '[]',
    actualizado TEXT NOT NULL,
    fuente TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (reporte_id, paso, padres)
);
CREATE TABLE IF NOT EXISTS mapas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporte_id INTEGER,
    cuando TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    alcance TEXT NOT NULL DEFAULT '',
    filtros TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS paginas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    creado TEXT NOT NULL,
    modificado TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS paginas_nombre ON paginas(nombre COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS opciones_pagina (
    pagina_id INTEGER NOT NULL,
    filtro TEXT NOT NULL,
    padres TEXT NOT NULL DEFAULT '[]',
    opciones TEXT NOT NULL DEFAULT '[]',
    actualizado TEXT NOT NULL,
    fuente TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (pagina_id, filtro, padres)
);
"""

# v3.3: varias vigilancias por reporte o Página.  Cada una tiene su id y vigila (reporte_id + paso) o (pagina_id +
# filtro), con los valores de los otros filtros (`favorito` de la Página y/o `valores`, JSON): p. ej. «Elegir corte»
# con el reporte «Detalles Ventas Mayorista» y, aparte, con «Cartera General».  Las opciones ya vistas son de cada
# vigilancia (`opciones_vigiladas`), así que dos vigilancias de la misma lista con otros valores no se mezclan.
ESQUEMA_VIGILANCIAS = """
CREATE TABLE IF NOT EXISTS vigilancias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporte_id INTEGER,
    paso INTEGER,
    pagina_id INTEGER,
    filtro TEXT NOT NULL DEFAULT '',
    favorito TEXT NOT NULL DEFAULT '',
    valores TEXT NOT NULL DEFAULT '{}',
    nombre TEXT NOT NULL DEFAULT '',
    activa INTEGER NOT NULL DEFAULT 1,
    auto_descargar INTEGER NOT NULL DEFAULT 0,
    descargar_sin_fecha INTEGER NOT NULL DEFAULT 0,
    frecuencia TEXT NOT NULL DEFAULT '',
    cada_horas INTEGER,
    hora TEXT NOT NULL DEFAULT '',
    ultima_revision TEXT,
    ultimo_resultado TEXT NOT NULL DEFAULT '',
    creada TEXT NOT NULL DEFAULT '',
    programacion TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS vigilancias_por_reporte ON vigilancias(reporte_id, paso);
CREATE INDEX IF NOT EXISTS vigilancias_por_pagina ON vigilancias(pagina_id, filtro);
CREATE TABLE IF NOT EXISTS opciones_vigiladas (
    vigilancia_id INTEGER NOT NULL,
    texto TEXT NOT NULL,
    primera_vez TEXT NOT NULL,
    orden INTEGER NOT NULL DEFAULT 0,
    nueva INTEGER NOT NULL DEFAULT 0,
    descargada TEXT,
    archivos TEXT NOT NULL DEFAULT '[]',
    sin_orden INTEGER NOT NULL DEFAULT 0,
    novedad TEXT,
    PRIMARY KEY (vigilancia_id, texto)
);
"""
# tablas de la 3.0–3.2 (una vigilancia por reporte / por Página); al convertir se renombran con «_v32» (no se borran)
TABLAS_VIGILANCIA_V32 = ("vigilancias", "opciones_vistas", "vigilancias_paginas", "opciones_vistas_paginas")
SUFIJO_COPIA_V33 = ".antes-v3.3"
CAMPOS_VIGILANCIA = ("favorito", "valores", "nombre", "activa", "auto_descargar", "descargar_sin_fecha", "frecuencia",
                     "cada_horas", "hora", "paso", "filtro", "programacion")
# v3.4: frecuencias de una vigilancia: '' (solo a mano), 'horas' y 'diaria' (3.0–3.3) y 'programa' (la columna
# `programacion` manda)
FRECUENCIAS_VIGILANCIA = ("", "horas", "diaria", "programa")

# v3.4: la última programación con la que se creó la tarea de Windows de un reporte, una Página o un correo
ESQUEMA_PROGRAMACIONES = """
CREATE TABLE IF NOT EXISTS programaciones (
    clave TEXT PRIMARY KEY,
    programacion TEXT NOT NULL DEFAULT '',
    tarea TEXT NOT NULL DEFAULT '',
    actualizado TEXT NOT NULL DEFAULT ''
);
"""

# v3.4 «Correo» (`webbot/correo.py`): cuentas de correo (Outlook/Gmail en el navegador o IMAP; la contraseña IMAP va al
# Administrador de credenciales, nunca aquí), búsquedas (qué correo + qué hacer con él + cuándo) y los correos ya
# procesados por cada búsqueda (para no procesarlos dos veces).
ESQUEMA_CORREO = """
CREATE TABLE IF NOT EXISTS cuentas_correo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    proveedor TEXT NOT NULL DEFAULT 'outlook_web',
    direccion TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    host TEXT NOT NULL DEFAULT '',
    puerto INTEGER,
    usuario TEXT NOT NULL DEFAULT '',
    ssl INTEGER NOT NULL DEFAULT 1,
    carpeta TEXT NOT NULL DEFAULT '',
    estado_sesion TEXT NOT NULL DEFAULT '',
    sesion_texto TEXT NOT NULL DEFAULT '',
    sesion_cuando TEXT,
    creada TEXT NOT NULL,
    modificada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS busquedas_correo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    cuenta_id INTEGER NOT NULL,
    activa INTEGER NOT NULL DEFAULT 1,
    criterios TEXT NOT NULL DEFAULT '{}',
    acciones TEXT NOT NULL DEFAULT '[]',
    max_por_vez INTEGER NOT NULL DEFAULT 10,
    programacion TEXT NOT NULL DEFAULT '',
    ultima_revision TEXT,
    ultimo_resultado TEXT NOT NULL DEFAULT '',
    creada TEXT NOT NULL,
    modificada TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS busquedas_correo_nombre ON busquedas_correo(nombre COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS correos_procesados (
    busqueda_id INTEGER NOT NULL,
    clave TEXT NOT NULL,
    estado TEXT NOT NULL,
    cuando TEXT NOT NULL,
    asunto TEXT NOT NULL DEFAULT '',
    remitente TEXT NOT NULL DEFAULT '',
    fecha TEXT NOT NULL DEFAULT '',
    archivos TEXT NOT NULL DEFAULT '[]',
    valores TEXT NOT NULL DEFAULT '[]',
    hechas TEXT NOT NULL DEFAULT '[]',
    mensaje TEXT NOT NULL DEFAULT '',
    intentos INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (busqueda_id, clave)
);
"""

# v3.7: lo que se está ejecutando FUERA de la interfaz (tareas de Windows / línea de comandos), para que la interfaz y la
# ventanita enseñen su barra de progreso.  `pedido` = lo que pide el usuario (detener, cancelar, ya, en_vivo).
ESQUEMA_EN_CURSO = """
CREATE TABLE IF NOT EXISTS en_curso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL DEFAULT '',
    nombre TEXT NOT NULL DEFAULT '',
    objetivo_id INTEGER,
    paso INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    texto TEXT NOT NULL DEFAULT '',
    inicio TEXT NOT NULL,
    actualizado TEXT NOT NULL,
    pid INTEGER,
    estado TEXT NOT NULL DEFAULT 'en_curso',
    resumen TEXT NOT NULL DEFAULT '',
    visible INTEGER NOT NULL DEFAULT 0,
    empieza TEXT NOT NULL DEFAULT '',
    pedido TEXT NOT NULL DEFAULT ''
);
"""
ESTADOS_EN_CURSO = ("esperando", "en_curso", "ok", "error", "detenido", "cancelado")
PEDIDOS_EN_CURSO = ("", "detener", "cancelar", "ya", "en_vivo")
CAMPOS_EN_CURSO = ("tipo", "nombre", "objetivo_id", "paso", "total", "texto", "pid", "estado", "resumen", "visible",
                   "empieza", "pedido")
EN_CURSO_GUARDAR_TERMINADOS = 90        # segundos que se conserva una fila terminada (la ventanita enseña el resultado)
EN_CURSO_MAX_HORAS = 13                 # más que el límite de las tareas (12 h): una fila más vieja ya no está viva


def pid_vivo(pid):
    """v3.7: ¿sigue vivo el proceso `pid`?  En Windows con OpenProcess/GetExitCodeProcess (os.kill(pid, 0) MATARÍA el
    proceso en Windows).  Ante la duda, sí."""
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        h = k32.OpenProcess(0x1000, False, pid)                     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5                      # acceso denegado: existe
        try:
            codigo = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(codigo)):
                return True
            return codigo.value == 259                               # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:          # noqa: BLE001
        return True


# v3.2: `ejecuciones` con `reporte_id` vacío (ejecuciones de una Página) y `pagina_id`.  Las bases de datos anteriores
# se convierten copiando la tabla (SQLite no deja quitar un NOT NULL).
_EJECUCIONES_V32 = """
CREATE TABLE ejecuciones_v32 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporte_id INTEGER REFERENCES reportes(id) ON DELETE CASCADE,
    cuando TEXT NOT NULL,
    resultado TEXT NOT NULL,
    mensaje TEXT NOT NULL DEFAULT '',
    archivos TEXT NOT NULL DEFAULT '[]',
    duracion REAL,
    registro TEXT NOT NULL DEFAULT '',
    captura TEXT NOT NULL DEFAULT '',
    pagina_id INTEGER
)"""

AJUSTES_DEFECTO = {
    "navegador": "chrome",
    "timeout_paso": 60,
    "timeout_descarga": 600,
    "pausa_entre_pasos": 0.3,
    "carpeta_descargas": "",
    "recuperacion_automatica": True,
    "esperar_carga": True,
    "ver_mientras_trabaja": True,
    "guia_vista": False,          # v3.8: la guía de inicio ya se vio o se saltó
}


class ErrorAlmacen(ValueError):
    """Operación no válida sobre los reportes guardados (nombre repetido, reporte inexistente…)."""


def ruta_por_defecto():
    """`datos/bot.db` del proyecto (o la variable de entorno BOTWEB_DB)."""
    if os.environ.get("BOTWEB_DB"):
        return os.path.abspath(os.environ["BOTWEB_DB"])
    from . import RAIZ
    return os.path.join(RAIZ, "datos", "bot.db")


def nombre_perfil(reporte_id):
    """Carpeta del perfil del navegador de un reporte (dentro de `perfiles/`): va por id, así que
    renombrar el reporte no pierde la sesión iniciada."""
    return "reporte_%d" % int(reporte_id)


def _ahora(cuando=None):
    return (cuando or datetime.datetime.now()).strftime(FORMATO_FECHA)


def validar_nombre(nombre):
    """Devuelve el nombre limpio o lanza ErrorAlmacen."""
    n = re.sub(r"\s+", " ", (nombre or "")).strip()
    if not n:
        raise ErrorAlmacen("Escribe un nombre para el reporte")
    if len(n) > LARGO_MAX_NOMBRE:
        raise ErrorAlmacen("El nombre es demasiado largo (máximo %d caracteres)" % LARGO_MAX_NOMBRE)
    if '"' in n or re.search(r"[\x00-\x1f]", n):
        raise ErrorAlmacen("El nombre no puede llevar comillas dobles (\")")
    return n


def _url_de(flujo):
    return flujo.url or next((p.url for p in flujo.pasos if p.tipo == "abrir_url"), "")


class Almacen:
    def __init__(self, ruta=None):
        self.ruta = os.path.abspath(ruta or ruta_por_defecto())
        os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
        self._local = threading.local()
        self._conexiones = []
        self._cerrojo = threading.RLock()
        con = self._con()
        with self._cerrojo:
            con.executescript(ESQUEMA)
            con.execute("INSERT OR IGNORE INTO meta(clave, valor) VALUES ('version', ?)", (str(VERSION_ESQUEMA),))
            con.execute("UPDATE meta SET valor = ? WHERE clave = 'version' AND CAST(valor AS INTEGER) < ?",
                        (str(VERSION_ESQUEMA), VERSION_ESQUEMA))
            columnas = {f[1] for f in con.execute("PRAGMA table_info(ejecuciones)")}
            for col in ("registro", "captura"):          # v3.0: registro y captura de error de cada ejecución
                if col not in columnas:
                    con.execute("ALTER TABLE ejecuciones ADD COLUMN %s TEXT NOT NULL DEFAULT ''" % col)
            # v3.3.1: lo que dijo la página cuando se marcó la contraseña como rechazada
            if "motivo" not in {f[1] for f in con.execute("PRAGMA table_info(estado_claves)")}:
                con.execute("ALTER TABLE estado_claves ADD COLUMN motivo TEXT NOT NULL DEFAULT ''")
            self.copia_v33 = ""
            self._migrar_vigilancias_v33(con)
            con.executescript(ESQUEMA_VIGILANCIAS)
            # v3.4: programación completa de cada vigilancia (JSON; vacía = la de su frecuencia antigua)
            if "programacion" not in {f[1] for f in con.execute("PRAGMA table_info(vigilancias)")}:
                con.execute("ALTER TABLE vigilancias ADD COLUMN programacion TEXT NOT NULL DEFAULT ''")
            con.executescript(ESQUEMA_PROGRAMACIONES)
            self._migrar_ejecuciones_v32(con)
            # v3.4 «Correo»: tablas nuevas (no se toca nada de lo anterior) y la búsqueda de cada ejecución
            con.executescript(ESQUEMA_CORREO)
            if "correo_id" not in {f[1] for f in con.execute("PRAGMA table_info(ejecuciones)")}:
                con.execute("ALTER TABLE ejecuciones ADD COLUMN correo_id INTEGER")
            con.execute("CREATE INDEX IF NOT EXISTS ejecuciones_por_correo ON ejecuciones(correo_id, id)")
            con.executescript(ESQUEMA_EN_CURSO)              # v3.7: tabla nueva (no cambia nada de lo anterior)

    def _tablas(self, con):
        return {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def copia_de_seguridad(self, sufijo):
        """Copia el archivo de la base de datos (con la API de copia de SQLite, coherente aunque esté abierta) a
        `<ruta><sufijo>` (o «<ruta><sufijo> (2)»… si ya existe).  Devuelve la ruta de la copia."""
        destino = self.ruta + sufijo
        n = 2
        while os.path.exists(destino):
            destino = "%s%s (%d)" % (self.ruta, sufijo, n)
            n += 1
        copia = sqlite3.connect(destino)
        try:
            self._con().backup(copia)
        finally:
            copia.close()
        return destino

    def _migrar_vigilancias_v33(self, con):
        """v3.3: de una vigilancia por reporte/Página (`vigilancias.reporte_id` y `vigilancias_paginas.pagina_id` como
        clave) a varias con su propio id.  ANTES de cambiar nada se hace una copia del archivo (`bot.db.antes-v3.3`).
        Las filas se copian (con sus opciones ya vistas) y las tablas antiguas quedan renombradas como «*_v32»."""
        tablas = self._tablas(con)
        cols = {f[1] for f in con.execute("PRAGMA table_info(vigilancias)")} if "vigilancias" in tablas else set()
        viejas = [t for t in TABLAS_VIGILANCIA_V32 if t in tablas and not (t == "vigilancias" and "id" in cols)]
        if not viejas:
            return
        self.copia_v33 = self.copia_de_seguridad(SUFIJO_COPIA_V33)       # primero, la copia de seguridad
        if "opciones_vistas" in tablas:          # (bases de datos de la 3.0: columnas de la 3.1)
            columnas = {f[1] for f in con.execute("PRAGMA table_info(opciones_vistas)")}
            if "sin_orden" not in columnas:
                con.execute("ALTER TABLE opciones_vistas ADD COLUMN sin_orden INTEGER NOT NULL DEFAULT 0")
            if "novedad" not in columnas:
                con.execute("ALTER TABLE opciones_vistas ADD COLUMN novedad TEXT")
        if "vigilancias" in viejas and "descargar_sin_fecha" not in cols:
            con.execute("ALTER TABLE vigilancias ADD COLUMN descargar_sin_fecha INTEGER NOT NULL DEFAULT 0")
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("DROP TABLE IF EXISTS vigilancias_v33")
            con.execute("DROP TABLE IF EXISTS opciones_vigiladas")
            for sentencia in ESQUEMA_VIGILANCIAS.replace("TABLE IF NOT EXISTS vigilancias (",
                                                         "TABLE vigilancias_v33 (").split(";"):
                if sentencia.strip() and "CREATE INDEX" not in sentencia:
                    con.execute(sentencia)
            ahora = _ahora()
            comunes = "activa, auto_descargar, descargar_sin_fecha, frecuencia, cada_horas, hora, ultima_revision, ultimo_resultado"
            columnas_op = "texto, primera_vez, orden, nueva, descargada, archivos, sin_orden, novedad"
            if "vigilancias" in viejas:
                for v in con.execute("SELECT * FROM vigilancias").fetchall():
                    cur = con.execute("INSERT INTO vigilancias_v33(reporte_id, paso, %s, creada) SELECT reporte_id, paso, %s, ? "
                                      "FROM vigilancias WHERE reporte_id = ?" % (comunes, comunes), (ahora, v["reporte_id"]))
                    if "opciones_vistas" in viejas:
                        con.execute("INSERT OR IGNORE INTO opciones_vigiladas(vigilancia_id, %s) SELECT ?, %s FROM opciones_vistas "
                                    "WHERE reporte_id = ? AND paso = ?" % (columnas_op, columnas_op),
                                    (cur.lastrowid, v["reporte_id"], v["paso"]))
            if "vigilancias_paginas" in viejas:
                for v in con.execute("SELECT * FROM vigilancias_paginas").fetchall():
                    cur = con.execute("INSERT INTO vigilancias_v33(pagina_id, filtro, favorito, %s, creada) SELECT pagina_id, "
                                      "filtro, favorito, %s, ? FROM vigilancias_paginas WHERE pagina_id = ?" % (comunes, comunes),
                                      (ahora, v["pagina_id"]))
                    if "opciones_vistas_paginas" in viejas:
                        con.execute("INSERT OR IGNORE INTO opciones_vigiladas(vigilancia_id, %s) SELECT ?, %s FROM "
                                    "opciones_vistas_paginas WHERE pagina_id = ? AND filtro = ?" % (columnas_op, columnas_op),
                                    (cur.lastrowid, v["pagina_id"], v["filtro"]))
            for t in viejas:
                con.execute("DROP TABLE IF EXISTS %s_v32" % t)
                con.execute("ALTER TABLE %s RENAME TO %s_v32" % (t, t))
            con.execute("ALTER TABLE vigilancias_v33 RENAME TO vigilancias")
            con.execute("INSERT OR REPLACE INTO meta(clave, valor) VALUES ('vigilancias_v33', ?)", (self.copia_v33,))
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")

    def _migrar_ejecuciones_v32(self, con):
        """v3.2: `ejecuciones` con `pagina_id` y `reporte_id` que puede ir vacío.  Copia la tabla entera (mismos ids)."""
        columnas = {f[1] for f in con.execute("PRAGMA table_info(ejecuciones)")}
        if "pagina_id" not in columnas:
            con.execute("PRAGMA foreign_keys = OFF")          # (fuera de la transacción: si no, no tiene efecto)
            try:
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute("DROP TABLE IF EXISTS ejecuciones_v32")
                    con.execute(_EJECUCIONES_V32)
                    con.execute("INSERT INTO ejecuciones_v32(id, reporte_id, cuando, resultado, mensaje, archivos, duracion, "
                                "registro, captura) SELECT id, reporte_id, cuando, resultado, mensaje, archivos, duracion, "
                                "registro, captura FROM ejecuciones")
                    con.execute("DROP TABLE ejecuciones")
                    con.execute("ALTER TABLE ejecuciones_v32 RENAME TO ejecuciones")
                    con.execute("CREATE INDEX IF NOT EXISTS ejecuciones_por_reporte ON ejecuciones(reporte_id, id)")
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
                con.execute("COMMIT")
            finally:
                con.execute("PRAGMA foreign_keys = ON")
        con.execute("CREATE INDEX IF NOT EXISTS ejecuciones_por_pagina ON ejecuciones(pagina_id, id)")

    # ------------------------------------------------------------- conexiones
    def _con(self):
        c = getattr(self._local, "con", None)
        if c is None:
            c = sqlite3.connect(self.ruta, timeout=20, check_same_thread=False, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA busy_timeout = 20000")
            self._local.con = c
            with self._cerrojo:
                self._conexiones.append(c)
        return c

    @contextmanager
    def _transaccion(self):
        c = self._con()
        with self._cerrojo:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    def liberar_hilo(self):
        """Cierra la conexión del hilo actual (se vuelve a abrir sola si hace falta)."""
        c = getattr(self._local, "con", None)
        if c is not None:
            self._local.con = None
            with self._cerrojo:
                if c in self._conexiones:
                    self._conexiones.remove(c)
            c.close()

    def cerrar(self):
        """Cierra todas las conexiones (de todos los hilos)."""
        with self._cerrojo:
            for c in self._conexiones:
                try:
                    c.close()
                except sqlite3.Error:
                    pass
            self._conexiones = []
        self._local = threading.local()

    # ---------------------------------------------------------------- lectura
    _COLUMNAS_LISTA = """r.id, r.nombre, r.url, r.creado, r.modificado, r.eliminado, r.origen,
        (SELECT e.cuando FROM ejecuciones e WHERE e.reporte_id = r.id ORDER BY e.id DESC LIMIT 1) AS ultima,
        (SELECT e.resultado FROM ejecuciones e WHERE e.reporte_id = r.id ORDER BY e.id DESC LIMIT 1) AS resultado,
        (SELECT e.mensaje FROM ejecuciones e WHERE e.reporte_id = r.id ORDER BY e.id DESC LIMIT 1) AS mensaje"""

    def listar(self):
        """Reportes activos, por nombre: dicts {id, nombre, url, creado, modificado, ultima, resultado, mensaje}."""
        filas = self._con().execute(
            "SELECT %s FROM reportes r WHERE r.eliminado IS NULL ORDER BY r.nombre COLLATE NOCASE" % self._COLUMNAS_LISTA)
        return [dict(f) for f in filas]

    def papelera(self):
        """Reportes eliminados (recuperables), del más reciente al más antiguo."""
        filas = self._con().execute(
            "SELECT %s FROM reportes r WHERE r.eliminado IS NOT NULL ORDER BY r.eliminado DESC, r.id DESC"
            % self._COLUMNAS_LISTA)
        return [dict(f) for f in filas]

    def obtener(self, reporte_id, incluir_eliminados=False):
        """El reporte (dict con la columna `flujo` en JSON) o None."""
        sql = "SELECT * FROM reportes WHERE id = ?" + ("" if incluir_eliminados else " AND eliminado IS NULL")
        f = self._con().execute(sql, (int(reporte_id),)).fetchone()
        return dict(f) if f else None

    def obtener_por_nombre(self, nombre):
        f = self._con().execute("SELECT * FROM reportes WHERE nombre = ? COLLATE NOCASE AND eliminado IS NULL",
                                ((nombre or "").strip(),)).fetchone()
        return dict(f) if f else None

    def obtener_por_origen(self, archivo):
        """Reporte importado de un archivo .json con ese nombre (sin carpeta; con o sin «.json»)."""
        base = os.path.basename((archivo or "").strip())
        candidatos = {base.lower(), (base + ".json").lower()}
        for f in self._con().execute("SELECT * FROM reportes WHERE origen <> '' AND eliminado IS NULL ORDER BY id"):
            if f["origen"].lower() in candidatos:
                return dict(f)
        return None

    def existe_nombre(self, nombre, excluir_id=None):
        r = self.obtener_por_nombre(nombre)
        return r is not None and (excluir_id is None or r["id"] != int(excluir_id))

    def cargar_flujo(self, reporte_id, incluir_eliminados=False):
        r = self.obtener(reporte_id, incluir_eliminados=incluir_eliminados)
        if r is None:
            raise ErrorAlmacen("No existe el reporte con número %s" % reporte_id)
        try:
            fl = Flujo.desde_json(r["flujo"])
        except ErrorFlujo as e:
            raise ErrorAlmacen("El reporte «%s» está dañado: %s" % (r["nombre"], e)) from e
        fl.nombre = r["nombre"]
        return fl

    def resolver(self, ref):
        """Id de un reporte a partir de un número o de su nombre (lanza ErrorAlmacen si no existe)."""
        if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit() and self.obtener(int(ref))):
            r = self.obtener(int(ref))
        else:
            r = self.obtener_por_nombre(str(ref))
        if r is None:
            raise ErrorAlmacen("No existe el reporte «%s»" % ref)
        return r["id"]

    # -------------------------------------------------------------- escritura
    def guardar(self, flujo, reporte_id=None):
        """Guarda el flujo con su nombre (`flujo.nombre`).  Sin id crea un reporte nuevo; con id lo
        actualiza (y si cambió el nombre, lo renombra).  Devuelve el id."""
        nombre = validar_nombre(flujo.nombre)
        flujo.nombre = nombre
        texto = flujo.a_json()
        ahora = _ahora()
        try:
            with self._transaccion() as c:
                if reporte_id is None:
                    cur = c.execute("INSERT INTO reportes(nombre, url, flujo, creado, modificado) VALUES (?, ?, ?, ?, ?)",
                                    (nombre, _url_de(flujo), texto, ahora, ahora))
                    return cur.lastrowid
                cur = c.execute("UPDATE reportes SET nombre = ?, url = ?, flujo = ?, modificado = ? "
                                "WHERE id = ? AND eliminado IS NULL", (nombre, _url_de(flujo), texto, ahora, int(reporte_id)))
                if cur.rowcount == 0:
                    raise ErrorAlmacen("El reporte ya no existe (¿se eliminó?). Usa «Guardar como…».")
                return int(reporte_id)
        except sqlite3.IntegrityError as e:
            raise ErrorAlmacen("Ya existe un reporte llamado «%s». Elige otro nombre." % nombre) from e

    def renombrar(self, reporte_id, nombre):
        """Cambia el nombre (el id, el historial y el perfil del navegador se conservan)."""
        nombre = validar_nombre(nombre)
        fl = self.cargar_flujo(reporte_id)
        fl.nombre = nombre
        self.guardar(fl, reporte_id)
        return nombre

    def nombre_libre(self, nombre, sufijo="copia"):
        """«X» si está libre; si no, «X (copia)», «X (copia 2)»…"""
        nombre = validar_nombre(nombre)
        if not self.existe_nombre(nombre):
            return nombre
        n = 1
        while True:
            base = "%s (%s)" % (nombre, sufijo) if n == 1 else "%s (%s %d)" % (nombre, sufijo, n)
            if len(base) > LARGO_MAX_NOMBRE:
                base = base[-LARGO_MAX_NOMBRE:]
            if not self.existe_nombre(base):
                return base
            n += 1

    def duplicar(self, reporte_id):
        """Copia el reporte con el nombre «X (copia)».  Devuelve el id nuevo (perfil nuevo, sin sesión)."""
        fl = self.cargar_flujo(reporte_id)
        r = self.obtener(reporte_id)
        fl.nombre = self.nombre_libre(r["nombre"])
        return self.guardar(fl)

    def eliminar(self, reporte_id):
        """Envía el reporte a la papelera (se puede recuperar con `restaurar`)."""
        with self._transaccion() as c:
            cur = c.execute("UPDATE reportes SET eliminado = ? WHERE id = ? AND eliminado IS NULL",
                            (_ahora(), int(reporte_id)))
            if cur.rowcount == 0:
                raise ErrorAlmacen("No existe el reporte con número %s" % reporte_id)

    def restaurar(self, reporte_id):
        """Saca un reporte de la papelera.  Si ya hay otro con su nombre, se llama «X (recuperado)».
        Devuelve el nombre con el que queda."""
        r = self.obtener(reporte_id, incluir_eliminados=True)
        if r is None or r["eliminado"] is None:
            raise ErrorAlmacen("Ese reporte no está en la papelera")
        nombre = self.nombre_libre(r["nombre"], sufijo="recuperado")
        try:
            with self._transaccion() as c:
                texto = r["flujo"]
                if nombre != r["nombre"]:
                    try:
                        d = json.loads(texto)
                        d["nombre"] = nombre
                        texto = json.dumps(d, ensure_ascii=False, indent=2)
                    except ValueError:
                        pass
                c.execute("UPDATE reportes SET eliminado = NULL, nombre = ?, flujo = ?, modificado = ? WHERE id = ?",
                          (nombre, texto, _ahora(), int(reporte_id)))
        except sqlite3.IntegrityError as e:     # pragma: no cover (carrera con otro hilo)
            raise ErrorAlmacen("Ya existe un reporte llamado «%s»" % nombre) from e
        return nombre

    def borrar_definitivo(self, reporte_id):
        """Borra para siempre un reporte que ya está en la papelera (y su historial, vigilancia y mapas)."""
        with self._transaccion() as c:
            cur = c.execute("DELETE FROM reportes WHERE id = ? AND eliminado IS NOT NULL", (int(reporte_id),))
            if cur.rowcount == 0:
                raise ErrorAlmacen("Solo se pueden borrar definitivamente los reportes de la papelera")
            c.execute("DELETE FROM opciones_vigiladas WHERE vigilancia_id IN (SELECT id FROM vigilancias WHERE reporte_id = ?)",
                      (int(reporte_id),))
            for tabla in ("vigilancias", "mapas", "opciones_filtro"):
                c.execute("DELETE FROM %s WHERE reporte_id = ?" % tabla, (int(reporte_id),))

    # -------------------------------------------------------------- historial
    def registrar_ejecucion(self, reporte_id, resultado, mensaje="", archivos=None, cuando=None, duracion=None,
                            registro="", captura="", pagina_id=None, correo_id=None):
        """Anota una ejecución.  `resultado`: «ok», «error» o «detenido».  v3.2: con `pagina_id` (y `reporte_id` None)
        es una ejecución de una Página; v3.4: con `correo_id`, la revisión de una búsqueda de correo (los archivos se
        guardan con su ruta completa, para «Abrir archivo»)."""
        if correo_id is not None:
            nombres = [str(a) for a in (archivos or [])][:20]
            tabla, columna, clave = "busquedas_correo", "correo_id", int(correo_id)
        elif pagina_id is not None:
            nombres = [os.path.basename(a) for a in (archivos or [])][:20]
            tabla, columna, clave = "paginas", "pagina_id", int(pagina_id)
        else:
            nombres = [os.path.basename(a) for a in (archivos or [])][:20]
            tabla, columna, clave = "reportes", "reporte_id", int(reporte_id)
        with self._transaccion() as c:
            if c.execute("SELECT 1 FROM %s WHERE id = ?" % tabla, (clave,)).fetchone() is None:
                return False
            c.execute("INSERT INTO ejecuciones(reporte_id, pagina_id, correo_id, cuando, resultado, mensaje, archivos, "
                      "duracion, registro, captura) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (clave if columna == "reporte_id" else None, clave if columna == "pagina_id" else None,
                       clave if columna == "correo_id" else None, _ahora(cuando), resultado, (mensaje or "")[:300],
                       json.dumps(nombres, ensure_ascii=False), duracion, registro or "", captura or ""))
            c.execute("DELETE FROM ejecuciones WHERE {0} = ? AND id NOT IN "
                      "(SELECT id FROM ejecuciones WHERE {0} = ? ORDER BY id DESC LIMIT ?)".format(columna),
                      (clave, clave, MAX_HISTORIAL_POR_REPORTE))
        return True

    def registrar_resultado(self, reporte_id, res):
        """Anota un ResultadoEjecucion del ejecutor."""
        if res is None or reporte_id is None:
            return False
        estado = "ok" if res.ok else ("detenido" if res.detenido else "error")
        try:
            self.guardar_opciones_leidas(reporte_id, res, "ejecucion")     # v3.1: listas leídas en la ejecución
        except (sqlite3.Error, TypeError, ValueError):
            pass
        return self.registrar_ejecucion(reporte_id, estado, "" if res.ok else res.resumen(), res.archivos,
                                        registro=getattr(res, "ruta_log", "") or "",
                                        captura=getattr(res, "ruta_captura", "") or "")

    def historial(self, reporte_id=None, limite=50, pagina_id=None, correo_id=None):
        """Últimas ejecuciones (la más reciente primero): dicts {reporte_id, pagina_id, correo_id, nombre, cuando,
        resultado, mensaje, archivos}.  Sin `reporte_id`, `pagina_id` ni `correo_id`: todas (reportes, Páginas y
        búsquedas de correo)."""
        sql = ("SELECT e.id, e.reporte_id, e.pagina_id, e.correo_id, COALESCE(r.nombre, p.nombre, b.nombre) AS nombre, "
               "e.cuando, e.resultado, e.mensaje, e.archivos, e.duracion, e.registro, e.captura FROM ejecuciones e "
               "LEFT JOIN reportes r ON r.id = e.reporte_id LEFT JOIN paginas p ON p.id = e.pagina_id "
               "LEFT JOIN busquedas_correo b ON b.id = e.correo_id "
               "WHERE (r.id IS NOT NULL OR p.id IS NOT NULL OR b.id IS NOT NULL)")
        args = []
        if reporte_id is not None:
            sql += " AND e.reporte_id = ?"
            args.append(int(reporte_id))
        if pagina_id is not None:
            sql += " AND e.pagina_id = ?"
            args.append(int(pagina_id))
        if correo_id is not None:
            sql += " AND e.correo_id = ?"
            args.append(int(correo_id))
        sql += " ORDER BY e.id DESC LIMIT ?"
        args.append(int(limite))
        res = []
        for f in self._con().execute(sql, args):
            d = dict(f)
            try:
                d["archivos"] = json.loads(d["archivos"] or "[]")
            except ValueError:
                d["archivos"] = []
            res.append(d)
        return res

    def ejecucion(self, ejecucion_id):
        f = self._con().execute("SELECT * FROM ejecuciones WHERE id = ?", (int(ejecucion_id),)).fetchone()
        return dict(f) if f else None

    def ultima_ejecucion(self, reporte_id):
        h = self.historial(reporte_id, limite=1)
        return h[0] if h else None

    # ------------------------------------------------- importar / exportar
    def importar_flujo(self, flujo, origen=""):
        """Añade un flujo como reporte nuevo (si el nombre está ocupado, «X (2)»…).  Devuelve el id."""
        nombre = validar_nombre(flujo.nombre or "Reporte importado")
        if flujo.version < VERSION_FORMATO:
            migrar_flujo(flujo)          # el archivo original sirve de copia de la versión anterior
        libre = nombre
        n = 2
        while self.existe_nombre(libre):
            libre = "%s (%d)" % (nombre, n)
            n += 1
        flujo.nombre = libre
        rid = self.guardar(flujo)
        if origen:
            with self._transaccion() as c:
                c.execute("UPDATE reportes SET origen = ? WHERE id = ?", (origen, rid))
        return rid

    def importar_archivo(self, ruta):
        """Importa un archivo .json de flujo (formatos antiguos incluidos).  Devuelve el id."""
        try:
            fl = Flujo.cargar(ruta)
        except (ErrorFlujo, OSError, ValueError) as e:
            raise ErrorAlmacen("No se pudo leer el archivo: %s" % e) from e
        if not (fl.nombre or "").strip() or fl.nombre == "Flujo":
            fl.nombre = os.path.splitext(os.path.basename(ruta))[0]
        return self.importar_flujo(fl)

    def exportar(self, reporte_id, ruta):
        """Escribe el reporte como archivo .json (copia de seguridad o para compartir)."""
        self.cargar_flujo(reporte_id).guardar(ruta)
        return ruta

    # ---------------------------------------------- versiones (copias de seguridad)
    def guardar_version(self, reporte_id, motivo="", _con=None):
        """Guarda una copia del reporte tal como está ahora (para poder volver a ella).  Devuelve su id."""
        def hacer(c):
            r = c.execute("SELECT nombre, flujo FROM reportes WHERE id = ?", (int(reporte_id),)).fetchone()
            if r is None:
                raise ErrorAlmacen("No existe el reporte con número %s" % reporte_id)
            cur = c.execute("INSERT INTO versiones(reporte_id, cuando, motivo, nombre, flujo) VALUES (?, ?, ?, ?, ?)",
                            (int(reporte_id), _ahora(), motivo or "", r["nombre"], r["flujo"]))
            return cur.lastrowid
        if _con is not None:
            return hacer(_con)
        with self._transaccion() as c:
            return hacer(c)

    def versiones(self, reporte_id):
        """Copias guardadas de un reporte (la más reciente primero): dicts {id, reporte_id, cuando, motivo, nombre}."""
        filas = self._con().execute("SELECT id, reporte_id, cuando, motivo, nombre FROM versiones WHERE reporte_id = ? "
                                    "ORDER BY id DESC", (int(reporte_id),))
        return [dict(f) for f in filas]

    def flujo_de_version(self, version_id):
        f = self._con().execute("SELECT flujo FROM versiones WHERE id = ?", (int(version_id),)).fetchone()
        if f is None:
            raise ErrorAlmacen("No existe esa copia del reporte")
        return Flujo.desde_json(f["flujo"])

    def restaurar_version(self, version_id):
        """Vuelve el reporte a una copia anterior (antes guarda otra copia de cómo está ahora, por si acaso).
        El reporte conserva su nombre actual.  Devuelve el id del reporte."""
        fila = self._con().execute("SELECT * FROM versiones WHERE id = ?", (int(version_id),)).fetchone()
        if fila is None:
            raise ErrorAlmacen("No existe esa copia del reporte")
        rid = int(fila["reporte_id"])
        with self._transaccion() as c:
            actual = c.execute("SELECT nombre FROM reportes WHERE id = ?", (rid,)).fetchone()
            if actual is None:
                raise ErrorAlmacen("El reporte de esa copia ya no existe")
            self.guardar_version(rid, "antes de restaurar la copia del %s" % fila["cuando"], _con=c)
            texto = fila["flujo"]
            try:
                d = json.loads(texto)
                d["nombre"] = actual["nombre"]
                texto = json.dumps(d, ensure_ascii=False, indent=2)
            except ValueError:
                pass
            c.execute("UPDATE reportes SET flujo = ?, modificado = ? WHERE id = ?", (texto, _ahora(), rid))
        return rid

    def migrar_formato(self):
        """Actualiza al formato actual los reportes guardados con una versión anterior (junta los pasos de inicio
        de sesión del principio en un paso «Iniciar sesión»).  ANTES de cambiar cada reporte guarda una copia en
        `versiones` (se puede restaurar).  Un reporte que no se pueda convertir se deja como estaba.
        Devuelve [(id, nombre, mensajes, pasos_antes, pasos_despues)] de los reportes cuyos pasos cambiaron."""
        res = []
        filas = self._con().execute("SELECT id, nombre, flujo FROM reportes").fetchall()
        for f in filas:
            try:
                d = json.loads(f["flujo"])
                version = d.get("version", VERSION_FORMATO) if isinstance(d, dict) else VERSION_FORMATO
                if not isinstance(version, int) or version >= VERSION_FORMATO:
                    continue
                fl = Flujo.desde_dict(d)
                antes = len(fl.pasos)
                mensajes = migrar_flujo(fl)
                if fl.problemas() and not Flujo.desde_dict(d).problemas():
                    continue                       # la conversión no sería válida: se deja como estaba
                texto = fl.a_json()
                Flujo.desde_json(texto)            # comprobación: el resultado se puede volver a leer
            except (ValueError, TypeError, KeyError, AttributeError, ErrorFlujo):
                continue
            with self._transaccion() as c:
                self.guardar_version(f["id"], "antes de actualizar a la versión 2.3 (formato %d)" % VERSION_FORMATO,
                                     _con=c)
                c.execute("UPDATE reportes SET flujo = ? WHERE id = ?", (texto, f["id"]))
            if mensajes:
                res.append((f["id"], f["nombre"], mensajes, antes, len(fl.pasos)))
        return res

    META_NOMBRES_V35 = "nombres_descarga_v35"

    def migrar_nombres_descarga(self, forzar=False):
        """v3.5, UNA sola vez (marca `meta.nombres_descarga_v35`): los pasos «Descargar» que guardaban el archivo con el
        nombre fijo que da la web («report_xls{ext}», «DetallesVentasMayorista{ext}»: lo que dejaba la grabación hasta
        la 3.4) pasan a «{reporte} {hoy:%Y-%m-%d}{ext}» (el nombre completo del reporte y la fecha).  ANTES de cambiar
        cada reporte guarda una copia en `versiones` (Versiones anteriores → Restaurar).  Los nombres con plantillas
        (fechas, {opcion}…) no se tocan.  Devuelve [(id, nombre, [(paso, antes, después)])]."""
        from .flujo import usar_nombre_del_reporte
        if self.meta(self.META_NOMBRES_V35) == "1" and not forzar:
            return []
        res = []
        for f in self._con().execute("SELECT id, nombre, flujo FROM reportes WHERE eliminado IS NULL").fetchall():
            try:
                fl = Flujo.desde_json(f["flujo"])
                cambios = usar_nombre_del_reporte(fl)
                if not cambios:
                    continue
                fl.nombre = f["nombre"]
                texto = fl.a_json()
                Flujo.desde_json(texto)            # comprobación: el resultado se puede volver a leer
            except (ValueError, TypeError, KeyError, AttributeError, ErrorFlujo):
                continue
            with self._transaccion() as c:
                self.guardar_version(f["id"], "antes de poner el nombre del reporte a las descargas (v3.5)", _con=c)
                c.execute("UPDATE reportes SET flujo = ?, modificado = ? WHERE id = ?", (texto, _ahora(), f["id"]))
            res.append((f["id"], f["nombre"], cambios))
        self.poner_meta(self.META_NOMBRES_V35, "1")
        return res

    META_DESCARTADOS_V361 = "descartados_correo_v361"

    def olvidar_descartados_correo(self, forzar=False):
        """v3.6.1, UNA sola vez (marca `meta.descartados_correo_v361`): hasta la 3.6 el bot leía mal el remitente del
        correo abierto en Outlook (solo se ve el nombre) y DESCARTABA correos que sí coincidían, que después ya no se
        volvían a mirar.  Se olvidan los descartados para que la próxima revisión los mire otra vez.  Devuelve cuántos."""
        if self.meta(self.META_DESCARTADOS_V361) == "1" and not forzar:
            return 0
        with self._transaccion() as c:
            n = c.execute("DELETE FROM correos_procesados WHERE estado = 'descartado'").rowcount
        self.poner_meta(self.META_DESCARTADOS_V361, "1")
        return max(0, n or 0)

    # ---------------------------------------------------------------- accesos
    @staticmethod
    def _fila_acceso(f):
        d = dict(f)
        try:
            d["selectores"] = json.loads(d.get("selectores") or "[]")
        except ValueError:
            d["selectores"] = []
        return d

    def accesos_de(self, host):
        """Datos de acceso guardados de un sitio: [{host, clave, etiqueta, tipo, valor, secreto, selectores}]."""
        filas = self._con().execute("SELECT * FROM accesos WHERE host = ? ORDER BY orden, clave",
                                    ((host or "").lower(),))
        return [self._fila_acceso(f) for f in filas]

    def listar_accesos(self):
        filas = self._con().execute("SELECT * FROM accesos ORDER BY host, orden, clave")
        return [self._fila_acceso(f) for f in filas]

    def guardar_acceso(self, host, clave, etiqueta="", tipo="texto", valor=None, secreto=None, selectores=None):
        """Guarda (o cambia) un campo de acceso.  `tipo` «texto» guarda `valor`; «clave» solo el NOMBRE de la
        contraseña (`secreto`), nunca su valor."""
        host = (host or "").lower().strip()
        if not host or not clave:
            raise ErrorAlmacen("Falta el sitio o el campo")
        if tipo not in ("texto", "clave"):
            raise ErrorAlmacen("Tipo de campo no válido: %s" % tipo)
        with self._transaccion() as c:
            previo = c.execute("SELECT * FROM accesos WHERE host = ? AND clave = ?", (host, clave)).fetchone()
            if previo is not None:
                orden = previo["orden"]
            else:
                orden = c.execute("SELECT COUNT(*) FROM accesos WHERE host = ?", (host,)).fetchone()[0]
            lista = list(selectores or (json.loads(previo["selectores"] or "[]") if previo is not None else []))
            c.execute("INSERT OR REPLACE INTO accesos(host, clave, etiqueta, tipo, valor, secreto, selectores, orden, "
                      "modificado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (host, clave, etiqueta or (previo["etiqueta"] if previo is not None else clave), tipo,
                       valor if tipo == "texto" else None, secreto if tipo == "clave" else None,
                       json.dumps(lista, ensure_ascii=False), orden, _ahora()))

    def borrar_acceso(self, host, clave=None):
        """Borra un campo (o todos los del sitio si `clave` es None).  Las contraseñas se borran aparte."""
        with self._transaccion() as c:
            if clave is None:
                c.execute("DELETE FROM accesos WHERE host = ?", ((host or "").lower(),))
            else:
                c.execute("DELETE FROM accesos WHERE host = ? AND clave = ?", ((host or "").lower(), clave))

    # ------------------------------------------------- v3.0: estado de las contraseñas
    def marcar_clave_rechazada(self, secreto, host="", usuario="", cuando=None, motivo=""):
        """La página rechazó la contraseña guardada como `secreto` (solo se guarda el NOMBRE, la fecha y, desde la 3.3.1,
        lo que dijo la página: `motivo`)."""
        with self._transaccion() as c:
            c.execute("INSERT INTO estado_claves(secreto, host, usuario, rechazada, motivo) VALUES (?, ?, ?, ?, ?) "
                      "ON CONFLICT(secreto) DO UPDATE SET rechazada = excluded.rechazada, motivo = excluded.motivo, "
                      "host = CASE WHEN excluded.host <> '' THEN excluded.host ELSE estado_claves.host END, "
                      "usuario = CASE WHEN excluded.usuario <> '' THEN excluded.usuario ELSE estado_claves.usuario END",
                      (secreto, (host or "").lower(), usuario or "", _ahora(cuando), (motivo or "")[:300]))

    def marcar_clave_ok(self, secreto, host="", usuario=""):
        """La contraseña funcionó (o el usuario la cambió): se quita la marca de rechazada."""
        with self._transaccion() as c:
            c.execute("INSERT INTO estado_claves(secreto, host, usuario, ultimo_ok) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT(secreto) DO UPDATE SET rechazada = NULL, motivo = '', ultimo_ok = excluded.ultimo_ok, "
                      "host = CASE WHEN excluded.host <> '' THEN excluded.host ELSE estado_claves.host END, "
                      "usuario = CASE WHEN excluded.usuario <> '' THEN excluded.usuario ELSE estado_claves.usuario END",
                      (secreto, (host or "").lower(), usuario or "", _ahora()))

    def limpiar_rechazo_clave(self, secreto):
        with self._transaccion() as c:
            c.execute("UPDATE estado_claves SET rechazada = NULL, motivo = '' WHERE secreto = ?", (secreto,))

    def estado_clave(self, secreto):
        f = self._con().execute("SELECT * FROM estado_claves WHERE secreto = ?", (secreto,)).fetchone()
        return dict(f) if f else None

    def estados_claves(self):
        return [dict(f) for f in self._con().execute("SELECT * FROM estado_claves ORDER BY host, secreto")]

    # ------------------------------------------------------- v3.0: notificaciones
    @staticmethod
    def _fila_notificacion(f):
        d = dict(f)
        try:
            d["datos"] = json.loads(d.get("datos") or "{}")
        except ValueError:
            d["datos"] = {}
        d["leida"] = bool(d.get("leida"))
        return d

    def crear_notificacion(self, tipo, titulo, texto="", datos=None):
        """Crea un aviso de la aplicación.  Si ya hay uno sin leer con el mismo tipo y título, se actualiza (no se
        repite).  Devuelve su id."""
        datos_txt = json.dumps(datos or {}, ensure_ascii=False)
        with self._transaccion() as c:
            previo = c.execute("SELECT id FROM notificaciones WHERE tipo = ? AND titulo = ? AND leida = 0",
                               (tipo, titulo)).fetchone()
            if previo is not None:
                c.execute("UPDATE notificaciones SET cuando = ?, texto = ?, datos = ? WHERE id = ?",
                          (_ahora(), texto or "", datos_txt, previo["id"]))
                return previo["id"]
            cur = c.execute("INSERT INTO notificaciones(cuando, tipo, titulo, texto, datos) VALUES (?, ?, ?, ?, ?)",
                            (_ahora(), tipo, titulo, texto or "", datos_txt))
            c.execute("DELETE FROM notificaciones WHERE id NOT IN (SELECT id FROM notificaciones ORDER BY id DESC LIMIT 300)")
            return cur.lastrowid

    def notificaciones(self, limite=50, solo_no_leidas=False):
        sql = "SELECT * FROM notificaciones" + (" WHERE leida = 0" if solo_no_leidas else "") + " ORDER BY id DESC LIMIT ?"
        return [self._fila_notificacion(f) for f in self._con().execute(sql, (int(limite),))]

    def notificacion(self, nid):
        f = self._con().execute("SELECT * FROM notificaciones WHERE id = ?", (int(nid),)).fetchone()
        return self._fila_notificacion(f) if f else None

    def marcar_notificacion(self, nid, leida=True):
        with self._transaccion() as c:
            c.execute("UPDATE notificaciones SET leida = ? WHERE id = ?", (1 if leida else 0, int(nid)))

    def marcar_notificaciones_de(self, tipo, clave, valor):
        """Marca como leídas las notificaciones de un tipo cuyo dato `clave` vale `valor` (p. ej. al arreglarse)."""
        for n in self.notificaciones(limite=300, solo_no_leidas=True):
            if n["tipo"] == tipo and n["datos"].get(clave) == valor:
                self.marcar_notificacion(n["id"])

    def no_leidas(self):
        return self._con().execute("SELECT COUNT(*) FROM notificaciones WHERE leida = 0").fetchone()[0]

    # ------------------------------------------------------------- v3.0: ajustes
    def ajustes(self):
        d = dict(AJUSTES_DEFECTO)
        f = self._con().execute("SELECT valor FROM meta WHERE clave = 'ajustes'").fetchone()
        if f is not None:
            try:
                d.update(json.loads(f["valor"] or "{}"))
            except ValueError:
                pass
        return d

    def guardar_ajustes(self, cambios):
        d = self.ajustes()
        d.update({k: v for k, v in (cambios or {}).items() if k in AJUSTES_DEFECTO})
        with self._transaccion() as c:
            c.execute("INSERT OR REPLACE INTO meta(clave, valor) VALUES ('ajustes', ?)", (json.dumps(d, ensure_ascii=False),))
        return d

    # ----------------------------------------------------------- v3.3: vigilancias (varias)
    def _fila_vigilancia(self, f):
        if f is None:
            return None
        d = dict(f)
        try:
            d["valores"] = json.loads(d.get("valores") or "{}")
        except ValueError:
            d["valores"] = {}
        d["tipo"] = "pagina" if d.get("pagina_id") is not None else "reporte"
        for k in ("activa", "auto_descargar", "descargar_sin_fecha"):
            d[k] = int(d.get(k) or 0)
        # v3.4: la programación que vale (la guardada o, si no hay, la de la frecuencia antigua), ya leída
        d["programacion"] = horario.de_vigilancia(d)
        return d

    _SELECT_VIG = ("SELECT v.*, COALESCE(r.nombre, p.nombre) AS objetivo FROM vigilancias v "
                   "LEFT JOIN reportes r ON r.id = v.reporte_id LEFT JOIN paginas p ON p.id = v.pagina_id ")

    def vigilancia_id(self, vigilancia_id):
        """La vigilancia número `vigilancia_id` (dict con `tipo` reporte|pagina, `objetivo` = nombre del reporte o de la
        Página, `valores` ya leído) o None."""
        f = self._con().execute(self._SELECT_VIG + "WHERE v.id = ?", (int(vigilancia_id),)).fetchone()
        return self._fila_vigilancia(f)

    def lista_vigilancias(self, reporte_id=None, pagina_id=None, solo_activas=False, tipo=None):
        """Todas las vigilancias (de los reportes que no están en la papelera y de las Páginas), o las de un reporte o
        una Página, ordenadas por el nombre del reporte/Página y por id."""
        donde = ["(v.reporte_id IS NULL OR (r.id IS NOT NULL AND r.eliminado IS NULL))",
                 "(v.pagina_id IS NULL OR p.id IS NOT NULL)"]
        args = []
        if reporte_id is not None:
            donde.append("v.reporte_id = ?")
            args.append(int(reporte_id))
        if pagina_id is not None:
            donde.append("v.pagina_id = ?")
            args.append(int(pagina_id))
        if tipo == "reporte":
            donde.append("v.reporte_id IS NOT NULL")
        elif tipo == "pagina":
            donde.append("v.pagina_id IS NOT NULL")
        if solo_activas:
            donde.append("v.activa = 1")
        filas = self._con().execute(self._SELECT_VIG + "WHERE " + " AND ".join(donde) +
                                    " ORDER BY objetivo COLLATE NOCASE, v.id", args)
        return [self._fila_vigilancia(f) for f in filas]

    @staticmethod
    def _validar_vigilancia(d):
        if d.get("frecuencia", "") not in FRECUENCIAS_VIGILANCIA:
            raise ErrorAlmacen("Frecuencia no válida: %s" % d.get("frecuencia"))

    @staticmethod
    def _sincronizar_programacion(campos):
        """v3.4: con `programacion` (dict o JSON) la frecuencia pasa a 'programa' (o '' si no tiene reglas) y se
        olvidan `cada_horas`/`hora`; con solo la frecuencia antigua (API de la 3.3) se borra la programación guardada,
        para que valga esa frecuencia."""
        campos = dict(campos)
        if "programacion" in campos:
            try:
                p = horario.normalizar(campos["programacion"])
            except horario.ErrorHorario as e:
                raise ErrorAlmacen(str(e))
            campos["programacion"] = horario.a_json(p)
            campos["frecuencia"] = "programa" if p["reglas"] else ""
            campos["cada_horas"] = None
            campos["hora"] = ""
        elif "frecuencia" in campos:
            campos["programacion"] = ""
        return campos

    @staticmethod
    def _valores_vig(d):
        out = {}
        for k in CAMPOS_VIGILANCIA:
            if k not in d:
                continue
            v = d[k]
            if k == "valores":
                v = json.dumps(v or {}, ensure_ascii=False, sort_keys=True) if not isinstance(v, str) else (v or "{}")
            elif k in ("activa", "auto_descargar", "descargar_sin_fecha"):
                v = 1 if v else 0
            elif k == "cada_horas":
                v = int(v) if v else None
            elif k == "paso":
                v = int(v) if v is not None else None
            else:
                v = "" if v is None else str(v)
            out[k] = v
        return out

    def crear_vigilancia(self, reporte_id=None, paso=None, pagina_id=None, filtro=None, **campos):
        """Crea una vigilancia de (reporte + paso) o de (Página + filtro).  `campos`: favorito, valores, nombre, activa,
        auto_descargar, descargar_sin_fecha, frecuencia, cada_horas, hora.  Devuelve su id.  Si es la primera de esa
        lista sin otros valores y hay opciones vistas de la 3.2 (tablas «_v32»), se parte de ellas (la referencia)."""
        if (reporte_id is None) == (pagina_id is None):
            raise ErrorAlmacen("Una vigilancia es de un reporte o de una página")
        if reporte_id is not None:
            if self.obtener(reporte_id) is None:
                raise ErrorAlmacen("No existe el reporte con número %s" % reporte_id)
            if paso is None:
                raise ErrorAlmacen("Elige el paso que se vigila")
        else:
            if self.obtener_pagina(pagina_id) is None:
                raise ErrorAlmacen("No existe la página número %s" % pagina_id)
            if not filtro:
                raise ErrorAlmacen("Elige el filtro que se vigila")
        campos.setdefault("activa", True)
        campos = self._sincronizar_programacion(campos)
        d = self._valores_vig(dict(campos, paso=paso, filtro=filtro or ""))
        self._validar_vigilancia(d)
        d["reporte_id"] = int(reporte_id) if reporte_id is not None else None
        d["pagina_id"] = int(pagina_id) if pagina_id is not None else None
        d["creada"] = _ahora()
        cols = list(d)
        with self._transaccion() as c:
            cur = c.execute("INSERT INTO vigilancias(%s) VALUES (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                            [d[k] for k in cols])
            vid = cur.lastrowid
            self._sembrar_v32(c, vid, d)
        return vid

    def _sembrar_v32(self, c, vid, d):
        """La primera vigilancia de una lista (sin favorito ni valores) parte de las opciones que ya se habían visto con
        la 3.2 (si las hay), para que la próxima revisión no sea «la primera»."""
        if d.get("favorito") or (d.get("valores") or "{}") != "{}":
            return
        tablas = self._tablas(c)
        if d["reporte_id"] is not None and "opciones_vistas_v32" in tablas:
            fuente, donde, args = "opciones_vistas_v32", "reporte_id = ? AND paso = ?", (d["reporte_id"], d["paso"])
            otras = "reporte_id = ? AND paso = ?"
        elif d["pagina_id"] is not None and "opciones_vistas_paginas_v32" in tablas:
            fuente, donde, args = "opciones_vistas_paginas_v32", "pagina_id = ? AND filtro = ?", (d["pagina_id"], d["filtro"])
            otras = "pagina_id = ? AND filtro = ?"
        else:
            return
        if c.execute("SELECT COUNT(*) FROM vigilancias WHERE id <> ? AND " + otras, (vid,) + args).fetchone()[0]:
            return
        columnas = "texto, primera_vez, orden, nueva, descargada, archivos, sin_orden, novedad"
        c.execute("INSERT OR IGNORE INTO opciones_vigiladas(vigilancia_id, %s) SELECT ?, %s FROM %s WHERE %s"
                  % (columnas, columnas, fuente, donde), (vid,) + args)

    def actualizar_vigilancia(self, vigilancia_id, **campos):
        """Cambia los datos de una vigilancia (los que se pasen).  Si cambia lo que se vigila (paso/filtro, favorito o
        valores), sus opciones vistas se olvidan: la próxima revisión vuelve a ser la referencia."""
        v = self.vigilancia_id(vigilancia_id)
        if v is None:
            raise ErrorAlmacen("No existe la vigilancia número %s" % vigilancia_id)
        d = self._valores_vig(self._sincronizar_programacion(campos))
        if not d:
            return v
        self._validar_vigilancia(dict(v, **d))
        antes = self._valores_vig({k: v[k] for k in ("paso", "filtro", "favorito", "valores")})
        cambia = any(k in d and d[k] != antes[k] for k in antes)
        with self._transaccion() as c:
            c.execute("UPDATE vigilancias SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in d),
                      list(d.values()) + [int(vigilancia_id)])
            if cambia:
                c.execute("DELETE FROM opciones_vigiladas WHERE vigilancia_id = ?", (int(vigilancia_id),))
        return self.vigilancia_id(vigilancia_id)

    def renumerar_pasos(self, reporte_id, desde, quitados):
        """v3.3.1: se quitaron `quitados` pasos del reporte justo después del paso `desde` (p. ej. al convertir «abrir la
        lista + clic en la opción» en un solo «Elegir opción»): las vigilancias y las opciones guardadas de los pasos de
        después se renumeran (sin olvidar lo que ya habían visto: siguen vigilando la misma lista)."""
        if not quitados:
            return
        rid, desde, q = int(reporte_id), int(desde), int(quitados)
        with self._transaccion() as c:
            c.execute("UPDATE vigilancias SET paso = paso - ? WHERE reporte_id = ? AND paso > ?", (q, rid, desde + q))
            c.execute("DELETE FROM opciones_filtro WHERE reporte_id = ? AND paso > ? AND paso <= ?", (rid, desde, desde + q))
            # (en dos pasos para no chocar con la clave primaria mientras se renumera)
            c.execute("UPDATE opciones_filtro SET paso = -(paso - ?) WHERE reporte_id = ? AND paso > ?", (q, rid, desde + q))
            c.execute("UPDATE opciones_filtro SET paso = -paso WHERE reporte_id = ? AND paso < 0", (rid,))

    def borrar_vigilancia_id(self, vigilancia_id):
        with self._transaccion() as c:
            c.execute("DELETE FROM opciones_vigiladas WHERE vigilancia_id = ?", (int(vigilancia_id),))
            c.execute("DELETE FROM vigilancias WHERE id = ?", (int(vigilancia_id),))

    def anotar_revision_id(self, vigilancia_id, resultado):
        with self._transaccion() as c:
            c.execute("UPDATE vigilancias SET ultima_revision = ?, ultimo_resultado = ? WHERE id = ?",
                      (_ahora(), (resultado or "")[:300], int(vigilancia_id)))

    @staticmethod
    def _clave_vig(vigilancia_id):
        return (("vigilancia_id", int(vigilancia_id)),)

    def opciones_de_vigilancia(self, vigilancia_id):
        return self._vistas("opciones_vigiladas", self._clave_vig(vigilancia_id))

    def registrar_opciones_vigilancia(self, vigilancia_id, textos, detalle=False):
        """Anota las opciones leídas por esa vigilancia (regla de novedad de la 3.1, ver `registrar_opciones`)."""
        return self._registrar_vistas("opciones_vigiladas", self._clave_vig(vigilancia_id), textos, detalle)

    def marcar_descargada_vigilancia(self, vigilancia_id, texto, archivos=None):
        self._marcar_descargada("opciones_vigiladas", self._clave_vig(vigilancia_id), texto, archivos)

    def pendientes_vigilancia(self, vigilancia_id, incluir_sin_orden=False):
        return [o["texto"] for o in self.opciones_de_vigilancia(vigilancia_id) if o["nueva"] and not o["descargada"]
                and (incluir_sin_orden or not o["sin_orden"])]

    def novedades_vigilancia(self, vigilancia_id, dias=7):
        return self._novedades("opciones_vigiladas", self._clave_vig(vigilancia_id), dias)

    # --- compatibilidad (3.0–3.2): «la» vigilancia de un reporte = la primera (la de sin otros valores, si la hay)
    def _principal(self, reporte_id=None, paso=None, pagina_id=None, filtro=None):
        if reporte_id is not None:
            donde, args = "reporte_id = ?", [int(reporte_id)]
            if paso is not None:
                donde += " AND paso = ?"
                args.append(int(paso))
        else:
            donde, args = "pagina_id = ?", [int(pagina_id)]
            if filtro is not None:
                donde += " AND filtro = ?"
                args.append(str(filtro))
        f = self._con().execute("SELECT id FROM vigilancias WHERE %s ORDER BY (favorito = '' AND valores = '{}') DESC, id "
                                "LIMIT 1" % donde, args).fetchone()
        return f["id"] if f else None

    def _principal_o_nueva(self, reporte_id=None, paso=None, pagina_id=None, filtro=None):
        vid = self._principal(reporte_id, paso, pagina_id, filtro)
        if vid is None:          # (compatibilidad: anotar opciones sin vigilancia crea una, desactivada)
            vid = self.crear_vigilancia(reporte_id=reporte_id, paso=paso, pagina_id=pagina_id, filtro=filtro, activa=False)
        return vid

    def vigilancia(self, reporte_id):
        """(Compatibilidad) la vigilancia principal de un reporte (o None)."""
        vid = self._principal(reporte_id=reporte_id)
        return self.vigilancia_id(vid) if vid else None

    # ----------------------------------------------------------- v3.4: programaciones (reportes, Páginas, correos…)
    def guardar_programacion(self, clave, programacion, tarea=""):
        """Guarda la programación (dict o JSON, se comprueba) con la que se creó la tarea de Windows de `clave`
        («reporte:3», «pagina:2», «pagina:2:Favorito», «correo:5»…) y el nombre de la tarea."""
        try:
            texto = horario.a_json(programacion)
        except horario.ErrorHorario as e:
            raise ErrorAlmacen(str(e))
        with self._transaccion() as c:
            c.execute("INSERT OR REPLACE INTO programaciones(clave, programacion, tarea, actualizado) VALUES (?, ?, ?, ?)",
                      (str(clave), texto, tarea or "", _ahora()))

    def programacion(self, clave):
        """{clave, programacion (dict), tarea, actualizado} o None."""
        f = self._con().execute("SELECT * FROM programaciones WHERE clave = ?", (str(clave),)).fetchone()
        if f is None:
            return None
        d = dict(f)
        try:
            d["programacion"] = horario.desde_json(d["programacion"]) or horario.vacia()
        except horario.ErrorHorario:
            d["programacion"] = horario.vacia()
        return d

    def lista_programaciones(self, prefijo=""):
        filas = self._con().execute("SELECT clave FROM programaciones WHERE clave LIKE ? ORDER BY clave",
                                    ((prefijo or "") + "%",)).fetchall()
        return [self.programacion(f[0]) for f in filas]

    def borrar_programacion(self, clave):
        with self._transaccion() as c:
            c.execute("DELETE FROM programaciones WHERE clave = ?", (str(clave),))

    # ----------------------------------------------------------- v3.7: lo que se ejecuta fuera de la interfaz
    @staticmethod
    def _valores_en_curso(campos):
        out = {}
        for k, v in campos.items():
            if k not in CAMPOS_EN_CURSO:
                raise ErrorAlmacen("Campo no válido: %s" % k)
            if k == "estado" and v not in ESTADOS_EN_CURSO:
                raise ErrorAlmacen("Estado no válido: %s" % v)
            if k == "pedido" and v not in PEDIDOS_EN_CURSO:
                raise ErrorAlmacen("Petición no válida: %s" % v)
            if k in ("paso", "total"):
                v = max(0, int(v or 0))
            elif k == "visible":
                v = 1 if v else 0
            elif k in ("objetivo_id", "pid"):
                v = int(v) if v not in (None, "") else None
            else:
                v = "" if v is None else str(v)[:500]
            out[k] = v
        return out

    def crear_en_curso(self, **campos):
        """v3.7: apunta una ejecución que empieza (o espera para empezar) fuera de la interfaz.  Devuelve su id."""
        d = self._valores_en_curso(dict({"estado": "en_curso", "pid": os.getpid()}, **campos))
        ahora = _ahora()
        d.update(inicio=ahora, actualizado=ahora)
        with self._transaccion() as c:
            cur = c.execute("INSERT INTO en_curso(%s) VALUES (%s)" % (", ".join(d), ", ".join("?" * len(d))),
                            list(d.values()))
            return cur.lastrowid

    def actualizar_en_curso(self, fila_id, empezar=False, **campos):
        """Cambia campos de la fila.  `empezar=True`: pasa de «esperando» a «en curso» (el tiempo cuenta desde ahora)."""
        d = self._valores_en_curso(campos)
        d["actualizado"] = _ahora()
        if empezar:
            d.update(estado="en_curso", inicio=d["actualizado"])
        with self._transaccion() as c:
            c.execute("UPDATE en_curso SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in d),
                      list(d.values()) + [int(fila_id)])

    @staticmethod
    def _fila_en_curso(f):
        if f is None:
            return None
        d = dict(f)
        d["visible"] = bool(d.get("visible"))
        d["terminado"] = d["estado"] not in ("esperando", "en_curso")
        try:
            ini = datetime.datetime.strptime(d["inicio"], FORMATO_FECHA)
            fin = datetime.datetime.strptime(d["actualizado"], FORMATO_FECHA) if d["terminado"] else \
                datetime.datetime.now()
            d["segundos"] = max(0, int((fin - ini).total_seconds()))
        except (TypeError, ValueError):
            d["segundos"] = 0
        return d

    def en_curso_id(self, fila_id):
        f = self._con().execute("SELECT * FROM en_curso WHERE id = ?", (int(fila_id),)).fetchone()
        return self._fila_en_curso(f)

    def pedir_en_curso(self, fila_id, pedido):
        """Lo que pide el usuario (ventanita o interfaz): detener, cancelar (mientras espera), ya, en_vivo.  False si ya
        no está en marcha."""
        f = self.en_curso_id(fila_id)
        if f is None or f["terminado"]:
            return False
        self.actualizar_en_curso(fila_id, pedido=pedido)
        return True

    def lista_en_curso(self, limpiar=True, vivo=None, ahora=None):
        """Lo que se está ejecutando fuera de la interfaz (y lo que terminó hace menos de
        `EN_CURSO_GUARDAR_TERMINADOS` s).  Con `limpiar`, borra las filas de procesos que ya no existen (se cerraron sin
        avisar: apagado, error…) y las terminadas viejas."""
        vivo = vivo or pid_vivo
        ahora = ahora or datetime.datetime.now()
        res, borrar = [], []
        for f in self._con().execute("SELECT * FROM en_curso ORDER BY id").fetchall():
            d = self._fila_en_curso(f)
            try:
                act = datetime.datetime.strptime(d["actualizado"], FORMATO_FECHA)
            except (TypeError, ValueError):
                act = ahora
            if d["terminado"]:
                if (ahora - act).total_seconds() > EN_CURSO_GUARDAR_TERMINADOS:
                    borrar.append(d["id"])
                    continue
            elif not vivo(d["pid"]) or (ahora - act).total_seconds() > EN_CURSO_MAX_HORAS * 3600:
                borrar.append(d["id"])
                continue
            res.append(d)
        if limpiar and borrar:
            with self._transaccion() as c:
                c.executemany("DELETE FROM en_curso WHERE id = ?", [(i,) for i in borrar])
        return res

    def borrar_en_curso(self, fila_id):
        with self._transaccion() as c:
            c.execute("DELETE FROM en_curso WHERE id = ?", (int(fila_id),))

    def vigilancias(self):
        """(Compatibilidad) las vigilancias de reportes, con el nombre del reporte en `nombre`."""
        res = []
        for v in self.lista_vigilancias(tipo="reporte"):
            res.append(dict(v, nombre=v["objetivo"]))
        return res

    def guardar_vigilancia(self, reporte_id, paso, activa=True, auto_descargar=False, frecuencia="", cada_horas=None,
                           hora="", descargar_sin_fecha=False, vigilancia_id=None):
        """(Compatibilidad 3.0–3.2) crea o cambia la vigilancia principal del reporte (o la `vigilancia_id`)."""
        if self.obtener(reporte_id) is None:
            raise ErrorAlmacen("No existe el reporte con número %s" % reporte_id)
        campos = dict(activa=activa, auto_descargar=auto_descargar, frecuencia=frecuencia or "", cada_horas=cada_horas,
                      hora=hora or "", descargar_sin_fecha=descargar_sin_fecha)
        self._validar_vigilancia(campos)
        vid = vigilancia_id or self._principal(reporte_id=reporte_id)
        if vid is None:
            return self.crear_vigilancia(reporte_id=reporte_id, paso=paso, **campos)
        self.actualizar_vigilancia(vid, paso=paso, **campos)
        return vid

    def borrar_vigilancia(self, reporte_id):
        """(Compatibilidad) borra todas las vigilancias del reporte."""
        for v in self.lista_vigilancias(reporte_id=reporte_id):
            self.borrar_vigilancia_id(v["id"])

    def anotar_revision(self, reporte_id, resultado):
        vid = self._principal(reporte_id=reporte_id)
        if vid:
            self.anotar_revision_id(vid, resultado)

    def opciones_vistas(self, reporte_id, paso):
        vid = self._principal(reporte_id=reporte_id, paso=paso)
        return self.opciones_de_vigilancia(vid) if vid else []

    def _vistas(self, tabla, claves):
        donde = " AND ".join("%s = ?" % c for c, _v in claves)
        filas = self._con().execute("SELECT * FROM %s WHERE %s ORDER BY orden, texto" % (tabla, donde),
                                    [v for _c, v in claves])
        res = []
        for f in filas:
            d = dict(f)
            try:
                d["archivos"] = json.loads(d.get("archivos") or "[]")
            except ValueError:
                d["archivos"] = []
            d["nueva"] = bool(d["nueva"])
            d["sin_orden"] = bool(d.get("sin_orden"))
            res.append(d)
        return res

    def registrar_opciones(self, reporte_id, paso, textos, detalle=False):
        """Anota las opciones leídas del filtro vigilado.  Devuelve (nuevas, primera_vez); con `detalle=True`, un dict
        {nuevas, primera, recientes, sin_orden, historicas}.

        v3.1, regla de novedad: una opción que se ve por primera vez solo es «nueva» (aviso, descarga automática) si es
        MÁS RECIENTE (`clave_reciente`) que la más reciente de las ya conocidas antes de esta revisión.  Las más antiguas
        que aparecen por primera vez (la web añadió historial, o se leyó entera una lista virtual) se apuntan en silencio
        como históricas.  Si la opción no lleva fecha, año ni número (o no hay ninguna conocida con la que compararla)
        cuenta como nueva por ser desconocida, pero queda marcada `sin_orden`: no se descarga sola salvo que la
        vigilancia tenga «descargar también las opciones sin fecha».  La primera revisión es la referencia.
        (v3.3: en la vigilancia principal de ese paso del reporte; ver `registrar_opciones_vigilancia`.)"""
        return self.registrar_opciones_vigilancia(self._principal_o_nueva(reporte_id=reporte_id, paso=paso), textos,
                                                  detalle)

    def _registrar_vistas(self, tabla, claves, textos, detalle=False):
        conocidas = self._vistas(tabla, claves)
        vistas = {o["texto"] for o in conocidas}
        primera = not vistas
        conocidas_claves = [clave_reciente(o["texto"]) for o in conocidas if es_reconocible(o["texto"])]
        referencia = max(conocidas_claves) if conocidas_claves else None
        recientes, sin_orden, historicas = [], [], []
        for t in textos:
            if t in vistas or t in recientes or t in sin_orden or t in historicas:
                continue
            if primera:
                historicas.append(t)
            elif es_reconocible(t) and referencia is not None:
                (recientes if clave_reciente(t) > referencia else historicas).append(t)
            else:
                sin_orden.append(t)
        ahora = _ahora()
        cols = [c for c, _v in claves]
        vals = [v for _c, v in claves]
        donde = " AND ".join("%s = ?" % c for c in cols)
        with self._transaccion() as c:
            for k, t in enumerate(textos):
                if t in vistas:
                    c.execute("UPDATE %s SET orden = ? WHERE %s AND texto = ?" % (tabla, donde), [k] + vals + [t])
                else:
                    nueva = t in recientes or t in sin_orden
                    c.execute("INSERT OR IGNORE INTO %s(%s, texto, primera_vez, orden, nueva, sin_orden, novedad) "
                              "VALUES (%s, ?, ?, ?, ?, ?, ?)" % (tabla, ", ".join(cols), ", ".join("?" * len(cols))),
                              vals + [t, ahora, k, 1 if nueva else 0, 1 if t in sin_orden else 0, ahora if nueva else None])
        nuevas = [t for t in dict.fromkeys(textos) if t in recientes or t in sin_orden]
        if detalle:
            return {"nuevas": nuevas, "primera": primera, "recientes": recientes, "sin_orden": sin_orden,
                    "historicas": [] if primera else historicas}
        return nuevas, primera

    def marcar_descargada(self, reporte_id, paso, texto, archivos=None):
        vid = self._principal(reporte_id=reporte_id, paso=paso)
        if vid:
            self.marcar_descargada_vigilancia(vid, texto, archivos)

    def _marcar_descargada(self, tabla, claves, texto, archivos=None):
        donde = " AND ".join("%s = ?" % c for c, _v in claves)
        with self._transaccion() as c:
            c.execute("UPDATE %s SET descargada = ?, nueva = 0, archivos = ? WHERE %s AND texto = ?" % (tabla, donde),
                      [_ahora(), json.dumps([os.path.basename(a) for a in archivos or []], ensure_ascii=False)]
                      + [v for _c, v in claves] + [texto])

    def pendientes_de_descargar(self, reporte_id, paso, incluir_sin_orden=False):
        """Opciones nuevas que todavía no se descargaron (las «sin orden» —sin fecha ni número— solo si se pide)."""
        vid = self._principal(reporte_id=reporte_id, paso=paso)
        return self.pendientes_vigilancia(vid, incluir_sin_orden) if vid else []

    def novedades(self, reporte_id, paso, dias=7):
        """Textos detectados como novedad (más recientes que lo anterior) en los últimos `dias` días, en TODAS las
        vigilancias de ese paso del reporte (v3.3: se juntan)."""
        res = []
        for v in self.lista_vigilancias(reporte_id=reporte_id):
            if v["paso"] == int(paso):
                res += [t for t in self.novedades_vigilancia(v["id"], dias) if t not in res]
        return res

    def _novedades(self, tabla, claves, dias=7):
        desde = _ahora(datetime.datetime.now() - datetime.timedelta(days=dias))
        donde = " AND ".join("%s = ?" % c for c, _v in claves)
        filas = self._con().execute("SELECT texto FROM %s WHERE %s AND novedad IS NOT NULL AND novedad >= ?" % (tabla, donde),
                                    [v for _c, v in claves] + [desde])
        return [f["texto"] for f in filas]

    # --------------------------------------------- v3.1: opciones de los filtros
    @staticmethod
    def clave_padres(padres):
        """Clave (JSON) de una combinación de filtros anteriores {paso: texto elegido}."""
        if isinstance(padres, str):
            return padres
        items = sorted(((int(k), str(v)) for k, v in (padres or {}).items()), key=lambda x: x[0])
        return json.dumps([[k, v] for k, v in items], ensure_ascii=False)

    def guardar_opciones_filtro(self, reporte_id, paso, opciones, padres=None, firma="", fuente=""):
        """Guarda las opciones conocidas del filtro (paso) para esa combinación de los filtros anteriores (`padres`)."""
        if reporte_id is None or opciones is None:
            return
        opciones = list(dict.fromkeys(str(o) for o in opciones if str(o).strip()))
        with self._transaccion() as c:
            if c.execute("SELECT 1 FROM reportes WHERE id = ?", (int(reporte_id),)).fetchone() is None:
                return
            c.execute("INSERT OR REPLACE INTO opciones_filtro(reporte_id, paso, padres, firma, opciones, actualizado, fuente) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (int(reporte_id), int(paso), self.clave_padres(padres), firma or "",
                       json.dumps(opciones, ensure_ascii=False), _ahora(), fuente or ""))

    def opciones_filtro(self, reporte_id, paso=None):
        """Filas de `opciones_filtro` de un reporte (o de un paso), la más reciente primero:
        {paso, padres: {paso: texto}, firma, opciones, actualizado, fuente}."""
        sql = "SELECT rowid AS fila, * FROM opciones_filtro WHERE reporte_id = ?"
        args = [int(reporte_id)]
        if paso is not None:
            sql += " AND paso = ?"
            args.append(int(paso))
        res = []
        for f in self._con().execute(sql + " ORDER BY actualizado DESC, fila DESC", args):
            d = dict(f)
            try:
                d["opciones"] = json.loads(d["opciones"] or "[]")
            except ValueError:
                d["opciones"] = []
            try:
                d["padres"] = {int(k): v for k, v in json.loads(d["padres"] or "[]")}
            except (ValueError, TypeError):
                d["padres"] = {}
            res.append(d)
        return res

    def guardar_opciones_leidas(self, reporte_id, res, fuente):
        """Guarda las listas que leyó una ejecución (`ResultadoEjecucion.opciones_leidas`)."""
        for paso, d in (getattr(res, "opciones_leidas", None) or {}).items():
            self.guardar_opciones_filtro(reporte_id, paso, d.get("opciones"), d.get("padres"), d.get("firma", ""), fuente)

    # ----------------------------------------------------------------- v3.0: mapas
    def guardar_mapa(self, reporte_id, url, alcance, filtros):
        with self._transaccion() as c:
            cur = c.execute("INSERT INTO mapas(reporte_id, cuando, url, alcance, filtros) VALUES (?, ?, ?, ?, ?)",
                            (int(reporte_id) if reporte_id is not None else None, _ahora(), url or "", alcance or "",
                             json.dumps(filtros or [], ensure_ascii=False)))
            return cur.lastrowid

    def mapas(self, reporte_id=None, limite=20):
        if reporte_id is None:
            filas = self._con().execute("SELECT * FROM mapas WHERE reporte_id IS NULL ORDER BY id DESC LIMIT ?", (int(limite),))
        else:
            filas = self._con().execute("SELECT * FROM mapas WHERE reporte_id = ? ORDER BY id DESC LIMIT ?",
                                        (int(reporte_id), int(limite)))
        res = []
        for f in filas:
            d = dict(f)
            try:
                d["filtros"] = json.loads(d["filtros"] or "[]")
            except ValueError:
                d["filtros"] = []
            res.append(d)
        return res

    def ultimo_mapa(self, reporte_id):
        m = self.mapas(reporte_id, limite=1)
        return m[0] if m else None

    def mapa(self, mapa_id):
        f = self._con().execute("SELECT * FROM mapas WHERE id = ?", (int(mapa_id),)).fetchone()
        if f is None:
            return None
        d = dict(f)
        try:
            d["filtros"] = json.loads(d["filtros"] or "[]")
        except ValueError:
            d["filtros"] = []
        return d

    # ------------------------------------------------------------------ v3.2: meta
    def meta(self, clave, defecto=None):
        f = self._con().execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
        return f["valor"] if f is not None else defecto

    def poner_meta(self, clave, valor):
        with self._transaccion() as c:
            c.execute("INSERT OR REPLACE INTO meta(clave, valor) VALUES (?, ?)", (clave, str(valor)))

    # -------------------------------------------------------------- v3.2: Páginas
    @staticmethod
    def _fila_pagina(f):
        d = dict(f)
        try:
            d["data"] = json.loads(d.get("data") or "{}")
        except ValueError:
            d["data"] = {}
        if not isinstance(d["data"], dict):
            d["data"] = {}
        return d

    def listar_paginas(self):
        """Páginas guardadas, por nombre, con su última ejecución: dicts {id, nombre, host, url, data, ultima, resultado}."""
        filas = self._con().execute(
            "SELECT p.*, (SELECT e.cuando FROM ejecuciones e WHERE e.pagina_id = p.id ORDER BY e.id DESC LIMIT 1) AS ultima, "
            "(SELECT e.resultado FROM ejecuciones e WHERE e.pagina_id = p.id ORDER BY e.id DESC LIMIT 1) AS resultado, "
            "(SELECT e.mensaje FROM ejecuciones e WHERE e.pagina_id = p.id ORDER BY e.id DESC LIMIT 1) AS mensaje "
            "FROM paginas p ORDER BY p.nombre COLLATE NOCASE")
        return [self._fila_pagina(f) for f in filas]

    def obtener_pagina(self, pagina_id):
        f = self._con().execute("SELECT * FROM paginas WHERE id = ?", (int(pagina_id),)).fetchone()
        return self._fila_pagina(f) if f else None

    def obtener_pagina_por_nombre(self, nombre):
        f = self._con().execute("SELECT * FROM paginas WHERE nombre = ? COLLATE NOCASE", ((nombre or "").strip(),)).fetchone()
        return self._fila_pagina(f) if f else None

    def resolver_pagina(self, ref):
        """Id de una Página a partir de su número o su nombre (lanza ErrorAlmacen si no existe)."""
        r = None
        if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
            r = self.obtener_pagina(int(ref))
        if r is None:
            r = self.obtener_pagina_por_nombre(str(ref))
        if r is None:
            raise ErrorAlmacen("No existe la página «%s» (mira la lista de Páginas)" % ref)
        return r["id"]

    def nombre_pagina_libre(self, nombre):
        nombre = validar_nombre(nombre)
        libre, n = nombre, 2
        while self.obtener_pagina_por_nombre(libre) is not None:
            libre = "%s (%d)" % (nombre, n)
            n += 1
        return libre

    def guardar_pagina(self, nombre, data, pagina_id=None, host="", url=""):
        """Crea (sin id) o actualiza una Página.  `data` = el diccionario de `webbot.paginas`.  Devuelve el id."""
        nombre = validar_nombre(nombre)
        texto = json.dumps(data or {}, ensure_ascii=False)
        ahora = _ahora()
        try:
            with self._transaccion() as c:
                if pagina_id is None:
                    cur = c.execute("INSERT INTO paginas(nombre, host, url, creado, modificado, data) VALUES (?, ?, ?, ?, ?, ?)",
                                    (nombre, host or "", url or "", ahora, ahora, texto))
                    return cur.lastrowid
                cur = c.execute("UPDATE paginas SET nombre = ?, host = ?, url = ?, modificado = ?, data = ? WHERE id = ?",
                                (nombre, host or "", url or "", ahora, texto, int(pagina_id)))
                if cur.rowcount == 0:
                    raise ErrorAlmacen("La página ya no existe")
                return int(pagina_id)
        except sqlite3.IntegrityError as e:
            raise ErrorAlmacen("Ya existe una página llamada «%s». Elige otro nombre." % nombre) from e

    def borrar_pagina(self, pagina_id):
        """Borra la Página, sus opciones guardadas y su vigilancia (el historial de sus ejecuciones se borra también)."""
        with self._transaccion() as c:
            cur = c.execute("DELETE FROM paginas WHERE id = ?", (int(pagina_id),))
            if cur.rowcount == 0:
                raise ErrorAlmacen("No existe la página número %s" % pagina_id)
            c.execute("DELETE FROM opciones_vigiladas WHERE vigilancia_id IN (SELECT id FROM vigilancias WHERE pagina_id = ?)",
                      (int(pagina_id),))
            for tabla in ("opciones_pagina", "vigilancias", "ejecuciones"):
                c.execute("DELETE FROM %s WHERE pagina_id = ?" % tabla, (int(pagina_id),))

    # opciones de los filtros de una Página (por combinación de los filtros anteriores: {id del filtro: texto})
    @staticmethod
    def clave_padres_pagina(padres):
        if isinstance(padres, str):
            return padres
        return json.dumps(sorted([str(k), str(v)] for k, v in (padres or {}).items()), ensure_ascii=False)

    def guardar_opciones_pagina(self, pagina_id, filtro, opciones, padres=None, fuente=""):
        if pagina_id is None or opciones is None:
            return
        opciones = list(dict.fromkeys(str(o) for o in opciones if str(o).strip()))
        with self._transaccion() as c:
            if c.execute("SELECT 1 FROM paginas WHERE id = ?", (int(pagina_id),)).fetchone() is None:
                return
            c.execute("INSERT OR REPLACE INTO opciones_pagina(pagina_id, filtro, padres, opciones, actualizado, fuente) "
                      "VALUES (?, ?, ?, ?, ?, ?)", (int(pagina_id), str(filtro), self.clave_padres_pagina(padres),
                                                    json.dumps(opciones, ensure_ascii=False), _ahora(), fuente or ""))

    def opciones_pagina(self, pagina_id, filtro=None):
        """Filas (la más reciente primero): {filtro, padres: {id: texto}, opciones, actualizado, fuente}."""
        sql = "SELECT rowid AS fila, * FROM opciones_pagina WHERE pagina_id = ?"
        args = [int(pagina_id)]
        if filtro is not None:
            sql += " AND filtro = ?"
            args.append(str(filtro))
        res = []
        for f in self._con().execute(sql + " ORDER BY actualizado DESC, fila DESC", args):
            d = dict(f)
            try:
                d["opciones"] = json.loads(d["opciones"] or "[]")
            except ValueError:
                d["opciones"] = []
            try:
                d["padres"] = {str(k): v for k, v in json.loads(d["padres"] or "[]")}
            except (ValueError, TypeError):
                d["padres"] = {}
            res.append(d)
        return res

    # vigilancia de un filtro de una Página (compatibilidad 3.2: «la» vigilancia de la Página = la primera)
    def vigilancia_pagina(self, pagina_id):
        vid = self._principal(pagina_id=pagina_id)
        return self.vigilancia_id(vid) if vid else None

    def vigilancias_paginas(self):
        return [dict(v, nombre=v["objetivo"]) for v in self.lista_vigilancias(tipo="pagina")]

    def guardar_vigilancia_pagina(self, pagina_id, filtro, activa=True, auto_descargar=False, favorito="", frecuencia="",
                                  cada_horas=None, hora="", descargar_sin_fecha=False, vigilancia_id=None):
        if self.obtener_pagina(pagina_id) is None:
            raise ErrorAlmacen("No existe la página número %s" % pagina_id)
        campos = dict(activa=activa, auto_descargar=auto_descargar, favorito=favorito or "", frecuencia=frecuencia or "",
                      cada_horas=cada_horas, hora=hora or "", descargar_sin_fecha=descargar_sin_fecha)
        self._validar_vigilancia(campos)
        vid = vigilancia_id or self._principal(pagina_id=pagina_id)
        if vid is None:
            return self.crear_vigilancia(pagina_id=pagina_id, filtro=str(filtro), **campos)
        self.actualizar_vigilancia(vid, filtro=str(filtro), **campos)
        return vid

    def borrar_vigilancia_pagina(self, pagina_id):
        for v in self.lista_vigilancias(pagina_id=pagina_id):
            self.borrar_vigilancia_id(v["id"])

    def anotar_revision_pagina(self, pagina_id, resultado):
        vid = self._principal(pagina_id=pagina_id)
        if vid:
            self.anotar_revision_id(vid, resultado)

    def opciones_vistas_pagina(self, pagina_id, filtro):
        vid = self._principal(pagina_id=pagina_id, filtro=filtro)
        return self.opciones_de_vigilancia(vid) if vid else []

    def registrar_opciones_pagina(self, pagina_id, filtro, textos, detalle=False):
        """Como `registrar_opciones` (misma regla de novedad de la 3.1), para un filtro de una Página."""
        return self.registrar_opciones_vigilancia(self._principal_o_nueva(pagina_id=pagina_id, filtro=filtro), textos,
                                                  detalle)

    def marcar_descargada_pagina(self, pagina_id, filtro, texto, archivos=None):
        vid = self._principal(pagina_id=pagina_id, filtro=filtro)
        if vid:
            self.marcar_descargada_vigilancia(vid, texto, archivos)

    def pendientes_pagina(self, pagina_id, filtro, incluir_sin_orden=False):
        vid = self._principal(pagina_id=pagina_id, filtro=filtro)
        return self.pendientes_vigilancia(vid, incluir_sin_orden) if vid else []

    def novedades_pagina(self, pagina_id, filtro, dias=7):
        """Novedades de ese filtro de la Página en TODAS sus vigilancias (v3.3: la marca «nueva» del formulario junta
        las de las vigilancias de la misma lista con otros valores)."""
        res = []
        for v in self.lista_vigilancias(pagina_id=pagina_id):
            if v["filtro"] == str(filtro):
                res += [t for t in self.novedades_vigilancia(v["id"], dias) if t not in res]
        return res

    # ------------------------------------------------------------ v3.4: correo
    @staticmethod
    def _fila_cuenta(f):
        if f is None:
            return None
        d = dict(f)
        d["ssl"] = bool(d.get("ssl"))
        return d

    def listar_cuentas_correo(self):
        return [self._fila_cuenta(f) for f in self._con().execute("SELECT * FROM cuentas_correo ORDER BY nombre COLLATE "
                                                                   "NOCASE, id")]

    def cuenta_correo(self, cuenta_id):
        try:
            cid = int(cuenta_id)
        except (TypeError, ValueError):
            return None
        return self._fila_cuenta(self._con().execute("SELECT * FROM cuentas_correo WHERE id = ?", (cid,)).fetchone())

    def guardar_cuenta_correo(self, datos, cuenta_id=None):
        """Crea o cambia una cuenta de correo (los datos se comprueban con `correo.normalizar_cuenta`).  Devuelve su id.
        Si cambia el proveedor o la dirección web, la sesión se da por desconocida."""
        from . import correo
        try:
            d = correo.normalizar_cuenta(datos)
        except correo.ErrorCorreo as e:
            raise ErrorAlmacen(str(e))
        ahora = _ahora()
        cols = ["nombre", "proveedor", "direccion", "url", "host", "puerto", "usuario", "ssl", "carpeta"]
        valores = [d[k] if k != "ssl" else (1 if d["ssl"] else 0) for k in cols]
        with self._transaccion() as c:
            if cuenta_id is None:
                cur = c.execute("INSERT INTO cuentas_correo(%s, creada, modificada) VALUES (%s, ?, ?)"
                                % (", ".join(cols), ", ".join("?" * len(cols))), valores + [ahora, ahora])
                return cur.lastrowid
            antes = c.execute("SELECT * FROM cuentas_correo WHERE id = ?", (int(cuenta_id),)).fetchone()
            if antes is None:
                raise ErrorAlmacen("No existe la cuenta de correo número %s" % cuenta_id)
            c.execute("UPDATE cuentas_correo SET %s, modificada = ? WHERE id = ?" % ", ".join("%s = ?" % k for k in cols),
                      valores + [ahora, int(cuenta_id)])
            if antes["proveedor"] != d["proveedor"] or antes["url"] != d["url"]:
                c.execute("UPDATE cuentas_correo SET estado_sesion = '', sesion_texto = '' WHERE id = ?", (int(cuenta_id),))
        return int(cuenta_id)

    def borrar_cuenta_correo(self, cuenta_id):
        usadas = [b["nombre"] for b in self.listar_busquedas_correo() if b["cuenta_id"] == int(cuenta_id)]
        if usadas:
            raise ErrorAlmacen("Esa cuenta la usan las búsquedas: %s. Bórralas o cámbialas de cuenta antes."
                               % ", ".join(usadas))
        with self._transaccion() as c:
            c.execute("DELETE FROM cuentas_correo WHERE id = ?", (int(cuenta_id),))

    def marcar_sesion_correo(self, cuenta_id, estado, texto=""):
        """`estado`: «ok» (el buzón cargó), «caducada» (pide iniciar sesión) o «error»."""
        with self._transaccion() as c:
            c.execute("UPDATE cuentas_correo SET estado_sesion = ?, sesion_texto = ?, sesion_cuando = ? WHERE id = ?",
                      (estado or "", (texto or "")[:300], _ahora(), int(cuenta_id)))

    def _fila_busqueda(self, f):
        if f is None:
            return None
        from . import correo
        d = dict(f)
        d["activa"] = bool(d.get("activa"))
        d["criterios"] = correo.leer_json(d.get("criterios"), {})
        d["acciones"] = correo.leer_json(d.get("acciones"), [])
        try:
            d["programacion"] = horario.desde_json(d.get("programacion") or "") or horario.vacia()
        except horario.ErrorHorario:
            d["programacion"] = horario.vacia()
        return d

    _SELECT_BUSQ = ("SELECT b.*, c.nombre AS cuenta, c.proveedor AS proveedor FROM busquedas_correo b "
                    "LEFT JOIN cuentas_correo c ON c.id = b.cuenta_id ")

    def listar_busquedas_correo(self, solo_activas=False):
        sql = self._SELECT_BUSQ + ("WHERE b.activa = 1 " if solo_activas else "") + "ORDER BY b.nombre COLLATE NOCASE, b.id"
        return [self._fila_busqueda(f) for f in self._con().execute(sql)]

    def busqueda_correo(self, busqueda_id):
        try:
            bid = int(busqueda_id)
        except (TypeError, ValueError):
            return None
        return self._fila_busqueda(self._con().execute(self._SELECT_BUSQ + "WHERE b.id = ?", (bid,)).fetchone())

    def busqueda_correo_por_nombre(self, nombre):
        f = self._con().execute(self._SELECT_BUSQ + "WHERE b.nombre = ? COLLATE NOCASE", (str(nombre),)).fetchone()
        return self._fila_busqueda(f)

    def guardar_busqueda_correo(self, datos, busqueda_id=None, hoy=None):
        """Crea o cambia una búsqueda de correo (se comprueba con `correo.normalizar_busqueda`).  Devuelve su id.  Si
        cambian los criterios, los correos «descartados» (que al abrirlos no coincidían) se olvidan: se vuelven a mirar."""
        from . import correo
        try:
            d = correo.normalizar_busqueda(datos, hoy)
        except correo.ErrorCorreo as e:
            raise ErrorAlmacen(str(e))
        if self.cuenta_correo(d["cuenta_id"]) is None:
            raise ErrorAlmacen("No existe la cuenta de correo número %s" % d["cuenta_id"])
        otra = self.busqueda_correo_por_nombre(d["nombre"])
        if otra is not None and otra["id"] != busqueda_id:
            raise ErrorAlmacen("Ya hay una búsqueda que se llama «%s»" % d["nombre"])
        ahora = _ahora()
        fila = {"nombre": d["nombre"], "cuenta_id": d["cuenta_id"], "activa": 1 if d["activa"] else 0,
                "criterios": correo.a_json(d["criterios"]), "acciones": json.dumps(d["acciones"], ensure_ascii=False),
                "max_por_vez": d["max_por_vez"], "programacion": horario.a_json(d["programacion"])}
        with self._transaccion() as c:
            if busqueda_id is None:
                cols = list(fila)
                cur = c.execute("INSERT INTO busquedas_correo(%s, creada, modificada) VALUES (%s, ?, ?)"
                                % (", ".join(cols), ", ".join("?" * len(cols))), [fila[k] for k in cols] + [ahora, ahora])
                return cur.lastrowid
            antes = c.execute("SELECT criterios FROM busquedas_correo WHERE id = ?", (int(busqueda_id),)).fetchone()
            if antes is None:
                raise ErrorAlmacen("No existe la búsqueda de correo número %s" % busqueda_id)
            c.execute("UPDATE busquedas_correo SET %s, modificada = ? WHERE id = ?" % ", ".join("%s = ?" % k for k in fila),
                      list(fila.values()) + [ahora, int(busqueda_id)])
            if correo.leer_json(antes["criterios"], {}) != d["criterios"]:
                c.execute("DELETE FROM correos_procesados WHERE busqueda_id = ? AND estado = 'descartado'",
                          (int(busqueda_id),))
        return int(busqueda_id)

    def activar_busqueda_correo(self, busqueda_id, activa):
        with self._transaccion() as c:
            c.execute("UPDATE busquedas_correo SET activa = ? WHERE id = ?", (1 if activa else 0, int(busqueda_id)))

    def borrar_busqueda_correo(self, busqueda_id):
        with self._transaccion() as c:
            c.execute("DELETE FROM correos_procesados WHERE busqueda_id = ?", (int(busqueda_id),))
            c.execute("DELETE FROM busquedas_correo WHERE id = ?", (int(busqueda_id),))
            c.execute("DELETE FROM programaciones WHERE clave = ?", ("correo:%d" % int(busqueda_id),))

    def anotar_revision_correo(self, busqueda_id, resultado):
        with self._transaccion() as c:
            c.execute("UPDATE busquedas_correo SET ultima_revision = ?, ultimo_resultado = ? WHERE id = ?",
                      (_ahora(), (resultado or "")[:300], int(busqueda_id)))

    @staticmethod
    def _fila_procesado(f):
        if f is None:
            return None
        d = dict(f)
        for k in ("archivos", "valores", "hechas"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except ValueError:
                d[k] = []
        return d

    def correo_procesado(self, busqueda_id, clave):
        f = self._con().execute("SELECT * FROM correos_procesados WHERE busqueda_id = ? AND clave = ?",
                                (int(busqueda_id), str(clave))).fetchone()
        return self._fila_procesado(f)

    def marcar_correo_procesado(self, busqueda_id, clave, estado, asunto="", remitente="", fecha="", archivos=None,
                                valores=None, hechas=None, mensaje="", intentos=1):
        """`estado`: «ok», «error» (alguna acción falló: se reintenta lo que faltó, hasta 3 veces) o «descartado» (al
        abrirlo no coincidía)."""
        with self._transaccion() as c:
            c.execute("INSERT OR REPLACE INTO correos_procesados(busqueda_id, clave, estado, cuando, asunto, remitente, "
                      "fecha, archivos, valores, hechas, mensaje, intentos) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (int(busqueda_id), str(clave), estado, _ahora(), (asunto or "")[:300], (remitente or "")[:200],
                       fecha or "", json.dumps(list(archivos or []), ensure_ascii=False),
                       json.dumps([list(v) for v in valores or []], ensure_ascii=False),
                       json.dumps(list(hechas or [])), (mensaje or "")[:500], int(intentos or 0)))
            # se guardan los últimos 2000 de cada búsqueda (de sobra para no repetir ninguno)
            c.execute("DELETE FROM correos_procesados WHERE busqueda_id = ? AND rowid NOT IN (SELECT rowid FROM "
                      "correos_procesados WHERE busqueda_id = ? ORDER BY cuando DESC LIMIT 2000)",
                      (int(busqueda_id), int(busqueda_id)))

    def procesados_correo(self, busqueda_id, limite=50, incluir_descartados=False):
        sql = "SELECT * FROM correos_procesados WHERE busqueda_id = ?"
        if not incluir_descartados:
            sql += " AND estado <> 'descartado'"
        sql += " ORDER BY cuando DESC, rowid DESC LIMIT ?"
        return [self._fila_procesado(f) for f in self._con().execute(sql, (int(busqueda_id), int(limite)))]

    def olvidar_correo_procesado(self, busqueda_id, clave):
        """«Volver a procesar»: la próxima revisión lo vuelve a procesar (si sigue coincidiendo)."""
        with self._transaccion() as c:
            n = c.execute("DELETE FROM correos_procesados WHERE busqueda_id = ? AND clave = ?",
                          (int(busqueda_id), str(clave))).rowcount
        return n > 0

    # ------------------------------------------------------------ v3.0: resumen (Inicio)
    def resumen_inicio(self, hoy=None):
        dia = (hoy or datetime.date.today()).strftime("%Y-%m-%d")
        c = self._con()
        guardados = c.execute("SELECT COUNT(*) FROM reportes WHERE eliminado IS NULL").fetchone()[0]
        hoy_ok = c.execute("SELECT COUNT(*) FROM ejecuciones WHERE cuando LIKE ?", (dia + "%",)).fetchone()[0]
        fallidos = c.execute("SELECT COUNT(*) FROM ejecuciones WHERE cuando LIKE ? AND resultado = 'error'",
                             (dia + "%",)).fetchone()[0]
        novedades = c.execute("SELECT COUNT(*) FROM opciones_vigiladas o JOIN vigilancias v ON v.id = o.vigilancia_id "
                              "LEFT JOIN reportes r ON r.id = v.reporte_id LEFT JOIN paginas p ON p.id = v.pagina_id "
                              "WHERE o.nueva = 1 AND ((r.id IS NOT NULL AND r.eliminado IS NULL) OR p.id IS NOT NULL)"
                              ).fetchone()[0]
        paginas = c.execute("SELECT COUNT(*) FROM paginas").fetchone()[0]
        return {"reportes": guardados, "ejecutados_hoy": hoy_ok, "fallidos_hoy": fallidos, "novedades": novedades,
                "notificaciones": self.no_leidas(), "paginas": paginas}

    def serie_dias(self, hoy=None, dias=7):
        """v3.5 (Centro de control): por cada uno de los últimos `dias` días (el último = hoy), cuántas ejecuciones hubo
        (`total`), cuántas salieron bien (`descargas`), con error (`errores`) y cuántas novedades llegaron (avisos de
        vigilancia y de correo, `novedades`).  Una consulta por tabla, agrupada por día."""
        fin = hoy or datetime.date.today()
        lista = [(fin - datetime.timedelta(days=k)).strftime("%Y-%m-%d") for k in range(dias - 1, -1, -1)]
        pos = {d: i for i, d in enumerate(lista)}
        res = {"dias": lista, "total": [0] * dias, "descargas": [0] * dias, "errores": [0] * dias, "novedades": [0] * dias}
        c = self._con()
        desde = lista[0]
        for f in c.execute("SELECT substr(cuando, 1, 10) AS dia, resultado, COUNT(*) AS n FROM ejecuciones "
                           "WHERE cuando >= ? GROUP BY dia, resultado", (desde,)):
            i = pos.get(f["dia"])
            if i is None:
                continue
            res["total"][i] += f["n"]
            if f["resultado"] == "ok":
                res["descargas"][i] += f["n"]
            elif f["resultado"] == "error":
                res["errores"][i] += f["n"]
        for f in c.execute("SELECT substr(cuando, 1, 10) AS dia, COUNT(*) AS n FROM notificaciones "
                           "WHERE cuando >= ? AND tipo IN ('vigilancia', 'correo') GROUP BY dia", (desde,)):
            i = pos.get(f["dia"])
            if i is not None:
                res["novedades"][i] += f["n"]
        return res

    def ultimas_por_reporte(self):
        """v3.5: la última ejecución de cada reporte (con archivos y duración): {reporte_id: dict}."""
        res = {}
        for f in self._con().execute(
                "SELECT e.id, e.reporte_id, e.cuando, e.resultado, e.mensaje, e.archivos, e.duracion FROM ejecuciones e "
                "JOIN (SELECT MAX(id) AS id FROM ejecuciones WHERE reporte_id IS NOT NULL GROUP BY reporte_id) m "
                "ON m.id = e.id"):
            d = dict(f)
            try:
                d["archivos"] = json.loads(d["archivos"] or "[]")
            except ValueError:
                d["archivos"] = []
            res[d["reporte_id"]] = d
        return res

    # ------------------------------------------------------------ migración
    def migrar_carpeta(self, carpeta_flujos, carpeta_perfiles=None):
        """Importa (una sola vez) los flujos `.json` de la carpeta antigua `flujos/` y su `_historial.json`;
        después mueve esos archivos a `flujos/_importados/`.

        Si `carpeta_perfiles` existe, el perfil del navegador antiguo (`perfiles/<nombre>`) pasa a ser el
        del reporte (`perfiles/reporte_<id>`) para no perder la sesión iniciada.
        Devuelve {"importados": [(archivo, id, nombre)], "errores": [(archivo, mensaje)], "historial": n}."""
        from . import lote          # funciones de la versión de archivos (solo se usan para migrar)
        res = {"importados": [], "errores": [], "historial": 0}
        if not carpeta_flujos or not os.path.isdir(carpeta_flujos):
            return res
        destino = os.path.join(carpeta_flujos, CARPETA_IMPORTADOS)
        historial = lote.Historial(carpeta_flujos)
        hist = historial.leer()
        por_archivo = {}
        for item in lote.listar_flujos(carpeta_flujos):
            if item["error"]:
                res["errores"].append((item["archivo"], item["error"]))
                continue
            try:
                fl = Flujo.cargar(item["ruta"])
                nombre_antiguo = fl.nombre
                if not (fl.nombre or "").strip():
                    fl.nombre = os.path.splitext(item["archivo"])[0]
                rid = self.importar_flujo(fl, origen=item["archivo"])
            except (ErrorFlujo, ErrorAlmacen, OSError, ValueError) as e:
                res["errores"].append((item["archivo"], str(e)))
                continue
            por_archivo[item["archivo"].lower()] = rid
            res["importados"].append((item["archivo"], rid, fl.nombre))
            self._mover_perfil(carpeta_perfiles, nombre_antiguo, rid)
            self._mover(item["ruta"], destino)
        for clave, entrada in hist.items():
            rid = por_archivo.get(os.path.basename(clave).lower())
            if rid is None or not isinstance(entrada, dict):
                continue
            try:
                cuando = datetime.datetime.strptime(entrada.get("ultima", ""), FORMATO_FECHA)
            except ValueError:
                cuando = None
            self.registrar_ejecucion(rid, entrada.get("resultado") or "error", entrada.get("mensaje", ""),
                                     entrada.get("archivos") or [], cuando=cuando)
            res["historial"] += 1
        if os.path.isfile(historial.ruta) and (res["importados"] or not hist):
            self._mover(historial.ruta, destino)
        return res

    @staticmethod
    def _mover(ruta, carpeta):
        os.makedirs(carpeta, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(ruta))
        destino = os.path.join(carpeta, base + ext)
        n = 2
        while os.path.exists(destino):
            destino = os.path.join(carpeta, "%s (%d)%s" % (base, n, ext))
            n += 1
        try:
            shutil.move(ruta, destino)
        except OSError:
            pass
        return destino

    @staticmethod
    def _mover_perfil(carpeta_perfiles, nombre_antiguo, rid):
        if not carpeta_perfiles or not os.path.isdir(carpeta_perfiles):
            return
        origen = os.path.join(carpeta_perfiles, slug(nombre_antiguo))
        destino = os.path.join(carpeta_perfiles, nombre_perfil(rid))
        if os.path.isdir(origen) and not os.path.exists(destino):
            try:
                os.rename(origen, destino)
            except OSError:
                pass       # el perfil está en uso: el reporte empezará sin la sesión iniciada
