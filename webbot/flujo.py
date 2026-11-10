"""Modelo de flujos y pasos (sin importar playwright, para poder probarlo solo).

Un flujo es: {version, nombre, url, variables{}, opciones{}, pasos[]}.
Cada paso: {tipo, ...datos, nota, opcional, timeout, pagina, marco}.
Las contraseñas nunca se guardan aquí: el paso lleva «{secreto:nombre}».
"""

import copy
import dataclasses
import json
import os
import re
from dataclasses import dataclass, field

from . import plantillas

VERSION_FORMATO = 3      # 3 = v2.3: paso «iniciar_sesion» (los reportes guardados en versión 2 se convierten)

TIPOS = (
    "abrir_url", "clic", "escribir", "tecla", "seleccionar", "marcar",
    "esperar_elemento", "esperar_texto", "esperar_segundos", "descargar", "guardar_pagina",
    "pasar_raton", "iniciar_sesion", "elegir_opcion",
)

NOMBRES_TIPO = {
    "abrir_url": "Abrir página",
    "clic": "Clic",
    "escribir": "Escribir",
    "tecla": "Pulsar tecla",
    "seleccionar": "Seleccionar",
    "marcar": "Marcar casilla",
    "esperar_elemento": "Esperar elemento",
    "esperar_texto": "Esperar texto",
    "esperar_segundos": "Esperar segundos",
    "descargar": "Descargar",
    "guardar_pagina": "Guardar página",
    "pasar_raton": "Pasar el ratón",
    "iniciar_sesion": "Iniciar sesión",
    "elegir_opcion": "Elegir opción",
}

# elegir_opcion: cómo se elige la opción de una lista (nativa o propia: Vuetify, combobox…)
ESTRATEGIAS = ("fija", "mas_reciente", "primera", "ultima", "contiene", "por_fecha")
NOMBRES_ESTRATEGIA = {
    "fija": "la opción con este texto exacto",
    "mas_reciente": "la más reciente (número o fecha más alta)",
    "primera": "la primera de la lista",
    "ultima": "la última de la lista",
    "contiene": "la primera que contiene este texto (o expresión regular)",
    "por_fecha": "la de una fecha (hoy, ayer o un día exacto)",
}
# v3.8: lo que `Paso.problemas` dice de un paso sin valor.  No impide ejecutar el reporte: ese paso se salta.
PROBLEMAS_SIN_VALOR = ("Falta el texto de la opción", "Falta la fecha de la opción")

# Pasos tras los que se espera a que la página termine de cargar (opción «esperar_carga»).
TIPOS_CON_CARGA = ("abrir_url", "clic", "escribir", "tecla", "seleccionar", "marcar", "descargar",
                   "iniciar_sesion", "esperar_elemento", "esperar_texto", "elegir_opcion")
TIPOS_CAMPO_ACCESO = ("texto", "clave")

BOTONES = ("izquierdo", "derecho", "medio")
ESTADOS = ("visible", "oculto")
FORMATOS_PAGINA = ("pdf", "html", "csv")

OPCIONES_DEFECTO = {
    "navegador": "chrome",          # chrome | msedge
    "timeout_paso": 60,             # segundos
    "timeout_descarga": 600,        # segundos (esperar a que se genere el reporte / tope de las esperas aprendidas)
    "pausa_entre_pasos": 0.3,       # segundos entre un paso y el siguiente (no antes del primero)
    "carpeta_descargas": "",        # vacío = carpeta «descargas» del proyecto
    "si_existe": "numerar",         # numerar | sobrescribir
    "recuperacion_automatica": True,  # si un elemento de un menú no se ve, intentar abrir el menú (ratón encima, reabrir lista)
    "esperar_carga": True,          # tras cada acción, esperar a que la página termine de cargar (indicadores, peticiones)
    "repetir_dias": None,           # v3.0: {modo: fijo|ultimos|mes_hasta_ayer|ayer, desde, hasta, n}: un pase por día ({fecha})
}

MODOS_DIAS = {
    "fijo": "entre dos fechas",
    "ultimos": "los últimos N días (hasta ayer)",
    "mes_hasta_ayer": "desde el inicio del mes hasta ayer",
    "ayer": "solo ayer",
}

_ROLES = {"button": "botón", "link": "enlace", "menuitem": "opción de menú", "tab": "pestaña",
          "option": "opción", "checkbox": "casilla", "textbox": "campo", "combobox": "lista"}


class ErrorFlujo(ValueError):
    """El flujo o un paso no es válido."""


def describir_selector(sel):
    """Texto legible (en español) para un selector."""
    if not sel:
        return "(sin selector)"
    m = re.match(r'^role=(\w+)\[name="(.*)"[is]?\]$', sel)
    if m:
        return "%s «%s»" % (_ROLES.get(m.group(1), m.group(1)), m.group(2).replace('\\"', '"'))
    m = re.match(r'^[\w.\-#> ]*:text-is\("(.*)"\)$', sel)
    if m:
        return "«%s»" % m.group(1).replace('\\"', '"')
    m = re.match(r'^\w*\[(name|placeholder|aria-label|data-testid|data-test|data-qa|data-cy|title)="(.*)"\]', sel)
    if m:
        if m.group(1) in ("name", "placeholder"):
            return "campo «%s»" % m.group(2)
        return "«%s»" % m.group(2)
    if re.match(r"^#[\w\-\\]+$", sel):
        return "elemento %s" % sel
    return sel if len(sel) <= 60 else sel[:57] + "..."


def _mostrar_valor(valor):
    """Valor para mostrar al usuario: las contraseñas se muestran solo por su nombre."""
    if valor is None:
        return ""
    return re.sub(r"\{secreto:([^}]*)\}", lambda m: "<contraseña %s>" % m.group(1), valor)


def slug(texto):
    """Nombre seguro para usar como carpeta o archivo."""
    s = re.sub(r"[^\w\-. ]+", "_", (texto or "").strip(), flags=re.UNICODE).strip(" .")
    return s or "flujo"


_RE_CLAVE = re.compile(r"pass|contrase|clave|pwd", re.IGNORECASE)
TIMEOUT_OPCIONAL = 5    # segundos que se espera un paso opcional si no tiene tiempo propio


def parece_campo_contrasena(*textos):
    """True si alguno de los textos (selectores, nombre del elemento…) sugiere un campo de contraseña."""
    return any(t and _RE_CLAVE.search(str(t)) for t in textos)


