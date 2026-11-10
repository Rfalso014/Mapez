"""«Mapear página / Sacar filtros» (v3.0): encuentra los filtros de una página y los convierte en pasos.

- `escanear(ej, pg, raiz=None)`: con el navegador ya en la página (dentro de `Ejecutor.al_final`), devuelve los filtros:
  pestañas, listas propias (Vuetify, combobox… se abren para leer sus opciones, también las virtuales), listas nativas,
  fechas, textos, casillas y botones de acción (Generar, Buscar, Consultar, Exportar, Descargar…), cada uno con su
  etiqueta, valor actual, opciones, selectores (los mismos que calcula el grabador) y su orden en la página.
- `actualizar_opciones(ej, pg, filtros, k, valor)`: elige `valor` en el filtro k y vuelve a leer las listas que van
  después (listas que dependen de otra: «reporte → corte»).
- `generar_pasos(filtros, elecciones)`: pasos (clic en la pestaña, «Elegir opción», escribir la fecha, marcar, clic en
  «Generar», descargar) a partir de lo que el usuario eligió.
- `comparar(viejo, nuevo)`: qué cambió desde el mapa anterior (filtros y opciones nuevos o quitados).
- `punto_de_mapeo(flujo)`: hasta qué paso se ejecuta un reporte antes de mapear (antes del primer filtro).
- `SesionMapeo`: sesión interactiva (navegador visible) para la interfaz: ejecuta los pasos hasta ese punto y espera
  órdenes («mapear todo», «elegir una parte», «actualizar opciones», «terminar») mientras el usuario puede navegar.

v3.3 (el mapeo solo funcionaba en Portal): se analizan TODOS los marcos (iframes, también de otra web) y cada filtro
lleva `marco` (cadena de iframes) y `pagina` (pestaña), que pasan a los pasos y a las Páginas; se mapea la pestaña que el
usuario está viendo (o la que elija); etiquetas de celdas de tabla, de DevExpress, texto anterior y el name/id legible
(«ctl00$formContent$txtFechaIni» → «Fecha Ini»); listas y fechas de DevExpress, fechas de bootstrap-datepicker, campos con
lupa de búsqueda (`leer_busqueda`), <input type=image>, enlaces con aspecto de botón y opciones de los menús de
DevExpress; un control que falla no estropea el mapa (`errores`); si sale vacío o algo falla, `avisos_del_mapa` explica
por qué y `guardar_diagnostico` deja captura, direcciones, controles (sin contraseñas) y errores en
`registros/mapas/<fecha>_<sitio>/`.  Cada orden de la sesión queda en el registro.

Playwright solo se usa a través del ejecutor, en su hilo de trabajo.
"""

import concurrent.futures
import os
import queue
import re
import threading
import time

from . import flujo as mod_flujo
from . import plantillas
from .flujo import Paso

CARPETA = os.path.dirname(os.path.abspath(__file__))
TIPOS_FILTRO = ("pestana", "lista", "lista_nativa", "fecha", "texto", "casilla", "accion")
NOMBRES_TIPO_FILTRO = {"pestana": "Pestaña", "lista": "Lista", "lista_nativa": "Lista", "fecha": "Fecha",
                       "texto": "Texto", "casilla": "Casilla", "accion": "Botón"}
FECHAS = {"hoy": "{hoy:%s}", "ayer": "{ayer:%s}", "fecha": "{fecha:%s}", "inicio_mes": "{inicio_mes:%s}",
          "fin_mes": "{fin_mes:%s}", "inicio_mes_anterior": "{inicio_mes_anterior:%s}",
          "fin_mes_anterior": "{fin_mes_anterior:%s}"}
RX_ACCION = re.compile(r"^(generar|buscar|consultar|ver reporte|ver informe|exportar|descargar|filtrar|aplicar|procesar|"
                       r"mostrar|ejecutar|search|export|download|apply)\b", re.IGNORECASE)

_script = None


def script_mapeador():
    """Script que se inyecta: los bloques de selectores de grabador.js + mapeador.js (en una función propia)."""
    global _script
    if _script is None:
        with open(os.path.join(CARPETA, "grabador.js"), encoding="utf-8") as f:
            grab = f.read()
        bloques = []
        for n in (1, 2):
            m = re.search(r"// <<selectores-%d[^\n]*\n(.*?)// selectores-%d>>" % (n, n), grab, re.S)
            if not m:
                raise RuntimeError("grabador.js no tiene el bloque de selectores %d" % n)
            bloques.append(m.group(1))
        with open(os.path.join(CARPETA, "mapeador.js"), encoding="utf-8") as f:
            propio = f.read()
        _script = ("(() => {\n'use strict';\nif (window.__botMapear) return true;\n" + "\n".join(bloques) + "\n" + propio +
                   "\nreturn true;\n})()")
    return _script


def instalar(pg):
    pg.evaluate(script_mapeador())


# v3.3: datos del <iframe> (en el documento que lo contiene): posición, si se ve, su selector y si está dentro de la
# parte elegida («Mapear una parte»)
JS_DATOS_IFRAME = r"""(e, raiz) => {
  const r = e.getBoundingClientRect();
  const cs = getComputedStyle(e);
  let dentro = true;
  if (raiz) { try { const z = document.querySelector(raiz); dentro = !!z && z.contains(e); } catch (x) { dentro = true; } }
  let sel = window.__botSelectorDe ? window.__botSelectorDe(e) : null;
  if (!sel && e.id) sel = '#' + CSS.escape(e.id);
  if (!sel && e.getAttribute('name')) sel = 'iframe[name="' + e.getAttribute('name').replace(/"/g, '\\"') + '"]';
  return { x: Math.round(r.left + scrollX), y: Math.round(r.top + scrollY), selector: sel, dentro,
           visible: r.width > 2 && r.height > 2 && cs.visibility !== 'hidden' && cs.display !== 'none' };
}"""
MAX_PROFUNDIDAD_MARCOS = 4
CARPETA_DIAGNOSTICOS = "mapas"


class ErrorMapeo(RuntimeError):
    """El mapeo no se pudo hacer (con el motivo en español y, si se guardó, la carpeta del diagnóstico)."""

    def __init__(self, mensaje, diagnostico=""):
        super().__init__(mensaje + ((" (diagnóstico en %s)" % diagnostico) if diagnostico else ""))
        self.diagnostico = diagnostico


