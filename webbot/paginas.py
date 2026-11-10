"""«Páginas» (v3.2): una copia de la página de filtros de una web dentro del bot, para usarla cuando quieras.

Un mapa («Mapear página») dejaba de servir en cuanto se creaba el reporte.  Una **Página** lo conserva como un
formulario reutilizable: «Portal – Reportes» con Pestaña, Filtro por sistema, Seleccione reporte, Elegir corte y
Formato.  Eliges los valores y el bot (por detrás) abre la web, inicia sesión, llega a la página, pone esos filtros,
genera y descarga.  Otro día, otros valores (o varios: una ejecución por combinación), sin volver a mapear ni grabar.

Datos de una Página (`data`, JSON en la tabla `paginas`):
- `llegada`: pasos para llegar a la página (abrir la dirección, «Iniciar sesión» si hace falta —con Accesos—, clics y
  «pasar el ratón» de los menús antes de los filtros).  Son pasos normales del bot (`Paso.a_dict()`).
- `filtros`: [{id, nombre, tipo, selectores, pagina, marco, depende_de, depende_auto, depende_manual, en_nombre, defecto,
  pestanas (solo pestaña), formato (fecha), nombre_origen}] en el orden en que se rellenan.
  tipo = pestana | lista (propia: Vuetify, combobox…) | lista_nativa (<select>) | fecha | texto | casilla.
  `defecto` = {estrategia, valor} (listas y pestañas: fija | mas_reciente | primera | ultima | contiene), {valor} (fecha
  o texto; admite plantillas como {ayer:%d/%m/%Y}) o {marcado} (casilla).
  `depende_de` = ids de filtros anteriores que cambian sus opciones (detectado al leer, o puesto por el usuario).
- `accion`: cómo se obtiene el resultado: {tipo, generar {selectores, objetivo}, descargar {…}, menu [{…}],
  exportar {…}, formato, pestana, pasos}.  tipo = descargar (el botón descarga) | boton_descarga (Generar y luego
  «Descargar», que se habilita al terminar) | menu_exportar (ratón sobre «Vista Exportar» y clic en «Exportar») |
  guardar_pagina (el informe se abre en otra pestaña: PDF/CSV/HTML) | pasos (los pasos del reporte, tal cual).
- `nombre_archivo`: plantilla; por defecto «{pagina} - {variantes}» = el nombre de la Página y lo elegido en los filtros
  que varían (los de `en_nombre` y los que llevan varias opciones en esta ejecución).  Admite {Nombre del filtro},
  {hoy:%Y-%m-%d}… (lo elegido de verdad: con «la más reciente», el corte que eligió el bot).
- `favoritos`: [{nombre, valores {id: elección}, sin_navegador}] — «Mayorista + corte más reciente + Excel».
- `opciones` (tiempos, navegador…), `sin_navegador` (por defecto sí), `perfil` (carpeta del perfil del navegador).

Opciones de los filtros: tabla `opciones_pagina` por página + filtro + combinación de los filtros anteriores.  Se llenan
con el mapa, con cada ejecución (el bot lee entera cada lista por la que pasa), con «Actualizar opciones», al pedir una
lista que no se conoce («trayendo opciones…») y con la vigilancia.

Este módulo no importa playwright: `construir_flujo` crea un `Flujo` normal que ejecuta el `Ejecutor` de siempre
(esperas de carga, guardia de inicio de sesión, recuperación de menús…).  `ejecutar`/`leer_opciones` reciben
`crear_ejecutor(flujo, **extra)` de quien llama (interfaz, línea de comandos o vigilancia).
"""

import copy
import itertools
import os
import re
from urllib.parse import urlparse

from . import filtros as mod_filtros
from . import flujo as mod_flujo
from . import plantillas
from .flujo import Flujo, Paso

VERSION_DATOS = 1
TIPOS = ("pestana", "lista", "lista_nativa", "fecha", "texto", "casilla")
NOMBRES_TIPO = {"pestana": "Pestaña", "lista": "Lista", "lista_nativa": "Lista", "fecha": "Fecha", "texto": "Texto",
                "casilla": "Casilla"}
TIPOS_ACCION = {
    "descargar": "Un botón que descarga el archivo (p. ej. «Exportar»)",
    "boton_descarga": "«Generar» y después el botón «Descargar» (se habilita al terminar)",
    "menu_exportar": "«Generar» y un menú de exportar (ratón encima de «Vista Exportar» + «Exportar»)",
    "guardar_pagina": "«Ver reporte» abre el informe en otra pestaña: guardarlo como PDF, CSV o HTML",
    "pasos": "Los pasos del reporte tal cual (después de los filtros)",
}
PLANTILLA_DEFECTO = "{pagina} - {variantes}"
MAX_SIN_CONFIRMAR = mod_filtros.MAX_SIN_CONFIRMAR
MAX_EJECUCIONES = mod_filtros.MAX_EJECUCIONES
DIAS_NUEVA = mod_filtros.DIAS_NUEVA
FUENTES = dict(mod_filtros.FUENTES, traer="traídas al elegir otro valor", deteccion="de «Detectar dependencias»")
RX_GENERAR = re.compile(r"^(generar|ver reporte|ver informe|consultar|buscar|procesar|mostrar|ejecutar|aplicar|filtrar|"
                        r"search|apply|submit|enviar|aceptar)\b", re.IGNORECASE)
RX_DESCARGAR = re.compile(r"^(descargar|exportar|download|export|bajar)\b", re.IGNORECASE)
RX_FORMATO = re.compile(r"formato|format|export", re.IGNORECASE)
SELECTORES_DESCARGAR = ['role=button[name="Descargar"]', 'role=link[name="Descargar"]', 'button:has-text("Descargar")',
                        'a:has-text("Descargar")']
TOKENS_PAGINA = ("pagina", "variantes")
_SALTAR_SEGMENTO = {"pages", "page", "app", "web", "site", "index", "home", "default", "main", "inicio", "es", "en", "ui",
                    "portal", "modulos", "modules"}
_SI = {"si", "sí", "s", "true", "1", "marcada", "marcado", "yes", "on"}
_ESTRATEGIA_CLI = {"mas_reciente": "mas_reciente", "más reciente": "mas_reciente", "mas reciente": "mas_reciente",
                   "la más reciente": "mas_reciente", "la mas reciente": "mas_reciente", "primera": "primera",
                   "la primera": "primera", "ultima": "ultima", "última": "ultima", "la última": "ultima",
                   "la ultima": "ultima"}


class ErrorPagina(ValueError):
    """La Página o lo elegido no es válido."""


# ====================================================================== utilidades
def _norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def host_de(url):
    return mod_flujo.host_de(url)


def nombre_sugerido(url):
    """«Portal – Reportes» para https://portal.ejemplo.com/portal/#/reportes/corte (el primer nombre del sitio y el primer
    trozo de la dirección que dice algo); «Informes» para http://127.0.0.1/informes.html."""
    try:
        u = urlparse(url or "")
    except ValueError:
        return "Página"
    host = (u.hostname or "").lower()
    etiquetas = [x for x in host.split(".") if x and x != "www"]
    es_ip = bool(re.fullmatch(r"[\d.]+", host)) or host in ("localhost", "")
    trozos = []
    for s in re.split(r"[/#?&=]+", (u.path or "") + "/" + (u.fragment or "")):
        s = re.sub(r"\.(html?|aspx?|php|jsp|do)$", "", s, flags=re.IGNORECASE)
        if s and re.search(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]", s) and s.lower() not in _SALTAR_SEGMENTO and len(s) <= 40:
            trozos.append(s)
    base = "" if es_ip or not etiquetas else etiquetas[0]
    if not base and trozos:
        base = trozos.pop(0)
    trozos = [t for t in trozos if t.lower() != base.lower()]

    def bonito(t):
        t = re.sub(r"[_\-]+", " ", t).strip()
        if len(t) <= 3:
            return t.upper()
        t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
        return t[:1].upper() + t[1:]
    nombre = bonito(base) if base else "Página"
    if trozos:
        nombre += " – " + bonito(trozos[0])
    return nombre[:70]


def validar_nombre_filtro(nombre):
    n = re.sub(r"\s+", " ", nombre or "").strip().rstrip(":").strip()
    if not n:
        raise ErrorPagina("Escribe un nombre para el filtro")
    if len(n) > 60:
        raise ErrorPagina("El nombre del filtro es demasiado largo (máximo 60 caracteres)")
    if re.search(r"[{}:\"]", n):
        raise ErrorPagina("El nombre del filtro no puede llevar llaves, dos puntos ni comillas: «%s»" % n)
    if mod_flujo.etiqueta_generica(n):
        raise ErrorPagina("«%s» no sirve como nombre de un filtro: escribe lo que elige (p. ej. «Elegir corte»)" % n)
    if n.lower() in TOKENS_PAGINA or n in plantillas.RESERVADAS:
        raise ErrorPagina("«%s» es un nombre reservado: elige otro" % n)
    return n


def _paso_dict(p):
    return p.a_dict() if isinstance(p, Paso) else Paso.desde_dict(p).a_dict()


