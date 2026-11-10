"""v3.7 «Avisos y vista»: lo que hace una ejecución que lanza una tarea de Windows (línea de comandos) antes, durante y
después de trabajar.

- **Antes** (`--aviso-antes N`): la tarea se lanzó N minutos antes de la hora de verdad (ver
  `programador.disparadores`).  `Seguimiento.esperar_antes` avisa («"PORTAL" se ejecutará en 5 min, a las 12:50»), espera
  hasta la hora de verdad (`horario.siguiente_en`; si no se sabe, N minutos) y se puede cancelar, adelantar («Empezar ya»)
  o pasar a «Ver en vivo» desde la ventanita o la interfaz.
- **Al empezar** (`--avisar-inicio`) y **al terminar** (`--avisar-fin`, con el resultado corto: «terminó bien: 1 archivo»,
  «falló en el paso 5: …», «nada nuevo»): notificaciones de Windows (`avisos.notificar`).
- **Durante**: el progreso («Paso 3 de 8: Clic en …») va a la tabla `en_curso` (lo lee la interfaz abierta y la
  ventanita, `--ventanita`, que se abre en su propio proceso: si tkinter falla o no hay escritorio, la ejecución sigue).
  «Detener» de la ventanita o de la interfaz llega por `en_curso.pedido` y enciende `detener` (el mismo Event que usa el
  ejecutor).

Nada de esto puede tumbar una ejecución: cualquier fallo de la base de datos, de las notificaciones o de la ventanita se
ignora.  Sin playwright ni tkinter.
"""

import datetime as _dt
import os
import subprocess
import threading
import time

from . import avisos, horario

ahora_real = _dt.datetime.now          # (las pruebas los cambian)
dormir_real = time.sleep


def duracion_texto(segundos):
    """«45 s», «1 min 20 s», «1 h 5 min»."""
    s = max(0, int(round(segundos or 0)))
    if s < 60:
        return "%d s" % s
    m, s = divmod(s, 60)
    if m < 60:
        return "%d min %d s" % (m, s) if s else "%d min" % m
    h, m = divmod(m, 60)
    return "%d h %d min" % (h, m) if m else "%d h" % h


def _plural(n, uno, varios):
    return "%d %s" % (n, uno if n == 1 else varios)


def _corto(texto, n=140):
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[:n - 1] + "…"


def resumen_corto(resultados, codigo=0):
    """El resultado en pocas palabras, para la notificación del final y la ventanita: «terminó bien: 1 archivo»,
    «falló en el paso 5: no apareció…», «se detuvo», «nada nuevo», «novedad: «45 - 2026»»…  `resultados` = lo que
    devolvieron el ejecutor (ResultadoEjecucion), una Página (ResultadoPagina), una vigilancia (ResultadoRevision), el
    correo (ResultadoCorreo) o un lote (ResultadoLote), en cualquier mezcla."""
    archivos, nuevas, correos = 0, [], 0
    hay_buscar = False                    # vigilancias / correo: «nada nuevo» si no hubo nada
    for r in resultados or []:
        if getattr(r, "detenido", False):
            return "se detuvo (lo paraste tú)"
        items = getattr(r, "items", None)
        if items is not None and hasattr(r, "resumen") and not hasattr(r, "resultados"):      # lote
            for it in items:
                if getattr(it, "estado", "") == "detenido":
                    return "se detuvo (lo paraste tú)"
                if getattr(it, "estado", "") not in ("ok", ""):
                    return "falló «%s»: %s" % (getattr(it, "nombre", "") or "un reporte", _corto(it.mensaje, 110))
                archivos += len(getattr(it, "archivos", None) or [])
            continue
        if hasattr(r, "procesados") and hasattr(r, "sesion_caducada"):                          # correo
            hay_buscar = True
            if not r.ok:
                return "falló: %s" % _corto(r.error)
            correos += len(r.procesados)
            archivos += len(r.archivos)
            continue
        if hasattr(r, "nuevas") and hasattr(r, "descargas"):                                    # vigilancia
            hay_buscar = True
            if not r.ok:
                return "falló: %s" % _corto(r.error)
            nuevas += list(r.nuevas)
            for _t, d in r.descargas:
                if d is not None and not d.ok:
                    return "novedad «%s», pero la descarga falló: %s" % (_t, _corto(d.error, 100))
                archivos += len(getattr(d, "archivos", None) or []) if d is not None else 0
            continue
        if hasattr(r, "resultados") and hasattr(r, "errores"):                                  # Página
            for _e, x in r.resultados:
                if getattr(x, "detenido", False):
                    return "se detuvo (lo paraste tú)"
                if not x.ok:
                    return _fallo_ejecucion(x)
            if r.errores:
                return "falló: %s" % _corto(r.errores[0])
            archivos += len(r.archivos)
            continue
        if hasattr(r, "paso_fallido"):                                                          # ejecutor
            if not r.ok:
                return _fallo_ejecucion(r)
            archivos += len(r.archivos or [])
    if not resultados:
        return "terminó bien" if codigo == 0 else ("falló" if codigo == 1 else "no se pudo empezar (mira el registro)")
    if codigo not in (0, None) and not nuevas and not archivos:
        return "falló (mira el registro)"
    partes = []
    if nuevas:
        partes.append(("novedad: " if len(nuevas) == 1 else "novedades: ") + ", ".join("«%s»" % t for t in nuevas[:3]))
    if correos:
        partes.append(_plural(correos, "correo procesado", "correos procesados"))
    if archivos:
        partes.append(_plural(archivos, "archivo", "archivos"))
    if not partes:
        return "nada nuevo" if hay_buscar else "terminó bien"
    if nuevas or correos:
        return "; ".join(partes)
    return "terminó bien: " + "; ".join(partes)


