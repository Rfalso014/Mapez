"""v3.4 «Correo»: Gmail en el navegador (https://mail.google.com/mail/u/0/).

- Se busca con la dirección de búsqueda de Gmail: `…/mail/u/0/#search/<operadores>` con `subject:(…)`, `from:(…)`,
  `after:AAAA/MM/DD`, `before:AAAA/MM/DD`, `has:attachment`, `filename:…` y los trozos del cuerpo entre comillas
  (`correo.consulta_gmail`).  Gmail ya filtra casi todo; después se comprueba cada resultado aquí.
- Filas: `tr.zA` (asunto `.bog`, remitente `[email]`, fecha en el `title` de `td.xW span`, hilo
  `[data-legacy-thread-id]`).  Correo abierto: asunto `h2.hP`, remitente `span.gD[email]`, fecha `span.g3[title]`,
  cuerpo `div.a3s`, adjuntos `div.aQH span.aZo` (nombre `.aV3`; botón «Descargar» o, si no, su enlace, que se
  descarga con las cookies de la sesión).
- Sesión caducada = Gmail lleva a accounts.google.com o enseña el campo de correo/contraseña.  El bot nunca escribe la
  contraseña de Google: la primera vez entra el usuario en la ventana visible («Iniciar sesión en el correo»).

NO VERIFICADO contra el Gmail real desde este equipo (solo contra la página de prueba `tests/sitio_prueba/
correo_gmail.html`, que imita su estructura).  Si Google cambia la página, la opción más estable es una cuenta IMAP con
«contraseña de aplicación».
"""

import time
from urllib.parse import quote_plus, urljoin

from . import correo
from .correo import ErrorProveedor
from .correo_web import AdaptadorWeb

CREDENCIALES = ("#identifierId:visible", "input[type='email']:visible", "input[type='password']:visible",
                "input[name='Passwd']:visible")
SIN_RESULTADOS = ("td.TC:visible", "div.TC:visible")

_JS_FILAS = r"""() => {
  const res = [];
  const vistos = new Set();
  for (const tr of document.querySelectorAll('tr.zA')) {
    if (tr.offsetParent === null) continue;            // Gmail deja ocultas las listas de vistas anteriores
    const hilo = tr.querySelector('[data-legacy-thread-id]') || tr.querySelector('[data-thread-id]');
    const id = (hilo && (hilo.getAttribute('data-legacy-thread-id') || hilo.getAttribute('data-thread-id'))) ||
               tr.getAttribute('data-id') || tr.id || '';
    if (vistos.has(id)) continue;
    vistos.add(id);
    const quien = tr.querySelector('[email]');
    const fecha = tr.querySelector('td.xW span[title], td.xW [title], span[title][aria-label]');
    const asunto = tr.querySelector('.bog');
    const adj = tr.querySelector('.brd, .brc, [data-tooltip*="adjunto" i], img.yE, [aria-label*="adjunto" i], [aria-label*="attachment" i]');
    res.push({id, asunto: asunto ? asunto.innerText.trim() : '', email: quien ? quien.getAttribute('email') : '',
              nombre: quien ? (quien.getAttribute('name') || quien.innerText || '').trim() : '',
              fecha: fecha ? (fecha.getAttribute('title') || fecha.innerText || '') : '',
              texto: (tr.innerText || '').trim(), adjunto: !!adj});
  }
  return res;
}"""

