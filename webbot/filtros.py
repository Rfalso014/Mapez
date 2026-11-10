"""«Usar filtros» (v3.1): los filtros de un reporte, con todas sus opciones conocidas, para elegirlas y descargar.

Un «filtro» es un paso activo del reporte que elige algo en la página: «Elegir opción» (listas propias o nativas),
«Seleccionar» (lista nativa grabada) o «Escribir» una fecha.  Este módulo (sin playwright) prepara los datos del panel
y aplica lo que el usuario elige:

- `pasos_filtro(flujo)`: [(índice, paso)] de los filtros.
- `nombre_filtro(...)` / `nombres(flujo, mapas)`: nombre para el usuario.  Por orden: el guardado en el paso (`filtro`),
  la etiqueta del filtro en el último mapa («Filtro por sistema», «Elegir corte»… enlazado por selectores o por el
  valor), el `objetivo` del paso, la etiqueta flotante repetida en un selector `div:text-is("Corte44 - 2026 …Corte")`, lo
  que se deduce de las opciones («Corte», «Periodo», «Formato») y, si no, «Lista del paso N».  Nunca «Open», «Abrir»,
  «Close» ni nombres de iconos (`flujo.etiqueta_generica`).
- `datos_panel(...)`: los filtros con sus opciones (las listas que parecen de periodos, de la más reciente a la más
  antigua con `clave_reciente`; las demás en el orden de la página), la elección actual, de dónde salen las opciones
  (`opciones_filtro`: mapa / ejecución / vigilancia / «Actualizar opciones») y cuándo, y las opciones nuevas.  Las
  opciones se guardan por combinación de los valores de los filtros anteriores (listas dependientes, p. ej. «corte»
  depende de «reporte»); si no hay lista para la combinación elegida se muestra la última conocida con una nota.
- `combinaciones(flujo, elecciones)`: una ejecución por cada combinación (varias opciones en un filtro → producto
  cartesiano).  `aplicar(flujo, cambios, sufijo)`: copia del flujo con esos cambios (no toca el reporte guardado) y,
  si hay varias ejecuciones, el nombre del archivo lleva « - <opción>» para que no se pisen.
- `guardar_predeterminado(flujo, elecciones, nombres)`: escribe las elecciones en los pasos (quien llama guarda antes
  una copia en `versiones`).
- `resolver_cli(flujo, textos, mapas)`: `--filtro "Elegir corte=43 - 2026 (…)"` → cambios por paso.
"""

import itertools
import re

from . import flujo as mod_flujo
from . import plantillas

TIPOS = ("elegir_opcion", "seleccionar", "escribir")
MAX_SIN_CONFIRMAR = 10        # más ejecuciones que estas: se pide confirmación
MAX_EJECUCIONES = 100
DIAS_NUEVA = 7                # una opción nueva (vigilancia) lleva la marca «nueva» durante estos días
FUENTES = {"mapa": "del mapa de la página", "ejecucion": "de una ejecución", "vigilancia": "de la vigilancia",
           "actualizar": "de «Actualizar opciones»"}
_RX_FECHA_PLANTILLA = re.compile(r"\{(hoy|ayer|fecha|inicio_mes|fin_mes|inicio_mes_anterior|fin_mes_anterior|"
                                 r"manana|mañana|lunes|semana|dias|lunes_semana|lunes_semana_anterior|"
                                 r"domingo_semana_anterior|inicio_anio)\b", re.IGNORECASE)
_RX_FECHA_TEXTO = re.compile(r"fecha|date|desde|hasta|inicio|final|periodo|período|día|dia\b", re.IGNORECASE)
_RX_FECHA_VALOR = re.compile(r"^\s*\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}\s*$")
_RX_CORTE = re.compile(r"^\s*\d{1,2}\s*-\s*\d{4}\b")
_RX_FORMATO = re.compile(r"\b(excel|xlsx?|csv|pdf|txt|word|docx?|html|xml|json)\b", re.IGNORECASE)
_RX_TEXT_IS = re.compile(r':text-is\("((?:[^"\\]|\\.)*)"\)')
_RX_ESTRATEGIA_CLI = {"mas_reciente": "mas_reciente", "más reciente": "mas_reciente", "mas reciente": "mas_reciente",
                      "la más reciente": "mas_reciente", "la mas reciente": "mas_reciente", "primera": "primera",
                      "la primera": "primera", "ultima": "ultima", "última": "ultima", "la última": "ultima",
                      "la ultima": "ultima"}


