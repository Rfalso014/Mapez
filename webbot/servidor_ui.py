"""Interfaz nueva (v3.0): servidor local con la página `ui/` y una API JSON.

- Solo escucha en 127.0.0.1, en un puerto libre.  Cada sesión tiene un TOKEN aleatorio que la página manda en la
  cabecera `X-Bot-Token` en TODAS las llamadas a la API; se rechazan las peticiones de otros orígenes (cabecera
  Origin/Host distinta) para que ninguna otra página web pueda usar la API.
- Los archivos de `ui/` (HTML, CSS y JavaScript sin dependencias ni CDN: funciona sin Internet) se sirven tal cual.
- Los trabajos con navegador (ejecutar, lote, grabar, mapear, vigilar, probar un acceso) corren de uno en uno en su
  propio hilo; Playwright solo vive en ese hilo.  El progreso llega a la página como «eventos» (la página los pide con
  /api/eventos?desde=N&espera=S).  Las preguntas del hilo de trabajo (iniciar sesión, «la contraseña falló») se
  convierten en «preguntas» que la página muestra como ventanas y contesta con POST /api/preguntas/<id>.
- `abrir_aplicacion(args)`: arranca el servidor y abre una ventana tipo aplicación (Edge o Chrome con --app; si no,
  el navegador predeterminado).  `probar_web(args)`: --smoke-web.

Las contraseñas solo pasan por la API cuando el usuario las escribe (cambiar contraseña, contestar una pregunta) y van
directas al Administrador de credenciales: nunca se guardan en la base de datos ni en los registros.
"""

import datetime
import hmac
import http.server
import json
import mimetypes
import os
import queue
import secrets as mod_secrets
import shutil
import socketserver
import sys
import tempfile
import re
import threading
import time
import traceback
from urllib.parse import parse_qs, unquote, urlparse

from . import RAIZ, VERSION, carpeta
from . import accesos as mod_accesos
from . import flujo as mod_flujo
from . import horario, plantillas, programador, secretos
from .accesos import PeticionAcceso
from .almacen import Almacen, ErrorAlmacen, nombre_perfil
from .flujo import ErrorFlujo, Flujo, Paso

CARPETA_UI = os.path.join(RAIZ, "ui")
MAX_EVENTOS = 3000
MAX_CUERPO = 5 * 1024 * 1024
TTL_TAREAS = 60.0            # v3.5: la lista de tareas de Windows (schtasks /Query tarda ~1 s) se guarda 60 s
mimetypes.add_type("font/woff2", ".woff2")          # v3.5: las fuentes de ui/fuentes (Windows no siempre lo conoce)


class ErrorApi(Exception):
    def __init__(self, mensaje, codigo=400):
        super().__init__(mensaje)
        self.codigo = codigo


# ====================================================================== eventos
class Eventos:
    """Lista de eventos con número de orden; la página pide los posteriores a uno (con espera)."""

    def __init__(self):
        self._lista = []
        self._seq = 0
        self._cond = threading.Condition()

    def emitir(self, tipo, **datos):
        with self._cond:
            self._seq += 1
            datos.update(seq=self._seq, tipo=tipo, cuando=time.strftime("%H:%M:%S"))
            self._lista.append(datos)
            if len(self._lista) > MAX_EVENTOS:
                del self._lista[:len(self._lista) - MAX_EVENTOS]
            self._cond.notify_all()
            return self._seq

    def desde(self, n, espera=0.0):
        fin = time.monotonic() + max(0.0, min(float(espera or 0), 25.0))
        with self._cond:
            while True:
                nuevos = [e for e in self._lista if e["seq"] > n]
                if nuevos or time.monotonic() >= fin:
                    return nuevos, self._seq
                self._cond.wait(max(0.05, fin - time.monotonic()))

    @property
    def ultimo(self):
        return self._seq


# ===================================================================== trabajo
class Trabajo:
    def __init__(self, tipo, descripcion, objetivo=None):
        self.id = mod_secrets.token_hex(4)
        self.tipo = tipo
        self.descripcion = descripcion
        self.objetivo = dict(objetivo or {})         # v3.5: {reporte_id | pagina_id | correo_id} (para la interfaz)
        self.detener = threading.Event()
        self.hilo = None
        self.inicio = time.time()
        self.estado = "en_curso"
        self.resumen = ""
        self.paso = None
        self.total = 0
        self.texto = ""

    def a_dict(self):
        d = {"id": self.id, "tipo": self.tipo, "descripcion": self.descripcion, "estado": self.estado,
             "resumen": self.resumen, "paso": self.paso, "total": self.total, "texto": self.texto,
             "segundos": int(time.time() - self.inicio)}
        d.update(self.objetivo)
        return d


def _paso_dict(p, i=None):
    d = p.a_dict()
    d.update(descripcion=p.descripcion(), accion=p.accion(), detalle=p.detalle(), problemas=p.problemas())
    if i is not None:
        d["indice"] = i
    return d


def _flujo_desde(datos):
    if not isinstance(datos, dict):
        raise ErrorApi("Falta el reporte")
    try:
        return Flujo.desde_dict(datos)
    except (ErrorFlujo, TypeError, ValueError) as e:
        raise ErrorApi("El reporte no es válido: %s" % e)


def _corto(nombre_tarea):
    """«BotWeb\\X» → «X» (como las lista `programador.listar_tareas`)."""
    return (nombre_tarea or "").split("\\", 1)[-1]