_JS_MENSAJE = r"""() => {
  const vis = (el) => el && el.offsetParent !== null;
  const todos = (s) => Array.from(document.querySelectorAll(s)).filter(vis);
  const cuerpos = todos('div.a3s');
  const cuerpo = cuerpos.length ? cuerpos[cuerpos.length - 1] : null;
  const asunto = (todos('h2.hP')[0] || {}).innerText || '';
  const quienes = todos('span.gD[email]');
  const quien = quienes.length ? quienes[quienes.length - 1] : null;
  const fechas = todos('span.g3[title]');
  const fecha = fechas.length ? fechas[fechas.length - 1].getAttribute('title') : '';
  // los adjuntos del ÚLTIMO mensaje del hilo (el que se acaba de recibir)
  let zona = document;
  if (cuerpo) {
    let p = cuerpo;
    for (let i = 0; i < 12 && p && p.parentElement; i++) { p = p.parentElement; if (p.querySelector('div.aQH')) { zona = p; break; } }
  }
  const adjuntos = [];
  for (const el of zona.querySelectorAll('div.aQH span.aZo, span.aZo')) {
    if (!vis(el)) continue;
    let nombre = ((el.querySelector('.aV3') || {}).innerText || '').trim();
    const du = el.getAttribute('download_url') || '';
    if (!nombre && du) nombre = du.split(':')[1] || '';
    const enlace = el.querySelector('a[href]');
    if (nombre && !adjuntos.some((a) => a.nombre === nombre))
      adjuntos.push({nombre, url: du ? du.split(':').slice(2).join(':') : (enlace ? enlace.getAttribute('href') : '')});
  }
  return {asunto: asunto.trim(), email: quien ? quien.getAttribute('email') : '',
          nombre: quien ? (quien.getAttribute('name') || quien.innerText || '').trim() : '', fecha,
          html: cuerpo ? cuerpo.innerHTML : '', texto: cuerpo ? cuerpo.innerText : '', adjuntos,
          firma: asunto + '|' + fecha + '|' + (cuerpo ? cuerpo.innerText.slice(0, 200) : '')};
}"""