class ErrorFiltros(ValueError):
    pass


# ------------------------------------------------------------------ qué pasos son filtros
def es_fecha(paso):
    """Paso «Escribir» que escribe una fecha (no contraseñas ni textos cualquiera)."""
    if paso.tipo != "escribir" or paso.es_secreto() or paso.parece_contrasena():
        return False
    v = paso.valor or ""
    return bool(paso.fecha_directa or _RX_FECHA_PLANTILLA.search(v) or _RX_FECHA_VALOR.match(v)
                or _RX_FECHA_TEXTO.search(paso.objetivo or "") or _RX_FECHA_TEXTO.search(paso.filtro or ""))


def es_filtro(paso):
    if paso.desactivado or paso.tipo not in TIPOS:
        return False
    return paso.tipo != "escribir" or es_fecha(paso)


def pasos_filtro(flujo):
    return [(i, p) for i, p in enumerate(flujo.pasos) if es_filtro(p)]


def es_lista(paso):
    return paso.tipo in ("elegir_opcion", "seleccionar")


def ultimo_filtro(flujo):
    pf = pasos_filtro(flujo)
    return pf[-1][0] if pf else None


def firma_paso(paso):
    """Identifica el campo del filtro (para no confundir opciones si los pasos se mueven)."""
    return (paso.selectores or [""])[0][:300]


def desescapar(valor):
    """Texto literal de un valor escapado con `plantillas.escapar` (las plantillas de verdad se dejan tal cual)."""
    v = valor or ""
    if plantillas.es_plantilla(v):
        return v
    return v.replace("{{", "{").replace("}}", "}")


def valor_actual(paso):
    """(estrategia, valor) que tiene guardado el paso (valor en texto literal)."""
    if paso.tipo == "seleccionar":
        return "fija", paso.etiqueta or desescapar(paso.valor)
    if paso.tipo == "escribir":
        return "", paso.valor or ""
    est = paso.estrategia or "fija"
    return est, desescapar(paso.valor) if est in ("fija", "contiene", "por_fecha") else ""