@dataclass
class Paso:
    tipo: str
    selectores: list = field(default_factory=list)
    url: str = ""
    valor: str = ""
    etiqueta: str = ""        # texto de la opción elegida (seleccionar)
    boton: str = "izquierdo"
    doble: bool = False
    tecla: str = ""
    marcado: bool = True
    estado: str = "visible"
    texto: str = ""
    segundos: float = 1.0
    nombre: str = ""          # plantilla del nombre del archivo descargado / guardado
    carpeta: str = ""
    formato: str = ""         # guardar_pagina: pdf | html | csv
    objetivo: str = ""        # nombre legible del elemento (solo informativo)
    nota: str = ""
    opcional: bool = False
    timeout: float = None     # segundos; None = el del flujo
    pagina: int = 0
    marco: list = field(default_factory=list)  # cadena de iframes (selectores)
    espera_grabada: float = None   # segundos que pasaron desde el paso anterior al grabar (espera aprendida)
    desactivado: bool = False      # el paso se conserva pero no se ejecuta
    fecha_directa: bool = False    # escribir: fecha escrita directamente (sustituye los clics del calendario)
    auto: bool = False             # pasar_raton: añadido automáticamente por el grabador
    esperar_carga: object = None   # None = lo que diga el flujo; True / False = forzarlo en este paso
    sitio: str = ""                # iniciar_sesion: host de la página de inicio de sesión
    campos: list = field(default_factory=list)   # iniciar_sesion: [{selectores, etiqueta, tipo, clave, valor | secreto}]
    enviar: dict = field(default_factory=dict)   # iniciar_sesion: {selectores, objetivo} o {tecla: "Enter"}
    estrategia: str = ""           # elegir_opcion: fija (defecto) | mas_reciente | primera | ultima | contiene | por_fecha
    filtro: str = ""               # v3.1: nombre del filtro para el usuario («Elegir corte»; panel «Usar filtros»)

    # --- serialización ---------------------------------------------------
    def a_dict(self):
        base = Paso(self.tipo)
        d = {"tipo": self.tipo}
        for campo in dataclasses.fields(self):
            if campo.name == "tipo":
                continue
            v = getattr(self, campo.name)
            if v != getattr(base, campo.name):
                d[campo.name] = copy.deepcopy(v)
        return d

    @classmethod
    def desde_dict(cls, d):
        if not isinstance(d, dict) or "tipo" not in d:
            raise ErrorFlujo("Un paso no tiene «tipo»")
        if d["tipo"] not in TIPOS:
            raise ErrorFlujo("Tipo de paso desconocido: %s" % d["tipo"])
        nombres = {f.name for f in dataclasses.fields(cls)}
        datos = {k: v for k, v in d.items() if k in nombres}
        if isinstance(datos.get("selectores"), str):
            datos["selectores"] = [datos["selectores"]]
        paso = cls(**datos)
        paso.selectores = list(paso.selectores or [])
        paso.marco = list(paso.marco or [])
        paso.campos = [dict(c) for c in (paso.campos or []) if isinstance(c, dict)]
        for c in paso.campos:
            sels = c.get("selectores")
            c["selectores"] = [sels] if isinstance(sels, str) else list(sels or [])
        paso.enviar = dict(paso.enviar) if isinstance(paso.enviar, dict) else {}
        if paso.esperar_carga is not None:
            paso.esperar_carga = bool(paso.esperar_carga)
        return paso

    def copia(self):
        return Paso.desde_dict(self.a_dict())

    # --- contraseñas ------------------------------------------------------
    def es_secreto(self):
        return self.tipo == "escribir" and bool(re.fullmatch(r"\{secreto:[^}]*\}", self.valor or ""))

    def parece_contrasena(self):
        """Paso «escribir» cuyo campo parece de contraseña (aunque el valor sea literal)."""
        return self.tipo == "escribir" and parece_campo_contrasena(self.objetivo, *self.selectores)

    def valor_literal_en_campo_contrasena(self):
        """True si es un campo de contraseña con el texto escrito en claro (conviene convertirlo)."""
        return self.parece_contrasena() and not self.es_secreto() and bool(self.valor)

    # --- v3.8: sin valor ---------------------------------------------------
    def sin_valor(self):
        """True si el paso necesita un valor y no lo tiene (lista, texto o fecha que se dejó vacío): no se ejecuta.
        Los pasos sin concepto de valor (clic, descargar…) y las estrategias que no lo usan siempre se ejecutan."""
        if (self.valor or "").strip():
            return False
        if self.tipo == "escribir":
            return True
        return self.tipo == "elegir_opcion" and (self.estrategia or "fija") in ("fija", "contiene", "por_fecha")

    # --- tiempos ----------------------------------------------------------
    def timeout_efectivo(self, opciones=None):
        """Segundos máximos de espera del paso.

        - Si tiene `timeout` propio, ese.
        - Si es opcional, TIMEOUT_OPCIONAL.
        - Si no: max(timeout_paso, espera_grabada × 3 + 30), con tope en timeout_descarga.
        """
        opciones = opciones or {}
        base = float(opciones.get("timeout_paso") or OPCIONES_DEFECTO["timeout_paso"])
        tope = float(opciones.get("timeout_descarga") or OPCIONES_DEFECTO["timeout_descarga"])
        if self.timeout:
            return float(self.timeout)
        if self.opcional:
            return float(TIMEOUT_OPCIONAL)
        valor = base
        if self.espera_grabada:
            valor = max(base, float(self.espera_grabada) * 3 + 30)
        return min(valor, max(tope, base))

    def timeout_descarga_efectivo(self, opciones=None):
        """Espera máxima de los pasos que generan un archivo (descargar, guardar página)."""
        opciones = opciones or {}
        if self.timeout:
            return float(self.timeout)
        return float(opciones.get("timeout_descarga") or OPCIONES_DEFECTO["timeout_descarga"])

    # --- descripción en español -----------------------------------------
    def nombre_objetivo(self):
        if self.filtro and (not self.objetivo or etiqueta_generica(self.objetivo)):
            return "«%s»" % self.filtro
        if self.objetivo:
            return "«%s»" % self.objetivo
        if self.selectores:
            return describir_selector(self.selectores[0])
        return ""

    def accion(self):
        t = self.tipo
        if t == "clic":
            if self.doble:
                return "Doble clic"
            return {"derecho": "Clic derecho", "medio": "Clic central"}.get(self.boton, "Clic")
        if t == "marcar":
            return "Marcar casilla" if self.marcado else "Desmarcar casilla"
        if t == "pasar_raton" and self.auto:
            return "Pasar el ratón (automático)"
        return NOMBRES_TIPO.get(t, t)

    def detalle(self):
        t = self.tipo
        obj = self.nombre_objetivo()
        if t == "abrir_url":
            return self.url
        if t == "iniciar_sesion":
            partes = []
            for c in self.campos:
                nombre = c.get("etiqueta") or c.get("clave") or "campo"
                if c.get("tipo") == "clave":
                    if c.get("secreto"):
                        que = "contraseña «%s»" % c["secreto"]
                    else:
                        que = "«********» (contraseña en claro)" if c.get("valor") else "se pedirá"
                else:
                    que = ("«%s»" % _mostrar_valor(c.get("valor"))) if c.get("valor") else "se pedirá"
                partes.append("%s: %s" % (nombre, que))
            env = self.enviar or {}
            if env.get("selectores"):
                partes.append("enviar con «%s»" % (env.get("objetivo") or describir_selector(env["selectores"][0]).strip("«»")))
            elif env.get("tecla"):
                partes.append("enviar con %s" % env["tecla"])
            return "en «%s» (si hace falta)%s" % (self.sitio or "la página", (" — " + "; ".join(partes)) if partes else "")
        if t in ("clic", "pasar_raton"):
            return obj or "(elemento sin identificar)"
        if t == "escribir":
            v = self.valor
            m = re.fullmatch(r"\{secreto:([^}]*)\}", v or "")
            if m:
                texto = "la contraseña «%s»" % m.group(1)
            elif self.parece_contrasena() and v:
                texto = "«********» (¡contraseña en claro! usa «Convertir en contraseña»)"
            else:
                texto = "«%s»" % _mostrar_valor(v)
            return "%s en %s" % (texto, obj) if obj else texto
        if t == "tecla":
            return "%s%s" % (self.tecla, (" en " + obj) if obj else "")
        if t == "seleccionar":
            op = self.etiqueta or _mostrar_valor(self.valor)
            return "«%s» en %s" % (op, obj) if obj else "«%s»" % op
        if t == "elegir_opcion":
            est = self.estrategia or "fija"
            if est == "fija":
                que = "«%s»" % _mostrar_valor(self.valor)
            elif est == "contiene":
                que = "la opción que contiene «%s»" % _mostrar_valor(self.valor)
            elif est == "por_fecha":
                que = "la opción de la fecha «%s»" % plantillas.describir_fecha(self.valor)
            else:
                que = {"mas_reciente": "la opción más reciente", "primera": "la primera opción",
                       "ultima": "la última opción"}.get(est, est)
            return "%s en %s" % (que, obj) if obj else que
        if t == "marcar":
            return obj
        if t == "esperar_elemento":
            frase = "hasta que aparezca" if self.estado != "oculto" else "hasta que desaparezca"
            return "%s %s" % (frase, obj or "(elemento)")
        if t == "esperar_texto":
            return "hasta que aparezca «%s»" % _mostrar_valor(self.texto)
        if t == "esperar_segundos":
            s = self.segundos
            return "%g segundo%s" % (s, "" if s == 1 else "s")
        if t == "descargar":
            nombre = self.nombre or "{nombre}{ext}"
            donde = (" en " + self.carpeta) if self.carpeta else ""
            return "%s → guardar como «%s»%s" % (obj, nombre, donde) if obj else \
                "guardar como «%s»%s" % (nombre, donde)
        if t == "guardar_pagina":
            nombre = self.nombre or "Pagina_{hoy:%Y-%m-%d}"
            donde = (" en " + self.carpeta) if self.carpeta else ""
            return "%s → «%s»%s" % ((self.formato or "html").upper(), nombre, donde)
        return ""

    def descripcion(self):
        """Frase completa en español, p. ej. «Clic derecho en «Resultado» (pestaña 2)»."""
        t = self.tipo
        det = self.detalle()
        if t == "abrir_url":
            txt = "Abrir la página %s" % self.url
        elif t == "iniciar_sesion":
            txt = "Iniciar sesión en «%s» (si hace falta)" % (self.sitio or "la página")
        elif t == "clic":
            txt = "%s en %s" % (self.accion(), det)
        elif t == "pasar_raton":
            txt = "Pasar el ratón sobre %s" % det
        elif t == "elegir_opcion":
            txt = "Elegir %s" % det
        elif t == "esperar_elemento":
            txt = "Esperar %s" % det
        elif t == "esperar_texto":
            txt = "Esperar %s" % det
        elif t == "esperar_segundos":
            txt = "Esperar %s" % det
        elif t == "descargar":
            txt = "Descargar: %s" % det
        elif t == "guardar_pagina":
            txt = "Guardar la página como %s" % det
        else:
            txt = "%s %s" % (self.accion(), det)
        if self.pagina:
            txt += " (pestaña %d)" % (self.pagina + 1)
        if self.desactivado:
            txt += " [desactivado]"
        return txt

    def problemas(self):
        """Lista de problemas de validación (vacía si el paso es correcto)."""
        p = []
        t = self.tipo
        if t not in TIPOS:
            return ["Tipo desconocido: %s" % t]
        if t == "abrir_url" and not self.url:
            p.append("Falta la dirección (URL)")
        if t in ("clic", "escribir", "seleccionar", "marcar", "esperar_elemento", "pasar_raton", "elegir_opcion") \
                and not self.selectores:
            p.append("Falta al menos un selector")
        if t == "elegir_opcion":
            est = self.estrategia or "fija"
            if est not in ESTRATEGIAS:
                p.append("Estrategia no válida: %s" % est)
            elif est in ("fija", "contiene") and not (self.valor or "").strip():
                p.append("Falta el texto de la opción")
            elif est == "por_fecha" and not (self.valor or "").strip():
                p.append("Falta la fecha de la opción")
        if t == "tecla" and not self.tecla:
            p.append("Falta la tecla")
        if t == "esperar_texto" and not self.texto:
            p.append("Falta el texto a esperar")
        if t == "esperar_segundos" and self.segundos < 0:
            p.append("Los segundos no pueden ser negativos")
        if t == "iniciar_sesion":
            if not self.campos:
                p.append("Falta al menos un campo (usuario o contraseña)")
            for c in self.campos:
                nombre = c.get("etiqueta") or c.get("clave") or "?"
                if c.get("tipo", "texto") not in TIPOS_CAMPO_ACCESO:
                    p.append("Tipo de campo no válido en «%s»: %s" % (nombre, c.get("tipo")))
                if not c.get("selectores"):
                    p.append("Al campo «%s» le falta el selector" % nombre)
                err = plantillas.validar(c.get("valor") or "")
                if err:
                    p.append("%s: %s" % (nombre, err))
        if t == "guardar_pagina" and (self.formato or "html") not in FORMATOS_PAGINA:
            p.append("Formato no válido: %s (usa pdf, html o csv)" % self.formato)
        if self.boton not in BOTONES:
            p.append("Botón no válido: %s" % self.boton)
        if self.estado not in ESTADOS:
            p.append("Estado no válido: %s" % self.estado)
        for campo in ("url", "valor", "texto", "nombre", "carpeta"):
            err = plantillas.validar(getattr(self, campo))
            if err:
                p.append("%s: %s" % (campo, err))
        return p


