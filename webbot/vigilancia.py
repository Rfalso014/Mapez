"""Vigilancia (v3.0): detectar que llegó algo nuevo a un filtro de un reporte y descargarlo.

Ejemplo: el filtro «Elegir corte» de Portal tiene esta semana «44 - 2026 (09/10/2026 - 15/10/2026)» y la que
viene tendrá «45 - 2026 (…)».  Se vigila un paso «Elegir opción» del reporte:

- `revisar(almacen, reporte_id, crear_ejecutor)`: ejecuta los pasos del reporte hasta ese filtro (iniciando sesión si
  hace falta), lee sus opciones y las compara con las ya vistas (tabla `opciones_vistas`).  La primera revisión solo
  apunta lo que hay (referencia).  Si aparecen opciones nuevas: aviso en la aplicación + notificación de Windows
  «Llegó un corte nuevo en «Reporte»: …» con la acción «Descargar».  Con «descargar automáticamente lo nuevo», ejecuta
  el reporte una vez por cada opción nueva con esa opción elegida.
- `descargar_opcion(almacen, reporte_id, paso, texto, crear_ejecutor)`: ejecuta el reporte con esa opción y la anota
  como descargada (no se vuelve a descargar).

v3.1 — regla de novedad (ver `Almacen.registrar_opciones`): solo cuenta como «nueva» (aviso «Llegó un corte nuevo…»,
descarga automática) una opción MÁS RECIENTE que la más reciente ya conocida.  Las más antiguas que aparecen por primera
vez («45 - 2023» en una lista que ya llegaba a «44 - 2026») se guardan en silencio como históricas.  Las opciones sin
fecha, año ni número se avisan como «opción nueva» (sin decir que sea un corte nuevo) y no se descargan solas salvo que
la vigilancia tenga «descargar también las opciones sin fecha».  Cada revisión guarda además la lista en las opciones
del filtro (panel «Usar filtros»).

v3.3 — VARIAS vigilancias: cada una tiene su número y vigila (reporte + paso) o (Página + filtro), con los valores de
los otros filtros (favorito y/o `valores`): «Elegir corte» con el reporte «Detalles Ventas Mayorista» y, aparte, con
«Cartera General», cada una con sus opciones vistas, su novedad y su descarga automática.
`revisar_vigilancia(almacen, id, crear_ejecutor)` revisa una; `descargar_vigilancia(almacen, id, texto, …)` descarga
una opción con los valores de esa vigilancia.  Los avisos dicen de qué vigilancia son («… en «Portal – Reportes»
(Cartera General): 45 - 2026 …») y llevan su `vigilancia_id`.  `revisar`/`revisar_pagina`/`descargar_opcion*` siguen
sirviendo (usan la vigilancia principal del reporte o de la Página).

`crear_ejecutor(flujo, reporte_id=None, **extra)` lo pone quien llama (perfil, carpetas, visible/oculto, pedir_acceso…).
No importa playwright (el ejecutor lo hace en su hilo).
"""

import time

from . import avisos
from . import flujo as mod_flujo
from . import plantillas

TITULO_NOVEDAD = "Llegó %s en «%s»"
TITULO_SIN_ORDEN = "Opción nueva en «%s» (sin fecha: no se sabe si es más reciente)"     # (3.1; ver _titulo_sin_orden)


class ErrorVigilancia(ValueError):
    pass


