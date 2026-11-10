"""v3.4 «Correo»: Outlook en el navegador (Outlook en la web / Microsoft 365: https://outlook.cloud.microsoft/mail/inbox).

Adaptado de Octopus (`data_correo/motor/descargar_reporte.py`), que encontraba UN correo; aquí se recorren todos los
resultados de la búsqueda:

- v3.6: el texto de la búsqueda se PEGA en el buscador (`insert_text`, un solo evento como al pegar; si no lo acepta,
  portapapeles + Ctrl+V; como último recurso se teclea) y se comprueba que quedó entero antes de pulsar Enter.  Antes se
  tecleaba pulsación a pulsación y el combobox de sugerencias de Outlook podía comerse o robarse letras (con `fill()` el
  texto aparece pero Outlook no lanza la búsqueda).  Se busca con el texto COMPLETO (el asunto entero) y, si nada de lo
  que sale vale, una vez más con uno más corto.  Los resultados están listos cuando la dirección pasa a «search» o
  cambian las primeras filas.  Buscar es la forma fiable de llegar al correo: la bandeja
  solo tiene en la página los correos que caben en pantalla.
- Cada fila se lee entera: el texto que se ve + los `title`/`aria-label` (el asunto largo sale recortado en pantalla,
  pero completo en el aria-label).  La fecha real está en el `title` de un elemento interno («Fri 9/11/2026 8:07 AM»;
  en inglés M/D/AAAA y en español D/M/AAAA: se desempata con el día de la semana).
- El identificador de la fila (`data-convid`) es el de la CONVERSACIÓN: por eso la clave del correo procesado lleva
  también la fecha.  Si Outlook agrupa en conversaciones, solo se ve el último correo de cada una (se puede quitar en
  Outlook: Configuración → Correo → Diseño → «Mostrar como mensajes»).
- Los adjuntos son tarjetas `[role=option]` con el nombre en el aria-label («…S.A.S..xlsx Abrir 19 KB»: se corta por
  la extensión, igual en todos los idiomas); cada una se descarga con su menú «Más acciones» → «Descargar» y, si eso
  falla, con «Descargar todo» (un .zip que se descomprime).
- El cuerpo está en `div[aria-label="Cuerpo del mensaje"]` (o «Message body», `UniqueMessageBody…`, `role=document`).

NO VERIFICADO contra el Outlook real desde este equipo (solo contra la página de prueba `tests/sitio_prueba/
correo_outlook.html`, que imita su estructura): si Microsoft cambia la página, puede haber que ajustar los selectores.
"""

import os
import re
import tempfile
import time
from urllib.parse import urlparse

from . import correo
from .correo import ErrorProveedor
from .correo_web import AdaptadorWeb

FILAS = "[data-convid]"
FILAS_RESERVA = '[role="listbox"] [role="option"], [role="grid"] [role="row"]'
CREDENCIALES = ("input[name='loginfmt']:visible", "input[type='email']:visible", "input[type='password']:visible",
                "#displayName:visible")
# v3.6.1: primero lo que NO cambia al escribir.  En el Outlook real el buscador es `input#topSearchInput[role=combobox]`
# y su `placeholder` («Search») DESAPARECE en cuanto tiene texto: buscarlo por el placeholder lo perdía justo después de
# pegar (el bot se quedaba esperando y nunca pulsaba Enter).
BUSCADOR = ("#topSearchInput", "input[role='combobox'][aria-label*='Search']",
            "input[role='combobox'][aria-label*='Buscar']", "input[type='search']",
            "input[aria-label*='Search']", "input[aria-label*='Buscar']",
            "input[placeholder*='Search']", "input[placeholder*='Buscar']")
SELECTORES_CUERPO = ('div[aria-label="Cuerpo del mensaje"]', 'div[aria-label="Message body"]',
                     'div[id^="UniqueMessageBody"]', 'div[role="document"]')