# ------------------------------------------------------------------ nombres
def etiqueta_de_selector(paso):
    """«Corte» de `div:text-is("Corte44 - 2026 (…)Corte")`: la etiqueta flotante de Vuetify sale al principio y al final."""
    for sel in paso.selectores or []:
        m = _RX_TEXT_IS.search(sel or "")
        if not m:
            continue
        t = m.group(1).replace('\\"', '"')
        for n in range(len(t) // 2, 1, -1):
            pref = t[:n]
            if t.endswith(pref) and len(t) > 2 * n and pref.strip() and not mod_flujo.etiqueta_generica(pref):
                return pref.strip()
    return ""


def nombre_inferido(opciones, paso=None):
    ops = [o for o in opciones or [] if (o or "").strip()]
    if paso is not None and paso.tipo == "escribir":
        return "Fecha"
    if not ops:
        return ""
    n = len(ops)
    if sum(1 for o in ops if _RX_CORTE.match(o)) * 10 >= n * 6:
        return "Corte"
    if mod_flujo.parece_cronologica(ops):
        return "Periodo"
    if sum(1 for o in ops if _RX_FORMATO.search(o)) * 10 >= n * 6:
        return "Formato"
    return ""


def filtro_del_mapa(paso, mapas):
    """(filtro del mapa, mapa) enlazado con el paso: por selectores y, si no, por su valor entre las opciones."""
    sels = set(paso.selectores or [])
    for m in mapas or []:
        for f in m.get("filtros") or []:
            if f.get("tipo") in ("lista", "lista_nativa", "fecha", "texto") and sels & set(f.get("selectores") or []):
                return f, m
    if es_lista(paso):
        _est, valor = valor_actual(paso)
        if valor:
            for m in mapas or []:
                cands = [f for f in m.get("filtros") or [] if f.get("tipo") in ("lista", "lista_nativa")
                         and (valor in (f.get("opciones") or []) or f.get("valor") == valor)]
                if len(cands) == 1:
                    return cands[0], m
    return None, None


def nombre_filtro(paso, indice, filtro_mapa=None, opciones=None):
    """(nombre, origen): origen = guardado | mapa | paso | pagina | deducido | numero."""
    if paso.filtro and not mod_flujo.etiqueta_generica(paso.filtro):
        return paso.filtro.strip(), "guardado"
    et = (filtro_mapa or {}).get("etiqueta") or ""
    if et and not mod_flujo.etiqueta_generica(et):
        return et.strip(), "mapa"
    if paso.objetivo and not mod_flujo.etiqueta_generica(paso.objetivo):
        return paso.objetivo.strip(), "paso"
    et = etiqueta_de_selector(paso)
    if et:
        return et, "pagina"
    et = nombre_inferido(opciones or ((filtro_mapa or {}).get("opciones") or []), paso)
    if et:
        return et, "deducido"
    return ("Fecha del paso %d" if paso.tipo == "escribir" else "Lista del paso %d") % (indice + 1), "numero"


def nombres(flujo, mapas=None, opciones_por_paso=None):
    """{índice: (nombre, origen)} de todos los filtros; los repetidos llevan « (paso N)»."""
    res = {}
    for i, p in pasos_filtro(flujo):
        f, _m = filtro_del_mapa(p, mapas)
        res[i] = nombre_filtro(p, i, f, (opciones_por_paso or {}).get(i))
    for i, n in _desambiguar({i: (n, o) for i, (n, o) in res.items()}).items():
        res[i] = (n, res[i][1])
    return res


_FUERZA = {"guardado": 0, "mapa": 1, "paso": 2, "pagina": 3, "deducido": 4, "numero": 5}


def _desambiguar(nombres_origen):
    """{índice: nombre}: si varios filtros se llaman igual, el de nombre más fiable (guardado, del mapa…) lo conserva y
    los demás llevan « (paso N)»."""
    grupos = {}
    for i, (n, o) in nombres_origen.items():
        grupos.setdefault(n.lower(), []).append((_FUERZA.get(o, 9), i))
    res = {i: n for i, (n, _o) in nombres_origen.items()}
    for idx in grupos.values():
        if len(idx) > 1:
            idx.sort()
            for _f, i in idx[1:]:
                if nombres_origen[i][1] != "guardado":
                    res[i] = "%s (paso %d)" % (nombres_origen[i][0], i + 1)
    return res


def validar_nombre(nombre):
    n = re.sub(r"\s+", " ", nombre or "").strip()
    if not n:
        raise ErrorFiltros("Escribe un nombre para el filtro")
    if len(n) > 60:
        raise ErrorFiltros("El nombre es demasiado largo (máximo 60 caracteres)")
    if mod_flujo.etiqueta_generica(n):
        raise ErrorFiltros("«%s» no sirve como nombre de un filtro: escribe lo que elige (p. ej. «Elegir corte»)" % n)
    return n


# ------------------------------------------------------------------ opciones guardadas
def buscar_opciones(filas, padres, firma=""):
    """Elige la lista guardada para esa combinación de filtros anteriores.  Devuelve (fila o None, exacta, distintas):
    `exacta` = es de esa combinación (o de una compatible: sin valores distintos); `distintas` = hay listas diferentes
    para otras combinaciones (la lista depende de los filtros anteriores)."""
    filas = [f for f in filas or [] if not firma or not f.get("firma") or f.get("firma") == firma]
    if not filas:
        return None, False, False
    distintas = len({tuple(f.get("opciones") or []) for f in filas}) > 1
    padres = {int(k): v for k, v in (padres or {}).items()}
    for f in filas:
        if f.get("padres") == padres:
            return f, True, distintas
    # compatible: los filtros anteriores que tienen en común valen lo mismo (los que una de las dos no conoce —p. ej. el
    # mapa solo sabe los valores de sus listas— no cuentan)
    compatibles = []
    for f in filas:
        fp = f.get("padres") or {}
        comunes = set(fp) & set(padres)
        if all(fp[k] == padres[k] for k in comunes):
            compatibles.append((len(comunes), f))
    if compatibles:
        compatibles.sort(key=lambda x: -x[0])          # estable: entre iguales, la más reciente (vienen ordenadas)
        n, f = compatibles[0]
        return f, bool(n) or not padres or not (f.get("padres") or {}), distintas
    return filas[0], False, distintas


def _texto_elegido(opciones, est, valor):
    if est in ("fija", "") and valor:
        return valor
    texto_valor = valor
    if est in ("contiene", "por_fecha") and plantillas.es_plantilla(valor or ""):
        try:
            texto_valor = plantillas.renderizar(valor)
        except plantillas.ErrorPlantilla:
            texto_valor = valor
    k = mod_flujo.elegir_indice(opciones or [], est or "fija", texto_valor or "")
    return opciones[k] if k is not None else ""


def normalizar_elecciones(elecciones):
    """{índice: {estrategia, valor} | {valores: [...]}} (las claves pueden venir como texto desde la API)."""
    res = {}
    for k, e in (elecciones or {}).items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            raise ErrorFiltros("Paso no válido: %s" % k)
        if isinstance(e, str):
            e = {"estrategia": "fija", "valor": e}
        if not isinstance(e, dict):
            raise ErrorFiltros("Elección no válida para el paso %d" % (i + 1))
        d = {}
        vals = e.get("valores")
        if isinstance(vals, list):
            vals = [str(v) for v in vals if str(v).strip()]
            if vals:
                d["valores"] = list(dict.fromkeys(vals))
        if "valores" not in d:
            d["estrategia"] = str(e.get("estrategia") or "fija")
            d["valor"] = "" if e.get("valor") is None else str(e.get("valor"))
        res[i] = d
    return res


def _sugerencias_fecha(valor):
    m = re.search(r"\{[a-z_]+:([^}]*)\}", valor or "")
    fmt = m.group(1) if m else None
    if not fmt:
        v = (valor or "").strip()
        fmt = "%d/%m/%Y"
        for patron, f in ((r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"), (r"\d{2}/\d{2}/\d{4}", "%d/%m/%Y"),
                          (r"\d{2}-\d{2}-\d{4}", "%d-%m-%Y"), (r"\d{4}/\d{2}/\d{2}", "%Y/%m/%d")):
            if re.fullmatch(patron, v):
                fmt = f
    return [{"valor": "{hoy:%s}" % fmt, "texto": "hoy"}, {"valor": "{ayer:%s}" % fmt, "texto": "ayer"},
            {"valor": "{inicio_mes:%s}" % fmt, "texto": "inicio del mes"},
            {"valor": "{fin_mes:%s}" % fmt, "texto": "fin del mes"},
            {"valor": "{inicio_mes_anterior:%s}" % fmt, "texto": "inicio del mes anterior"},
            {"valor": "{fin_mes_anterior:%s}" % fmt, "texto": "fin del mes anterior"}]


def datos_panel(flujo, filas_cache=None, mapas=None, novedades=None, vigilado=None, elecciones=None,
                vistas_vigilancia=None):
    """Lista de filtros para el panel.  `filas_cache`: filas de `Almacen.opciones_filtro`; `mapas`: los del reporte (el
    más reciente primero); `novedades`: {paso: [textos nuevos]}; `vigilado`: índice del paso vigilado; `elecciones`:
    lo que el usuario tiene elegido en el panel (para las listas que dependen de otras); `vistas_vigilancia`: textos ya
    vistos por la vigilancia (si no hay otra lista)."""
    elecciones = normalizar_elecciones(elecciones)
    por_paso = {}
    for f in filas_cache or []:
        por_paso.setdefault(int(f["paso"]), []).append(f)
    res = []
    elegidas = {}
    nombres_previos = {}
    for i, p in pasos_filtro(flujo):
        fm, mapa = filtro_del_mapa(p, mapas)
        est_g, valor_g = valor_actual(p)
        e = elecciones.get(i) or {}
        d = {"paso": i, "numero": i + 1, "tipo": p.tipo, "clase": "lista" if es_lista(p) else "fecha",
             "nombre_guardado": p.filtro, "objetivo": p.objetivo, "estrategia_guardada": est_g, "valor_guardado": valor_g,
             "vigilado": vigilado is not None and int(vigilado) == i, "descripcion": p.descripcion()}
        if not es_lista(p):
            d.update(opciones=[], valor=e.get("valor", valor_g) if "valores" not in e else e["valores"][0],
                     sugerencias=_sugerencias_fecha(valor_g), actualizado="", fuente="", nota="", exacta=True,
                     # v3.6: el formato de la fecha grabada (el calendario de la interfaz lo propone)
                     formato=plantillas.formato_de_fecha(valor_g) or "")
            d["nombre"], d["origen_nombre"] = nombre_filtro(p, i, fm)
            res.append(d)
            continue
        padres = {k: v for k, v in elegidas.items() if k < i}
        fila, exacta, distintas = buscar_opciones(por_paso.get(i), padres, firma_paso(p))
        opciones, actualizado, fuente = [], "", ""
        if fila is not None:
            opciones, actualizado, fuente = list(fila.get("opciones") or []), fila.get("actualizado", ""), fila.get("fuente", "")
        elif fm is not None and fm.get("opciones"):
            opciones, actualizado, fuente, exacta = list(fm["opciones"]), (mapa or {}).get("cuando", ""), "mapa", True
        elif d["vigilado"] and vistas_vigilancia:
            opciones, fuente, exacta = list(vistas_vigilancia), "vigilancia", True
        cron = mod_flujo.parece_cronologica(opciones)
        orden = mod_flujo.ordenar_recientes(opciones) if cron else list(opciones)
        nuevas = set((novedades or {}).get(i) or [])
        if "valores" in e:
            est, valor, seleccion = "fija", e["valores"][0], list(e["valores"])
        else:
            est = e.get("estrategia", est_g) or "fija"
            valor = e.get("valor", valor_g) if e else valor_g
            seleccion = []
        actual = _texto_elegido(opciones, est, valor)
        if not seleccion:
            seleccion = [actual] if actual else []
        if est == "fija" and valor and valor not in opciones:
            orden.insert(0, valor)
        d["nombre"], d["origen_nombre"] = nombre_filtro(p, i, fm, opciones)
        mas_reciente = orden[0] if cron and orden and mod_flujo.es_reconocible(orden[0]) and orden[0] in opciones else ""
        d.update(estrategia=est, valor=valor, actual=actual, seleccion=seleccion, cronologica=cron,
                 mas_reciente=mas_reciente, actualizado=actualizado, fuente=fuente,
                 fuente_texto=FUENTES.get(fuente, fuente), exacta=bool(exacta),
                 opciones=[{"texto": t, "detalle": mod_flujo.describir_opcion(t), "nueva": t in nuevas,
                            "mas_reciente": t == mas_reciente, "guardada": t not in opciones} for t in orden],
                 padres={nombres_previos.get(k, "paso %d" % (k + 1)): v for k, v in padres.items()})
        d["nota"], d["nota_tipo"] = "", ""
        combo = ", ".join("%s = «%s»" % (k, v) for k, v in d["padres"].items())
        if not opciones:
            d["nota"], d["nota_tipo"] = "Todavía no se conocen las opciones de este filtro: pulsa «Actualizar opciones».", "info"
        elif not d["exacta"] and distintas:
            d["nota"], d["nota_tipo"] = ("No hay opciones guardadas para esta combinación (%s): se muestra la última lista "
                                         "conocida (%s). Pulsa «Actualizar opciones» para leer la de esta combinación."
                                         % (combo, actualizado)), "aviso"
        elif not d["exacta"]:
            d["nota"], d["nota_tipo"] = ("Estas opciones se leyeron con otra combinación de los filtros anteriores. Si "
                                         "dependen de ellos (%s), pulsa «Actualizar opciones» para leer las de esta "
                                         "combinación." % combo), "info"
        if seleccion:
            elegidas[i] = seleccion[0]
        nombres_previos[i] = d["nombre"]
        res.append(d)
    nuevos = _desambiguar({d["paso"]: (d["nombre"], d["origen_nombre"]) for d in res})     # repetidos → « (paso N)»
    for d in res:
        d["nombre"] = nuevos[d["paso"]]
    return res


# ------------------------------------------------------------------ aplicar elecciones
def _limpio_para_archivo(texto, largo=80):
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(texto)).strip(" .")
    return t[:largo].strip()


def _distinto(paso, cambio):
    if paso.tipo == "escribir":
        return (cambio.get("valor") or "") != (paso.valor or "")
    est_g, valor_g = valor_actual(paso)
    est = cambio.get("estrategia") or "fija"
    if paso.tipo == "seleccionar":
        return est != "fija" or (cambio.get("valor") or "") != valor_g
    if est != est_g:
        return True
    return est in ("fija", "contiene", "por_fecha") and (cambio.get("valor") or "") != valor_g


def describir_cambio(paso, cambio):
    if paso.tipo == "escribir":
        return "«%s»" % (cambio.get("valor") or "")
    est = cambio.get("estrategia") or "fija"
    if est == "fija":
        return "«%s»" % (cambio.get("valor") or "")
    if est == "contiene":
        return "la que contiene «%s»" % (cambio.get("valor") or "")
    if est == "por_fecha":
        return "la de la fecha «%s»" % plantillas.describir_fecha(cambio.get("valor") or "")
    return {"mas_reciente": "la más reciente", "primera": "la primera", "ultima": "la última"}.get(est, est)


def aplicar(flujo, cambios, sufijo=None, nombres_filtros=None):
    """Copia del flujo con los `cambios` {índice: {estrategia, valor}} (valor = texto literal de la opción; en las
    fechas, el texto o plantilla a escribir).  `sufijo`: lista de textos que se añaden al nombre de los archivos
    (« - 43 - 2026 (…)») si el nombre no lleva ya `{opcion}`.  Devuelve (flujo, líneas para el registro)."""
    f = flujo.copia()
    lineas = []
    for i, cambio in sorted((int(k), v) for k, v in (cambios or {}).items()):
        if not 0 <= i < len(f.pasos):
            raise ErrorFiltros("El reporte no tiene el paso %d" % (i + 1))
        p = f.pasos[i]
        if not es_filtro(p):
            raise ErrorFiltros("El paso %d no es un filtro (%s)" % (i + 1, p.descripcion()))
        if not _distinto(p, cambio):
            continue
        nombre = (nombres_filtros or {}).get(i) or p.filtro or p.objetivo or "paso %d" % (i + 1)
        if p.tipo == "escribir":
            valor = cambio.get("valor") or ""
            err = plantillas.validar(valor)
            if err:
                raise ErrorFiltros("%s: %s" % (nombre, err))
            p.valor = valor
        else:
            est = cambio.get("estrategia") or "fija"
            if est not in mod_flujo.ESTRATEGIAS:
                raise ErrorFiltros("Estrategia no válida: %s" % est)
            valor = cambio.get("valor") or ""
            if est in ("fija", "contiene", "por_fecha") and not valor.strip():
                raise ErrorFiltros("Falta la opción de «%s»" % nombre)
            err = plantillas.validar(valor) if est == "por_fecha" else None
            if err:
                raise ErrorFiltros("%s: %s" % (nombre, err))
            if p.tipo == "seleccionar":        # lista nativa grabada: se elige por el texto con «Elegir opción»
                p.tipo, p.etiqueta = "elegir_opcion", ""
            p.estrategia = est
            p.valor = plantillas.escapar(valor) if est == "fija" else (valor if est in ("contiene", "por_fecha") else "")
        lineas.append("paso %d «%s» = %s" % (i + 1, nombre, describir_cambio(p, cambio)))
    if sufijo:
        extra = " - " + " - ".join(_limpio_para_archivo(t) for t in sufijo if str(t).strip())
        extra = plantillas.escapar(extra)
        for p in f.pasos:
            if p.tipo not in ("descargar", "guardar_pagina") or p.desactivado:
                continue
            base = p.nombre or ("{nombre}{ext}" if p.tipo == "descargar" else "Pagina_{hoy:%Y-%m-%d}")
            if "{opcion" in base:
                continue
            p.nombre = base.replace("{ext}", extra + "{ext}", 1) if "{ext}" in base else base + extra
    return f, lineas


def combinaciones(flujo, elecciones):
    """[(cambios, sufijo)] — una ejecución por combinación.  Si nada tiene varias opciones, una sola (sufijo None)."""
    elecciones = normalizar_elecciones(elecciones)
    grupos, varian = [], []
    for i in sorted(elecciones):
        if not 0 <= i < len(flujo.pasos) or not es_filtro(flujo.pasos[i]):
            raise ErrorFiltros("El paso %d no es un filtro" % (i + 1))
        e = elecciones[i]
        if "valores" in e:
            vals = e["valores"]
            if flujo.pasos[i].tipo == "escribir":
                grupos.append([(i, {"valor": v}) for v in vals])
            else:
                grupos.append([(i, {"estrategia": "fija", "valor": v}) for v in vals])
            if len(vals) > 1:
                varian.append(i)
        else:
            grupos.append([(i, dict(e))])
    res = []
    for combo in itertools.product(*grupos) if grupos else [()]:
        cambios = {i: c for i, c in combo}
        sufijo = [cambios[i].get("valor") for i in varian] if varian else None
        res.append((cambios, sufijo))
    return res


def guardar_predeterminado(flujo, elecciones, nombres_filtros=None):
    """Escribe en los pasos la elección de cada filtro (una por filtro) y sus nombres.  Devuelve mensajes."""
    elecciones = normalizar_elecciones(elecciones)
    cambios = {}
    for i, e in elecciones.items():
        if "valores" in e:
            if len(e["valores"]) > 1:
                raise ErrorFiltros("Para guardarlo como predeterminado elige una sola opción en cada filtro")
            e = ({"valor": e["valores"][0]} if flujo.pasos[i].tipo == "escribir"
                 else {"estrategia": "fija", "valor": e["valores"][0]})
        cambios[i] = e
    nuevo, lineas = aplicar(flujo, cambios, nombres_filtros=nombres_filtros)
    for i, p in pasos_filtro(nuevo):
        n = (nombres_filtros or {}).get(i)
        if n and not mod_flujo.etiqueta_generica(n):
            p.filtro = n
    flujo.pasos = nuevo.pasos
    return lineas


# ------------------------------------------------------------------ línea de comandos
def _norm(t):
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


def resolver_cli(flujo, textos, mapas=None):
    """`--filtro NOMBRE=VALOR` (repetible) → elecciones {índice: {...}}.  NOMBRE = nombre del filtro (como en el panel,
    sin distinguir mayúsculas) o número de paso («6» o «paso 6»).  VALOR = el texto de la opción, o «más reciente»,
    «primera», «última»; en las fechas, el texto o plantilla ({ayer:%d/%m/%Y}).  Repetir el mismo filtro con valores
    distintos = una ejecución por valor."""
    filtros = dict(pasos_filtro(flujo))
    noms = nombres(flujo, mapas)
    elecciones = {}
    for texto in textos or []:
        if "=" not in texto:
            raise ErrorFiltros("--filtro debe ser «nombre=valor» (p. ej. --filtro \"Elegir corte=43 - 2026 (…)\")")
        clave, valor = texto.split("=", 1)
        clave, valor = clave.strip(), valor.strip()
        m = re.fullmatch(r"(?:paso\s*)?(\d+)", clave, re.IGNORECASE)
        if m:
            i = int(m.group(1)) - 1
            if i not in filtros:
                raise ErrorFiltros("El paso %s no es un filtro del reporte (filtros: %s)" % (
                    m.group(1), ", ".join("%d «%s»" % (k + 1, noms[k][0]) for k in filtros)))
        else:
            cands = [k for k in filtros if _norm(noms[k][0]) == _norm(clave)
                     or _norm(re.sub(r" \(paso \d+\)$", "", noms[k][0])) == _norm(clave)
                     or _norm(filtros[k].filtro) == _norm(clave) or _norm(filtros[k].objetivo) == _norm(clave)]
            if not cands:
                raise ErrorFiltros("No hay ningún filtro «%s» (filtros: %s)" % (
                    clave, ", ".join("%d «%s»" % (k + 1, noms[k][0]) for k in filtros)))
            if len(cands) > 1:
                raise ErrorFiltros("Hay varios filtros «%s»: usa el número de paso (%s)" % (
                    clave, ", ".join(str(k + 1) for k in cands)))
            i = cands[0]
        if not valor:
            raise ErrorFiltros("Falta el valor del filtro «%s»" % clave)
        p = filtros[i]
        est = _RX_ESTRATEGIA_CLI.get(_norm(valor)) if es_lista(p) else None
        previo = elecciones.get(i)
        if est:
            if previo:
                raise ErrorFiltros("El filtro «%s» está repetido" % clave)
            elecciones[i] = {"estrategia": est, "valor": ""}
        elif previo is not None:
            if "valores" not in previo:
                raise ErrorFiltros("El filtro «%s» está repetido" % clave)
            previo["valores"].append(valor)
        else:
            elecciones[i] = {"valores": [valor]}
    return elecciones