class ResultadoRevision:
    def __init__(self, reporte_id, nombre=""):
        self.reporte_id = reporte_id
        self.nombre = nombre
        self.ok = False
        self.opciones = []
        self.nuevas = []               # nuevas de verdad: más recientes que todo lo anterior (+ las «sin orden»)
        self.recientes = []            # v3.1: más recientes que la más reciente conocida
        self.sin_orden = []            # v3.1: nuevas sin fecha, año ni número
        self.historicas = []           # v3.1: más antiguas, vistas por primera vez (se apuntan sin avisar)
        self.primera = False
        self.descargas = []            # [(texto, ResultadoEjecucion)]
        self.error = ""
        self.ruta_log = ""

    def resumen(self):
        if not self.ok:
            return "Vigilancia de «%s»: error: %s" % (self.nombre, self.error)
        if self.primera:
            return "Vigilancia de «%s»: primera revisión, %d opciones apuntadas (la más reciente: «%s»)" % (
                self.nombre, len(self.opciones), self.mas_reciente() or "—")
        hist = ("; %d opción(es) antigua(s) apuntadas sin avisar" % len(self.historicas)) if self.historicas else ""
        if not self.nuevas:
            return "Vigilancia de «%s»: nada nuevo (%d opciones)%s" % (self.nombre, len(self.opciones), hist)
        txt = "Vigilancia de «%s»: %d nueva%s: %s" % (self.nombre, len(self.nuevas), "" if len(self.nuevas) == 1 else "s",
                                                    ", ".join("«%s»" % t for t in self.nuevas))
        if self.descargas:
            bien = sum(1 for _t, r in self.descargas if r is not None and r.ok)
            txt += "; descargadas %d de %d" % (bien, len(self.descargas))
        return txt + hist

    def mas_reciente(self):
        k = mod_flujo.elegir_indice(self.opciones, "mas_reciente")
        return self.opciones[k] if k is not None else ""


def paso_vigilable(flujo, indice):
    try:
        paso = flujo.pasos[int(indice)]
    except (IndexError, TypeError, ValueError):
        raise ErrorVigilancia("El reporte no tiene el paso %s" % indice)
    if paso.tipo != "elegir_opcion":
        raise ErrorVigilancia("Solo se puede vigilar un paso «Elegir opción» (convierte la lista del reporte en uno)")
    return paso


def pasos_vigilables(flujo):
    """[(índice, descripción)] de los pasos que se pueden vigilar."""
    return [(i, p.descripcion()) for i, p in enumerate(flujo.pasos) if p.tipo == "elegir_opcion" and not p.desactivado]


def nombre_de_la_novedad(paso, textos=None):
    """«un corte nuevo», «un periodo nuevo» o «una opción nueva» (por el nombre del filtro o, si es «Open» o no dice
    nada, por la forma de las opciones: «45 - 2026 (…)» es un corte)."""
    from . import filtros as mod_filtros
    t = ("%s %s" % (paso.filtro or "", paso.objetivo or "")).lower()
    deducido = mod_filtros.nombre_inferido(textos or []).lower()
    # la forma de las opciones manda («Octubre 2026» es un periodo aunque la lista se llame «corte»)
    if deducido == "periodo":
        return "un periodo nuevo"
    if "corte" in t or ((not t.strip() or mod_flujo.etiqueta_generica(paso.objetivo or "")) and deducido == "corte"):
        return "un corte nuevo"
    if "fecha" in t or "periodo" in t or "período" in t:
        return "un periodo nuevo"
    return "una opción nueva"


def etiqueta_vigilancia(v):
    """Lo que distingue a esta vigilancia de las otras de la misma lista: su nombre, o el favorito y los valores de los
    otros filtros («Mayorista CSV», «Detalles Ventas Mayorista»).  "" si no lleva nada."""
    if (v.get("nombre") or "").strip():
        return v["nombre"].strip()
    partes = []
    if v.get("favorito"):
        partes.append(v["favorito"])
    for _k, e in sorted((v.get("valores") or {}).items(), key=lambda x: str(x[0])):
        if isinstance(e, dict):
            t = e.get("valor") or ((e.get("valores") or [""])[0]) or _ESTRATEGIAS_TEXTO.get(e.get("estrategia") or "", "")
            if "marcado" in e and not t:
                t = "sí" if e.get("marcado") else "no"
        else:
            t = str(e)
        if str(t).strip():
            partes.append(str(t).strip())
    return " + ".join(partes)


_ESTRATEGIAS_TEXTO = {"mas_reciente": "la más reciente", "primera": "la primera", "ultima": "la última"}


def _titulo(que, objetivo, etiqueta):
    return TITULO_NOVEDAD % (que, objetivo) + ((" (%s)" % etiqueta) if etiqueta else "")


def _titulo_sin_orden(objetivo, etiqueta):
    base = "Opción nueva en «%s»%s" % (objetivo, (" (%s)" % etiqueta) if etiqueta else "")
    return base + " (sin fecha: no se sabe si es más reciente)"


