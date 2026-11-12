"""Varios reportes: ejecución por lotes (y utilidades de la versión 2.1, basada en archivos).

No importa playwright ni tkinter (el ejecutor trae playwright solo cuando abre el navegador).

- `ejecutar_lote(...)`: ejecuta varios reportes uno detrás de otro; si uno falla sigue con el siguiente y
  devuelve un resumen.  Cada elemento es el id de un reporte guardado en la aplicación (`almacen`) o la
  ruta de un archivo `.json` (compatibilidad).
- Formato antiguo (2.1), que ahora solo se usa para importar a la base de datos (`almacen.migrar_carpeta`):
  `listar_flujos(carpeta)` (los `.json` de `flujos/`), `Historial` (`flujos/_historial.json`),
  `duplicar_flujo`, `mover_a_papelera`.
"""

import datetime
import json
import os
import re
import shutil

from .flujo import ErrorFlujo, Flujo, reportes_siguientes, slug

NOMBRE_HISTORIAL = "_historial.json"
MAX_ENCADENADOS = 50          # v3.9: como mucho tantos reportes en una tanda con «Al terminar, ejecutar…»
CARPETA_PAPELERA = "_papelera"
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------- lista de flujos
def listar_flujos(carpeta):
    """Flujos guardados en `carpeta`: lista de dicts {archivo, ruta, nombre, url, error}, por nombre.

    Si un archivo no se puede leer, aparece igualmente con `error` (para que el usuario lo vea)."""
    res = []
    if not os.path.isdir(carpeta):
        return res
    for nombre in sorted(os.listdir(carpeta), key=str.lower):
        ruta = os.path.join(carpeta, nombre)
        if nombre.startswith("_") or not nombre.lower().endswith(".json") or not os.path.isfile(ruta):
            continue
        item = {"archivo": nombre, "ruta": os.path.abspath(ruta), "nombre": os.path.splitext(nombre)[0],
                "url": "", "error": ""}
        try:
            f = Flujo.cargar(ruta)
            item["nombre"] = f.nombre or item["nombre"]
            item["url"] = f.url or next((p.url for p in f.pasos if p.tipo == "abrir_url"), "")
        except (ErrorFlujo, OSError, ValueError) as e:
            item["error"] = str(e)
        res.append(item)
    return res


def nombre_archivo(nombre):
    """Nombre de archivo válido en Windows a partir del nombre del flujo (se conservan los paréntesis)."""
    limpio = re.sub(r'[<>:"/\|?*\x00-\x1f]+', "_", (nombre or "").strip()).strip(" .")
    return limpio or "flujo"


def nombre_copia(carpeta, nombre):
    """Nombre libre para duplicar: «X (copia)», «X (copia 2)»…"""
    n = 1
    while True:
        candidato = "%s (copia)" % nombre if n == 1 else "%s (copia %d)" % (nombre, n)
        if not os.path.exists(os.path.join(carpeta, nombre_archivo(candidato) + ".json")):
            return candidato
        n += 1


def duplicar_flujo(ruta, carpeta=None):
    """Copia un flujo a un archivo nuevo con el nombre «… (copia)».  Devuelve la ruta nueva."""
    carpeta = carpeta or os.path.dirname(os.path.abspath(ruta))
    f = Flujo.cargar(ruta)
    f.nombre = nombre_copia(carpeta, f.nombre)
    destino = os.path.join(carpeta, nombre_archivo(f.nombre) + ".json")
    f.guardar(destino)
    return destino


def mover_a_papelera(ruta):
    """«Elimina» un flujo moviéndolo a `flujos/_papelera/` (se puede recuperar a mano)."""
    carpeta = os.path.join(os.path.dirname(os.path.abspath(ruta)), CARPETA_PAPELERA)
    os.makedirs(carpeta, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(ruta))
    destino = os.path.join(carpeta, base + ext)
    n = 2
    while os.path.exists(destino):
        destino = os.path.join(carpeta, "%s (%d)%s" % (base, n, ext))
        n += 1
    shutil.move(ruta, destino)
    return destino