class Aplicacion:
    """Estado y API de la interfaz.  `crear_ejecutor`, `crear_grabador`, `listar_tareas` y `ejecutar_tareas` (v3.4: lo
    que llama a schtasks al crear/borrar una tarea) se pueden inyectar (pruebas)."""

    def __init__(self, almacen, carpeta_perfiles=None, carpeta_registros=None, carpeta_descargas=None,
                 listar_tareas=None, oculto_forzado=None, hoy=None, ejecutar_tareas=None, abrir_dialogo=None):
        self.almacen = almacen
        self.token = mod_secrets.token_urlsafe(24)
        self.eventos = Eventos()
        self.preguntas = {}
        self._cerrojo = threading.RLock()
        self.trabajo = None
        self.grabador = None
        self.sesion_mapa = None
        self.ultimo_grabado = None
        self.carpeta_perfiles = carpeta_perfiles or carpeta("perfiles")
        self.carpeta_registros = carpeta_registros or carpeta("registros")
        self.carpeta_descargas = carpeta_descargas
        self.listar_tareas = listar_tareas if listar_tareas is not None else programador.listar_tareas
        self.ejecutar_tareas = ejecutar_tareas      # v3.4: None = schtasks de verdad (las pruebas ponen uno falso)
        # v3.6.1: arranca la ejecución de hoy cuando el aviso previo ya pasó.  None = NO se lanza nada: solo la
        # aplicación de verdad (`abrir_aplicacion`) pone `programador.lanzar_desacoplado`; las pruebas nunca lanzan el bot
        self.lanzar_proceso = None
        self.guia_al_abrir = False       # v3.8: solo la aplicación de verdad enseña la guía de inicio sola
        self.oculto_forzado = oculto_forzado        # pruebas: siempre oculto
        self.hoy = hoy
        self.ultimo_latido = None
        self.al_iniciar = []                        # acciones pedidas por la línea de comandos (--ejecutar)
        self.abrir_en_sistema = abrir_en_sistema    # v3.2: «Abrir carpeta» / «Abrir archivo» (las pruebas lo cambian)
        self.abrir_dialogo = abrir_dialogo          # v3.5: «📁 Elegir…» (None = el explorador de Windows; pruebas: falso)
        # v3.5: caché de la lista de tareas de Windows (schtasks /Query tarda ~1 s y se pedía en cada carga del Inicio,
        # de Vigilancia y de Correo).  Se vacía al crear/borrar una tarea desde el bot.  Con `tareas_en_segundo_plano`
        # (lo pone `abrir_aplicacion`), pasado el plazo se devuelve la lista anterior y se relee en otro hilo.
        self._tareas_cache = None                   # (momento, lista)
        self._tareas_cerrojo = threading.Lock()
        self._tareas_releyendo = False
        self.tareas_en_segundo_plano = False
        # v3.7: lo que se ejecuta FUERA de la interfaz (tareas de Windows), leído de la tabla `en_curso`
        self._externos = []
        self._externos_firma = None
        self._externos_cuando = 0.0
        self._externos_cerrojo = threading.Lock()
        # v3.9: «Hay una nueva actualización».  None = no se mira GitHub (las pruebas y --smoke-web): solo la aplicación
        # de verdad (`abrir_aplicacion`) pone un `actualizar.Actualizador`.  `salir` = cerrar el programa (al actualizar)
        self.actualizador = None
        self.actualizando = False
        self.salir = threading.Event()

    # ----------------------------------------------------------- utilidades
    def _oculto(self, ver):
        if self.oculto_forzado is not None:
            return bool(self.oculto_forzado)
        return not ver

    def _perfil(self, flujo, reporte_id):
        if reporte_id is not None:
            return os.path.join(self.carpeta_perfiles, nombre_perfil(reporte_id))
        return os.path.join(self.carpeta_perfiles, "_sin_guardar_" + mod_flujo.slug(flujo.nombre))

    def _log(self, linea):
        self.eventos.emitir("log", linea=linea)

    def _progreso(self, trabajo, i, estado, texto="", reporte=None):
        trabajo.paso = i
        trabajo.texto = texto
        self.eventos.emitir("progreso", trabajo=trabajo.id, i=i, estado=estado, texto=texto, reporte=reporte,
                            total=trabajo.total if trabajo.tipo not in ("lote", "filtros", "pagina_varias") else 0)

    def _pedir_acceso(self, trabajo):
        def pedir(solicitud, esperar):
            pet = PeticionAcceso(solicitud)
            pid = mod_secrets.token_hex(6)
            pet.id = pid
            pet.tipo = solicitud.get("tipo") or "inicio_sesion"
            with self._cerrojo:
                self.preguntas[pid] = pet
            self.eventos.emitir("pregunta", id=pid, clase=pet.tipo, host=solicitud.get("host", ""))
            try:
                esperar(pet.evento)
            except BaseException:
                pet.cancelar()
                raise
            finally:
                with self._cerrojo:
                    self.preguntas.pop(pid, None)
                self.eventos.emitir("pregunta_fin", id=pid)
            return pet.respuesta
        return pedir

    def _notificar(self, tipo, datos):
        self.eventos.emitir("aviso", aviso=tipo, **{k: v for k, v in (datos or {}).items() if isinstance(v, (str, int))})

    def crear_ejecutor(self, trabajo, flujo, reporte_id=None, ver=None, lento=False, variables=None, **extra):
        from .ejecutor import Ejecutor
        ajustes = self.almacen.ajustes()
        ver = ajustes.get("ver_mientras_trabaja", True) if ver is None else ver
        perfil = extra.pop("carpeta_perfil", None) or self._perfil(flujo, reporte_id)
        return Ejecutor(flujo, carpeta_perfil=perfil, carpeta_registros=self.carpeta_registros,
                        carpeta_descargas=self.carpeta_descargas, oculto=self._oculto(ver), lento=lento,
                        variables=variables, hoy=self.hoy,
                        progreso=lambda i, estado, texto="": self._progreso(trabajo, i, estado, texto, flujo.nombre),
                        log=self._log, detener=trabajo.detener, pedir_acceso=self._pedir_acceso(trabajo),
                        accesos=self.almacen, notificar=self._notificar, reporte_id=reporte_id, **extra)

    def lanzar(self, tipo, descripcion, funcion, **objetivo):
        """Empieza un trabajo con navegador en su hilo (uno a la vez).  v3.5: `objetivo` (reporte_id, pagina_id,
        correo_id) viaja en los eventos «trabajo» para que la interfaz actualice solo esa fila."""
        objetivo = {k: v for k, v in objetivo.items() if v is not None}
        with self._cerrojo:
            if self.trabajo is not None and self.trabajo.estado == "en_curso":
                raise ErrorApi("Ya hay un trabajo en curso (%s). Espera a que termine o pulsa Detener."
                               % self.trabajo.descripcion, 409)
            if self.actualizando:
                raise ErrorApi("Bot Web se está actualizando: se cerrará y volverá a abrirse solo en unos minutos.", 409)
            t = Trabajo(tipo, descripcion, objetivo)
            self.trabajo = t

        def correr():
            ok, resumen = False, ""
            try:
                ok, resumen = funcion(t)
            except Exception as e:     # noqa: BLE001
                resumen = "Error inesperado: %s: %s" % (type(e).__name__, str(e).splitlines()[0] if str(e) else "")
                self._log(resumen)
                traceback.print_exc()
            finally:
                try:
                    self.almacen.liberar_hilo()
                except Exception:      # noqa: BLE001
                    pass
            t.estado = "ok" if ok else ("detenido" if t.detener.is_set() else "error")
            t.resumen = resumen
            self.eventos.emitir("trabajo", trabajo=t.id, estado=t.estado, tipo_trabajo=t.tipo, resumen=resumen,
                                descripcion=t.descripcion, **t.objetivo)

        t.hilo = threading.Thread(target=correr, name="trabajo-" + tipo, daemon=True)
        self.eventos.emitir("trabajo", trabajo=t.id, estado="en_curso", tipo_trabajo=tipo, descripcion=descripcion,
                            **t.objetivo)
        t.hilo.start()
        return t

    def detener(self):
        t = self.trabajo
        if t is not None:
            t.detener.set()
        for pet in list(self.preguntas.values()):
            pet.cancelar()
        if self.grabador is not None:
            self.grabador.detener()
        if self.sesion_mapa is not None:
            self.sesion_mapa.pedir("terminar")
        return {"ok": True}

    # ============================================================== la API
    def api(self, metodo, ruta, datos, query):
        partes = [unquote(p) for p in ruta.strip("/").split("/")][1:]      # sin «api»
        if not partes:
            raise ErrorApi("Ruta vacía", 404)
        nombre = "_api_" + partes[0].replace("-", "_")
        funcion = getattr(self, nombre, None)
        if funcion is None:
            raise ErrorApi("No existe /api/%s" % partes[0], 404)
        return funcion(metodo, partes[1:], datos or {}, query)

    # --------------------------------------------------------------- estado
    def _api_estado(self, metodo, partes, datos, q):
        t = self.trabajo
        return {"version": VERSION, "trabajo": t.a_dict() if t else None, "evento": self.eventos.ultimo,
                "preguntas": self._preguntas(), "no_leidas": self.almacen.no_leidas(),
                "grabando": self.grabador is not None, "mapeando": self.sesion_mapa is not None
                and not self.sesion_mapa.terminada.is_set(), "al_iniciar": list(self.al_iniciar),
                "guia_pendiente": bool(self.guia_al_abrir and not self.almacen.ajustes().get("guia_vista")),
                "actualizacion": self.actualizador.estado() if self.actualizador is not None else None}

    # ------------------------------------------------------- v3.9: actualizaciones
    def _ocupado_para_actualizar(self):
        """Qué está haciendo el bot ahora mismo (texto) o None si se puede actualizar."""
        t = self.trabajo
        if t is not None and t.estado == "en_curso":
            return "«%s»" % t.descripcion
        if self.grabador is not None:
            return "una grabación"
        if self.sesion_mapa is not None and not self.sesion_mapa.terminada.is_set():
            return "el mapeo de una página"
        externos = [x for x in self.revisar_en_curso(forzar=True) if not x.get("terminado")]
        if externos:
            return "una tarea programada (%s)" % (externos[0].get("nombre") or "en segundo plano")
        return None

    def _api_actualizacion(self, metodo, partes, datos, q):
        """GET → lo último que se sabe.  POST actualizacion/comprobar («Buscar actualizaciones»),
        actualizacion/mas-tarde y actualizacion/instalar («Actualizar»: se niega si el bot está trabajando)."""
        from . import actualizar as mod_actualizar
        act = self.actualizador
        accion = partes[0] if partes else ""
        if metodo != "POST" or not accion:
            return act.estado() if act is not None else {"activo": False, "disponible": False}
        if accion not in ("comprobar", "mas-tarde", "instalar"):
            raise ErrorApi("Acción no válida", 404)
        if act is None:
            raise ErrorApi("La búsqueda de actualizaciones no está activa en esta ventana.", 409)
        if accion == "comprobar":
            return act.comprobar(manual=True)
        if accion == "mas-tarde":
            return act.posponer()
        with self._cerrojo:
            if self.actualizando:
                raise ErrorApi("La actualización ya está en marcha.", 409)
            ocupado = self._ocupado_para_actualizar()
            if ocupado:
                raise ErrorApi("Ahora mismo el bot está trabajando (%s). Espera a que termine y vuelve a pulsar "
                               "«Actualizar»." % ocupado, 409)
            self.actualizando = True
        try:
            res = act.actualizar(self.almacen.ruta)
        except mod_actualizar.ErrorActualizar as e:
            self.actualizando = False
            raise ErrorApi(str(e), 409)
        except BaseException:
            self.actualizando = False
            raise
        self.eventos.emitir("actualizando", sha=res.get("sha", ""))
        # (un momento para que la respuesta llegue a la ventana; luego el programa se cierra y el instalador sigue)
        temporizador = threading.Timer(2.0, self.salir.set)
        temporizador.daemon = True
        temporizador.start()
        return {"ok": True, "copia": res.get("copia") or ""}

    def _api_latido(self, metodo, partes, datos, q):
        self.ultimo_latido = time.monotonic()
        return {"ok": True}

    def _api_eventos(self, metodo, partes, datos, q):
        self.ultimo_latido = time.monotonic()           # la página sigue abierta (aunque esté minimizada)
        try:
            desde = int((q.get("desde") or ["0"])[0])
            espera = float((q.get("espera") or ["0"])[0])
        except ValueError:
            raise ErrorApi("Parámetros no válidos")
        # v3.7: mientras espera, mira cada segundo lo que hacen las tareas de Windows (tabla `en_curso`): si cambia, sale
        # el evento «externo» con la lista (así la interfaz enseña también su barra de progreso)
        fin = time.monotonic() + max(0.0, min(espera, 25.0))
        while True:
            self.revisar_en_curso()
            lista, ultimo = self.eventos.desde(desde, min(1.0, max(0.0, fin - time.monotonic())))
            if lista or time.monotonic() >= fin:
                return {"eventos": lista, "ultimo": ultimo}

    # ------------------------------------------------------ v3.7: lo que se ejecuta fuera (tareas de Windows)
    def revisar_en_curso(self, forzar=False):
        """Lee la tabla `en_curso` (como mucho una vez por segundo; borra las filas de procesos que ya no existen) y, si
        cambió, emite «externo» con la lista.  Devuelve la lista.  Nunca lanza."""
        ahora = time.monotonic()
        with self._externos_cerrojo:
            if not forzar and ahora - self._externos_cuando < 0.9:
                return list(self._externos)
            self._externos_cuando = ahora
            try:
                lista = self.almacen.lista_en_curso()
            except Exception:          # noqa: BLE001
                return list(self._externos)
            firma = json.dumps([[x.get(k) for k in ("id", "estado", "paso", "total", "texto", "pedido", "visible",
                                                     "empieza", "resumen")] for x in lista], ensure_ascii=False)
            if firma != self._externos_firma:
                self._externos_firma = firma
                self._externos = lista
                self.eventos.emitir("externo", lista=lista)
            return list(lista)

    def _api_en_curso(self, metodo, partes, datos, q):
        """GET → {lista} (lo que ejecutan las tareas de Windows).  POST en_curso/<id>/<detener|cancelar|ya|en_vivo> →
        se lo pide a esa ejecución (la ventanita y la interfaz piden lo mismo)."""
        if not partes:
            return {"lista": self.revisar_en_curso(forzar=True)}
        try:
            fid = int(partes[0])
        except ValueError:
            raise ErrorApi("Número no válido")
        accion = partes[1] if len(partes) > 1 else ""
        if metodo != "POST" or accion not in ("detener", "cancelar", "ya", "en_vivo"):
            raise ErrorApi("Acción no válida", 404)
        try:
            ok = self.almacen.pedir_en_curso(fid, accion)
        except ErrorAlmacen as e:
            raise ErrorApi(str(e))
        if not ok:
            raise ErrorApi("Esa ejecución ya terminó", 409)
        self.revisar_en_curso(forzar=True)
        return {"ok": True}

    def _programados(self, tareas):
        """v3.7: todo lo que tiene horario (reportes y Páginas con tarea, vigilancias y búsquedas de correo), con su
        «En vivo / En segundo plano» y sus avisos, para el Centro de control."""
        from . import vigilancia as mod_vigilancia
        alm = self.almacen
        existentes = {t["nombre"] for t in tareas}
        res = []

        def fila(clave, tipo, nombre, prog, tiene_tarea):
            e = horario.ejecucion(prog)
            prox = horario.proximas(prog, 1)
            res.append({"clave": clave, "tipo": tipo, "nombre": nombre, "cuando_texto": horario.describir(prog),
                        "proxima": horario.texto_fecha(prox[0]) if prox else "",
                        "cuando": prox[0].strftime("%Y-%m-%dT%H:%M") if prox else "",
                        "en_vivo": bool(e and e["en_vivo"]), "avisos_texto": horario.describir_ejecucion(e),
                        "tiene_tarea": tiene_tarea})
        for g in alm.lista_programaciones("reporte:"):
            try:
                r = alm.obtener(int(g["clave"].split(":")[1]))
            except (ValueError, IndexError):
                r = None
            if r is not None and g["programacion"]["reglas"]:
                fila(g["clave"], "reporte", r["nombre"], g["programacion"], _corto(g["tarea"]) in existentes)
        for g in alm.lista_programaciones("pagina:"):
            partes = g["clave"].split(":", 2)
            try:
                pg = alm.obtener_pagina(int(partes[1]))
            except (ValueError, IndexError, ErrorAlmacen):
                pg = None
            if pg is not None and g["programacion"]["reglas"]:
                fila(g["clave"], "pagina", pg["nombre"] + ((" — " + partes[2]) if len(partes) > 2 else ""),
                     g["programacion"], _corto(g["tarea"]) in existentes)
        for v in alm.lista_vigilancias(solo_activas=True):
            if v["programacion"]["reglas"]:
                et = mod_vigilancia.etiqueta_vigilancia(v)
                fila("vigilancia:%d" % v["id"], "vigilancia", "Vigilar «%s»%s" % (v["objetivo"], (" (%s)" % et) if et else ""),
                     v["programacion"], bool(self._tareas_de_vigilancia(v["id"], tareas)))
        for b in alm.listar_busquedas_correo(solo_activas=True):
            if b["programacion"]["reglas"]:
                fila("correo:%d" % b["id"], "correo", "Correo «%s»" % b["nombre"], b["programacion"],
                     bool(self._tareas_de_correo(b["id"], tareas)))
        res.sort(key=lambda x: x["cuando"] or "9999")
        return res

    def _api_en_vivo(self, metodo, partes, datos, q):
        """v3.7: POST {clave: «reporte:3» | «pagina:2[:Favorito]» | «vigilancia:5» | «correo:4», en_vivo: bool} → guarda
        «Ver la ejecución en vivo» de lo programado y, si tiene tarea de Windows, la actualiza (--visible / --oculto)."""
        if metodo != "POST":
            raise ErrorApi("Método no válido", 405)
        clave = str(datos.get("clave") or "")
        en_vivo = datos.get("en_vivo") is True
        tipo, _, resto = clave.partition(":")
        alm = self.almacen
        tareas = self._tareas()
        actualizada = False
        try:
            if tipo == "reporte":
                rid = int(resto)
                g = alm.programacion(clave)
                if g is None or not g["programacion"]["reglas"] or alm.obtener(rid) is None:
                    raise ErrorApi("Ese reporte no está programado")
                p = horario.con_en_vivo(g["programacion"], en_vivo)
                if _corto(g["tarea"]) in {t["nombre"] for t in tareas}:
                    self._programar(rid, "POST", {"programacion": p, "confirmar": True}, False)
                    actualizada = True
                else:
                    alm.guardar_programacion(clave, p, g["tarea"])
            elif tipo == "pagina":
                from . import paginas as mod_paginas
                sid, _, fav = resto.partition(":")
                pid = int(sid)
                g = alm.programacion(clave)
                if g is None or not g["programacion"]["reglas"]:
                    raise ErrorApi("Esa Página no está programada")
                p = horario.con_en_vivo(g["programacion"], en_vivo)
                if _corto(g["tarea"]) in {t["nombre"] for t in tareas}:
                    fila = alm.obtener_pagina(pid)
                    self._programar_pagina(pid, fila, mod_paginas.normalizar(fila["data"]),
                                           {"favorito": fav or None, "programacion": p, "confirmar": True}, False)
                    actualizada = True
                else:
                    alm.guardar_programacion(clave, p, g["tarea"])
            elif tipo == "vigilancia":
                vid = int(resto)
                v = alm.vigilancia_id(vid)
                if v is None or not v["programacion"]["reglas"]:
                    raise ErrorApi("Esa vigilancia no tiene horario")
                p = horario.con_en_vivo(v["programacion"], en_vivo)
                alm.actualizar_vigilancia(vid, programacion=p)
                if self._tareas_de_vigilancia(vid, tareas):
                    self._programar_vigilancia(alm.vigilancia_id(vid), {"programacion": p, "confirmar": True})
                    actualizada = True
            elif tipo == "correo":
                bid = int(resto)
                b = alm.busqueda_correo(bid)
                if b is None or not b["programacion"]["reglas"]:
                    raise ErrorApi("Esa búsqueda de correo no tiene horario")
                p = horario.con_en_vivo(b["programacion"], en_vivo)
                if self._tareas_de_correo(bid, tareas):
                    self._api_busquedas_correo("POST", [str(bid), "programar"], {"programacion": p, "confirmar": True})
                    actualizada = True
                else:
                    alm.guardar_busqueda_correo(dict(b, programacion=p), bid, hoy=self.hoy)
            else:
                raise ErrorApi("No se sabe qué cambiar: %s" % clave)
        except (ValueError, ErrorAlmacen, horario.ErrorHorario) as e:
            raise ErrorApi(str(e) or "No válido")
        return {"ok": True, "en_vivo": en_vivo, "tarea_actualizada": actualizada}

    def _api_ayuda(self, metodo, partes, datos, q):
        return {"plantillas": plantillas.AYUDA_PLANTILLAS, "estrategias": mod_flujo.NOMBRES_ESTRATEGIA,
                "tipos": mod_flujo.NOMBRES_TIPO, "modos_dias": mod_flujo.MODOS_DIAS,
                "opciones_defecto": mod_flujo.OPCIONES_DEFECTO, "formatos": list(mod_flujo.FORMATOS_PAGINA),
                "botones": list(mod_flujo.BOTONES)}

    def _api_detener(self, metodo, partes, datos, q):
        return self.detener()

    # --------------------------------------------------------------- inicio
    def _api_inicio(self, metodo, partes, datos, q):
        r = self.almacen.resumen_inicio(self.hoy)
        from . import vigilancia as mod_vigilancia
        tareas = self._tareas()
        # v3.4: cada vigilancia con horario, con su próxima revisión calculada (y si tiene tarea de Windows)
        vigs, de_vigilancias = [], set()
        for v in self.almacen.lista_vigilancias(solo_activas=True):
            prog = v["programacion"]
            if not prog["reglas"]:
                continue
            et = mod_vigilancia.etiqueta_vigilancia(v)
            suyas = self._tareas_de_vigilancia(v["id"], tareas)
            de_vigilancias.update(suyas)
            prox = horario.proximas(prog, 1)
            vigs.append({"nombre": "Vigilar %s«%s»%s" % ("la página " if v["tipo"] == "pagina" else "", v["objetivo"],
                                                         (" (%s)" % et) if et else ""),
                         "proxima": ((horario.texto_fecha(prox[0]) + " · ") if prox else "") + horario.describir(prog),
                         "cuando": prox[0].strftime("%Y-%m-%dT%H:%M") if prox else "",
                         "estado": "vigilancia" if suyas else "vigilancia — SIN tarea de Windows: no se revisará sola",
                         "sin_tarea": not suyas, "vigilancia_id": v["id"]})
        # v3.4: las búsquedas de correo con horario (próxima revisión, y si tienen tarea de Windows)
        for b in self.almacen.listar_busquedas_correo(solo_activas=True):
            prog = b["programacion"]
            if not prog["reglas"]:
                continue
            suyas = self._tareas_de_correo(b["id"], tareas)
            de_vigilancias.update(suyas)
            prox = horario.proximas(prog, 1)
            vigs.append({"nombre": "Revisar el correo «%s»" % b["nombre"],
                         "proxima": ((horario.texto_fecha(prox[0]) + " · ") if prox else "") + horario.describir(prog),
                         "cuando": prox[0].strftime("%Y-%m-%dT%H:%M") if prox else "",
                         "estado": "correo" if suyas else "correo — SIN tarea de Windows: no se revisará solo",
                         "sin_tarea": not suyas, "correo_id": b["id"]})
        vigs.sort(key=lambda x: x["cuando"] or "9999")
        guardadas = {}
        for g in self.almacen.lista_programaciones():
            if g["tarea"]:
                guardadas[_corto(g["tarea"])] = g["programacion"]
        otras = []
        for t in tareas:
            if t["nombre"] in de_vigilancias:
                continue
            t = dict(t)
            if t["nombre"] in guardadas:
                t["cuando_texto"] = horario.describir(guardadas[t["nombre"]])
            otras.append(t)
        proximas = (vigs + otras)[:10]
        # v3.5 «Centro de control»: series de 7 días (chispas), los reportes como filas densas, lo último del correo y la
        # novedad de vigilancia más reciente.  Todo en una sola llamada (la página no hace N peticiones).
        serie = self.almacen.serie_dias(self.hoy)
        r["descargas_hoy"] = serie["descargas"][-1]
        r["descargas_ayer"] = serie["descargas"][-2]
        t = self.trabajo
        en_curso = t.a_dict() if t is not None and t.estado == "en_curso" else None
        historial = self.almacen.historial(limite=40)
        correo = next((e for e in historial if e.get("correo_id")), None)
        return {"kpi": r, "ultimas": historial[:12], "proximas": proximas,
                "notificaciones": self.almacen.notificaciones(limite=8), "serie": serie,
                "externos": self.revisar_en_curso(forzar=True), "programados": self._programados(tareas),
                "reportes": self._filas_inicio(tareas), "en_curso": en_curso,
                "tareas_activas": len(tareas), "vigilancia_novedad": self._novedad_vigilancia(),
                "correo_ultimo": correo}

    def _filas_inicio(self, tareas):
        """v3.5: cada reporte para el Centro de control: estado (ok/error/curso/programado/nuevo), sitio, la última
        ejecución (archivo, duración, mensaje), su horario y la próxima ejecución según Windows."""
        alm = self.almacen
        ultimas = alm.ultimas_por_reporte()
        vigilados = {v["reporte_id"] for v in alm.lista_vigilancias(tipo="reporte")}
        por_nombre = {x["nombre"]: x for x in tareas}
        progs = {}
        for g in alm.lista_programaciones("reporte:"):
            try:
                progs[int(g["clave"].split(":")[1])] = g
            except (KeyError, ValueError, IndexError, TypeError):
                pass
        t = self.trabajo
        curso = t.objetivo.get("reporte_id") if t is not None and t.estado == "en_curso" else None
        res = []
        for x in alm.listar():
            u = ultimas.get(x["id"]) or {}
            g = progs.get(x["id"])
            tarea = por_nombre.get(_corto((g or {}).get("tarea", ""))) or por_nombre.get(x["nombre"])
            estado = u.get("resultado") or ""
            if curso == x["id"]:
                estado = "curso"
            elif not estado:
                estado = "programado" if tarea else "nuevo"
            res.append({"id": x["id"], "nombre": x["nombre"], "url": x["url"] or "",
                        "sitio": urlparse(x["url"] or "").hostname or "", "estado": estado,
                        "resultado": u.get("resultado") or "", "ultima": u.get("cuando") or "",
                        "mensaje": u.get("mensaje") or "", "archivos": u.get("archivos") or [],
                        "duracion": u.get("duracion"), "vigilado": x["id"] in vigilados,
                        "programado": bool(tarea), "proxima": (tarea or {}).get("proxima", ""),
                        "fechas": self._fechas_de_reporte(x["id"]),
                        "cuando_texto": horario.describir(g["programacion"]) if g else ""})
        return res

    def _fechas_de_reporte(self, rid):
        """v3.8: lo que el chip «Fecha: …» enseña y cambia: los campos de fecha del reporte, sus listas «por fecha» y las
        listas «la más reciente» (se pasan a «por fecha» solo si el usuario lo elige)."""
        from . import filtros as mod_filtros
        try:
            fl = self.almacen.cargar_flujo(rid)
        except Exception:                 # noqa: BLE001 (un reporte dañado no impide enseñar los demás)
            return []
        res = []
        for i, p in mod_filtros.pasos_filtro(fl):
            lista = p.tipo == "elegir_opcion" and (p.estrategia or "fija") in ("por_fecha", "mas_reciente")
            if p.tipo != "escribir" and not lista:
                continue
            res.append({"paso": i, "nombre": p.filtro or p.objetivo or "Fecha", "valor": p.valor or "", "lista": lista,
                        "estrategia": (p.estrategia or "fija") if lista else "",
                        "formato": plantillas.formato_de_fecha(p.valor) or ""})
        return res

    def _novedad_vigilancia(self):
        """v3.5: la opción nueva (sin descargar) más reciente de todas las vigilancias, o None."""
        from . import vigilancia as mod_vigilancia
        mejor = None
        for v in self.almacen.lista_vigilancias():
            for o in self.almacen.opciones_de_vigilancia(v["id"]):
                if not o["nueva"] or o["descargada"]:
                    continue
                clave = (o.get("novedad") or o.get("primera_vez") or "", mod_flujo.clave_reciente(o["texto"]))
                if mejor is None or clave > mejor[0]:
                    mejor = (clave, v, o)
        if mejor is None:
            return None
        _c, v, o = mejor
        return {"vigilancia_id": v["id"], "texto": o["texto"], "periodo": mod_flujo.describir_opcion(o["texto"]),
                "objetivo": v["objetivo"], "etiqueta": mod_vigilancia.etiqueta_vigilancia(v), "tipo": v["tipo"],
                "reporte_id": v.get("reporte_id"), "pagina_id": v.get("pagina_id"),
                "cuando": o.get("novedad") or o.get("primera_vez") or ""}

    def _api_buscador(self, metodo, partes, datos, q):
        """v3.5: lo que se puede buscar con Ctrl K (reportes, Páginas, vigilancias y búsquedas de correo), sin nada lento
        (ni tareas de Windows ni contraseñas)."""
        from . import vigilancia as mod_vigilancia
        alm = self.almacen
        return {"reportes": [{"id": x["id"], "nombre": x["nombre"], "sitio": urlparse(x["url"] or "").hostname or ""}
                             for x in alm.listar()],
                "paginas": [{"id": p["id"], "nombre": p["nombre"]} for p in alm.listar_paginas()],
                "vigilancias": [{"id": v["id"], "objetivo": v["objetivo"], "etiqueta": mod_vigilancia.etiqueta_vigilancia(v),
                                 "activa": bool(v["activa"])} for v in alm.lista_vigilancias()],
                "busquedas": [{"id": b["id"], "nombre": b["nombre"], "activa": bool(b["activa"])}
                              for b in alm.listar_busquedas_correo()]}

    # ------------------------------------------------------ v3.4: programación completa
    def _api_horario(self, metodo, partes, datos, q):
        """POST {programacion, n?, vacio?} → {valida, programacion (normalizada), descripcion, proximas [{fecha, texto}],
        avisos, disparadores} o {valida: false, error}.  La interfaz lo usa para la vista previa del editor «Cuándo»."""
        try:
            n = min(max(int(datos.get("n") or 5), 1), 20)
        except (TypeError, ValueError):
            n = 5
        return horario.vista(datos.get("programacion"), n=n, vacio=datos.get("vacio") or "solo a mano")

    def _tareas(self):
        """Las tareas del bot en Windows (solo se LEEN); [] si no se puede.  v3.5: con caché de `TTL_TAREAS` segundos
        (schtasks /Query tarda ~1 s); se vacía al crear o borrar una tarea desde el bot (`_ejecutor_tareas`)."""
        with self._tareas_cerrojo:
            cache = self._tareas_cache
            if cache is not None and time.monotonic() - cache[0] < TTL_TAREAS:
                return list(cache[1])
            if cache is not None and self.tareas_en_segundo_plano:
                if not self._tareas_releyendo:            # la anterior ya sirve; se relee sin hacer esperar a nadie
                    self._tareas_releyendo = True
                    threading.Thread(target=self._releer_tareas, name="tareas-windows", daemon=True).start()
                return list(cache[1])
            return list(self._leer_tareas())

    def _leer_tareas(self):
        try:
            lista = list(self.listar_tareas() or [])
        except Exception:              # noqa: BLE001
            lista = []
        self._tareas_cache = (time.monotonic(), lista)
        return lista

    def _releer_tareas(self):
        try:
            try:                                          # (se lee fuera del cerrojo: nadie espera)
                lista = list(self.listar_tareas() or [])
            except Exception:          # noqa: BLE001
                lista = []
            with self._tareas_cerrojo:
                self._tareas_cache = (time.monotonic(), lista)
        finally:
            self._tareas_releyendo = False

    def invalidar_tareas(self):
        """v3.5: la próxima consulta vuelve a leer las tareas de Windows (tras crear o borrar una)."""
        with self._tareas_cerrojo:
            self._tareas_cache = None

    def precargar_tareas(self):
        """v3.5: lee las tareas de Windows en otro hilo (al abrir la interfaz), para que el Inicio no espere."""
        threading.Thread(target=self._tareas, name="tareas-windows", daemon=True).start()

    def _ejecutor_tareas(self, cmd):
        """v3.5: lo que ejecuta schtasks al crear/borrar (el inyectado en pruebas o el de verdad) y vacía la caché."""
        try:
            return (self.ejecutar_tareas or programador._ejecutar)(cmd)
        finally:
            self.invalidar_tareas()

    @staticmethod
    def _tareas_de_vigilancia(vid, tareas):
        """Nombres de las tareas de Windows de la vigilancia `vid` («Vigilar … #N»: el nombre cambia si se renombra)."""
        fin = re.compile(r" #%d$" % int(vid))
        return [t["nombre"] for t in tareas if t["nombre"].startswith("Vigilar ") and fin.search(t["nombre"])]

    def _db_para_tarea(self):
        por_defecto = os.path.abspath(os.path.join(RAIZ, "datos", "bot.db"))
        return None if os.path.abspath(self.almacen.ruta) == por_defecto else self.almacen.ruta

    def _programar_con_horario(self, tarea, prog, datos, comando, clave=None, sustituir=()):
        """v3.4: tarea de Windows con varios disparadores (XML).  Sin `confirmar`: muestra lo que se creará (comando
        schtasks, el programa que ejecuta, el horario en español, los disparadores, las próximas ejecuciones y el XML);
        con `confirmar: true` la crea (o la sustituye), borra las tareas antiguas de `sustituir` y guarda la programación
        en `clave`.  `comando` = argumentos de `programador.comando_bot`."""
        try:
            p = horario.normalizar(prog)
        except horario.ErrorHorario as e:
            raise ErrorApi(str(e))
        if not p["reglas"]:
            raise ErrorApi("No hay nada que programar: elige los días y las horas en «Cuándo»")
        comando = dict(comando, **programador.opciones_comando(p))      # v3.7: «Avisos y vista» (si lo tiene)
        try:
            linea = programador.comando_bot(os.path.join(RAIZ, "bot.py"), db=self._db_para_tarea(), **comando)
            nombre = programador.nombre_tarea(tarea)
            desc = horario.describir(p)
            xml = programador.construir_xml_tarea(p, linea, "Bot Web: %s — %s" % (tarea, desc), nombre=tarea)
            disp = programador.disparadores(p)
        except (programador.ErrorProgramador, horario.ErrorHorario) as e:
            raise ErrorApi(str(e))
        existentes = {t["nombre"] for t in self._tareas()}
        corto = _corto(nombre)
        otras = sorted({n for n in sustituir if n and n != corto and n in existentes})
        res = {"tarea": nombre, "descripcion": desc, "programa": linea, "existe": corto in existentes,
               "sustituye": otras, "disparadores": [d["texto"] for d in disp],
               "proximas": horario.vista(p)["proximas"], "programacion": p,
               "ejecucion": horario.ejecucion(p), "ejecucion_texto": horario.describir_ejecucion(horario.ejecucion(p)),
               "en_vivo": bool((horario.ejecucion(p) or {}).get("en_vivo"))}
        if datos.get("confirmar") is True:
            try:
                salida = programador.crear_con_xml(tarea, xml, confirmado=True, ejecutor=self._ejecutor_tareas)
            except programador.ErrorProgramador as e:
                raise ErrorApi(str(e))
            for n in otras:                       # la misma vigilancia con otro nombre (se renombró): la vieja sobra
                try:
                    programador.borrar(n, confirmado=True, ejecutor=self._ejecutor_tareas)
                except programador.ErrorProgramador as e:
                    self._log("No se pudo borrar la tarea antigua «%s»: %s" % (n, e))
            if clave:
                self.almacen.guardar_programacion(clave, p, nombre)
            self._log("Tarea de Windows «%s» creada: %s" % (nombre, desc))
            res.update(creada=True, salida=salida)
            self._arrancar_si_ya_paso_el_aviso(p, linea, nombre, res)
            return res
        res.update(creada=False, xml=xml,
                   comando=programador.como_texto(programador.construir_comando_xml(tarea, programador.RUTA_XML_EJEMPLO)))
        return res

    def _arrancar_si_ya_paso_el_aviso(self, p, linea, nombre, res, ahora=None):
        """v3.6.1: con «Avisarme N min antes» la tarea de Windows empieza N minutos antes de la hora.  Si la próxima
        ejecución es dentro de menos de N minutos (se acaba de poner p. ej. «hoy a las 14:39» a las 14:38), ese arranque
        adelantado ya pasó y Windows no la ejecutaría hoy: se lanza ahora el mismo programa, que avisa y espera a la
        hora exacta (`--aviso-antes`).  `res["arrancada"]` = la hora."""
        try:
            n = int((horario.ejecucion(p) or {}).get("avisar_antes") or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            return False
        ahora = ahora or datetime.datetime.now()
        cuando = horario.siguiente_en(p, ahora, n)
        if cuando is None or cuando <= ahora or cuando - datetime.timedelta(minutes=n) > ahora:
            return False
        lanzar = self.lanzar_proceso
        if lanzar is None:
            return False
        try:
            lanzar(linea)
        except Exception as e:         # noqa: BLE001
            self._log("No se pudo arrancar «%s» para hoy: %s" % (nombre, e))
            return False
        res["arrancada"] = cuando.strftime("%H:%M")
        self._log("«%s»: el aviso de %d min antes ya pasó; se arranca ahora y se ejecutará a las %s"
                  % (nombre, n, res["arrancada"]))
        return True

    def _quitar_tareas(self, nombres, datos, clave=None):
        """Borra tareas de Windows del bot.  Sin `confirmar`: dice cuáles y con qué comando; con `confirmar: true`, las
        borra."""
        existentes = {t["nombre"] for t in self._tareas()}
        nombres = [n for n in dict.fromkeys(nombres) if n and n in existentes]
        if not nombres:
            raise ErrorApi("No hay ninguna tarea de Windows que quitar")
        if datos.get("confirmar") is not True:
            return {"borrada": False, "tareas": nombres,
                    "comandos": [programador.como_texto(programador.construir_comando_borrar(n)) for n in nombres]}
        for n in nombres:
            try:
                programador.borrar(n, confirmado=True, ejecutor=self._ejecutor_tareas)
            except programador.ErrorProgramador as e:
                raise ErrorApi(str(e))
        if clave:
            self.almacen.borrar_programacion(clave)
        return {"borrada": True, "tareas": nombres}

    def _vista_programacion(self, clave, tarea):
        """Lo guardado de un reporte/Página (para rellenar la ventana «Programar…») y si su tarea existe."""
        guardada = self.almacen.programacion(clave)
        existentes = {t["nombre"] for t in self._tareas()}
        corto = _corto(programador.nombre_tarea(tarea))
        return {"tarea": programador.nombre_tarea(tarea),
                "existe": corto in existentes or bool(guardada and _corto(guardada["tarea"]) in existentes),
                "guardada": guardada["programacion"] if guardada else None,
                "descripcion": horario.describir(guardada["programacion"], "sin programar") if guardada else "sin programar"}

    # ------------------------------------------------------------- reportes
    def _api_reportes(self, metodo, partes, datos, q):
        alm = self.almacen
        if not partes:
            if metodo == "GET":
                vig = {v["reporte_id"]: v for v in alm.vigilancias()}
                res = []
                for r in alm.listar():
                    r = dict(r)
                    r["vigilancia"] = bool(vig.get(r["id"]))
                    r["fechas"] = self._fechas_de_reporte(r["id"])
                    res.append(r)
                return {"reportes": res}
            if metodo == "POST":
                fl = _flujo_desde(datos.get("flujo"))
                if datos.get("nombre"):
                    fl.nombre = datos["nombre"]
                rid = self._guardar_flujo(fl, None)
                return {"id": rid, "nombre": fl.nombre}
            raise ErrorApi("Método no válido", 405)
        try:
            rid = int(partes[0])
        except ValueError:
            raise ErrorApi("Número de reporte no válido")
        accion = partes[1] if len(partes) > 1 else ""
        if accion == "" and metodo == "GET":
            fila = alm.obtener(rid)
            if fila is None:
                raise ErrorApi("No existe el reporte %d" % rid, 404)
            fl = alm.cargar_flujo(rid)
            return {"id": rid, "nombre": fila["nombre"], "flujo": fl.a_dict(),
                    "pasos": [_paso_dict(p, i) for i, p in enumerate(fl.pasos)], "problemas": fl.problemas(),
                    "vigilancia": alm.vigilancia(rid), "pares": mod_flujo.pares_lista_opcion(fl.pasos),
                    "ultima": alm.ultima_ejecucion(rid), "versiones": alm.versiones(rid)[:10]}
        if accion == "" and metodo == "PUT":
            fl = _flujo_desde(datos.get("flujo"))
            if datos.get("nombre"):
                fl.nombre = datos["nombre"]
            self._guardar_flujo(fl, rid)
            return {"id": rid, "nombre": fl.nombre}
        if accion == "" and metodo == "DELETE":
            alm.eliminar(rid)
            return {"ok": True}
        if accion == "duplicar" and metodo == "POST":
            return {"id": alm.duplicar(rid)}
        if accion == "renombrar" and metodo == "POST":
            return {"nombre": alm.renombrar(rid, datos.get("nombre"))}
        if accion == "historial":
            return {"historial": alm.historial(rid, limite=50)}
        if accion == "versiones" and metodo == "POST":
            return {"id": alm.restaurar_version(int(datos.get("version")))}
        if accion == "programar":
            return self._programar(rid, metodo, datos, vigilar=False)
        if accion == "quitar_tarea" and metodo == "POST":            # v3.4
            g = alm.programacion("reporte:%d" % rid)
            return self._quitar_tareas([alm.obtener(rid)["nombre"], _corto((g or {}).get("tarea", ""))], datos,
                                       clave="reporte:%d" % rid)
        if accion == "filtros":
            return self._api_filtros(rid, metodo, partes[2] if len(partes) > 2 else "", datos)
        raise ErrorApi("Acción no válida: %s" % accion, 404)

    # ------------------------------------------------------- v3.1: usar filtros
    def _panel_filtros(self, rid, elecciones=None):
        from . import filtros as mod_filtros
        alm = self.almacen
        fila = alm.obtener(rid)
        if fila is None:
            raise ErrorApi("No existe el reporte %d" % rid, 404)
        fl = alm.cargar_flujo(rid)
        vig = alm.vigilancia(rid)
        novedades, vistas = {}, None
        for v in alm.lista_vigilancias(reporte_id=rid):            # v3.3: la marca «nueva» de todas sus vigilancias
            novedades[int(v["paso"])] = alm.novedades(rid, v["paso"], mod_filtros.DIAS_NUEVA)
        if vig is not None:
            vistas = [o["texto"] for o in alm.opciones_vistas(rid, vig["paso"])]
        try:
            lista = mod_filtros.datos_panel(fl, alm.opciones_filtro(rid), alm.mapas(rid, limite=5), novedades,
                                            vig["paso"] if vig else None, elecciones, vistas)
        except mod_filtros.ErrorFiltros as e:
            raise ErrorApi(str(e))
        return fl, {"id": rid, "nombre": fila["nombre"], "filtros": lista,
                    "max_sin_confirmar": mod_filtros.MAX_SIN_CONFIRMAR, "max_ejecuciones": mod_filtros.MAX_EJECUCIONES}

    @staticmethod
    def _con_nombres(fl, lista):
        """Copia del flujo con el nombre de cada filtro (para el registro); el reporte guardado no cambia."""
        copia = fl.copia()
        for d in lista:
            p = copia.pasos[d["paso"]]
            if not p.filtro:
                p.filtro = d["nombre"]
        return copia

    def _api_filtros(self, rid, metodo, accion, datos):
        from . import filtros as mod_filtros
        alm = self.almacen
        elecciones = datos.get("elecciones") or {}
        if accion == "":
            return self._panel_filtros(rid, elecciones if metodo == "POST" else None)[1]
        if metodo != "POST":
            raise ErrorApi("Método no válido", 405)
        fl, panel = self._panel_filtros(rid, elecciones)
        nombres = {d["paso"]: d["nombre"] for d in panel["filtros"]}
        try:
            if accion == "nombre":
                paso = int(datos.get("paso"))
                if paso not in nombres:
                    raise ErrorApi("El paso %d no es un filtro" % (paso + 1))
                fl.pasos[paso].filtro = mod_filtros.validar_nombre(datos.get("nombre"))
                self._guardar_flujo(fl, rid)
                return {"ok": True, "nombre": fl.pasos[paso].filtro}
            if accion == "predeterminado":
                buenos = {d["paso"]: d["nombre"] for d in panel["filtros"] if d["origen_nombre"] != "numero"}
                buenos.update({int(k): mod_filtros.validar_nombre(v) for k, v in (datos.get("nombres") or {}).items()})
                alm.guardar_version(rid, "antes de «Guardar como predeterminado» en «Usar filtros»")
                lineas = mod_filtros.guardar_predeterminado(fl, elecciones, buenos)
                self._guardar_flujo(fl, rid)
                return {"ok": True, "cambios": lineas}
            if accion == "descargar":
                combos = mod_filtros.combinaciones(fl, elecciones)
                n = len(combos)
                if n > mod_filtros.MAX_EJECUCIONES:
                    raise ErrorApi("Son %d ejecuciones: el máximo es %d. Elige menos opciones." % (
                        n, mod_filtros.MAX_EJECUCIONES))
                if n > mod_filtros.MAX_SIN_CONFIRMAR and datos.get("confirmar") is not True:
                    return {"confirmar": True, "n": n, "mensaje": "Con estas opciones el reporte se ejecutará %d veces "
                            "(una por cada combinación). ¿Seguro?" % n}
                return self._lanzar_filtros(fl, rid, panel, combos, datos.get("ver")).a_dict()
            if accion == "actualizar":
                combos = mod_filtros.combinaciones(fl, elecciones)
                ultimo = mod_filtros.ultimo_filtro(fl)
                if ultimo is None:
                    raise ErrorApi("Este reporte no tiene filtros")
                return self._lanzar_actualizar(fl, rid, panel, combos[0][0] if combos else {}, ultimo).a_dict()
        except mod_filtros.ErrorFiltros as e:
            raise ErrorApi(str(e))
        raise ErrorApi("Acción no válida: %s" % accion, 404)

    def _lanzar_filtros(self, fl, rid, panel, combos, ver):
        from . import filtros as mod_filtros
        base = self._con_nombres(fl, panel["filtros"])
        n = len(combos)
        # se comprueba antes de empezar que los cambios se pueden aplicar
        for cambios, sufijo in combos:
            mod_filtros.aplicar(base, cambios, sufijo)

        def trabajo(t):
            t.total = n if n > 1 else len(base.pasos)
            bien, archivos, errores = 0, [], []
            for k, (cambios, sufijo) in enumerate(combos, 1):
                if t.detener.is_set():
                    break
                flujo_k, _l = mod_filtros.aplicar(base, {}, sufijo)          # solo el nombre de los archivos
                etiqueta = " · ".join(sufijo or []) or "con los filtros elegidos"
                if n > 1:
                    self.eventos.emitir("lote", n=k, total=n, nombre=etiqueta, fase="inicio", estado="en_curso")
                    self._log("=== «%s» (%d de %d): %s ===" % (fl.nombre, k, n, etiqueta))
                ej = self.crear_ejecutor(t, flujo_k, rid, ver=ver, filtros=cambios)
                res = ej.ejecutar()
                try:
                    self.almacen.registrar_resultado(rid, res)
                except Exception:      # noqa: BLE001
                    pass
                self.eventos.emitir("resultado", trabajo=t.id, reporte_id=rid, ok=res.ok, resumen=res.resumen(),
                                    registro=res.ruta_log, captura=res.ruta_captura, archivos=res.archivos)
                if res.ok:
                    bien += 1
                    archivos += res.archivos
                else:
                    errores.append("%s: %s" % (etiqueta, res.resumen()))
            hechas = bien + len(errores)
            if n == 1:
                return bien == 1, (errores[0] if errores else "Descargado con los filtros elegidos" +
                                   ("; archivos: " + ", ".join(os.path.basename(a) for a in archivos) if archivos else ""))
            txt = "Descargas con filtros de «%s»: %d de %d bien" % (fl.nombre, bien, n)
            if hechas < n:
                txt += " (detenido tras %d)" % hechas
            if archivos:
                txt += "; archivos: " + ", ".join(os.path.basename(a) for a in archivos)
            if errores:
                txt += "; fallaron: " + " | ".join(errores[:3])
            return bien == n, txt
        return self.lanzar("ejecutar" if n == 1 else "filtros", "Descargar «%s» con filtros%s" % (
            fl.nombre, (" (%d ejecuciones)" % n) if n > 1 else ""), trabajo, reporte_id=rid)

    def _lanzar_actualizar(self, fl, rid, panel, cambios, ultimo):
        base = self._con_nombres(fl, panel["filtros"])

        def trabajo(t):
            t.total = ultimo + 1
            ej = self.crear_ejecutor(t, base, rid, ver=False, hasta=ultimo + 1, filtros=cambios, solo_leer=True)
            res = ej.ejecutar()
            try:
                self.almacen.guardar_opciones_leidas(rid, res, "actualizar")
            except Exception:          # noqa: BLE001
                pass
            n = len(res.opciones_leidas)
            self.eventos.emitir("filtros_actualizados", reporte_id=rid, ok=res.ok, listas=n)
            if res.ok:
                return True, "Opciones actualizadas: %d lista(s) leída(s)" % n
            return False, "%s%s" % (res.resumen(), (" (se guardaron %d lista(s) leídas antes del error)" % n) if n else "")
        return self.lanzar("actualizar_filtros", "Actualizar las opciones de «%s»" % fl.nombre, trabajo)

    def _guardar_flujo(self, fl, rid):
        problemas = [p for p in fl.problemas() if "Repetir por días" in p]
        if problemas:
            raise ErrorApi(problemas[0])
        try:
            return self.almacen.guardar(fl, rid)
        except ErrorAlmacen as e:
            raise ErrorApi(str(e))

    def _api_papelera(self, metodo, partes, datos, q):
        if not partes:
            return {"reportes": self.almacen.papelera()}
        rid = int(partes[0])
        if len(partes) > 1 and partes[1] == "restaurar" and metodo == "POST":
            return {"nombre": self.almacen.restaurar(rid)}
        if metodo == "DELETE" and datos.get("confirmar") is True:
            self.almacen.borrar_definitivo(rid)
            return {"ok": True}
        raise ErrorApi("Para borrar definitivamente hay que confirmarlo", 400)

    def _api_flujo(self, metodo, partes, datos, q):
        """Utilidades sobre un reporte que se está editando (sin guardarlo)."""
        fl = _flujo_desde(datos.get("flujo"))
        accion = partes[0] if partes else "describir"
        if accion == "convertir_listas":
            pares = datos.get("pares")
            est = {int(k): v for k, v in (datos.get("estrategias") or {}).items()}
            mensajes = mod_flujo.convertir_listas(fl, pares=pares, estrategias=est)
            return {"flujo": fl.a_dict(), "mensajes": mensajes, "pasos": [_paso_dict(p, i) for i, p in enumerate(fl.pasos)]}
        if accion == "usar_nombre_reporte":        # v3.5: «Usar el nombre del reporte» en las descargas
            cambios = mod_flujo.usar_nombre_del_reporte(fl, solo_de_la_web=datos.get("solo_de_la_web") is not False)
            return {"flujo": fl.a_dict(), "cambios": [{"paso": i, "antes": a, "despues": d} for i, a, d in cambios],
                    "pasos": [_paso_dict(p, i) for i, p in enumerate(fl.pasos)]}
        if accion == "describir":
            return {"pasos": [_paso_dict(p, i) for i, p in enumerate(fl.pasos)], "problemas": fl.problemas(),
                    "pares": mod_flujo.pares_lista_opcion(fl.pasos), "flujo": fl.a_dict(),
                    "nombres_web": mod_flujo.pasos_con_nombre_de_la_web(fl),
                    "dias": [d.isoformat() for d in mod_flujo.dias_a_repetir(fl.opciones.get("repetir_dias"), self.hoy)]
                    if not [p for p in fl.problemas() if "Repetir" in p] else []}
        if accion == "paso":
            try:
                p = Paso.desde_dict(datos.get("paso"))
            except (ErrorFlujo, TypeError) as e:
                raise ErrorApi("El paso no es válido: %s" % e)
            return {"paso": _paso_dict(p)}
        raise ErrorApi("Acción no válida", 404)

    def _api_plantilla(self, metodo, partes, datos, q):
        texto = datos.get("texto") or ""
        if datos.get("archivo"):
            return self._vista_archivo(datos)
        try:
            vista = plantillas.renderizar(texto, variables=datos.get("variables") or {}, hoy=self.hoy,
                                          enmascarar_secretos=True, ext=datos.get("ext") or ".xlsx",
                                          nombre=datos.get("nombre") or "nombre_que_da_la_web", fecha=None,
                                          reporte=datos.get("reporte") or "Nombre del reporte")
            return {"vista": vista, "error": ""}
        except plantillas.ErrorPlantilla as e:
            return {"vista": "", "error": str(e)}

    def _vista_archivo(self, datos):
        """v3.7: «Se guardará como: <archivo> en <carpeta>».  POST /api/plantilla con `archivo`:
        - «descargar» / «guardar_pagina»: `texto` = el «Nombre del archivo» tal como se escribe (la extensión se pone sola
          en las descargas), `reporte`, `variables` (las del reporte), `carpeta` (la del reporte), `subcarpeta` (la
          propia del paso), `formato` (Guardar página);
        - «pagina»: `texto` = el nombre de los archivos de la Página, `pagina` = {nombre, data} (o `pagina_id`),
          `carpeta`.
        Devuelve {vista, archivo, carpeta, ruta, error}."""
        from . import paginas as mod_paginas
        texto = str(datos.get("texto") or "")
        carpeta = str(datos.get("carpeta") or "").strip()
        try:
            if datos.get("archivo") == "pagina":
                p = datos.get("pagina") or {}
                data, nombre = p.get("data"), p.get("nombre")
                if data is None and datos.get("pagina_id"):
                    fila, data = self._pagina_fila(int(datos["pagina_id"]))
                    nombre = nombre or fila["nombre"]
                data = mod_paginas.normalizar(data or {"filtros": [], "llegada": []})
                archivo, carpeta_v = mod_paginas.vista_archivo(data, nombre or "Página", texto.strip(), hoy=self.hoy,
                                                               carpeta=carpeta, carpeta_forzada=self.carpeta_descargas)
            else:
                tipo = "guardar_pagina" if datos.get("archivo") == "guardar_pagina" else "descargar"
                plantilla = texto.strip() if tipo == "guardar_pagina" else mod_flujo.nombre_con_ext(texto)
                variables = {str(k): str(v) for k, v in (datos.get("variables") or {}).items()}
                variables.setdefault("opcion", "opción elegida")
                archivo, carpeta_v = mod_flujo.vista_archivo(
                    plantilla, tipo, reporte=datos.get("reporte") or "Nombre del reporte", variables=variables,
                    hoy=self.hoy, carpeta=carpeta, subcarpeta=str(datos.get("subcarpeta") or "").strip(),
                    formato=datos.get("formato") or "pdf", carpeta_forzada=self.carpeta_descargas)
        except (plantillas.ErrorPlantilla, mod_paginas.ErrorPagina) as e:
            return {"vista": "", "archivo": "", "carpeta": "", "ruta": "", "error": str(e)}
        return {"vista": archivo, "archivo": archivo, "carpeta": carpeta_v, "ruta": os.path.join(carpeta_v, archivo),
                "error": ""}

    # ------------------------------------------------- v3.5: elegir una carpeta o un archivo
    def _api_elegir(self, metodo, partes, datos, q):
        """POST {tipo: carpeta|archivo|guardar, inicial, filtros: [[«Excel», «*.xlsx»]…], titulo} → {ruta} (None si se
        cancela).  Abre el explorador de Windows EN ESTE PC (el del usuario: el servidor solo escucha en 127.0.0.1 y pide
        el token de la sesión) y espera a que se elija algo."""
        from . import dialogos
        if metodo != "POST":
            raise ErrorApi("Método no válido", 405)
        tipo = datos.get("tipo") or "carpeta"
        if tipo not in dialogos.TIPOS:
            raise ErrorApi("Tipo no válido: %s (carpeta, archivo o guardar)" % tipo)
        inicial = str(datos.get("inicial") or "").strip()
        if "{" in inicial:                          # plantillas: se abre en la parte fija («Correo\{fecha_correo:%Y-%m}»)
            inicial = os.path.dirname(inicial.split("{", 1)[0]) if tipo != "carpeta" else inicial.split("{", 1)[0]
        if inicial:
            inicial = os.path.expanduser(os.path.expandvars(inicial))
            if not os.path.isabs(inicial):          # «migracion» = dentro de la carpeta de descargas del bot
                inicial = os.path.join(self._carpeta_descargas(), inicial)
        else:
            inicial = self._carpeta_descargas()
        filtros = datos.get("filtros") if isinstance(datos.get("filtros"), list) else None
        try:
            ruta = dialogos.elegir(tipo, inicial, filtros, datos.get("titulo"), abrir=self.abrir_dialogo)
        except dialogos.ErrorDialogo as e:
            raise ErrorApi(str(e))
        return {"ruta": ruta, "cancelado": ruta is None}

    # ------------------------------------------------------------ ejecutar
    def _api_ejecutar(self, metodo, partes, datos, q):
        ver = datos.get("ver")
        lento = bool(datos.get("lento"))
        variables = {str(k): str(v) for k, v in (datos.get("variables") or {}).items()}
        if datos.get("flujo") is not None:                 # el del editor, aunque no esté guardado
            fl = _flujo_desde(datos["flujo"])
            rid = datos.get("reporte_id")
            return self._lanzar_uno(fl, int(rid) if rid else None, ver, lento, variables).a_dict()
        ids = [int(i) for i in datos.get("ids") or []]
        if not ids:
            raise ErrorApi("Elige al menos un reporte")
        if len(ids) == 1:
            fl = self.almacen.cargar_flujo(ids[0])
            return self._lanzar_uno(fl, ids[0], ver, lento, variables).a_dict()
        return self._lanzar_lote(ids, ver, lento, variables).a_dict()

    def _lanzar_uno(self, fl, rid, ver, lento, variables):
        problemas = fl.problemas()
        if problemas:
            raise ErrorApi("El reporte tiene errores: " + "; ".join(problemas[:3]))

        def trabajo(t):
            t.total = len(fl.pasos)
            ej = self.crear_ejecutor(t, fl, rid, ver=ver, lento=lento, variables=variables)
            res = ej.ejecutar()
            if rid is not None:
                try:
                    self.almacen.registrar_resultado(rid, res)
                except Exception:      # noqa: BLE001
                    pass
            self.eventos.emitir("resultado", trabajo=t.id, reporte_id=rid, ok=res.ok, resumen=res.resumen(),
                                registro=res.ruta_log, captura=res.ruta_captura, archivos=res.archivos)
            return res.ok, res.resumen()
        return self.lanzar("ejecutar", "Ejecutar «%s»" % fl.nombre, trabajo, reporte_id=rid)

    def _lanzar_lote(self, ids, ver, lento, variables):
        from . import lote

        def trabajo(t):
            t.total = len(ids)
            ajustes = self.almacen.ajustes()
            v = ajustes.get("ver_mientras_trabaja", True) if ver is None else ver

            def fabrica(fl, **kw):
                from .ejecutor import Ejecutor
                kw.update(progreso=lambda i, estado, texto="": self._progreso(t, i, estado, texto, fl.nombre),
                          notificar=self._notificar)
                return Ejecutor(fl, **kw)
            res = lote.ejecutar_lote(ids, carpeta_perfiles=self.carpeta_perfiles, carpeta_registros=self.carpeta_registros,
                                     carpeta_descargas=self.carpeta_descargas, oculto=self._oculto(v), lento=lento,
                                     variables=variables, log=self._log, detener=t.detener, almacen=self.almacen,
                                     pedir_acceso=self._pedir_acceso(t), hoy=self.hoy, fabrica_ejecutor=fabrica,
                                     aviso_lote=lambda n, total, item, fase: self.eventos.emitir(
                                         "lote", n=n, total=total, nombre=item.nombre, fase=fase, estado=item.estado,
                                         trabajo=t.id, reporte_id=item.ruta if isinstance(item.ruta, int) else None))
            return res.ok, res.resumen()
        return self.lanzar("lote", "Lote de %d reportes" % len(ids), trabajo)

    # ----------------------------------------------------------- preguntas
    def _preguntas(self):
        res = []
        for pid, pet in list(self.preguntas.items()):
            if pet.evento.is_set():
                continue
            sol = dict(pet.solicitud)
            res.append({"id": pid, "tipo": getattr(pet, "tipo", "inicio_sesion"), "solicitud": sol})
        return res

    def _api_preguntas(self, metodo, partes, datos, q):
        if not partes:
            return {"preguntas": self._preguntas()}
        pet = self.preguntas.get(partes[0])
        if pet is None:
            raise ErrorApi("Esa pregunta ya no está pendiente", 404)
        if metodo != "POST":
            raise ErrorApi("Método no válido", 405)
        resp = datos.get("respuesta")
        if resp is not None and not isinstance(resp, dict):
            raise ErrorApi("Respuesta no válida")
        if resp is not None:
            resp = {"valores": {str(k): ("" if v is None else str(v)) for k, v in (resp.get("valores") or {}).items()},
                    "recordar": bool(resp.get("recordar", True))}
        pet.responder(resp)
        return {"ok": True}

    # --------------------------------------------------------------- grabar
    def _api_grabar(self, metodo, partes, datos, q):
        accion = partes[0] if partes else ""
        if accion == "terminar":
            if self.grabador is not None:
                self.grabador.detener()
            return {"ok": True}
        if accion == "ultimo":
            return {"flujo": self.ultimo_grabado}
        if metodo != "POST":
            raise ErrorApi("Método no válido", 405)
        url = (datos.get("url") or "").strip()
        if not url:
            raise ErrorApi("Escribe la dirección (URL) de la página")
        if "://" not in url:
            url = "https://" + url
        ajustes = self.almacen.ajustes()
        fl = Flujo(nombre=(datos.get("nombre") or "").strip() or "Nuevo reporte", url=url)
        for k in ("navegador", "timeout_paso", "timeout_descarga", "pausa_entre_pasos", "carpeta_descargas",
                  "recuperacion_automatica", "esperar_carga"):
            fl.opciones[k] = ajustes.get(k, fl.opciones.get(k))
        rid = datos.get("reporte_id")
        perfil = self._perfil(fl, int(rid) if rid else None) if rid else os.path.join(
            self.carpeta_perfiles, "_grabacion_" + time.strftime("%Y%m%d%H%M%S"))
        oculto = bool(self.oculto_forzado)

        def trabajo(t):
            from .grabador_web import GrabadorWeb

            def evento(tipo, **d):
                if tipo == "paso":
                    self.eventos.emitir("grab_paso", indice=d["indice"], paso=_paso_dict(d["paso"], d["indice"]))
                elif tipo == "paso_actualizado":
                    self.eventos.emitir("grab_paso", indice=d["indice"], paso=_paso_dict(d["paso"], d["indice"]),
                                        actualizado=True)
                elif tipo == "sugerencia":
                    d["paso"].valor = d["plantilla"]        # fecha relativa: se usa la fecha dinámica (se puede editar)
                    self.eventos.emitir("grab_estado", texto="Fecha «%s» guardada como fecha dinámica %s." % (
                        d["original"], d["plantilla"]))
                elif tipo == "accesos":
                    self.eventos.emitir("aviso", aviso="accesos_guardados", host=d.get("host", ""), texto=d.get("texto", ""))
                elif tipo == "estado":
                    self.eventos.emitir("grab_estado", texto=d.get("texto", ""))
            g = GrabadorWeb(fl, perfil, navegador=fl.opcion("navegador"), oculto=oculto, al_evento=evento,
                            accesos=self.almacen, hoy=self.hoy)
            self.grabador = g
            t.grabador = g
            try:
                g.grabar(url)
            finally:
                self.grabador = None
            self.ultimo_grabado = dict(fl.a_dict(), perfil=perfil)
            self.eventos.emitir("grab_fin", flujo=fl.a_dict(), perfil=perfil,
                                pasos=[_paso_dict(p, i) for i, p in enumerate(fl.pasos)])
            return True, "Grabación terminada: %d pasos" % len(fl.pasos)
        t = self.lanzar("grabar", "Grabar %s" % url, trabajo)
        return t.a_dict()

    def _api_guardar_grabacion(self, metodo, partes, datos, q):
        """Guarda la grabación como reporte nuevo (o reemplaza los pasos de uno) y le pasa el perfil (la sesión)."""
        fl = _flujo_desde(datos.get("flujo"))
        fl.nombre = datos.get("nombre") or fl.nombre
        rid = datos.get("reporte_id")
        rid = self._guardar_flujo(fl, int(rid) if rid else None)
        perfil = datos.get("perfil") or ""
        destino = os.path.join(self.carpeta_perfiles, nombre_perfil(rid))
        origen = os.path.abspath(perfil) if perfil else ""
        if origen and os.path.isdir(origen) and os.path.dirname(origen) == os.path.abspath(self.carpeta_perfiles) \
                and os.path.basename(origen).startswith("_grabacion_") and not os.path.exists(destino):
            try:
                os.rename(origen, destino)
            except OSError:
                pass
        return {"id": rid, "nombre": fl.nombre}

    # --------------------------------------------------------------- mapear
    def _api_mapa(self, metodo, partes, datos, q):
        from . import mapeador
        accion = partes[0] if partes else ""
        if accion == "iniciar":
            if self.sesion_mapa is not None and not self.sesion_mapa.terminada.is_set():
                raise ErrorApi("Ya hay una sesión de «Mapear página» abierta", 409)
            rid = datos.get("reporte_id")
            if rid:
                fl = self.almacen.cargar_flujo(int(rid))
                hasta = datos.get("hasta")
                hasta = mapeador.punto_de_mapeo(fl) if hasta in (None, "") else int(hasta)
            else:
                url = (datos.get("url") or "").strip()
                if not url:
                    raise ErrorApi("Elige un reporte o escribe una dirección")
                if "://" not in url:
                    url = "https://" + url
                fl = Flujo(nombre="Mapa de " + (mod_flujo.host_de(url) or "la página"), url=url,
                           pasos=[Paso("abrir_url", url=url)])
                hasta = None
            fl.opciones["pausa_entre_pasos"] = min(float(fl.opcion("pausa_entre_pasos") or 0.3), 0.3)
            listo = threading.Event()

            def trabajo(t):
                def crear(flujo, **extra):
                    return self.crear_ejecutor(t, flujo, int(rid) if rid else None, ver=True, **extra)
                sesion = mapeador.SesionMapeo(fl, crear, hasta=hasta,
                                              al_evento=lambda tipo, d=None: self.eventos.emitir("mapa_" + tipo, **(d or {})))
                self.sesion_mapa = sesion
                listo.set()
                sesion._trabajo()             # en este mismo hilo de trabajo
                return not sesion.error, sesion.error or "Sesión de mapeo terminada"
            t = self.lanzar("mapear", "Mapear «%s»" % fl.nombre, trabajo)
            listo.wait(5)
            return {"trabajo": t.a_dict(), "hasta": hasta, "pasos": [_paso_dict(p, i) for i, p in enumerate(fl.pasos)]}
        if accion == "guardar":
            mid = self.almacen.guardar_mapa(datos.get("reporte_id"), datos.get("url"), datos.get("alcance"),
                                            datos.get("filtros") or [])
            return {"id": mid}
        if accion == "anterior":
            rid = datos.get("reporte_id") or (q.get("reporte_id") or [None])[0]
            return {"mapa": self.almacen.ultimo_mapa(int(rid)) if rid else None}
        if accion == "crear_pasos":
            return self._crear_pasos_mapa(datos)
        if accion == "propuesta":                            # v3.2: «Guardar como Página»
            return self._propuesta_pagina(datos)
        s = self.sesion_mapa
        if s is None or s.terminada.is_set():
            raise ErrorApi("No hay ninguna sesión de «Mapear página» abierta", 409)
        if not s.listo.is_set() and accion != "terminar":
            raise ErrorApi("El navegador todavía se está preparando; espera un momento", 409)
        espera = {"mapear": 300, "parte": 320, "actualizar": 120, "terminar": 30, "dependencias": 600, "pestanas": 30,
                  "busqueda": 60}.get(accion)
        if espera is None:
            raise ErrorApi("Acción no válida", 404)
        pestana = datos.get("pestana")
        pestana = int(pestana) if pestana not in (None, "") else None
        if accion == "mapear":
            fut = s.pedir("mapear", alcance=datos.get("alcance") or "todo", selector=datos.get("selector"), pestana=pestana,
                          marco=[str(x) for x in (datos.get("marco") or []) if str(x).strip()])
        elif accion == "pestanas":                           # v3.3: las pestañas abiertas (para elegir cuál mapear)
            fut = s.pedir("pestanas")
        elif accion == "busqueda":                           # v3.3: leer las filas de la ventanita de búsqueda
            fut = s.pedir("busqueda", k=int(datos.get("k")))
        elif accion == "parte":
            fut = s.pedir("elegir_parte", pestana=pestana)
        elif accion == "actualizar":
            fut = s.pedir("actualizar", k=int(datos.get("k")), valor=datos.get("valor") or "")
        elif accion == "dependencias":
            fut = s.pedir("dependencias", ks=datos.get("ks"))
        else:
            fut = s.pedir("terminar")
        try:
            res = fut.result(timeout=espera)
        except Exception as e:         # noqa: BLE001
            raise ErrorApi(str(e).splitlines()[0] if str(e) else type(e).__name__)
        if accion == "mapear" and isinstance(res, dict):
            rid = datos.get("reporte_id")
            anterior = self.almacen.ultimo_mapa(int(rid)) if rid else None
            res["comparacion"] = mapeador.comparar(anterior["filtros"], res["filtros"]) if anterior else None
            res["anterior"] = anterior["cuando"] if anterior else None
        if accion == "terminar":
            return {"ok": True}
        return res if isinstance(res, dict) else {"parte": res}

    def _guardar_opciones_mapa(self, rid, fl, pasos, usados, desde):
        """v3.1: las opciones que leyó el mapa quedan como opciones de los filtros del reporte."""
        from . import filtros as mod_filtros
        from . import mapeador
        for i, opciones, padres in mapeador.opciones_para_cache(pasos, usados, desde):
            try:
                self.almacen.guardar_opciones_filtro(rid, i, opciones, padres, mod_filtros.firma_paso(fl.pasos[i]), "mapa")
            except Exception:          # noqa: BLE001
                pass

    def _crear_pasos_mapa(self, datos):
        from . import mapeador
        filtros = datos.get("filtros") or []
        if not datos.get("reporte_id"):
            filtros = mapeador.con_pestana(filtros, 0)     # v3.3: el reporte nuevo abre la dirección en la 1.ª pestaña
        pasos, usados = mapeador.generar_pasos(filtros, datos.get("elecciones") or [], con_filtros=True)
        if not pasos:
            raise ErrorApi("Elige al menos un filtro")
        destino = datos.get("destino") or "nuevo"
        rid = datos.get("reporte_id")
        # v3.7: la carpeta de «Archivo descargado» (solo si se envía: si no, la de siempre)
        carpeta_d = datos.get("carpeta_descargas")
        carpeta_d = None if carpeta_d is None else str(carpeta_d).strip()
        if destino in ("reemplazar", "anadir") and rid:
            fl = self.almacen.cargar_flujo(int(rid))
            hasta = datos.get("hasta")
            hasta = mapeador.punto_de_mapeo(fl) if hasta in (None, "") else int(hasta)
            self.almacen.guardar_version(int(rid), "antes de «Crear pasos» desde «Mapear página»")
            mapeador.aplicar_pasos(fl, pasos, hasta, "anadir" if destino == "anadir" else "reemplazar")
            if carpeta_d is not None:
                fl.opciones["carpeta_descargas"] = carpeta_d
            self._guardar_flujo(fl, int(rid))
            self._guardar_opciones_mapa(int(rid), fl, pasos, usados, max(0, min(int(hasta), len(fl.pasos))))
            return {"id": int(rid), "nombre": fl.nombre, "pasos": len(fl.pasos)}
        if rid:
            base = self.almacen.cargar_flujo(int(rid))
            hasta = datos.get("hasta")
            hasta = mapeador.punto_de_mapeo(base) if hasta in (None, "") else int(hasta)
            previos = base.pasos[:hasta]
            opciones = dict(base.opciones)
            url = base.url
        else:
            url = datos.get("url") or ""
            previos = [Paso("abrir_url", url=url)] if url else []
            opciones = dict(mod_flujo.OPCIONES_DEFECTO)
        if carpeta_d is not None:
            opciones["carpeta_descargas"] = carpeta_d
        fl = Flujo(nombre=self.almacen.nombre_libre(datos.get("nombre") or "Reporte mapeado"), url=url,
                   opciones=opciones, pasos=list(previos) + pasos)
        nuevo = self._guardar_flujo(fl, None)
        self._guardar_opciones_mapa(nuevo, fl, pasos, usados, len(previos))
        return {"id": nuevo, "nombre": fl.nombre, "pasos": len(fl.pasos)}

    # ------------------------------------------------------------- vigilancia
    def _vig_dict(self, v, data=None, max_opciones=15, tareas=None):
        """Una vigilancia para la interfaz: lo que vigila, con qué valores, su estado y sus opciones vistas."""
        from . import paginas as mod_paginas
        from . import vigilancia as mod_vigilancia
        alm = self.almacen
        vistas = alm.opciones_de_vigilancia(v["id"])
        d = dict(v, etiqueta=mod_vigilancia.etiqueta_vigilancia(v), opciones=self._opciones_recientes(vistas)[:max_opciones],
                 n_opciones=len(vistas), nuevas=[o["texto"] for o in vistas if o["nueva"] and not o["descargada"]])
        # v3.4: el horario en español, la próxima revisión y (si se conocen las tareas) si tiene tarea de Windows
        prog = v["programacion"]
        d["cuando"] = horario.describir(prog, "solo con «Revisar ahora»")
        prox = horario.proximas(prog, 1) if prog["reglas"] else []
        d["proxima"] = horario.texto_fecha(prox[0]) if prox else ""
        if tareas is not None:
            suyas = self._tareas_de_vigilancia(v["id"], tareas)
            d["tarea"] = {"existe": bool(suyas), "nombres": suyas,
                          "proxima": next((t.get("proxima", "") for t in tareas if t["nombre"] in suyas), "")}
        if v["tipo"] == "pagina":
            d["que"] = v["filtro"]
            if data is not None:
                try:
                    d["que"] = mod_paginas.filtro(data, v["filtro"])["nombre"]
                    nombres = {f["id"]: f["nombre"] for f in data["filtros"]}
                    d["valores_texto"] = ["%s = %s" % (nombres.get(str(k), k), mod_vigilancia.etiqueta_vigilancia(
                        {"valores": {k: e}})) for k, e in (v.get("valores") or {}).items()]
                except mod_paginas.ErrorPagina:
                    d["que"] = "(filtro borrado: %s)" % v["filtro"]
        else:
            d["que"] = "paso %d" % (int(v["paso"]) + 1)
            try:
                fl = alm.cargar_flujo(v["reporte_id"])
                p = fl.pasos[int(v["paso"])]
                d["que"] = "Paso %d: %s" % (int(v["paso"]) + 1, p.filtro or p.objetivo or p.descripcion())
            except (ErrorAlmacen, IndexError, ValueError):
                pass
        return d

    def _crear_para_vigilancia(self, t, v, ver=None, descarga=False):
        """Fábrica de ejecutores para revisar/descargar una vigilancia (una Página usa su perfil; revisa sin navegador
        y descarga como diga su interruptor «Sin abrir navegador»)."""
        from . import paginas as mod_paginas
        if v["tipo"] == "pagina":
            data = mod_paginas.normalizar(self.almacen.obtener_pagina(v["pagina_id"])["data"])
            if ver is None:
                ver = (not data["sin_navegador"]) if descarga else False
            return self._crear_ejecutor_pagina(t, v["pagina_id"], data, ver=bool(ver))
        return lambda fl, reporte_id=None, **ex: self.crear_ejecutor(t, fl, reporte_id, ver=ver, **ex)

    def _revisar_vigilancias(self, ids, ver=None):
        """Trabajo que revisa una o varias vigilancias, una tras otra («Revisar ahora» / «Revisar todas»)."""
        from . import vigilancia as mod_vigilancia
        alm = self.almacen

        def trabajo(t):
            todo_bien, resumenes = True, []
            for vid in ids:
                if t.detener.is_set():
                    break
                v = alm.vigilancia_id(vid)
                if v is None:
                    continue
                try:
                    r = mod_vigilancia.revisar_vigilancia(alm, vid, self._crear_para_vigilancia(t, v, ver), log=self._log)
                except mod_vigilancia.ErrorVigilancia as e:
                    todo_bien = False
                    resumenes.append(str(e))
                    continue
                self.eventos.emitir("vigilancia", vigilancia_id=vid, reporte_id=v.get("reporte_id"),
                                    pagina_id=v.get("pagina_id"), ok=r.ok, nuevas=r.nuevas, resumen=r.resumen())
                todo_bien = todo_bien and r.ok
                resumenes.append(r.resumen())
            return todo_bien, " · ".join(resumenes) if resumenes else "No había nada que revisar"
        return trabajo

    def _descargar_vigilancia(self, v, texto, ver=None):
        from . import vigilancia as mod_vigilancia
        alm = self.almacen
        tipo = "pagina" if v["tipo"] == "pagina" else "ejecutar"

        def trabajo(t):
            res = mod_vigilancia.descargar_vigilancia(alm, v["id"], texto,
                                                      self._crear_para_vigilancia(t, v, ver, descarga=True), log=self._log)
            if res is None:
                return False, "No se pudo descargar «%s»" % texto
            self.eventos.emitir("resultado", trabajo=t.id, reporte_id=v.get("reporte_id"), pagina_id=v.get("pagina_id"),
                                ok=res.ok, resumen=res.resumen(), registro=res.ruta_log, captura=res.ruta_captura,
                                archivos=res.archivos)
            if v["tipo"] == "pagina":
                self.eventos.emitir("pagina_fin", trabajo=t.id, pagina_id=v["pagina_id"], ok=res.ok, archivos=res.archivos)
            return res.ok, res.resumen()
        return self.lanzar(tipo, "Descargar «%s» de «%s»" % (texto, v["objetivo"]), trabajo,
                           reporte_id=v.get("reporte_id"), pagina_id=v.get("pagina_id")).a_dict()

    def _datos_vigilancia(self, datos, v=None):
        """Los campos de una vigilancia que vienen de la interfaz (comprobados)."""
        from . import paginas as mod_paginas
        from . import vigilancia as mod_vigilancia
        campos = {}
        for k in ("activa", "auto_descargar", "descargar_sin_fecha"):
            if k in datos:
                campos[k] = datos.get(k) is not False and bool(datos.get(k))
        if "activa" in datos:
            campos["activa"] = datos.get("activa") is not False
        for k in ("frecuencia", "hora", "nombre", "favorito"):
            if k in datos:
                campos[k] = (datos.get(k) or "").strip()
        if "cada_horas" in datos:
            campos["cada_horas"] = datos.get("cada_horas") or None
        if "programacion" in datos:          # v3.4: programación completa (manda sobre la frecuencia antigua)
            try:
                campos["programacion"] = horario.normalizar(datos.get("programacion"))
            except horario.ErrorHorario as e:
                raise ErrorApi(str(e))
            for k in ("frecuencia", "hora", "cada_horas"):
                campos.pop(k, None)
        if "valores" in datos:
            campos["valores"] = {str(k): e for k, e in (datos.get("valores") or {}).items() if e not in (None, "", {})}
        tipo = (v or {}).get("tipo") or ("pagina" if datos.get("pagina_id") else "reporte")
        if tipo == "pagina":
            pid = (v or {}).get("pagina_id") or int(datos.get("pagina_id"))
            fila = self.almacen.obtener_pagina(pid)
            if fila is None:
                raise ErrorApi("No existe la página %s" % pid, 404)
            data = mod_paginas.normalizar(fila["data"])
            if "filtro" in datos:
                f = mod_paginas.filtro(data, datos.get("filtro"))
                if f["tipo"] not in ("lista", "lista_nativa"):
                    raise ErrorApi("Solo se puede vigilar una lista")
                campos["filtro"] = f["id"]
            if campos.get("favorito"):
                campos["favorito"] = mod_paginas.buscar_favorito(data, campos["favorito"])["nombre"]
            for k in campos.get("valores") or {}:
                mod_paginas.filtro(data, k)
        else:
            rid = (v or {}).get("reporte_id") or int(datos.get("reporte_id"))
            if "paso" in datos:
                try:
                    mod_vigilancia.paso_vigilable(self.almacen.cargar_flujo(rid), datos.get("paso"))
                except mod_vigilancia.ErrorVigilancia as e:
                    raise ErrorApi(str(e))
                campos["paso"] = int(datos["paso"])
            campos.pop("favorito", None)
        return campos

    def _api_vigilancias(self, metodo, partes, datos, q):
        """v3.3: varias vigilancias.  GET (todas) · POST (crear: reporte_id + paso o pagina_id + filtro, con favorito,
        valores, nombre…) · POST revisar (todas las activas) · GET/PUT/DELETE <id> · GET <id>/opciones ·
        POST <id>/revisar · POST <id>/descargar {texto} · POST <id>/programar."""
        alm = self.almacen
        if not partes:
            if metodo == "GET":
                tareas = self._tareas()
                return {"vigilancias": [self._vig_dict(v, tareas=tareas) for v in alm.lista_vigilancias()]}
            if metodo == "POST":
                if not datos.get("pagina_id") and datos.get("reporte_id") and "paso" not in datos and (
                        datos.get("par") is not None or datos.get("seleccionar") is not None):
                    datos = dict(datos, paso=self._convertir_para_vigilar(int(datos["reporte_id"]), datos))
                campos = self._datos_vigilancia(datos)
                try:
                    if datos.get("pagina_id"):
                        if "filtro" not in campos:
                            raise ErrorApi("Elige la lista que se vigila")
                        vid = alm.crear_vigilancia(pagina_id=int(datos["pagina_id"]), **campos)
                    else:
                        if "paso" not in campos:
                            raise ErrorApi("Elige el paso que se vigila")
                        vid = alm.crear_vigilancia(reporte_id=int(datos["reporte_id"]), **campos)
                except ErrorAlmacen as e:
                    raise ErrorApi(str(e))
                return {"vigilancia": self._vig_dict(alm.vigilancia_id(vid))}
            raise ErrorApi("Método no válido", 405)
        if partes[0] == "revisar" and metodo == "POST":            # «Revisar todas»
            ids = [v["id"] for v in alm.lista_vigilancias(solo_activas=True)]
            if not ids:
                raise ErrorApi("No hay ninguna vigilancia activa")
            return self.lanzar("vigilar", "Revisar todas las vigilancias (%d)" % len(ids),
                               self._revisar_vigilancias(ids, datos.get("ver"))).a_dict()
        try:
            vid = int(partes[0])
        except ValueError:
            raise ErrorApi("Acción no válida", 404)
        v = alm.vigilancia_id(vid)
        if v is None:
            raise ErrorApi("No existe la vigilancia %d" % vid, 404)
        accion = partes[1] if len(partes) > 1 else ""
        if accion == "" and metodo == "GET":
            return {"vigilancia": self._vig_dict(v, tareas=self._tareas())}
        if accion == "" and metodo == "PUT":
            try:
                v = alm.actualizar_vigilancia(vid, **self._datos_vigilancia(datos, v))
            except ErrorAlmacen as e:
                raise ErrorApi(str(e))
            return {"vigilancia": self._vig_dict(v)}
        if accion == "" and metodo == "DELETE":
            alm.borrar_vigilancia_id(vid)
            return {"ok": True}
        if accion == "opciones":
            return {"opciones": self._opciones_recientes(alm.opciones_de_vigilancia(vid))}
        if metodo != "POST":
            raise ErrorApi("Método no válido", 405)
        if accion == "revisar":
            et = self._vig_dict(v)["etiqueta"]
            return self.lanzar("vigilar", "Revisar «%s»%s" % (v["objetivo"], (" (%s)" % et) if et else ""),
                               self._revisar_vigilancias([vid], datos.get("ver"))).a_dict()
        if accion == "descargar":
            texto = datos.get("texto") or ""
            if not texto:
                raise ErrorApi("Falta la opción a descargar")
            return self._descargar_vigilancia(v, texto, datos.get("ver"))
        if accion == "programar":
            return self._programar_vigilancia(v, datos)
        if accion == "quitar_tarea":                               # v3.4
            return self._quitar_tareas(self._tareas_de_vigilancia(vid, self._tareas()), datos)
        raise ErrorApi("Acción no válida", 404)

    def _convertir_para_vigilar(self, rid, datos):
        """v3.3.1: «Añadir vigilancia» con una lista grabada como clics («abrir la lista» + «clic en la opción», `par` =
        índice del primer paso) o como lista nativa («Seleccionar», `seleccionar` = índice): se convierte en un paso
        «Elegir opción» (antes se guarda una copia en Versiones) y se devuelve su índice.  Estrategia: la que se pida,
        o «la más reciente» si la opción grabada parece un corte o periodo (lleva fecha o año), si no la opción grabada."""
        try:
            fl = self.almacen.cargar_flujo(rid)
        except ErrorAlmacen as e:
            raise ErrorApi(str(e), 404)
        est_pedida = datos.get("estrategia") or ""
        if est_pedida and est_pedida not in ("fija", "mas_reciente", "primera", "ultima"):
            raise ErrorApi("Estrategia no válida: %s" % est_pedida)
        if datos.get("par") is not None:
            i = int(datos["par"])
            par = next((x for x in mod_flujo.pares_lista_opcion(fl.pasos) if x[0] == i), None)
            if par is None:
                raise ErrorApi("Esa lista ya no está en el reporte (¿se cambió?): vuelve a abrir «Añadir vigilancia».")
            i, j, texto = par
            est = est_pedida or ("mas_reciente" if mod_flujo.tiene_fecha_o_anio(texto) else "fija")
            self.almacen.guardar_version(rid, "Antes de convertir una lista en «Elegir opción» para vigilarla")
            mod_flujo.convertir_listas(fl, pares=[i], estrategias={i: est})
            quitados = j - i
        else:
            i = int(datos["seleccionar"])
            if not 0 <= i < len(fl.pasos) or fl.pasos[i].tipo != "seleccionar":
                raise ErrorApi("Ese paso ya no es una lista del reporte (¿se cambió?): vuelve a abrir «Añadir vigilancia».")
            p = fl.pasos[i]
            texto = p.etiqueta or p.valor or ""
            est = est_pedida or ("mas_reciente" if mod_flujo.tiene_fecha_o_anio(texto) else "fija")
            self.almacen.guardar_version(rid, "Antes de convertir una lista en «Elegir opción» para vigilarla")
            fl.pasos[i] = Paso("elegir_opcion", selectores=list(p.selectores), objetivo=p.objetivo or "la lista",
                               estrategia=est, valor=plantillas.escapar(texto) if est == "fija" else "",
                               pagina=p.pagina, marco=list(p.marco), espera_grabada=p.espera_grabada, filtro=p.filtro,
                               opcional=p.opcional, nota=((p.nota + " ") if p.nota else "") +
                               "Convertido de «%s» para vigilarlo." % p.descripcion()[:60])
            quitados = 0
        try:
            self.almacen.guardar(fl, rid)
        except ErrorAlmacen as e:
            raise ErrorApi(str(e))
        self.almacen.renumerar_pasos(rid, i, quitados)
        self._log("Reporte %d: la lista del paso %d se convirtió en «%s» para vigilarla (copia en Versiones)"
                  % (rid, i + 1, fl.pasos[i].descripcion()))
        return i

    def _programar_vigilancia(self, v, datos):
        """Tarea de Windows que revisa ESA vigilancia (`--vigilancia-id N`): muestra el comando o, con confirmar, la crea."""
        from . import vigilancia as mod_vigilancia
        et = mod_vigilancia.etiqueta_vigilancia(v)
        tarea = "Vigilar %s%s #%d" % (v["objetivo"], (" - " + et) if et else "", v["id"])
        if "programacion" in datos or "frecuencia" not in datos:
            # v3.4: con su programación (la que se pase o la guardada): XML con varios disparadores
            prog = datos["programacion"] if "programacion" in datos else v["programacion"]
            if "programacion" not in datos and horario.es_vacia(prog):
                raise ErrorApi("Esta vigilancia no tiene horario: elige cuándo revisarla en «Cambiar…»")
            return self._programar_con_horario(tarea, prog, datos, {"vigilancia_id": v["id"]},
                                               sustituir=self._tareas_de_vigilancia(v["id"], self._tareas()))
        frecuencia = (datos.get("frecuencia") or "DIARIA").upper()
        try:
            cmd = programador.construir_comando_crear(
                tarea, os.path.join(RAIZ, "bot.py"), hora=datos.get("hora") or "07:00", frecuencia=frecuencia,
                dias=datos.get("dias"), db=None if os.path.abspath(self.almacen.ruta) == os.path.abspath(
                    os.path.join(RAIZ, "datos", "bot.db")) else self.almacen.ruta, cada_horas=datos.get("cada_horas"),
                vigilancia_id=v["id"])
        except programador.ErrorProgramador as e:
            raise ErrorApi(str(e))
        if datos.get("confirmar") is True:
            try:
                salida = programador.crear(cmd, confirmado=True, ejecutor=self._ejecutor_tareas)
            except programador.ErrorProgramador as e:
                raise ErrorApi(str(e))
            return {"creada": True, "tarea": programador.nombre_tarea(tarea), "salida": salida}
        return {"creada": False, "tarea": programador.nombre_tarea(tarea), "comando": programador.como_texto(cmd),
                "cmd": cmd}

    def _api_vigilancia(self, metodo, partes, datos, q):
        """La página Vigilancia (GET: los reportes y las Páginas con sus vigilancias) y, por compatibilidad con la 3.2,
        la vigilancia «principal» de un reporte: vigilancia/<rid> (PUT/DELETE/opciones/revisar/descargar/programar)."""
        from . import paginas as mod_paginas
        from . import vigilancia
        alm = self.almacen
        if not partes:
            todas = alm.lista_vigilancias()
            tareas = self._tareas()
            res = []
            for r in alm.listar():
                try:
                    fl = alm.cargar_flujo(r["id"])
                except ErrorAlmacen:
                    continue
                vigs = [self._vig_dict(v, tareas=tareas) for v in todas if v["reporte_id"] == r["id"]]
                pasos = vigilancia.pasos_vigilables(fl)
                primera = vigs[0] if vigs else None
                # v3.3.1: también las listas grabadas como clics y las listas nativas («Seleccionar»): se pueden vigilar
                # directamente (al añadir la vigilancia se convierten en «Elegir opción»)
                pares = mod_flujo.pares_lista_opcion(fl.pasos)
                listas_clic = [{"par": i, "opcion": j, "texto": t, "periodo": mod_flujo.tiene_fecha_o_anio(t),
                                "descripcion": "Lista donde se eligió «%s» (pasos %d y %d)" % (t, i + 1, j + 1)}
                               for i, j, t in pares]
                selects = [{"paso": i, "texto": p.etiqueta or p.valor,
                            "periodo": mod_flujo.tiene_fecha_o_anio(p.etiqueta or p.valor),
                            "descripcion": "Paso %d: %s" % (i + 1, p.descripcion())}
                           for i, p in enumerate(fl.pasos) if p.tipo == "seleccionar" and not p.desactivado]
                res.append({"id": r["id"], "nombre": r["nombre"], "pasos": pasos, "vigilancias": vigs,
                            "vigilancia": primera, "opciones": primera["opciones"] if primera else [],
                            "n_opciones": primera["n_opciones"] if primera else 0,
                            "nuevas": [t for x in vigs for t in x["nuevas"]],
                            "repetir_dias": mod_flujo.describir_repetir_dias(fl.opciones.get("repetir_dias")),
                            "pares": len(pares), "listas_clic": listas_clic, "selects": selects,
                            "con_listas": bool(pasos or listas_clic or selects)})
            pags = []
            for p in alm.listar_paginas():
                try:
                    data = mod_paginas.normalizar(p["data"])
                except mod_paginas.ErrorPagina:
                    continue
                listas = [{"id": f["id"], "nombre": f["nombre"], "tipo": f["tipo"]} for f in data["filtros"]
                          if f["tipo"] in ("lista", "lista_nativa")]
                vigs = [self._vig_dict(v, data, max_opciones=5, tareas=tareas) for v in todas
                        if v["pagina_id"] == p["id"]]
                primera = vigs[0] if vigs else None
                pags.append({"id": p["id"], "nombre": p["nombre"], "listas": listas, "vigilancias": vigs,
                             "con_listas": bool(listas),
                             "favoritos": [f["nombre"] for f in data["favoritos"]],
                             "vigilancia": primera, "opciones": primera["opciones"] if primera else [],
                             "nuevas": [t for x in vigs for t in x["nuevas"]]})
            pags.sort(key=lambda x: (not x["vigilancias"], x["nombre"].lower()))
            return {"reportes": res, "paginas": pags, "total": len(todas),
                    "activas": len([v for v in todas if v["activa"]])}
        rid = int(partes[0])
        accion = partes[1] if len(partes) > 1 else ""
        vid = datos.get("vigilancia_id") or alm._principal(reporte_id=rid)
        if accion == "" and metodo == "PUT":
            fl = alm.cargar_flujo(rid)
            try:
                vigilancia.paso_vigilable(fl, datos.get("paso"))
            except vigilancia.ErrorVigilancia as e:
                raise ErrorApi(str(e))
            frecuencia = datos.get("frecuencia") or ""
            try:
                vid = alm.guardar_vigilancia(rid, int(datos["paso"]), activa=datos.get("activa", True) is not False,
                                             auto_descargar=bool(datos.get("auto_descargar")), frecuencia=frecuencia,
                                             cada_horas=datos.get("cada_horas") or None, hora=datos.get("hora") or "",
                                             descargar_sin_fecha=bool(datos.get("descargar_sin_fecha")),
                                             vigilancia_id=datos.get("vigilancia_id"))
            except ErrorAlmacen as e:
                raise ErrorApi(str(e))
            return {"vigilancia": alm.vigilancia_id(vid)}
        if accion == "" and metodo == "DELETE":
            alm.borrar_vigilancia(rid)
            return {"ok": True}
        if accion == "opciones":
            return {"opciones": self._opciones_recientes(alm.opciones_de_vigilancia(vid)) if vid else []}
        if vid is None:
            raise ErrorApi("El reporte no tiene ningún filtro vigilado")
        return self._api_vigilancias(metodo, [str(vid)] + list(partes[1:]), datos, q)

    @staticmethod
    def _opciones_recientes(vistas):
        """v3.1: opciones vistas de la más reciente a la más antigua (`clave_reciente`; si empatan, en el orden de la
        página), con `mas_reciente` en la primera y el periodo legible en `periodo`."""
        orden = sorted(vistas, key=lambda o: mod_flujo.clave_reciente(o["texto"]), reverse=True)
        res = []
        for k, o in enumerate(orden):
            o = dict(o)
            o["mas_reciente"] = k == 0 and mod_flujo.es_reconocible(o["texto"])
            o["periodo"] = mod_flujo.describir_opcion(o["texto"])
            res.append(o)
        return res

    def _programar(self, rid, metodo, datos, vigilar):
        """Muestra (GET/POST sin confirmar) o crea (POST con confirmar=true) la tarea del Programador de Windows."""
        fila = self.almacen.obtener(rid)
        if fila is None:
            raise ErrorApi("No existe el reporte %d" % rid, 404)
        nombre = fila["nombre"]
        tarea = ("Vigilar %s" if vigilar else "%s") % nombre
        clave = "reporte:%d" % rid
        if "programacion" in datos and not vigilar:          # v3.4: programación completa (XML)
            g = self.almacen.programacion(clave)
            return self._programar_con_horario(tarea, datos["programacion"], datos, {"ids": [rid]}, clave=clave,
                                               sustituir=[_corto((g or {}).get("tarea", ""))])
        if metodo == "GET" and not vigilar:                  # v3.4: lo guardado, para rellenar la ventana
            return self._vista_programacion(clave, tarea)
        frecuencia = (datos.get("frecuencia") or "DIARIA").upper()
        try:
            cmd = programador.construir_comando_crear(
                tarea, os.path.join(RAIZ, "bot.py"), hora=datos.get("hora") or "07:00", frecuencia=frecuencia,
                dias=datos.get("dias"), ids=[rid], db=None if os.path.abspath(self.almacen.ruta) ==
                os.path.abspath(os.path.join(RAIZ, "datos", "bot.db")) else self.almacen.ruta, vigilar=vigilar,
                cada_horas=datos.get("cada_horas"))
        except programador.ErrorProgramador as e:
            raise ErrorApi(str(e))
        if metodo == "POST" and datos.get("confirmar") is True:
            try:
                salida = programador.crear(cmd, confirmado=True, ejecutor=self._ejecutor_tareas)
            except programador.ErrorProgramador as e:
                raise ErrorApi(str(e))
            return {"creada": True, "tarea": programador.nombre_tarea(tarea), "salida": salida}
        return {"creada": False, "tarea": programador.nombre_tarea(tarea), "comando": programador.como_texto(cmd)}

    # ============================================================ v3.2: Páginas
    def _propuesta_pagina(self, datos):
        return self._propuesta(datos)[0]

    def _propuesta(self, datos):
        """Lo que se propone al pulsar «Guardar como Página» tras mapear: nombre, pasos de llegada (los que se
        ejecutaron antes de mapear), filtros con nombre, botones y la acción adivinada.  Devuelve (propuesta, filtros del
        mapa con la pestaña en la que estarán al ejecutar la Página)."""
        from . import mapeador
        from . import paginas as mod_paginas
        filtros = datos.get("filtros") or []
        rid = datos.get("reporte_id")
        url = (datos.get("url") or "").strip()
        nota = ""
        pasos_reporte, despues = [], []
        carpeta_d = self.almacen.ajustes().get("carpeta_descargas") or ""     # v3.7: la que tendrá la Página
        if rid:
            fl = self.almacen.cargar_flujo(int(rid))
            carpeta_d = fl.opcion("carpeta_descargas") or ""
            hasta = datos.get("hasta")
            hasta = mapeador.punto_de_mapeo(fl) if hasta in (None, "") else int(hasta)
            llegada = [p for p in fl.pasos[:hasta]]
            pasos_reporte, _u, despues = mod_paginas.pasos_tras_filtros(fl, hasta, filtros)
        else:
            llegada = [Paso("abrir_url", url=url)] if url else []
        s = self.sesion_mapa
        inicio = getattr(s, "url_inicio", "") if s is not None else ""
        if url and inicio and url != inicio and mod_flujo.host_de(url) == mod_flujo.host_de(inicio):
            nota = ("Navegaste a mano hasta otra dirección (%s): el bot la abrirá directamente después de los pasos de "
                    "llegada. Revisa que no falte ningún clic (menús) antes de los filtros." % url)
            if rid:
                llegada.append(Paso("abrir_url", url=url, nota="Dirección a la que se llegó navegando a mano."))
            else:
                llegada = [Paso("abrir_url", url=url)]
        if not rid or nota:
            # v3.3: la Página abre directamente esa dirección en la primera pestaña, aunque al mapear estuviera en otra
            # (el reporte se abrió en una pestaña nueva)
            filtros = mapeador.con_pestana(filtros, 0)
        nombres = mod_paginas.nombres_desde_mapa(filtros)
        lista = []
        for f in sorted(filtros, key=lambda x: x.get("orden", 0)):
            if f.get("tipo") == "accion":
                continue
            n, origen = nombres.get(int(f["k"]), ("", ""))
            lista.append({"k": f["k"], "tipo": f["tipo"], "etiqueta": f.get("etiqueta") or "", "nombre": n,
                          "origen": origen, "incluir": True, "valor": f.get("valor") or "",
                          "n_opciones": len(f.get("opciones") or [])})
        return {"nombre": self.almacen.nombre_pagina_libre(mod_paginas.nombre_sugerido(url)),
                "llegada": [_paso_dict(p, i) for i, p in enumerate(llegada)], "filtros": lista,
                "botones": mod_paginas.botones_de_mapa(filtros),
                "accion": mod_paginas.adivinar_accion(filtros, despues), "tipos_accion": mod_paginas.TIPOS_ACCION,
                "nota": nota, "pasos_reporte": len(pasos_reporte),
                "nombre_archivo": mod_paginas.PLANTILLA_DEFECTO, "carpeta_descargas": carpeta_d}, filtros

    def _accion_de_formulario(self, a, filtros_mapa, propuesta):
        """La acción que eligió el usuario en «Guardar como Página»: {tipo, generar_k | generar_texto, descargar_k |
        descargar_texto, menu_texto, exportar_texto, formato, pestana}."""
        from . import paginas as mod_paginas
        por_k = {int(f["k"]): f for f in filtros_mapa}
        a = a or {}
        tipo = a.get("tipo") or propuesta.get("tipo") or "descargar"
        if tipo == "pasos":
            if propuesta.get("tipo") != "pasos":
                raise ErrorApi("Este mapa no viene de un reporte con pasos de descarga: elige otra acción")
            return dict(propuesta)

        # v3.3: los botones van con su pestaña y su marco (iframe); los que se dan por su texto, donde está el formulario
        formulario = next((f for f in sorted(filtros_mapa, key=lambda x: x.get("orden", 0)) if f.get("tipo") != "accion"),
                          None) or (filtros_mapa[0] if filtros_mapa else {})
        lugar = {"marco": list(formulario.get("marco") or []), "pagina": int(formulario.get("pagina") or 0)}

        def boton(clave):
            k = a.get(clave + "_k")
            if k not in (None, ""):
                f = por_k.get(int(k))
                if f is None:
                    raise ErrorApi("Ese botón no está en el mapa")
                return {"selectores": list(f.get("selectores") or []), "objetivo": f.get("etiqueta") or "",
                        "marco": list(f.get("marco") or []), "pagina": int(f.get("pagina") or 0)}
            texto = (a.get(clave + "_texto") or "").strip()
            if texto:
                return dict(lugar, selectores=mod_paginas.selectores_por_texto(texto), objetivo=texto)
            return None
        res = {"tipo": tipo, "generar": boton("generar")}
        if res["generar"]:
            lugar = {"marco": res["generar"]["marco"], "pagina": res["generar"]["pagina"]}
        if tipo == "descargar" and res["generar"] is None:
            res["generar"] = boton("descargar")
        if tipo == "boton_descarga":
            res["descargar"] = boton("descargar") or {"selectores": list(mod_paginas.SELECTORES_DESCARGAR),
                                                      "objetivo": "Descargar"}
        if tipo == "menu_exportar":
            res["menu"] = [dict(lugar, selectores=mod_paginas.selectores_por_texto(t.strip()), objetivo=t.strip())
                           for t in (a.get("menu_texto") or "").split(">") if t.strip()]
            res["exportar"] = boton("exportar") or boton("descargar")
        if tipo == "guardar_pagina":
            res["formato"] = (a.get("formato") or "pdf").lower()
            res["pestana"] = int(a.get("pestana") if a.get("pestana") not in (None, "") else lugar["pagina"] + 1)
        return res

    def _crear_pagina_desde_mapa(self, datos):
        from . import mapeador
        from . import paginas as mod_paginas
        if not (datos.get("filtros") or []):
            raise ErrorApi("Primero mapea la página")
        rid = datos.get("reporte_id")
        url = (datos.get("url") or "").strip()
        propuesta, filtros = self._propuesta(datos)
        pasos_reporte, opciones = [], {}
        ajustes = self.almacen.ajustes()
        for k in ("navegador", "timeout_paso", "timeout_descarga", "pausa_entre_pasos", "carpeta_descargas",
                  "recuperacion_automatica", "esperar_carga"):
            opciones[k] = ajustes.get(k)
        perfil = "_sin_guardar_" + mod_flujo.slug("Mapa de " + (mod_flujo.host_de(url) or "la página"))
        if rid:
            fl = self.almacen.cargar_flujo(int(rid))
            hasta = datos.get("hasta")
            hasta = mapeador.punto_de_mapeo(fl) if hasta in (None, "") else int(hasta)
            pasos_reporte, _u, _d = mod_paginas.pasos_tras_filtros(fl, hasta, filtros)
            opciones = dict(fl.opciones)
            perfil = nombre_perfil(int(rid))
        llegada = datos.get("llegada")
        if llegada is None:
            llegada = propuesta["llegada"]
        try:
            llegada = [Paso.desde_dict({k: v for k, v in p.items() if k not in ("descripcion", "accion", "detalle",
                                                                                   "problemas", "indice", "incluir")})
                       for p in llegada if p.get("incluir", True) is not False]
        except (ErrorFlujo, TypeError, AttributeError) as e:
            raise ErrorApi("Los pasos de llegada no son válidos: %s" % e)
        accion = self._accion_de_formulario(datos.get("accion"), filtros, propuesta["accion"])
        deps = {int(k): [int(x) for x in v] for k, v in (datos.get("dependencias") or {}).items()}
        try:
            data, k_a_id = mod_paginas.desde_mapa(filtros, url=url, incluir=datos.get("incluir"),
                                                  nombres=datos.get("nombres"), llegada=llegada, accion=accion,
                                                  dependencias=deps, pasos_reporte=pasos_reporte, opciones=opciones,
                                                  perfil=perfil)
            lecturas = mod_paginas.lecturas_de_mapa(filtros, k_a_id)
            for x in datos.get("lecturas") or []:
                fid = k_a_id.get(int(x["k"]))
                if fid:
                    lecturas.append((fid, list(x.get("opciones") or []),
                                     {k_a_id[int(k)]: v for k, v in (x.get("padres") or {}).items() if int(k) in k_a_id}))
            if rid:
                data["origen"] = {"reporte_id": int(rid)}
            # v3.7: «Archivo descargado» del diálogo (si no se envía o va vacío, lo de siempre)
            if str(datos.get("nombre_archivo") or "").strip():
                data["nombre_archivo"] = str(datos["nombre_archivo"]).strip()
                err = mod_paginas.validar_plantilla(data, data["nombre_archivo"])
                if err:
                    raise mod_paginas.ErrorPagina(err)
            if datos.get("carpeta_descargas") is not None:
                data["opciones"] = dict(data.get("opciones") or {},
                                        carpeta_descargas=str(datos["carpeta_descargas"]).strip())
            pid, nombre = mod_paginas.guardar_nueva(self.almacen, datos.get("nombre") or propuesta["nombre"], data,
                                                    lecturas, "mapa")
        except mod_paginas.ErrorPagina as e:
            raise ErrorApi(str(e))
        return {"id": pid, "nombre": nombre}

    def _pagina_fila(self, pid):
        from . import paginas as mod_paginas
        fila = self.almacen.obtener_pagina(pid)
        if fila is None:
            raise ErrorApi("No existe la página %d" % pid, 404)
        try:
            return fila, mod_paginas.normalizar(fila["data"])
        except mod_paginas.ErrorPagina as e:
            raise ErrorApi("La página «%s» está dañada: %s" % (fila["nombre"], e))

    def _vista_pagina(self, pid, seleccion=None):
        from . import paginas as mod_paginas
        alm = self.almacen
        fila, data = self._pagina_fila(pid)
        vig = alm.vigilancia_pagina(pid)
        vigs = alm.lista_vigilancias(pagina_id=pid)
        novedades = {}
        for v in vigs:                 # v3.3: la marca «nueva» junta las de todas las vigilancias de la misma lista
            novedades[v["filtro"]] = alm.novedades_pagina(pid, v["filtro"], mod_paginas.DIAS_NUEVA)
        try:
            form = mod_paginas.formulario(data, alm.opciones_pagina(pid), seleccion, novedades,
                                          [v["filtro"] for v in vigs])
        except mod_paginas.ErrorPagina as e:
            raise ErrorApi(str(e))
        llegada = [_paso_dict(Paso.desde_dict(p), i) for i, p in enumerate(data["llegada"])]
        try:
            accion_pasos = [p.descripcion() for p in mod_paginas.pasos_accion(data)]
        except mod_paginas.ErrorPagina as e:
            accion_pasos = ["⚠ " + str(e)]
        return {"id": pid, "nombre": fila["nombre"], "host": fila["host"], "url": fila["url"], "data": data,
                "filtros": form, "actualizado": mod_paginas.actualizado(form), "favoritos": [
                    dict(f, descripcion=mod_paginas.describir_favorito(data, f)) for f in data["favoritos"]],
                "sin_navegador": data["sin_navegador"], "vigilancia": vig, "llegada": llegada, "accion_pasos": accion_pasos,
                "vigilancias": [self._vig_dict(v, data, max_opciones=5) for v in vigs],
                "problemas": mod_paginas.validar(data), "historial": alm.historial(pagina_id=pid, limite=10),
                "tipos_accion": mod_paginas.TIPOS_ACCION, "max_sin_confirmar": mod_paginas.MAX_SIN_CONFIRMAR,
                "max_ejecuciones": mod_paginas.MAX_EJECUCIONES, "carpeta": self._carpeta_descargas(data),
                "plantilla_vista": mod_paginas.plantilla_archivo(data)}

    def _carpeta_descargas(self, data=None):
        carpeta_d = self.carpeta_descargas or ((data or {}).get("opciones") or {}).get("carpeta_descargas") or \
            self.almacen.ajustes().get("carpeta_descargas") or os.path.join(RAIZ, "descargas")
        return os.path.abspath(carpeta_d)

    def _crear_ejecutor_pagina(self, t, pid, data, ver, **fijos):
        from . import paginas as mod_paginas
        perfil = mod_paginas.carpeta_perfil(self.carpeta_perfiles, pid, data)

        def crear(flujo, reporte_id=None, **extra):
            extra.update(fijos)
            return self.crear_ejecutor(t, flujo, None, ver=ver, carpeta_perfil=perfil, **extra)
        return crear

    @staticmethod
    def _al_final_nombres(ej, pg):
        """Al terminar de leer las listas: mapa rápido de la página (sin abrir las listas) para corregir los nombres."""
        from . import mapeador
        try:
            return mapeador.escanear(ej, pg, leer_listas=False)
        except Exception:              # noqa: BLE001 (solo sirve para poner nombres mejores)
            return None

    def _lanzar_pagina(self, pid, fila, data, sel, combos, sin_navegador):
        from . import paginas as mod_paginas
        n = len(combos)
        primero, _i = mod_paginas.construir_flujo(data, fila["nombre"], combos[0][0], combos[0][1], hoy=self.hoy)

        def trabajo(t):
            t.total = n if n > 1 else len(primero.pasos)
            crear = self._crear_ejecutor_pagina(t, pid, data, ver=not sin_navegador)

            def aviso(k, total, etiqueta):
                if total > 1:
                    self.eventos.emitir("lote", n=k, total=total, nombre=etiqueta, fase="inicio", estado="en_curso",
                                        pagina_id=pid)

            def al_resultado(res, etiqueta):
                self.eventos.emitir("resultado", trabajo=t.id, pagina_id=pid, ok=res.ok, resumen=res.resumen(),
                                    registro=res.ruta_log, captura=res.ruta_captura, archivos=res.archivos,
                                    etiqueta=etiqueta)
            r = mod_paginas.ejecutar(self.almacen, pid, sel, crear, combos=combos, log=self._log, detener=t.detener,
                                     aviso=aviso, al_resultado=al_resultado, hoy=self.hoy)
            self.eventos.emitir("pagina_fin", trabajo=t.id, pagina_id=pid, ok=r.ok, archivos=r.archivos)
            return r.ok, r.resumen()
        modo = " (sin abrir navegador)" if sin_navegador else ""
        return self.lanzar("pagina" if n == 1 else "pagina_varias", "«%s»%s%s" % (
            fila["nombre"], (" — %d ejecuciones" % n) if n > 1 else "", modo), trabajo, pagina_id=pid)

    def _lanzar_leer_pagina(self, pid, fila, data, sel, hasta, fuente, descripcion):
        from . import paginas as mod_paginas

        def trabajo(t):
            t.total = 0
            crear = self._crear_ejecutor_pagina(t, pid, data, ver=False)
            try:
                res, n, mensajes = mod_paginas.leer_opciones(self.almacen, pid, sel, crear, hasta=hasta, fuente=fuente,
                                                             al_final=self._al_final_nombres)
            except mod_paginas.ErrorPagina as e:
                self.eventos.emitir("pagina_opciones", pagina_id=pid, ok=False, listas=0, filtro=hasta or "",
                                    texto=str(e))
                return False, str(e)
            texto = ("Opciones leídas: %d lista(s)" % n) + ((". " + ". ".join(mensajes)) if mensajes else "")
            if not res.ok:
                texto = "%s%s" % (res.resumen(), (" (se guardaron %d lista(s) leídas antes del error)" % n) if n else "")
            self.eventos.emitir("pagina_opciones", pagina_id=pid, ok=res.ok, listas=n, filtro=hasta or "", texto=texto)
            return res.ok, texto
        return self.lanzar("pagina_opciones", descripcion, trabajo)

    def _api_paginas(self, metodo, partes, datos, q):
        from . import paginas as mod_paginas
        alm = self.almacen
        if not partes:
            if metodo == "GET":
                vigs = {v["pagina_id"]: v for v in alm.vigilancias_paginas()}
                res = []
                for p in alm.listar_paginas():
                    try:
                        data = mod_paginas.normalizar(p["data"])
                    except mod_paginas.ErrorPagina:
                        data = {"filtros": [], "favoritos": []}
                    filas = alm.opciones_pagina(p["id"])
                    res.append({"id": p["id"], "nombre": p["nombre"], "host": p["host"], "url": p["url"],
                                "filtros": [f["nombre"] for f in data["filtros"]],
                                "favoritos": [f["nombre"] for f in data["favoritos"]], "ultima": p["ultima"],
                                "resultado": p["resultado"], "mensaje": p["mensaje"], "vigilada": p["id"] in vigs,
                                "actualizado": max([f["actualizado"] for f in filas] or [""]),
                                "nuevas": sum(len(alm.pendientes_vigilancia(v["id"])) for v in
                                              alm.lista_vigilancias(pagina_id=p["id"]))})
                return {"paginas": res}
            if metodo == "POST":
                return self._crear_pagina_desde_mapa(datos)
            raise ErrorApi("Método no válido", 405)
        try:
            pid = int(partes[0])
        except ValueError:
            raise ErrorApi("Número de página no válido")
        accion = partes[1] if len(partes) > 1 else ""
        sub = partes[2] if len(partes) > 2 else ""
        seleccion = datos.get("seleccion") if isinstance(datos.get("seleccion"), dict) else None
        try:
            if accion == "" and metodo == "GET":
                return self._vista_pagina(pid)
            if accion == "formulario":
                return self._vista_pagina(pid, seleccion)
            fila, data = self._pagina_fila(pid)
            if accion == "" and metodo == "PUT":
                nuevo = datos.get("data")
                if not isinstance(nuevo, dict):
                    raise ErrorApi("Faltan los datos de la página")
                nuevo = dict(nuevo)
                for k in ("perfil", "origen"):          # no se cambian desde la página
                    if k in data:
                        nuevo[k] = data[k]
                for f in nuevo.get("filtros") or []:
                    if f.get("nombre"):
                        f["nombre"] = mod_paginas.validar_nombre_filtro(f["nombre"])
                nuevo = mod_paginas.normalizar(nuevo)
                problemas = mod_paginas.validar(nuevo)
                if problemas:
                    raise ErrorApi("No se puede guardar: " + "; ".join(problemas[:3]))
                nombre = datos.get("nombre") or fila["nombre"]
                try:
                    alm.guardar_pagina(nombre, nuevo, pid, host=mod_paginas.host_de(nuevo.get("url")) or fila["host"],
                                       url=nuevo.get("url") or fila["url"])
                except ErrorAlmacen as e:
                    raise ErrorApi(str(e))
                return self._vista_pagina(pid)
            if accion == "" and metodo == "DELETE":
                if datos.get("confirmar") is not True:
                    raise ErrorApi("Para borrar la página hay que confirmarlo")
                alm.borrar_pagina(pid)
                return {"ok": True}
            if accion == "historial":
                return {"historial": alm.historial(pagina_id=pid, limite=50)}
            if metodo != "POST" and accion not in ("vigilancia",):
                raise ErrorApi("Método no válido", 405)
            if accion == "ejecutar":
                sel = mod_paginas.seleccion_base(data, favorito=datos.get("favorito"), seleccion=seleccion)
                combos = mod_paginas.preparar(data, sel)
                n = len(combos)
                if n > mod_paginas.MAX_SIN_CONFIRMAR and datos.get("confirmar") is not True:
                    return {"confirmar": True, "n": n, "mensaje": "Con estas opciones la página se ejecutará %d veces "
                            "(una por cada combinación). ¿Seguro?" % n}
                sin = datos.get("sin_navegador")
                if sin is None:
                    fav = mod_paginas.buscar_favorito(data, datos["favorito"]) if datos.get("favorito") else None
                    sin = fav["sin_navegador"] if fav else data["sin_navegador"]
                return self._lanzar_pagina(pid, fila, data, sel, combos, bool(sin)).a_dict()
            if accion in ("traer", "actualizar"):
                hasta = datos.get("filtro") if accion == "traer" else None
                if hasta:
                    f = mod_paginas.filtro(data, hasta)
                    desc = "Trayendo las opciones de «%s» de «%s»" % (f["nombre"], fila["nombre"])
                else:
                    desc = "Actualizar las opciones de «%s»" % fila["nombre"]
                return self._lanzar_leer_pagina(pid, fila, data, seleccion, hasta, "traer" if hasta else "actualizar",
                                                desc).a_dict()
            if accion == "favoritos":
                if sub == "borrar":
                    mod_paginas.borrar_favorito(data, datos.get("nombre"))
                    nombre_fav = None
                else:
                    nombre_fav = mod_paginas.guardar_favorito(data, datos.get("nombre"), seleccion or {},
                                                              datos.get("sin_navegador", True) is not False)
                mod_paginas._guardar_data(alm, pid, fila, data)
                return {"ok": True, "nombre": nombre_fav, "favoritos": [
                    dict(f, descripcion=mod_paginas.describir_favorito(data, f)) for f in data["favoritos"]]}
            if accion == "predeterminado":
                sel = mod_paginas.seleccion_base(data, seleccion=seleccion)
                for f in data["filtros"]:
                    if seleccion and f["id"] in seleccion:
                        e = sel[f["id"]]
                        if "valores" in e:
                            if len(e["valores"]) > 1:
                                raise ErrorApi("Para guardarlo como valor por defecto elige una sola opción en «%s»"
                                               % f["nombre"])
                            e = mod_paginas.normalizar_eleccion(f, e["valores"][0])
                        f["defecto"] = e
                mod_paginas._guardar_data(alm, pid, fila, data)
                return self._vista_pagina(pid)
            if accion == "programar":
                return self._programar_pagina(pid, fila, data, datos, vigilar=False)
            if accion == "vigilancia":
                return self._api_vigilancia_pagina(pid, fila, data, metodo, sub, datos)
        except mod_paginas.ErrorPagina as e:
            raise ErrorApi(str(e))
        raise ErrorApi("Acción no válida: %s" % accion, 404)

    def _api_vigilancia_pagina(self, pid, fila, data, metodo, sub, datos):
        """(Compatibilidad 3.2) la vigilancia «principal» de la Página (o `vigilancia_id`).  Las demás: /api/vigilancias."""
        from . import paginas as mod_paginas
        alm = self.almacen
        vid = datos.get("vigilancia_id") or alm._principal(pagina_id=pid)
        if sub == "" and metodo == "PUT":
            f = mod_paginas.filtro(data, datos.get("filtro"))
            if f["tipo"] not in ("lista", "lista_nativa"):
                raise ErrorApi("Solo se puede vigilar una lista")
            fav = datos.get("favorito") or ""
            if fav:
                mod_paginas.buscar_favorito(data, fav)
            vid = alm.guardar_vigilancia_pagina(pid, f["id"], activa=datos.get("activa", True) is not False,
                                                auto_descargar=bool(datos.get("auto_descargar")), favorito=fav,
                                                frecuencia=datos.get("frecuencia") or "",
                                                cada_horas=datos.get("cada_horas") or None, hora=datos.get("hora") or "",
                                                descargar_sin_fecha=bool(datos.get("descargar_sin_fecha")),
                                                vigilancia_id=datos.get("vigilancia_id"))
            return {"vigilancia": alm.vigilancia_id(vid)}
        if sub == "" and metodo == "DELETE":
            alm.borrar_vigilancia_pagina(pid)
            return {"ok": True}
        if sub == "" and metodo == "GET":
            v = alm.vigilancia_id(vid) if vid else None
            return {"vigilancia": v, "opciones": self._opciones_recientes(alm.opciones_de_vigilancia(vid)) if vid else []}
        if vid is None:
            raise ErrorApi("La página no tiene ningún filtro vigilado")
        return self._api_vigilancias(metodo, [str(vid), sub], datos, {})

    def _programar_pagina(self, pid, fila, data, datos, vigilar):
        from . import paginas as mod_paginas
        fav = datos.get("favorito") or None
        if fav and not vigilar:
            fav = mod_paginas.buscar_favorito(data, fav)["nombre"]
        tarea = ("Vigilar %s" if vigilar else "%s") % fila["nombre"] + ((" - " + fav) if fav and not vigilar else "")
        clave = "pagina:%d" % pid + ((":" + fav) if fav and not vigilar else "")
        if not vigilar:
            g = self.almacen.programacion(clave)
            if "programacion" in datos:                      # v3.4: programación completa (XML)
                return self._programar_con_horario(tarea, datos["programacion"], datos,
                                                   {"pagina_id": pid, "favorito": fav}, clave=clave,
                                                   sustituir=[_corto((g or {}).get("tarea", ""))])
            if datos.get("consultar") is True:               # v3.4: lo guardado, para rellenar la ventana
                return self._vista_programacion(clave, tarea)
            if datos.get("quitar") is True:                  # v3.4: quitar su tarea de Windows (con confirmar)
                return self._quitar_tareas([_corto(programador.nombre_tarea(tarea)), _corto((g or {}).get("tarea", ""))],
                                           datos, clave=clave)
        frecuencia = (datos.get("frecuencia") or "DIARIA").upper()
        try:
            cmd = programador.construir_comando_crear(
                tarea, os.path.join(RAIZ, "bot.py"), hora=datos.get("hora") or "07:00", frecuencia=frecuencia,
                dias=datos.get("dias"), db=None if os.path.abspath(self.almacen.ruta) == os.path.abspath(
                    os.path.join(RAIZ, "datos", "bot.db")) else self.almacen.ruta, vigilar=vigilar,
                cada_horas=datos.get("cada_horas"), pagina_id=pid, favorito=None if vigilar else fav)
        except programador.ErrorProgramador as e:
            raise ErrorApi(str(e))
        if datos.get("confirmar") is True:
            try:
                salida = programador.crear(cmd, confirmado=True, ejecutor=self._ejecutor_tareas)
            except programador.ErrorProgramador as e:
                raise ErrorApi(str(e))
            return {"creada": True, "tarea": programador.nombre_tarea(tarea), "salida": salida}
        return {"creada": False, "tarea": programador.nombre_tarea(tarea), "comando": programador.como_texto(cmd),
                "cmd": cmd}

    # ------------------------------------------------------- v3.4: correo
    @staticmethod
    def _tareas_de_correo(bid, tareas):
        """Nombres de las tareas de Windows de la búsqueda de correo `bid` («Correo … #N»: el nombre cambia si se
        renombra)."""
        fin = re.compile(r" #%d$" % int(bid))
        return [t["nombre"] for t in tareas if t["nombre"].startswith("Correo ") and fin.search(t["nombre"])]

    def _cuenta_dict(self, c):
        from . import correo as mod_correo
        d = dict(c, proveedor_texto=mod_correo.PROVEEDORES.get(c["proveedor"], c["proveedor"]),
                 url_efectiva=mod_correo.url_de_cuenta(c) if c["proveedor"] != "imap" else "")
        if c["proveedor"] == "imap":
            try:
                d["tiene_clave"] = secretos.existe(mod_correo.secreto_de_cuenta(c["id"]))
            except secretos.ErrorSecreto:
                d["tiene_clave"] = False
        else:
            d["perfil_guardado"] = os.path.isdir(os.path.join(self.carpeta_perfiles, "correo_%d" % c["id"]))
        d["busquedas"] = [b["nombre"] for b in self.almacen.listar_busquedas_correo() if b["cuenta_id"] == c["id"]]
        return d

    def _busqueda_dict(self, b, tareas=None, procesados=5):
        from . import correo as mod_correo
        d = dict(b)
        d["que_texto"] = mod_correo.describir_criterios(b["criterios"], self.hoy)
        acciones = []
        for a in b["acciones"]:
            try:
                acciones.append(mod_correo.describir_accion(a))
            except (KeyError, TypeError):
                acciones.append("(acción no válida)")
        d["acciones_texto"] = acciones
        d["agrega"] = mod_correo.acciones_que_agregan(b["acciones"])          # v3.5: avisar antes de reprocesar
        prog = b["programacion"]
        d["cuando"] = horario.describir(prog, "solo con «Revisar ahora»")
        prox = horario.proximas(prog, 1) if prog["reglas"] else []
        d["proxima"] = horario.texto_fecha(prox[0]) if prox else ""
        if tareas is not None:
            suyas = self._tareas_de_correo(b["id"], tareas)
            d["tarea"] = {"existe": bool(suyas), "nombres": suyas,
                          "proxima": next((t.get("proxima", "") for t in tareas if t["nombre"] in suyas), "")}
        if procesados:
            d["procesados"] = self.almacen.procesados_correo(b["id"], limite=procesados)
        return d

    def _fabrica_correo(self, t, ver=False, esperar_login=0):
        from . import correo as mod_correo
        navegador = self.almacen.ajustes().get("navegador") or "chrome"
        oculto = self._oculto(ver)

        def abrir(cuenta):
            return mod_correo.crear_adaptador(cuenta, self.carpeta_perfiles, oculto=oculto, navegador=navegador,
                                              log=self._log, detener=t.detener, esperar_login=esperar_login)
        return abrir

    def _lanzar_procesar_correos(self, b, claves, rango, buscar_hasta, ver):
        """v3.5 «Procesar este» / «Procesar seleccionados»: procesa ESOS correos aunque ya se hubieran procesado."""
        from . import correo as mod_correo
        alm = self.almacen

        def trabajo(t):
            r = mod_correo.revisar_busqueda(alm, b["id"], self._fabrica_correo(t, ver), self._carpeta_descargas(),
                                            self.hoy, log=self._log, detener=t.detener,
                                            carpeta_registros=self.carpeta_registros, solo=claves, rango=rango,
                                            buscar_hasta=buscar_hasta)
            self.eventos.emitir("correo", trabajo=t.id, busqueda_id=r.busqueda_id, ok=r.ok,
                                sesion_caducada=r.sesion_caducada, resumen=r.resumen(), archivos=r.archivos[:50],
                                procesados=len(r.procesados), a_mano=True,
                                claves=[p["clave"] for p in r.procesados])
            return r.ok and not r.con_error and not r.no_encontrados and bool(r.procesados), r.resumen()
        n = len(claves)
        return self.lanzar("correo", "Procesar %s de «%s»" % ("1 correo" if n == 1 else "%d correos" % n, b["nombre"]),
                           trabajo).a_dict()

    def _relacionados_correo(self, b, datos):
        """v3.5 «Correos relacionados»: trabajo (oculto) que busca TODOS los correos que cumplen la búsqueda con otro rango
        de fechas y los devuelve en el evento «correo_relacionados» (sin procesar ninguno)."""
        from . import correo as mod_correo
        alm = self.almacen
        cuenta = alm.cuenta_correo(b["cuenta_id"])
        if cuenta is None:
            raise ErrorApi("La cuenta de correo de «%s» ya no existe: elige otra en «Editar»" % b["nombre"])
        rango = str(datos.get("rango") or "30")
        try:
            mod_correo.criterios_con_rango(b["criterios"], rango)
            desde = max(0, int(datos.get("desde") or 0))
            limite = max(1, min(int(datos.get("limite") or mod_correo.RELACIONADOS_POR_PAGINA), 50))
        except (TypeError, ValueError) as e:
            raise ErrorApi(str(e) or "Parámetros no válidos")
        abrir = datos.get("abrir") is not False

        def trabajo(t):
            base = dict(trabajo=t.id, busqueda_id=b["id"], rango=rango, desde=desde)
            try:
                with self._fabrica_correo(t, datos.get("ver"))(cuenta) as a:
                    res = mod_correo.correos_relacionados(a, b["criterios"], self.hoy, rango, desde, limite, almacen=alm,
                                                          busqueda_id=b["id"], abrir=abrir, log=self._log)
            except mod_correo.ErrorSesion as e:
                alm.marcar_sesion_correo(cuenta["id"], "caducada", str(e))
                self.eventos.emitir("correo_relacionados", ok=False, error=str(e), sesion_caducada=True, **base)
                return False, str(e)
            except (mod_correo.ErrorProveedor, mod_correo.ErrorCorreo) as e:
                self.eventos.emitir("correo_relacionados", ok=False, error=str(e), **base)
                return False, str(e)
            alm.marcar_sesion_correo(cuenta["id"], "ok", "")
            self.eventos.emitir("correo_relacionados", ok=True, mensajes=res["mensajes"], hay_mas=res["hay_mas"],
                                total_visto=res["total_visto"], **base)
            return True, "Correos relacionados de «%s»: %d" % (b["nombre"], len(res["mensajes"]))
        return self.lanzar("correo_relacionados", "Buscar los correos relacionados de «%s»" % b["nombre"],
                           trabajo).a_dict()

    def _lanzar_revision_correo(self, ids, ver, descripcion):
        from . import correo as mod_correo
        alm = self.almacen

        def trabajo(t):
            def al_resultado(r):
                self.eventos.emitir("correo", trabajo=t.id, busqueda_id=r.busqueda_id, ok=r.ok,
                                    sesion_caducada=r.sesion_caducada, resumen=r.resumen(), archivos=r.archivos[:50],
                                    procesados=len(r.procesados))
            res = mod_correo.revisar_varias(alm, ids, self._fabrica_correo(t, ver), self._carpeta_descargas(), self.hoy,
                                            log=self._log, detener=t.detener, carpeta_registros=self.carpeta_registros,
                                            al_resultado=al_resultado, manual=True)    # (v3.6.1: lo pidió el usuario)
            if not res:
                return False, "No había nada que revisar"
            return all(r.ok and not r.con_error for r in res), " · ".join(r.resumen() for r in res)
        return self.lanzar("correo", descripcion, trabajo, correo_id=ids[0] if len(ids) == 1 else None).a_dict()

    def _api_correo(self, metodo, partes, datos, q):
        """v3.4 «Correo».  GET (cuentas, búsquedas y ayudas) · cuentas (POST) · cuentas/<id> (PUT, DELETE) ·
        cuentas/<id>/sesion (POST: ventana visible para iniciar sesión) · cuentas/<id>/probar · busquedas (POST) ·
        busquedas/<id> (GET, PUT, DELETE) · busquedas/<id>/{revisar, activar, procesados, reprocesar, programar,
        quitar_tarea} · probar (POST: los correos que coinciden ahora, sin procesarlos) · revisar (POST: todas)."""
        from . import correo as mod_correo
        alm = self.almacen
        if not partes:
            if metodo != "GET":
                raise ErrorApi("Método no válido", 405)
            tareas = self._tareas()
            return {"cuentas": [self._cuenta_dict(c) for c in alm.listar_cuentas_correo()],
                    "busquedas": [self._busqueda_dict(b, tareas) for b in alm.listar_busquedas_correo()],
                    "proveedores": mod_correo.PROVEEDORES, "modos_fecha": mod_correo.MODOS_FECHA,
                    "tipos_accion": mod_correo.TIPOS_ACCION, "modos_texto": mod_correo.MODOS_TEXTO,
                    "modos_tabla": mod_correo.MODOS_TABLA, "plantillas": mod_correo.AYUDA_PLANTILLAS,
                    "hay_excel": mod_correo.HAY_OPENPYXL, "carpeta_base": self._carpeta_descargas(),
                    "criterios_defecto": mod_correo.CRITERIOS_DEFECTO, "acciones_defecto": mod_correo.ACCION_DEFECTO,
                    "max_por_vez": mod_correo.MAX_POR_VEZ, "rangos": mod_correo.RANGOS_RELACIONADOS,
                    "por_pagina": mod_correo.RELACIONADOS_POR_PAGINA}
        que = partes[0]
        if que == "revisar" and metodo == "POST":
            ids = [b["id"] for b in alm.listar_busquedas_correo(solo_activas=True)]
            if not ids:
                raise ErrorApi("No hay ninguna búsqueda de correo activa")
            return self._lanzar_revision_correo(ids, datos.get("ver"), "Revisar el correo (%d búsquedas)" % len(ids))
        if que == "probar" and metodo == "POST":
            return self._probar_correo(datos)
        if que == "cuentas":
            return self._api_cuentas_correo(metodo, partes[1:], datos)
        if que == "busquedas":
            return self._api_busquedas_correo(metodo, partes[1:], datos)
        raise ErrorApi("Acción no válida: %s" % que, 404)

    def _guardar_clave_imap(self, cid, datos):
        from . import correo as mod_correo
        if datos.get("contrasena"):
            try:
                secretos.guardar(mod_correo.secreto_de_cuenta(cid), datos["contrasena"])
            except secretos.ErrorSecreto as e:
                raise ErrorApi(str(e))

    def _api_cuentas_correo(self, metodo, partes, datos):
        from . import correo as mod_correo
        alm = self.almacen
        if not partes:
            if metodo != "POST":
                raise ErrorApi("Método no válido", 405)
            try:
                cid = alm.guardar_cuenta_correo(datos)
            except ErrorAlmacen as e:
                raise ErrorApi(str(e))
            self._guardar_clave_imap(cid, datos)
            return {"cuenta": self._cuenta_dict(alm.cuenta_correo(cid))}
        try:
            cid = int(partes[0])
        except ValueError:
            raise ErrorApi("Número de cuenta no válido")
        c = alm.cuenta_correo(cid)
        if c is None:
            raise ErrorApi("No existe la cuenta de correo %d" % cid, 404)
        accion = partes[1] if len(partes) > 1 else ""
        if accion == "" and metodo == "GET":
            return {"cuenta": self._cuenta_dict(c)}
        if accion == "" and metodo == "PUT":
            try:
                alm.guardar_cuenta_correo(dict(c, **datos), cid)
            except ErrorAlmacen as e:
                raise ErrorApi(str(e))
            self._guardar_clave_imap(cid, datos)
            return {"cuenta": self._cuenta_dict(alm.cuenta_correo(cid))}
        if accion == "" and metodo == "DELETE":
            try:
                alm.borrar_cuenta_correo(cid)
            except ErrorAlmacen as e:
                raise ErrorApi(str(e))
            if c["proveedor"] == "imap":
                try:
                    secretos.borrar(mod_correo.secreto_de_cuenta(cid))
                except secretos.ErrorSecreto:
                    pass
            return {"ok": True}
        if metodo != "POST" or accion not in ("sesion", "probar"):
            raise ErrorApi("Acción no válida", 404)
        visible = accion == "sesion" and c["proveedor"] != "imap"

        def trabajo(t):
            try:
                if c["proveedor"] == "imap":
                    from .correo_imap import probar_conexion
                    texto = probar_conexion(c)
                else:
                    fabrica = self._fabrica_correo(t, ver=visible, esperar_login=600 if visible else 0)
                    with fabrica(c):
                        pass
                    texto = "La bandeja de «%s» cargó: la sesión está iniciada" % c["nombre"]
            except mod_correo.ErrorSesion as e:
                alm.marcar_sesion_correo(cid, "caducada", str(e))
                self.eventos.emitir("correo_sesion", cuenta_id=cid, ok=False, texto=str(e))
                return False, str(e)
            except (mod_correo.ErrorProveedor, mod_correo.ErrorCorreo) as e:
                alm.marcar_sesion_correo(cid, "error", str(e))
                self.eventos.emitir("correo_sesion", cuenta_id=cid, ok=False, texto=str(e))
                return False, str(e)
            alm.marcar_sesion_correo(cid, "ok", "")
            alm.marcar_notificaciones_de("correo_sesion", "cuenta_id", cid)
            self.eventos.emitir("correo_sesion", cuenta_id=cid, ok=True, texto=texto)
            return True, texto
        if visible:
            desc = "Iniciar sesión en «%s» (entra tú en la ventana que se abre)" % c["nombre"]
        else:
            desc = "Comprobar la sesión de «%s»" % c["nombre"]
        return self.lanzar("correo_sesion", desc, trabajo).a_dict()

    def _datos_busqueda(self, datos, b=None):
        base = dict(b or {})
        for k in ("nombre", "cuenta_id", "activa", "criterios", "acciones", "max_por_vez", "programacion"):
            if k in datos:
                base[k] = datos[k]
        return base

    def _api_busquedas_correo(self, metodo, partes, datos):
        alm = self.almacen
        if not partes:
            if metodo != "POST":
                raise ErrorApi("Método no válido", 405)
            try:
                bid = alm.guardar_busqueda_correo(self._datos_busqueda(datos), hoy=self.hoy)
            except ErrorAlmacen as e:
                raise ErrorApi(str(e))
            return {"busqueda": self._busqueda_dict(alm.busqueda_correo(bid), self._tareas())}
        try:
            bid = int(partes[0])
        except ValueError:
            raise ErrorApi("Número de búsqueda no válido")
        b = alm.busqueda_correo(bid)
        if b is None:
            raise ErrorApi("No existe la búsqueda de correo %d" % bid, 404)
        accion = partes[1] if len(partes) > 1 else ""
        if accion == "" and metodo == "GET":
            return {"busqueda": self._busqueda_dict(b, self._tareas(), procesados=50),
                    "historial": alm.historial(correo_id=bid, limite=20)}
        if accion == "" and metodo == "PUT":
            try:
                alm.guardar_busqueda_correo(self._datos_busqueda(datos, b), bid, hoy=self.hoy)
            except ErrorAlmacen as e:
                raise ErrorApi(str(e))
            cambio = horario.normalizar(b["programacion"]) != horario.normalizar(
                datos.get("programacion", b["programacion"]))
            return {"busqueda": self._busqueda_dict(alm.busqueda_correo(bid), self._tareas()), "cambio_horario": cambio}
        if accion == "" and metodo == "DELETE":
            alm.borrar_busqueda_correo(bid)
            return {"ok": True}
        if accion == "procesados":
            return {"procesados": alm.procesados_correo(bid, limite=int(datos.get("limite") or 100),
                                                        incluir_descartados=True)}
        if metodo != "POST":
            raise ErrorApi("Método no válido", 405)
        if accion == "activar":
            alm.activar_busqueda_correo(bid, datos.get("activa") is not False)
            return {"busqueda": self._busqueda_dict(alm.busqueda_correo(bid), self._tareas())}
        if accion == "revisar":
            return self._lanzar_revision_correo([bid], datos.get("ver"), "Revisar el correo «%s»" % b["nombre"])
        if accion == "relacionados":                 # v3.5: «Correos relacionados» (la lista, sin procesar)
            return self._relacionados_correo(b, datos)
        if accion == "procesar":                     # v3.5: «Procesar este» / «Procesar seleccionados» (a la fuerza)
            from . import correo as mod_correo
            claves = [str(c) for c in datos.get("claves") or [] if str(c or "").strip()]
            if not claves:
                raise ErrorApi("Elige al menos un correo")
            if len(claves) > mod_correo.RELACIONADOS_MAX:
                raise ErrorApi("Como mucho %d correos a la vez" % mod_correo.RELACIONADOS_MAX)
            rango = str(datos.get("rango") or "busqueda")
            try:
                mod_correo.criterios_con_rango(b["criterios"], rango)
                buscar_hasta = int(datos.get("buscar_hasta") or 0)
            except (TypeError, ValueError) as e:
                raise ErrorApi(str(e) or "Parámetros no válidos")
            agrega = mod_correo.acciones_que_agregan(b["acciones"])
            ya = [c for c in claves if (alm.correo_procesado(bid, c) or {}).get("estado") in ("ok", "error")]
            if agrega and ya and datos.get("confirmar") is not True:
                return {"confirmar": True, "ya_procesados": len(ya), "acciones": agrega,
                        "mensaje": "%s ya se procesó. Volver a procesarlo repite TODAS sus acciones, y estas AÑADEN filas "
                                   "a un archivo, así que pueden quedar repetidas: %s. ¿Procesar igualmente?"
                                   % ("1 de los correos elegidos" if len(ya) == 1 else "%d de los correos elegidos" % len(ya),
                                      "; ".join(agrega))}
            return self._lanzar_procesar_correos(b, claves, rango, buscar_hasta, datos.get("ver"))
        if accion == "reprocesar":
            clave = datos.get("clave") or ""
            if not alm.olvidar_correo_procesado(bid, clave):
                raise ErrorApi("Ese correo no estaba apuntado como procesado")
            return {"ok": True}
        if accion == "programar":
            prog = datos["programacion"] if "programacion" in datos else b["programacion"]
            if "programacion" not in datos and horario.es_vacia(prog):
                raise ErrorApi("Esta búsqueda no tiene horario: elige cuándo revisarla en «Editar» → Cuándo")
            if datos.get("confirmar") is True and "programacion" in datos:
                try:
                    alm.guardar_busqueda_correo(dict(b, programacion=prog), bid, hoy=self.hoy)
                except ErrorAlmacen as e:
                    raise ErrorApi(str(e))
            tarea = "Correo %s #%d" % (b["nombre"], bid)
            return self._programar_con_horario(tarea, prog, datos, {"correo_id": bid}, clave="correo:%d" % bid,
                                               sustituir=self._tareas_de_correo(bid, self._tareas()))
        if accion == "quitar_tarea":
            return self._quitar_tareas(self._tareas_de_correo(bid, self._tareas()), datos, clave="correo:%d" % bid)
        raise ErrorApi("Acción no válida", 404)

    def _probar_correo(self, datos):
        """«Probar búsqueda»: un trabajo (oculto) que abre el buzón, busca y abre los correos que coinciden AHORA para
        enseñar su asunto, remitente, fecha y adjuntos, sin procesarlos.  El resultado llega en el evento
        «correo_prueba»."""
        from . import correo as mod_correo
        alm = self.almacen
        bid = datos.get("busqueda_id")
        b = alm.busqueda_correo(bid) if bid else None
        cuenta = alm.cuenta_correo(datos.get("cuenta_id") or (b or {}).get("cuenta_id"))
        if cuenta is None:
            raise ErrorApi("Elige la cuenta de correo")
        criterios = datos.get("criterios") if datos.get("criterios") is not None else (b or {}).get("criterios")
        try:
            criterios = mod_correo.normalizar_criterios(criterios, self.hoy, exigir=False)
        except mod_correo.ErrorCorreo as e:
            raise ErrorApi(str(e))
        try:
            limite = min(max(int(datos.get("limite") or 10), 1), 30)
        except (TypeError, ValueError):
            limite = 10

        def trabajo(t):
            try:
                with self._fabrica_correo(t, datos.get("ver"))(cuenta) as a:
                    res = mod_correo.probar_busqueda(a, criterios, self.hoy, limite, almacen=alm,
                                                     busqueda_id=b["id"] if b else None, log=self._log)
            except mod_correo.ErrorSesion as e:
                alm.marcar_sesion_correo(cuenta["id"], "caducada", str(e))
                self.eventos.emitir("correo_prueba", trabajo=t.id, ok=False, error=str(e), sesion_caducada=True,
                                    cuenta_id=cuenta["id"])
                return False, str(e)
            except (mod_correo.ErrorProveedor, mod_correo.ErrorCorreo) as e:
                self.eventos.emitir("correo_prueba", trabajo=t.id, ok=False, error=str(e), cuenta_id=cuenta["id"])
                return False, str(e)
            alm.marcar_sesion_correo(cuenta["id"], "ok", "")
            buenos = [m for m in res if m.get("coincide")]
            self.eventos.emitir("correo_prueba", trabajo=t.id, ok=True, mensajes=res, cuenta_id=cuenta["id"],
                                busqueda_id=b["id"] if b else None)
            return True, "Probar búsqueda: %d correo(s) coinciden ahora" % len(buenos)
        return self.lanzar("correo_prueba", "Probar la búsqueda de correo", trabajo).a_dict()

    # ------------------------------------------------------- v3.2: abrir archivos
    def _raices_permitidas(self):
        raices = {self._carpeta_descargas(), os.path.abspath(os.path.join(RAIZ, "descargas"))}
        if self.carpeta_descargas:
            raices.add(os.path.abspath(self.carpeta_descargas))
        for p in self.almacen.listar_paginas():
            c = ((p.get("data") or {}).get("opciones") or {}).get("carpeta_descargas")
            if c and os.path.isabs(c):
                raices.add(os.path.abspath(c))
        # v3.4: las carpetas y archivos de las acciones de correo (la parte fija, antes de la primera plantilla)
        for b in self.almacen.listar_busquedas_correo():
            for a in b["acciones"]:
                for k in ("carpeta", "archivo"):
                    v = (a.get(k) or "").split("{", 1)[0].strip()
                    v = os.path.expanduser(os.path.expandvars(v)) if v else ""
                    if v and os.path.isabs(v):
                        raices.add(os.path.abspath(v if k == "carpeta" else os.path.dirname(v) or v))
        return {r for r in raices if len(r) > 3}         # nunca la raíz de una unidad entera

    EXTENSIONES_ABRIR = (".xlsx", ".xls", ".csv", ".pdf", ".txt", ".docx", ".doc", ".json", ".xml", ".html", ".htm",
                         ".png", ".jpg", ".jpeg", ".zip")

    def _api_archivos(self, metodo, partes, datos, q):
        """POST archivos/abrir {ruta} abre un archivo descargado; POST archivos/carpeta {ruta} abre su carpeta (con el
        archivo marcado).  Solo archivos dentro de las carpetas de descargas del bot."""
        if metodo != "POST":
            raise ErrorApi("Método no válido", 405)
        accion = partes[0] if partes else ""
        ruta = os.path.abspath(datos.get("ruta") or "")
        if not datos.get("ruta") or not any(os.path.commonpath([r, ruta]) == r for r in self._raices_permitidas()
                                            if os.path.splitdrive(r)[0].lower() == os.path.splitdrive(ruta)[0].lower()):
            raise ErrorApi("Ese archivo no está en la carpeta de descargas del bot", 403)
        if accion == "carpeta":
            if os.path.isdir(ruta):
                self.abrir_en_sistema(ruta, carpeta=True)
                return {"ok": True}
            if not os.path.isfile(ruta):
                raise ErrorApi("Ya no existe: %s" % ruta, 404)
            self.abrir_en_sistema(ruta, carpeta=True)
            return {"ok": True}
        if accion == "abrir":
            if not os.path.isfile(ruta):
                raise ErrorApi("Ya no existe: %s" % ruta, 404)
            if os.path.splitext(ruta)[1].lower() not in self.EXTENSIONES_ABRIR:
                raise ErrorApi("Por seguridad, ese tipo de archivo no se abre desde aquí: usa «Abrir carpeta»")
            self.abrir_en_sistema(ruta, carpeta=False)
            return {"ok": True}
        raise ErrorApi("Acción no válida", 404)

    # --------------------------------------------------------------- accesos
    def _sitios(self):
        """Sitios con datos de acceso: los de Accesos, los de los pasos «Iniciar sesión» y los de estado_claves."""
        sitios = {}
        for a in self.almacen.listar_accesos():
            s = sitios.setdefault(a["host"], {"host": a["host"], "campos": {}, "reportes": []})
            s["campos"][a["clave"]] = {"clave": a["clave"], "etiqueta": a["etiqueta"], "tipo": a["tipo"],
                                       "valor": a["valor"] if a["tipo"] == "texto" else None, "secreto": a["secreto"],
                                       "origen": "accesos"}
        for r in self.almacen.listar():
            try:
                fl = self.almacen.cargar_flujo(r["id"])
            except ErrorAlmacen:
                continue
            for i, p in enumerate(fl.pasos):
                if p.tipo != "iniciar_sesion" or not p.sitio:
                    continue
                s = sitios.setdefault(p.sitio, {"host": p.sitio, "campos": {}, "reportes": []})
                if r["nombre"] not in [x["nombre"] for x in s["reportes"]]:
                    s["reportes"].append({"id": r["id"], "nombre": r["nombre"], "paso": i})
                for c in p.campos:
                    clave = c.get("clave") or "campo"
                    if clave in s["campos"]:
                        continue
                    tipo = c.get("tipo") or "texto"
                    s["campos"][clave] = {"clave": clave, "etiqueta": c.get("etiqueta") or clave, "tipo": tipo,
                                          "valor": (c.get("valor") or "") if tipo == "texto" else None,
                                          "secreto": c.get("secreto") or (mod_accesos.nombre_secreto(p.sitio, clave)
                                                                          if tipo == "clave" else None),
                                          "origen": "reporte"}
        estados = {e["secreto"]: e for e in self.almacen.estados_claves()}
        for e in estados.values():
            if e["host"]:
                sitios.setdefault(e["host"], {"host": e["host"], "campos": {}, "reportes": []})
        res = []
        for host in sorted(sitios):
            s = sitios[host]
            campos = list(s["campos"].values())
            for c in campos:
                if c["tipo"] != "clave":
                    continue
                nombre = c.get("secreto") or mod_accesos.nombre_secreto(host, c["clave"])
                c["secreto"] = nombre
                try:
                    existe = secretos.existe(nombre)
                    rech = secretos.rechazada(nombre) if existe else None
                except secretos.ErrorSecreto:
                    existe, rech = False, None
                est = estados.get(nombre) or {}
                c["estado"] = "rechazada" if rech else ("guardada" if existe else "falta")
                c["rechazada_en"] = rech or ""
                # v3.3.1: lo que dijo la página al rechazarla (si era un dato obligatorio vacío, no era la contraseña)
                c["motivo"] = (est.get("motivo") or "") if rech else ""
                c["motivo_obligatorio"] = bool(rech) and mod_accesos.es_mensaje_obligatorio(c["motivo"])
                c["ultimo_ok"] = est.get("ultimo_ok") or ""
            s["campos"] = campos
            s["usuario"] = next((c["valor"] for c in campos if c["tipo"] == "texto" and c.get("valor")), "")
            s["estado"] = ("rechazada" if any(c.get("estado") == "rechazada" for c in campos) else
                           "falta" if any(c.get("estado") == "falta" for c in campos) else "guardada")
            res.append(s)
        return res

    def _api_accesos(self, metodo, partes, datos, q):
        alm = self.almacen
        if not partes:
            return {"sitios": self._sitios()}
        host = partes[0].lower()
        accion = partes[1] if len(partes) > 1 else ""
        sitio = next((s for s in self._sitios() if s["host"] == host), None)
        if accion == "clave" and metodo == "POST":
            nueva = datos.get("contrasena") or ""
            if not nueva:
                raise ErrorApi("Escribe la contraseña nueva")
            campo = datos.get("clave")
            campos = [c for c in (sitio or {}).get("campos", []) if c["tipo"] == "clave"]
            c = next((x for x in campos if x["clave"] == campo), campos[0] if campos else None)
            nombre = (c or {}).get("secreto") or mod_accesos.nombre_secreto(host, campo or "clave")
            secretos.guardar(nombre, nueva)
            secretos.limpiar_rechazo(nombre)
            alm.guardar_acceso(host, (c or {}).get("clave") or campo or "clave", (c or {}).get("etiqueta") or "Contraseña",
                               "clave", secreto=nombre)
            alm.marcar_clave_ok(nombre, host)
            alm.marcar_notificaciones_de("clave_rechazada", "host", host)
            if datos.get("usuario") is not None and sitio:
                texto = next((x for x in sitio["campos"] if x["tipo"] == "texto"), None)
                if texto is not None and datos["usuario"] != (texto.get("valor") or ""):
                    alm.guardar_acceso(host, texto["clave"], texto["etiqueta"], "texto", valor=datos["usuario"])
            self.eventos.emitir("aviso", aviso="accesos_guardados", host=host,
                                texto="Contraseña de «%s» guardada" % host)
            return {"ok": True, "secreto": nombre}
        if accion == "quitar_rechazo" and metodo == "POST":
            # v3.3.1: «Quitar marca de rechazada» (p. ej. la puso un «campo obligatorio vacío», no la contraseña)
            quitadas = []
            for c in (sitio or {}).get("campos", []):
                if c["tipo"] != "clave" or not c.get("secreto"):
                    continue
                if datos.get("clave") and c["clave"] != datos.get("clave"):
                    continue
                try:
                    secretos.limpiar_rechazo(c["secreto"])
                except secretos.ErrorSecreto:
                    pass
                alm.limpiar_rechazo_clave(c["secreto"])
                quitadas.append(c["secreto"])
            alm.marcar_notificaciones_de("clave_rechazada", "host", host)
            return {"ok": True, "quitadas": len(quitadas)}
        if accion == "campo" and metodo == "PUT":
            alm.guardar_acceso(host, datos.get("clave"), datos.get("etiqueta") or "", "texto", valor=datos.get("valor") or "")
            return {"ok": True}
        if accion == "" and metodo == "DELETE":
            for c in (sitio or {}).get("campos", []):
                if c["tipo"] == "clave" and c.get("secreto") and c.get("origen") == "accesos":
                    try:
                        secretos.borrar(c["secreto"])
                    except secretos.ErrorSecreto:
                        pass
            alm.borrar_acceso(host)
            return {"ok": True}
        if accion == "probar" and metodo == "POST":
            return self._probar_acceso(host, sitio, datos).a_dict()
        raise ErrorApi("Acción no válida", 404)

    def _probar_acceso(self, host, sitio, datos):
        """Ejecuta solo el inicio de sesión de un reporte que usa ese sitio, con un perfil temporal (sin sesión)."""
        reportes = (sitio or {}).get("reportes") or []
        if not reportes:
            raise ErrorApi("Ningún reporte guardado inicia sesión en «%s»: graba uno o ejecútalo una vez." % host)
        r = reportes[0]
        fl = self.almacen.cargar_flujo(r["id"])
        fl.nombre = "Probar acceso a %s" % host
        fl.pasos = [p for p in fl.pasos[:r["paso"] + 1] if not p.desactivado]

        def trabajo(t):
            tmp = tempfile.mkdtemp(prefix="botweb_acceso_")
            try:
                ej = self.crear_ejecutor(t, fl, None, ver=datos.get("ver"), carpeta_perfil=tmp)
                res = ej.ejecutar()
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            texto = ("El acceso a «%s» funciona." % host) if res.ok else ("El acceso a «%s» falló: %s" % (host, res.error))
            self.eventos.emitir("acceso_probado", host=host, ok=res.ok, texto=texto)
            return res.ok, texto
        return self.lanzar("probar_acceso", "Probar acceso a «%s»" % host, trabajo)

    # -------------------------------------------------------- notificaciones
    def _api_notificaciones(self, metodo, partes, datos, q):
        if not partes:
            if metodo == "POST":                         # todas leídas
                for n in self.almacen.notificaciones(limite=300, solo_no_leidas=True):
                    self.almacen.marcar_notificacion(n["id"])
                return {"ok": True}
            return {"notificaciones": self.almacen.notificaciones(limite=int((q.get("limite") or ["50"])[0])),
                    "no_leidas": self.almacen.no_leidas()}
        nid = int(partes[0])
        if metodo == "POST":
            self.almacen.marcar_notificacion(nid, datos.get("leida", True) is not False)
            return {"ok": True}
        n = self.almacen.notificacion(nid)
        if n is None:
            raise ErrorApi("No existe esa notificación", 404)
        return {"notificacion": n}

    # -------------------------------------------------------------- historial
    def _api_historial(self, metodo, partes, datos, q):
        if not partes:
            rid = (q.get("reporte") or [None])[0]
            limite = int((q.get("limite") or ["100"])[0])
            return {"historial": self.almacen.historial(int(rid) if rid else None, limite=limite)}
        e = self.almacen.ejecucion(int(partes[0]))
        if e is None:
            raise ErrorApi("No existe esa ejecución", 404)
        que = partes[1] if len(partes) > 1 else "registro"
        ruta = e.get("registro" if que == "registro" else "captura") or ""
        base = os.path.abspath(self.carpeta_registros)
        ruta = os.path.abspath(ruta) if ruta else ""
        if not ruta or os.path.commonpath([base, ruta]) != base or not os.path.isfile(ruta):
            raise ErrorApi("No se encontró el %s de esa ejecución" % ("registro" if que == "registro" else "captura"), 404)
        if que == "registro":
            with open(ruta, encoding="utf-8", errors="replace") as f:
                return {"texto": f.read()[-200000:], "ruta": ruta}
        with open(ruta, "rb") as f:
            return ("image/png", f.read())

    # ---------------------------------------------------------------- ajustes
    def _api_ajustes(self, metodo, partes, datos, q):
        if metodo == "PUT":
            return {"ajustes": self.almacen.guardar_ajustes(datos.get("ajustes") or {})}
        return {"ajustes": self.almacen.ajustes(), "carpeta_descargas_defecto": os.path.join(RAIZ, "descargas"),
                "base_de_datos": self.almacen.ruta}


# ======================================================================= HTTP
class _Manejador(http.server.BaseHTTPRequestHandler):
    server_version = "BotWeb"
    sys_version = ""

    def log_message(self, *args):
        pass

    @property
    def app(self):
        return self.server.app

    def _cabeceras_comunes(self, cache=False):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # v3.5: las fuentes (ui/fuentes) no cambian: el navegador las guarda un día; lo demás, nunca
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8", cache=False):
        try:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self._cabeceras_comunes(cache)
            if tipo.startswith("text/html"):
                self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data:; "
                                 "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
                                 "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)
        except (ConnectionError, OSError):
            pass

    def _json(self, codigo, datos):
        self._enviar(codigo, json.dumps(datos, ensure_ascii=False, default=str).encode("utf-8"))

    def _origen_valido(self):
        puerto = self.server.server_address[1]
        validos = {"127.0.0.1:%d" % puerto, "localhost:%d" % puerto}
        if (self.headers.get("Host") or "") not in validos:
            return False
        origen = self.headers.get("Origin")
        if origen is not None and origen not in {"http://" + v for v in validos}:
            return False
        sitio = self.headers.get("Sec-Fetch-Site")
        if sitio is not None and sitio not in ("same-origin", "none"):
            return False
        return True

    def do_GET(self):
        self._atender("GET")

    def do_HEAD(self):
        self._atender("GET")

    def do_POST(self):
        self._atender("POST")

    def do_PUT(self):
        self._atender("PUT")

    def do_DELETE(self):
        self._atender("DELETE")

    def _atender(self, metodo):
        u = urlparse(self.path)
        if not self._origen_valido():
            return self._json(403, {"error": "Origen no permitido"})
        if not u.path.startswith("/api/"):
            if metodo != "GET":
                return self._json(405, {"error": "Método no válido"})
            return self._estatico(u.path)
        token = self.headers.get("X-Bot-Token") or ""
        if not hmac.compare_digest(token.encode("utf-8"), self.app.token.encode("utf-8")):
            return self._json(401, {"error": "Falta el permiso de esta sesión (token)"})
        datos = {}
        if metodo in ("POST", "PUT", "DELETE"):
            if "application/json" not in (self.headers.get("Content-Type") or "") and int(self.headers.get("Content-Length") or 0):
                return self._json(415, {"error": "Se espera JSON"})
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                largo = 0
            if largo > MAX_CUERPO:
                return self._json(413, {"error": "Petición demasiado grande"})
            if largo:
                try:
                    datos = json.loads(self.rfile.read(largo).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return self._json(400, {"error": "JSON no válido"})
        try:
            res = self.app.api(metodo, u.path, datos if isinstance(datos, dict) else {}, parse_qs(u.query))
        except ErrorApi as e:
            return self._json(e.codigo, {"error": str(e)})
        except (ErrorAlmacen, ErrorFlujo, secretos.ErrorSecreto, ValueError, KeyError, TypeError) as e:
            return self._json(400, {"error": str(e) or type(e).__name__})
        except Exception as e:         # noqa: BLE001
            traceback.print_exc()
            return self._json(500, {"error": "Error inesperado: %s" % type(e).__name__})
        finally:
            # v3.5: cada petición llega en un hilo NUEVO (ThreadingMixIn) y abría su propia conexión de SQLite, que nunca
            # se cerraba (se acumulaban miles en un día con el sondeo de eventos).  Se cierra al terminar la petición.
            try:
                self.app.almacen.liberar_hilo()
            except Exception:          # noqa: BLE001
                pass
        if isinstance(res, tuple):                       # (tipo, bytes): archivos (capturas)
            return self._enviar(200, res[1], res[0])
        return self._json(200, res)

    def _estatico(self, ruta):
        ruta = unquote(ruta)
        if ruta in ("", "/"):
            ruta = "/index.html"
        base = os.path.abspath(self.server.carpeta_ui)
        destino = os.path.abspath(os.path.join(base, ruta.lstrip("/").replace("/", os.sep)))
        if os.path.commonpath([base, destino]) != base or not os.path.isfile(destino):
            return self._json(404, {"error": "No existe"})
        tipo = mimetypes.guess_type(destino)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        with open(destino, "rb") as f:
            self._enviar(200, f.read(), tipo, cache=tipo.startswith("font/"))


class ServidorUI(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, app, puerto=0, carpeta_ui=CARPETA_UI):
        super().__init__(("127.0.0.1", int(puerto or 0)), _Manejador)
        self.app = app
        self.carpeta_ui = carpeta_ui
        self.puerto = self.server_address[1]
        self.url = "http://127.0.0.1:%d/" % self.puerto
        self._hilo = None

    def iniciar(self):
        self._hilo = threading.Thread(target=self.serve_forever, name="servidor-ui", daemon=True)
        self._hilo.start()
        return self

    def parar(self):
        self.shutdown()
        self.server_close()

    def url_con_token(self, ruta="inicio"):
        return "%s#t=%s&r=%s" % (self.url, self.app.token, ruta)


def abrir_en_sistema(ruta, carpeta=False):
    """Abre un archivo con su programa (Excel, el visor de PDF…) o su carpeta en el Explorador con el archivo marcado."""
    import subprocess
    if carpeta:
        if os.path.isfile(ruta):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(ruta)])
        else:
            os.startfile(os.path.normpath(ruta))          # noqa: S606 (carpeta del bot)
        return
    os.startfile(os.path.normpath(ruta))                  # noqa: S606 (archivo descargado por el bot)