def _boton(d, lugar=None):
    """{selectores, objetivo, marco, pagina} limpio (o None).  v3.3: con la pestaña y el marco (iframe) del botón; si no
    los trae, los de `lugar` (p. ej. los del botón «Generar»: el menú de exportar está en el mismo marco)."""
    if not d:
        return None
    sels = d.get("selectores") or []
    if isinstance(sels, str):
        sels = [s for s in sels.splitlines() if s.strip()]
    sels = [str(s).strip() for s in sels if str(s).strip()]
    if not sels and d.get("texto"):
        sels = selectores_por_texto(d["texto"])
    if not sels:
        return None
    lugar = lugar or {}
    marco = d.get("marco") if d.get("marco") is not None else lugar.get("marco")
    pagina = d.get("pagina") if d.get("pagina") is not None else lugar.get("pagina")
    return {"selectores": sels, "objetivo": _norm(d.get("objetivo") or d.get("texto") or "")[:80],
            "marco": [str(m) for m in marco or []], "pagina": int(pagina or 0)}


def _donde(b):
    return {"marco": list((b or {}).get("marco") or []), "pagina": int((b or {}).get("pagina") or 0)}


def selectores_por_texto(texto, rol=None):
    """Selectores para un botón, enlace u opción de menú a partir de su texto («Descargar», «Vista Exportar»)."""
    t = _norm(texto).replace('"', '\\"')
    if not t:
        return []
    roles = [rol] if rol else ["button", "link", "menuitem"]
    return ['role=%s[name="%s"]' % (r, t) for r in roles] + [':text-is("%s")' % t, 'text="%s"' % t]


# ====================================================================== datos
def normalizar(data):
    """Copia de `data` con todos los campos (y los antiguos/ausentes con su valor por defecto)."""
    d = copy.deepcopy(data or {})
    d.setdefault("version", VERSION_DATOS)
    d["llegada"] = [_paso_dict(p) for p in d.get("llegada") or []]
    filtros = []
    for k, f in enumerate(d.get("filtros") or []):
        f = dict(f)
        f.setdefault("id", "f%d" % (k + 1))
        f["id"] = str(f["id"])
        if f.get("tipo") not in TIPOS:
            raise ErrorPagina("Tipo de filtro desconocido: %s" % f.get("tipo"))
        f["selectores"] = [str(s) for s in f.get("selectores") or [] if str(s).strip()]
        f.setdefault("nombre", NOMBRES_TIPO[f["tipo"]])
        f.setdefault("pagina", 0)
        f["marco"] = list(f.get("marco") or [])
        f["depende_de"] = [str(x) for x in f.get("depende_de") or []]
        f.setdefault("depende_auto", False)
        f.setdefault("depende_manual", False)
        f.setdefault("en_nombre", f["tipo"] in ("lista", "lista_nativa", "fecha"))
        f.setdefault("nombre_origen", "usuario")
        f.setdefault("defecto", {})
        if f["tipo"] == "pestana":
            f["pestanas"] = [{"texto": _norm(t.get("texto")), "selectores": list(t.get("selectores") or [])}
                             for t in f.get("pestanas") or [] if _norm(t.get("texto"))]
        filtros.append(f)
    d["filtros"] = filtros
    d["accion"] = dict(d.get("accion") or {})
    d["accion"].setdefault("tipo", "descargar")
    d["nombre_archivo"] = d.get("nombre_archivo") or PLANTILLA_DEFECTO
    d["favoritos"] = [dict(x) for x in d.get("favoritos") or [] if isinstance(x, dict) and x.get("nombre")]
    for fav in d["favoritos"]:
        fav["valores"] = {str(k): v for k, v in (fav.get("valores") or {}).items()}
        fav.setdefault("sin_navegador", True)
    ops = dict(mod_flujo.OPCIONES_DEFECTO)
    ops.update(d.get("opciones") or {})
    ops["repetir_dias"] = None
    d["opciones"] = ops
    d["sin_navegador"] = d.get("sin_navegador", True) is not False
    d["perfil"] = os.path.basename(str(d.get("perfil") or "")).strip()
    d.setdefault("url", "")
    d.setdefault("pestana_mapeada", "")
    return d


def filtro(data, fid):
    for f in data.get("filtros") or []:
        if f["id"] == str(fid):
            return f
    raise ErrorPagina("La página no tiene el filtro «%s»" % fid)


def es_lista(f):
    return f["tipo"] in ("lista", "lista_nativa", "pestana")


def nuevo_id(data):
    usados = {f["id"] for f in data.get("filtros") or []}
    n = 1
    while "f%d" % n in usados:
        n += 1
    return "f%d" % n


def validar(data, nombre=""):
    """Lista de problemas (vacía si la Página se puede ejecutar)."""
    p = []
    try:
        d = normalizar(data)
    except (ErrorPagina, mod_flujo.ErrorFlujo, TypeError, ValueError) as e:
        return [str(e)]
    if not d["llegada"]:
        p.append("Falta cómo llegar a la página (al menos «Abrir la página»)")
    for i, paso in enumerate(d["llegada"], 1):
        for pr in Paso.desde_dict(paso).problemas():
            p.append("Llegada, paso %d: %s" % (i, pr))
    nombres = {}
    for f in d["filtros"]:
        try:
            validar_nombre_filtro(f["nombre"])
        except ErrorPagina as e:
            p.append(str(e))
        if f["nombre"].lower() in nombres:
            p.append("Hay dos filtros llamados «%s»" % f["nombre"])
        nombres[f["nombre"].lower()] = f["id"]
        if f["tipo"] == "pestana" and not f.get("pestanas"):
            p.append("La pestaña «%s» no tiene opciones" % f["nombre"])
        elif f["tipo"] != "pestana" and not f["selectores"]:
            p.append("Al filtro «%s» le falta el selector" % f["nombre"])
        ids = [g["id"] for g in d["filtros"]]
        for dep in f["depende_de"]:
            if dep not in ids or ids.index(dep) >= ids.index(f["id"]):
                p.append("«%s» depende de un filtro que no va antes" % f["nombre"])
    try:
        pasos_accion(d)
    except ErrorPagina as e:
        p.append(str(e))
    err = validar_plantilla(d, d["nombre_archivo"])
    if err:
        p.append(err)
    return p


def validar_plantilla(data, plantilla):
    """None si la plantilla del nombre de archivo es válida; si no, el mensaje."""
    err = plantillas.validar(plantilla)
    if err:
        return "Nombre de los archivos: %s" % err
    nombres = {f["nombre"] for f in data.get("filtros") or []}
    for v in plantillas.variables_usadas(plantilla):
        if v not in nombres and v not in TOKENS_PAGINA:
            return ("Nombre de los archivos: no hay ningún filtro «%s». Puedes usar {pagina}, {variantes}, {hoy:%%Y-%%m-%%d} "
                    "o el nombre de un filtro entre llaves (%s)" % (v, ", ".join("{%s}" % n for n in sorted(nombres))))
    return None


# ====================================================================== crear desde un mapa
def nombres_desde_mapa(filtros_mapa):
    """{k: (nombre, origen)} para los filtros del mapa (sin «Open»/«Abrir»…: reglas de la 3.1).  origen = pagina (la
    etiqueta de la web) | deducido (por sus opciones: «Corte», «Periodo», «Formato») | numero («Lista 2»)."""
    res = {}
    cuenta = {}
    for f in sorted(filtros_mapa or [], key=lambda x: x.get("orden", 0)):
        t = f.get("tipo")
        if t in ("accion", None):
            continue
        if t == "pestana":
            res[int(f["k"])] = ("Pestaña", "pagina")
            continue
        clase = "Lista" if t in ("lista", "lista_nativa") else NOMBRES_TIPO.get(t, "Filtro")
        cuenta[clase] = cuenta.get(clase, 0) + 1
        et = _norm(f.get("etiqueta")).rstrip(":").strip()
        if et and not mod_flujo.etiqueta_generica(et) and not re.search(r"[{}\"]", et):
            res[int(f["k"])] = (et.replace(":", " ")[:60].strip(), "pagina")
            continue
        ded = mod_filtros.nombre_inferido(f.get("opciones") or []) if t in ("lista", "lista_nativa") else ""
        if t == "fecha":
            ded = "Fecha"
        if ded:
            res[int(f["k"])] = (ded, "deducido")
        else:
            res[int(f["k"])] = ("%s %d" % (clase, cuenta[clase]), "numero")
    # repetidos: el de la web conserva el nombre; los demás «Corte (2)»
    vistos = {}
    fuerza = {"pagina": 0, "deducido": 1, "numero": 2}
    for k, (n, o) in sorted(res.items(), key=lambda x: (fuerza.get(x[1][1], 9), x[0])):
        if n == "Pestaña" and o == "pagina":
            vistos.setdefault(n.lower(), 0)
            continue
        if n.lower() in vistos:
            vistos[n.lower()] += 1
            res[k] = ("%s (%d)" % (n, vistos[n.lower()] + 1), o)
        else:
            vistos[n.lower()] = 0
    return res