def leer_opciones(flujo, indice, crear_ejecutor, reporte_id=None, filtros=None):
    """Ejecuta el reporte hasta el paso `indice` (sin hacerlo) y lee las opciones de esa lista.  `filtros`: otros valores
    para los pasos anteriores (v3.3: los de la vigilancia).  Devuelve (opciones o None, ResultadoEjecucion)."""
    paso = paso_vigilable(flujo, indice)

    def al_final(ej, _pg):
        p = ej.flujo.pasos[int(indice)] if 0 <= int(indice) < len(ej.flujo.pasos) else paso
        pg, scope = ej._alcance(p, 30)
        ej._esperar_carga(pg, minimo=0, forzar=True)
        loc = ej._localizar(pg, scope, p.selectores, ej._timeout_paso(p), que=p.nombre_objetivo(), guardia=True)
        textos = ej.leer_opciones(pg, scope, loc, time.monotonic() + 60, cerrar=True)
        ej.anotar_opciones_leidas(int(indice), p, textos)          # v3.1: para las opciones del filtro
        return textos

    extra = {"filtros": filtros} if filtros else {}
    ej = crear_ejecutor(flujo, reporte_id=reporte_id, hasta=int(indice), al_final=al_final, **extra)
    res = ej.ejecutar()
    return (res.extra if res.ok else None), res


def _filtros_de(v):
    """Los valores de los otros pasos de un reporte vigilado ({paso: {estrategia, valor}}) o None."""
    vals = {}
    for k, e in (v.get("valores") or {}).items():
        try:
            vals[int(k)] = dict(e) if isinstance(e, dict) else {"estrategia": "fija", "valor": str(e)}
        except (TypeError, ValueError):
            continue
    return vals or None


def _avisar_novedades(almacen, r, que, objetivo, etiqueta, datos, texto_ayuda):
    if r.recientes:
        titulo = _titulo(que, objetivo, etiqueta)
        for texto in r.recientes:
            avisos.avisar(almacen, "vigilancia", "%s: %s" % (titulo, texto), texto_ayuda, dict(datos, opcion=texto),
                          windows=False)
        avisos.notificar(titulo, "; ".join(r.recientes)[:250])
    if r.sin_orden:
        titulo = _titulo_sin_orden(objetivo, etiqueta)
        for texto in r.sin_orden:
            avisos.avisar(almacen, "vigilancia", "%s: %s" % (titulo, texto), "No lleva fecha ni número, así que el bot no "
                          "sabe si es más reciente. Pulsa «Descargar» si la quieres.", dict(datos, opcion=texto),
                          windows=False)
        avisos.notificar(titulo, "; ".join(r.sin_orden)[:250])


def revisar_vigilancia(almacen, vigilancia_id, crear_ejecutor, descargar=None, log=None):
    """v3.3: revisa UNA vigilancia (de un reporte o de una Página) por su número.  `crear_ejecutor(flujo, **extra)` lo
    pone quien llama (para una Página, con su perfil).  `descargar`: None = lo que diga la vigilancia."""
    v = almacen.vigilancia_id(vigilancia_id)
    if v is None:
        raise ErrorVigilancia("No existe la vigilancia número %s" % vigilancia_id)
    if v["tipo"] == "pagina":
        return _revisar_pagina(almacen, v, crear_ejecutor, descargar, log)
    return _revisar_reporte(almacen, v, crear_ejecutor, descargar, log)


def revisar(almacen, reporte_id, crear_ejecutor, descargar=None, log=None, vigilancia_id=None):
    """Revisa el filtro vigilado de un reporte: la vigilancia `vigilancia_id` o (como en la 3.0–3.2) la principal del
    reporte.  Para revisarlas todas, `revisar_vigilancia` con cada una de `almacen.lista_vigilancias(reporte_id=…)`."""
    fila = almacen.obtener(reporte_id)
    if fila is None:
        raise ErrorVigilancia("No existe el reporte número %s" % reporte_id)
    v = almacen.vigilancia_id(vigilancia_id) if vigilancia_id else almacen.vigilancia(reporte_id)
    if v is None:
        raise ErrorVigilancia("El reporte «%s» no tiene ningún filtro vigilado" % fila["nombre"])
    return _revisar_reporte(almacen, v, crear_ejecutor, descargar, log)