PANEL_LECTURA = "#ReadingPaneContainerId, #ConversationReadingPaneContainer, [aria-label='Panel de lectura'], " \
                "[aria-label='Reading Pane']"
TEXTO_DESCARGAR_TODO = re.compile(r"Descargar todo|Download all", re.I)
TEXTO_DESCARGAR = re.compile(r"^\s*(Download|Descargar)\s*$", re.I)
TEXTO_MOSTRAR_TODO = re.compile(r"Show all|Mostrar todo|Ver todo|Mostrar todos", re.I)

_RX_TITLE_FECHA = re.compile(r"^\s*[A-Za-zÀ-ÿ]{2,4}\.?,?\s+\d{1,2}[/-]\d{1,2}[/-]\d{4}")

_JS_FILAS = r"""(arg) => {
  const sel = arg.sel, reserva = arg.reserva;
  let filas = Array.from(document.querySelectorAll(sel));
  if (!filas.length) filas = Array.from(document.querySelectorAll(reserva));
  const res = [];
  const vistos = new Set();
  for (const el of filas) {
    if (el.closest('[aria-label="Cuerpo del mensaje"], [aria-label="Message body"]')) continue;
    const id = el.getAttribute('data-convid') || el.getAttribute('data-item-id') || el.id || '';
    const clave = id || (el.getAttribute('aria-label') || el.innerText || '').slice(0, 200);
    if (vistos.has(clave)) continue;
    vistos.add(clave);
    const titulos = [];
    const propio = el.getAttribute('aria-label') || el.getAttribute('title');
    if (propio) titulos.push(propio);
    for (const x of el.querySelectorAll('[title],[aria-label]')) {
      const v = x.getAttribute('title') || x.getAttribute('aria-label');
      if (v) titulos.push(v);
    }
    const fechas = titulos.filter((v) => /\d{1,2}[\/-]\d{1,2}[\/-]\d{4}/.test(v));
    const correos = titulos.filter((v) => /@/.test(v));
    const adj = !!el.querySelector('[data-icon-name*="Attach" i], [aria-label*="adjunto" i], [title*="adjunto" i], ' +
                                    '[aria-label*="attachment" i], [title*="attachment" i]');
    res.push({id, texto: (el.innerText || '').trim(), titulos, fechas, correos, adjunto: adj});
  }
  return res;
}"""

_JS_ADJUNTOS = r"""(arg) => {
  const panel = document.querySelector(arg.panel) || document;
  const res = [];
  const vistos = new Set();
  for (const el of panel.querySelectorAll('[role="option"][aria-label]')) {
    if (el.closest('[data-convid]') || el.hasAttribute('data-convid')) continue;
    const aria = el.getAttribute('aria-label') || '';
    const m = /^(.*?\.[A-Za-z0-9]{1,5})(?=\s|$)/.exec(aria.trim());
    if (!m) continue;
    const nombre = m[1].trim();
    if (vistos.has(nombre)) continue;
    vistos.add(nombre);
    const tam = /(\d+(?:[.,]\d+)?\s*(?:KB|MB|GB|bytes|B))\b/i.exec(aria);
    res.push({nombre, tamano: tam ? tam[1] : '', aria});
  }
  return res;
}"""