def botones_de_mapa(filtros_mapa):
    return [{"k": int(f["k"]), "etiqueta": _norm(f.get("etiqueta")), "selectores": list(f.get("selectores") or []),
             "descarga": bool(f.get("descarga")), "submenu": bool(f.get("submenu")), "marco": list(f.get("marco") or []),
             "pagina": int(f.get("pagina") or 0)} for f in filtros_mapa or [] if f.get("tipo") == "accion"]


def _de_boton(b):
    return {"selectores": list(b["selectores"]), "objetivo": b["etiqueta"], "marco": list(b.get("marco") or []),
            "pagina": int(b.get("pagina") or 0)}


def adivinar_accion(filtros_mapa, pasos_despues=None):
    """Cómo se obtiene el resultado: con los pasos del reporte que iban después de los filtros (si los hay) y los botones
    del mapa («Generar»/«Ver Reporte»/«Consultar» y «Descargar»/«Exportar»)."""
    pasos = [p if isinstance(p, Paso) else Paso.desde_dict(p) for p in pasos_despues or []]
    pasos = [p for p in pasos if not p.desactivado]
    archivo = next((i for i, p in enumerate(pasos) if p.tipo in ("descargar", "guardar_pagina")), None)
    if archivo is not None:
        # desde el primer «Generar/Consultar/Ver reporte…» (o desde los «pasar el ratón» justo antes del archivo): así no
        # se repiten clics grabados en los filtros, que ya pone la Página
        inicio = next((i for i, p in enumerate(pasos[:archivo + 1]) if p.tipo in ("clic", "descargar") and (
            RX_GENERAR.match(p.objetivo or "") or RX_DESCARGAR.match(p.objetivo or ""))), None)
        if inicio is None:
            inicio = archivo
            while inicio > 0 and pasos[inicio - 1].tipo in ("pasar_raton", "esperar_elemento", "esperar_texto",
                                                            "esperar_segundos"):
                inicio -= 1
        return {"tipo": "pasos", "pasos": [p.a_dict() for p in pasos[inicio:]]}
    botones = botones_de_mapa(filtros_mapa)
    gen = next((b for b in botones if RX_GENERAR.match(b["etiqueta"])), None)
    desc = next((b for b in botones if (RX_DESCARGAR.match(b["etiqueta"]) or b["descarga"]) and not b["submenu"]), None)
    sub = next((b for b in botones if b["submenu"]), None)       # v3.3: «Vista Exportar» (menú de DevExpress)
    clic_gen = next((p for p in pasos if p.tipo == "clic" and RX_GENERAR.match(p.objetivo or "")), None)
    if clic_gen is not None and gen is None:
        gen = {"etiqueta": clic_gen.objetivo, "selectores": list(clic_gen.selectores), "marco": list(clic_gen.marco),
               "pagina": clic_gen.pagina}
    if gen and desc:
        return {"tipo": "boton_descarga", "generar": _de_boton(gen), "descargar": _de_boton(desc)}
    if desc:
        return {"tipo": "descargar", "generar": _de_boton(desc)}
    if gen and sub:
        # ERP: «Consultar» y después el menú «Vista Exportar» → «Exportar» (con el ratón encima)
        return {"tipo": "menu_exportar", "generar": _de_boton(gen), "menu": [_de_boton(sub)],
                "exportar": dict(_de_boton(sub), selectores=selectores_por_texto("Exportar"), objetivo="Exportar")}
    if gen and clic_gen is not None:
        # el reporte solo pulsaba «Generar» (Portal): el archivo sale con el botón «Descargar» que se habilita después
        return {"tipo": "boton_descarga", "generar": _de_boton(gen),
                "descargar": dict(_de_boton(gen), selectores=list(SELECTORES_DESCARGAR), objetivo="Descargar")}
    if gen and re.match(r"^ver (reporte|informe)", gen["etiqueta"], re.IGNORECASE):
        # Informes: «Ver Reporte» abre el informe en otra pestaña → se guarda (la pestaña siguiente a la del formulario)
        return {"tipo": "guardar_pagina", "generar": _de_boton(gen), "formato": "pdf",
                "pestana": int(gen.get("pagina") or 0) + 1}
    if gen:
        return {"tipo": "descargar", "generar": _de_boton(gen)}
    return {"tipo": "descargar", "generar": None}


def _defecto_de_mapa(f, previo=None):
    """Valor por defecto de un filtro del mapa (o el del paso del reporte, `previo` = Paso)."""
    t = f["tipo"]
    if previo is not None:
        if previo.tipo == "elegir_opcion":
            est = previo.estrategia or "fija"
            return {"estrategia": est, "valor": mod_filtros.desescapar(previo.valor) if est in ("fija", "contiene") else ""}
        if previo.tipo == "seleccionar":
            return {"estrategia": "fija", "valor": previo.etiqueta or mod_filtros.desescapar(previo.valor)}
        if previo.tipo == "escribir":
            return {"valor": previo.valor or ""}
        if previo.tipo == "marcar":
            return {"marcado": bool(previo.marcado)}
    if t in ("lista", "lista_nativa"):
        ops = f.get("opciones") or []
        if ops and mod_flujo.parece_cronologica(ops):
            return {"estrategia": "mas_reciente", "valor": ""}
        if _norm(f.get("valor")):
            return {"estrategia": "fija", "valor": _norm(f["valor"])}
        return {"estrategia": "primera", "valor": ""}
    if t == "fecha":
        from .mapeador import formato_fecha
        return {"valor": "{hoy:%s}" % formato_fecha(f)}
    if t == "texto":
        return {"valor": plantillas.escapar(f.get("valor") or "")}
    if t == "casilla":
        return {"marcado": bool(f.get("marcado"))}
    return {}


def desde_mapa(filtros_mapa, url="", incluir=None, nombres=None, llegada=None, accion=None, dependencias=None,
               pasos_reporte=None, opciones=None, perfil=""):
    """Crea los datos de una Página a partir de un mapa.  Devuelve (data, {k del mapa: id del filtro}).

    - `incluir`: los k del mapa que se traen (por defecto, todos menos los botones).
    - `nombres`: {k: nombre} que puso el usuario (si no, `nombres_desde_mapa`).
    - `llegada`: pasos (dicts) para llegar a la página (si no, solo «Abrir la página» `url`).
    - `accion`: dict (si no, `adivinar_accion`).  `dependencias`: {k_hijo: [k_padre…]} detectadas en el navegador.
    - `pasos_reporte`: [(k, Paso)] pasos del reporte que ya elegían algo en esos filtros (valores por defecto)."""
    filtros_mapa = [dict(f) for f in filtros_mapa or []]
    por_k = {int(f["k"]): f for f in filtros_mapa}
    if incluir is None:
        incluir = [int(f["k"]) for f in filtros_mapa if f.get("tipo") != "accion"]
    incluir = [int(k) for k in incluir if int(k) in por_k and por_k[int(k)].get("tipo") != "accion"]
    auto = nombres_desde_mapa(filtros_mapa)
    nombres = {int(k): v for k, v in (nombres or {}).items() if _norm(v)}
    previos = {int(k): p for k, p in (pasos_reporte or [])}
    data = {"version": VERSION_DATOS, "url": url, "filtros": [], "favoritos": [], "nombre_archivo": PLANTILLA_DEFECTO,
            "llegada": [_paso_dict(p) for p in llegada] if llegada else ([Paso("abrir_url", url=url).a_dict()] if url else []),
            "accion": dict(accion) if accion else adivinar_accion(filtros_mapa), "opciones": dict(opciones or {}),
            "sin_navegador": True, "perfil": perfil or ""}
    k_a_id = {}
    # 1) las pestañas, juntas en un filtro «Pestaña»
    tabs = sorted([por_k[k] for k in incluir if por_k[k]["tipo"] == "pestana"], key=lambda x: x.get("orden", 0))
    if tabs:
        activa = next((t for t in tabs if t.get("activo")), tabs[0])
        k0 = int(tabs[0]["k"])
        f = {"id": "f1", "tipo": "pestana", "nombre": nombres.get(k0) or "Pestaña", "selectores": [],
             "pagina": int(tabs[0].get("pagina") or 0), "marco": list(tabs[0].get("marco") or []),
             "pestanas": [{"texto": _norm(t.get("etiqueta")), "selectores": list(t.get("selectores") or [])} for t in tabs],
             "defecto": {"estrategia": "fija", "valor": _norm(activa.get("etiqueta"))}, "en_nombre": False,
             "nombre_origen": "usuario" if nombres.get(k0) else "pagina", "depende_de": []}
        data["filtros"].append(f)
        data["pestana_mapeada"] = _norm(activa.get("etiqueta"))
        for t in tabs:
            k_a_id[int(t["k"])] = f["id"]
    # 2) los demás, en el orden de la página
    resto = sorted([por_k[k] for k in incluir if por_k[k]["tipo"] != "pestana"], key=lambda x: x.get("orden", 0))
    for m in resto:
        k = int(m["k"])
        fid = nuevo_id(data)
        nombre, origen = (nombres[k], "usuario") if k in nombres else auto.get(k, ("Filtro", "numero"))
        tipo = m["tipo"]
        f = {"id": fid, "tipo": tipo, "nombre": nombre, "nombre_origen": origen, "selectores": list(m.get("selectores") or []),
             "defecto": _defecto_de_mapa(m, previos.get(k)), "depende_de": [], "etiqueta_pagina": _norm(m.get("etiqueta")),
             "pagina": int(m.get("pagina") or 0), "marco": list(m.get("marco") or [])}      # v3.3: pestaña y marco
        if tipo == "texto" and (m.get("busqueda") or {}).get("selectores"):
            f["busqueda"] = {k2: m["busqueda"].get(k2) for k2 in ("selectores", "etiqueta", "filas", "tabla")
                             if m["busqueda"].get(k2) is not None}
        if tipo == "fecha":
            from .mapeador import formato_fecha
            f["formato"] = formato_fecha(m)
            f["tipo_campo"] = m.get("tipo_campo") or ""
        f["en_nombre"] = tipo in ("lista", "lista_nativa", "fecha") and not (
            RX_FORMATO.search(nombre) or mod_filtros.nombre_inferido(m.get("opciones") or []) == "Formato")
        data["filtros"].append(f)
        k_a_id[k] = fid
    # listas repetidas (la misma lista arriba en la barra y en el formulario): solo la última va en el nombre del archivo
    vistas = {}
    for m in resto:
        ops = tuple(m.get("opciones") or [])
        if len(ops) >= 2 and m["tipo"] in ("lista", "lista_nativa"):
            if ops in vistas:
                filtro(data, vistas[ops])["en_nombre"] = False
            vistas[ops] = k_a_id[int(m["k"])]
    # 3) dependencias detectadas en el navegador
    for kh, kps in (dependencias or {}).items():
        fid = k_a_id.get(int(kh))
        if fid is None:
            continue
        f = filtro(data, fid)
        ids = [g["id"] for g in data["filtros"]]
        deps = [k_a_id[int(kp)] for kp in kps if int(kp) in k_a_id and ids.index(k_a_id[int(kp)]) < ids.index(fid)]
        f["depende_de"] = list(dict.fromkeys(deps))
        f["depende_auto"] = bool(f["depende_de"])
    for f in data["filtros"]:
        if mod_flujo.etiqueta_generica(f["nombre"]):
            f["nombre"], f["nombre_origen"] = "Filtro %s" % f["id"][1:], "numero"
    return normalizar(data), k_a_id