# ===================================================================== arranque
def buscar_navegador_app():
    """Ruta de Edge o Chrome para abrir la interfaz como ventana de aplicación (o None).  Vale con uno solo de los dos
    (v3.7: también los busca en «App Paths» del registro)."""
    from . import navegador as mod_navegador
    return (mod_navegador.buscar_ejecutable("msedge") or mod_navegador.buscar_ejecutable("chrome")
            or shutil.which("msedge") or shutil.which("chrome"))


def abrir_ventana(url):
    import subprocess
    import webbrowser
    exe = buscar_navegador_app()
    if exe:
        perfil = os.path.join(carpeta("perfiles"), "_interfaz")
        try:
            subprocess.Popen([exe, "--app=" + url, "--user-data-dir=" + perfil, "--no-first-run",
                              "--no-default-browser-check", "--window-size=1360,880"])
            return True
        except OSError:
            pass
    return webbrowser.open(url)


def abrir_aplicacion(args):
    """`python bot.py`: arranca la interfaz nueva y abre su ventana.  Se cierra sola cuando se cierra la ventana (sin
    latidos durante un rato y sin trabajos en curso) o con Ctrl+C."""
    from .almacen import Almacen
    import bot as mod_bot
    almacen = mod_bot.abrir_almacen(args)
    for m in mod_bot.migrar_flujos_antiguos(almacen, args) + mod_bot.migrar_reportes(almacen):
        print(m, flush=True)
    app = Aplicacion(almacen, carpeta_perfiles=mod_bot.carpeta_perfiles_de(args),
                     carpeta_registros=os.path.abspath(args.registros) if args.registros else None,
                     carpeta_descargas=os.path.abspath(args.descargas) if args.descargas else None)
    try:
        ids = [x for x in mod_bot.objetivos_de(args, almacen=almacen) if isinstance(x, int)]
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        ids = []
    if ids:
        app.al_iniciar.append({"accion": "ejecutar" if args.ejecutar else "abrir", "ids": ids})
        if args.ejecutar:
            try:
                app._api_ejecutar("POST", [], {"ids": ids, "ver": True if args.visible else (False if args.oculto else None),
                                               "lento": args.lento}, {})
            except ErrorApi as e:
                print(str(e), file=sys.stderr)
    app.tareas_en_segundo_plano = True                # v3.5: la lista de tareas de Windows nunca hace esperar
    app.lanzar_proceso = programador.lanzar_desacoplado   # v3.6.1: solo la aplicación de verdad lanza el bot
    app.guia_al_abrir = True                              # v3.8: la primera vez, la guía con flechas
    if os.environ.get("BOTWEB_SIN_ACTUALIZAR") != "1":    # v3.9: avisa si hay otra versión en GitHub (cada 6 h)
        from . import actualizar as mod_actualizar
        app.actualizador = mod_actualizar.Actualizador(registrar=lambda linea: print(linea, flush=True),
                                                       emitir=app.eventos.emitir).iniciar_periodico()
    app.precargar_tareas()
    srv = ServidorUI(app, puerto=getattr(args, "puerto", 0)).iniciar()
    url = srv.url_con_token("reportes" if ids else "inicio")
    print("Bot Web %s — interfaz en %s" % (VERSION, srv.url), flush=True)
    print("(Para la ventana clásica: python bot.py --clasica)", flush=True)
    if not getattr(args, "sin_navegador", False):
        abrir_ventana(url)
    else:
        print("Abre esta dirección: %s" % url, flush=True)
    inicio = time.monotonic()
    try:
        while True:
            if app.salir.wait(2):
                break                                    # v3.9: se actualiza (el instalador espera a que se cierre)
            ultimo = app.ultimo_latido
            ocupado = app.trabajo is not None and app.trabajo.estado == "en_curso"
            if ultimo is None:
                if time.monotonic() - inicio > 600 and not getattr(args, "sin_navegador", False):
                    break                                # nunca se abrió la ventana
                continue
            if not ocupado and time.monotonic() - ultimo > 120:
                break                                    # se cerró la ventana (sin latidos ni consultas durante 2 min)
    except KeyboardInterrupt:
        pass
    if app.actualizador is not None:
        app.actualizador.parar()
    app.detener()
    srv.parar()
    almacen.cerrar()
    return 0