def _revisar_reporte(almacen, v, crear_ejecutor, descargar, log):
    reporte_id = v["reporte_id"]
    fila = almacen.obtener(reporte_id)
    if fila is None:
        raise ErrorVigilancia("No existe el reporte número %s" % reporte_id)
    etiqueta = etiqueta_vigilancia(v)
    r = ResultadoRevision(reporte_id, fila["nombre"] + ((" (%s)" % etiqueta) if etiqueta else ""))
    r.vigilancia_id = v["id"]
    flujo = almacen.cargar_flujo(reporte_id)
    try:
        paso = paso_vigilable(flujo, v["paso"])
    except ErrorVigilancia as e:
        r.error = str(e)
        almacen.anotar_revision_id(v["id"], "error: " + r.error)
        return r
    opciones, res = leer_opciones(flujo, v["paso"], crear_ejecutor, reporte_id=reporte_id, filtros=_filtros_de(v))
    r.ruta_log = res.ruta_log
    if opciones is None:
        r.error = res.resumen() if not res.ok else "no se pudieron leer las opciones"
        almacen.anotar_revision_id(v["id"], "error: " + r.error)
        if log:
            log(r.resumen())
        return r
    r.ok = True
    r.opciones = list(opciones)
    det = almacen.registrar_opciones_vigilancia(v["id"], r.opciones, detalle=True)
    r.nuevas, r.primera = det["nuevas"], det["primera"]
    r.recientes, r.sin_orden, r.historicas = det["recientes"], det["sin_orden"], det["historicas"]
    try:
        almacen.guardar_opciones_leidas(reporte_id, res, "vigilancia")
    except Exception:                  # noqa: BLE001 (la caché de opciones no debe estropear la revisión)
        pass
    if r.historicas and log:
        log("Vigilancia de «%s»: %d opción(es) más antigua(s) que la más reciente conocida aparecieron por primera vez "
            "(p. ej. «%s»): se apuntan como históricas, sin aviso ni descarga" % (r.nombre, len(r.historicas),
                                                                                r.historicas[0]))
    datos = {"vigilancia_id": v["id"], "reporte_id": reporte_id, "paso": v["paso"], "accion": "descargar"}
    _avisar_novedades(almacen, r, nombre_de_la_novedad(paso, r.opciones), fila["nombre"], etiqueta, datos,
                      "Pulsa «Descargar» para bajar el reporte con esa opción.")
    hacer = bool(v.get("auto_descargar")) if descargar is None else bool(descargar)
    if hacer and not r.primera:
        for texto in almacen.pendientes_vigilancia(v["id"], incluir_sin_orden=bool(v.get("descargar_sin_fecha"))):
            r.descargas.append((texto, descargar_vigilancia(almacen, v["id"], texto, crear_ejecutor, log=log)))
    almacen.anotar_revision_id(v["id"], r.resumen())
    if log:
        log(r.resumen())
    return r


# ------------------------------------------------------------------ v3.2: vigilar un filtro de una Página
def revisar_pagina(almacen, pagina_id, crear_ejecutor, descargar=None, log=None, vigilancia_id=None):
    """Como `revisar`, para un filtro de una Página («Elegir corte» de «Portal – Reportes»): la vigilancia
    `vigilancia_id` o la principal de la Página.  Los filtros anteriores llevan los valores del favorito y de los
    `valores` de la vigilancia (o los de por defecto).  Las opciones leídas quedan en la Página (el «45 - 2026» sale en
    su lista con la marca «nueva»).  Con «descargar automáticamente», ejecuta la Página con esos valores y la opción
    nueva."""
    fila = almacen.obtener_pagina(pagina_id)
    if fila is None:
        raise ErrorVigilancia("No existe la página número %s" % pagina_id)
    v = almacen.vigilancia_id(vigilancia_id) if vigilancia_id else almacen.vigilancia_pagina(pagina_id)
    if v is None:
        raise ErrorVigilancia("La página «%s» no tiene ningún filtro vigilado" % fila["nombre"])
    return _revisar_pagina(almacen, v, crear_ejecutor, descargar, log)