def _primera(e):
    t = str(e).strip().splitlines()
    return (t[0] if t else type(e).__name__)[:200]


def _scope(pg, marco):
    """La página o el marco (cadena de iframes) donde está un filtro."""
    s = pg
    for m in marco or []:
        s = s.frame_locator(m)
    return s


def marcos(pg, raiz=None, errores=None, marco_raiz=None):
    """[(frame, cadena de selectores de los iframes, (dx, dy))]: el documento principal y sus marcos visibles (también
    los de otra web: Playwright los ve todos).  Los que no se pueden leer van a `errores`.  `raiz` (la parte elegida)
    está en el documento del marco `marco_raiz` (v3.8; vacío = el principal): ahí solo se siguen los iframes de dentro."""
    errores = errores if errores is not None else []
    marco_raiz = list(marco_raiz or [])
    res = []

    def recorrer(fr, cadena, off, nivel):
        res.append((fr, cadena, off))
        if nivel >= MAX_PROFUNDIDAD_MARCOS:
            return
        for hijo in list(fr.child_frames):
            try:
                if hijo.is_detached():
                    continue
                el = hijo.frame_element()
                try:
                    fr.evaluate(script_mapeador())
                except Exception:      # noqa: BLE001 (sin el script se usa el id o el name del iframe)
                    pass
                d = el.evaluate(JS_DATOS_IFRAME, raiz if (raiz and cadena == marco_raiz) else None)
            except Exception as e:     # noqa: BLE001
                errores.append({"marco": hijo.url or "(marco sin dirección)",
                                "error": "no se pudo leer el marco: " + _primera(e)})
                continue
            if not d.get("visible") or not d.get("dentro"):
                continue
            if not d.get("selector"):
                errores.append({"marco": hijo.url, "error": "no se pudo leer el marco: sin selector para el iframe"})
                continue
            recorrer(hijo, cadena + [d["selector"]], (off[0] + d["x"], off[1] + d["y"]), nivel + 1)
    recorrer(pg.main_frame, [], (0, 0), 0)
    return res


def escanear(ej, pg, raiz=None, leer_listas=True, segundos_por_lista=20, detalle=False, pagina=0, marco_raiz=None):
    """Filtros de la página (o de la parte `raiz`, un selector CSS) y de TODOS sus marcos (iframes).  Abre cada lista
    propia para leer sus opciones (y la cierra con Escape).  Cada filtro lleva `marco` (cadena de iframes) y `pagina`
    (pestaña).  Un control o un marco que falla no estropea el mapa: va a `errores`.  v3.8: si la parte está dentro de
    un iframe (`marco_raiz`, como en el ERP), solo se mira ese marco (la parte) y los iframes que hay dentro de ella.

    Devuelve la lista de filtros o, con `detalle`, {filtros, errores, marcos, infos, avisos}."""
    errores, infos, lista_marcos, filtros = [], [], [], []
    base = 0
    marco_raiz = list(marco_raiz or []) if raiz else []
    for fr, cadena, off in marcos(pg, raiz, errores, marco_raiz):
        if cadena[:len(marco_raiz)] != marco_raiz:
            continue                   # fuera del marco de la parte elegida
        nombre_marco = " > ".join(cadena) if cadena else "documento principal"
        try:
            fr.evaluate(script_mapeador())
            r = fr.evaluate("a => window.__botMapear(a)", {"raiz": raiz if cadena == marco_raiz else None, "base": base})
        except Exception as e:         # noqa: BLE001
            errores.append({"marco": nombre_marco, "url": fr.url, "error": "no se pudo leer el marco: " + _primera(e)})
            lista_marcos.append({"marco": list(cadena), "url": fr.url, "ok": False, "error": _primera(e), "filtros": 0})
            continue
        r = r if isinstance(r, dict) else {"filtros": r or [], "errores": [], "info": {}}
        for f in r.get("filtros") or []:
            f["marco"] = list(cadena)
            f["pagina"] = int(pagina or 0)
            f["x"] = int(f.get("x") or 0) + off[0]
            f["y"] = int(f.get("y") or 0) + off[1]
            if cadena:
                f["url_marco"] = fr.url
            filtros.append(f)
        base += len(r.get("filtros") or [])
        for e in r.get("errores") or []:
            errores.append(dict(e, marco=nombre_marco))
        infos.append(dict(r.get("info") or {}, marco=list(cadena)))
        lista_marcos.append({"marco": list(cadena), "url": fr.url, "ok": True, "filtros": len(r.get("filtros") or [])})
    _marcar_fuera_del_reporte(filtros)
    filtros.sort(key=lambda f: (f.get("y", 0), f.get("x", 0)))
    for i, f in enumerate(filtros):
        f["orden"] = i
        f.setdefault("opciones", None)
    for f in filtros:
        if f["tipo"] == "lista" and leer_listas and not f.get("opciones") and not f.get("secundario"):
            _leer_lista(ej, pg, f, segundos_por_lista)
            if f.get("error"):
                errores.append({"control": f.get("etiqueta") or "lista %d" % f["k"], "error": f["error"]})
    res = {"filtros": filtros, "errores": errores, "marcos": lista_marcos, "infos": infos}
    res["avisos"] = avisos_del_mapa(res, pg)
    return res if detalle else filtros


GRUPO_FUERA = "De la web, fuera del reporte"


def _marcar_fuera_del_reporte(filtros):
    """v3.8: si un documento (o marco) solo aporta textos sueltos (el buscador general de la web, en la barra de
    arriba) y otro marco trae el formulario (3 o más filtros), los del primero son secundarios: no se traen solos.
    En una página de un solo documento no cambia nada."""
    por_marco = {}
    for f in filtros:
        por_marco.setdefault(tuple(f.get("marco") or []), []).append(f)
    if len(por_marco) < 2:
        return
    principales = [m for m, fs in por_marco.items() if len([f for f in fs if not f.get("secundario")]) >= 3]
    if not principales:
        return
    for m, fs in por_marco.items():
        if m in principales or len(fs) > 3:
            continue
        if all(f.get("tipo") in ("texto", "accion") for f in fs) and any(f.get("tipo") == "texto" for f in fs):
            for f in fs:
                f["secundario"] = True
                f["grupo"] = GRUPO_FUERA