def lecturas_de_mapa(filtros_mapa, k_a_id):
    """[(id del filtro, opciones, padres)] de las listas del mapa (padres = lo que tenían las listas anteriores)."""
    res, padres = [], {}
    for m in sorted(filtros_mapa or [], key=lambda x: x.get("orden", 0)):
        fid = k_a_id.get(int(m["k"]))
        if fid is None or m.get("tipo") not in ("lista", "lista_nativa"):
            continue
        if m.get("opciones"):
            res.append((fid, list(m["opciones"]), dict(padres)))
        if _norm(m.get("valor")):
            padres[fid] = _norm(m["valor"])
    return res


def pasos_tras_filtros(flujo, hasta, filtros_mapa):
    """Enlaza los pasos del reporte (desde `hasta`) con los filtros del mapa por sus selectores.  Devuelve
    ([(k, paso)] de los filtros que el reporte ya elegía, {k usados}, pasos que van después del último filtro)."""
    pasos_reporte, usados, ultimo = [], set(), int(hasta) - 1
    for i, p in enumerate(flujo.pasos[int(hasta):], int(hasta)):
        if p.desactivado:
            continue
        sels = set(p.selectores or [])
        for m in filtros_mapa or []:
            if m.get("tipo") == "accion" or int(m["k"]) in usados:
                continue
            if sels and sels & set(m.get("selectores") or []):
                usados.add(int(m["k"]))
                if m.get("tipo") != "pestana":
                    pasos_reporte.append((int(m["k"]), p))
                ultimo = max(ultimo, i)
                break
    despues = [p for p in flujo.pasos[ultimo + 1:] if not p.desactivado]
    return pasos_reporte, usados, despues


def convertir_reporte_y_mapa(flujo, mapa):
    """La Página de un reporte creado con «Mapear página» y su mapa (v3.2: el «Reporte mapeado» de Portal pasa a ser la
    Página «Portal – Reportes»).  La llegada = los pasos del reporte antes del primer filtro; los valores por defecto =
    lo que elegían sus pasos; la acción = sus pasos después de los filtros o, si solo pulsaba «Generar», Generar +
    «Descargar».  Devuelve (nombre sugerido, data, k_a_id, lecturas)."""
    from .mapeador import punto_de_mapeo
    filtros_mapa = mapa.get("filtros") or []
    hasta = punto_de_mapeo(flujo)
    llegada = [p for p in flujo.pasos[:hasta]]
    pasos_reporte, usados, despues = pasos_tras_filtros(flujo, hasta, filtros_mapa)
    accion = adivinar_accion(filtros_mapa, despues)
    url = mapa.get("url") or flujo.url
    nombres_reporte = {}
    for k, p in pasos_reporte:
        n = p.filtro or ("" if mod_flujo.etiqueta_generica(p.objetivo) else p.objetivo)
        m = next((x for x in filtros_mapa if int(x["k"]) == k), {})
        if n and not mod_flujo.etiqueta_generica(n) and mod_flujo.etiqueta_generica(m.get("etiqueta") or "Open"):
            nombres_reporte[k] = n
    # se traen los filtros del mapa que el reporte usaba (y las pestañas); si el reporte no usaba ninguno, todos
    incluir = sorted(usados | {int(m["k"]) for m in filtros_mapa if m.get("tipo") == "pestana"})
    if not [k for k, _p in pasos_reporte]:
        incluir = None
    data, k_a_id = desde_mapa(filtros_mapa, url=url, incluir=incluir, nombres=None, llegada=llegada, accion=accion,
                              pasos_reporte=pasos_reporte, opciones=dict(flujo.opciones))
    for k, n in nombres_reporte.items():          # el nombre que el usuario puso en el paso (si la web decía «Open»)
        fid = k_a_id.get(k)
        if fid and not any(f["nombre"].lower() == n.lower() for f in data["filtros"]):
            try:
                filtro(data, fid)["nombre"] = validar_nombre_filtro(n)
                filtro(data, fid)["nombre_origen"] = "usuario"
            except ErrorPagina:
                pass
    return nombre_sugerido(url), data, k_a_id, lecturas_de_mapa(filtros_mapa, k_a_id)


def corregir_nombres(data, filtros_mapa):
    """Pone la etiqueta de la web a los filtros con un nombre deducido o numerado («Lista 2», «Corte (2)») cuando un
    mapa nuevo de la página (al «Actualizar opciones») la encuentra («Seleccione reporte»).  Devuelve los cambios."""
    cambios = []
    usados = {f["nombre"].lower() for f in data["filtros"]}
    for f in data["filtros"]:
        if f.get("nombre_origen") not in ("deducido", "numero") or f["tipo"] == "pestana":
            continue
        sels = set(f["selectores"])
        m = next((x for x in filtros_mapa or [] if x.get("tipo") not in ("accion", "pestana")
                  and sels & set(x.get("selectores") or [])), None)
        if m is None:
            continue
        et = _norm(m.get("etiqueta")).rstrip(":").strip()
        try:
            et = validar_nombre_filtro(et)
        except ErrorPagina:
            continue
        if et.lower() in usados:
            continue
        cambios.append("«%s» → «%s»" % (f["nombre"], et))
        usados.discard(f["nombre"].lower())
        usados.add(et.lower())
        f["nombre"], f["nombre_origen"], f["etiqueta_pagina"] = et, "pagina", et
    return cambios


# ====================================================================== elecciones
def defecto(f):
    d = dict(f.get("defecto") or {})
    if f["tipo"] in ("lista", "lista_nativa", "pestana"):
        d.setdefault("estrategia", "fija" if d.get("valor") else ("mas_reciente" if f["tipo"] != "pestana" else "primera"))
        d.setdefault("valor", "")
    elif f["tipo"] == "casilla":
        d.setdefault("marcado", True)
    else:
        d.setdefault("valor", "")
    return d


def normalizar_eleccion(f, e):
    """Elección de un filtro en su forma canónica: {estrategia, valor} | {valores: [...]} | {valor} | {marcado}."""
    if e is None:
        return defecto(f)
    if isinstance(e, str):
        e = {"valor": e} if f["tipo"] in ("fecha", "texto") else {"estrategia": "fija", "valor": e}
    if not isinstance(e, dict):
        raise ErrorPagina("Elección no válida para «%s»" % f["nombre"])
    vals = e.get("valores")
    if isinstance(vals, list):
        vals = list(dict.fromkeys(str(v) for v in vals if str(v).strip()))
        if vals:
            if f["tipo"] == "casilla":
                raise ErrorPagina("Una casilla no admite varias opciones")
            return {"valores": vals}
    t = f["tipo"]
    if t == "casilla":
        if "marcado" in e:
            return {"marcado": bool(e["marcado"])}
        return {"marcado": str(e.get("valor") or "").strip().lower() in _SI}
    if t in ("fecha", "texto"):
        return {"valor": "" if e.get("valor") is None else str(e.get("valor"))}
    est = str(e.get("estrategia") or "fija")
    if est not in mod_flujo.ESTRATEGIAS:
        raise ErrorPagina("Estrategia no válida: %s" % est)
    return {"estrategia": est, "valor": "" if e.get("valor") is None else str(e.get("valor"))}