def _fallo_ejecucion(r):
    if getattr(r, "paso_fallido", None):
        return "falló en el paso %s: %s" % (r.paso_fallido, _corto(r.error, 120))
    return "falló: %s" % _corto(r.error or "error", 120)


def estado_final(resultados, codigo, detenido=False):
    if detenido or any(getattr(r, "detenido", False) for r in resultados or []):
        return "detenido"
    return "ok" if codigo == 0 else "error"


def abrir_ventanita_proceso(db, fila_id):
    """La ventanita en su propio proceso (`bot.py --ventanita-de N`): si tkinter falla o no hay escritorio, solo se
    pierde la ventanita.  No hace nada en las pruebas."""
    if avisos.avisos_desactivados():
        return False
    from . import RAIZ, programador
    cmd = [programador.ejecutable_python(True), os.path.join(RAIZ, "bot.py"), "--db", db, "--ventanita-de", str(fila_id)]
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except OSError:
        return False


class Seguimiento:
    """Avisos, espera previa y progreso de UNA ejecución sin ventana (la que lanza una tarea de Windows)."""

    def __init__(self, almacen, tipo, nombre, objetivo_id=None, programacion=None, aviso_antes=0, avisar_inicio=False,
                 avisar_fin=False, ventanita=False, visible=False, notificar=None, abrir_ventanita=None, ahora=None,
                 dormir=None, cada=0.5):
        self.almacen = almacen
        self.tipo = tipo
        self.nombre = nombre or "Bot Web"
        self.objetivo_id = objetivo_id
        self.programacion = programacion
        self.aviso_antes = max(0, int(aviso_antes or 0))
        self.avisar_inicio = bool(avisar_inicio)
        self.avisar_fin = bool(avisar_fin)
        self.ventanita = bool(ventanita)
        self.visible = bool(visible)
        self._notificar = notificar or avisos.notificar
        self._abrir = abrir_ventanita or abrir_ventanita_proceso
        self._ahora = ahora or (lambda: ahora_real())
        self._dormir = dormir or (lambda s: dormir_real(s))
        self.cada = cada
        self.detener = threading.Event()
        self.fila = None
        self.resultados = []
        self.paso = 0
        self.total = 0
        self.texto = ""
        self.cancelada = False
        self.estado = ""
        self.resumen = ""
        self._t0 = None
        self._ultima = 0.0
        self._ventanita_abierta = False
        self._hilo = None
        self._fin_hilo = threading.Event()

    # ------------------------------------------------------------- base de datos (nunca lanza)
    def _crear(self, estado, **campos):
        try:
            self.fila = self.almacen.crear_en_curso(tipo=self.tipo, nombre=self.nombre, objetivo_id=self.objetivo_id,
                                                    estado=estado, visible=self.visible, **campos)
        except Exception:          # noqa: BLE001
            self.fila = None

    def _escribir(self, **campos):
        if self.fila is None:
            return
        try:
            self.almacen.actualizar_en_curso(self.fila, **campos)
        except Exception:          # noqa: BLE001
            pass

    def _pedido(self):
        if self.fila is None:
            return ""
        try:
            f = self.almacen.en_curso_id(self.fila)
        except Exception:          # noqa: BLE001
            return ""
        return (f or {}).get("pedido") or ""

    def _aviso(self, titulo, texto):
        try:
            self._notificar(titulo, texto)
        except Exception:          # noqa: BLE001
            pass

    def _abrir_ventanita(self):
        if not self.ventanita or self._ventanita_abierta or self.fila is None:
            return
        self._ventanita_abierta = True
        try:
            self._abrir(self.almacen.ruta, self.fila)
        except Exception:          # noqa: BLE001
            pass

    def _modo(self):
        return "en vivo (se abre el navegador)" if self.visible else "en segundo plano"

    # ------------------------------------------------------------- antes
    def hora_objetivo(self, ahora=None):
        """A qué hora empieza de verdad: la ejecución programada que cae en los próximos N minutos o, si no se sabe,
        dentro de N minutos."""
        ahora = ahora or self._ahora()
        cuando = horario.siguiente_en(self.programacion, ahora, self.aviso_antes) if self.programacion else None
        if cuando is None:
            cuando = ahora + _dt.timedelta(minutes=self.aviso_antes)
        return max(cuando, ahora)

    def esperar_antes(self):
        """Con «Avisarme antes»: avisa, espera hasta la hora y vuelve True (o False si el usuario canceló esta vez)."""
        if self.aviso_antes <= 0:
            return True
        ahora = self._ahora()
        objetivo = self.hora_objetivo(ahora)
        minutos = max(1, int(round((objetivo - ahora).total_seconds() / 60.0)))
        self._crear("esperando", empieza=objetivo.strftime("%Y-%m-%d %H:%M:%S"),
                    texto="Empieza a las %s" % objetivo.strftime("%H:%M"))
        self.estado = "esperando"
        extra = " Puedes cancelarlo en la ventanita del bot." if self.ventanita else ""
        self._aviso("«%s» se ejecutará en %d min, a las %s" % (self.nombre, minutos, objetivo.strftime("%H:%M")),
                    "Se ejecutará %s.%s" % (self._modo(), extra))
        self._abrir_ventanita()
        while True:
            resto = (objetivo - self._ahora()).total_seconds()
            if resto <= 0:
                break
            pedido = self._pedido()
            if pedido in ("cancelar", "detener"):
                self.cancelada = True
                self.estado = "cancelado"
                self.resumen = "cancelada: esta vez no se ejecuta"
                self._escribir(estado="cancelado", resumen=self.resumen, texto="Cancelada: esta vez no se ejecuta",
                               pedido="")
                return False
            if pedido == "ya":
                self._escribir(pedido="")
                break
            if pedido == "en_vivo":
                self.visible = True
                self._escribir(pedido="", visible=True)
            try:
                self._dormir(min(self.cada, resto))
            except KeyboardInterrupt:
                self.cancelada = True
                self._escribir(estado="cancelado", resumen="cancelada", pedido="")
                return False
        return True

    # ------------------------------------------------------------- durante
    def empezar(self):
        self._t0 = time.monotonic()
        self.estado = "en_curso"
        if self.fila is None:
            self._crear("en_curso", texto="Empezando…")
        else:
            try:
                self.almacen.actualizar_en_curso(self.fila, empezar=True, texto="Empezando…", pedido="",
                                                 visible=self.visible, empieza="")
            except Exception:      # noqa: BLE001
                pass
        if self.avisar_inicio:
            self._aviso("«%s» se está ejecutando" % self.nombre,
                        ("En vivo: se abre el navegador." if self.visible else "En segundo plano.") +
                        (" Te aviso cuando termine." if self.avisar_fin else ""))
        self._abrir_ventanita()
        if self.fila is not None and self._hilo is None:
            self._hilo = threading.Thread(target=self._vigilar_pedidos, name="en-curso", daemon=True)
            self._hilo.start()

    def _vigilar_pedidos(self):
        """«Detener» de la ventanita o de la interfaz (columna `pedido`) → `detener` (el ejecutor se para)."""
        try:
            while not self._fin_hilo.wait(self.cada):
                if self._pedido() in ("detener", "cancelar"):
                    self.detener.set()
                    self.texto = "Deteniendo…"
                    self._escribir(pedido="", texto="Deteniendo…")
        finally:
            try:
                self.almacen.liberar_hilo()
            except Exception:      # noqa: BLE001
                pass

    def nuevo_flujo(self, total):
        """Empieza un flujo (un reporte, una ejecución de una Página, la lectura de una vigilancia…) de `total` pasos."""
        self.total = max(0, int(total or 0))
        self.paso = 0
        self._escribir(total=self.total, paso=0)

    def progreso(self, i, estado, texto=""):
        """El `progreso(indice, estado, texto)` del ejecutor (el mismo que usa la interfaz)."""
        if self.detener.is_set():
            return
        if estado == "dia":
            self.texto = texto
        elif i is not None and i >= 0:
            self.paso = min(i + 1, self.total) if self.total else i + 1
            if estado in ("inicio", "espera"):
                self.texto = texto
            elif estado == "error":
                self.texto = "Falló: " + (texto or "")
        ahora = time.monotonic()
        if estado == "espera" and ahora - self._ultima < 1.0:      # (los avisos de espera llegan muy seguidos)
            return
        self._ultima = ahora
        self._escribir(paso=self.paso, texto=self.texto)

    def anotar_log(self, linea):
        """Las líneas del registro solo se enseñan cuando no hay pasos que contar (correo, lote)."""
        if self.total or self.detener.is_set():
            return
        ahora = time.monotonic()
        if ahora - self._ultima < 0.5:
            return
        self._ultima = ahora
        self.texto = _corto(linea, 160)
        self._escribir(texto=self.texto)

    def resultado(self, r):
        self.resultados.append(r)

    # ------------------------------------------------------------- después
    def terminar(self, codigo):
        if self.cancelada:
            return self.resumen
        self._fin_hilo.set()
        if self._hilo is not None:
            self._hilo.join(timeout=3)
        self.estado = estado_final(self.resultados, codigo, self.detener.is_set())
        self.resumen = "se detuvo (lo paraste tú)" if self.estado == "detenido" else resumen_corto(self.resultados, codigo)
        dur = time.monotonic() - self._t0 if self._t0 is not None else 0
        self._escribir(estado=self.estado, resumen=self.resumen, texto=self.resumen[0].upper() + self.resumen[1:],
                       paso=self.total or self.paso, pedido="")
        if self.avisar_fin:
            titulo = {"ok": "«%s» terminó", "detenido": "«%s» se detuvo"}.get(self.estado, "«%s» falló") % self.nombre
            self._aviso(titulo, "%s%s (tardó %s)" % (self.resumen[0].upper(), self.resumen[1:], duracion_texto(dur)))
        return self.resumen