def extractos_html(pg):
    """v3.8: {k: trozo de HTML alrededor del filtro} de todos los marcos (sin valores ni contraseñas), para el
    diagnóstico."""
    res = {}
    try:
        for fr, _cadena, _off in marcos(pg, None, []):
            try:
                fr.evaluate(script_mapeador())
                res.update(fr.evaluate("() => window.__botExtractos ? window.__botExtractos() : {}") or {})
            except Exception:          # noqa: BLE001
                continue
    except Exception:                  # noqa: BLE001
        pass
    return res


def avisos_del_mapa(res, pg=None):
    """Por qué el mapa salió vacío o incompleto, en español (para la interfaz y el registro)."""
    avisos = []
    infos = res.get("infos") or []
    principal = next((i for i in infos if not i.get("marco")), {})
    fallidos = [e for e in res.get("errores") or [] if str(e.get("error", "")).startswith("no se pudo leer el marco")]
    if not res.get("filtros"):
        url = principal.get("url") or ""
        if not url and pg is not None:
            try:
                url = pg.url
            except Exception:          # noqa: BLE001
                url = ""
        titulo = principal.get("titulo") or ""
        controles = sum(int(i.get("controles") or 0) for i in infos)
        if any(i.get("clave") for i in infos):
            pass                       # (el aviso del inicio de sesión va abajo)
        elif principal and principal.get("listo") not in (None, "complete"):
            avisos.append("La página todavía se está cargando: espera a que termine y vuelve a pulsar «Mapear».")
        elif controles == 0:
            avisos.append("No se encontró ningún control de formulario (listas, campos, casillas ni botones) en «%s» (%s). "
                          "¿Es la página de los filtros? Si abriste el reporte en otra pestaña, elígela en «Pestaña»."
                          % (titulo or "la página", url))
        else:
            avisos.append("La página tiene %d controles pero ninguno parece un filtro visible (están ocultos o no se "
                          "reconocen). Revisa el diagnóstico o prueba «Mapear una parte…»." % controles)
    if any(i.get("clave") for i in infos):
        avisos.insert(0, "Parece la página de inicio de sesión (hay un campo de contraseña): inicia sesión en el navegador, "
                         "ve hasta la página de los filtros y vuelve a pulsar «Mapear».")
    if fallidos:
        avisos.append("No se pudieron leer %d marco(s) (iframes) de la página: %s" % (
            len(fallidos), "; ".join("%s (%s)" % (e.get("url") or e.get("marco"), e.get("error")) for e in fallidos[:3])))
    malos = [e for e in res.get("errores") or [] if e.get("control")]
    if malos:
        avisos.append("%d control(es) no se pudieron analizar del todo (se siguió con los demás): %s" % (
            len(malos), "; ".join("%s: %s" % (e["control"], str(e.get("error"))[:80]) for e in malos[:3])))
    return avisos


