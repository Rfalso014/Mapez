"""v3.4 «Correo»: lo común a los buzones que se usan EN EL NAVEGADOR (Outlook y Gmail): abrir el navegador con el perfil
persistente de la cuenta (`perfiles/correo_<id>`, con la sesión iniciada por el usuario), esperar a que cargue la
bandeja, reconocer la pantalla de inicio de sesión (sesión caducada) y capturar las descargas.

Lo de las descargas y las esperas viene de Octopus (`descargar_reporte.py`), pasado a la API síncrona de Playwright:
- Las descargas se capturan en el CONTEXTO (no en la pestaña): Outlook a veces cierra la pestaña al entregar el archivo.
- Si Playwright no recibe la descarga (el navegador la guardó él mismo en «Descargas» como «GUID.tmp» o con su nombre),
  se busca en esa carpeta lo que apareció DESPUÉS del clic con ese nombre (o un .tmp cuyo tamaño ya no cambia) y se
  recupera (nunca se toca otro archivo de esa carpeta).
- La bandeja se sondea cada 0,4 s; la pantalla de inicio de sesión solo cuenta si sigue ahí unos segundos seguidos (al
  entrar, Outlook enseña un momento su pantalla de cuenta mientras restaura la sesión guardada).

Playwright solo se usa dentro de los métodos (y en el hilo que abrió el adaptador).
"""

import os
import shutil
import time

from . import correo
from . import navegador as mod_navegador
from .correo import ErrorProveedor, ErrorSesion

ESPERA_BANDEJA_S = 90          # lo que puede tardar el buzón en pintar la bandeja
CONFIRMAR_LOGIN = 50           # sondeos seguidos (de 0,4 s) viendo la pantalla de inicio de sesión: ~20 s
ESPERA_DESCARGA_S = 60
TIMEOUT_MS = 30000


def carpeta_descargas_usuario():
    casa = os.path.expanduser("~")
    for nombre in ("Downloads", "Descargas"):
        c = os.path.join(casa, nombre)
        if os.path.isdir(c):
            return c
    return os.path.join(casa, "Downloads")


