"""Grabador: abre el navegador, inyecta grabador.js y convierte los eventos en pasos.

Hilos: todo lo de Playwright ocurre en el hilo que llama a `grabar()` (el «hilo de
trabajo»).  Los manejadores de eventos de Playwright solo meten datos en una cola;
el bucle principal los procesa.  Hacia la ventana (Tk) se avisa con `al_evento`,
que debe limitarse a poner el mensaje en una cola.
"""

import concurrent.futures
import os
import queue
import re
import threading
import time
from urllib.parse import urlparse

from . import flujo as mod_flujo
from . import navegador as mod_navegador
from . import plantillas, secretos
from .flujo import Paso, slug

RUTA_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grabador.js")


class ErrorGrabacion(RuntimeError):
    pass


class GrabadorWeb:
    def __init__(self, flujo, carpeta_perfil, navegador="chrome", oculto=False, al_evento=None,
                 hoy=None, fechas_automaticas=False, carpeta_descargas_grabacion=None, agrupar_inicio_sesion=True,
                 accesos=None):
        self.flujo = flujo
        self.carpeta_perfil = carpeta_perfil
        self.navegador = navegador
        self.oculto = oculto
        self.al_evento = al_evento or (lambda tipo, **datos: None)
        self.hoy = hoy
        self.fechas_automaticas = fechas_automaticas
        self.paginas = []               # páginas por orden de aparición (índice = «pagina» del paso)
        self.contexto = None
        self._cola = queue.Queue()      # eventos de Playwright/JS (solo se llenan; se procesan en el bucle)
        self._tareas = queue.Queue()    # funciones pedidas desde otros hilos (pruebas)
        self._parar = threading.Event()
        self._listo = threading.Event()
        self._ultima_descarga = None
        self._t_ultimo = None           # instante (monotonic) del último paso anotado
        self._t_evento = None           # instante en que llegó el evento que se está procesando
        self._por_id = {}               # id del clic (JS) -> Paso, para desactivar los clics de un calendario
        # Inicio de sesión: id(paso) -> {token, rol, clave, host} de los pasos hechos en un formulario de inicio
        # de sesión; al terminar se juntan en un paso «Iniciar sesión» (ver flujo.agrupar_inicio_sesion).
        self.agrupar_inicio_sesion = agrupar_inicio_sesion
        self._meta_login = {}
        # v3.0: los datos de acceso escritos al grabar se guardan solos en «Accesos» (la contraseña ya está en el
        # Administrador de credenciales; aquí solo su nombre)
        self.accesos = accesos
        if carpeta_descargas_grabacion is None:
            from . import RAIZ
            carpeta_descargas_grabacion = os.path.join(RAIZ, "descargas", "grabacion")
        self.carpeta_descargas_grabacion = carpeta_descargas_grabacion

    # ------------------------------------------------------------ API pública
    def detener(self):
        self._parar.set()

    def esperar_listo(self, timeout=60):
        """Bloquea (desde otro hilo) hasta que el navegador está abierto y grabando."""
        return self._listo.wait(timeout)

    def solicitar(self, funcion):
        """Pide ejecutar `funcion(grabador)` en el hilo de trabajo (donde viven los objetos de
        Playwright).  Devuelve un Future.  Sirve para manejar la página en las pruebas."""
        fut = concurrent.futures.Future()
        self._tareas.put((funcion, fut))
        return fut

    def grabar(self, url):
        """Graba hasta que se llame a `detener()`, se pulse «Terminar» o se cierre el navegador."""
        from playwright.sync_api import sync_playwright
        pasos = self.flujo.pasos
        if not pasos or pasos[0].tipo != "abrir_url":
            self._anadir(Paso("abrir_url", url=url))
        try:
            with sync_playwright() as p:
                ctx = mod_navegador.abrir_contexto(p, self.carpeta_perfil, self.navegador, self.oculto)
                self.contexto = ctx
                try:
                    self._preparar(ctx)
                    self.al_evento("estado", texto="Grabando… haz tus pasos en el navegador.")
                    self._abrir(url)
                    self._t_ultimo = time.monotonic()      # la espera aprendida cuenta desde que la página cargó
                    self._listo.set()
                    self._bucle()
                    self._cerrar_grabacion()
                finally:
                    self._listo.set()
                    try:
                        ctx.close()
                    except Exception:
                        pass
        finally:
            self.contexto = None
        self.al_evento("fin", pasos=len(self.flujo.pasos))
        return self.flujo

    # ------------------------------------------------------------ preparación
    def _preparar(self, ctx):
        ctx.expose_binding("__botEvento", self._al_binding)
        ctx.add_init_script(path=RUTA_JS)
        ctx.on("page", self._registrar_pagina)
        for pg in ctx.pages:
            self._registrar_pagina(pg)

    def _registrar_pagina(self, pg):
        self.paginas.append(pg)
        pg.on("download", lambda d, pg=pg: self._cola.put(("descarga", pg, d)))
        pg.on("dialog", lambda dlg: self._aceptar_dialogo(dlg))

    @staticmethod
    def _aceptar_dialogo(dlg):
        try:
            dlg.accept()
        except Exception:
            pass

    def _al_binding(self, origen, ev):
        # No se llama a Playwright aquí: solo se encola.
        self._cola.put(("evento", origen.get("page"), origen.get("frame"), ev, time.monotonic()))

    def _abrir(self, url):
        if not self.paginas:
            self.contexto.new_page()
        pg = self.paginas[0]
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            raise ErrorGrabacion("No se pudo abrir %s: %s" % (url, str(e).splitlines()[0] if str(e) else e)) from e

    # ------------------------------------------------------------------ bucle
    def _paginas_vivas(self):
        return [p for p in self.paginas if not p.is_closed()]

    def _bombear(self, ms=50):
        """Deja que Playwright procese eventos.  False si el navegador ya no existe."""
        for pg in self._paginas_vivas():
            try:
                pg.wait_for_timeout(ms)
                return True
            except Exception:
                continue
        return False

    def _bucle(self):
        while not self._parar.is_set():
            self._vaciar()
            if not self._bombear():
                self.al_evento("estado", texto="Se cerró el navegador.")
                break

    def _cerrar_grabacion(self):
        """Antes de cerrar: envía el valor del campo que se estaba escribiendo y vacía la cola."""
        for pg in self._paginas_vivas():
            for fr in pg.frames:
                try:
                    fr.evaluate("() => window.__botVolcar && window.__botVolcar()")
                except Exception:
                    pass
        for _ in range(6):
            self._vaciar()
            if not self._bombear(40):
                break
        self._vaciar()
        self._agrupar_login()

    def _agrupar_login(self):
        """Junta los pasos del formulario de inicio de sesión (usuario, contraseña, ojito, «Entrar») en uno."""
        if not self.agrupar_inicio_sesion or not self._meta_login:
            return
        info = {k: v for k, v in self._meta_login.items() if v.get("token")}
        nuevos, grupos = mod_flujo.agrupar_inicio_sesion(self.flujo.pasos, self.flujo.url, info=info)
        if grupos:
            self.flujo.pasos[:] = nuevos
            for _a, _b, paso in grupos:
                self.al_evento("estado", texto="Inicio de sesión agrupado en un paso: «%s». Al ejecutar, si ya hay una "
                                               "sesión abierta se omite; si falta la contraseña, se pide." % paso.descripcion())
                self._guardar_accesos(paso)

    def _guardar_accesos(self, paso):
        """Guarda en Accesos los campos del inicio de sesión grabado (usuario, licencia… y el NOMBRE de la contraseña)."""
        from . import accesos as mod_accesos
        if self.accesos is None or not paso.sitio:
            return
        try:
            previos = {a["clave"]: a for a in self.accesos.accesos_de(paso.sitio)}
            cambios = False
            for c in paso.campos:
                clave = c.get("clave") or mod_flujo.clave_de_campo(c.get("selectores"), c.get("etiqueta"))
                if c.get("tipo") == "clave":
                    if not c.get("secreto"):
                        continue
                    cambios = cambios or (previos.get(clave) or {}).get("secreto") != c["secreto"]
                    self.accesos.guardar_acceso(paso.sitio, clave, c.get("etiqueta") or clave, "clave", secreto=c["secreto"],
                                                selectores=c.get("selectores"))
                    secretos.limpiar_rechazo(c["secreto"])
                    marcar = getattr(self.accesos, "marcar_clave_ok", None)
                    if marcar is not None:
                        marcar(c["secreto"], paso.sitio, next((x.get("valor") for x in paso.campos
                                                               if x.get("tipo") != "clave" and x.get("valor")), ""))
                else:
                    try:
                        valor = plantillas.renderizar(c.get("valor") or "", hoy=self.hoy)
                    except plantillas.ErrorPlantilla:
                        valor = c.get("valor") or ""
                    if not valor:
                        continue
                    cambios = cambios or (previos.get(clave) or {}).get("valor") != valor
                    self.accesos.guardar_acceso(paso.sitio, clave, c.get("etiqueta") or clave, "texto", valor=valor,
                                                selectores=c.get("selectores"))
        except Exception as e:          # noqa: BLE001 (no poder guardarlos no debe perder la grabación)
            self.al_evento("estado", texto="No se pudieron guardar los datos de acceso de «%s» (%s)." % (
                paso.sitio, type(e).__name__))
            return
        texto = (mod_accesos.MENSAJE_ACTUALIZADOS if previos and cambios else mod_accesos.MENSAJE_GUARDADOS) % paso.sitio
        if previos and not cambios:
            texto = "Los datos de acceso de «%s» ya estaban guardados" % paso.sitio
        self.al_evento("accesos", host=paso.sitio, texto=texto)
        self.al_evento("estado", texto=texto + " (Accesos).")

    def _anotar_login(self, paso, ev):
        login = ev.get("login")
        if paso is None or not isinstance(login, dict) or not login.get("token"):
            return
        self._meta_login[id(paso)] = {"token": login.get("token"), "rol": login.get("rol") or "",
                                      "clave": bool(ev.get("password")), "host": (login.get("host") or "").lower()}

    def _vaciar(self):
        while True:
            try:
                funcion, fut = self._tareas.get_nowait()
            except queue.Empty:
                break
            try:
                fut.set_result(funcion(self))
            except BaseException as e:  # se devuelve a quien lo pidió
                fut.set_exception(e)
        while True:
            try:
                item = self._cola.get_nowait()
            except queue.Empty:
                break
            try:
                if item[0] == "evento":
                    self._t_evento = item[4] if len(item) > 4 else None
                    self._procesar_evento(item[1], item[2], item[3])
                elif item[0] == "descarga":
                    self._t_evento = None
                    self._procesar_descarga(item[1], item[2])
            except Exception as e:  # un evento raro no debe romper la grabación
                self.al_evento("estado", texto="Aviso: no se pudo registrar una acción (%s)." % type(e).__name__)

    # --------------------------------------------------------------- pasos
    def _anadir(self, paso):
        """Añade un paso y anota cuánto se esperó desde el anterior (espera aprendida)."""
        ahora = self._t_evento if self._t_evento is not None else time.monotonic()
        if self._t_ultimo is not None:
            paso.espera_grabada = round(max(0.0, ahora - self._t_ultimo), 1)
        self._t_ultimo = max(ahora, self._t_ultimo or 0.0)
        self.flujo.pasos.append(paso)
        self.al_evento("paso", indice=len(self.flujo.pasos) - 1, paso=paso)

    def _actualizado(self, paso):
        self.al_evento("paso_actualizado", indice=self.flujo.pasos.index(paso), paso=paso)

    def _indice_pagina(self, pg):
        try:
            return self.paginas.index(pg)
        except ValueError:
            return 0

    def _cadena_marco(self, frame):
        """Selectores de los iframes que contienen al elemento (mejor esfuerzo)."""
        cadena = []
        try:
            f = frame
            while f is not None and f.parent_frame is not None:
                sel = f.frame_element().evaluate("e => window.__botSelector ? window.__botSelector(e) : null")
                if not sel:
                    break
                cadena.insert(0, sel)
                f = f.parent_frame
        except Exception:
            pass
        return cadena

    def _procesar_evento(self, pg, frame, ev):
        tipo = ev.get("tipo")
        if tipo == "terminar":
            self._parar.set()
            return
        pagina = self._indice_pagina(pg)
        marco = self._cadena_marco(frame) if (frame is not None and pg is not None and frame != pg.main_frame) else []
        cands = list(ev.get("candidatos") or [])[:5]
        comunes = dict(pagina=pagina, marco=marco, objetivo=ev.get("objetivo") or "")
        ult = self.flujo.pasos[-1] if self.flujo.pasos else None

        if tipo == "clic":
            if ev.get("doble") and ult is not None and ult.tipo == "clic" and ult.selectores == cands \
                    and not ult.doble and ult.pagina == pagina:
                ult.doble = True      # el navegador envía clic, clic(2): se funden en un doble clic
                self._actualizado(ult)
                return
            previo = self._por_id.get(ev.get("reemplaza")) if ev.get("reemplaza") else None
            if previo is not None and previo is ult and ult.tipo == "clic" and not ult.desactivado \
                    and ult.pagina == pagina:
                # clic en la etiqueta y enseguida en el cuadro del mismo campo: se queda solo el último
                # (si no, al ejecutar rápido la lista se abriría y se volvería a cerrar)
                ult.selectores, ult.objetivo, ult.marco = cands, comunes["objetivo"], marco
                ult.boton, ult.doble = ev.get("boton", "izquierdo"), bool(ev.get("doble"))
                if ev.get("id"):
                    self._por_id[ev["id"]] = ult
                self._anotar_login(ult, ev)
                self._actualizado(ult)
                return
            paso = Paso("clic", selectores=cands, boton=ev.get("boton", "izquierdo"),
                        doble=bool(ev.get("doble")), **comunes)
            self._anotar_login(paso, ev)
            self._anadir(paso)
            if ev.get("id"):
                self._por_id[ev["id"]] = paso
        elif tipo == "pasar_raton":
            if ult is not None and ult.tipo == "pasar_raton" and ult.selectores == cands and ult.pagina == pagina:
                return                # el mismo elemento dos veces seguidas
            nuevo = Paso("pasar_raton", selectores=cands, auto=bool(ev.get("auto")), **comunes)
            self._anotar_login(nuevo, ev)
            self._anadir(nuevo)
            if not ev.get("auto"):
                self.al_evento("estado", texto="Paso «Pasar el ratón» añadido.")
        elif tipo == "escribir":
            self._procesar_escribir(pg, ev, cands, comunes, ult)
        elif tipo == "seleccionar":
            if ult is not None and ult.tipo == "seleccionar" and ult.selectores == cands and ult.pagina == pagina:
                ult.valor, ult.etiqueta = ev.get("valor", ""), ev.get("etiqueta", "")   # cambió de opinión
                self._actualizado(ult)
            else:
                self._anadir(Paso("seleccionar", selectores=cands, valor=ev.get("valor", ""),
                                  etiqueta=ev.get("etiqueta", ""), **comunes))
        elif tipo == "marcar":
            self._anadir(Paso("marcar", selectores=cands, marcado=bool(ev.get("marcado")), **comunes))
        elif tipo == "tecla":
            nuevo = Paso("tecla", selectores=cands, tecla=ev.get("tecla", ""), **comunes)
            self._anotar_login(nuevo, ev)
            self._anadir(nuevo)
        elif tipo == "esperar_elemento":
            self._anadir(Paso("esperar_elemento", selectores=cands, estado=ev.get("estado", "visible"), **comunes))
        elif tipo == "esperar_texto":
            texto, nota = ev.get("texto", ""), ""
            if mod_flujo.texto_volatil(texto, largo_max=None):
                estable = max(mod_flujo.fragmentos_estables(texto) or [""], key=len)
                if len(estable) >= 4:
                    nota = "Se quitó la parte que cambia cada día (fechas, horas…); texto grabado: «%s»." % texto[:120]
                    texto = estable
            self._anadir(Paso("esperar_texto", texto=texto, nota=nota,
                              pagina=pagina))
        elif tipo == "guardar_pagina":
            titulo = re.sub(r"\s+", "_", slug(ev.get("titulo") or "")) if ev.get("titulo") else "Pagina"
            formato = ev.get("formato") if ev.get("formato") in mod_flujo.FORMATOS_PAGINA else "html"
            self._anadir(Paso("guardar_pagina", formato=formato, pagina=pagina,
                              nombre=plantillas.escapar(titulo) + "_{hoy:%Y-%m-%d}"))
            self.al_evento("estado", texto="Paso «Guardar página» (%s) añadido." % formato.upper())

    def _procesar_escribir(self, pg, ev, cands, comunes, ult):
        valor = ev.get("valor", "")
        sonda = Paso("escribir", selectores=cands, objetivo=comunes.get("objetivo", ""))
        if ev.get("password") or sonda.parece_contrasena():
            if valor == "":
                return
            host = urlparse(pg.url if pg is not None else "").hostname or "sitio"
            nombre = "%s:%s" % (host, ev.get("campo") or "clave")
            nota = ""
            try:
                secretos.guardar(nombre, valor)
            except secretos.ErrorSecreto:
                nota = "No se pudo guardar la contraseña automáticamente: guárdala con el nombre «%s»." % nombre
            valor = "{secreto:%s}" % nombre
            ev["valor"] = None          # el valor real no se conserva en ningún sitio
            paso_nuevo = Paso("escribir", selectores=cands, valor=valor, nota=nota, **comunes)
            if ult is not None and ult.tipo == "escribir" and ult.selectores == cands and ult.pagina == comunes["pagina"]:
                ult.valor = valor
                self._anotar_login(ult, ev)
                self._actualizado(ult)
            else:
                self._anotar_login(paso_nuevo, ev)
                self._anadir(paso_nuevo)
            return
        if ev.get("desactivado"):
            # La web puso el valor al elegir una opción de una lista: el clic en la opción ya lo hace.
            self._anadir(Paso("escribir", selectores=cands, valor=plantillas.escapar(valor), desactivado=True,
                              nota=ev.get("nota") or "Valor puesto al elegir una opción de la lista.", **comunes))
            return
        if ult is not None and ult.tipo == "escribir" and ult.selectores == cands and ult.pagina == comunes["pagina"] \
                and not ult.desactivado:
            ult.valor = plantillas.escapar(valor)
            paso = ult
            self._anotar_login(paso, ev)
            self._actualizado(paso)
        else:
            paso = Paso("escribir", selectores=cands, valor=plantillas.escapar(valor), **comunes)
            self._anotar_login(paso, ev)
            self._anadir(paso)
        if ev.get("fecha_directa"):
            # Un calendario puso el valor: se escribe la fecha directamente y los clics del calendario
            # se conservan pero desactivados.
            paso.fecha_directa = True
            ids = set(ev.get("picker_ids") or [])
            if ev.get("apertura_id"):
                ids.add(ev["apertura_id"])
            for pid in ids:
                clic = self._por_id.get(pid)
                if clic is not None and clic in self.flujo.pasos and not clic.desactivado:
                    clic.desactivado = True
                    self._actualizado(clic)
            self._actualizado(paso)
            self.al_evento("estado", texto="Fecha escrita directamente: %s (los clics del calendario quedan desactivados)." % valor)
        sugerida = plantillas.proponer_fecha_dinamica(valor, self.hoy)
        if sugerida:
            if self.fechas_automaticas:
                paso.valor = sugerida
                self._actualizado(paso)
            else:
                self.al_evento("sugerencia", indice=self.flujo.pasos.index(paso), paso=paso,
                               original=valor, plantilla=sugerida)

    def _procesar_descarga(self, pg, descarga):
        """La descarga se deja completar y se guarda en descargas/grabacion/ (así la web se comporta
        con normalidad y se pueden seguir grabando más descargas).  El paso queda como «descargar»."""
        from .ejecutor import nombre_archivo_seguro, ruta_libre
        sugerido = descarga.suggested_filename or "descarga"
        guardado = ""
        try:
            os.makedirs(self.carpeta_descargas_grabacion, exist_ok=True)
            destino = ruta_libre(os.path.join(self.carpeta_descargas_grabacion, nombre_archivo_seguro(sugerido)))
            descarga.save_as(destino)
            if not descarga.failure():
                guardado = destino
        except Exception:
            guardado = ""
        # v3.5: el archivo se llamará como el REPORTE (nombre completo) + la fecha; el nombre que da la web
        # («report_xls», «DetallesVentasMayorista») sigue disponible como {nombre}.  Si el reporte descarga varios
        # archivos, todos llevan además el nombre de la web para no pisarse.
        pasos = self.flujo.pasos
        ult = pasos[-1] if pasos else None
        previas = [p for p in pasos if p.tipo == "descargar" and p is not ult]
        nombre = mod_flujo.nombre_descarga_defecto(varias=bool(previas))
        if previas:
            for p in previas:
                if p.nombre == mod_flujo.NOMBRE_DESCARGA_DEFECTO:
                    p.nombre = mod_flujo.NOMBRE_DESCARGA_VARIAS
                    self._actualizado(p)
        if ult is not None and ult.tipo == "clic":
            ult.tipo = "descargar"
            ult.nombre = nombre
            self._actualizado(ult)
        else:
            self._anadir(Paso("descargar", nombre=nombre, pagina=self._indice_pagina(pg),
                              nota="La descarga empezó sin un clic directo; se espera a que llegue."))
        donde = (" Copia de la grabación: %s" % guardado) if guardado else ""
        self.al_evento("estado", texto="Descarga detectada: %s → se guardará con el nombre del reporte y la fecha "
                                       "(«%s»; el nombre que da la web es {nombre}).%s" % (sugerido, nombre, donde))