_JS_LECTURA = r"""(arg) => {
  const panel = document.querySelector(arg.panel) || document;
  let cuerpo = null;
  for (const s of arg.cuerpos) {
    for (const el of panel.querySelectorAll(s)) {
      if (el.offsetParent !== null && (el.innerText || '').trim()) { cuerpo = el; break; }
    }
    if (cuerpo) break;
  }
  const visible = (el) => el && el.offsetParent !== null;
  let asunto = '';
  for (const el of panel.querySelectorAll('[role="heading"]')) {
    if (visible(el) && !el.closest('[data-convid]') && (el.innerText || '').trim()) { asunto = el.innerText.trim(); break; }
  }
  let remitente = '', correo = '', fecha = '';
  for (const el of panel.querySelectorAll('[title],[aria-label]')) {
    if (el.closest('[data-convid]') || (cuerpo && cuerpo.contains(el)) || el.closest('[role="option"]')) continue;
    const v = el.getAttribute('title') || el.getAttribute('aria-label') || '';
    if (!correo && /[\w.+-]+@[\w-]+\.[\w.-]+/.test(v)) {
      correo = (/[\w.+-]+@[\w-]+\.[\w.-]+/.exec(v) || [''])[0];
      remitente = (el.innerText || '').trim() || v;
    }
    if (!fecha && /\d{1,2}[\/-]\d{1,2}[\/-]\d{4}/.test(v)) fecha = v;
  }
  // v3.6.1, Outlook real: el correo abierto tiene «…_SUBJECT», «…_FROM» (solo el NOMBRE: la dirección está en la ficha de
  // contacto) y «…_DATETIME» (la fecha en el texto, no en un title)
  const porId = (fin) => Array.from(document.querySelectorAll('[id$="' + fin + '"]'))
    .filter((el) => visible(el) && !el.closest('[data-convid]') && (el.innerText || '').trim());
  const s = porId('_SUBJECT');
  if (s.length) asunto = s[0].innerText.trim();
  const de = porId('_FROM');
  const de_nombre = de.length ? de[0].innerText.trim() : '';
  if (!remitente && de_nombre) remitente = de_nombre;
  const f = porId('_DATETIME');
  if (f.length) fecha = f[0].innerText.trim();
  return {html: cuerpo ? cuerpo.innerHTML : '', texto: cuerpo ? cuerpo.innerText : '', asunto, remitente, correo, fecha,
          de_nombre, firma: cuerpo ? (cuerpo.innerText || '').slice(0, 300) : ''};
}"""

# v3.6.1: la ficha de contacto que abre Outlook al pasar el ratón por el remitente («Send an email to x@y» / «Work email:
# x@y» / «Enviar un correo electrónico a x@y»…)
_JS_TARJETA = r"""() => {
  const rx = /^(send an email to|enviar (un )?(correo|mensaje)( electr[oó]nico)? a|work email:?|correo( electr[oó]nico)? (del|de) trabajo:?|email:?)\s*([\w.+-]+@[\w-]+\.[\w.-]+)\s*$/i;
  for (const el of document.querySelectorAll('[aria-label],[title]')) {
    for (const v of [el.getAttribute('aria-label'), el.getAttribute('title')]) {
      const m = rx.exec((v || '').trim());
      if (m) return m[m.length - 1];
    }
  }
  return '';
}"""