def seleccion_base(data, favorito=None, seleccion=None):
    """Lo que se usa en cada filtro: el valor por defecto, encima el del favorito y encima lo elegido ahora."""
    res = {}
    fav = buscar_favorito(data, favorito) if favorito else None
    for f in data["filtros"]:
        e = None
        if fav is not None and f["id"] in fav["valores"]:
            e = fav["valores"][f["id"]]
        if seleccion and f["id"] in seleccion and seleccion[f["id"]] is not None:
            e = seleccion[f["id"]]
        res[f["id"]] = normalizar_eleccion(f, e)
    desconocidos = [k for k in (seleccion or {}) if k not in res]
    if desconocidos:
        raise ErrorPagina("La página no tiene el filtro «%s»" % desconocidos[0])
    return res


def combinaciones(data, seleccion):
    """[(elección única por filtro, ids de los filtros con varias opciones)] — una ejecución por combinación."""
    grupos, varian = [], []
    for f in data["filtros"]:
        e = seleccion.get(f["id"]) or defecto(f)
        if "valores" in e:
            if f["tipo"] in ("fecha", "texto"):
                grupos.append([(f["id"], {"valor": v}) for v in e["valores"]])
            else:
                grupos.append([(f["id"], {"estrategia": "fija", "valor": v}) for v in e["valores"]])
            if len(e["valores"]) > 1:
                varian.append(f["id"])
        else:
            grupos.append([(f["id"], dict(e))])
    return [({fid: c for fid, c in combo}, list(varian)) for combo in itertools.product(*grupos)] if grupos else [({}, [])]


def describir_eleccion(f, e):
    if f["tipo"] == "casilla":
        return "marcada" if e.get("marcado") else "sin marcar"
    if f["tipo"] in ("fecha", "texto"):
        return "«%s»" % (e.get("valor") or "")
    if "valores" in e:
        return ", ".join("«%s»" % v for v in e["valores"])
    return mod_filtros.describir_cambio(Paso("elegir_opcion"), e)


# ====================================================================== flujo
def paso_de_filtro(f, e):
    t = f["tipo"]
    nombre = f["nombre"]
    if t == "pestana":
        est, valor = e.get("estrategia") or "fija", e.get("valor") or ""
        textos = [x["texto"] for x in f["pestanas"]]
        k = mod_flujo.elegir_indice(textos, est, valor)
        if k is None:
            raise ErrorPagina("La pestaña «%s» no existe (pestañas: %s)" % (valor, ", ".join(textos)))
        return Paso("clic", selectores=list(f["pestanas"][k]["selectores"]), objetivo=textos[k], filtro=nombre,
                    pagina=int(f.get("pagina") or 0), marco=list(f.get("marco") or []))
    comunes = dict(selectores=list(f["selectores"]), objetivo=nombre, filtro=nombre, pagina=int(f.get("pagina") or 0),
                   marco=list(f.get("marco") or []))
    if t in ("lista", "lista_nativa"):
        est, valor = e.get("estrategia") or "fija", e.get("valor") or ""
        # v3.8: sin opción no es un error: el ejecutor salta el paso y lo dice en el registro
        err = plantillas.validar(valor) if est == "por_fecha" else None
        if err:
            raise ErrorPagina("%s: %s" % (nombre, err))
        return Paso("elegir_opcion", estrategia=est,
                    valor=plantillas.escapar(valor) if est == "fija" else (valor if est in ("contiene", "por_fecha") else ""), **comunes)
    if t == "fecha":
        valor = e.get("valor") or ""
        err = plantillas.validar(valor)
        if err:
            raise ErrorPagina("%s: %s" % (nombre, err))
        return Paso("escribir", valor=valor, fecha_directa=True, **comunes)
    if t == "texto":
        valor = e.get("valor") or ""
        err = plantillas.validar(valor)
        if err:
            raise ErrorPagina("%s: %s" % (nombre, err))
        return Paso("escribir", valor=valor, **comunes)
    if t == "casilla":
        comunes.pop("filtro")
        return Paso("marcar", marcado=bool(e.get("marcado")), **comunes)
    raise ErrorPagina("Tipo de filtro desconocido: %s" % t)


def opcion_de_fila(celdas):
    """Texto de una fila de la ventanita de búsqueda como opción: «1110209 · Asociacion Ejemplo»."""
    return " · ".join(str(c) for c in list(celdas)[:3] if str(c).strip())


def celda_de_busqueda(busqueda, valor):
    """La celda en la que se hace clic para elegir `valor` en la ventanita de búsqueda (o None si no es una fila
    conocida: entonces se escribe el texto)."""
    v = _norm(valor)
    for fila in (busqueda or {}).get("filas") or []:
        celdas = [_norm(c) for c in fila if _norm(c)]
        if not celdas:
            continue
        if v == opcion_de_fila(celdas) or v == celdas[0]:
            return celdas[0]
        if v in celdas:
            return v
    return None


def pasos_de_filtro(f, e):
    """v3.3: los pasos de un filtro.  Un campo «con búsqueda» (lupa que abre una ventanita con una tabla, como «Cuenta
    No.» de Informes) con una fila conocida: clic en la lupa + clic en la fila.  Los demás: `paso_de_filtro`."""
    p = paso_de_filtro(f, e)
    b = f.get("busqueda") or {}
    valor = (e or {}).get("valor") or ""
    if f["tipo"] != "texto" or not b.get("selectores") or not valor.strip():
        return [p]
    celda = celda_de_busqueda(b, valor)
    if celda is None:
        return [p]
    lit = celda.replace("\\", "\\\\").replace('"', '\\"')
    sels = ([b["tabla"] + ' td:text-is("%s")' % lit] if b.get("tabla") else []) + ['td:text-is("%s")' % lit]
    donde = {"pagina": int(f.get("pagina") or 0), "marco": list(f.get("marco") or [])}
    return [Paso("clic", selectores=list(b["selectores"]), objetivo="Buscar %s" % f["nombre"], **donde),
            Paso("clic", selectores=sels, objetivo=celda, **donde)]


def _texto_estatico(f, e, hoy=None):
    """Valor de {Nombre del filtro} antes de ejecutar (el ejecutor lo cambia por lo que elija de verdad)."""
    if f["tipo"] == "casilla":
        return "sí" if e.get("marcado") else "no"
    if f["tipo"] in ("fecha", "texto"):
        try:
            return plantillas.renderizar(e.get("valor") or "", hoy=hoy)
        except plantillas.ErrorPlantilla:
            return e.get("valor") or ""
    if (e.get("estrategia") or "fija") == "fija":
        return e.get("valor") or ""
    if f["tipo"] == "pestana":
        textos = [x["texto"] for x in f["pestanas"]]
        k = mod_flujo.elegir_indice(textos, e.get("estrategia"), e.get("valor") or "")
        return textos[k] if k is not None else ""
    return ""


def plantilla_archivo(data, varian=()):
    """La plantilla del nombre de los archivos con {variantes} ya cambiado por los filtros que van en el nombre."""
    base = data.get("nombre_archivo") or PLANTILLA_DEFECTO
    nombres = [f["nombre"] for f in data["filtros"] if f.get("en_nombre") or f["id"] in varian]
    trozo = " - ".join("{%s}" % n for n in nombres)
    if "{variantes}" in base:
        if trozo:
            base = base.replace("{variantes}", trozo)
        else:
            base = re.sub(r"\s*[-–_]?\s*\{variantes\}", "", base)
    elif varian:
        faltan = [f["nombre"] for f in data["filtros"] if f["id"] in varian and "{%s}" % f["nombre"] not in base]
        if faltan:          # varias opciones en un filtro que no sale en el nombre: se añade para que no se pisen
            extra = " - " + " - ".join("{%s}" % n for n in faltan)
            base = base.replace("{ext}", extra + "{ext}", 1) if "{ext}" in base else base + extra
    return base.strip() or "{pagina}"