def seleccion_de_vigilancia(data, v, extra=None):
    """Lo elegido para ejecutar la Página en esta vigilancia: favorito (si sigue existiendo) + `valores` + `extra`."""
    from . import paginas as mod_paginas
    fav = v.get("favorito") or None
    if fav:
        try:
            mod_paginas.buscar_favorito(data, fav)
        except mod_paginas.ErrorPagina:
            fav = None                 # el favorito se borró: con los valores por defecto
    ids = {f["id"] for f in data["filtros"]}
    sel = {str(k): e for k, e in (v.get("valores") or {}).items() if str(k) in ids}
    sel.update(extra or {})
    return mod_paginas.seleccion_base(data, favorito=fav, seleccion=sel)


def _revisar_pagina(almacen, v, crear_ejecutor, descargar, log):
    from . import paginas as mod_paginas
    pagina_id = v["pagina_id"]
    fila = almacen.obtener_pagina(pagina_id)
    if fila is None:
        raise ErrorVigilancia("No existe la página número %s" % pagina_id)
    etiqueta = etiqueta_vigilancia(v)
    r = ResultadoRevision(None, fila["nombre"] + ((" (%s)" % etiqueta) if etiqueta else ""))
    r.pagina_id = pagina_id
    r.vigilancia_id = v["id"]
    data = mod_paginas.normalizar(fila["data"])
    try:
        f = mod_paginas.filtro(data, v["filtro"])
        if f["tipo"] not in ("lista", "lista_nativa"):
            raise ErrorVigilancia("Solo se puede vigilar una lista")
        sel = seleccion_de_vigilancia(data, v)
        eleccion = mod_paginas.combinaciones(data, sel)[0][0]
        flujo, indices = mod_paginas.construir_flujo(data, fila["nombre"], eleccion, hasta=f["id"])
    except (mod_paginas.ErrorPagina, ErrorVigilancia) as e:
        r.error = str(e)
        almacen.anotar_revision_id(v["id"], "error: " + r.error)
        return r
    opciones, res = leer_opciones(flujo, indices[f["id"]], crear_ejecutor)
    r.ruta_log = res.ruta_log
    try:
        if mod_paginas.guardar_lecturas(almacen, pagina_id, data, mod_paginas.lecturas_de_resultado(indices, res),
                                        "vigilancia"):
            mod_paginas._guardar_data(almacen, pagina_id, fila, data)
    except Exception:                  # noqa: BLE001
        pass
    if opciones is None:
        r.error = res.resumen() if not res.ok else "no se pudieron leer las opciones"
        almacen.anotar_revision_id(v["id"], "error: " + r.error)
        if log:
            log(r.resumen())
        return r
    r.ok = True
    r.opciones = list(opciones)
    det = almacen.registrar_opciones_vigilancia(v["id"], r.opciones, detalle=True)
    r.nuevas, r.primera = det["nuevas"], det["primera"]
    r.recientes, r.sin_orden, r.historicas = det["recientes"], det["sin_orden"], det["historicas"]
    paso_vigilado = flujo.pasos[indices[f["id"]]]
    datos = {"vigilancia_id": v["id"], "pagina_id": pagina_id, "filtro": f["id"], "accion": "descargar"}
    _avisar_novedades(almacen, r, nombre_de_la_novedad(paso_vigilado, r.opciones), fila["nombre"], etiqueta, datos,
                      "Pulsa «Descargar» para bajarla con la página.")
    hacer = bool(v.get("auto_descargar")) if descargar is None else bool(descargar)
    if hacer and not r.primera:
        for texto in almacen.pendientes_vigilancia(v["id"], incluir_sin_orden=bool(v.get("descargar_sin_fecha"))):
            r.descargas.append((texto, descargar_vigilancia(almacen, v["id"], texto, crear_ejecutor, log=log)))
    almacen.anotar_revision_id(v["id"], r.resumen())
    if log:
        log(r.resumen())
    return r