class AdaptadorOutlook(AdaptadorWeb):
    nombre_proveedor = "Outlook"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._texto_busqueda = None
        self._ultima_firma = None
        self._abierto = None

    # ----------------------------------------------------------------- sesión y bandeja
    def _buscador(self):
        try:
            c = self.pg.get_by_role("searchbox")
            if c.count() > 0:
                return c.first
        except Exception:              # noqa: BLE001
            pass
        for s in BUSCADOR:
            try:
                c = self.pg.locator(s)
                if c.count() > 0:
                    return c.first
            except Exception:          # noqa: BLE001
                continue
        return None

    def bandeja_lista(self):
        try:
            if self.pg.locator(FILAS).count() > 0 or self.pg.locator(FILAS_RESERVA).count() > 0:
                return True
            b = self._buscador()
            return b is not None and b.is_visible()
        except Exception:              # noqa: BLE001
            return False

    def pide_credenciales(self):
        """Solo campos VISIBLES (al entrar, Outlook rebota por login.microsoftonline.com aunque la sesión esté
        guardada: mirar la dirección daría falsos avisos)."""
        return any(self._visible(s) for s in CREDENCIALES)

    # ----------------------------------------------------------------- buscar
    def _huella_lista(self, n=3):
        try:
            filas = self.pg.locator(FILAS)
            if filas.count() == 0:
                filas = self.pg.locator(FILAS_RESERVA)
            trozos = [filas.nth(i).inner_text() for i in range(min(filas.count(), n))]
        except Exception:              # noqa: BLE001
            return ""
        return correo.normalizar(" ".join(trozos))[:200]

    # ----------------------------------------------------------------- v3.6: el texto se PEGA, no se teclea
    def _valor_buscador(self, campo):
        try:
            return campo.input_value(timeout=3000)
        except Exception:              # noqa: BLE001
            try:
                return campo.evaluate("e => e.value !== undefined ? e.value : (e.textContent || '')", timeout=3000)
            except Exception:          # noqa: BLE001
                return None

    @staticmethod
    def _mismo_texto(valor, texto):
        return " ".join(str(valor or "").split()) == " ".join(str(texto or "").split())

    def _vaciar_buscador(self, campo):
        """Clic en el buscador y Ctrl+A, Supr (como una persona; `fill("")` no siempre avisa al combobox)."""
        campo.click(timeout=10000)
        self._esperar(250)
        for tecla in ("Control+A", "Delete"):
            try:
                self.pg.keyboard.press(tecla)
            except Exception:          # noqa: BLE001
                pass
        if self._valor_buscador(campo):
            try:
                campo.fill("")
            except Exception:          # noqa: BLE001
                pass

    def _pegar_portapapeles(self, texto):
        """Pegado de verdad (Ctrl+V) con el portapapeles: se guarda lo que había, se pone el texto, Ctrl+V y se deja el
        portapapeles como estaba.  (Con el navegador oculto, Chrome usa un portapapeles propio, no el de Windows.)
        Devuelve False si el navegador no deja usar el portapapeles."""
        pg = self.pg
        try:
            u = urlparse(pg.url or "")
            if u.scheme in ("http", "https") and u.netloc:
                self.ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="%s://%s" % (u.scheme, u.netloc))
        except Exception:              # noqa: BLE001
            pass
        try:
            previo = pg.evaluate("async () => { try { return await navigator.clipboard.readText(); } "
                                 "catch (e) { return null; } }")
        except Exception:              # noqa: BLE001
            previo = None
        try:
            puesto = pg.evaluate("async (t) => { try { await navigator.clipboard.writeText(t); return true; } "
                                 "catch (e) { return false; } }", texto)
        except Exception:              # noqa: BLE001
            puesto = False
        if not puesto:
            return False
        try:
            pg.keyboard.press("Control+V")
            self._esperar(300)
        finally:
            if previo is not None:
                try:
                    pg.evaluate("async (t) => { try { await navigator.clipboard.writeText(t); } catch (e) {} }", previo)
                except Exception:      # noqa: BLE001
                    pass
            else:
                self.log("  (no se pudo guardar lo que había en el portapapeles: ahora tiene el texto de la búsqueda)")
        return True

    def _escribir_busqueda(self, campo, texto):
        """Pone `texto` en el buscador y COMPRUEBA que quedó entero.  Primero «pegándolo» (`insert_text`: un solo
        evento, como al pegar: el combobox de sugerencias de Outlook no puede comerse letras); si el buscador no lo
        acepta, con el portapapeles y Ctrl+V; y, si nada de eso vale, tecleándolo como antes.  Devuelve cómo se
        puso («pegado», «pegado con Ctrl+V», «tecleado») o None si el buscador nunca quedó con el texto entero."""
        formas = (("pegado", lambda: self.pg.keyboard.insert_text(texto)),
                  ("pegado con Ctrl+V", lambda: self._pegar_portapapeles(texto)),
                  ("tecleado", lambda: campo.type(texto, delay=40)))
        valor = None
        for modo, poner in formas:
            campo = self._buscador() or campo          # (v3.6.1: Outlook puede redibujar el buscador)
            self._vaciar_buscador(campo)
            if poner() is False:
                self.log("  (el navegador no deja usar el portapapeles)")
                continue
            self._esperar(400)
            valor = self._valor_buscador(campo)
            if self._mismo_texto(valor, texto):
                self.log("  buscador: «%s» (%s y comprobado)" % (valor, modo))
                return modo
            self.log("  el buscador quedó con «%s» en vez de «%s»: se prueba de otra forma" % (valor, texto))
        self.log("  ⚠ el buscador no quedó con el texto entero (tiene «%s»): se busca igual" % valor)
        return None

    def _esperar_resultados(self, antes, url_antes, segundos=20):
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            self._esperar(600)
            url = (self.pg.url or "").lower()
            ahora = self._huella_lista()
            if ("search" in url and url != url_antes.lower()) or (ahora and ahora != antes):
                self._esperar(1000)
                return True
        return False

    def _lanzar_busqueda(self, texto, que=""):
        campo = self._buscador()
        if campo is None:
            self.log("No encontré el buscador de Outlook: se mira la bandeja tal cual.")
            return False
        antes = self._huella_lista()
        url_antes = self.pg.url or ""
        self.log("Buscando en Outlook: «%s»%s" % (texto, (" (%s)" % que) if que else ""))
        try:
            modo = self._escribir_busqueda(campo, texto)
            self._esperar(500)
            self.pg.keyboard.press("Enter")
        except Exception as e:         # noqa: BLE001
            raise ErrorProveedor("No se pudo usar el buscador de Outlook: %s" % str(e).splitlines()[0][:120])
        if self._esperar_resultados(antes, url_antes):
            return True
        if modo == "pegado":
            # El texto quedó en el buscador pero Outlook no buscó: se pega de verdad (Ctrl+V) y otra vez Enter
            self.log("Outlook no lanzó la búsqueda con el texto pegado: se prueba con Ctrl+V")
            try:
                campo = self._buscador() or campo
                self._vaciar_buscador(campo)
                if self._pegar_portapapeles(texto) and self._mismo_texto(self._valor_buscador(campo), texto):
                    self._esperar(500)
                    self.pg.keyboard.press("Enter")
                    if self._esperar_resultados(antes, url_antes):
                        return True
            except Exception as e:     # noqa: BLE001
                self.log("  Ctrl+V falló: %s" % str(e).splitlines()[0][:120])
        self.log("La lista no cambió tras buscar; se sigue con lo que hay.")
        return False

    def _leer_filas(self):
        return self.pg.evaluate(_JS_FILAS, {"sel": FILAS, "reserva": FILAS_RESERVA}) or []

    def _desplazar(self):
        try:
            self.pg.evaluate("""(sel) => { const f = document.querySelectorAll(sel);
                if (f.length) f[f.length - 1].scrollIntoView({block: 'end'}); }""", FILAS)
            self._esperar(800)
        except Exception:              # noqa: BLE001
            pass

    def buscar(self, criterios, hoy=None, limite=30):
        """v3.6: se busca con el texto COMPLETO (el asunto entero o lo de «Texto que se escribe en el buscador»); si
        ninguna fila de los resultados cumple la búsqueda, se prueba UNA vez con una versión más corta (hasta la
        primera coma o las 4 primeras palabras: lo que hacía Octopus)."""
        self._comprobar_detener()
        textos = correo.textos_a_buscar(criterios)
        if not textos:
            self._texto_busqueda = None
            return self._resultados(limite)
        res = []
        for k, (texto, que) in enumerate(textos):
            self._comprobar_detener()
            self._texto_busqueda = texto
            self._lanzar_busqueda(texto, que)
            res = self._resultados(limite)
            if k + 1 >= len(textos) or self._alguna_vale(res, criterios, hoy):
                break
            self.log("Outlook: sin resultados que cumplan la búsqueda con «%s»; se prueba con «%s» (%s)"
                     % (texto, textos[k + 1][0], textos[k + 1][1]))
        return res

    @staticmethod
    def _alguna_vale(res, criterios, hoy):
        for m in res:
            try:
                if correo.coincide(m, criterios, hoy, fase="resumen")[0]:
                    return True
            except Exception:          # noqa: BLE001  (criterios sin normalizar: no se reintenta)
                return True
        return False

    def _resultados(self, limite):
        filas, vistos = [], set()
        for _vuelta in range(6):                 # la lista es «virtual»: se baja para que pinte más filas
            nuevas = 0
            for f in self._leer_filas():
                k = f["id"] or f["texto"][:200]
                if k in vistos:
                    continue
                vistos.add(k)
                filas.append(f)
                nuevas += 1
            if len(filas) >= limite or not nuevas:
                break
            self._desplazar()
        res = []
        for f in filas[:limite]:
            fecha = None
            # v3.6.1: primero el title de la fecha de llegada («Sun 11/1/2026 3:30 PM»: día de la semana + fecha), no el
            # aria-label de la fila, que lleva el ASUNTO (y el asunto puede traer otra fecha: «… AL 01/11/2026»)
            fechas = sorted(f["fechas"], key=lambda t: 0 if _RX_TITLE_FECHA.match(t or "") else 1)
            for t in fechas + f["titulos"]:
                fecha = correo.leer_fecha(t)
                if fecha:
                    break
            lineas = [x.strip() for x in f["texto"].splitlines() if x.strip()]
            dire = correo.correo_de(" ".join(f["correos"]))
            res.append({"id": ("outlook:" + f["id"]) if f["id"] else None, "_fila": f["id"], "asunto": "",
                        "remitente": lineas[0] if lineas else "", "remitente_correo": dire, "fecha": fecha,
                        "adjuntos": None, "tiene_adjuntos": True if f["adjunto"] else None,
                        "texto": " ".join([f["texto"]] + f["titulos"])})
        self.log("Outlook: %d fila(s) en la lista de resultados" % len(res))
        return res

    # ----------------------------------------------------------------- abrir un correo
    def _fila(self, m):
        if m.get("_fila"):
            loc = self.pg.locator('[data-convid="%s"]' % m["_fila"].replace('"', '\\"'))
            if loc.count() > 0:
                return loc.first
            return None
        filas = self.pg.locator(FILAS_RESERVA)
        for i in range(filas.count()):
            if correo.normalizar(filas.nth(i).inner_text())[:80] in correo.normalizar(m.get("texto"))[:400]:
                return filas.nth(i)
        return None

    def _lectura(self):
        return self.pg.evaluate(_JS_LECTURA, {"panel": PANEL_LECTURA, "cuerpos": list(SELECTORES_CUERPO)}) or {}

    def _expandir_adjuntos(self):
        try:
            b = self.pg.locator("button:visible, [role='button']:visible").filter(has_text=TEXTO_MOSTRAR_TODO)
            if b.count() > 0:
                b.first.click(timeout=5000)
                self._esperar(800)
        except Exception:              # noqa: BLE001
            pass

    def _adjuntos(self):
        try:
            return self.pg.evaluate(_JS_ADJUNTOS, {"panel": PANEL_LECTURA}) or []
        except Exception:              # noqa: BLE001
            return []

    @staticmethod
    def _firma(lec):
        return (lec.get("asunto"), lec.get("fecha"), lec.get("firma"))

    def abrir(self, m, forzar=False):
        self._comprobar_detener()
        self.pagina_viva()
        if forzar:
            self._ultima_firma = None
        fila = self._fila(m)
        if fila is None and self._texto_busqueda:      # la lista cambió (o se recargó Outlook): se vuelve a buscar
            self._lanzar_busqueda(self._texto_busqueda)
            fila = self._fila(m)
        if fila is None:
            raise ErrorProveedor("No se encuentra el correo en la lista de Outlook (¿se movió o se borró?)")
        try:
            fila.scroll_into_view_if_needed(timeout=5000)
        except Exception:              # noqa: BLE001
            pass
        fila.click(timeout=15000)
        lec = {}
        fin = time.monotonic() + 20
        while time.monotonic() < fin:
            self._esperar(300)
            lec = self._lectura()
            if (lec.get("firma") or lec.get("html")) and self._firma(lec) != self._ultima_firma:
                break
        if not lec.get("html") and not lec.get("texto"):
            raise ErrorProveedor("Outlook no mostró el cuerpo del correo")
        self._ultima_firma = self._firma(lec)
        adjuntos = self._adjuntos()
        espera_adj = time.monotonic() + (8 if m.get("tiene_adjuntos") else 1.5)
        while not adjuntos and time.monotonic() < espera_adj:
            self._esperar(300)
            adjuntos = self._adjuntos()
        self._expandir_adjuntos()
        adjuntos = self._adjuntos() or adjuntos
        self._abierto = m.get("_fila")
        fecha = correo.leer_fecha(lec.get("fecha")) if lec.get("fecha") else None
        if not lec.get("correo"):
            lec["correo"] = self._correo_de_tarjeta()
        remitente = lec.get("remitente") or ""
        if lec.get("correo") and lec["correo"].lower() not in remitente.lower():
            remitente = "%s <%s>" % (remitente, lec["correo"]) if remitente else lec["correo"]
        return {"asunto": lec.get("asunto") or "", "remitente": remitente,
                "remitente_correo": (lec.get("correo") or "").lower(), "fecha": fecha,
                "html": lec.get("html") or "", "texto": lec.get("texto") or "",
                "adjuntos": [{"nombre": a["nombre"], "tamano": a.get("tamano", "")} for a in adjuntos]}

    def _correo_de_tarjeta(self):
        """v3.6.1: el correo abierto solo enseña el NOMBRE del remitente («Ana Pérez»); su dirección está en la ficha
        de contacto que sale al pasar el ratón por el nombre.  Se pasa el ratón, se lee y se quita.  "" si no sale."""
        try:
            nombre = self.pg.locator('[id$="_FROM"] [role="button"]:visible, [id$="_FROM"]:visible').first
            if nombre.count() == 0:
                return ""
            nombre.hover(timeout=5000)
            fin = time.monotonic() + 6
            dire = ""
            while not dire and time.monotonic() < fin:
                self._esperar(400)
                dire = self.pg.evaluate(_JS_TARJETA) or ""
            if dire:
                self.log("  remitente: %s (de su ficha de contacto)" % dire)
            else:
                self.log("  (Outlook no enseñó la dirección del remitente)")
            return dire.lower()
        except Exception as e:         # noqa: BLE001
            self.log("  (no se pudo leer la ficha del remitente: %s)" % str(e).splitlines()[0][:100])
            return ""
        finally:
            try:
                self.pg.mouse.move(2, 2)
                self._esperar(300)
            except Exception:          # noqa: BLE001
                pass

    # ----------------------------------------------------------------- descargar adjuntos
    def _asegurar_abierto(self, m):
        pg = self.pagina_viva()
        if "outlook" not in (pg.url or "") and not self.bandeja_lista():
            self.ir_a_bandeja()
            if self._texto_busqueda:
                self._lanzar_busqueda(self._texto_busqueda)
            self.abrir(m, forzar=True)
        elif not self._adjuntos():
            self.abrir(m, forzar=True)

    def _tarjeta(self, nombre):
        tarjetas = self.pg.locator("[role='option'][aria-label]")
        for k in range(min(tarjetas.count(), 60)):
            t = tarjetas.nth(k)
            try:
                if t.get_attribute("data-convid"):
                    continue
                aria = (t.get_attribute("aria-label") or "").strip()
            except Exception:          # noqa: BLE001
                continue
            if aria.startswith(nombre) or correo.normalizar(aria).startswith(correo.normalizar(nombre)):
                return t
        return None

    def _descargar_tarjeta(self, nombre, carpeta):
        t = self._tarjeta(nombre)
        if t is None:
            self._expandir_adjuntos()
            t = self._tarjeta(nombre)
        if t is None:
            self.log("  no se encuentra la tarjeta del adjunto «%s»" % nombre)
            return None
        mas = t.locator("button[aria-label*='More actions' i], button[aria-label*='acciones' i]")
        try:
            mas.first.scroll_into_view_if_needed(timeout=5000)
            mas.first.click(timeout=6000)
            try:
                self.pg.wait_for_selector("[role='menuitem']:visible", timeout=5000)
            except Exception:          # noqa: BLE001
                self._esperar(800)
        except Exception as e:         # noqa: BLE001
            self.log("  no se pudo abrir el menú del adjunto «%s»: %s" % (nombre, str(e).splitlines()[0][:100]))
            return None
        item = self.pg.locator("[role='menuitem']:visible").filter(has_text=re.compile(r"Download|Descargar", re.I))
        if item.count() == 0:
            self.log("  el menú del adjunto no muestra «Descargar»")
            self._escape()
            return None
        ruta = self.capturar_descarga(lambda: item.first.click(), carpeta, esperado=nombre)
        self._escape()
        return ruta

    def _escape(self):
        for _ in range(2):
            try:
                self.pagina_viva().keyboard.press("Escape")
            except Exception:          # noqa: BLE001
                pass
        self._esperar(300)

    def _descargar_todo(self, carpeta):
        """«Descargar todo»: un .zip con los adjuntos (botón partido: a veces descarga al primer clic y a veces abre un
        menú donde hay que volver a elegir la opción)."""
        boton = self.pg.locator("[data-automationid='splitbuttonprimary']").filter(has_text=TEXTO_DESCARGAR_TODO)
        if boton.count() == 0:
            boton = self.pg.locator("button:visible, [role='button']:visible").filter(has_text=TEXTO_DESCARGAR_TODO)
        if boton.count() == 0:
            self.log("  no aparece el botón «Descargar todo»")
            return None

        def pulsar():
            try:
                boton.first.click(timeout=10000)
            except Exception:          # noqa: BLE001
                boton.first.click(timeout=10000, force=True)
            for _ in range(4):
                item = self.pg.locator("[role='menuitem']:visible").filter(has_text=TEXTO_DESCARGAR_TODO)
                try:
                    if item.count() > 0:
                        item.first.click(timeout=5000)
                        return
                except Exception:      # noqa: BLE001
                    pass
                self._esperar(300)
        return self.capturar_descarga(pulsar, carpeta, esperado=None)

    def descargar(self, m, det, nombres, carpeta):
        res = {}
        self._asegurar_abierto(m)
        for n in nombres:
            self._comprobar_detener()
            ruta = None
            for _intento in range(2):
                try:
                    ruta = self._descargar_tarjeta(n, carpeta)
                except Exception as e:  # noqa: BLE001
                    self.log("  «%s»: %s" % (n, str(e).splitlines()[0][:120] if str(e) else type(e).__name__))
                    ruta = None
                if ruta:
                    break
                self._asegurar_abierto(m)
            if ruta:
                res[n] = ruta
                self.log("  descargado «%s»" % n)
        faltan = [n for n in nombres if n not in res]
        if faltan:
            self.log("  faltan %d adjunto(s): se prueba «Descargar todo»" % len(faltan))
            try:
                self._asegurar_abierto(m)
                z = self._descargar_todo(carpeta)
            except Exception as e:     # noqa: BLE001
                self.log("  «Descargar todo» falló: %s" % (str(e).splitlines()[0][:120] if str(e) else e))
                z = None
            if z and correo.es_zip_valido(z):
                sub = tempfile.mkdtemp(prefix="todo_", dir=carpeta)
                for p in correo.extraer_zip(z, sub):
                    base = os.path.basename(p)
                    for n in faltan:
                        if n not in res and correo.normalizar(base) == correo.normalizar(n):
                            res[n] = p
        return res