class _BuzonDePrueba:
    """(--smoke-web) Un buzón en memoria con dos correos, para abrir «Correos relacionados» sin ningún correo real."""

    def __init__(self, cuenta=None):               # (la clase hace de «abrir_adaptador(cuenta)»)
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def buscar(self, c, hoy=None, limite=30):
        ahora = datetime.datetime.now().replace(second=0, microsecond=0)
        return [{"id": "prueba:%d" % i, "asunto": "RESUMEN DE VENTAS %d" % i, "remitente": "Reportes <r@ejemplo.com>",
                 "remitente_correo": "r@ejemplo.com", "fecha": ahora - datetime.timedelta(days=i), "adjuntos": None,
                 "tiene_adjuntos": True, "texto": ""} for i in range(2)][:limite]

    def abrir(self, m):
        return {"asunto": m["asunto"], "remitente": m["remitente"], "fecha": m["fecha"], "html": "<p>Total ventas: 1</p>",
                "texto": "", "adjuntos": [{"nombre": "SUPERVISION VENTAS.xlsx", "tamano": ""}]}

    def descargar(self, m, det, nombres, carpeta):
        return {}


def probar_web(args):
    """--smoke-web: arranca la interfaz con una base de datos TEMPORAL, la carga en un navegador oculto, recorre todas
    las páginas comprobando que no hay errores en la consola y sale (0 = bien)."""
    from playwright.sync_api import sync_playwright
    secretos.usar_almacen(secretos.AlmacenMemoria())      # nunca toca las credenciales reales
    tmp = tempfile.mkdtemp(prefix="botweb_smokeweb_")
    try:
        alm = Almacen(os.path.join(tmp, "bot.db"))
        rid = alm.guardar(Flujo(nombre="Ventas (prueba)", url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"),
            Paso("elegir_opcion", selectores=["#corte"], objetivo="Elegir corte", estrategia="mas_reciente"),
            # v3.5: una descarga con el nombre fijo que da la web (el editor ofrece «Usar el nombre del reporte»)
            Paso("descargar", selectores=["#generar"], nombre="report_xls{ext}")]))
        from . import paginas as mod_paginas          # v3.2: una Página de prueba (con un favorito y opciones)
        pid, _n = mod_paginas.guardar_nueva(alm, "Portal – Reportes (prueba)", {
            "url": "http://127.0.0.1/", "llegada": [Paso("abrir_url", url="http://127.0.0.1/").a_dict()],
            "filtros": [{"id": "f1", "tipo": "pestana", "nombre": "Pestaña", "pestanas": [
                {"texto": "Corte", "selectores": ["#t1"]}, {"texto": "Crédito y Cobros", "selectores": ["#t2"]}],
                "defecto": {"estrategia": "fija", "valor": "Corte"}},
                {"id": "f2", "tipo": "lista", "nombre": "Seleccione reporte", "selectores": ["#rep"],
                 "defecto": {"estrategia": "fija", "valor": "Detalles Ventas Mayorista"}},
                {"id": "f3", "tipo": "lista", "nombre": "Elegir corte", "selectores": ["#corte"], "depende_de": ["f2"],
                 "defecto": {"estrategia": "mas_reciente", "valor": ""}},
                {"id": "f4", "tipo": "fecha", "nombre": "Desde", "selectores": ["#desde"], "defecto": {"valor": "{ayer}"}},
                {"id": "f5", "tipo": "casilla", "nombre": "Solo vencidos", "selectores": ["#venc"]}],
            "accion": {"tipo": "boton_descarga", "generar": {"selectores": ["#generar"], "objetivo": "Generar"}},
            "favoritos": [{"nombre": "Mayorista", "valores": {"f3": {"estrategia": "mas_reciente", "valor": ""}}}]},
            [("f2", ["Detalles Ventas Mayorista", "Resumen de Ventas"], {}),
             ("f3", ["43 - 2026 (02/10/2026 - 08/10/2026)", "44 - 2026 (09/10/2026 - 15/10/2026)"],
              {"f2": "Detalles Ventas Mayorista"})])
        # v3.3: varias vigilancias (la misma lista de la Página con otro reporte, y una del reporte)
        alm.crear_vigilancia(pagina_id=pid, filtro="f3", valores={"f2": {"estrategia": "fija",
                                                                         "valor": "Detalles Ventas Mayorista"}})
        alm.crear_vigilancia(pagina_id=pid, filtro="f3", nombre="Resumen", auto_descargar=True,
                             valores={"f2": {"estrategia": "fija", "valor": "Resumen de Ventas"}})
        alm.crear_vigilancia(reporte_id=rid, paso=1, frecuencia="horas", cada_horas=4)
        # v3.4: una cuenta de correo y una búsqueda con horario (sin tarea de Windows)
        cid = alm.guardar_cuenta_correo({"nombre": "Correo (prueba)", "proveedor": "outlook_web",
                                         "direccion": "reportes@ejemplo.com"})
        alm.guardar_busqueda_correo({"nombre": "Ventas (prueba)", "cuenta_id": cid,
                                     "criterios": {"asunto": "RESUMEN DE VENTAS", "fecha": "ultimos", "dias": 7},
                                     "acciones": [{"tipo": "adjuntos", "coincide": "SUPERVISION VENTAS",
                                                   "nombre": "Ventas {fecha_correo:%Y-%m-%d}.xlsx"},
                                                  {"tipo": "texto", "etiqueta": "Total ventas:"}],
                                     "programacion": {"reglas": [{"tipo": "semanal", "dias": ["lun", "mar", "mie", "jue",
                                                                                              "vie"],
                                                                  "horas": ["09:00", "15:00"]}]}})
        elegida = os.path.join(tmp, "Carpeta elegida, S.A.S")       # v3.5: «📁 Elegir…» falso (ningún diálogo de verdad)
        app = Aplicacion(alm, carpeta_perfiles=os.path.join(tmp, "perfiles"),
                         carpeta_registros=os.path.join(tmp, "registros"), listar_tareas=lambda: [], oculto_forzado=True,
                         ejecutar_tareas=lambda cmd: (1, "(prueba: nunca se crean tareas)"),
                         abrir_dialogo=lambda tipo, inicial, filtros, titulo: elegida)
        app._fabrica_correo = lambda t, ver=False, esperar_login=0: _BuzonDePrueba   # v3.5: sin Outlook de verdad
        srv = ServidorUI(app).iniciar()
        errores = []
        try:
            with sync_playwright() as p:
                from . import navegador as mod_navegador     # v3.7: con Edge si no hay Chrome (y al revés)
                nav = mod_navegador.lanzar(p, getattr(args, "navegador", None) or "chrome", headless=True)
                try:
                    pg = nav.new_page()
                    pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
                    pg.on("pageerror", lambda e: errores.append(str(e)))
                    pg.goto(srv.url_con_token(), wait_until="load")
                    pg.wait_for_selector("#contenido [data-pagina='inicio']", timeout=15000)
                    for pagina in ("reportes", "grabar", "mapear", "vigilancia", "correo", "accesos", "historial",
                                   "ajustes", "editor/1", "paginas/%d" % pid, "inicio"):
                        pg.evaluate("p => { location.hash = '#/' + p; }", pagina)
                        pg.wait_for_selector("#contenido [data-pagina='%s']" % pagina.split("/")[0], timeout=15000)
                        pg.wait_for_timeout(250)
                        if pagina.startswith("paginas/"):       # v3.2: el formulario de la Página tiene sus filtros
                            pg.wait_for_selector("#contenido .pagina-form [data-filtro='f3'] select", timeout=15000)
                            if not pg.locator("#contenido .pagina-form .filtro").count() == 5:
                                errores.append("el formulario de la página no tiene sus 5 filtros")
                    # v3.3: la página Vigilancia muestra las 3 vigilancias y la ventana «Añadir vigilancia» se abre
                    pg.evaluate("() => { location.hash = '#/vigilancia'; }")
                    pg.wait_for_selector("#contenido [data-pagina='vigilancia'] .vigilancia-tarjeta", timeout=15000)
                    if pg.locator("#contenido .vigilancia-tarjeta").count() != 3:
                        errores.append("la página Vigilancia no muestra las 3 vigilancias")
                    pg.locator("#contenido button[data-anadir^='pagina-']").first.click()
                    pg.wait_for_selector(".modal [data-valores-vigilancia] select", timeout=15000)
                    pg.click(".modal .pie button:has-text('Cancelar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    # v3.3.1: «＋ Añadir vigilancia» de arriba: elegir cualquier reporte o Página y después la lista
                    pg.click("#contenido button[data-anadir-vigilancia]")
                    pg.wait_for_selector(".modal [data-candidatos-vigilancia] li[data-candidato='reporte-%d']" % rid,
                                         timeout=15000)
                    pg.click(".modal li[data-candidato='reporte-%d']" % rid)
                    pg.wait_for_selector(".modal [data-modal-vigilancia] select", timeout=15000)
                    pg.click(".modal .pie button:has-text('Cancelar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    # v3.4: la vigilancia con horario y sin tarea lo dice; «Cambiar…» muestra el editor «Cuándo» con la
                    # vista previa (próximas revisiones calculadas por el bot) y se puede añadir otro horario
                    pg.evaluate("() => { location.hash = '#/vigilancia'; }")
                    pg.wait_for_selector("#contenido [data-tarea-vigilancia='no'] button[data-activar-tarea]", timeout=15000)
                    pg.locator("#contenido [data-tarea-vigilancia='no']").first.locator(
                        "xpath=ancestor::div[contains(@class,'vigilancia-tarjeta')]").locator("button:has-text('Cambiar')").click()
                    pg.wait_for_selector(".modal [data-cuando] [data-cuando-regla] input[type=number]", timeout=15000)
                    pg.wait_for_selector(".modal [data-cuando-proximas]", timeout=15000)
                    pg.click(".modal button[data-cuando-anadir]")
                    pg.wait_for_selector(".modal [data-cuando-regla='1']", timeout=5000)
                    pg.select_option(".modal select[data-regla-tipo='1']", "mensual")
                    pg.wait_for_selector(".modal [data-cuando-regla='1'] button[data-dia-mes='ultimo']", timeout=5000)
                    pg.click(".modal [data-cuando-regla='1'] button[data-dia-mes='ultimo']")
                    pg.wait_for_function("() => /último día/.test(document.querySelector('.modal [data-cuando-vista]')"
                                         ".textContent)", timeout=10000)
                    pg.click(".modal .pie button:has-text('Cancelar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    # v3.4: «Programar…» de un reporte: editor «Cuándo» y la confirmación con lo que se crearía (no se crea)
                    pg.evaluate("() => { location.hash = '#/editor/%d'; }" % rid)
                    pg.wait_for_selector("#contenido [data-pagina='editor']", timeout=15000)
                    pg.click("#contenido button:has-text('Programar…')")
                    pg.wait_for_selector(".modal [data-modal-programar='reporte'] [data-cuando-proximas]", timeout=15000)
                    pg.click(".modal .pie button.primario")
                    pg.wait_for_selector(".modal [data-confirmar-tarea]", timeout=15000)
                    if "schtasks /Create /XML" not in pg.locator(".modal [data-confirmar-tarea]").inner_text():
                        errores.append("la confirmación de la tarea no muestra el comando schtasks /XML")
                    pg.click(".modal .pie button:has-text('Cancelar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    # v3.4: la página Correo (cuenta + búsqueda con su horario sin tarea), su editor (las cuatro partes,
                    # añadir una acción, el editor «Cuándo») y la ventana de una cuenta IMAP (con la nota de Gmail)
                    pg.evaluate("() => { location.hash = '#/correo'; }")
                    pg.wait_for_selector("#contenido [data-pagina='correo'] .correo-tarjeta [data-tarea-correo='no']",
                                         timeout=15000)
                    if pg.locator("#contenido .correo-cuenta").count() != 1:
                        errores.append("la página Correo no muestra la cuenta")
                    pg.click("#contenido button[data-editar-correo]")
                    pg.wait_for_selector(".modal [data-modal-correo] [data-correo-acciones] .correo-accion", timeout=15000)
                    pg.wait_for_selector(".modal [data-modal-correo] [data-cuando-proximas]", timeout=15000)
                    if pg.locator(".modal .correo-seccion h3").count() != 4:
                        errores.append("el editor de correo no tiene sus 4 partes")
                    pg.click(".modal button[data-anadir-accion]")
                    pg.wait_for_selector(".modal .correo-accion[data-accion='2']", timeout=5000)
                    pg.select_option(".modal select[data-accion-tipo='2']", "tabla")
                    pg.wait_for_selector(".modal .correo-accion[data-accion='2'] input[aria-label='Número de la tabla']",
                                         timeout=5000)
                    pg.click(".modal .pie button:has-text('Cancelar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    pg.click("#contenido button[data-nueva-cuenta]")
                    pg.wait_for_selector(".modal [data-modal-cuenta-correo]", timeout=10000)
                    pg.select_option(".modal select[data-cuenta-proveedor]", "imap")
                    pg.wait_for_function("() => /contraseña de aplicación/.test(document.querySelector("
                                         "'.modal [data-modal-cuenta-correo]').textContent)", timeout=5000)
                    pg.click(".modal .pie button:has-text('Cancelar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    # v3.5: «📁 Elegir…» pone la ruta elegida (diálogo falso) en Ajustes
                    pg.evaluate("() => { location.hash = '#/ajustes'; }")
                    pg.wait_for_selector("#contenido [data-pagina='ajustes'] button[data-elegir='carpeta']", timeout=15000)
                    pg.click("#contenido button[data-elegir='carpeta']")
                    pg.wait_for_function("v => [...document.querySelectorAll('#contenido .campo-ruta input')]"
                                         ".some(i => i.value === v)", arg=elegida, timeout=10000)
                    # v3.5: el editor avisa de la descarga con el nombre de la web y «Usar el nombre del reporte» lo cambia
                    pg.evaluate("() => { location.hash = '#/editor/%d'; }" % rid)
                    pg.wait_for_selector("#contenido [data-aviso-nombres] button[data-usar-nombre-reporte]", timeout=15000)
                    pg.click("#contenido button[data-usar-nombre-reporte]")
                    pg.wait_for_selector("#contenido [data-aviso-nombres].oculto", state="attached", timeout=10000)
                    pg.locator("#contenido tr[data-indice='2'] button:has-text('Editar')").click()
                    pg.wait_for_selector(".modal input[data-nombre-descarga]", timeout=10000)
                    if pg.input_value(".modal input[data-nombre-descarga]") != "{reporte} {hoy:%Y-%m-%d}{ext}":
                        errores.append("«Usar el nombre del reporte» no cambió el nombre de la descarga")
                    pg.click(".modal button[data-nombre-rapido='web']")
                    if pg.input_value(".modal input[data-nombre-descarga]") != "{nombre}{ext}":
                        errores.append("el botón «Nombre que da la web» no funciona")
                    if not pg.locator(".modal .campo-ruta button[data-elegir='carpeta']").count():
                        errores.append("la carpeta del paso «Descargar» no tiene «Elegir…»")
                    pg.click(".modal .pie button:has-text('Cancelar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    # v3.5: «Correos relacionados» con un buzón de prueba: la lista, el más reciente y «Procesar este»
                    pg.evaluate("() => { location.hash = '#/correo'; }")
                    pg.wait_for_selector("#contenido button[data-relacionados-correo]", timeout=15000)
                    pg.click("#contenido button[data-relacionados-correo]")
                    pg.wait_for_selector(".modal [data-modal-relacionados] li[data-correo-relacionado]", timeout=20000)
                    if pg.locator(".modal li[data-correo-relacionado]").count() != 2:
                        errores.append("«Correos relacionados» no muestra los 2 correos del buzón de prueba")
                    if pg.locator(".modal li.mas-reciente").count() != 1:
                        errores.append("«Correos relacionados» no marca el más reciente")
                    pg.click(".modal .pie button:has-text('Cerrar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    # v3.1: el panel «Usar filtros» (desde Reportes) se abre y se cierra sin errores
                    pg.evaluate("() => { location.hash = '#/reportes'; }")
                    pg.wait_for_selector("#contenido [data-pagina='reportes']", timeout=15000)
                    pg.click("#contenido button:has-text('Usar filtros')")
                    pg.wait_for_selector(".modal [data-filtros] .filtro", timeout=15000)
                    pg.wait_for_timeout(250)
                    pg.click(".modal .pie button:has-text('Cerrar')")
                    pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                    # v3.6: el campo de fecha (calendario) de la Página: «Ayer» → «Hace 7 días», el calendario y Esc
                    pg.evaluate("p => { location.hash = '#/paginas/' + p; }", pid)
                    boton_fecha = "#contenido [data-filtro='f4'] button[data-campo-fecha]"
                    pg.wait_for_selector(boton_fecha, timeout=15000)
                    if "Ayer" not in pg.locator(boton_fecha).inner_text():
                        errores.append("el campo de fecha de la Página no dice «Ayer»")
                    pg.click(boton_fecha)
                    pg.wait_for_selector("[data-fecha-pop] [data-fecha-rel='ayer'].activo", timeout=5000)
                    pg.fill("[data-fecha-pop] input[data-fecha-n]", "7")
                    if pg.input_value("#contenido [data-filtro='f4'] input.fecha-texto") != "{dias:-7}":
                        errores.append("«Hace 7 días» del calendario no puso {dias:-7}")
                    pg.click("[data-fecha-pop] [data-fecha-modo='fija']")
                    pg.wait_for_selector("[data-fecha-pop] .cal-dia.hoy", timeout=5000)
                    pg.keyboard.press("Escape")
                    pg.wait_for_selector("[data-fecha-pop]", state="detached", timeout=5000)
                finally:
                    nav.close()
        finally:
            srv.parar()
            alm.cerrar()
        if errores:
            print("ERROR: la interfaz tiene errores en la consola: %s" % "; ".join(errores[:5]), file=sys.stderr)
            return 1
        print("OK: la interfaz web se cargó y se recorrieron todas sus páginas sin errores.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