@dataclass
class Flujo:
    nombre: str = "Nuevo flujo"
    url: str = ""
    variables: dict = field(default_factory=dict)
    opciones: dict = field(default_factory=lambda: dict(OPCIONES_DEFECTO))
    pasos: list = field(default_factory=list)
    version: int = VERSION_FORMATO

    def opcion(self, clave):
        return self.opciones.get(clave, OPCIONES_DEFECTO.get(clave))

    def a_dict(self):
        return {
            "version": self.version,
            "nombre": self.nombre,
            "url": self.url,
            "variables": dict(self.variables),
            "opciones": dict(self.opciones),
            "pasos": [p.a_dict() for p in self.pasos],
        }

    @classmethod
    def desde_dict(cls, d):
        if not isinstance(d, dict):
            raise ErrorFlujo("El archivo no tiene el formato de un flujo")
        version = d.get("version", VERSION_FORMATO)
        if not isinstance(version, int) or version > VERSION_FORMATO:
            raise ErrorFlujo("Versión de flujo no soportada: %s" % version)
        opciones = dict(OPCIONES_DEFECTO)
        opciones.update(d.get("opciones") or {})
        return cls(
            nombre=d.get("nombre", "Flujo"),
            url=d.get("url", ""),
            variables=dict(d.get("variables") or {}),
            opciones=opciones,
            pasos=[Paso.desde_dict(p) for p in d.get("pasos", [])],
            version=version,
        )

    def a_json(self):
        return json.dumps(self.a_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def desde_json(cls, texto):
        try:
            return cls.desde_dict(json.loads(texto))
        except json.JSONDecodeError as e:
            raise ErrorFlujo("El archivo no es un JSON válido: %s" % e) from e

    def guardar(self, ruta):
        os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(self.a_json())
        os.replace(tmp, ruta)

    @classmethod
    def cargar(cls, ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return cls.desde_json(f.read())

    def copia(self):
        return Flujo.desde_dict(self.a_dict())

    def timeout_de(self, paso):
        """Tiempo máximo efectivo de un paso con las opciones de este flujo."""
        return paso.timeout_efectivo(self.opciones)

    def aplicar_url(self, url):
        """Cambia la URL del flujo y la del primer paso «abrir_url» (o lo crea)."""
        self.url = url
        for p in self.pasos:
            if p.tipo == "abrir_url":
                p.url = url
                return
        self.pasos.insert(0, Paso("abrir_url", url=url))

    def problemas(self):
        res = []
        for i, p in enumerate(self.pasos, 1):
            for pr in p.problemas():
                if pr in PROBLEMAS_SIN_VALOR:       # v3.8: se salta al ejecutar, no es un error del reporte
                    continue
                res.append("Paso %d (%s): %s" % (i, p.accion(), pr))
        try:
            validar_repetir_dias(self.opciones.get("repetir_dias"))
        except ErrorFlujo as e:
            res.append("Repetir por días: %s" % e)
        return res

    def variables_necesarias(self):
        """Variables propias que usa el flujo y no están definidas."""
        usadas = []
        for p in self.pasos:
            textos = [getattr(p, c) for c in ("url", "valor", "texto", "nombre", "carpeta")]
            textos += [c.get("valor") or "" for c in p.campos]
            for texto in textos:
                for v in plantillas.variables_usadas(texto):
                    if v not in usadas:
                        usadas.append(v)
        return [v for v in usadas if v not in self.variables]

    def secretos_necesarios(self, incluir_inicio_sesion=True):
        """Nombres de las contraseñas que usa el flujo.  Las de los pasos «Iniciar sesión» solo se incluyen si
        `incluir_inicio_sesion` (si faltan, el ejecutor las pide al usuario en vez de fallar al empezar)."""
        res = []
        for p in self.pasos:
            nombres = []
            for campo in ("url", "valor", "texto", "nombre", "carpeta"):
                nombres += plantillas.secretos_usados(getattr(p, campo))
            if incluir_inicio_sesion:
                for c in p.campos:
                    nombres += plantillas.secretos_usados(c.get("valor") or "")
                    if c.get("secreto"):
                        nombres.append(c["secreto"])
            for s in nombres:
                if s not in res:
                    res.append(s)
        return res


# --- contraseñas ya escritas en claro ---------------------------------------

def nombre_secreto_sugerido(paso, url=""):
    """Nombre propuesto para guardar la contraseña de un paso: «dominio:campo»."""
    from urllib.parse import urlparse
    host = urlparse(url or "").hostname or "sitio"
    campo = ""
    for sel in paso.selectores:
        m = re.match(r'^(?:#|\w*\[name=")([\w\-.]+)', sel)
        if m:
            campo = m.group(1)
            break
    campo = campo or slug(paso.objetivo).lower() or "clave"
    return "%s:%s" % (host, campo)


def convertir_en_secreto(paso, nombre, guardar):
    """Mueve el texto literal de un paso «escribir» al almacén de contraseñas.

    `guardar(nombre, valor)` es la función que guarda (p. ej. secretos.guardar).  El paso queda con
    «{secreto:nombre}».  Si el valor ya era un secreto o está vacío, falla con ErrorFlujo."""
    if paso.tipo != "escribir":
        raise ErrorFlujo("Solo se puede convertir en contraseña un paso «Escribir»")
    if paso.es_secreto():
        raise ErrorFlujo("Este paso ya usa una contraseña guardada")
    if not paso.valor:
        raise ErrorFlujo("El paso no tiene ningún texto que guardar")
    nombre = (nombre or "").strip()
    if not nombre or "}" in nombre or "{" in nombre:
        raise ErrorFlujo("Nombre de contraseña no válido")
    literal = paso.valor.replace("{{", "{").replace("}}", "}")   # el texto literal se guarda con las llaves escapadas
    guardar(nombre, literal)
    paso.valor = "{secreto:%s}" % nombre
    return paso


# --- textos que cambian cada día (fechas, horas, números largos) -------------

_RX_VOLATIL = re.compile(
    r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b"              # 24/10/2026, 24-10-26
    r"|\b\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}\b"               # 2026-10-24
    r"|\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?\s*m\.?)?"  # 11:32, 11:32:05 p. m.
    r"|\d{5,}", re.IGNORECASE)                            # números largos (folios, totales…)
LARGO_TEXTO_ESTABLE = 40


def _normal(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def texto_volatil(texto, largo_max=LARGO_TEXTO_ESTABLE):
    """True si el texto lleva fechas, horas o números largos (o es muy largo): no sirve para reconocer
    el mismo elemento otro día."""
    t = _normal(texto)
    return bool(_RX_VOLATIL.search(t)) or (largo_max is not None and len(t) > largo_max)


def fragmentos_estables(texto):
    """Trozos del texto sin las partes que cambian (fechas, horas, números largos), en orden.

    «ACME Detalles 24/10/2026 11:32 Canal» → ["ACME Detalles", "Canal"].  Sin partes que cambien,
    devuelve [texto] entero.  Los trozos de menos de 3 letras o números se descartan."""
    t = _normal(texto)
    if not _RX_VOLATIL.search(t):
        return [t] if t else []
    res = []
    for trozo in _RX_VOLATIL.split(t):
        trozo = trozo.strip(" -–—:,;()[]/|·.")
        if len(re.sub(r"[\W_]", "", trozo)) >= 3:
            res.append(trozo)
    return res


def etiqueta_estable(texto, largo_max=LARGO_TEXTO_ESTABLE):
    """Nombre corto que no cambia: el texto hasta la primera fecha/hora/número largo, como mucho `largo_max`."""
    frag = fragmentos_estables(texto)
    t = frag[0] if frag else _normal(texto)
    if len(t) > largo_max:
        corte = t[:largo_max].rsplit(" ", 1)[0]
        t = corte if len(corte) >= 10 else t[:largo_max]
    return t


def coincide_texto_estable(texto_pagina, buscado):
    """True si `buscado` aparece en `texto_pagina`; si `buscado` tiene fechas u horas, basta con que aparezcan
    (en orden) sus trozos estables."""
    pagina = _normal(texto_pagina)
    b = _normal(buscado)
    if not b:
        return False
    if b in pagina:
        return True
    frag = fragmentos_estables(b)
    if not frag or frag == [b]:
        return False
    pos = 0
    for f in frag:
        k = pagina.find(f, pos)
        if k < 0:
            return False
        pos = k + len(f)
    return True


# --- inicio de sesión: campos y agrupación de pasos ---------------------------

def host_de(url):
    """Host de una URL («portal.ejemplo.com»), en minúsculas; '' si no tiene."""
    from urllib.parse import urlparse
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def clave_de_campo(selectores, objetivo=""):
    """Clave estable de un campo de inicio de sesión: su id o su name (p. ej. «txtPassword»)."""
    for sel in selectores or []:
        m = re.match(r'^#([\w\-\\.$:]+)$', sel)
        if m:
            return m.group(1).replace("\\", "")
    for sel in selectores or []:
        m = re.search(r'\[name="([^"]+)"\]', sel)
        if m:
            return m.group(1)
    for sel in selectores or []:
        m = re.match(r'^#([\w\-]+)', sel)
        if m:
            return m.group(1)
    return slug(objetivo).lower() or "campo"


def etiqueta_bonita(objetivo, selectores=None):
    """Etiqueta legible de un campo: «ctl00$formContent$txtLicencia» → «Licencia»."""
    t = _normal(objetivo)
    if not t or (re.fullmatch(r"[\w$:.\-]+", t) and re.search(r"[$_]|^txt|^ctl\d", t)):
        base = t or clave_de_campo(selectores or [])
        base = re.split(r"[$:]", base)[-1]
        base = re.sub(r"_(I|I_CLND|CLND|Input|input)$", "", base)
        base = base.split("_")[-1] if "_" in base else base
        base = re.sub(r"^(txt|tb|inp|input|ctl\d*)", "", base, flags=re.IGNORECASE) or base
        base = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
        t = base[:1].upper() + base[1:]
    return t[:60]


_RX_INCIDENTAL = re.compile(r"appended action|prepended action|mostrar|ocultar|\bshow\b|\bhide\b|toggle|\beye\b|"
                            r"\bojo\b|ojito|visibility|ver contrase|ver clave|^(div|td|span|i|label|svg|path|tr)$",
                            re.IGNORECASE)
_RX_SEL_INCIDENTAL = re.compile(r"mdi-eye|\beye\b|visibility|toggle|_CLND|password-toggle", re.IGNORECASE)


def _clic_incidental(paso, meta=None):
    """Clic que no envía el formulario: el «ojito» de la contraseña, el recuadro (td/div) de un campo…"""
    if meta and meta.get("rol") == "incidental":
        return True
    if meta and meta.get("rol") == "enviar":
        return False
    if _RX_INCIDENTAL.search(_normal(paso.objetivo)):
        return True
    return any(_RX_SEL_INCIDENTAL.search(s or "") for s in paso.selectores)


def _mismo_campo(a, b):
    return bool(a and b and (a[0] == b[0] or set(a) & set(b)))


def _campo_desde_paso(paso, meta=None):
    meta = meta or {}
    clave = bool(meta.get("clave")) or paso.es_secreto() or paso.parece_contrasena()
    c = {"selectores": list(paso.selectores), "etiqueta": etiqueta_bonita(paso.objetivo, paso.selectores),
         "tipo": "clave" if clave else "texto", "clave": clave_de_campo(paso.selectores, paso.objetivo)}
    if clave and paso.es_secreto():
        c["secreto"] = re.fullmatch(r"\{secreto:([^}]*)\}", paso.valor).group(1)
    else:
        c["valor"] = paso.valor
    return c


def _quitar_clones(campos):
    """DevExpress pone un campo «clon» (…_I_CLND) encima de la contraseña real (…_I): basta con el real."""
    claves = [c for c in campos if c["tipo"] == "clave"]
    res = []
    for c in campos:
        sel = c["selectores"][0] if c["selectores"] else ""
        if c["tipo"] == "clave" and "_CLND" in sel and any(
                o is not c and "_CLND" not in ((o["selectores"] or [""])[0]) for o in claves):
            continue
        res.append(c)
    return res


def _grupo_inicio_sesion(pasos, i, info, host):
    """Si en `pasos[i]` empieza una secuencia de inicio de sesión, devuelve (fin, paso_nuevo, indices)."""
    primero = pasos[i]
    meta0 = info.get(id(primero), {})
    token = meta0.get("token")
    if primero.desactivado:
        return None
    if primero.tipo != "escribir":
        # al grabar, un clic suelto en el recuadro del campo puede ir antes del primer «escribir»
        if not (token and primero.tipo == "clic" and _clic_incidental(primero, meta0)):
            return None
    pagina, marco = primero.pagina, primero.marco
    campos, usados, enviar = [], [], None

    def mismo_sitio(p):
        if p.pagina != pagina or p.marco != marco:
            return False
        if token is not None:
            return info.get(id(p), {}).get("token") == token
        return True

    def poner(p):
        c = _campo_desde_paso(p, info.get(id(p)))
        for k, otro in enumerate(campos):
            if _mismo_campo(otro["selectores"], c["selectores"]):
                campos[k] = c
                return
        campos.append(c)

    j = i
    while j < len(pasos):
        p = pasos[j]
        if p.desactivado or not mismo_sitio(p):
            break
        if p.tipo == "escribir":
            poner(p)
            usados.append(j)
        elif p.tipo == "clic" and p.boton == "izquierdo" and not p.doble:
            usados.append(j)
            if not _clic_incidental(p, info.get(id(p))):
                enviar = {"selectores": list(p.selectores), "objetivo": p.objetivo}
                j += 1
                break
        elif p.tipo == "tecla" and p.tecla == "Enter":
            usados.append(j)
            enviar = {"tecla": "Enter"}
            j += 1
            break
        elif p.tipo == "pasar_raton" and p.auto:
            usados.append(j)
        else:
            break
        j += 1
    if enviar is None or not any(c["tipo"] == "clave" for c in campos):
        return None
    # Reintentos al grabar (p. ej. se corrigió el usuario y se pulsó otra vez «Entrar»): se juntan en el mismo paso.
    k, pendientes, extra = j, [], []
    while k < len(pasos):
        p = pasos[k]
        if p.desactivado or not mismo_sitio(p):
            break
        if p.tipo == "escribir" and any(_mismo_campo(c["selectores"], p.selectores) for c in campos):
            pendientes.append(p)
            extra.append(k)
        elif p.tipo == "clic" and enviar.get("selectores") and _mismo_campo(enviar["selectores"], p.selectores):
            for q in pendientes:
                poner(q)
            extra.append(k)
            usados.extend(extra)
            pendientes, extra = [], []
            j = k + 1
        elif p.tipo == "clic" and _clic_incidental(p, info.get(id(p))):
            extra.append(k)
        elif p.tipo == "tecla" and p.tecla == "Enter" and enviar.get("tecla") and pendientes:
            for q in pendientes:
                poner(q)
            extra.append(k)
            usados.extend(extra)
            pendientes, extra = [], []
            j = k + 1
        else:
            break
        k += 1
    campos = _quitar_clones(campos)
    sitio = meta0.get("host") or host
    nuevo = Paso("iniciar_sesion", sitio=sitio, campos=campos, enviar=enviar, pagina=pagina, marco=list(marco),
                 espera_grabada=primero.espera_grabada,
                 nota="Si la página ya tiene la sesión abierta, se omite; si falta o se rechaza la contraseña, "
                      "se pide.")
    return j, nuevo, sorted(set(usados))


def agrupar_inicio_sesion(pasos, url="", info=None, solo_al_inicio=False):
    """Junta las secuencias de inicio de sesión (escribir usuario/contraseña + clic en «Entrar», con los clics
    sueltos del «ojito» o del recuadro del campo entre medias) en un único paso «iniciar_sesion».

    - `info`: {id(paso): {token, rol, clave, host}} que manda el grabador (qué pasos son del mismo formulario
      de inicio de sesión).  Con `info` se agrupa donde esté el formulario.
    - `solo_al_inicio` (reportes ya guardados, sin `info`): solo lo que está justo después del primer
      «Abrir la página» y lleva al menos una contraseña guardada aparte ({secreto:…}).
    Devuelve (pasos_nuevos, [(primer_indice, ultimo_indice, paso_nuevo)])."""
    info = info or {}
    res, grupos = [], []
    host = host_de(url)
    primero_abrir = next((k for k, p in enumerate(pasos) if p.tipo == "abrir_url"), None)
    if primero_abrir is not None:
        host = host_de(pasos[primero_abrir].url) or host
    inicio_posible = None
    if solo_al_inicio:
        if primero_abrir is None:
            return list(pasos), []
        inicio_posible = primero_abrir + 1
        while inicio_posible < len(pasos) and pasos[inicio_posible].desactivado:
            inicio_posible += 1
    i = 0
    while i < len(pasos):
        p = pasos[i]
        if solo_al_inicio:
            candidato = i == inicio_posible
        else:
            candidato = bool(info.get(id(p), {}).get("token"))
        g = _grupo_inicio_sesion(pasos, i, info, host) if candidato else None
        if g is not None and solo_al_inicio and not any(pasos[k].es_secreto() for k in g[2]):
            g = None
        if g is not None:
            fin, nuevo, _usados = g
            res.append(nuevo)
            grupos.append((i, fin - 1, nuevo))
            i = fin
            continue
        res.append(p)
        i += 1
    return res, grupos


def migrar_flujo(flujo):
    """Actualiza (en el sitio) un flujo de una versión anterior al formato actual.  Devuelve la lista de
    mensajes de lo que cambió en los pasos (vacía si solo cambió el número de versión)."""
    mensajes = []
    if flujo.version < 3:
        nuevos, grupos = agrupar_inicio_sesion(flujo.pasos, flujo.url, solo_al_inicio=True)
        for a, b, paso in grupos:
            mensajes.append("los pasos %d a %d (inicio de sesión) se juntaron en «%s»" % (a + 1, b + 1, paso.descripcion()))
        flujo.pasos = nuevos
    flujo.version = VERSION_FORMATO
    return mensajes


# --- v3.0: elegir una opción de una lista (estrategias) ----------------------

_RX_FECHA_DMY = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
_RX_FECHA_YMD = re.compile(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b")
_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
          "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
          "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "sept": 9,
          "oct": 10, "nov": 11, "dic": 12,
          "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
          "september": 9, "october": 10, "november": 11, "december": 12}
_RX_MES_ANIO = re.compile(r"\b([A-Za-zÁÉÍÓÚáéíóúñÑ]{3,10})\.?\s+(?:de\s+)?(\d{4})\b", re.IGNORECASE)


def clave_reciente(texto):
    """Clave para comparar opciones por «lo más reciente»: (fecha más alta del texto, año, número inicial).

    «45 - 2026 (16/10/2026 - 22/10/2026)» > «44 - 2026 (09/10/2026 - 15/10/2026)»; «Octubre 2026» > «Septiembre 2026»;
    «2026-10-25» > «2026-10-24»; «Semana 12» > «Semana 9»."""
    import datetime as _dt
    t = _normal(texto)
    fechas = []
    for d, m, a in _RX_FECHA_DMY.findall(t):
        try:
            fechas.append(_dt.date(int(a), int(m), int(d)))
        except ValueError:
            pass
    for a, m, d in _RX_FECHA_YMD.findall(t):
        try:
            fechas.append(_dt.date(int(a), int(m), int(d)))
        except ValueError:
            pass
    for mes, a in _RX_MES_ANIO.findall(t):
        n = _MESES.get(mes.lower())
        if n:
            fechas.append(_dt.date(int(a), n, 1))
    sin_fechas = _RX_FECHA_YMD.sub(" ", _RX_FECHA_DMY.sub(" ", t))
    numeros = [int(x) for x in re.findall(r"\d+", sin_fechas)]
    anio = next((n for n in numeros if 1900 <= n <= 2100), 0)
    otros = [n for n in numeros if not (1900 <= n <= 2100)]
    return (max(fechas) if fechas else _dt.date.min, anio, otros[0] if otros else -1)


_RX_FECHA_DMY_CORTA = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2})\b")
_RX_FECHA_LARGA = re.compile(r"\b(\d{1,2})\s+(?:de\s+)?([A-Za-zÁÉÍÓÚáéíóúñÑ]{3,10})\.?,?\s+(?:de\s+|del\s+)?(\d{4})\b", re.IGNORECASE)


def fechas_en_texto(texto):
    """v3.8: las fechas COMPLETAS (día, mes y año) de un texto, en orden: 04/11/2026, 4-11-2026, 04.11.26, 2026-11-04,
    «4 de noviembre de 2026», «4 Nov 2026».  Con números siempre se lee día/mes (la regla del proyecto), sin adivinar:
    «11/25/2026» no es una fecha válida y no cuenta.  «Noviembre 2026» no cuenta: le falta el día."""
    import datetime as _dt
    t = _normal(texto)
    halladas = []

    def anotar(pos, a, m, d):
        try:
            halladas.append((pos, _dt.date(int(a), int(m), int(d))))
        except ValueError:
            pass
    for x in _RX_FECHA_YMD.finditer(t):
        anotar(x.start(), x.group(1), x.group(2), x.group(3))
    for x in _RX_FECHA_DMY.finditer(t):
        anotar(x.start(), x.group(3), x.group(2), x.group(1))
    for x in _RX_FECHA_DMY_CORTA.finditer(t):
        anotar(x.start(), 2000 + int(x.group(3)), x.group(2), x.group(1))
    for x in _RX_FECHA_LARGA.finditer(t):
        n = _MESES.get(x.group(2).lower())
        if n:
            anotar(x.start(), x.group(3), n, x.group(1))
    return [f for _p, f in sorted(halladas, key=lambda y: y[0])]


def fecha_de_valor(valor):
    """v3.8: la fecha de un valor ya calculado («04/11/2026», «2026-11-04», «20261104», «04 Nov 2026»), o None."""
    import datetime as _dt
    a = plantillas.analizar_fecha(valor)
    if a.get("modo") == "fija":
        return _dt.datetime.strptime(a["fecha"], "%Y-%m-%d").date()
    s = _normal(valor)
    if re.fullmatch(r"\d{8}", s):
        try:
            return _dt.datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None
    f = fechas_en_texto(s)
    return f[0] if len(f) == 1 else None


def indice_por_fecha(textos, valor):
    """v3.8: índice de la opción de esa fecha, o None (NUNCA otra más vieja).  Primero la opción que solo lleva esa fecha
    («Corte 04/11/2026»); si no, una con esa fecha en su periodo («45 - 2026 (16/10/2026 - 22/10/2026)»)."""
    objetivo = fecha_de_valor(valor)
    if objetivo is None:
        return None
    en_periodo = None
    for i, t in enumerate(textos):
        fechas = fechas_en_texto(t)
        if not fechas:
            continue
        if len(fechas) == 1:
            if fechas[0] == objetivo:
                return i
        elif en_periodo is None and min(fechas) <= objetivo <= max(fechas):
            en_periodo = i
    return en_periodo


def es_reconocible(texto):
    """True si el texto lleva alguna fecha, año o número con el que ordenar por «lo más reciente»."""
    return clave_reciente(texto) != clave_reciente("")


def tiene_fecha_o_anio(texto):
    k = clave_reciente(texto)
    return k[0] != clave_reciente("")[0] or k[1] != 0


def parece_cronologica(textos):
    """True si la lista parece de periodos (cortes, meses, fechas): al menos 2 opciones y la mayoría con fecha o año."""
    textos = [t for t in textos or [] if _normal(t)]
    if len(textos) < 2:
        return False
    con = sum(1 for t in textos if tiene_fecha_o_anio(t))
    return con * 10 >= len(textos) * 6


def ordenar_recientes(textos):
    """Los textos de la más reciente a la más antigua (clave_reciente); si empatan, en el orden de la página.  Las que
    no tienen fecha, año ni número van al final, también en el orden de la página."""
    return sorted(list(textos or []), key=clave_reciente, reverse=True)   # sorted es estable también con reverse


def describir_opcion(texto):
    """Resumen legible del periodo de una opción: «año 2026 · del 09/10/2026 al 15/10/2026», «octubre de 2026»…  "" si
    el texto no lleva fechas ni año."""
    import datetime as _dt
    t = _normal(texto)
    fechas = []
    for d, m, a in _RX_FECHA_DMY.findall(t):
        try:
            fechas.append(_dt.date(int(a), int(m), int(d)))
        except ValueError:
            pass
    for a, m, d in _RX_FECHA_YMD.findall(t):
        try:
            fechas.append(_dt.date(int(a), int(m), int(d)))
        except ValueError:
            pass
    k = clave_reciente(texto)
    partes = []
    anio = k[1] or (max(fechas).year if fechas else 0)
    if not fechas:
        for mes, a in _RX_MES_ANIO.findall(t):
            n = _MESES.get(mes.lower())
            if n:
                nombres = [m for m, v in _MESES.items() if v == n and len(m) > 4] or [mes.lower()]
                return "%s de %s" % (nombres[0], a)
    if anio:
        partes.append("año %d" % anio)
    if len(fechas) >= 2:
        partes.append("del %s al %s" % (min(fechas).strftime("%d/%m/%Y"), max(fechas).strftime("%d/%m/%Y")))
    elif fechas:
        partes.append(fechas[0].strftime("%d/%m/%Y"))
    return " · ".join(partes)


_RX_ETIQUETA_GENERICA = re.compile(
    r"^(open|close|abrir|cerrar|toggle|menu|menú|clear|borrar|limpiar|expand|collapse|desplegar|plegar|mostrar|ocultar|"
    r"show|hide|appended action|prepended action|dropdown|select|seleccionar|elegir|lista|la lista|list|listbox|combobox|"
    r"options|opciones|search|buscar|arrow(?:[ _-][\w-]*)?|chevron(?:[ _-][\w-]*)?|caret(?:[ _-][\w-]*)?|"
    r"(?:mdi|fa|fas|far|bi|icon|material-icons)(?:[ _-][\w-]*)?|"
    r"div|span|input|label|button|svg|path|li|ul|form|▾|▼|⌄|˅)$", re.IGNORECASE)


def etiqueta_generica(texto):
    """True si un texto no sirve como nombre de un filtro: «Open»/«Close» (aria-label de los iconos de Vuetify),
    «Abrir», nombres de iconos («mdi-menu-down»), etiquetas HTML («div»), flechas…"""
    t = _normal(texto)
    return len(t) < 2 or bool(_RX_ETIQUETA_GENERICA.match(t))


def elegir_indice(textos, estrategia="fija", valor=""):
    """Índice de la opción elegida entre `textos` (ya leídos de la lista) o None si ninguna vale.

    - fija: el texto exacto (sin distinguir mayúsculas ni espacios de más);
    - mas_reciente: la de clave_reciente más alta (si empatan, la primera);
    - primera / ultima;
    - contiene: la primera que contiene `valor` (o que casa con él como expresión regular);
    - por_fecha: la de la fecha `valor` (ya calculada), o None si esa fecha no está (ver `indice_por_fecha`)."""
    textos = [_normal(t) for t in textos]
    validos = [i for i, t in enumerate(textos) if t]
    if not validos:
        return None
    est = estrategia or "fija"
    v = _normal(valor)
    if est == "fija":
        return next((i for i in validos if textos[i].lower() == v.lower()), None)
    if est == "primera":
        return validos[0]
    if est == "ultima":
        return validos[-1]
    if est == "contiene":
        if not v:
            return None
        k = next((i for i in validos if v.lower() in textos[i].lower()), None)
        if k is not None:
            return k
        try:
            rx = re.compile(valor, re.IGNORECASE)
        except re.error:
            return None
        return next((i for i in validos if rx.search(textos[i])), None)
    if est == "por_fecha":
        k = indice_por_fecha([textos[i] for i in validos], valor)
        return validos[k] if k is not None else None
    if est == "mas_reciente":
        mejor = None
        for i in validos:
            if mejor is None or clave_reciente(textos[i]) > clave_reciente(textos[mejor]):
                mejor = i
        return mejor
    raise ErrorFlujo("Estrategia no válida: %s" % est)


_RX_SEL_OPCION = re.compile(r"role=option|\[role=\"?option|v-list-item|\boption\b|listbox|role=menuitem|"
                            r"select2-results|mat-option|dropdown-item|ui-menu-item|\.v-overlay|#v-menu", re.IGNORECASE)


def texto_de_opcion(paso):
    """Texto de la opción que pulsa un clic grabado (de role=option[name="…"], :text-is("…") o su nombre)."""
    for sel in paso.selectores:
        m = re.search(r'name="((?:[^"\\]|\\.)*)"', sel) if sel.startswith("role=") else None
        if m:
            return m.group(1).replace('\\"', '"')
        m = re.search(r':text-is\("((?:[^"\\]|\\.)*)"\)', sel)
        if m:
            return m.group(1).replace('\\"', '"')
    return paso.objetivo or ""


def es_clic_en_opcion(paso):
    return paso.tipo == "clic" and not paso.desactivado and any(_RX_SEL_OPCION.search(s or "") for s in paso.selectores)


def pares_lista_opcion(pasos):
    """Pares «abrir la lista + clic en una opción» que se pueden convertir en un paso «Elegir opción».

    Devuelve [(i_abrir, i_opcion, texto_opcion)]: pasos[i_abrir] es un clic izquierdo (no en una opción) y el
    siguiente paso (saltando los «Pasar el ratón» automáticos) es un clic en una opción de una lista."""
    res = []
    i = 0
    while i < len(pasos) - 1:
        p = pasos[i]
        if p.tipo == "clic" and not p.desactivado and p.boton == "izquierdo" and not p.doble and not es_clic_en_opcion(p):
            j = i + 1
            while j < len(pasos) and pasos[j].tipo == "pasar_raton" and pasos[j].auto:
                j += 1
            if j < len(pasos) and es_clic_en_opcion(pasos[j]) and pasos[j].pagina == p.pagina \
                    and pasos[j].marco == p.marco and texto_de_opcion(pasos[j]):
                res.append((i, j, texto_de_opcion(pasos[j])))
                i = j + 1
                continue
        i += 1
    return res


def paso_elegir_desde_par(abrir, opcion, texto, estrategia="fija", objetivo=""):
    nombre = objetivo or (abrir.objetivo if abrir.objetivo and abrir.objetivo.lower() not in
                          ("div", "span", "i", "input", "label") else "") or "la lista"
    return Paso("elegir_opcion", selectores=list(abrir.selectores), objetivo=nombre, estrategia=estrategia,
                valor=plantillas.escapar(texto) if estrategia in ("fija", "contiene") else "",
                pagina=abrir.pagina, marco=list(abrir.marco), espera_grabada=abrir.espera_grabada,
                nota="Convertido de «%s» + «%s»." % (abrir.descripcion()[:60], opcion.descripcion()[:60]))


def convertir_listas(flujo, pares=None, estrategias=None):
    """Convierte (bajo pedido, no automáticamente) los pares «abrir lista + clic en opción» en pasos «Elegir opción».

    `pares`: los i_abrir a convertir (por defecto, todos los de `pares_lista_opcion`); `estrategias`: {i_abrir:
    estrategia}.  Devuelve la lista de mensajes."""
    encontrados = pares_lista_opcion(flujo.pasos)
    elegidos = [x for x in encontrados if pares is None or x[0] in set(pares)]
    if not elegidos:
        return []
    estrategias = estrategias or {}
    quitar, nuevos, mensajes = set(), {}, []
    for i, j, texto in elegidos:
        paso = paso_elegir_desde_par(flujo.pasos[i], flujo.pasos[j], texto, estrategias.get(i, "fija"))
        nuevos[i] = paso
        quitar.update(range(i + 1, j + 1))
        mensajes.append("pasos %d y %d → «%s»" % (i + 1, j + 1, paso.descripcion()))
    flujo.pasos = [nuevos.get(k, p) for k, p in enumerate(flujo.pasos) if k not in quitar]
    return mensajes


# --- v3.0: repetir un reporte por días ---------------------------------------

def validar_repetir_dias(conf):
    """Lanza ErrorFlujo si la configuración de «Repetir por días» no es válida (None / vacía = no repetir)."""
    if not conf:
        return
    if not isinstance(conf, dict):
        raise ErrorFlujo("configuración no válida")
    modo = conf.get("modo") or "no"
    if modo in ("no", ""):
        return
    if modo not in MODOS_DIAS:
        raise ErrorFlujo("modo no válido: %s" % modo)
    if modo == "fijo":
        import datetime as _dt
        try:
            d = _dt.date.fromisoformat(str(conf.get("desde")))
            h = _dt.date.fromisoformat(str(conf.get("hasta") or conf.get("desde")))
        except ValueError:
            raise ErrorFlujo("las fechas deben tener el formato AAAA-MM-DD")
        if h < d:
            raise ErrorFlujo("la fecha final es anterior a la inicial")
        if (h - d).days > 366:
            raise ErrorFlujo("como mucho 366 días")
    if modo == "ultimos":
        try:
            n = int(conf.get("n") or 0)
        except (TypeError, ValueError):
            raise ErrorFlujo("el número de días debe ser un número")
        if not 1 <= n <= 366:
            raise ErrorFlujo("el número de días debe estar entre 1 y 366")


def dias_a_repetir(conf, hoy=None):
    """Fechas (datetime.date, de la más antigua a la más reciente) en las que hay que ejecutar el reporte, o []
    si no se repite.  ultimos N = los N días hasta ayer; mes_hasta_ayer = del día 1 del mes hasta ayer (si hoy es día
    1: el mes anterior entero); ayer = solo ayer."""
    import datetime as _dt
    validar_repetir_dias(conf)
    if not conf or (conf.get("modo") or "no") in ("no", ""):
        return []
    base = hoy or _dt.date.today()
    if isinstance(base, _dt.datetime):
        base = base.date()
    ayer = base - _dt.timedelta(days=1)
    modo = conf["modo"]
    if modo == "ayer":
        return [ayer]
    if modo == "ultimos":
        n = int(conf.get("n") or 1)
        return [ayer - _dt.timedelta(days=k) for k in range(n - 1, -1, -1)]
    if modo == "mes_hasta_ayer":
        ini = ayer.replace(day=1)
        return [ini + _dt.timedelta(days=k) for k in range((ayer - ini).days + 1)]
    d = _dt.date.fromisoformat(str(conf["desde"]))
    h = _dt.date.fromisoformat(str(conf.get("hasta") or conf["desde"]))
    return [d + _dt.timedelta(days=k) for k in range((h - d).days + 1)]


def describir_repetir_dias(conf):
    if not conf or (conf.get("modo") or "no") in ("no", ""):
        return "no"
    modo = conf["modo"]
    if modo == "fijo":
        return "del %s al %s" % (conf.get("desde"), conf.get("hasta") or conf.get("desde"))
    if modo == "ultimos":
        return "los últimos %s días" % conf.get("n")
    return MODOS_DIAS.get(modo, modo)


# ============================================================================ v3.5: nombre de las descargas
# Antes, al grabar, el paso «Descargar» se quedaba con el nombre que da la web («report_xls{ext}»,
# «DetallesVentasMayorista{ext}»): todos los archivos se llamaban igual («report_xls (6).xlsx»).  Ahora, por defecto,
# llevan el nombre COMPLETO del reporte y la fecha; el nombre de la web sigue disponible como {nombre}.
NOMBRE_DESCARGA_DEFECTO = "{reporte} {hoy:%Y-%m-%d}{ext}"
NOMBRE_DESCARGA_VARIAS = "{reporte} - {nombre} {hoy:%Y-%m-%d}{ext}"     # si el reporte descarga varios archivos
NOMBRE_DESCARGA_WEB = "{nombre}{ext}"
NOMBRES_POR_DEFECTO = (NOMBRE_DESCARGA_DEFECTO, NOMBRE_DESCARGA_VARIAS)


def es_nombre_de_la_web(nombre):
    """¿Es el nombre que dejaba la grabación hasta la 3.4: el nombre fijo que da la web + «{ext}» (sin ninguna otra
    plantilla, sin {reporte})?  P. ej. «report_xls{ext}» o «DetallesVentasMayorista{ext}».  Los nombres con fechas u
    otras plantillas ({hoy:…}, {opcion}, {nombre}…) se consideran elegidos por el usuario y no se tocan."""
    from . import plantillas
    n = nombre or ""
    if not n.endswith("{ext}") or len(n) <= len("{ext}"):
        return False
    base = n[:-len("{ext}")]
    try:
        fichas = plantillas._tokens(base)
    except plantillas.ErrorPlantilla:
        return False
    return bool(fichas) and all(c == "lit" for c, _ in fichas) and bool("".join(t for _c, t in fichas).strip())


def nombre_descarga_defecto(varias=False, por_dias=False):
    """La plantilla por defecto del nombre de un archivo descargado.  `varias`: el reporte descarga más de un archivo
    (se añade el nombre de la web para distinguirlos); `por_dias`: «Repetir por días» ({fecha} = el día descargado)."""
    t = NOMBRE_DESCARGA_VARIAS if varias else NOMBRE_DESCARGA_DEFECTO
    return t.replace("{hoy:", "{fecha:") if por_dias else t


def usar_nombre_del_reporte(flujo, solo_de_la_web=True):
    """Pone el nombre por defecto («{reporte} {hoy:%Y-%m-%d}{ext}») en los pasos «Descargar» que tienen el nombre de la
    web (`es_nombre_de_la_web`; con `solo_de_la_web=False` también los vacíos y «{nombre}{ext}»).  Cambia `flujo` y
    devuelve [(índice, antes, después)]."""
    descargas = [i for i, p in enumerate(flujo.pasos) if p.tipo == "descargar" and not p.desactivado]
    por_dias = bool((flujo.opciones or {}).get("repetir_dias"))
    nuevo = nombre_descarga_defecto(varias=len(descargas) > 1, por_dias=por_dias)
    cambios = []
    for i, p in enumerate(flujo.pasos):
        if p.tipo != "descargar":
            continue
        antes = p.nombre or ""
        vale = es_nombre_de_la_web(antes) or (not solo_de_la_web and antes.strip() in ("", NOMBRE_DESCARGA_WEB))
        if vale and antes != nuevo:
            p.nombre = nuevo
            cambios.append((i, antes, nuevo))
    return cambios


def pasos_con_nombre_de_la_web(flujo):
    """Índices de los pasos «Descargar» que guardan el archivo con el nombre fijo que da la web."""
    return [i for i, p in enumerate(flujo.pasos) if p.tipo == "descargar" and es_nombre_de_la_web(p.nombre)]


# ============================================================================ v3.7: «Archivo descargado»
# El nombre y la carpeta de lo que se descarga, en «Opciones del reporte», en «Configurar esta página» y al terminar de
# mapear.  En la interfaz el nombre se escribe SIN la extensión (se pone sola: «{reporte} {hoy:%Y-%m-%d}» se guarda como
# «{reporte} {hoy:%Y-%m-%d}{ext}» en el paso «Descargar»); si no se toca nada, el paso se queda como estaba.
NOMBRE_ARCHIVO_DEFECTO = NOMBRE_DESCARGA_DEFECTO[:-len("{ext}")]          # «{reporte} {hoy:%Y-%m-%d}»
TIPOS_QUE_GUARDAN = ("descargar", "guardar_pagina")


def nombre_con_ext(nombre):
    """«Nombre del archivo» (como lo escribe el usuario) → la plantilla del paso «Descargar»: «{ext}» al final si no lo
    lleva.  Vacío = vacío (el paso guarda con el nombre que da la web, como siempre)."""
    n = (nombre or "").strip()
    if not n or "{ext}" in n:
        return n
    return n + "{ext}"


def nombre_sin_ext(plantilla):
    """Lo contrario de `nombre_con_ext`, para enseñarlo: «{reporte} {hoy:%Y-%m-%d}{ext}» → «{reporte} {hoy:%Y-%m-%d}»
    (si «{ext}» va en medio, se deja tal cual)."""
    p = plantilla or ""
    return p[:-len("{ext}")] if p.endswith("{ext}") else p


def pasos_que_guardan(flujo):
    """Índices de los pasos activos que guardan un archivo («Descargar» y «Guardar página»), en orden."""
    return [i for i, p in enumerate(flujo.pasos) if p.tipo in TIPOS_QUE_GUARDAN and not p.desactivado]


def vista_archivo(plantilla, tipo="descargar", reporte="", variables=None, hoy=None, carpeta="", subcarpeta="",
                  formato="pdf", carpeta_forzada=None, raiz=None, ext=".xlsx", nombre_web="nombre_que_da_la_web",
                  fecha=None):
    """(archivo, carpeta) de ejemplo, calculados como los calcula el Ejecutor: `plantilla` = el nombre del paso tal como
    se guarda (con {ext}), `carpeta` = la carpeta de descargas del reporte o de la Página (vacío = «descargas» del bot,
    o `carpeta_forzada` si el bot se abrió con otra), `subcarpeta` = la carpeta propia del paso (relativa = dentro de la
    anterior).  Las contraseñas no se resuelven.  Lanza `plantillas.ErrorPlantilla` si el nombre no es válido."""
    from .ejecutor import nombre_archivo_seguro          # (sin playwright: se importa al usarlo)
    if raiz is None:
        from . import RAIZ as raiz

    def r(texto, **extra):
        return plantillas.renderizar(texto, variables=variables or {}, hoy=hoy, enmascarar_secretos=True,
                                     reporte=reporte or "", fecha=fecha, **extra)
    if tipo == "guardar_pagina":
        e = "." + (formato or "html").lower()
        archivo = nombre_archivo_seguro(r(plantilla or "Pagina_{hoy:%Y-%m-%d}", ext=e, nombre="Título de la página"))
        if not archivo.lower().endswith(e):
            archivo += e
    else:
        archivo = nombre_archivo_seguro(r(plantilla or NOMBRE_DESCARGA_WEB, ext=ext, nombre=nombre_web))
    base = os.path.abspath(carpeta_forzada or carpeta or os.path.join(raiz, "descargas"))
    if subcarpeta:
        c = r(subcarpeta)
        base = c if os.path.isabs(c) else os.path.join(base, c)
    return archivo, base