# --------------------------------------------------------------------- historial
class Historial:
    """Última ejecución de cada flujo, en un JSON pequeño junto a los flujos."""

    def __init__(self, carpeta):
        self.carpeta = os.path.abspath(carpeta)
        self.ruta = os.path.join(self.carpeta, NOMBRE_HISTORIAL)

    def _clave(self, ruta):
        ruta = os.path.abspath(ruta)
        if os.path.dirname(ruta).lower() == self.carpeta.lower():
            return os.path.basename(ruta)
        return ruta

    def contiene_flujo(self, ruta):
        """True si el archivo del flujo está en la carpeta de este historial."""
        return os.path.dirname(os.path.abspath(ruta)).lower() == self.carpeta.lower()

    def leer(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.load(f)
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def obtener(self, ruta):
        return self.leer().get(self._clave(ruta))

    def registrar(self, ruta, resultado, mensaje="", archivos=None, cuando=None):
        """Anota la última ejecución.  `resultado`: «ok», «error» o «detenido»."""
        datos = self.leer()
        datos[self._clave(ruta)] = {
            "ultima": (cuando or datetime.datetime.now()).strftime(FORMATO_FECHA),
            "resultado": resultado,
            "mensaje": (mensaje or "")[:300],
            "archivos": [os.path.basename(a) for a in (archivos or [])][:20],
        }
        os.makedirs(self.carpeta, exist_ok=True)
        tmp = self.ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.ruta)

    def olvidar(self, ruta):
        datos = self.leer()
        if datos.pop(self._clave(ruta), None) is not None:
            tmp = self.ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.ruta)

    def registrar_resultado(self, ruta, res):
        """Anota un ResultadoEjecucion (solo si el flujo está en la carpeta del historial)."""
        if not self.contiene_flujo(ruta):
            return
        if res is None:
            return
        estado = "ok" if res.ok else ("detenido" if res.detenido else "error")
        self.registrar(ruta, estado, "" if res.ok else res.resumen(), res.archivos)


def texto_resultado(entrada):
    """Texto corto para la lista de reportes."""
    if not entrada:
        return "—"
    return {"ok": "Bien", "error": "Falló", "detenido": "Detenido"}.get(entrada.get("resultado"), "?")


# ------------------------------------------------------------------------- lotes
class ResultadoFlujoLote:
    def __init__(self, ruta, nombre):
        self.ruta = ruta
        self.nombre = nombre
        self.estado = "pendiente"      # ok | error | detenido | no_ejecutado | pendiente
        self.mensaje = ""
        self.archivos = []
        self.ruta_log = ""
        self.ruta_captura = ""
        self.despues_de = ""           # v3.9: nombre del reporte tras el que se ejecutó («Al terminar, ejecutar…»)

    @property
    def ok(self):
        return self.estado == "ok"


class ResultadoLote:
    def __init__(self):
        self.items = []
        self.detenido = False

    @property
    def ok(self):
        return bool(self.items) and all(i.ok for i in self.items)

    @property
    def correctos(self):
        return [i for i in self.items if i.ok]

    @property
    def fallidos(self):
        return [i for i in self.items if i.estado in ("error", "detenido")]

    @property
    def archivos(self):
        return [a for i in self.items for a in i.archivos]

    def resumen(self):
        """Resumen en español, una línea por flujo."""
        lineas = ["Resumen del lote: %d de %d reportes bien, %d fallaron%s" % (
            len(self.correctos), len(self.items), len(self.fallidos),
            ", %d sin ejecutar" % sum(1 for i in self.items if i.estado == "no_ejecutado")
            if any(i.estado == "no_ejecutado" for i in self.items) else "")]
        for i in self.items:
            tras = (" (después de «%s»)" % i.despues_de) if i.despues_de else ""
            if i.estado == "ok":
                lineas.append("  BIEN    %s%s — %d archivo(s)%s" % (
                    i.nombre, tras, len(i.archivos), (": " + ", ".join(os.path.basename(a) for a in i.archivos))
                    if i.archivos else ""))
            elif i.estado == "no_ejecutado":
                lineas.append("  SIN EJECUTAR  %s%s" % (i.nombre, tras))
            else:
                lineas.append("  FALLÓ   %s%s — %s" % (i.nombre, tras, i.mensaje))
        lineas.append("Archivos descargados: %d" % len(self.archivos))
        return "\n".join(lineas)