def guardar_diagnostico(pg, res, carpeta_registros, pestanas=None, motivo="", log=None):
    """v3.3: deja en `registros/mapas/<fecha>_<sitio>/` lo necesario para saber por qué un mapa salió mal: captura de
    pantalla, direcciones de las pestañas y los marcos, un resumen de los controles de cada documento (nunca el valor
    de un campo de contraseña) y la lista de errores.  Devuelve la carpeta (o "" si no se pudo)."""
    import datetime
    import json
    try:
        url = pg.url if pg is not None else ""
    except Exception:                  # noqa: BLE001
        url = ""
    host = mod_flujo.slug(mod_flujo.host_de(url) or "pagina") or "pagina"
    base = os.path.join(carpeta_registros, CARPETA_DIAGNOSTICOS,
                        "%s_%s" % (datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"), host))
    carpeta, n = base, 2
    while os.path.exists(carpeta):
        carpeta = "%s_%d" % (base, n)
        n += 1
    try:
        os.makedirs(carpeta, exist_ok=True)
    except OSError:
        return ""
    controles, errores_diag = [], []
    if pg is not None:
        try:
            pg.screenshot(path=os.path.join(carpeta, "captura.png"), timeout=10000)
        except Exception as e:         # noqa: BLE001
            errores_diag.append("captura: " + _primera(e))
        try:
            for fr, cadena, _off in marcos(pg, None, []):
                try:
                    fr.evaluate(script_mapeador())
                    d = fr.evaluate("() => window.__botResumenControles()")
                    d["marco"] = cadena
                    controles.append(d)
                except Exception as e:  # noqa: BLE001
                    controles.append({"marco": cadena, "url": fr.url, "error": _primera(e)})
        except Exception as e:         # noqa: BLE001
            errores_diag.append("marcos: " + _primera(e))
    res = res or {}
    extractos = extractos_html(pg) if pg is not None and res.get("filtros") else {}
    filtros = [{k: f.get(k) for k in ("k", "tipo", "etiqueta", "marco", "selectores", "error", "dx", "secundario", "grupo",
                                      "doble") if k in f}
               for f in res.get("filtros") or []]
    for f in filtros:
        if str(f.get("k")) in extractos:
            f["html"] = extractos[str(f.get("k"))]
    datos = {"cuando": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "motivo": motivo, "url": url,
             "pestanas": pestanas or [], "marcos": res.get("marcos") or [], "errores": res.get("errores") or [],
             "avisos": res.get("avisos") or [], "filtros": filtros, "controles": controles,
             "errores_del_diagnostico": errores_diag}
    try:
        with open(os.path.join(carpeta, "diagnostico.json"), "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=1)
        lineas = ["Diagnóstico de «Mapear página» (%s)" % datos["cuando"], "", "Motivo: %s" % (motivo or "-"),
                  "Dirección: %s" % url, "", "Pestañas:"]
        lineas += ["  %s %s — %s" % ("*" if p.get("activa") else " ", p.get("indice"), p.get("url")) for p in pestanas or []]
        lineas += ["", "Marcos (iframes):"]
        lineas += ["  %s %s — %s%s" % ("OK " if m.get("ok") else "MAL", " > ".join(m.get("marco") or []) or "(principal)",
                                       m.get("url"), (" — " + m["error"]) if m.get("error") else "")
                   for m in datos["marcos"]]
        lineas += ["", "Avisos:"] + ["  - " + a for a in datos["avisos"]]
        lineas += ["", "Errores:"] + ["  - %s: %s" % (e.get("control") or e.get("marco") or "", e.get("error"))
                                      for e in datos["errores"]]
        lineas += ["", "Filtros encontrados: %d" % len(filtros),
                   "Controles por documento: " + ", ".join(str(c.get("total", "?")) for c in controles),
                   "", "Detalle completo en diagnostico.json (no incluye contraseñas)."]
        with open(os.path.join(carpeta, "LEEME.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lineas) + "\n")
    except OSError:
        pass
    if log:
        log("    diagnóstico del mapa guardado en %s" % carpeta)
    return carpeta


def _loc(pg, f):
    return _scope(pg, f.get("marco")).locator('[data-bot-mapa="%d"]' % int(f["k"])).first


def _leer_lista(ej, pg, f, segundos=20):
    scope = _scope(pg, f.get("marco"))
    loc = _loc(pg, f)
    f.pop("error", None)
    try:
        f["opciones"] = ej.leer_opciones(pg, scope, loc, time.monotonic() + segundos, cerrar=True)
    except Exception as e:             # noqa: BLE001 (una lista que no se abre no debe estropear el mapa)
        f["opciones"] = []
        f["error"] = "No se pudo leer la lista (%s)" % (str(e).splitlines()[0][:120] if str(e) else type(e).__name__)
        try:
            ej._cerrar_lista(pg, loc)
        except Exception:              # noqa: BLE001
            pass


JS_CERRAR_BUSQUEDA = r"""() => {
  const vis = (e) => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  for (const b of document.querySelectorAll('.modal.in .close, .modal.show .close, [data-dismiss=modal], [data-bs-dismiss=modal], ' +
      '[role=dialog] [aria-label=Close], [role=dialog] [aria-label=Cerrar], .ui-dialog-titlebar-close, .dxpc-closeBtn, .btn-close')) {
    if (vis(b)) { b.click(); return true; }
  }
  return false;
}"""


def leer_busqueda(ej, pg, f, segundos=10):
    """v3.3: pulsa la lupa del campo «con búsqueda» (p. ej. «Cuenta No.» de Informes), lee las filas de la ventanita que
    se abre (como opciones del filtro) y la cierra.  Las filas quedan en `f["busqueda"]["filas"]`."""
    scope = _scope(pg, f.get("marco"))
    b = f.get("busqueda") or {}
    boton = scope.locator('[data-bot-busca="%d"]' % int(f["k"])).first
    if not boton.count():
        boton = next((scope.locator(s).first for s in b.get("selectores") or [] if scope.locator(s).count()), None)
    if boton is None:
        raise ErrorMapeo("No se encontró el botón de búsqueda de «%s»" % (f.get("etiqueta") or "el campo"))
    boton.click(timeout=8000)
    fin = time.monotonic() + segundos
    r = {"filas": []}
    raiz = scope.locator(":root").first
    while time.monotonic() < fin:
        ej._pausa(0.3)
        try:
            r = raiz.evaluate("() => window.__botLeerBusqueda ? window.__botLeerBusqueda() : null") or r
        except Exception:              # noqa: BLE001
            continue
        if r.get("filas"):
            break
    try:
        pg.keyboard.press("Escape")
        ej._pausa(0.3)
        raiz.evaluate(JS_CERRAR_BUSQUEDA)
    except Exception:                  # noqa: BLE001
        pass
    filas = [list(x) for x in r.get("filas") or []]
    if not filas:
        raise ErrorMapeo("La búsqueda de «%s» no mostró ninguna tabla con filas" % (f.get("etiqueta") or "el campo"))
    f["busqueda"] = dict(b, filas=filas[:300], tabla=r.get("tabla") or "")
    f["opciones"] = [opcion_de_fila(x) for x in filas[:300]]
    return f


def opcion_de_fila(celdas):
    """Texto de una fila de la búsqueda como opción: «1110209 · Asociacion Ejemplo»."""
    return " · ".join(str(c) for c in list(celdas)[:3] if str(c).strip())


def actualizar_opciones(ej, pg, filtros, k, valor):
    """Elige `valor` en el filtro `k` (lista propia o nativa) y vuelve a leer las listas que van después en la página
    (sus opciones pueden depender de esta)."""
    f = next((x for x in filtros if int(x["k"]) == int(k)), None)
    if f is None or f["tipo"] not in ("lista", "lista_nativa"):
        raise ValueError("Ese filtro no es una lista")
    loc = _loc(pg, f)
    scope = _scope(pg, f.get("marco"))
    fin = time.monotonic() + 30
    if f["tipo"] == "lista_nativa":
        loc.select_option(label=valor, timeout=10000)
    else:
        ej._abrir_lista(pg, scope, loc, fin)
        ej._pulsar_opcion(pg, scope, loc, valor, fin)
    f["valor"] = valor
    ej._esperar_carga(pg, minimo=0.3, forzar=True)
    for g in filtros:
        if g["orden"] <= f["orden"]:
            continue
        if g["tipo"] == "lista" and not g.get("dx"):
            _leer_lista(ej, pg, g)
        elif g["tipo"] == "lista_nativa":
            try:
                g["opciones"] = [t for t in _loc(pg, g).evaluate(
                    "s => Array.from(s.options).filter((o) => !o.disabled).map((o) => (o.text || '').replace(/\\s+/g, ' ').trim())")
                    if t]
            except Exception:          # noqa: BLE001
                pass
    return filtros


def con_pestana(filtros, pagina):
    """Copia de los filtros con otra pestaña (p. ej. 0 cuando la Página abre directamente la dirección a la que el
    usuario llegó a mano en otra pestaña)."""
    res = []
    for f in filtros or []:
        g = dict(f)
        g["pagina"] = int(pagina)
        res.append(g)
    return res


def detectar_dependencias(ej, pg, filtros, ks=None, max_listas=8):
    """v3.2 «Detectar dependencias»: elige otra opción en cada lista y vuelve a leer las que van después; si sus opciones
    cambian, dependen de ella.  Al terminar deja cada lista como estaba (si tenía valor).  Devuelve
    {dependencias: {k_hijo: [k_padre…]}, lecturas: [{k, opciones, padres: {k: valor}}], filtros}."""
    listas = sorted([f for f in filtros if f["tipo"] in ("lista", "lista_nativa")], key=lambda f: f["orden"])
    if ks:
        listas = [f for f in listas if int(f["k"]) in {int(k) for k in ks}]
    deps, lecturas = {}, []
    for f in listas[:max_listas]:
        siguientes = [g for g in listas if g["orden"] > f["orden"]]
        ops = [o for o in (f.get("opciones") or []) if o]
        if not siguientes or len(ops) < 2:
            continue
        original = f.get("valor") or ""
        antes = {int(g["k"]): list(g.get("opciones") or []) for g in siguientes}
        otra = next((o for o in ops if o != original), None)
        if otra is None:
            continue
        try:
            actualizar_opciones(ej, pg, filtros, f["k"], otra)
        except Exception as e:         # noqa: BLE001 (una lista que no se deja elegir no estropea las demás)
            f["error"] = "No se pudo elegir «%s» (%s)" % (otra[:40], str(e).splitlines()[0][:100] if str(e) else type(e).__name__)
            continue
        padres = {int(x["k"]): x.get("valor") for x in listas if x["orden"] <= f["orden"] and x.get("valor")}
        for g in siguientes:
            nuevas = list(g.get("opciones") or [])
            lecturas.append({"k": int(g["k"]), "opciones": nuevas, "padres": dict(padres)})
            if nuevas != antes[int(g["k"])]:
                deps.setdefault(int(g["k"]), []).append(int(f["k"]))
        if original:
            try:
                actualizar_opciones(ej, pg, filtros, f["k"], original)
            except Exception:          # noqa: BLE001
                pass
    return {"dependencias": deps, "lecturas": lecturas, "filtros": filtros}


JS_EMPEZAR_PARTE = """a => { window.__botParteRes = undefined;
  window.__botElegirParte(a).then((r) => { window.__botParteRes = r || null; }); return true; }"""
JS_LEER_PARTE = "() => window.__botParteRes === undefined ? 'pendiente' : window.__botParteRes"
JS_CANCELAR_PARTE = "() => { if (window.__botCancelarParte) window.__botCancelarParte(); return true; }"


def elegir_parte(pg, segundos=300, pausa=0.25):
    """El usuario elige con el ratón el contenedor que quiere mapear.  Devuelve {selector, descripcion, marco} o None.

    v3.8: el selector se instala en el documento principal Y en cada iframe visible: en el ERP los filtros están dentro
    de un iframe, y el ratón sobre un iframe no llega al documento de fuera (antes no se resaltaba nada, el clic no hacía
    nada y el bot esperaba 5 minutos).  El primero que elige (o Esc, que cancela) gana; a los demás se les quita."""
    activos = []
    for fr, cadena, _off in marcos(pg):
        try:
            fr.evaluate(script_mapeador())
            fr.evaluate(JS_EMPEZAR_PARTE, {"aviso": not cadena})
            activos.append((fr, cadena))
        except Exception:              # noqa: BLE001 (un marco que no se deja: se sigue con los demás)
            continue
    if not activos:
        raise ErrorMapeo("No se pudo preparar la página para elegir una parte")
    resultado = None
    limite = time.monotonic() + segundos
    try:
        while time.monotonic() < limite:
            hecho = False
            for fr, cadena in activos:
                try:
                    r = fr.evaluate(JS_LEER_PARTE)
                except Exception:      # noqa: BLE001 (el marco se fue o recargó)
                    continue
                if r == "pendiente":
                    continue
                hecho = True
                if isinstance(r, dict) and r.get("selector"):
                    resultado = dict(r, marco=list(cadena))
                break
            if hecho:
                break
            pg.wait_for_timeout(int(pausa * 1000))
    finally:
        for fr, _cadena in activos:
            try:
                fr.evaluate(JS_CANCELAR_PARTE)
            except Exception:          # noqa: BLE001
                pass
    return resultado


# ------------------------------------------------------------------ pasos
def formato_fecha(f):
    """Formato strftime del campo de fecha: por su tipo (date → AAAA-MM-DD) o por el valor que tenía."""
    tipo = (f.get("tipo_campo") or "").lower()
    if tipo == "date":
        return "%Y-%m-%d"
    if tipo == "datetime-local":
        return "%Y-%m-%dT00:00"
    if tipo == "month":
        return "%Y-%m"
    v = (f.get("valor") or "").strip()
    for patron, formato in ((r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"), (r"\d{2}/\d{2}/\d{4}", "%d/%m/%Y"),
                            (r"\d{2}-\d{2}-\d{4}", "%d-%m-%Y"), (r"\d{4}/\d{2}/\d{2}", "%Y/%m/%d"),
                            (r"\d{2}\.\d{2}\.\d{4}", "%d.%m.%Y")):
        if re.fullmatch(patron, v):
            return formato
    return "%d/%m/%Y"


def paso_de_filtro(f, e=None):
    """Paso para un filtro (`e` = lo que eligió el usuario: estrategia/valor, fecha/formato, marcado, modo/nombre)."""
    e = e or {}
    sels = list(f.get("selectores") or [])
    nombre = f.get("etiqueta") or ""
    if mod_flujo.etiqueta_generica(nombre):       # v3.1: nunca «Open»/«Abrir»/iconos como nombre
        nombre = ""
    t = f["tipo"]
    donde = {"pagina": int(f.get("pagina") or 0), "marco": list(f.get("marco") or [])}   # v3.3: pestaña y marco
    paso = _paso_de_filtro(f, e, t, sels, nombre)
    paso.pagina, paso.marco = donde["pagina"], donde["marco"]
    return paso


def _paso_de_filtro(f, e, t, sels, nombre):
    if t == "pestana":
        return Paso("clic", selectores=sels, objetivo=nombre)
    if t in ("lista", "lista_nativa"):
        est = e.get("estrategia") or "fija"
        valor = e.get("valor")
        if valor is None or (est in ("fija", "contiene") and not str(valor).strip()):
            valor = plantillas.escapar(f.get("valor") or "") if est in ("fija", "contiene") else ""
        if est == "por_fecha":                    # v3.8: la plantilla de la fecha, como en los campos de fecha
            error = plantillas.validar(valor or "")
            if error:
                raise ErrorMapeo("La fecha de «%s» no es válida: %s" % (nombre, error))
        return Paso("elegir_opcion", selectores=sels, objetivo=nombre, estrategia=est, filtro=nombre,
                    valor=(valor or "") if est in ("fija", "contiene", "por_fecha") else "")
    if t == "fecha":
        cual = e.get("fecha") or "hoy"
        formato = e.get("formato") or formato_fecha(f)
        if cual == "plantilla" and str(e.get("valor") or "").strip():
            # v3.6: lo que sale del calendario de la interfaz, tal cual («15/10/2026», «{ayer:%d/%m/%Y}», «{dias:-7}»)
            error = plantillas.validar(e["valor"])
            if error:
                raise ErrorMapeo("La fecha de «%s» no es válida: %s" % (nombre, error))
            valor = str(e["valor"]).strip()
        elif cual == "fija" or cual == "plantilla":
            valor = plantillas.escapar(e.get("valor") if e.get("valor") is not None else (f.get("valor") or ""))
        else:
            valor = FECHAS.get(cual, "{hoy:%s}") % formato
        return Paso("escribir", selectores=sels, objetivo=nombre, valor=valor, fecha_directa=True, filtro=nombre)
    if t == "texto":
        valor = e.get("valor") if e.get("valor") is not None else plantillas.escapar(f.get("valor") or "")
        return Paso("escribir", selectores=sels, objetivo=nombre, valor=valor)
    if t == "casilla":
        return Paso("marcar", selectores=sels, objetivo=nombre,
                    marcado=bool(e.get("marcado", f.get("marcado", True))))
    if t == "accion":
        modo = e.get("modo") or ("descargar" if f.get("descarga") else "clic")
        if modo == "descargar":
            return Paso("descargar", selectores=sels, objetivo=nombre,
                        nombre=e.get("nombre") or mod_flujo.NOMBRE_DESCARGA_DEFECTO)    # v3.5: el nombre del reporte
        return Paso("clic", selectores=sels, objetivo=nombre)
    raise ValueError("Tipo de filtro desconocido: %s" % t)


def generar_pasos(filtros, elecciones, con_filtros=False):
    """Pasos para los filtros elegidos.  `elecciones`: [{k, ...}] (solo los que se traen).  Primero las pestañas, luego
    los filtros en el orden de la página y al final los botones (Generar, Descargar…)."""
    por_k = {int(e["k"]): e for e in elecciones or [] if e.get("k") is not None}
    elegidos = [f for f in filtros if int(f["k"]) in por_k]
    clave = {"pestana": 0, "accion": 2}
    # v3.8: el botón que descarga va el último, aunque en la página esté antes que «Consultar» (ERP: Exportar | Consultar)
    def _descarga(f):
        e = por_k[int(f["k"])]
        return f["tipo"] == "accion" and (e.get("modo") or ("descargar" if f.get("descarga") else "clic")) == "descargar"
    elegidos.sort(key=lambda f: (clave.get(f["tipo"], 1) + (1 if _descarga(f) else 0), f.get("orden", 0)))
    pares = [(paso_de_filtro(f, por_k[int(f["k"])]), f) for f in elegidos]
    pares = [(p, f) for p, f in pares if not p.sin_valor()]      # v3.8: lo que se dejó vacío no genera ningún paso
    pasos = [p for p, _f in pares]
    elegidos = [f for _p, f in pares]
    if pasos:
        pasos[0].nota = "Creado con «Mapear página»."
    if con_filtros:
        return pasos, list(elegidos)
    return pasos


def opciones_para_cache(pasos, filtros_usados, desde):
    """v3.1: [(índice del paso en el reporte, opciones, padres)] de las listas generadas desde el mapa (`desde` = índice
    del primer paso generado; `filtros_usados` = los filtros del mapa de cada paso, en el mismo orden).  `padres` = el
    valor que tenía cada lista anterior en el mapa (con el que se leyeron sus opciones)."""
    res = []
    padres = {}
    for n, f in enumerate(filtros_usados):
        i = desde + n
        if pasos[n].tipo != "elegir_opcion":
            continue
        if f.get("opciones"):
            res.append((i, list(f["opciones"]), dict(padres)))
        if f.get("valor"):
            padres[i] = f["valor"]
    return res


def aplicar_pasos(flujo, nuevos, hasta, modo="reemplazar"):
    """Pone los pasos generados en el reporte a partir del paso `hasta`: «reemplazar» quita los que había desde ahí;
    «anadir» los inserta en ese punto (conservando los demás)."""
    hasta = max(0, min(int(hasta if hasta is not None else len(flujo.pasos)), len(flujo.pasos)))
    if modo == "anadir":
        flujo.pasos = flujo.pasos[:hasta] + list(nuevos) + flujo.pasos[hasta:]
    else:
        flujo.pasos = flujo.pasos[:hasta] + list(nuevos)
    return flujo


def punto_de_mapeo(flujo):
    """Índice del primer paso que toca un filtro (lista, fecha, casilla, «Generar»…): se ejecuta el reporte hasta
    justo antes (así se mapea la página con la sesión ya iniciada y en la pantalla de los filtros)."""
    pasos = flujo.pasos
    abridores = {i for i, _j, _t in mod_flujo.pares_lista_opcion(pasos)}
    for k, p in enumerate(pasos):
        if p.desactivado:
            continue
        if p.tipo in ("elegir_opcion", "seleccionar", "marcar", "escribir", "descargar", "guardar_pagina") or k in abridores:
            return k
        if p.tipo == "clic" and (RX_ACCION.match(p.objetivo or "") or mod_flujo.es_clic_en_opcion(p)
                                 or any(s.startswith("role=tab") for s in p.selectores)):
            return k
    return len(pasos)


def comparar(viejo, nuevo):
    """Diferencias entre dos mapas (listas de filtros): {nuevos, quitados, opciones: [{etiqueta, nuevas, quitadas}]}."""
    def clave(f):
        return (f.get("tipo") if f.get("tipo") != "lista_nativa" else "lista", (f.get("etiqueta") or "").lower())
    antes = {clave(f): f for f in viejo or []}
    ahora = {clave(f): f for f in nuevo or []}
    res = {"nuevos": [ahora[k]["etiqueta"] for k in ahora if k not in antes],
           "quitados": [antes[k]["etiqueta"] for k in antes if k not in ahora], "opciones": []}
    for k, f in ahora.items():
        if k in antes and f.get("opciones") is not None and antes[k].get("opciones") is not None:
            a, b = antes[k]["opciones"], f["opciones"]
            nuevas = [o for o in b if o not in a]
            quitadas = [o for o in a if o not in b]
            if nuevas or quitadas:
                res["opciones"].append({"etiqueta": f.get("etiqueta"), "nuevas": nuevas, "quitadas": quitadas})
    return res


# ------------------------------------------------------- sesión interactiva
JS_ESTADO_PESTANA = "() => [document.visibilityState, document.hasFocus(), document.title || '']"


class SesionMapeo:
    """Sesión de mapeo para la interfaz.  `crear_ejecutor(flujo, **extra)` crea el Ejecutor (visible, con pedir_acceso…).

    El hilo de trabajo ejecuta el reporte hasta `hasta` y luego atiende órdenes (`pedir(orden, **datos)` → Future):
    «mapear» {alcance: todo|parte, selector, pestana}, «pestanas» (v3.3), «elegir_parte», «actualizar» {k, valor},
    «dependencias» {ks} (v3.2), «busqueda» {k} (v3.3), «terminar».  Mientras tanto el usuario puede navegar a mano en el
    navegador (también abrir el reporte en otra pestaña).

    v3.3: se mapea la pestaña que el usuario está viendo (la que tiene el foco o se ve; si no se sabe, la última que se
    abrió o navegó), o la que elija en la interfaz; también los marcos (iframes).  Si el mapa sale vacío o algo falla, se
    explica por qué y se guarda un diagnóstico en `registros/mapas/`; cada orden queda en el registro de la sesión."""

    def __init__(self, flujo, crear_ejecutor, hasta=None, al_evento=None):
        self.flujo = flujo
        self.hasta = hasta
        self.crear_ejecutor = crear_ejecutor
        self.al_evento = al_evento or (lambda tipo, datos=None: None)
        self._ordenes = queue.Queue()
        self.listo = threading.Event()
        self.terminada = threading.Event()
        self.filtros = []
        self.url = ""
        self.url_inicio = ""
        self.pestana = 0              # v3.3: pestaña (índice) del último mapa
        self.resultado = None
        self.error = ""
        self._hilo = None
        self._actividad = {}          # id(página) -> última vez que se abrió o navegó
        self._pg_mapa = None

    def iniciar(self):
        self._hilo = threading.Thread(target=self._trabajo, name="mapeador", daemon=True)
        self._hilo.start()
        return self

    def _trabajo(self):
        try:
            ej = self.crear_ejecutor(self.flujo, hasta=self.hasta, al_final=self._sesion)
            self.resultado = ej.ejecutar()
            if not self.resultado.ok:
                self.error = self.resultado.resumen()
        except Exception as e:         # noqa: BLE001
            self.error = "%s: %s" % (type(e).__name__, e)
        finally:
            self.listo.set()
            self.terminada.set()
            while True:                # las órdenes que quedaran pendientes
                try:
                    _o, _d, fut = self._ordenes.get_nowait()
                except queue.Empty:
                    break
                if not fut.done():
                    fut.set_exception(RuntimeError("La sesión de mapeo terminó"))
            self.al_evento("fin", {"error": self.error})

    def pedir(self, orden, **datos):
        fut = concurrent.futures.Future()
        if self.terminada.is_set():
            fut.set_exception(RuntimeError("La sesión de mapeo ya terminó" + ((": " + self.error) if self.error else "")))
            return fut
        self._ordenes.put((orden, datos, fut))
        return fut

    # ---------------------------------------------------------- pestañas
    @staticmethod
    def _abiertas(ej):
        res = []
        for i, pg in enumerate(ej.paginas):
            try:
                if not pg.is_closed():
                    res.append((i, pg))
            except Exception:          # noqa: BLE001
                continue
        return res

    @staticmethod
    def _pagina(ej):
        abiertas = SesionMapeo._abiertas(ej)
        return abiertas[-1][1] if abiertas else None

    def _seguir_pestanas(self, ej):
        """Apunta cuándo se abre o navega cada pestaña (para saber cuál está usando el usuario)."""
        for _i, pg in self._abiertas(ej):
            if id(pg) in self._actividad:
                continue
            self._actividad[id(pg)] = time.monotonic()

            def navego(fr, pg=pg):
                try:
                    if fr == pg.main_frame:
                        self._actividad[id(pg)] = time.monotonic()
                except Exception:      # noqa: BLE001
                    pass
            try:
                pg.on("framenavigated", navego)
            except Exception:          # noqa: BLE001
                pass

    def pestanas(self, ej):
        """[{indice, url, titulo, visible, foco, activa}]: las pestañas abiertas; `activa` = la que se mapearía."""
        self._seguir_pestanas(ej)
        res = []
        for i, pg in self._abiertas(ej):
            d = {"indice": i, "url": "", "titulo": "", "visible": False, "foco": False, "activa": False,
                 "actividad": self._actividad.get(id(pg), 0)}
            try:
                d["url"] = pg.url
                vis, foco, titulo = pg.evaluate(JS_ESTADO_PESTANA)
                d.update(visible=vis == "visible", foco=bool(foco), titulo=(titulo or "")[:120])
            except Exception:          # noqa: BLE001 (navegando, o con un aviso abierto)
                pass
            res.append(d)
        if res:
            util = [d for d in res if d["url"] and not d["url"].startswith(("about:", "chrome-error:"))] or res
            mejor = max(util, key=lambda d: (d["foco"], d["visible"], d["actividad"], d["indice"]))
            mejor["activa"] = True
        for d in res:
            d.pop("actividad", None)
        return res

    def _elegir_pagina(self, ej, indice=None):
        """(índice, página) que se mapea: la pedida o la que el usuario está viendo."""
        abiertas = dict(self._abiertas(ej))
        if not abiertas:
            return None, None
        if indice not in (None, ""):
            indice = int(indice)
            if indice not in abiertas:
                raise ErrorMapeo("La pestaña %d ya no está abierta: vuelve a elegir la pestaña" % (indice + 1))
            return indice, abiertas[indice]
        lista = self.pestanas(ej)
        activa = next((d for d in lista if d["activa"]), None)
        i = activa["indice"] if activa else max(abiertas)
        return i, abiertas[i]

    def _pagina_del_mapa(self, ej):
        pg = self._pg_mapa
        try:
            if pg is not None and not pg.is_closed():
                return pg
        except Exception:              # noqa: BLE001
            pass
        return self._pagina(ej)

    # ---------------------------------------------------------- órdenes
    def _mapear(self, ej, datos):
        raiz = datos.get("selector") if datos.get("alcance") == "parte" else None
        marco_raiz = list(datos.get("marco") or []) if raiz else []     # v3.8: la parte elegida dentro de un iframe
        indice, pg = self._elegir_pagina(ej, datos.get("pestana"))
        if pg is None:
            raise ErrorMapeo("No hay ninguna pestaña abierta en el navegador del mapeo")
        pestanas = self.pestanas(ej)
        url = pg.url
        ej._log("Mapear %s: pestaña %d de %d — %s" % (
            "una parte (%s%s)" % (raiz, (" en el marco " + " > ".join(marco_raiz)) if marco_raiz else "") if raiz
            else "toda la página", indice + 1, len(pestanas), url))
        try:
            ej._esperar_carga(pg, minimo=0, forzar=True)
        except Exception as e:         # noqa: BLE001 (si no se puede esperar, se mapea igual)
            if type(e).__name__ == "Detenido":
                raise
        try:
            res = escanear(ej, pg, raiz=raiz, detalle=True, pagina=indice, marco_raiz=marco_raiz)
        except Exception as e:         # noqa: BLE001
            if type(e).__name__ == "Detenido":
                raise
            res = {"filtros": [], "errores": [{"marco": "documento principal", "error": _primera(e)}], "marcos": [],
                   "infos": [], "avisos": ["No se pudo analizar la página: %s" % _primera(e)]}
            ej._log("    ERROR al mapear: %s" % _primera(e))
            carpeta = guardar_diagnostico(pg, res, ej.carpeta_registros, pestanas, "error al mapear", log=ej._log)
            raise ErrorMapeo("No se pudo mapear la página: %s" % _primera(e), carpeta)
        self.filtros = res["filtros"]
        self.url = url
        self.pestana = indice
        self._pg_mapa = pg
        n_marcos = len([m for m in res["marcos"] if m.get("marco")])
        en_marcos = len([f for f in self.filtros if f.get("marco")])
        ej._log("    %d elemento(s) encontrados (%s)%s; %d marco(s) leído(s)%s" % (
            len(self.filtros), ", ".join("%d %s" % (n, t) for t, n in _contar_tipos(self.filtros)) or "ninguno",
            (", %d dentro de marcos" % en_marcos) if en_marcos else "", n_marcos,
            ("; %d error(es)" % len(res["errores"])) if res["errores"] else ""))
        for a in res["avisos"]:
            ej._log("    aviso: %s" % a)
        carpeta = ""
        secundarios = [f for f in self.filtros if f.get("secundario")]
        if not self.filtros or res["errores"] or res["avisos"] or len(self.filtros) >= 15 or secundarios:
            # v3.8: también con muchos filtros o con secundarios, para comparar lo detectado con la web real
            carpeta = guardar_diagnostico(pg, res, ej.carpeta_registros, pestanas,
                                          "mapa vacío" if not self.filtros else ("errores al mapear" if res["errores"]
                                                                                 else (res["avisos"][0] if res["avisos"] else
                                                                                       "revisión: %d filtros, %d secundarios" % (
                                                                                           len(self.filtros), len(secundarios)))),
                                          log=ej._log)
        return {"filtros": self.filtros, "url": url, "pestana": indice, "pestanas": pestanas,
                "errores": res["errores"], "avisos": res["avisos"], "marcos": res["marcos"], "diagnostico": carpeta}

    def _sesion(self, ej, pg):
        self._seguir_pestanas(ej)
        pg = self._pagina(ej) or pg
        self.url = pg.url if pg is not None else ""
        self.url_inicio = self.url          # v3.2: si al mapear la dirección es otra, el usuario navegó a mano
        self.listo.set()
        self.al_evento("listo", {"url": self.url})
        while True:
            pg = self._pagina(ej)
            if pg is None:
                ej._log("Mapear: se cerró el navegador.")
                self.al_evento("estado", {"texto": "Se cerró el navegador."})
                return self.filtros
            try:
                orden, datos, fut = self._ordenes.get_nowait()
            except queue.Empty:
                self._seguir_pestanas(ej)
                ej._comprobar_detener()
                ej._pausa(0.2)
                continue
            if orden == "terminar":
                ej._log("Mapear: sesión terminada (%d elemento(s) en el último mapa)." % len(self.filtros))
                fut.set_result(self.filtros)
                return self.filtros
            try:
                if orden == "mapear":
                    fut.set_result(self._mapear(ej, datos))
                elif orden == "pestanas":
                    fut.set_result({"pestanas": self.pestanas(ej)})
                elif orden == "elegir_parte":
                    _i, pgp = self._elegir_pagina(ej, datos.get("pestana"))
                    fut.set_result(elegir_parte(pgp or pg))
                elif orden == "actualizar":
                    pgm = self._pagina_del_mapa(ej)
                    actualizar_opciones(ej, pgm, self.filtros, datos["k"], datos["valor"])
                    fut.set_result({"filtros": self.filtros, "url": pgm.url})
                elif orden == "dependencias":
                    pgm = self._pagina_del_mapa(ej)
                    r = detectar_dependencias(ej, pgm, self.filtros, ks=datos.get("ks"))
                    r["url"] = pgm.url
                    fut.set_result(r)
                elif orden == "busqueda":
                    pgm = self._pagina_del_mapa(ej)
                    f = next((x for x in self.filtros if int(x["k"]) == int(datos["k"])), None)
                    if f is None or not f.get("busqueda"):
                        raise ErrorMapeo("Ese filtro no tiene botón de búsqueda")
                    leer_busqueda(ej, pgm, f)
                    ej._log("Mapear: búsqueda de «%s»: %d fila(s)" % (f.get("etiqueta"), len(f.get("opciones") or [])))
                    fut.set_result({"filtros": self.filtros, "url": pgm.url})
                else:
                    fut.set_exception(ValueError("Orden desconocida: %s" % orden))
            except BaseException as e:   # noqa: BLE001 (se devuelve a quien la pidió)
                if not fut.done():
                    fut.set_exception(e)
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                if type(e).__name__ == "Detenido":
                    raise
                try:
                    ej._log("    ERROR en «%s»: %s" % (orden, _primera(e)))
                except Exception:      # noqa: BLE001
                    pass


def _contar_tipos(filtros):
    cuenta = {}
    for f in filtros:
        t = NOMBRES_TIPO_FILTRO.get(f.get("tipo"), f.get("tipo")).lower()
        cuenta[t] = cuenta.get(t, 0) + 1
    return sorted(cuenta.items())