class AdaptadorGmail(AdaptadorWeb):
    nombre_proveedor = "Gmail"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._consulta = ""
        self._ultima_firma = None
        self._abierto = None

    def url_bandeja(self):
        u = self.url
        return u if "#" in u else u + "#inbox"

    def url_busqueda(self, consulta):
        return self.url.split("#", 1)[0] + "#search/" + quote_plus(consulta)

    def bandeja_lista(self):
        try:
            if "accounts.google." in (self.pg.url or ""):
                return False
            return (self._visible("tr.zA:visible") or self._visible("div[role='main']:visible")
                    or self._visible("input[name='q']:visible"))
        except Exception:              # noqa: BLE001
            return False

    def pide_credenciales(self):
        return any(self._visible(s) for s in CREDENCIALES) or "accounts.google." in (self.pg.url or "")

    # ----------------------------------------------------------------- buscar
    def _ir_a_busqueda(self):
        pg = self.pagina_viva()
        url = self.url_busqueda(self._consulta)
        self.log("Buscando en Gmail: %s" % self._consulta)
        try:
            pg.goto(url, wait_until="domcontentloaded")
        except Exception as e:         # noqa: BLE001
            raise ErrorProveedor("No se pudo abrir la búsqueda de Gmail: %s" % str(e).splitlines()[0][:120])
        fin = time.monotonic() + 20
        quieto = None
        while time.monotonic() < fin:
            self._comprobar_detener()
            self._esperar(400)
            if self.pide_credenciales() and not self.bandeja_lista():
                self.esperar_bandeja()                  # (lanza ErrorSesion si de verdad pide iniciar sesión)
                pg.goto(url, wait_until="domcontentloaded")
                continue
            if self._visible("tr.zA:visible"):
                self._esperar(600)
                return
            if any(self._visible(s) for s in SIN_RESULTADOS):
                return
            if self._visible("div[role='main']:visible"):
                quieto = quieto or time.monotonic()
                if time.monotonic() - quieto > 5:      # la vista cargó y no hay filas
                    return

    def buscar(self, criterios, hoy=None, limite=30):
        self._comprobar_detener()
        self._consulta = correo.consulta_gmail(criterios, hoy) or "in:inbox"
        self._ir_a_busqueda()
        filas = self.pg.evaluate(_JS_FILAS) or []
        res = []
        for f in filas[:limite]:
            res.append({"id": ("gmail:" + f["id"]) if f["id"] else None, "_fila": f["id"], "asunto": f["asunto"],
                        "remitente": ("%s <%s>" % (f["nombre"], f["email"])) if f["email"] and f["nombre"] else
                        (f["nombre"] or f["email"]), "remitente_correo": (f["email"] or "").lower(),
                        "fecha": correo.leer_fecha(f["fecha"]), "adjuntos": None,
                        "tiene_adjuntos": True if f["adjunto"] else None, "texto": f["texto"]})
        self.log("Gmail: %d resultado(s)" % len(res))
        return res

    # ----------------------------------------------------------------- abrir
    def _fila(self, m):
        if m.get("_fila"):
            for sel in ('tr.zA:has([data-legacy-thread-id="%s"])', 'tr.zA:has([data-thread-id="%s"])',
                        'tr.zA[data-id="%s"]'):
                loc = self.pg.locator(sel % m["_fila"].replace('"', '\\"'))
                try:
                    if loc.count() > 0 and loc.first.is_visible():
                        return loc.first
                except Exception:      # noqa: BLE001
                    continue
        return None

    def abrir(self, m):
        self._comprobar_detener()
        self.pagina_viva()
        fila = self._fila(m)
        if fila is None:
            self._ir_a_busqueda()
            fila = self._fila(m)
        if fila is None:
            raise ErrorProveedor("No se encuentra el correo en los resultados de Gmail (¿se movió o se borró?)")
        objetivo = fila.locator(".bog")
        (objetivo.first if objetivo.count() else fila).click(timeout=15000)
        lec = {}
        fin = time.monotonic() + 20
        while time.monotonic() < fin:
            self._esperar(300)
            lec = self.pg.evaluate(_JS_MENSAJE) or {}
            if (lec.get("html") or lec.get("texto")) and lec.get("firma") != self._ultima_firma:
                break
        if not lec.get("html") and not lec.get("texto"):
            raise ErrorProveedor("Gmail no mostró el cuerpo del correo")
        self._ultima_firma = lec.get("firma")
        self._abierto = (m.get("_fila"), lec.get("adjuntos") or [])
        remitente = ("%s <%s>" % (lec["nombre"], lec["email"])) if lec.get("email") and lec.get("nombre") else (
            lec.get("nombre") or lec.get("email") or "")
        return {"asunto": lec.get("asunto") or "", "remitente": remitente,
                "remitente_correo": (lec.get("email") or "").lower(), "fecha": correo.leer_fecha(lec.get("fecha")),
                "html": lec.get("html") or "", "texto": lec.get("texto") or "",
                "adjuntos": [{"nombre": a["nombre"], "tamano": ""} for a in lec.get("adjuntos") or []]}

    # ----------------------------------------------------------------- descargar
    def _zona_adjunto(self, nombre):
        zonas = self.pg.locator("span.aZo")
        for k in range(min(zonas.count(), 60)):
            z = zonas.nth(k)
            try:
                if not z.is_visible():
                    continue
                t = (z.locator(".aV3").first.inner_text() if z.locator(".aV3").count() else "") or ""
                du = z.get_attribute("download_url") or ""
            except Exception:          # noqa: BLE001
                continue
            if correo.normalizar(t) == correo.normalizar(nombre) or (du and correo.normalizar(nombre) in correo.normalizar(du)):
                return z
        return None

    def descargar(self, m, det, nombres, carpeta):
        res = {}
        if not self._abierto or self._abierto[0] != m.get("_fila"):
            self.abrir(m)
        enlaces = {a["nombre"]: a.get("url") or "" for a in (self._abierto[1] if self._abierto else [])}
        for n in nombres:
            self._comprobar_detener()
            ruta = None
            z = self._zona_adjunto(n)
            if z is not None:
                boton = z.locator("[aria-label*='Descargar' i], [aria-label*='Download' i], [data-tooltip*='Descargar' i], "
                                  "[data-tooltip*='Download' i]")
                if boton.count() > 0:
                    try:
                        z.hover(timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                    ruta = self.capturar_descarga(lambda: boton.first.click(force=True, timeout=10000), carpeta,
                                                  esperado=n, espera=30)
            if not ruta and enlaces.get(n):
                url = urljoin(self.pg.url, enlaces[n])
                ruta = self.bajar_url(url, carpeta, n)
            if ruta:
                res[n] = ruta
                self.log("  descargado «%s»" % n)
            else:
                self.log("  no se pudo descargar «%s»" % n)
        return res