def ejecutar_lote(rutas, carpeta_perfiles, carpeta_registros, carpeta_descargas=None, oculto=True, lento=False,
                  navegador=None, variables=None, progreso=None, log=None, detener=None, historial=None,
                  hoy=None, resolver_secreto=None, fabrica_ejecutor=None, aviso_lote=None, almacen=None,
                  pedir_acceso=None, accesos=None, encadenar=True, ya_ejecutados=None, despues_de=""):
    """Ejecuta los reportes de `rutas` uno tras otro.  Si uno falla, sigue con el siguiente.

    v3.9 «Al terminar, ejecutar…»: si un reporte guardado lo tiene (`encadenar`), los reportes que dice se ponen en la
    cola justo detrás (si terminó bien, o siempre, según diga).  Un reporte no se ejecuta dos veces en el mismo lote
    (así no hay círculos: A → B → A); `ya_ejecutados` = ids que ya se ejecutaron antes (cadena de una ejecución suelta),
    `despues_de` = nombre del reporte tras el que van los de `rutas`.

    - Cada elemento es el id (int) de un reporte de `almacen` o la ruta de un archivo `.json`.
    - Cada reporte usa su propio perfil: `carpeta_perfiles/reporte_<id>` (los archivos:
      `carpeta_perfiles/<nombre del flujo>`).
    - El resultado de cada reporte de la base de datos se anota en su historial (`almacen`); el de un
      archivo, en `historial` (formato antiguo) solo si se pasa.
    - `progreso(i, estado, texto)` es el de cada flujo (pasos); `aviso_lote(n, total, item, fase)` avisa
      de «inicio» / «fin» de cada flujo.
    - `detener` (threading.Event): se para el flujo en curso y los siguientes quedan «sin ejecutar».
    - `pedir_acceso(solicitud, esperar)`: si una página pide iniciar sesión y faltan datos, se preguntan (ventana);
      sin él (tareas programadas) el reporte falla con un mensaje claro.  `accesos`: datos de acceso por sitio
      (por defecto, los de `almacen`).
    - `fabrica_ejecutor` solo sirve para pruebas.
    """
    from .ejecutor import Ejecutor
    from .almacen import ErrorAlmacen, nombre_perfil
    fabrica = fabrica_ejecutor or Ejecutor
    lote = ResultadoLote()
    cola = list(rutas)                         # v3.9: crece con los reportes encadenados («Al terminar, ejecutar…»)
    tras = {k: despues_de for k in range(len(cola))} if despues_de else {}
    vistos = {int(x) for x in (ya_ejecutados or [])} | {r for r in cola if isinstance(r, int)}

    def encadenar_tras(fl, ok, n, ruta):
        """Pone en la cola (justo detrás del actual) los reportes de «Al terminar, ejecutar…» de `fl`."""
        if not encadenar or not isinstance(ruta, int) or almacen is None:
            return
        pos = n
        for sig in reportes_siguientes(fl, ok):
            fila_sig = almacen.obtener(sig)
            nombre_sig = fila_sig["nombre"] if fila_sig else "reporte %d" % sig
            if fila_sig is None:
                if log:
                    log("AVISO: «%s» tenía que ejecutar después el reporte número %d, pero ya no existe" % (fl.nombre, sig))
                continue
            if sig in vistos:
                if log:
                    log("(«%s» ya se ejecuta en esta tanda: no se repite después de «%s», así no hay círculos)"
                        % (nombre_sig, fl.nombre))
                continue
            if len(cola) >= MAX_ENCADENADOS:
                if log:
                    log("AVISO: demasiados reportes encadenados (máximo %d): no se añade «%s»" % (MAX_ENCADENADOS,
                                                                                               nombre_sig))
                break
            vistos.add(sig)
            for k in sorted(tras, reverse=True):           # (los que van detrás se corren un puesto)
                if k >= pos:
                    tras[k + 1] = tras.pop(k)
            cola.insert(pos, sig)
            tras[pos] = fl.nombre
            pos += 1
            if log:
                log("Al terminar «%s» se ejecutará «%s»" % (fl.nombre, nombre_sig))

    try:
        n = 0
        while n < len(cola):
            ruta = cola[n]
            n += 1
            total = len(cola)
            es_id = isinstance(ruta, int)
            if es_id:
                fila = almacen.obtener(ruta) if almacen is not None else None
                item = ResultadoFlujoLote(ruta, fila["nombre"] if fila else "reporte %d" % ruta)
            else:
                item = ResultadoFlujoLote(ruta, os.path.splitext(os.path.basename(ruta))[0])
            item.despues_de = tras.get(n - 1, "")
            lote.items.append(item)
            if detener is not None and detener.is_set():
                lote.detenido = True
                item.estado = "no_ejecutado"
                continue
            if aviso_lote:
                aviso_lote(n, total, item, "inicio")
            if log:
                log("=== Reporte %d de %d: %s ===" % (n, total, item.nombre))
            try:
                if es_id:
                    if almacen is None:
                        raise ErrorFlujo("no hay base de datos de reportes")
                    fl = almacen.cargar_flujo(ruta)
                    perfil = os.path.join(carpeta_perfiles, nombre_perfil(ruta))
                else:
                    fl = Flujo.cargar(ruta)
                    perfil = os.path.join(carpeta_perfiles, slug(fl.nombre))
                item.nombre = fl.nombre or item.nombre
            except (ErrorFlujo, ErrorAlmacen, OSError, ValueError) as e:
                item.estado = "error"
                item.mensaje = "No se pudo abrir el flujo: %s" % e
                if log:
                    log("ERROR: " + item.mensaje)
                _terminar_item(lote, item, historial, ruta, None, aviso_lote, n, total, almacen)
                continue
            if navegador:
                fl.opciones["navegador"] = navegador
            try:
                ej = fabrica(
                    fl, carpeta_perfil=perfil,
                    carpeta_registros=carpeta_registros, carpeta_descargas=carpeta_descargas,
                    oculto=oculto, lento=lento, variables=variables, hoy=hoy, progreso=progreso, log=log,
                    detener=detener, pedir_acceso=pedir_acceso,
                    accesos=accesos if accesos is not None else almacen, reporte_id=ruta if es_id else None,
                    **({"resolver_secreto": resolver_secreto} if resolver_secreto else {}))
                res = ej.ejecutar()
            except Exception as e:      # un flujo roto no debe tumbar el lote
                item.estado = "error"
                item.mensaje = "%s: %s" % (type(e).__name__, str(e).splitlines()[0] if str(e) else "")
                if log:
                    log("ERROR inesperado: " + item.mensaje)
                _terminar_item(lote, item, historial, ruta, None, aviso_lote, n, total, almacen)
                if not (detener is not None and detener.is_set()):
                    encadenar_tras(fl, False, n, ruta)
                continue
            item.archivos = list(res.archivos)
            item.ruta_log = res.ruta_log
            item.ruta_captura = res.ruta_captura
            if res.ok:
                item.estado = "ok"
            elif res.detenido:
                item.estado = "detenido"
                item.mensaje = res.resumen()
                lote.detenido = True
            else:
                item.estado = "error"
                item.mensaje = res.resumen()
            _terminar_item(lote, item, historial, ruta, res, aviso_lote, n, total, almacen)
            if item.estado != "detenido":
                encadenar_tras(fl, res.ok, n, ruta)
    finally:
        if almacen is not None:
            almacen.liberar_hilo()      # la conexión de este hilo de trabajo no se queda abierta
    return lote