def descargar_vigilancia(almacen, vigilancia_id, texto, crear_ejecutor, log=None):
    """v3.3: ejecuta el reporte o la Página de la vigilancia con `texto` en el filtro vigilado (y los valores de la
    vigilancia en los demás) y lo anota como descargado en ESA vigilancia.  Devuelve el ResultadoEjecucion (o None)."""
    v = almacen.vigilancia_id(vigilancia_id)
    if v is None:
        raise ErrorVigilancia("No existe la vigilancia número %s" % vigilancia_id)
    if v["tipo"] == "pagina":
        res = _ejecutar_pagina_con(almacen, v, texto, crear_ejecutor, log)
    else:
        res = _ejecutar_reporte_con(almacen, v, texto, crear_ejecutor, log)
    if res is not None and res.ok:
        almacen.marcar_descargada_vigilancia(v["id"], texto, res.archivos)
        _marcar_avisos(almacen, v["id"], texto)
    return res


def _marcar_avisos(almacen, vigilancia_id, texto):
    for n in almacen.notificaciones(limite=300, solo_no_leidas=True):
        d = n["datos"]
        if n["tipo"] == "vigilancia" and d.get("opcion") == texto and d.get("vigilancia_id") in (None, vigilancia_id):
            almacen.marcar_notificacion(n["id"])


def _ejecutar_pagina_con(almacen, v, texto, crear_ejecutor, log=None):
    from . import paginas as mod_paginas
    fila = almacen.obtener_pagina(v["pagina_id"])
    data = mod_paginas.normalizar(fila["data"])
    try:
        sel = seleccion_de_vigilancia(data, v, {str(v["filtro"]): {"estrategia": "fija", "valor": texto}})
        r = mod_paginas.ejecutar(almacen, v["pagina_id"], sel, lambda fl, **ex: crear_ejecutor(fl, **ex), log=log)
    except mod_paginas.ErrorPagina as e:
        if log:
            log("No se pudo descargar «%s»: %s" % (texto, e))
        return None
    return r.resultados[-1][1] if r.resultados else None


def _ejecutar_reporte_con(almacen, v, texto, crear_ejecutor, log=None):
    flujo = almacen.cargar_flujo(v["reporte_id"])
    paso = paso_vigilable(flujo, v["paso"])
    paso.estrategia = "fija"
    paso.valor = plantillas.escapar(texto)
    if log:
        log("=== «%s»: descargando «%s» ===" % (flujo.nombre, texto))
    filtros = _filtros_de(v)
    if filtros:
        filtros.pop(int(v["paso"]), None)
    ej = crear_ejecutor(flujo, reporte_id=v["reporte_id"], **({"filtros": filtros} if filtros else {}))
    res = ej.ejecutar()
    try:
        almacen.registrar_resultado(v["reporte_id"], res)
    except Exception:                  # noqa: BLE001
        pass
    return res


def descargar_opcion_pagina(almacen, pagina_id, filtro_id, texto, crear_ejecutor, favorito=None, log=None,
                            vigilancia_id=None):
    """(3.2) Ejecuta la Página con `texto` en el filtro vigilado y la anota como descargada.  v3.3: con la vigilancia
    `vigilancia_id` (o la principal de ese filtro) y sus valores."""
    vid = vigilancia_id or almacen._principal(pagina_id=pagina_id, filtro=filtro_id)
    if vid:
        return descargar_vigilancia(almacen, vid, texto, crear_ejecutor, log=log)
    v = {"id": None, "tipo": "pagina", "pagina_id": pagina_id, "filtro": filtro_id, "favorito": favorito or "",
         "valores": {}}
    return _ejecutar_pagina_con(almacen, v, texto, crear_ejecutor, log)


def descargar_opcion(almacen, reporte_id, paso_indice, texto, crear_ejecutor, log=None, vigilancia_id=None):
    """(3.0) Ejecuta el reporte con la opción `texto` elegida en el paso vigilado y la anota como descargada.  v3.3: en
    la vigilancia `vigilancia_id` (o la principal de ese paso)."""
    vid = vigilancia_id or almacen._principal(reporte_id=reporte_id, paso=paso_indice)
    if vid:
        return descargar_vigilancia(almacen, vid, texto, crear_ejecutor, log=log)
    v = {"id": None, "reporte_id": reporte_id, "paso": paso_indice, "valores": {}}
    return _ejecutar_reporte_con(almacen, v, texto, crear_ejecutor, log)