def vista_archivo(data, nombre, plantilla=None, hoy=None, carpeta=None, carpeta_forzada=None, raiz=None):
    """(v3.7) (archivo, carpeta) de ejemplo para «Se guardará como: …» en «Configurar esta página» y al guardar el mapa
    como Página: el mismo nombre que pondría `pasos_accion` (con «{variantes}» = los filtros marcados «en el nombre»),
    con los valores por defecto de los filtros (los que dependen de lo que haya en la web: «Nombre del filtro» entre
    comillas).  `plantilla` / `carpeta` = lo escrito (sin guardar todavía); None = lo de la Página.  Lanza ErrorPagina
    si el nombre no es válido."""
    d = dict(data, nombre_archivo=(data.get("nombre_archivo") if plantilla is None else plantilla) or PLANTILLA_DEFECTO)
    err = validar_plantilla(d, d["nombre_archivo"])
    if err:
        raise ErrorPagina(err)
    variables = {"pagina": nombre or "Página"}
    for f in d.get("filtros") or []:
        try:
            v = _texto_estatico(f, normalizar_eleccion(f, None), hoy)
        except (ErrorPagina, KeyError, TypeError):
            v = ""
        variables[f["nombre"]] = v or "«%s»" % f["nombre"]
    base = plantilla_archivo(d)
    a = d.get("accion") or {}
    tipo = "guardar_pagina" if a.get("tipo") == "guardar_pagina" else "descargar"
    texto = base if tipo == "guardar_pagina" or "{ext}" in base else base + "{ext}"
    if carpeta is None:
        carpeta = (d.get("opciones") or {}).get("carpeta_descargas") or ""
    try:
        return mod_flujo.vista_archivo(texto, tipo, reporte=nombre, variables=variables, hoy=hoy, carpeta=carpeta,
                                       formato=a.get("formato") or "pdf", carpeta_forzada=carpeta_forzada, raiz=raiz)
    except plantillas.ErrorPlantilla as e:
        raise ErrorPagina("Nombre de los archivos: %s" % e)


def pasos_accion(data, varian=()):
    """Pasos que producen el resultado (con el nombre de archivo de la Página)."""
    a = data.get("accion") or {}
    t = a.get("tipo") or "descargar"
    plantilla = plantilla_archivo(data, varian)
    con_ext = plantilla if "{ext}" in plantilla else plantilla + "{ext}"
    gen = _boton(a.get("generar"))
    if t not in TIPOS_ACCION:
        raise ErrorPagina("Acción desconocida: %s" % t)
    if t == "pasos":
        pasos = [Paso.desde_dict(d) for d in a.get("pasos") or []]
        if not any(p.tipo in ("descargar", "guardar_pagina") and not p.desactivado for p in pasos):
            raise ErrorPagina("Los pasos de la acción no descargan ni guardan nada")
        for p in pasos:
            if p.tipo == "descargar":
                p.nombre = con_ext
            elif p.tipo == "guardar_pagina":
                p.nombre = plantilla
        return pasos
    if t == "descargar":
        b = gen or _boton(a.get("descargar"))
        if b is None:
            raise ErrorPagina("Falta el botón que descarga el archivo (acción de la página)")
        return [Paso("descargar", selectores=b["selectores"], objetivo=b["objetivo"], nombre=con_ext, **_donde(b))]
    pasos = []
    if gen is not None:
        pasos.append(Paso("clic", selectores=gen["selectores"], objetivo=gen["objetivo"], **_donde(gen)))
    if t == "boton_descarga":
        if gen is None:
            raise ErrorPagina("Falta el botón «Generar» (acción de la página)")
        b = _boton(a.get("descargar"), gen) or dict(_donde(gen), selectores=list(SELECTORES_DESCARGAR), objetivo="Descargar")
        pasos.append(Paso("descargar", selectores=b["selectores"], objetivo=b["objetivo"], nombre=con_ext, **_donde(b)))
    elif t == "menu_exportar":
        menu = [m for m in (_boton(x, gen) for x in a.get("menu") or []) if m]
        exp = _boton(a.get("exportar"), gen)
        if exp is None:
            raise ErrorPagina("Falta la opción «Exportar» del menú (acción de la página)")
        for m in menu:
            pasos.append(Paso("pasar_raton", selectores=m["selectores"], objetivo=m["objetivo"], **_donde(m)))
        pasos.append(Paso("descargar", selectores=exp["selectores"], objetivo=exp["objetivo"], nombre=con_ext,
                          **_donde(exp)))
    elif t == "guardar_pagina":
        if gen is None:
            raise ErrorPagina("Falta el botón que abre el informe («Ver Reporte»)")
        formato = (a.get("formato") or "pdf").lower()
        if formato not in mod_flujo.FORMATOS_PAGINA:
            raise ErrorPagina("Formato no válido: %s (pdf, csv o html)" % formato)
        pasos.append(Paso("guardar_pagina", formato=formato, nombre=plantilla, pagina=int(a.get("pestana", 1) or 0),
                          timeout=a.get("timeout") or None))
    return pasos


def construir_flujo(data, nombre, eleccion, varian=(), hasta=None, hoy=None):
    """Flujo normal del bot para una ejecución: llegada + un paso por filtro + la acción.  `eleccion`: {id: elección
    única}; `hasta` = id de un filtro: solo hasta ese filtro (incluido) y sin la acción («Actualizar opciones»,
    «trayendo opciones…»).  Devuelve (flujo, {id del filtro: índice del paso})."""
    pasos = [Paso.desde_dict(d) for d in data["llegada"]]
    indices, variables = {}, {"pagina": nombre}
    for f in data["filtros"]:
        e = normalizar_eleccion(f, eleccion.get(f["id"]))
        if "valores" in e:
            e = combinaciones({"filtros": [f]}, {f["id"]: e})[0][0][f["id"]]
        indices[f["id"]] = len(pasos)
        pasos.extend(pasos_de_filtro(f, e))
        variables[f["nombre"]] = _texto_estatico(f, e, hoy)
        if hasta is not None and f["id"] == str(hasta):
            break
    if hasta is None:
        pasos += pasos_accion(data, varian)
    fl = Flujo(nombre=nombre, url=data.get("url") or next((p.url for p in pasos if p.tipo == "abrir_url"), ""),
               variables=variables, opciones=dict(data["opciones"]), pasos=pasos)
    return fl, indices


def ultimo_filtro_lista(data):
    listas = [f["id"] for f in data["filtros"] if f["tipo"] in ("lista", "lista_nativa")]
    return listas[-1] if listas else (data["filtros"][-1]["id"] if data["filtros"] else None)


# ====================================================================== opciones guardadas
def lecturas_de_resultado(indices, res):
    """[(id del filtro, opciones, padres {id: texto})] de las listas que leyó una ejecución."""
    inv = {i: fid for fid, i in indices.items()}
    out = []
    for i, d in (getattr(res, "opciones_leidas", None) or {}).items():
        fid = inv.get(int(i))
        if fid is None:
            continue
        padres = {inv[int(k)]: v for k, v in (d.get("padres") or {}).items() if int(k) in inv}
        out.append((fid, list(d.get("opciones") or []), padres))
    return out


def buscar_opciones(filas, depende_de, padres):
    """(fila o None, exacta).  Sin dependencias vale la lista más reciente; con dependencias, la de esa combinación de
    los filtros de los que depende (si no hay, la última conocida y exacta = False)."""
    if not filas:
        return None, False
    if not depende_de:
        return filas[0], True
    for fila in filas:
        if all(fila["padres"].get(p) == padres.get(p) for p in depende_de):
            return fila, True
    return filas[0], False


def _nuevas_llegadas(a, b):
    """True si dos listas solo se diferencian en unas pocas opciones añadidas (llegó un corte nuevo: no es dependencia)."""
    sa, sb = set(a), set(b)
    if sa <= sb:
        return len(sb - sa) <= 3
    if sb <= sa:
        return len(sa - sb) <= 3
    return False


def detectar_dependencias(data, filas):
    """Marca `depende_de` en las listas cuyas opciones cambian con lo elegido en un filtro anterior (según las listas
    guardadas).  No toca las que el usuario configuró a mano.  Devuelve los mensajes de lo que cambió."""
    cambios = []
    orden = [f["id"] for f in data["filtros"]]
    por = {}
    for fila in filas or []:
        por.setdefault(fila["filtro"], []).append(fila)
    for f in data["filtros"]:
        if f["tipo"] not in ("lista", "lista_nativa") or f.get("depende_manual"):
            continue
        filas_f = por.get(f["id"]) or []
        anteriores = set(orden[:orden.index(f["id"])])
        cand = None
        for a, b in itertools.combinations(filas_f, 2):
            if a["opciones"] == b["opciones"] or _nuevas_llegadas(a["opciones"], b["opciones"]):
                continue
            dif = {k for k in anteriores if (k in a["padres"] or k in b["padres"]) and a["padres"].get(k) != b["padres"].get(k)}
            if dif:
                cand = dif if cand is None else ((cand & dif) or (cand | dif))
        if cand:
            nuevo = [k for k in orden if k in cand or k in f["depende_de"]]
            if nuevo != f["depende_de"]:
                f["depende_de"], f["depende_auto"] = nuevo, True
                cambios.append("«%s» depende de %s" % (f["nombre"], ", ".join(
                    "«%s»" % filtro(data, k)["nombre"] for k in nuevo)))
    return cambios


def guardar_lecturas(almacen, pagina_id, data, lecturas, fuente):
    """Guarda las listas leídas y detecta dependencias.  Devuelve True si cambiaron los datos de la Página."""
    for fid, opciones, padres in lecturas:
        almacen.guardar_opciones_pagina(pagina_id, fid, opciones, padres, fuente)
    return bool(detectar_dependencias(data, almacen.opciones_pagina(pagina_id))) if lecturas else False