def ejecutar_encadenados(flujo, reporte_id, ok, log=None, **kw):
    """v3.9: tras ejecutar UN reporte guardado (botón «Ejecutar», tarea programada de un solo reporte), ejecuta los de su
    «Al terminar, ejecutar…» como un lote (con sus propias cadenas).  None si no tiene nada que ejecutar después."""
    if reporte_id is None:
        return None
    siguientes = [s for s in reportes_siguientes(flujo, ok) if s != reporte_id]
    if not siguientes:
        return None
    if log:
        log("=== Al terminar «%s»: %d reporte(s) más ===" % (flujo.nombre, len(siguientes)))
    return ejecutar_lote(siguientes, log=log, ya_ejecutados=[reporte_id], despues_de=flujo.nombre, **kw)


def siguientes_guardados(almacen, reporte_id):
    """Los ids de «Al terminar, ejecutar…» de un reporte guardado (sin mirar si termina bien o no); [] si no se puede."""
    try:
        fl = almacen.cargar_flujo(reporte_id)
    except Exception:          # noqa: BLE001  (reporte borrado o dañado: no encadena nada)
        return []
    return reportes_siguientes(fl, True)          # (con ok=True salen los de «solo si termina bien» y los de «siempre»)


def buscar_circulo(reporte_id, nuevos, siguientes_de):
    """v3.9: si `reporte_id` ejecutara `nuevos` al terminar, ¿se formaría un círculo (A → B → … → A)?  Devuelve los ids
    del círculo ([A, B, …, A]) o None.  `siguientes_de(id)` = los que ejecuta ese reporte al terminar."""
    pila = [(int(s), [int(reporte_id), int(s)]) for s in nuevos or []]
    vistos = set()
    while pila:
        x, camino = pila.pop()
        if x == int(reporte_id):
            return camino
        if x in vistos or len(camino) > MAX_ENCADENADOS:
            continue
        vistos.add(x)
        for y in siguientes_de(x) or []:
            pila.append((int(y), camino + [int(y)]))
    return None


def _terminar_item(lote, item, historial, ruta, res, aviso_lote, n, total, almacen=None):
    if isinstance(ruta, int):
        if almacen is not None:
            try:
                if res is not None:
                    almacen.registrar_resultado(ruta, res)
                else:
                    almacen.registrar_ejecucion(ruta, "error", item.mensaje)
            except Exception:          # el historial nunca debe tumbar el lote
                pass
    elif historial is not None and historial.contiene_flujo(ruta):
        try:
            if res is not None:
                historial.registrar_resultado(ruta, res)
            else:
                historial.registrar(ruta, "error", item.mensaje)
        except OSError:
            pass
    if aviso_lote:
        aviso_lote(n, total, item, "fin")