# ----------------------------------------------------------------- desde la línea de comandos
def describir_objetivo(args, almacen):
    """(tipo, nombre, objetivo_id, programación) de lo que va a ejecutar la línea de comandos `args` (para los avisos,
    la ventanita y la interfaz).  Nunca lanza: si algo no existe, un nombre genérico."""
    try:
        if getattr(args, "correo_id", None) or getattr(args, "correos", False):
            ids = list(args.correo_id or [])
            if len(ids) == 1:
                b = almacen.busqueda_correo(ids[0])
                if b is not None:
                    return "correo", "Correo: %s" % b["nombre"], b["id"], b["programacion"]
                return "correo", "Correo %s" % ids[0], ids[0], None
            return "correo", "Búsquedas de correo", None, None
        if getattr(args, "vigilancia_id", None) is not None:
            v = almacen.vigilancia_id(args.vigilancia_id)
            if v is None:
                return "vigilancia", "Vigilancia %s" % args.vigilancia_id, args.vigilancia_id, None
            nombre = "Vigilancia de %s" % v.get("objetivo")
            if v.get("nombre"):
                nombre += " (%s)" % v["nombre"]
            return "vigilancia", nombre, v["id"], v["programacion"]
        if getattr(args, "pagina", None) or getattr(args, "pagina_id", None) is not None:
            ref = args.pagina_id if args.pagina_id is not None else args.pagina
            try:
                pid = almacen.resolver_pagina(ref)
                fila = almacen.obtener_pagina(pid)
            except Exception:      # noqa: BLE001
                pid, fila = None, None
            nombre = (fila or {}).get("nombre") or str(ref)
            if getattr(args, "vigilar", False):
                return "vigilancia", "Vigilancia de %s" % nombre, None, None
            fav = getattr(args, "favorito", None)
            g = almacen.programacion("pagina:%d" % pid + ((":" + fav) if fav else "")) if pid is not None else None
            return "pagina", nombre + ((" — " + fav) if fav else ""), pid, (g or {}).get("programacion")
        if getattr(args, "vigilar", False):
            return "vigilancia", "Vigilancias", None, None
        ids = list(getattr(args, "id", None) or [])
        for n in getattr(args, "reporte", None) or []:
            r = almacen.obtener_por_nombre(n)
            if r is not None:
                ids.append(r["id"])
        if getattr(args, "todos", False):
            return "lote", "Todos los reportes", None, None
        if len(ids) == 1:
            r = almacen.obtener(ids[0])
            g = almacen.programacion("reporte:%d" % ids[0])
            return "reporte", (r or {}).get("nombre") or "Reporte %s" % ids[0], ids[0], (g or {}).get("programacion")
        return "lote", "%d reportes" % len(ids), None, None
    except Exception:              # noqa: BLE001
        return "otro", "Bot Web", None, None


def desde_args(args, almacen, **kw):
    """El Seguimiento de una ejecución por línea de comandos (opciones `--aviso-antes`, `--avisar-inicio`,
    `--avisar-fin`, `--ventanita`, `--visible`)."""
    tipo, nombre, oid, prog = describir_objetivo(args, almacen)
    return Seguimiento(almacen, tipo, nombre, oid, prog, aviso_antes=getattr(args, "aviso_antes", 0) or 0,
                       avisar_inicio=getattr(args, "avisar_inicio", False), avisar_fin=getattr(args, "avisar_fin", False),
                       ventanita=getattr(args, "ventanita", False), visible=bool(getattr(args, "visible", False)), **kw)