def _sugerencias_fecha(f):
    fmt = f.get("formato") or "%d/%m/%Y"
    return mod_filtros._sugerencias_fecha("{hoy:%s}" % fmt)


def formulario(data, filas, seleccion=None, novedades=None, vigilado=None):
    """Los filtros de la Página para el formulario: opciones conocidas (los periodos de la más reciente a la más
    antigua), lo elegido, de dónde salen y cuándo, las novedades de la vigilancia y si hay que traer la lista
    (`desconocida`: depende de otro filtro y no se conoce para lo elegido)."""
    sel = seleccion_base(data, seleccion=seleccion)
    # v3.3: `vigilado` puede ser un filtro o varios (cada vigilancia de la página vigila uno)
    if vigilado is None:
        vigilados = set()
    elif isinstance(vigilado, (list, tuple, set)):
        vigilados = {str(x) for x in vigilado}
    else:
        vigilados = {str(vigilado)}
    por = {}
    for fila in filas or []:
        por.setdefault(fila["filtro"], []).append(fila)
    elegidos = {}          # id -> texto elegido (para las listas que dependen de otras)
    res = []
    for f in data["filtros"]:
        e = sel[f["id"]]
        d = {"id": f["id"], "nombre": f["nombre"], "tipo": f["tipo"], "eleccion": e, "defecto": defecto(f),
             "en_nombre": bool(f.get("en_nombre")), "depende_de": list(f["depende_de"]),
             "depende_auto": bool(f.get("depende_auto")), "nombre_origen": f.get("nombre_origen", ""),
             "depende_nombres": [filtro(data, k)["nombre"] for k in f["depende_de"]],
             "vigilado": f["id"] in vigilados, "selectores": f.get("selectores") or [],
             "opciones": [], "actualizado": "", "fuente": "", "fuente_texto": "", "desconocida": False, "nota": "",
             "cronologica": False, "mas_reciente": "", "actual": ""}
        if f["tipo"] in ("fecha", "texto", "casilla"):
            if f["tipo"] == "fecha":
                d["sugerencias"] = _sugerencias_fecha(f)
                d["formato"] = f.get("formato") or "%d/%m/%Y"        # v3.6: para el calendario de la interfaz
            d["actual"] = e.get("valor", "") if f["tipo"] != "casilla" else ("sí" if e.get("marcado") else "no")
            if (f.get("busqueda") or {}).get("filas"):
                d["busqueda"] = True
                d["opciones_busqueda"] = [opcion_de_fila(x) for x in f["busqueda"]["filas"]]
            elif f.get("busqueda"):
                d["busqueda"] = True
            res.append(d)
            continue
        if f["tipo"] == "pestana":
            opciones = [x["texto"] for x in f["pestanas"]]
            fila, exacta = None, True
        else:
            padres = {k: v for k, v in elegidos.items() if k in f["depende_de"]}
            fila, exacta = buscar_opciones(por.get(f["id"]), f["depende_de"], padres)
            opciones = list(fila["opciones"]) if fila else []
        cron = mod_flujo.parece_cronologica(opciones)
        orden = mod_flujo.ordenar_recientes(opciones) if cron else list(opciones)
        nuevas = set((novedades or {}).get(f["id"]) or [])
        valores = e.get("valores") or []
        est, valor = (e.get("estrategia") or "fija", e.get("valor") or "") if not valores else ("fija", valores[0])
        actual = mod_filtros._texto_elegido(opciones, est, valor) if opciones else (valor if est == "fija" else "")
        if est == "fija" and valor and valor not in opciones:
            orden.insert(0, valor)
        mas = orden[0] if cron and orden and mod_flujo.es_reconocible(orden[0]) and orden[0] in opciones else ""
        d.update(opciones=[{"texto": t, "detalle": mod_flujo.describir_opcion(t) if cron else "", "nueva": t in nuevas,
                            "mas_reciente": t == mas, "guardada": t not in opciones} for t in orden],
                 cronologica=cron, mas_reciente=mas, actual=actual)
        if fila is not None:
            d.update(actualizado=fila.get("actualizado", ""), fuente=fila.get("fuente", ""),
                     fuente_texto=FUENTES.get(fila.get("fuente", ""), fila.get("fuente", "")))
        if f["tipo"] != "pestana":
            if not opciones:
                d["desconocida"] = bool(f["depende_de"])
                d["nota"] = "Todavía no se conocen las opciones: pulsa «Actualizar opciones»." if not f["depende_de"] else \
                    "Las opciones dependen de %s: hay que traerlas de la página." % ", ".join(
                        "«%s»" % n for n in d["depende_nombres"])
            elif not exacta:
                d["desconocida"] = True
                d["nota"] = "No se conocen las opciones para %s: se muestra la última lista conocida mientras se traen." % (
                    ", ".join("«%s» = «%s»" % (filtro(data, k)["nombre"], elegidos.get(k, "")) for k in f["depende_de"]))
        if valores:
            elegidos[f["id"]] = valores[0]
        elif actual:
            elegidos[f["id"]] = actual
        res.append(d)
    return res


def actualizado(formulario_lista):
    fechas = [d["actualizado"] for d in formulario_lista if d.get("actualizado")]
    return max(fechas) if fechas else ""


# ====================================================================== favoritos
def buscar_favorito(data, nombre):
    n = _norm(nombre).lower()
    for fav in data.get("favoritos") or []:
        if _norm(fav["nombre"]).lower() == n:
            return fav
    raise ErrorPagina("No hay ningún favorito «%s» (favoritos: %s)" % (
        nombre, ", ".join("«%s»" % f["nombre"] for f in data.get("favoritos") or []) or "ninguno"))


def guardar_favorito(data, nombre, seleccion, sin_navegador=True):
    n = re.sub(r"\s+", " ", nombre or "").strip()
    if not n:
        raise ErrorPagina("Escribe un nombre para el favorito")
    if len(n) > 60 or '"' in n:
        raise ErrorPagina("El nombre del favorito no puede llevar comillas ni pasar de 60 caracteres")
    sel = seleccion_base(data, seleccion=seleccion)
    valores = {fid: e for fid, e in sel.items() if seleccion and fid in seleccion}
    data["favoritos"] = [f for f in data.get("favoritos") or [] if _norm(f["nombre"]).lower() != n.lower()]
    data["favoritos"].append({"nombre": n, "valores": valores, "sin_navegador": bool(sin_navegador)})
    return n


def borrar_favorito(data, nombre):
    buscar_favorito(data, nombre)
    data["favoritos"] = [f for f in data["favoritos"] if _norm(f["nombre"]).lower() != _norm(nombre).lower()]


def describir_favorito(data, fav):
    partes = []
    for f in data["filtros"]:
        if f["id"] in fav["valores"]:
            partes.append("%s: %s" % (f["nombre"], describir_eleccion(f, normalizar_eleccion(f, fav["valores"][f["id"]]))))
    return "; ".join(partes) or "los valores por defecto"


# ====================================================================== línea de comandos
def resolver_cli(data, textos):
    """`--filtro "Elegir corte=43 - 2026 (…)"` (repetible) → selección.  Valor «más reciente», «primera», «última»;
    en casillas sí/no; el mismo filtro varias veces = una ejecución por valor."""
    sel = {}
    for texto in textos or []:
        if "=" not in texto:
            raise ErrorPagina("--filtro debe ser «nombre=valor» (p. ej. --filtro \"Elegir corte=43 - 2026 (…)\")")
        clave, valor = (x.strip() for x in texto.split("=", 1))
        cands = [f for f in data["filtros"] if _norm(f["nombre"]).lower() == _norm(clave).lower() or f["id"] == clave]
        if not cands:
            raise ErrorPagina("No hay ningún filtro «%s» (filtros: %s)" % (
                clave, ", ".join("«%s»" % f["nombre"] for f in data["filtros"])))
        f = cands[0]
        if not valor:
            raise ErrorPagina("Falta el valor del filtro «%s»" % clave)
        est = _ESTRATEGIA_CLI.get(_norm(valor).lower()) if es_lista(f) else None
        previo = sel.get(f["id"])
        if f["tipo"] == "casilla":
            if previo:
                raise ErrorPagina("El filtro «%s» está repetido" % clave)
            sel[f["id"]] = {"marcado": valor.lower() in _SI}
        elif est:
            if previo:
                raise ErrorPagina("El filtro «%s» está repetido" % clave)
            sel[f["id"]] = {"estrategia": est, "valor": ""}
        elif previo is not None:
            if "valores" not in previo:
                raise ErrorPagina("El filtro «%s» está repetido" % clave)
            previo["valores"].append(valor)
        else:
            sel[f["id"]] = {"valores": [valor]}
    return sel


# ====================================================================== ejecutar
def carpeta_perfil(carpeta_perfiles, pagina_id, data):
    """Perfil del navegador de la Página: el que se usó al mapearla (la sesión ya iniciada) o `pagina_<id>`."""
    nombre = data.get("perfil") or "pagina_%d" % int(pagina_id)
    return os.path.join(carpeta_perfiles, os.path.basename(nombre))