class AdaptadorWeb:
    """Base de Outlook/Gmail.  Se usa con `with`: abre el navegador y llega a la bandeja (o lanza ErrorSesion)."""

    nombre_proveedor = "el correo"

    def __init__(self, cuenta, perfil, oculto=True, navegador="chrome", log=None, detener=None, esperar_login=0,
                 carpeta_nativa=None):
        self.cuenta = cuenta
        self.perfil = perfil
        self.oculto = bool(oculto)
        self.navegador = navegador or "chrome"
        self._log_fn = log
        self.detener = detener
        self.esperar_login = float(esperar_login or 0)
        self.carpeta_nativa = carpeta_nativa
        self.url = correo.url_de_cuenta(cuenta)
        self._pw = None
        self.ctx = None
        self.pg = None

    # ----------------------------------------------------------------- abrir / cerrar
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self.ctx = mod_navegador.abrir_contexto(self._pw, self.perfil, self.navegador, oculto=self.oculto,
                                                    log=self.log)
        except mod_navegador.ErrorNavegador as e:
            self._pw.stop()
            self._pw = None
            raise ErrorProveedor(str(e))
        self.ctx.set_default_timeout(TIMEOUT_MS)
        self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        try:
            self.ir_a_bandeja()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self.ctx is not None:
                self.ctx.close()
        except Exception:              # noqa: BLE001
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:              # noqa: BLE001
            pass
        self.ctx = self._pw = self.pg = None
        return False

    # ----------------------------------------------------------------- utilidades
    def log(self, linea):
        if self._log_fn:
            try:
                self._log_fn(linea)
            except Exception:          # noqa: BLE001
                pass

    def _comprobar_detener(self):
        if self.detener is not None and self.detener.is_set():
            raise ErrorProveedor("Detenido por el usuario")

    def _esperar(self, ms):
        """Espera dejando que Playwright atienda sus eventos (las descargas llegan así)."""
        try:
            if self.pg is not None and not self.pg.is_closed():
                self.pg.wait_for_timeout(ms)
                return
        except Exception:              # noqa: BLE001
            pass
        time.sleep(ms / 1000.0)

    def pagina_viva(self):
        """Una pestaña viva (Outlook puede cerrar la suya tras una descarga): la actual, otra del contexto o una nueva."""
        try:
            if self.pg is not None and not self.pg.is_closed():
                return self.pg
        except Exception:              # noqa: BLE001
            pass
        vivas = [p for p in self.ctx.pages if not p.is_closed()]
        self.pg = vivas[-1] if vivas else self.ctx.new_page()
        return self.pg

    def _visible(self, selector):
        try:
            return self.pg.locator(selector).count() > 0
        except Exception:              # noqa: BLE001
            return False

    def captura(self, ruta):
        try:
            self.pagina_viva().screenshot(path=ruta, full_page=False)
            return ruta
        except Exception:              # noqa: BLE001
            return ""

    # ----------------------------------------------------------------- la bandeja y la sesión
    def bandeja_lista(self):            # (cada proveedor)
        raise NotImplementedError

    def pide_credenciales(self):        # (cada proveedor)
        raise NotImplementedError

    def url_bandeja(self):
        return self.url

    def ir_a_bandeja(self):
        pg = self.pagina_viva()
        self.log("Abriendo %s (%s)…" % (self.nombre_proveedor, self.url_bandeja()))
        try:
            pg.goto(self.url_bandeja(), wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        except Exception as e:         # noqa: BLE001
            raise ErrorProveedor("No se pudo abrir %s: %s" % (self.url_bandeja(), str(e).splitlines()[0]))
        self.esperar_bandeja()

    def esperar_bandeja(self):
        """Espera a que cargue la bandeja.  Si lo que se ve es el inicio de sesión: con `esperar_login` (ventana visible
        para que entre el usuario) espera hasta ese tiempo; si no, ErrorSesion (la sesión caducó)."""
        fin = time.monotonic() + ESPERA_BANDEJA_S
        aviso = time.monotonic() + 15
        seguidas = 0
        while time.monotonic() < fin:
            self._comprobar_detener()
            if self.bandeja_lista():
                return True
            if self.pide_credenciales():
                seguidas += 1
                if seguidas >= CONFIRMAR_LOGIN:
                    break
            else:
                seguidas = 0
            if time.monotonic() > aviso:
                aviso = time.monotonic() + 15
                self.log("%s sigue cargando…" % self.nombre_proveedor)
            self._esperar(400)
        else:
            raise ErrorProveedor("%s no cargó la bandeja en %d s" % (self.nombre_proveedor, ESPERA_BANDEJA_S))
        if self.esperar_login <= 0:
            raise ErrorSesion("La sesión de «%s» caducó (%s pide iniciar sesión). Abre Correo y pulsa «Iniciar sesión en "
                              "el correo»: entras tú una vez y el bot sigue solo." % (self.cuenta.get("nombre", ""),
                                                                                      self.nombre_proveedor))
        self.log("%s pide iniciar sesión: entra en la ventana que se abrió (el bot espera hasta %d min y nunca escribe "
                 "tu contraseña)." % (self.nombre_proveedor, max(1, int(self.esperar_login // 60))))
        hasta = time.monotonic() + self.esperar_login
        while time.monotonic() < hasta:
            self._comprobar_detener()
            if self.bandeja_lista():
                self.log("Sesión iniciada: la bandeja ya cargó.")
                return True
            self._esperar(1000)
        raise ErrorSesion("No se inició la sesión de «%s» a tiempo (%d min)." % (self.cuenta.get("nombre", ""),
                                                                                 max(1, int(self.esperar_login // 60))))

    # ----------------------------------------------------------------- descargas
    def _nativa(self):
        return self.carpeta_nativa or carpeta_descargas_usuario()

    @staticmethod
    def _listar(carpeta):
        try:
            return {n for n in os.listdir(carpeta) if os.path.isfile(os.path.join(carpeta, n))}
        except OSError:
            return set()

    def capturar_descarga(self, accion, carpeta, esperado=None, espera=ESPERA_DESCARGA_S):
        """Hace `accion()` (el clic) y guarda la descarga en `carpeta` (con el nombre `esperado` si se da, si no el que
        sugiere la web).  Devuelve la ruta o None.  Si Playwright no la recibe, se recupera de la carpeta «Descargas»
        del navegador (solo lo que apareció después del clic)."""
        nativa = self._nativa()
        antes = self._listar(nativa)
        descarga = None
        try:
            with self.ctx.expect_event("download", timeout=espera * 1000) as info:
                accion()
            descarga = info.value
        except Exception as e:         # noqa: BLE001
            self.log("  la descarga no llegó al bot (%s): se mira la carpeta de descargas del navegador"
                     % (str(e).splitlines()[0][:120] if str(e) else type(e).__name__))
        if descarga is not None:
            nombre = correo._limpio(esperado or descarga.suggested_filename or "adjunto") or "adjunto"
            destino = correo._ruta_libre(os.path.join(carpeta, nombre))
            try:
                descarga.save_as(destino)
                return destino
            except Exception as e:     # noqa: BLE001
                self.log("  no se pudo guardar la descarga (%s)" % (str(e).splitlines()[0][:120] if str(e) else e))
                try:
                    p = descarga.path()
                    if p and os.path.exists(p):
                        shutil.copy2(p, destino)
                        return destino
                except Exception:      # noqa: BLE001
                    pass
        return self._recuperar_nativa(nativa, antes, carpeta, esperado, espera=min(30, espera))

    def _recuperar_nativa(self, nativa, antes, carpeta, esperado, espera=30):
        """(De Octopus) la descarga «nativa»: un archivo nuevo con el nombre esperado o un GUID.tmp que deja de crecer."""
        tamanos, iguales = {}, {}
        fin = time.monotonic() + espera
        while time.monotonic() < fin:
            nuevos = [n for n in self._listar(nativa) - antes if not correo.es_descarga_a_medias(n)]
            reales = [n for n in nuevos if not correo.es_tmp_guid(n)
                      and (not esperado or correo.normalizar(n) == correo.normalizar(esperado))]
            if reales:
                origen = os.path.join(nativa, reales[0])
                destino = correo._ruta_libre(os.path.join(carpeta, correo._limpio(esperado or reales[0])))
                try:
                    shutil.move(origen, destino)
                    self.log("  descarga recuperada de «%s»" % origen)
                    return destino
                except OSError as e:
                    self.log("  no se pudo mover «%s»: %s" % (origen, e))
                    return None
            tmps = [n for n in nuevos if correo.es_tmp_guid(n)]
            if tmps and esperado:
                listo = None
                for n in tmps:
                    try:
                        t = os.path.getsize(os.path.join(nativa, n))
                    except OSError:
                        continue
                    iguales[n] = iguales.get(n, 0) + 1 if t == tamanos.get(n) else 0
                    tamanos[n] = t
                    if t > 0 and iguales[n] >= 3:
                        listo = n
                if listo:
                    destino = correo._ruta_libre(os.path.join(carpeta, correo._limpio(esperado)))
                    try:
                        shutil.move(os.path.join(nativa, listo), destino)
                        self.log("  descarga nativa recuperada → %s" % os.path.basename(destino))
                        return destino
                    except OSError:
                        return None
            self._esperar(500)
        return None

    def bajar_url(self, url, carpeta, nombre):
        """Descarga una dirección con las cookies de la sesión (Gmail: el enlace del adjunto)."""
        try:
            r = self.ctx.request.get(url, timeout=TIMEOUT_MS)
            if not r.ok:
                self.log("  la descarga de «%s» respondió %s" % (nombre, r.status))
                return None
            destino = correo._ruta_libre(os.path.join(carpeta, correo._limpio(nombre) or "adjunto"))
            with open(destino, "wb") as f:
                f.write(r.body())
            return destino
        except Exception as e:         # noqa: BLE001
            self.log("  no se pudo descargar «%s»: %s" % (nombre, str(e).splitlines()[0][:120] if str(e) else e))
            return None