class ResultadoPagina:
    def __init__(self, nombre):
        self.nombre = nombre
        self.resultados = []           # [(etiqueta, ResultadoEjecucion)]
        self.archivos = []
        self.errores = []
        self.n = 0
        self.detenido = False

    @property
    def ok(self):
        return bool(self.resultados) and not self.errores and len(self.resultados) == self.n

    def resumen(self):
        bien = sum(1 for _e, r in self.resultados if r.ok)
        if self.n == 1 and self.resultados:
            r = self.resultados[0][1]
            if not r.ok:
                return "«%s»: %s" % (self.nombre, r.resumen())
            return "«%s» descargada%s" % (self.nombre, ("; archivos: " + ", ".join(
                os.path.basename(a) for a in self.archivos)) if self.archivos else "")
        txt = "«%s»: %d de %d bien" % (self.nombre, bien, self.n)
        if len(self.resultados) < self.n:
            txt += " (detenido tras %d)" % len(self.resultados)
        if self.archivos:
            txt += "; archivos: " + ", ".join(os.path.basename(a) for a in self.archivos)
        if self.errores:
            txt += "; fallaron: " + " | ".join(self.errores[:3])
        return txt


def preparar(data, seleccion):
    """Comprueba lo elegido y devuelve las combinaciones (lanza ErrorPagina si algo no vale o son demasiadas)."""
    problemas = validar(data)
    if problemas:
        raise ErrorPagina("La página tiene errores: " + "; ".join(problemas[:3]))
    combos = combinaciones(data, seleccion)
    if len(combos) > MAX_EJECUCIONES:
        raise ErrorPagina("Son %d ejecuciones: el máximo es %d. Elige menos opciones." % (len(combos), MAX_EJECUCIONES))
    for eleccion, varian in combos:
        for f in data["filtros"]:
            paso_de_filtro(f, eleccion.get(f["id"]) or defecto(f))
        pasos_accion(data, varian)
    return combos


def etiqueta_combinacion(data, eleccion, varian):
    if not varian:
        return "con lo elegido"
    return " · ".join(eleccion[fid].get("valor", "") for fid in varian)


def ejecutar(almacen, pagina_id, seleccion, crear_ejecutor, combos=None, log=None, detener=None, aviso=None,
             al_resultado=None, hoy=None):
    """Ejecuta la Página una vez por combinación (`seleccion` ya completa, p. ej. de `seleccion_base`).  Cada ejecución
    va al historial y guarda las listas que leyó.  `aviso(n, total, etiqueta)` antes de cada una;
    `al_resultado(res, etiqueta)` después.  Devuelve ResultadoPagina."""
    fila = almacen.obtener_pagina(pagina_id)
    if fila is None:
        raise ErrorPagina("No existe la página número %s" % pagina_id)
    data = normalizar(fila["data"])
    combos = combos if combos is not None else preparar(data, seleccion)
    r = ResultadoPagina(fila["nombre"])
    r.n = len(combos)
    for k, (eleccion, varian) in enumerate(combos, 1):
        if detener is not None and detener.is_set():
            r.detenido = True
            break
        etiqueta = etiqueta_combinacion(data, eleccion, varian)
        if aviso:
            aviso(k, r.n, etiqueta)
        if log and r.n > 1:
            log("=== «%s» (%d de %d): %s ===" % (fila["nombre"], k, r.n, etiqueta))
        fl, indices = construir_flujo(data, fila["nombre"], eleccion, varian, hoy=hoy)
        ej = crear_ejecutor(fl)
        lineas = ["%s = %s" % (f["nombre"], describir_eleccion(f, eleccion.get(f["id"]) or defecto(f)))
                  for f in data["filtros"]]
        ej.lineas_inicio = ["Página «%s»: %s" % (fila["nombre"], "; ".join(lineas) or "sin filtros")]
        res = ej.ejecutar()
        try:
            almacen.registrar_ejecucion(None, "ok" if res.ok else ("detenido" if res.detenido else "error"),
                                        "" if res.ok else res.resumen(), res.archivos, registro=res.ruta_log or "",
                                        captura=res.ruta_captura or "", pagina_id=pagina_id)
            if guardar_lecturas(almacen, pagina_id, data, lecturas_de_resultado(indices, res), "ejecucion"):
                _guardar_data(almacen, pagina_id, fila, data)
        except Exception:              # noqa: BLE001 (el historial no debe estropear la descarga)
            pass
        r.resultados.append((etiqueta, res))
        if res.ok:
            r.archivos += res.archivos
        else:
            r.errores.append("%s: %s" % (etiqueta, res.resumen()))
            if res.detenido:
                r.detenido = True
        if al_resultado:
            al_resultado(res, etiqueta)
        if r.detenido:
            break
    return r


def _guardar_data(almacen, pagina_id, fila, data):
    almacen.guardar_pagina(fila["nombre"], data, pagina_id, host=fila.get("host", ""), url=fila.get("url", ""))


def leer_opciones(almacen, pagina_id, seleccion, crear_ejecutor, hasta=None, fuente="actualizar", al_final=None):
    """Ejecuta la Página (oculta) hasta un filtro (por defecto, la última lista) leyendo cada lista por la que pasa, y
    guarda las opciones (no genera ni descarga nada).  `al_final(ej, pg)` puede mapear la página (corregir nombres).
    Devuelve (ResultadoEjecucion, número de listas leídas, mensajes)."""
    fila = almacen.obtener_pagina(pagina_id)
    if fila is None:
        raise ErrorPagina("No existe la página número %s" % pagina_id)
    data = normalizar(fila["data"])
    hasta = hasta or ultimo_filtro_lista(data)
    if hasta is None:
        raise ErrorPagina("Esta página no tiene filtros")
    eleccion = combinaciones(data, seleccion_base(data, seleccion=seleccion))[0][0]
    fl, indices = construir_flujo(data, fila["nombre"], eleccion, hasta=hasta)
    ej = crear_ejecutor(fl, hasta=indices[str(hasta)] + 1, solo_leer=True, al_final=al_final)
    res = ej.ejecutar()
    lecturas = lecturas_de_resultado(indices, res)
    mensajes = []
    cambio = guardar_lecturas(almacen, pagina_id, data, lecturas, fuente)
    if cambio:
        mensajes.append("Dependencias detectadas")
    if res.ok and isinstance(res.extra, list):
        nombres = corregir_nombres(data, res.extra)
        if nombres:
            mensajes.append("Nombres de los filtros leídos de la página: " + ", ".join(nombres))
            cambio = True
    if cambio:
        _guardar_data(almacen, pagina_id, fila, data)
    return res, len(lecturas), mensajes


def guardar_nueva(almacen, nombre, data, lecturas=None, fuente="mapa"):
    """Guarda una Página nueva (con un nombre libre) y las opciones del mapa.  Devuelve (id, nombre)."""
    data = normalizar(data)
    problemas = validar(data)
    if problemas:
        raise ErrorPagina("La página no se puede guardar: " + "; ".join(problemas[:3]))
    nombre = almacen.nombre_pagina_libre(nombre or nombre_sugerido(data.get("url")))
    pid = almacen.guardar_pagina(nombre, data, host=host_de(data.get("url")), url=data.get("url") or "")
    for fid, opciones, padres in lecturas or []:
        almacen.guardar_opciones_pagina(pid, fid, opciones, padres, fuente)
    return pid, nombre


def convertir_mapas(almacen, log=None):
    """Una sola vez (v3.2): los reportes creados con «Mapear página» que tienen un mapa guardado pasan a ser también
    Páginas (p. ej. el «Reporte mapeado» de Portal → «Portal – Reportes»).  No cambia ni borra el reporte ni el mapa.
    Devuelve los mensajes."""
    if almacen.meta("paginas_convertidas") == "1":
        return []
    mensajes = []
    for r in almacen.listar():
        mapa = almacen.ultimo_mapa(r["id"])
        if not mapa or not mapa.get("filtros"):
            continue
        try:
            fl = almacen.cargar_flujo(r["id"])
            nombre, data, _k, lecturas = convertir_reporte_y_mapa(fl, mapa)
            data["perfil"] = "reporte_%d" % int(r["id"])        # la sesión ya iniciada de ese reporte
            data["origen"] = {"reporte_id": r["id"], "mapa_id": mapa["id"]}
            pid, nombre = guardar_nueva(almacen, nombre, data, lecturas, "mapa")
        except Exception as e:         # noqa: BLE001 (un mapa raro no debe impedir abrir el bot)
            mensajes.append("No se pudo crear la página del reporte «%s»: %s" % (r["nombre"], e))
            continue
        texto = ("Se creó la página «%s» a partir del mapa del reporte «%s» (el reporte sigue igual). Ábrela en «Páginas» "
                 "para elegir los filtros y descargar." % (nombre, r["nombre"]))
        mensajes.append(texto)
        try:
            almacen.crear_notificacion("pagina", "Nueva página: «%s»" % nombre, texto, {"pagina_id": pid})
        except Exception:              # noqa: BLE001
            pass
    almacen.poner_meta("paginas_convertidas", "1")
    if log:
        for m in mensajes:
            log(m)
    return mensajes
