"""v3.4 «Correo»: buscar correos (Outlook, Gmail o cualquier buzón IMAP), descargar sus adjuntos y copiar texto o
tablas de su cuerpo.  No importa playwright ni tkinter: aquí está todo lo que no depende del proveedor y se puede
probar sin navegador.

Ideas (reutilizadas del programa «Octopus» —`data_correo/motor/descargar_reporte.py` y `reglas.py`— y ampliadas):

- **Qué correo** (`criterios`): asunto contiene, remitente (contiene / exacto), fecha (hoy, ayer, últimos N días,
  desde–hasta con plantillas como `{dias:-7}`), trozos del cuerpo, «tiene adjunto», nombre o extensión del adjunto.  Las
  comparaciones no distinguen mayúsculas, acentos, espacios ni puntuación (`normalizar`: «S.A.S.», «S. A. S.» y «SAS»
  valen igual), como en Octopus.
- A diferencia de Octopus (un solo correo: el más reciente), una búsqueda procesa **todos** los correos que
  coinciden y todavía no se procesaron, del más reciente al más antiguo, con un máximo por revisión.  Cada correo
  procesado se apunta en `correos_procesados` (por su identificador del proveedor y la fecha, o una huella de remitente +
  asunto + fecha), así que nunca se procesa dos veces; «volver a procesar» lo olvida.
- **Qué hacer** (`acciones`): descargar adjuntos (todos o los que coinciden, descomprimir .zip, carpeta y nombre con
  plantillas: las de siempre más `{fecha_correo:%Y-%m-%d}`, `{asunto}`, `{remitente}`, `{adjunto}`, `{ext}`, `{n}`),
  copiar un texto del cuerpo («lo que va después de…», «entre… y…», o una expresión regular) —se muestra en el aviso y
  el historial y, si se quiere, se añade a un CSV/Excel o a un .txt—, copiar una tabla del cuerpo a Excel/CSV (agregar,
  reemplazar u hoja por mes) y guardar el cuerpo como .html/.txt.
- Los **proveedores** (`correo_outlook.py`, `correo_gmail.py`, `correo_imap.py`) tienen la misma interfaz pequeña:
  `with crear_adaptador(cuenta, …) as a: a.buscar(criterios, hoy, limite) → [resumen]; a.abrir(resumen) → detalle;
  a.descargar(resumen, detalle, nombres, carpeta) → {nombre: ruta}`.  Un resumen es un dict {id, asunto, remitente,
  remitente_correo, fecha (datetime o None), adjuntos (lista de nombres o None si no se sabe), tiene_adjuntos (True,
  False o None), texto (todo el texto de la fila, si no se sabe separar el asunto)}; un detalle añade html, texto y
  adjuntos [{nombre, tamano}].
- Si el proveedor ve la pantalla de inicio de sesión lanza `ErrorSesion` (la sesión caducó): la revisión lo avisa
  claro («Abre Correo y pulsa «Iniciar sesión en el correo»») y nunca escribe la contraseña de Microsoft o Google.
"""

import csv
import datetime
import email.utils
import hashlib
import html as mod_html
import io
import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
import zipfile
from html.parser import HTMLParser

from . import avisos, plantillas

try:                                    # openpyxl solo hace falta para escribir .xlsx (si no está: CSV)
    import openpyxl  # noqa: F401
    HAY_OPENPYXL = True
except ImportError:                     # pragma: no cover
    HAY_OPENPYXL = False

PROVEEDORES = {
    "outlook_web": "Outlook / Microsoft 365 (en el navegador)",
    "gmail_web": "Gmail (en el navegador)",
    "imap": "Otro buzón por IMAP (usuario y contraseña de aplicación)",
}
URL_OUTLOOK = "https://outlook.cloud.microsoft/mail/inbox"
URL_GMAIL = "https://mail.google.com/mail/u/0/"
MODOS_FECHA = {"cualquiera": "cualquier fecha", "hoy": "de hoy", "ayer": "de ayer", "ultimos": "de los últimos días",
               "rango": "entre dos fechas"}
TIPOS_ACCION = {"adjuntos": "Descargar los adjuntos", "texto": "Copiar un texto del cuerpo",
                "tabla": "Copiar una tabla del cuerpo a Excel/CSV", "cuerpo": "Guardar el cuerpo del correo"}
MODOS_TEXTO = {"despues": "lo que va después de", "entre": "lo que va entre", "regex": "expresión regular"}
MODOS_TABLA = {"agregar": "agregar las filas al final", "reemplazar": "reemplazar la hoja",
               "hoja_mes": "una hoja por mes"}
MAX_POR_VEZ = 10                        # correos nuevos que se procesan como mucho en cada revisión (por defecto)
MAX_POR_VEZ_TOPE = 100
MAX_INTENTOS = 3                        # un correo cuyas acciones fallan se reintenta en las revisiones siguientes
EXTENSIONES_CONOCIDAS = {"xlsx", "xlsm", "xls", "csv", "txt", "pdf", "zip", "docx", "doc", "html", "htm", "json", "xml",
                         "png", "jpg", "jpeg", "pptx", "ppt", "rar", "7z", "tsv"}
COLUMNAS_TEXTO = ["Fecha", "Asunto", "Campo", "Valor"]

AYUDA_PLANTILLAS = [
    ("{fecha_correo:%Y-%m-%d}", "Fecha del correo (aaaa-mm-dd)"),
    ("{fecha_correo:%d-%m-%Y}", "Fecha del correo (dd-mm-aaaa)"),
    ("{asunto}", "Asunto del correo"),
    ("{remitente}", "Quién lo envía"),
    ("{adjunto}", "Nombre original del adjunto, sin la extensión"),
    ("{ext}", "Extensión del adjunto (.xlsx, .pdf…)"),
    ("{n}", "Número del archivo dentro del correo (1, 2, 3…)"),
    ("{reporte}", "Nombre completo de la búsqueda"),
    ("{hoy:%Y-%m-%d}", "Fecha de hoy"),
]


class ErrorCorreo(ValueError):
    """La búsqueda o una acción no es válida (el mensaje es para una persona)."""


class ErrorSesion(RuntimeError):
    """El proveedor enseña la pantalla de inicio de sesión: la sesión guardada caducó (o nunca se inició)."""


class ErrorProveedor(RuntimeError):
    """El buzón no respondió como se esperaba (no cargó, no se encontró el buscador, IMAP rechazó la conexión…)."""


# ============================================================================== textos
def normalizar(texto):
    """Solo letras y números en MAYÚSCULAS, sin acentos (de Octopus): «Servicios, S.A.S.» → «SERVICIOSSAS»."""
    base = unicodedata.normalize("NFKD", str(texto or ""))
    base = "".join(c for c in base if not unicodedata.combining(c))
    return re.sub(r"[^0-9A-Za-z]+", "", base).upper()


def contiene(texto, fragmento):
    """¿`texto` contiene `fragmento` sin contar mayúsculas, acentos, espacios ni puntuación?  (Vacío = sí.)"""
    f = normalizar(fragmento)
    return not f or f in normalizar(texto)


def _plano(texto):
    """Minúsculas sin acentos conservando la LONGITUD (cada carácter por su letra base): para buscar una etiqueta y
    cortar el texto original en la misma posición."""
    salida = []
    for c in str(texto or ""):
        d = unicodedata.normalize("NFKD", c)
        b = d[0] if d else c
        salida.append(b.lower() if len(b.lower()) == 1 else b)
    return "".join(salida)


def _patron_etiqueta(etiqueta):
    """«Total ventas:» → regex (sobre el texto `_plano`) que admite cualquier cantidad de espacios entre las palabras y
    los signos («Total  ventas :» también vale)."""
    partes = re.findall(r"\w+|[^\w\s]", _plano(etiqueta))
    if not partes:
        return None
    return re.compile(r"\s*".join(re.escape(p) for p in partes))


def correo_de(remitente):
    """«Reportes <reportes@ejemplo.com>» → «reportes@ejemplo.com» ('' si no hay)."""
    _n, dire = email.utils.parseaddr(str(remitente or ""))
    if "@" in dire:
        return dire.strip().lower()
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(remitente or ""))
    return m.group(0).lower() if m else ""


def nombre_de(remitente):
    """«Reportes Ventas <reportes@ejemplo.com>» → «Reportes Ventas» (o la dirección si no hay nombre)."""
    nombre, dire = email.utils.parseaddr(str(remitente or ""))
    return (nombre or dire or str(remitente or "")).strip()


# ------------------------------------------------------------------------------ HTML → texto y tablas
class _Texto(HTMLParser):
    BLOQUES = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "section",
               "article", "header", "footer", "blockquote", "pre", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []
        self._omitir = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self._omitir += 1
        elif tag in self.BLOQUES:
            self.partes.append("\n")
        elif tag in ("td", "th"):
            self.partes.append("\t")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self._omitir = max(0, self._omitir - 1)
        elif tag in self.BLOQUES:
            self.partes.append("\n")

    def handle_data(self, data):
        if not self._omitir:
            self.partes.append(data)


def html_a_texto(html):
    """El texto de un HTML (párrafos y filas en líneas distintas, celdas separadas por tabulador)."""
    p = _Texto()
    try:
        p.feed(html or "")
        p.close()
    except Exception:                  # noqa: BLE001 (un HTML roto no debe tumbar la revisión)
        return re.sub(r"<[^>]+>", " ", html or "")
    texto = "".join(p.partes).replace("\xa0", " ")
    lineas = []
    for linea in texto.splitlines():
        celdas = [re.sub(r"[ \r\f\v]+", " ", c).strip() for c in linea.split("\t")]
        linea = "\t".join(c for c in celdas if c)
        if linea or (lineas and lineas[-1]):
            lineas.append(linea)
    return "\n".join(lineas).strip()


_ENTERO = re.compile(r"^-?\d+$")
_MILES = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_DECIMAL = re.compile(r"^-?\d+\.\d+$")


def valor_de_texto(texto):
    """(De Octopus) «1,234.50» → 1234.5; «42» → 42.  Lo demás (y códigos con ceros delante o muy largos) es texto."""
    t = (texto or "").strip() if isinstance(texto, str) else texto
    if not isinstance(t, str):
        return t
    digitos = t.lstrip("-")
    if _ENTERO.match(t) and len(digitos) < 16 and not (len(digitos) > 1 and digitos.startswith("0")):
        return int(t)
    if _MILES.match(t) or _DECIMAL.match(t):
        try:
            return float(t.replace(",", ""))
        except ValueError:
            return t
    return t


class _Tablas(HTMLParser):
    """(De Octopus) las tablas de un HTML en orden, celda a celda; las que solo envuelven a otras (maquetación de
    Outlook) no cuentan."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._abiertas = []
        self._orden = 0
        self.cerradas = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self._abiertas:
                self._abiertas[-1]["contenedora"] = True
            self._abiertas.append({"orden": self._orden, "filas": [], "celda": None, "contenedora": False})
            self._orden += 1
        elif not self._abiertas:
            return
        elif tag == "tr":
            self._abiertas[-1]["filas"].append([])
        elif tag in ("td", "th"):
            t = self._abiertas[-1]
            if not t["filas"]:
                t["filas"].append([])
            t["celda"] = []
        elif tag in ("br", "p", "div") and self._abiertas[-1]["celda"] is not None:
            self._abiertas[-1]["celda"].append(" ")

    def handle_endtag(self, tag):
        if not self._abiertas:
            return
        t = self._abiertas[-1]
        if tag in ("td", "th") and t["celda"] is not None:
            t["filas"][-1].append(re.sub(r"\s+", " ", "".join(t["celda"])).strip())
            t["celda"] = None
        elif tag == "table":
            self._abiertas.pop()
            filas = [f for f in t["filas"] if any(c for c in f)]
            if filas and not t["contenedora"]:
                self.cerradas.append((t["orden"], filas))

    def handle_data(self, data):
        if self._abiertas and self._abiertas[-1]["celda"] is not None:
            self._abiertas[-1]["celda"].append(data)


def tablas_html(html):
    """Las tablas con datos del HTML: [[[celda, …], …], …] (los números como números)."""
    lector = _Tablas()
    try:
        lector.feed(html or "")
        lector.close()
    except Exception:                  # noqa: BLE001
        pass
    return [[[valor_de_texto(c) for c in fila] for fila in filas] for _o, filas in sorted(lector.cerradas)]


# ------------------------------------------------------------------------------ copiar texto del cuerpo
def extraer_despues(texto, etiqueta):
    """Lo que va después de `etiqueta` hasta el final de la línea («Total ventas:» → «1.234»); si la etiqueta termina
    la línea, la línea siguiente con algo.  None si no está."""
    patron = _patron_etiqueta(etiqueta)
    if patron is None or not texto:
        return None
    m = patron.search(_plano(texto))
    if not m:
        return None
    resto = texto[m.end():]
    linea, _sep, despues = resto.partition("\n")
    valor = linea.strip().lstrip(":=-–").strip()
    if not valor:
        for siguiente in despues.splitlines():
            if siguiente.strip():
                valor = siguiente.strip().lstrip(":=-–").strip()
                break
    return re.sub(r"\s+", " ", valor).strip() or None


def extraer_entre(texto, desde, hasta):
    """Lo que va entre `desde` y `hasta` (sin `hasta`: hasta el final de la línea).  None si no está."""
    p1 = _patron_etiqueta(desde)
    if p1 is None or not texto:
        return None
    plano = _plano(texto)
    m = p1.search(plano)
    if not m:
        return None
    if not (hasta or "").strip():
        return extraer_despues(texto, desde)
    p2 = _patron_etiqueta(hasta)
    m2 = p2.search(plano, m.end())
    if not m2:
        return None
    valor = texto[m.end():m2.start()].strip().strip(":=").strip()
    return re.sub(r"\s+", " ", valor).strip() or None


def extraer_regex(texto, patron):
    """El primer grupo de la expresión (o todo lo que coincide).  None si no coincide."""
    try:
        m = re.search(patron, texto or "", re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        raise ErrorCorreo("La expresión regular no es válida: %s" % e)
    if not m:
        return None
    valor = next((g for g in m.groups() if g), None) if m.groups() else m.group(0)
    return (valor or m.group(0)).strip() or None


def extraer_texto(accion, texto):
    a = accion
    if a["modo"] == "regex":
        return extraer_regex(texto, a["regex"])
    if a["modo"] == "entre":
        return extraer_entre(texto, a["etiqueta"], a["hasta"])
    return extraer_despues(texto, a["etiqueta"])


# ============================================================================== fechas
MESES = {"ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
         "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12}
DIAS_SEMANA = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
               "lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}
_PATRON_FECHA = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_PATRON_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2}))?")
_PATRON_HORA = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)(?:[:.][0-5]\d)?\s*([AaPp])?\.?\s*[Mm]?\.?")


def _hora_de(texto):
    mh = _PATRON_HORA.search(texto or "")
    if not mh:
        return 0, 0
    hora, minuto = int(mh.group(1)), int(mh.group(2))
    sufijo = (mh.group(3) or "").lower()
    if sufijo == "p" and hora < 12:
        hora += 12
    elif sufijo == "a" and hora == 12:
        hora = 0
    return hora, minuto


def leer_fecha(texto):
    """La fecha (datetime) de textos como «Thu 10/29/2026 9:07 AM» (Outlook en inglés: M/D; en español: D/M; se
    desempata con el día de la semana, como en Octopus), «jue, 29 oct 2026, 9:07» (Gmail), «Oct 29, 2026, 9:07 AM»,
    «2026-10-29 09:07» o una cabecera Date de correo.  None si no hay fecha reconocible."""
    t = str(texto or "").strip()
    if not t:
        return None
    try:                                # cabecera «Date:» de un correo (RFC 2822: con zona horaria)
        if not re.search(r"[+-]\d{4}\s*(\(|$)|\b(GMT|UTC?)\b", t):
            raise ValueError("no es una cabecera Date")
        d = email.utils.parsedate_to_datetime(t)
        if d is not None:
            if d.tzinfo is not None:
                d = d.astimezone().replace(tzinfo=None)
            return d
    except (TypeError, ValueError, IndexError):
        pass
    m = _PATRON_ISO.search(t)
    if m:
        try:
            return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0),
                                     int(m.group(5) or 0))
        except ValueError:
            pass
    bajo = _plano(t)
    m = _PATRON_FECHA.search(t)
    if m:
        a, b, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
        candidatas = []
        for mes, dia in ((a, b), (b, a)):          # M/D primero (Outlook en inglés), luego D/M
            try:
                candidatas.append(datetime.date(anio, mes, dia))
            except ValueError:
                pass
        if not candidatas:
            return None
        elegida = candidatas[0]
        if re.search(r"[a-z]", bajo[:m.start()]) is None and len(candidatas) == 2 and a <= 12 and b <= 12:
            elegida = candidatas[1]                 # sin día de la semana delante: D/M (lo habitual en español)
        for nombre, indice in DIAS_SEMANA.items():
            if re.search(r"\b" + nombre, bajo):
                coinciden = [c for c in candidatas if c.weekday() == indice]
                if len(coinciden) > 1:
                    # v3.6.1: las dos lecturas caen el mismo día de la semana (11/1/2026: 1 de noviembre y 11 de enero
                    # son domingo): la más cercana a hoy (un correo es de ahora o de hace poco)
                    hoy = datetime.date.today()
                    coinciden.sort(key=lambda c: abs((c - hoy).days))
                if coinciden:
                    elegida = coinciden[0]
                break
        hora, minuto = _hora_de(t[m.end():])
        return datetime.datetime(elegida.year, elegida.month, elegida.day, hora, minuto)
    # «29 oct 2026, 9:07» / «Oct 29, 2026 9:07 AM» / «29 de octubre de 2026»
    m = re.search(r"\b(\d{1,2})\s+(?:de\s+)?([a-z]{3})[a-z]*\.?\s+(?:de\s+)?(\d{4})", bajo)
    orden = "dma"
    if not m:
        m = re.search(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", bajo)
        orden = "mda"
    if m:
        if orden == "dma":
            dia, mes_txt, anio = int(m.group(1)), m.group(2), int(m.group(3))
        else:
            mes_txt, dia, anio = m.group(1), int(m.group(2)), int(m.group(3))
        mes = MESES.get(mes_txt)
        if mes:
            try:
                hora, minuto = _hora_de(t[m.end():])
                return datetime.datetime(anio, mes, dia, hora, minuto)
            except ValueError:
                return None
    return None


def _a_fecha(valor):
    if isinstance(valor, datetime.datetime):
        return valor
    if isinstance(valor, datetime.date):
        return datetime.datetime(valor.year, valor.month, valor.day)
    if isinstance(valor, str) and valor:
        try:
            return datetime.datetime.fromisoformat(valor)
        except ValueError:
            return leer_fecha(valor)
    return None


def _ahora(hoy):
    if hoy is None:
        return datetime.datetime.now()
    return _a_fecha(hoy)


def _fecha_de_plantilla(texto, hoy, que):
    """«{dias:-7}», «01/10/2026», «2026-10-01», «{inicio_mes}» → date."""
    t = (texto or "").strip()
    if not t:
        return None
    try:
        valor = plantillas.renderizar(t, hoy=_ahora(hoy))
    except plantillas.ErrorPlantilla as e:
        raise ErrorCorreo("La fecha «%s» (%s) no es válida: %s" % (t, que, e))
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(valor.strip(), formato).date()
        except ValueError:
            continue
    raise ErrorCorreo("No entiendo la fecha «%s» (%s): escribe por ejemplo 01/10/2026 o {dias:-7}" % (t, que))


def rango_fechas(criterios, hoy=None):
    """(desde, hasta) como fechas (date, ambas incluidas) o None si no hay límite."""
    c = criterios
    dia = _ahora(hoy).date()
    modo = c.get("fecha") or "cualquiera"
    if modo == "hoy":
        return dia, dia
    if modo == "ayer":
        ayer = dia - datetime.timedelta(days=1)
        return ayer, ayer
    if modo == "ultimos":
        n = max(1, int(c.get("dias") or 7))
        return dia - datetime.timedelta(days=n), dia
    if modo == "rango":
        return _fecha_de_plantilla(c.get("desde"), hoy, "desde"), _fecha_de_plantilla(c.get("hasta"), hoy, "hasta")
    return None, None


# ============================================================================== criterios («¿Qué correo?»)
CRITERIOS_DEFECTO = {"asunto": "", "remitente": "", "remitente_exacto": False, "fecha": "ultimos", "dias": 7,
                     "desde": "", "hasta": "", "cuerpo": [], "con_adjunto": False, "adjunto": "", "extension": "",
                     "carpeta": "", "buscar": "",
                     # v3.6.1: «Procesar también los que ya se procesaron» (cada revisión rehace sus acciones)
                     "reprocesar": False}


def _extensiones(texto):
    partes = re.split(r"[\s,;]+", str(texto or "").lower())
    return [p.lstrip("*").lstrip(".") for p in partes if p.lstrip("*").lstrip(".")]


def normalizar_criterios(datos, hoy=None, exigir=True):
    """Forma canónica de los criterios (lanza ErrorCorreo con un mensaje para una persona)."""
    d = dict(CRITERIOS_DEFECTO)
    for k, v in (datos or {}).items():
        if k in d:
            d[k] = v
    for k in ("asunto", "remitente", "desde", "hasta", "adjunto", "carpeta", "buscar"):
        d[k] = re.sub(r"\s+", " ", str(d[k] or "")).strip()
    d["remitente_exacto"] = bool(d["remitente_exacto"])
    d["con_adjunto"] = bool(d["con_adjunto"])
    d["reprocesar"] = bool(d["reprocesar"])
    cuerpo = d["cuerpo"]
    if isinstance(cuerpo, str):
        cuerpo = cuerpo.splitlines()
    d["cuerpo"] = [re.sub(r"\s+", " ", str(x)).strip() for x in (cuerpo or []) if str(x or "").strip()]
    d["extension"] = ", ".join(_extensiones(d["extension"]))
    if d["fecha"] not in MODOS_FECHA:
        raise ErrorCorreo("Fecha no válida: %s" % d["fecha"])
    try:
        d["dias"] = int(d["dias"] or 7)
    except (TypeError, ValueError):
        raise ErrorCorreo("«Últimos días» tiene que ser un número")
    if not 1 <= d["dias"] <= 3650:
        raise ErrorCorreo("«Últimos días» tiene que estar entre 1 y 3650")
    if d["fecha"] == "rango":
        desde, hasta = rango_fechas(d, hoy)
        if desde is None and hasta is None:
            raise ErrorCorreo("Escribe al menos una de las dos fechas (desde / hasta)")
        if desde and hasta and hasta < desde:
            raise ErrorCorreo("La fecha «hasta» es anterior a «desde»")
    if exigir and not (d["asunto"] or d["remitente"] or d["cuerpo"] or d["adjunto"] or d["extension"]):
        raise ErrorCorreo("Pon al menos el asunto, el remitente, un trozo del cuerpo o el nombre del adjunto: si no, el "
                          "bot procesaría todos los correos del buzón.")
    return d


def describir_criterios(c, hoy=None):
    """«asunto con «RESUMEN DE VENTAS» · de reportes@ejemplo.com · de los últimos 7 días · con el adjunto «…»»."""
    partes = []
    if c.get("asunto"):
        partes.append("asunto con «%s»" % c["asunto"])
    if c.get("remitente"):
        partes.append(("de %s" if c.get("remitente_exacto") else "remitente con «%s»") % c["remitente"])
    modo = c.get("fecha") or "cualquiera"
    if modo == "ultimos":
        partes.append("de los últimos %d días" % int(c.get("dias") or 7))
    elif modo == "rango":
        if c.get("desde") and c.get("hasta"):
            partes.append("del %s al %s" % (c["desde"], c["hasta"]))
        elif c.get("desde"):
            partes.append("desde el %s" % c["desde"])
        else:
            partes.append("hasta el %s" % c.get("hasta"))
    elif modo in ("hoy", "ayer"):
        partes.append(MODOS_FECHA[modo])
    for f in c.get("cuerpo") or []:
        partes.append("el cuerpo dice «%s»" % f)
    if c.get("adjunto"):
        partes.append("con el adjunto «%s»" % c["adjunto"])
    if c.get("extension"):
        partes.append("adjuntos .%s" % ", .".join(_extensiones(c["extension"])))
    elif c.get("con_adjunto") and not c.get("adjunto"):
        partes.append("con algún adjunto")
    if c.get("reprocesar"):
        partes.append("también los ya procesados")
    return " · ".join(partes) or "todos los correos"


def adjunto_coincide(nombre, fragmento="", extension=""):
    """¿El adjunto `nombre` coincide con el trozo del nombre (sin mayúsculas, acentos ni puntuación) y la extensión?"""
    base, ext = os.path.splitext(str(nombre or ""))
    if fragmento and not contiene(base, fragmento) and not contiene(nombre, fragmento):
        return False
    exts = _extensiones(extension)
    if exts and ext.lower().lstrip(".") not in exts:
        return False
    return True


def coincide(m, c, hoy=None, fase="detalle"):
    """¿El correo `m` cumple los criterios `c`?  Devuelve (sí/no, motivo).

    `fase="resumen"`: con lo que se ve en la lista de resultados (lo que no se sabe todavía —el cuerpo, los adjuntos, a
    veces el asunto exacto— no descarta); `fase="detalle"`: con el correo abierto (todo cuenta)."""
    resumen = fase == "resumen"
    texto_fila = m.get("texto") or ""
    asunto = m.get("asunto") or ""
    if c.get("asunto"):
        donde = asunto if (asunto or not resumen) else texto_fila
        if not contiene(donde, c["asunto"]) and not (resumen and contiene(texto_fila, c["asunto"])):
            return False, "el asunto no contiene «%s»" % c["asunto"]
    if c.get("remitente"):
        quien = " ".join(x for x in (m.get("remitente") or "", m.get("remitente_correo") or "") if x)
        if c.get("remitente_exacto"):
            buscado = c["remitente"].strip().lower()
            dire = (m.get("remitente_correo") or correo_de(m.get("remitente"))).lower()
            if "@" in buscado:
                # (en la lista a veces no se ve la dirección: no descarta; se comprueba con el correo abierto)
                ok = dire == buscado if dire else resumen
            else:
                ok = normalizar(nombre_de(m.get("remitente"))) == normalizar(buscado) or (
                    resumen and not quien and contiene(texto_fila, buscado))
            if not ok:
                return False, "no lo envía «%s»" % c["remitente"]
        elif not contiene(quien, c["remitente"]) and not (resumen and contiene(texto_fila, c["remitente"])) and not (
                # v3.6.1: una dirección que no se ve en la lista (Outlook) no descarta: se comprueba al abrirlo
                resumen and "@" in c["remitente"] and not m.get("remitente_correo")):
            return False, "el remitente no contiene «%s»" % c["remitente"]
    desde, hasta = rango_fechas(c, hoy)
    fecha = _a_fecha(m.get("fecha"))
    if desde or hasta:
        if fecha is None:
            if not resumen:
                return False, "no se pudo leer la fecha del correo"
        else:
            if desde and fecha.date() < desde:
                return False, "es del %s (antes del %s)" % (fecha.strftime("%d/%m/%Y"), desde.strftime("%d/%m/%Y"))
            if hasta and fecha.date() > hasta:
                return False, "es del %s (después del %s)" % (fecha.strftime("%d/%m/%Y"), hasta.strftime("%d/%m/%Y"))
    adjuntos = m.get("adjuntos")
    nombres = None if adjuntos is None else [a["nombre"] if isinstance(a, dict) else str(a) for a in adjuntos]
    necesita = c.get("con_adjunto") or c.get("adjunto") or c.get("extension")
    if necesita:
        if nombres is None:
            if m.get("tiene_adjuntos") is False:
                return False, "no tiene adjuntos"
            if not resumen:
                return False, "no tiene adjuntos"
        elif not nombres:
            return False, "no tiene adjuntos"
        elif (c.get("adjunto") or c.get("extension")) and not any(
                adjunto_coincide(n, c.get("adjunto"), c.get("extension")) for n in nombres):
            return False, "ningún adjunto coincide (tiene: %s)" % ", ".join(nombres)[:200]
    if c.get("cuerpo") and not resumen:
        cuerpo = m.get("cuerpo_texto")
        if cuerpo is None:
            cuerpo = m.get("texto_cuerpo") or html_a_texto(m.get("html") or "")
        for f in c["cuerpo"]:
            if not contiene(cuerpo, f):
                return False, "el cuerpo no dice «%s»" % f
    return True, ""


def clave_mensaje(m):
    """Identificador estable del correo para no procesarlo dos veces: el del proveedor (y la fecha, porque en Outlook
    y Gmail el identificador de la fila es el de la CONVERSACIÓN) o, si no hay, una huella de remitente + asunto +
    fecha.  Se calcula siempre con el RESUMEN (lo de la lista), no con el correo abierto."""
    fecha = _a_fecha(m.get("fecha"))
    f = fecha.strftime("%Y-%m-%dT%H:%M") if fecha else ""
    if m.get("id"):
        return "%s|%s" % (m["id"], f) if f else str(m["id"])
    base = "%s|%s|%s" % (normalizar(m.get("remitente_correo") or m.get("remitente")),
                         normalizar(m.get("asunto") or m.get("texto")), f)
    return "h:" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def ordenar(mensajes):
    """Del más reciente al más antiguo (los que no tienen fecha, al final, en el orden de la lista)."""
    con = [m for m in mensajes if _a_fecha(m.get("fecha"))]
    sin = [m for m in mensajes if not _a_fecha(m.get("fecha"))]
    return sorted(con, key=lambda m: _a_fecha(m.get("fecha")), reverse=True) + sin


# ------------------------------------------------------------------------------ consultas de cada proveedor
def texto_a_teclear(c):
    """Lo que se pone en el buscador de Outlook: el `buscar` elegido o, si no, el asunto ENTERO (v3.6: antes solo las 4
    primeras palabras, como Octopus), el remitente, el primer trozo del cuerpo o el nombre del adjunto.  La comprobación
    seria se hace después sobre cada resultado.  Si con el texto entero no sale nada que valga, `textos_a_buscar` da
    una versión más corta para un segundo intento."""
    if c.get("buscar"):
        return str(c["buscar"]).strip()
    if c.get("asunto"):
        return " ".join(str(c["asunto"]).split())
    if c.get("remitente"):
        return str(c["remitente"]).strip()
    if c.get("cuerpo"):
        return " ".join(str(c["cuerpo"][0]).split())
    return str(c.get("adjunto") or "").strip()


PALABRAS_BUSQUEDA_CORTA = 4


def texto_corto(texto):
    """La versión corta de un texto de búsqueda (para el segundo intento): hasta la primera coma si quedan al menos 2
    palabras («RESUMEN DE VENTAS MI EMPRESA, S.A.S.» → «RESUMEN DE VENTAS MI EMPRESA»); si no,
    las 4 primeras palabras sin signos (lo que hacía Octopus).  "" si no hay nada más corto."""
    texto = " ".join(str(texto or "").split())
    antes = texto.split(",", 1)[0].strip()
    if antes != texto and len(antes.split()) >= 2:
        return antes
    corto = " ".join(re.sub(r"[^\w\s@.-]+", " ", texto).split()[:PALABRAS_BUSQUEDA_CORTA])
    return corto if corto and corto != texto else ""


def textos_a_buscar(c):
    """[(texto, «completo» | «más corto»)]: primero el texto entero; si da otro más corto, también (como mucho dos)."""
    texto = texto_a_teclear(c)
    if not texto:
        return []
    res = [(texto, "completo")]
    corto = texto_corto(texto)
    if corto:
        res.append((corto, "más corto"))
    return res


def _gmail_valor(v):
    v = re.sub(r"[()\"]+", " ", str(v or "")).strip()
    return "(%s)" % v if " " in v else v


def consulta_gmail(c, hoy=None):
    """Operadores de búsqueda de Gmail: subject:(…) from:(…) after:AAAA/MM/DD before:AAAA/MM/DD has:attachment
    filename:… "trozo del cuerpo".  (Gmail entiende las fechas como días enteros; `before` no incluye ese día.)"""
    partes = []
    if c.get("buscar"):
        partes.append(c["buscar"])
    if c.get("asunto"):
        partes.append("subject:" + _gmail_valor(c["asunto"]))
    if c.get("remitente"):
        partes.append("from:" + _gmail_valor(c["remitente"]))
    desde, hasta = rango_fechas(c, hoy)
    if desde:
        partes.append("after:" + desde.strftime("%Y/%m/%d"))
    if hasta:
        partes.append("before:" + (hasta + datetime.timedelta(days=1)).strftime("%Y/%m/%d"))
    if c.get("con_adjunto") or c.get("adjunto") or c.get("extension"):
        partes.append("has:attachment")
    if c.get("adjunto"):
        partes.append("filename:" + _gmail_valor(c["adjunto"]))
    exts = _extensiones(c.get("extension"))
    if len(exts) == 1:
        partes.append("filename:" + exts[0])
    elif exts:
        partes.append("{%s}" % " ".join("filename:" + e for e in exts))
    for f in c.get("cuerpo") or []:
        partes.append('"%s"' % f.replace('"', " ").strip())
    return " ".join(partes)


def criterios_imap(c, hoy=None):
    """Criterios de IMAP SEARCH (lo que el servidor puede filtrar; el resto se comprueba aquí después).  Los textos
    con letras fuera de ASCII no se mandan al servidor (no todos admiten CHARSET UTF-8): se filtran aquí."""
    res = []
    desde, hasta = rango_fechas(c, hoy)
    fmt = lambda d: "%02d-%s-%04d" % (d.day, ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",  # noqa: E731
                                              "Nov", "Dec")[d.month - 1], d.year)
    if desde:
        res += ["SINCE", fmt(desde)]
    if hasta:
        res += ["BEFORE", fmt(hasta + datetime.timedelta(days=1))]

    def ascii_ok(t):
        return t and all(ord(ch) < 128 for ch in t) and '"' not in t and "\\" not in t
    if ascii_ok(c.get("remitente")):
        res += ["FROM", '"%s"' % c["remitente"]]
    # el primer trozo del asunto sin puntuación, hasta 4 palabras (es un trozo SEGUIDO del asunto real: IMAP busca
    # subcadenas, y «VENTAS S.A.S.» no está en «VENTAS, S.A.S.»)
    trozo = next((t.strip() for t in re.split(r"[^\w ]+", c.get("asunto") or "") if t.strip()), "")
    texto = " ".join(trozo.split()[:4])
    if ascii_ok(texto):
        res += ["SUBJECT", '"%s"' % texto]
    return res or ["ALL"]


# ============================================================================== acciones («¿Qué hago con él?»)
ACCION_DEFECTO = {
    "adjuntos": {"coincide": "", "extension": "", "descomprimir": False, "carpeta": "", "nombre": ""},
    "texto": {"campo": "", "modo": "despues", "etiqueta": "", "hasta": "", "regex": "", "archivo": ""},
    "tabla": {"n": 1, "archivo": "", "modo": "agregar", "hoja": "", "con_encabezado": True},
    "cuerpo": {"formato": "html", "carpeta": "", "nombre": ""},
}


def _validar_plantilla(texto, que, nombre):
    if not texto:
        return
    err = plantillas.validar(texto)
    if err:
        raise ErrorCorreo("%s: %s no es válido: %s" % (nombre, que, err))
    try:
        renderizar(texto, contexto_prueba(), hoy=None, archivo=False)
    except ErrorCorreo as e:
        raise ErrorCorreo("%s: %s: %s" % (nombre, que, e))


def normalizar_accion(a, i=1):
    if not isinstance(a, dict):
        raise ErrorCorreo("Acción %d: no es válida" % i)
    tipo = a.get("tipo") or "adjuntos"
    if tipo not in TIPOS_ACCION:
        raise ErrorCorreo("Acción %d: tipo desconocido «%s»" % (i, tipo))
    d = dict(ACCION_DEFECTO[tipo])
    for k, v in a.items():
        if k in d:
            d[k] = v
    d["tipo"] = tipo
    nombre = "Acción %d («%s»)" % (i, TIPOS_ACCION[tipo])
    for k, v in list(d.items()):
        if isinstance(ACCION_DEFECTO[tipo].get(k), bool):
            d[k] = bool(v)
        elif isinstance(ACCION_DEFECTO[tipo].get(k), str):
            d[k] = str(v or "").strip() if k not in ("regex",) else str(v or "")
    if tipo == "adjuntos":
        d["extension"] = ", ".join(_extensiones(d["extension"]))
        _validar_plantilla(d["carpeta"], "la carpeta", nombre)
        _validar_plantilla(d["nombre"], "el nombre del archivo", nombre)
    elif tipo == "texto":
        if d["modo"] not in MODOS_TEXTO:
            raise ErrorCorreo("%s: forma desconocida «%s»" % (nombre, d["modo"]))
        if d["modo"] in ("despues", "entre") and not d["etiqueta"]:
            raise ErrorCorreo("%s: escribe el texto que va justo antes del dato (p. ej. «Total ventas:»)" % nombre)
        if d["modo"] == "regex":
            if not d["regex"].strip():
                raise ErrorCorreo("%s: escribe la expresión regular" % nombre)
            try:
                re.compile(d["regex"])
            except re.error as e:
                raise ErrorCorreo("%s: la expresión regular no es válida: %s" % (nombre, e))
        if not d["campo"]:
            d["campo"] = (d["etiqueta"].rstrip(":=- ").strip() or "Texto") if d["modo"] != "regex" else "Texto"
        _validar_plantilla(d["archivo"], "el archivo", nombre)
        ext = os.path.splitext(d["archivo"])[1].lower()
        if d["archivo"] and ext not in (".csv", ".xlsx", ".xlsm", ".txt"):
            raise ErrorCorreo("%s: el archivo donde se anota tiene que ser .xlsx, .csv o .txt" % nombre)
        if ext in (".xlsx", ".xlsm") and not HAY_OPENPYXL:
            raise ErrorCorreo("%s: no está instalado «openpyxl» para escribir Excel: usa un archivo .csv" % nombre)
    elif tipo == "tabla":
        try:
            d["n"] = max(1, int(d["n"] or 1))
        except (TypeError, ValueError):
            raise ErrorCorreo("%s: el número de la tabla tiene que ser 1, 2, 3…" % nombre)
        if d["modo"] not in MODOS_TABLA:
            raise ErrorCorreo("%s: forma de copiar desconocida «%s»" % (nombre, d["modo"]))
        if not d["archivo"]:
            raise ErrorCorreo("%s: escribe el archivo Excel o CSV donde se copia la tabla" % nombre)
        _validar_plantilla(d["archivo"], "el archivo", nombre)
        _validar_plantilla(d["hoja"], "la hoja", nombre)
        ext = os.path.splitext(d["archivo"])[1].lower()
        if ext not in (".xlsx", ".xlsm", ".csv"):
            raise ErrorCorreo("%s: el archivo tiene que ser .xlsx o .csv" % nombre)
        if ext in (".xlsx", ".xlsm") and not HAY_OPENPYXL:
            raise ErrorCorreo("%s: no está instalado «openpyxl» para escribir Excel: usa un archivo .csv" % nombre)
        if ext == ".csv" and d["modo"] == "hoja_mes":
            raise ErrorCorreo("%s: «una hoja por mes» solo vale con Excel (.xlsx); con CSV pon {fecha_correo:%%Y-%%m} en el "
                              "nombre del archivo" % nombre)
    elif tipo == "cuerpo":
        if d["formato"] not in ("html", "txt"):
            raise ErrorCorreo("%s: formato desconocido «%s» (html o txt)" % (nombre, d["formato"]))
        _validar_plantilla(d["carpeta"], "la carpeta", nombre)
        _validar_plantilla(d["nombre"], "el nombre del archivo", nombre)
    return d


def normalizar_acciones(lista):
    acciones = [normalizar_accion(a, i) for i, a in enumerate(lista or [], start=1)]
    return acciones


def describir_accion(a):
    t = a["tipo"]
    if t == "adjuntos":
        cuales = "los adjuntos" + ((" con «%s»" % a["coincide"]) if a["coincide"] else "") + (
            (" .%s" % ", .".join(_extensiones(a["extension"]))) if a["extension"] else "")
        return "Descargar %s%s%s%s" % (cuales, (" en «%s»" % a["carpeta"]) if a["carpeta"] else "",
                                       (" como «%s»" % a["nombre"]) if a["nombre"] else "",
                                       " (descomprimir .zip)" if a["descomprimir"] else "")
    if t == "texto":
        if a["modo"] == "regex":
            como = "con la expresión «%s»" % a["regex"]
        elif a["modo"] == "entre":
            como = "entre «%s» y «%s»" % (a["etiqueta"], a["hasta"] or "el final de la línea")
        else:
            como = "después de «%s»" % a["etiqueta"]
        return "Copiar «%s» (%s)%s" % (a["campo"], como, (" y anotarlo en «%s»" % a["archivo"]) if a["archivo"] else "")
    if t == "tabla":
        return "Copiar la tabla %d del cuerpo a «%s» (%s)" % (a["n"], a["archivo"], MODOS_TABLA[a["modo"]])
    return "Guardar el cuerpo como .%s%s" % (a["formato"], (" en «%s»" % a["carpeta"]) if a["carpeta"] else "")


# ============================================================================== búsqueda completa
def normalizar_busqueda(datos, hoy=None):
    """{nombre, cuenta_id, activa, criterios, acciones, max_por_vez, programacion} comprobada."""
    from . import horario
    d = dict(datos or {})
    nombre = re.sub(r"\s+", " ", str(d.get("nombre") or "")).strip()
    if not nombre:
        raise ErrorCorreo("Escribe un nombre para la búsqueda (p. ej. «Ventas diarias»)")
    if len(nombre) > 80 or '"' in nombre:
        raise ErrorCorreo("El nombre no puede pasar de 80 caracteres ni llevar comillas dobles")
    try:
        cuenta_id = int(d.get("cuenta_id"))
    except (TypeError, ValueError):
        raise ErrorCorreo("Elige la cuenta de correo")
    acciones = normalizar_acciones(d.get("acciones"))
    if not acciones:
        raise ErrorCorreo("Añade al menos una acción en «¿Qué hago con él?» (p. ej. descargar los adjuntos)")
    try:
        maximo = int(d.get("max_por_vez") or MAX_POR_VEZ)
    except (TypeError, ValueError):
        raise ErrorCorreo("«Como mucho, correos por revisión» tiene que ser un número")
    if not 1 <= maximo <= MAX_POR_VEZ_TOPE:
        raise ErrorCorreo("«Como mucho, correos por revisión» tiene que estar entre 1 y %d" % MAX_POR_VEZ_TOPE)
    try:
        prog = horario.normalizar(d.get("programacion"))
    except horario.ErrorHorario as e:
        raise ErrorCorreo(str(e))
    return {"nombre": nombre, "cuenta_id": cuenta_id, "activa": d.get("activa") is not False,
            "criterios": normalizar_criterios(d.get("criterios"), hoy), "acciones": acciones, "max_por_vez": maximo,
            "programacion": prog}


def normalizar_cuenta(datos):
    d = dict(datos or {})
    nombre = re.sub(r"\s+", " ", str(d.get("nombre") or "")).strip()
    proveedor = d.get("proveedor") or "outlook_web"
    if proveedor not in PROVEEDORES:
        raise ErrorCorreo("Tipo de cuenta desconocido: %s" % proveedor)
    direccion = str(d.get("direccion") or "").strip()
    if not nombre:
        nombre = direccion or PROVEEDORES[proveedor].split(" (")[0]
    if len(nombre) > 80 or '"' in nombre:
        raise ErrorCorreo("El nombre no puede pasar de 80 caracteres ni llevar comillas dobles")
    res = {"nombre": nombre, "proveedor": proveedor, "direccion": direccion, "url": str(d.get("url") or "").strip(),
           "host": str(d.get("host") or "").strip(), "puerto": None, "usuario": str(d.get("usuario") or "").strip(),
           "ssl": d.get("ssl") is not False, "carpeta": str(d.get("carpeta") or "").strip()}
    if res["url"] and not re.match(r"^https?://", res["url"], re.I):
        raise ErrorCorreo("La dirección web del correo tiene que empezar por https://")
    if proveedor == "imap":
        if not res["host"]:
            raise ErrorCorreo("Escribe el servidor IMAP (p. ej. imap.gmail.com u outlook.office365.com)")
        if not res["usuario"]:
            res["usuario"] = direccion
        if not res["usuario"]:
            raise ErrorCorreo("Escribe el usuario (normalmente tu dirección de correo)")
        try:
            res["puerto"] = int(d.get("puerto") or (993 if res["ssl"] else 143))
        except (TypeError, ValueError):
            raise ErrorCorreo("El puerto tiene que ser un número (normalmente 993)")
        res["carpeta"] = res["carpeta"] or "INBOX"
    return res


def url_de_cuenta(cuenta):
    if cuenta.get("url"):
        return cuenta["url"]
    return URL_GMAIL if cuenta.get("proveedor") == "gmail_web" else URL_OUTLOOK


def secreto_de_cuenta(cuenta_id):
    """Nombre con el que se guarda la contraseña IMAP en el Administrador de credenciales (nunca en la base de datos)."""
    return "correo_imap:%d" % int(cuenta_id)


# ============================================================================== nombres de archivo y carpetas
def contexto_prueba():
    return {"fecha_correo": datetime.datetime(2026, 1, 31, 9, 0), "asunto": "Asunto", "remitente": "Remitente",
            "adjunto": "archivo", "ext": ".xlsx", "n": 1, "reporte": "Búsqueda"}


def _limpio(valor):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(valor or "")).strip(" .")


def nombre_sin_prohibidos(valor):
    """(v3.5) Como `_limpio` pero sin quitar los puntos ni espacios de los extremos: «Ventas S.A.S.» sigue entero."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(valor or ""))


def renderizar(plantilla, ctx, hoy=None, archivo=True):
    """Plantillas de siempre ({hoy}, {dias:-7}, {fecha}…) más las del correo: {fecha_correo[:formato]}, {asunto},
    {remitente}, {adjunto} (= {nombre}), {ext}, {n}.  Con `archivo=True`, lo que sale de un correo (asunto, remitente…)
    se limpia de caracteres que Windows no admite en un nombre."""
    if plantilla is None:
        return ""
    ahora = _ahora(hoy)
    limpiar = _limpio if archivo else (lambda v: str(v or ""))
    partes = []
    try:
        fichas = plantillas._tokens(str(plantilla))
    except plantillas.ErrorPlantilla as e:
        raise ErrorCorreo(str(e))
    for clase, cont in fichas:
        if clase == "lit":
            partes.append(cont)
            continue
        nombre, _sep, resto = cont.partition(":")
        nombre = nombre.strip()
        if nombre == "fecha_correo":
            f = _a_fecha(ctx.get("fecha_correo")) or ahora
            try:
                partes.append(limpiar(f.strftime(resto or "%Y-%m-%d")))
            except ValueError as e:
                raise ErrorCorreo("Formato de fecha no válido «%s»: %s" % (resto, e))
        elif nombre in ("asunto", "remitente"):
            partes.append(limpiar(ctx.get(nombre) or ""))
        elif nombre in ("adjunto", "nombre"):
            partes.append(limpiar(ctx.get("adjunto") or ""))
        elif nombre == "reporte" and not resto:          # v3.5: el nombre COMPLETO de la búsqueda (con su punto final)
            v = str(ctx.get("reporte") or "")
            partes.append(nombre_sin_prohibidos(v) if archivo else v)
        elif nombre == "ext":
            partes.append(ctx.get("ext") or "")
        elif nombre == "n":
            partes.append(str(ctx.get("n") or 1))
        else:
            try:
                partes.append(plantillas.renderizar("{%s}" % cont, hoy=ahora))
            except plantillas.ErrorPlantilla as e:
                raise ErrorCorreo(str(e).replace("Defínela en el flujo o con --var %s=valor" % nombre,
                                                 "En el correo puedes usar {fecha_correo:%Y-%m-%d}, {asunto}, "
                                                 "{remitente}, {adjunto}, {ext}, {n} y las fechas de siempre"))
    return "".join(partes)


def nombre_final(plantilla, ctx, hoy=None):
    """El nombre del archivo: la plantilla (o el nombre original) y, si no lleva extensión, la del adjunto."""
    from .ejecutor import nombre_archivo_seguro
    original = (ctx.get("adjunto") or "archivo") + (ctx.get("ext") or "")
    if not (plantilla or "").strip():
        return nombre_archivo_seguro(original)
    nombre = renderizar(plantilla, ctx, hoy).strip()
    ext = ctx.get("ext") or ""
    if "{ext" not in plantilla and ext:
        propia = os.path.splitext(nombre)[1].lower().lstrip(".")
        if not (propia == ext.lower().lstrip(".") or propia in EXTENSIONES_CONOCIDAS):
            nombre += ext
    return nombre_archivo_seguro(nombre or original)


def resolver_carpeta(texto, base, ctx=None, hoy=None):
    """La carpeta de destino: vacía = `base` (la carpeta de descargas del bot); relativa = dentro de `base`; admite
    plantillas («Correo\\{fecha_correo:%Y-%m}»), %USERPROFILE% y «~»."""
    t = (texto or "").strip()
    if not t:
        return os.path.abspath(base)
    t = renderizar(t, ctx or {}, hoy, archivo=False)
    t = os.path.expanduser(os.path.expandvars(t))
    if not os.path.isabs(t):
        t = os.path.join(base, t)
    return os.path.abspath(t)


def resolver_archivo(texto, base, ctx=None, hoy=None):
    t = renderizar(texto, ctx or {}, hoy, archivo=False).strip()
    t = os.path.expanduser(os.path.expandvars(t))
    if not os.path.isabs(t):
        t = os.path.join(base, t)
    return os.path.abspath(t)


def _ruta_libre(ruta):
    from .ejecutor import ruta_libre
    return ruta_libre(ruta)


# ------------------------------------------------------------------------------ .zip (de Octopus)
def es_zip_valido(ruta):
    try:
        with open(ruta, "rb") as f:
            return f.read(4) == b"PK\x03\x04"
    except OSError:
        return False


def es_tmp_guid(nombre):
    """¿Es un «GUID.tmp» de Edge/Chrome (una descarga nativa sin renombrar)?"""
    bajo = str(nombre or "").lower()
    if not bajo.endswith(".tmp"):
        return False
    stem = bajo[:-4]
    return len(stem) == 36 and stem.count("-") == 4


def es_descarga_a_medias(nombre):
    return str(nombre or "").lower().endswith((".crdownload", ".partial"))


def extraer_zip(ruta_zip, carpeta):
    """Extrae los archivos del .zip en `carpeta` (sin sus subcarpetas, sin __MACOSX ni .DS_Store y sin salirse de la
    carpeta).  Devuelve las rutas extraídas."""
    extraidos = []
    os.makedirs(carpeta, exist_ok=True)
    with zipfile.ZipFile(ruta_zip) as z:
        for m in z.infolist():
            nombre = m.filename.replace("\\", "/")
            if nombre.endswith("/") or nombre.startswith("__MACOSX") or os.path.basename(nombre) in (".DS_Store", ""):
                continue
            destino = _ruta_libre(os.path.join(carpeta, os.path.basename(nombre)))
            with z.open(m) as fuente, open(destino, "wb") as salida:
                shutil.copyfileobj(fuente, salida)
            extraidos.append(destino)
    return extraidos


# ------------------------------------------------------------------------------ escribir: CSV / Excel / txt
def _reintentar(hacer, ruta, veces=3, espera=2.0):
    for intento in range(veces):
        try:
            return hacer()
        except PermissionError as e:
            if intento == veces - 1:
                raise ErrorCorreo("«%s» está abierto o bloqueado (¿Excel, OneDrive?): ciérralo y vuelve a intentarlo"
                                  % os.path.basename(ruta)) from e
            time.sleep(espera)
    return None


def _nombre_hoja(nombre):
    return re.sub(r"[\[\]:*?/\\]", "-", nombre).strip("' ")[:31] or "Hoja"


MESES_NOMBRE = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
                "NOVIEMBRE", "DICIEMBRE"]


def anotar_fila(ruta, columnas, fila):
    """Añade una fila a un .csv (separado por «;», como lo abre Excel en español), un .xlsx (primera hoja) o un .txt
    (una línea); si el archivo es nuevo, con la fila de títulos."""
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    ext = os.path.splitext(ruta)[1].lower()
    if ext == ".txt":
        linea = " | ".join("%s" % v for v in fila) + "\n"

        def escribir():
            with open(ruta, "a", encoding="utf-8") as f:
                f.write(linea)
        _reintentar(escribir, ruta)
        return ruta
    if ext == ".csv":
        nuevo = not os.path.exists(ruta) or os.path.getsize(ruta) == 0

        def escribir():
            with open(ruta, "a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as f:
                w = csv.writer(f, delimiter=";")
                if nuevo:
                    w.writerow(columnas)
                w.writerow(fila)
        _reintentar(escribir, ruta)
        return ruta
    from openpyxl import Workbook, load_workbook
    nuevo = not os.path.exists(ruta)
    libro = Workbook() if nuevo else load_workbook(ruta, keep_vba=ext == ".xlsm")
    hoja = libro.worksheets[0]
    if nuevo:
        hoja.title = "Datos"
        hoja.append(list(columnas))
    hoja.append(list(fila))
    _guardar_libro(libro, ruta)
    return ruta


def _guardar_libro(libro, ruta):
    """(De Octopus) se guarda en un temporal y se reemplaza: si el Excel está abierto, el archivo de la persona queda
    intacto, nunca a medias."""
    temporal = os.path.join(os.path.dirname(ruta) or ".", "~botweb-%d-%s" % (os.getpid(), os.path.basename(ruta)))
    libro.save(temporal)
    try:
        _reintentar(lambda: os.replace(temporal, ruta), ruta)
    finally:
        if os.path.exists(temporal):
            try:
                os.remove(temporal)
            except OSError:
                pass


def pegar_tabla(filas, ruta, modo="agregar", hoja="", con_encabezado=True, fecha=None):
    """(De Octopus) pega las filas en un Excel (agregar al final, reemplazar la hoja o una hoja por mes) o en un CSV
    (agregar o reemplazar).  Al agregar a un archivo con datos, se salta la fila de títulos (`con_encabezado`).
    Devuelve qué hizo, en palabras."""
    if not filas:
        raise ErrorCorreo("la tabla no tiene filas")
    fecha = _a_fecha(fecha) or datetime.datetime.now()
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    ext = os.path.splitext(ruta)[1].lower()
    if ext == ".csv":
        existe = os.path.exists(ruta) and os.path.getsize(ruta) > 0
        agregar = modo == "agregar" and existe
        desde = 1 if agregar and con_encabezado else 0

        def escribir():
            with open(ruta, "a" if agregar else "w", encoding="utf-8" if agregar else "utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";")
                for fila in filas[desde:]:
                    w.writerow(fila)
        _reintentar(escribir, ruta)
        return "%d fila(s) → %s" % (len(filas) - desde, os.path.basename(ruta))
    from openpyxl import Workbook, load_workbook
    nuevo = not os.path.exists(ruta)
    libro = Workbook() if nuevo else load_workbook(ruta, keep_vba=ext == ".xlsm")
    nombre = hoja or ("%s %d" % (MESES_NOMBRE[fecha.month - 1], fecha.year) if modo == "hoja_mes" else "")
    nombre = _nombre_hoja(nombre) if nombre else ""
    if nombre:
        if nombre in libro.sheetnames:
            h = libro[nombre]
        elif nuevo and libro.sheetnames == ["Sheet"]:
            h = libro.active
            h.title = nombre
        else:
            h = libro.create_sheet(nombre)
    else:
        h = libro.worksheets[0]
    if modo in ("reemplazar", "hoja_mes"):
        titulo, pos = h.title, libro.sheetnames.index(h.title)
        libro.remove(h)
        h = libro.create_sheet(titulo, pos)
    tiene_datos = any(c.value not in (None, "") for c in h._cells.values())
    desde = 1 if modo == "agregar" and con_encabezado and tiene_datos else 0
    for fila in filas[desde:]:
        h.append(list(fila))
    _guardar_libro(libro, ruta)
    return "%d fila(s) → %s [%s]" % (len(filas) - desde, os.path.basename(ruta), h.title)


# ============================================================================== aplicar las acciones a un correo
def contexto_de(m):
    return {"fecha_correo": _a_fecha(m.get("fecha")), "asunto": m.get("asunto") or "",
            "remitente": nombre_de(m.get("remitente")) or m.get("remitente_correo") or ""}


def texto_del_cuerpo(detalle):
    if detalle.get("texto"):
        return detalle["texto"]
    return html_a_texto(detalle.get("html") or "")


def aplicar_acciones(acciones, m, detalle, descargar, base, hoy=None, log=None, hechas=(), reporte=""):
    """Hace las acciones con un correo abierto.  `descargar(nombres, carpeta)` → {nombre: ruta} lo pone el proveedor.
    `hechas` = índices de acciones ya hechas en un intento anterior (no se repiten: así «agregar filas» no duplica).
    Devuelve {archivos, valores [(campo, valor)], hechas, errores, detalle (textos para el registro)}."""
    log = log or (lambda _l: None)
    ctx = contexto_de(dict(m, **{k: detalle[k] for k in ("asunto", "remitente", "fecha") if detalle.get(k)}))
    ctx["reporte"] = reporte or ""
    res = {"archivos": [], "valores": [], "hechas": list(hechas), "errores": [], "detalle": []}
    texto = texto_del_cuerpo(detalle)
    bajados = {}
    tmp = None
    n_archivo = 0
    try:
        for i, a in enumerate(acciones):
            if i in res["hechas"]:
                continue
            nombre_accion = "Acción %d (%s)" % (i + 1, describir_accion(a))
            try:
                if a["tipo"] == "adjuntos":
                    adjuntos = [x["nombre"] for x in detalle.get("adjuntos") or []]
                    elegidos = [n for n in adjuntos if adjunto_coincide(n, a["coincide"], a["extension"])
                                or (a["descomprimir"] and n.lower().endswith(".zip"))]
                    if not elegidos:
                        raise ErrorCorreo("el correo no trae ningún adjunto que coincida (trae: %s)"
                                          % (", ".join(adjuntos) or "ninguno"))
                    faltan = [n for n in elegidos if n not in bajados]
                    if faltan:
                        if tmp is None:
                            tmp = tempfile.mkdtemp(prefix="botweb_correo_")
                        bajados.update(descargar(faltan, tmp) or {})
                    no_llegaron = [n for n in elegidos if n not in bajados]
                    if no_llegaron:
                        raise ErrorCorreo("no se pudo descargar: %s" % ", ".join(no_llegaron))
                    for n in elegidos:
                        origen = bajados[n]
                        piezas = [origen]
                        if a["descomprimir"] and n.lower().endswith(".zip") and es_zip_valido(origen):
                            sub = tempfile.mkdtemp(prefix="zip_", dir=tmp)
                            piezas = [p for p in extraer_zip(origen, sub)
                                      if adjunto_coincide(os.path.basename(p), a["coincide"], a["extension"])]
                            log("  %s: se descomprimió «%s» (%d archivo(s) que coinciden)" % (nombre_accion, n, len(piezas)))
                        for p in piezas:
                            n_archivo += 1
                            stem, ext = os.path.splitext(os.path.basename(p))
                            c2 = dict(ctx, adjunto=stem, ext=ext, n=n_archivo)
                            carpeta = resolver_carpeta(a["carpeta"], base, c2, hoy)
                            os.makedirs(carpeta, exist_ok=True)
                            destino = _ruta_libre(os.path.join(carpeta, nombre_final(a["nombre"], c2, hoy)))
                            # (copiar y no mover: la misma descarga puede servir a otra acción del mismo correo)
                            _reintentar(lambda: shutil.copy2(p, destino), destino)
                            res["archivos"].append(destino)
                            res["detalle"].append("guardado %s" % destino)
                            log("  %s: guardado «%s»" % (nombre_accion, destino))
                elif a["tipo"] == "texto":
                    valor = extraer_texto(a, texto)
                    if valor is None:
                        raise ErrorCorreo("no se encontró «%s» en el cuerpo del correo" % (
                            a["etiqueta"] if a["modo"] != "regex" else a["regex"]))
                    res["valores"].append((a["campo"], valor))
                    log("  %s: %s = %s" % (nombre_accion, a["campo"], valor))
                    if a["archivo"]:
                        ruta = resolver_archivo(a["archivo"], base, ctx, hoy)
                        fecha = ctx["fecha_correo"].strftime("%d/%m/%Y %H:%M") if ctx["fecha_correo"] else ""
                        anotar_fila(ruta, COLUMNAS_TEXTO, [fecha, ctx["asunto"], a["campo"], valor])
                        res["detalle"].append("anotado en %s" % ruta)
                        log("  %s: anotado en «%s»" % (nombre_accion, ruta))
                elif a["tipo"] == "tabla":
                    tablas = tablas_html(detalle.get("html") or "")
                    if a["n"] > len(tablas):
                        raise ErrorCorreo("el correo trae %d tabla(s) y la acción pide la %d" % (len(tablas), a["n"]))
                    ruta = resolver_archivo(a["archivo"], base, ctx, hoy)
                    hoja = renderizar(a["hoja"], ctx, hoy, archivo=False) if a["hoja"] else ""
                    hecho = pegar_tabla(tablas[a["n"] - 1], ruta, a["modo"], hoja, a["con_encabezado"],
                                        ctx["fecha_correo"])
                    res["archivos"].append(ruta)
                    res["detalle"].append("tabla: %s" % hecho)
                    log("  %s: %s" % (nombre_accion, hecho))
                else:                                   # cuerpo
                    ext = "." + a["formato"]
                    c2 = dict(ctx, adjunto=_limpio(ctx["asunto"])[:80] or "correo", ext=ext, n=1)
                    carpeta = resolver_carpeta(a["carpeta"], base, c2, hoy)
                    os.makedirs(carpeta, exist_ok=True)
                    plantilla = a["nombre"] or "{fecha_correo:%Y-%m-%d %H%M} {asunto}"
                    destino = _ruta_libre(os.path.join(carpeta, nombre_final(plantilla, c2, hoy)))
                    if a["formato"] == "html":
                        contenido = detalle.get("html") or "<pre>%s</pre>" % mod_html.escape(texto)
                        if "<html" not in contenido[:500].lower():
                            contenido = ('<!doctype html><html><head><meta charset="utf-8"><title>%s</title></head><body>'
                                         '%s</body></html>' % (mod_html.escape(ctx["asunto"]), contenido))
                    else:
                        contenido = texto

                    def escribir(destino=destino, contenido=contenido):
                        with open(destino, "w", encoding="utf-8") as f:
                            f.write(contenido)
                    _reintentar(escribir, destino)
                    res["archivos"].append(destino)
                    res["detalle"].append("cuerpo guardado en %s" % destino)
                    log("  %s: cuerpo guardado en «%s»" % (nombre_accion, destino))
                res["hechas"].append(i)
            except ErrorCorreo as e:
                res["errores"].append("%s: %s" % (nombre_accion, e))
                log("  %s: ERROR: %s" % (nombre_accion, e))
            except Exception as e:             # noqa: BLE001 (una acción rota no para las demás)
                res["errores"].append("%s: %s: %s" % (nombre_accion, type(e).__name__, e))
                log("  %s: ERROR: %s: %s" % (nombre_accion, type(e).__name__, e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return res


# ============================================================================== revisar (procesar los correos)
class ResultadoCorreo:
    def __init__(self, busqueda_id, nombre):
        self.busqueda_id = busqueda_id
        self.nombre = nombre
        self.ok = False
        self.error = ""
        self.sesion_caducada = False
        self.encontrados = 0          # coinciden con la búsqueda (en la lista)
        self.ya_procesados = 0
        self.descartados = 0          # al abrirlos no coincidían (cuerpo, adjunto…)
        self.procesados = []          # [{clave, asunto, remitente, fecha, archivos, valores, errores}]
        self.pendientes = 0           # nuevos que no se procesaron por el máximo por revisión
        self.no_abiertos = []         # correos que no se pudieron abrir (se reintentan en la próxima revisión)
        self.no_encontrados = 0       # v3.5: elegidos a mano que ya no aparecen en la búsqueda
        self.ruta_log = ""
        self.ruta_captura = ""

    @property
    def archivos(self):
        return [a for p in self.procesados for a in p["archivos"]]

    @property
    def con_error(self):
        return [p for p in self.procesados if p["errores"]] + [{"no_abierto": t} for t in self.no_abiertos]

    def resumen(self):
        if self.sesion_caducada:
            return "«%s»: %s" % (self.nombre, self.error)
        if not self.ok:
            return "«%s»: error: %s" % (self.nombre, self.error)
        no_abiertos = ("; %d correo(s) no se pudieron abrir" % len(self.no_abiertos)) if self.no_abiertos else ""
        if not self.procesados and self.no_encontrados:
            return "«%s»: los correos elegidos ya no aparecen en el buzón (%d)%s" % (self.nombre, self.no_encontrados,
                                                                                  no_abiertos)
        if not self.procesados:
            txt = "«%s»: no hay correos nuevos" % self.nombre
            if self.ya_procesados:
                txt += " (%d ya procesado(s))" % self.ya_procesados
            return txt + no_abiertos
        partes = ["%d correo(s) procesado(s)" % len(self.procesados)]
        if self.archivos:
            partes.append("%d archivo(s)" % len(self.archivos))
        valores = ["%s: %s" % kv for p in self.procesados for kv in p["valores"]][:3]
        partes += valores
        con_error = [p for p in self.procesados if p["errores"]]
        if con_error:
            partes.append("%d con error" % len(con_error))
        if self.pendientes:
            partes.append("%d más para la próxima revisión" % self.pendientes)
        if self.no_encontrados:
            partes.append("%d ya no aparece(n) en el buzón" % self.no_encontrados)
        return "«%s»: %s%s" % (self.nombre, ", ".join(partes), no_abiertos)


def _texto_aviso(p):
    partes = []
    n = len(p["archivos"])
    if n:
        partes.append("%d archivo%s guardado%s" % (n, "" if n == 1 else "s", "" if n == 1 else "s"))
    partes += ["%s: %s" % kv for kv in p["valores"]]
    if p["errores"]:
        partes.append("%d acción(es) con error" % len(p["errores"]))
    return ", ".join(partes) or "procesado"


class _Registro:
    """Las líneas de la revisión: al registro de la interfaz/consola y a un archivo en registros/."""

    def __init__(self, carpeta, log, nombre):
        self.log = log
        self.ruta = ""
        self._f = None
        if carpeta:
            try:
                os.makedirs(carpeta, exist_ok=True)
                base = os.path.join(carpeta, "%s_correo_%s.log" % (datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"),
                                                                   re.sub(r"[^\w-]+", "_", nombre)[:40]))
                self.ruta = _ruta_libre(base)
                self._f = open(self.ruta, "w", encoding="utf-8")
            except OSError:
                self._f = None
                self.ruta = ""

    def __call__(self, linea):
        if self._f:
            try:
                self._f.write("%s %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), linea))
                self._f.flush()
            except OSError:
                pass
        if self.log:
            try:
                self.log(linea)
            except Exception:          # noqa: BLE001
                pass

    def cerrar(self):
        if self._f:
            try:
                self._f.close()
            except OSError:
                pass
            self._f = None


def _resumen_publico(m):
    f = _a_fecha(m.get("fecha"))
    adj = m.get("adjuntos")
    return {"clave": clave_mensaje(m), "asunto": m.get("asunto") or (m.get("texto") or "")[:120],
            "remitente": m.get("remitente") or "", "remitente_correo": m.get("remitente_correo") or "",
            "fecha": f.strftime("%d/%m/%Y %H:%M") if f else "",
            "adjuntos": None if adj is None else [a["nombre"] if isinstance(a, dict) else str(a) for a in adj]}


def _buscar_coincidentes(adaptador, c, hoy, limite, log):
    lista = adaptador.buscar(c, hoy, limite) or []
    candidatos = []
    for m in lista:
        ok, motivo = coincide(m, c, hoy, fase="resumen")
        if ok:
            candidatos.append(m)
        elif log:
            log("  descartado en la lista: %s — %s" % ((m.get("asunto") or m.get("texto") or "?")[:80], motivo))
    return lista, ordenar(candidatos)


def _detalle_completo(m, det):
    """El correo para comprobar los criterios con todo: lo de la lista + lo del correo abierto."""
    junto = dict(m)
    for k in ("asunto", "remitente", "remitente_correo", "fecha"):
        if det.get(k):
            junto[k] = det[k]
    junto["adjuntos"] = det.get("adjuntos") if det.get("adjuntos") is not None else (m.get("adjuntos") or [])
    junto["cuerpo_texto"] = texto_del_cuerpo(det)
    return junto


def probar_busqueda(adaptador, criterios, hoy=None, limite=10, almacen=None, busqueda_id=None, log=None):
    """«Probar búsqueda»: los correos que coinciden AHORA (abiertos para ver sus adjuntos y comprobar el cuerpo), sin
    procesarlos.  Devuelve [{clave, asunto, remitente, fecha, adjuntos, coincide, motivo, procesado}]."""
    c = normalizar_criterios(criterios, hoy, exigir=False)
    _lista, candidatos = _buscar_coincidentes(adaptador, c, hoy, max(limite * 3, 30), log)
    res = []
    for m in candidatos[:limite]:
        d = _resumen_publico(m)
        try:
            det = adaptador.abrir(m)
            ok, motivo = coincide(_detalle_completo(m, det), c, hoy, fase="detalle")
            d.update(adjuntos=[x["nombre"] for x in det.get("adjuntos") or []], coincide=ok, motivo=motivo,
                     asunto=det.get("asunto") or d["asunto"],
                     remitente=det.get("remitente") or d["remitente"])
        except ErrorSesion:
            raise
        except Exception as e:         # noqa: BLE001
            d.update(coincide=False, motivo="no se pudo abrir: %s" % e)
        if almacen is not None and busqueda_id is not None:
            p = almacen.correo_procesado(busqueda_id, d["clave"])
            d["procesado"] = p["cuando"] if p and p["estado"] in ("ok", "error") else ""
            d["estado_procesado"] = p["estado"] if p else ""
        res.append(d)
    return res


# ------------------------------------------------------------------ v3.5: «Correos relacionados»
RANGOS_RELACIONADOS = {"busqueda": "las fechas de la búsqueda", "30": "últimos 30 días", "90": "últimos 90 días",
                       "365": "último año", "todas": "todas las fechas"}
RELACIONADOS_POR_PAGINA = 10
RELACIONADOS_MAX = 200


def criterios_con_rango(c, rango):
    """Los criterios de la búsqueda con OTRO rango de fechas (para la lista de correos relacionados y para procesarlos
    a mano): «busqueda» = el suyo, «30»/«90»/«365» = los últimos N días, «todas» = cualquier fecha."""
    c2 = dict(c)
    r = str(rango or "busqueda")
    if r == "busqueda":
        return c2
    if r == "todas":
        c2["fecha"] = "cualquiera"
        return c2
    try:
        n = int(r)
    except ValueError:
        raise ErrorCorreo("Rango de fechas no válido: %s" % rango)
    if not 1 <= n <= 3650:
        raise ErrorCorreo("Rango de fechas no válido: %s" % rango)
    c2.update(fecha="ultimos", dias=n)
    return c2


def acciones_que_agregan(acciones):
    """Descripción de las acciones que AÑADEN filas a un archivo (procesar otra vez un correo las repetiría)."""
    res = []
    for a in acciones or []:
        if a.get("tipo") == "tabla" and a.get("modo") in ("agregar", "hoja_mes"):
            res.append("copiar la tabla %s a «%s» (agrega filas)" % (a.get("n", 1), a.get("archivo")))
        elif a.get("tipo") == "texto" and a.get("archivo"):
            res.append("anotar «%s» en «%s» (agrega una fila)" % (a.get("campo") or "el texto", a.get("archivo")))
    return res


def estado_de(previo):
    """(estado, texto) del chip: nuevo / procesado / error / descartado."""
    if not previo:
        return "nuevo", "nuevo"
    e = previo.get("estado")
    cuando = previo.get("cuando") or ""
    if e == "ok":
        return "procesado", "ya procesado el %s" % cuando
    if e == "error":
        return "error", "procesado con error el %s" % cuando
    if e == "descartado":
        return "descartado", "descartado el %s" % cuando
    return e or "nuevo", e or "nuevo"


def correos_relacionados(adaptador, criterios, hoy=None, rango="30", desde=0, limite=RELACIONADOS_POR_PAGINA,
                         almacen=None, busqueda_id=None, abrir=True, log=None):
    """«Correos relacionados» (como la lista de cortes de una Página): TODOS los correos que cumplen los criterios de la
    búsqueda, con el rango de fechas `rango` (independiente del de la búsqueda), del más reciente al más antiguo, de
    `desde` a `desde + limite` («Cargar más»).  Cada uno con fecha, remitente, asunto, adjuntos (abriéndolo si `abrir`),
    su estado (nuevo / ya procesado y cuándo / con error / descartado) y `mas_reciente` en el primero.  No procesa
    nada.  Devuelve {mensajes, hay_mas, desde, rango, total_visto}."""
    c = criterios_con_rango(normalizar_criterios(criterios, hoy, exigir=False), rango)
    desde = max(0, int(desde or 0))
    limite = max(1, min(int(limite or RELACIONADOS_POR_PAGINA), 50))
    pedir = max(min(desde + limite + 1, RELACIONADOS_MAX + 1), 30)
    lista, candidatos = _buscar_coincidentes(adaptador, c, hoy, pedir, log)
    trozo = candidatos[desde:desde + limite]
    res = []
    for k, m in enumerate(trozo):
        d = _resumen_publico(m)
        d.update(coincide=True, motivo="", mas_reciente=(desde + k == 0), posicion=desde + k + 1)
        if abrir:
            try:
                det = adaptador.abrir(m)
                ok, motivo = coincide(_detalle_completo(m, det), c, hoy, fase="detalle")
                d.update(adjuntos=[x["nombre"] for x in det.get("adjuntos") or []], coincide=ok, motivo=motivo,
                         asunto=det.get("asunto") or d["asunto"], remitente=det.get("remitente") or d["remitente"])
            except ErrorSesion:
                raise
            except Exception as e:     # noqa: BLE001
                d.update(motivo="no se pudo abrir: %s" % (str(e).splitlines()[0] if str(e) else type(e).__name__))
        previo = almacen.correo_procesado(busqueda_id, d["clave"]) if almacen is not None and busqueda_id else None
        d["estado"], d["estado_texto"] = estado_de(previo)
        d["procesado"] = (previo or {}).get("cuando", "") if d["estado"] in ("procesado", "error") else ""
        d["archivos"] = list((previo or {}).get("archivos") or [])
        res.append(d)
    hay_mas = len(candidatos) > desde + limite or (len(lista) >= pedir and desde + limite < RELACIONADOS_MAX)
    return {"mensajes": res, "hay_mas": bool(hay_mas), "desde": desde, "rango": str(rango or "busqueda"),
            "total_visto": len(candidatos)}


def revisar_busqueda(almacen, busqueda_id, abrir_adaptador, base, hoy=None, log=None, detener=None,
                     carpeta_registros=None, adaptador=None, avisar=True, solo=None, rango=None, buscar_hasta=None,
                     manual=False):
    """Revisa UNA búsqueda: busca los correos que coinciden, salta los ya procesados y, del más reciente al más
    antiguo (como mucho `max_por_vez`), los abre, comprueba el cuerpo y los adjuntos y hace sus acciones.  Apunta cada
    correo en `correos_procesados`, crea los avisos («Llegó «…»: 2 archivos guardados, Total ventas: 1.234») y una
    ejecución en el historial.  `abrir_adaptador(cuenta)` → adaptador (context manager); con `adaptador` se usa ese
    (varias búsquedas de la misma cuenta con un solo navegador).  v3.5: con `solo` (claves) procesa ESOS correos aunque
    ya se hubieran procesado («Correos relacionados» → «Procesar este»), buscándolos con el `rango` de fechas elegido."""
    b = almacen.busqueda_correo(busqueda_id)
    if b is None:
        raise ErrorCorreo("No existe la búsqueda de correo número %s" % busqueda_id)
    r = ResultadoCorreo(b["id"], b["nombre"])
    reg = _Registro(carpeta_registros, log, "busqueda_%d" % b["id"])
    r.ruta_log = reg.ruta
    inicio = time.monotonic()
    cuenta = almacen.cuenta_correo(b["cuenta_id"])
    try:
        if cuenta is None:
            raise ErrorCorreo("La cuenta de correo de «%s» ya no existe: elige otra en «Editar»" % b["nombre"])
        reg("%s el correo «%s» (cuenta «%s», %s): %s" % (
            "Procesar a mano" if solo is not None else "Revisar", b["nombre"], cuenta["nombre"],
            PROVEEDORES.get(cuenta["proveedor"], cuenta["proveedor"]),
            describir_criterios(criterios_con_rango(b["criterios"], rango) if rango else b["criterios"], hoy)))
        extra = {"solo": set(solo), "rango": rango, "buscar_hasta": buscar_hasta} if solo is not None else {
            "manual": bool(manual)}
        if adaptador is not None:
            _revisar_con(almacen, b, cuenta, adaptador, base, hoy, reg, detener, r, **extra)
        else:
            with abrir_adaptador(cuenta) as a:
                _revisar_con(almacen, b, cuenta, a, base, hoy, reg, detener, r, **extra)
        r.ok = True
    except ErrorSesion as e:
        r.sesion_caducada = True
        r.error = str(e) or ("La sesión de «%s» caducó: abre Correo y pulsa «Iniciar sesión en el correo»"
                             % (cuenta or {}).get("nombre", "?"))
        reg("ERROR: " + r.error)
        if cuenta is not None:
            almacen.marcar_sesion_correo(cuenta["id"], "caducada", r.error)
            if avisar:
                avisos.avisar(almacen, "correo_sesion", "La sesión del correo «%s» caducó" % cuenta["nombre"],
                              "El bot no puede entrar en el buzón (pide iniciar sesión). Abre Correo y pulsa «Iniciar "
                              "sesión en el correo»: entras tú una vez en la ventana que se abre y el bot sigue solo.",
                              {"cuenta_id": cuenta["id"], "busqueda_id": b["id"]})
    except (ErrorCorreo, ErrorProveedor) as e:
        r.error = str(e)
        reg("ERROR: " + r.error)
    except Exception as e:             # noqa: BLE001
        r.error = "%s: %s" % (type(e).__name__, str(e).splitlines()[0] if str(e) else "")
        reg("ERROR inesperado: " + r.error)
    finally:
        reg(r.resumen())
        reg.cerrar()
    if cuenta is not None and r.ok:
        almacen.marcar_sesion_correo(cuenta["id"], "ok", "")
        almacen.marcar_notificaciones_de("correo_sesion", "cuenta_id", cuenta["id"])
    if solo is None:                    # (procesar a mano no cuenta como «última revisión»)
        almacen.anotar_revision_correo(b["id"], r.resumen())
    if r.procesados or r.no_abiertos or not r.ok:
        estado = "ok" if r.ok and not r.con_error else "error"
        almacen.registrar_ejecucion(None, estado, r.resumen()[:300], r.archivos, duracion=time.monotonic() - inicio,
                                    registro=r.ruta_log, captura=r.ruta_captura, correo_id=b["id"])
    if avisar:
        for p in r.procesados:
            avisos.avisar(almacen, "correo", "%s «%s»: %s" % ("Procesado otra vez" if p.get("reprocesado") else "Llegó",
                                                            p["asunto"][:90] or "(sin asunto)", _texto_aviso(p)),
                          "%s · %s · búsqueda «%s»" % (p["fecha"], p["remitente"], b["nombre"]),
                          {"busqueda_id": b["id"], "clave": p["clave"], "archivos": p["archivos"][:20]}, windows=False)
        if r.procesados:
            avisos.notificar("Correo: %s" % b["nombre"], "; ".join(
                "«%s»: %s" % (p["asunto"][:50], _texto_aviso(p)) for p in r.procesados)[:280])
        elif not r.ok and not r.sesion_caducada:
            avisos.avisar(almacen, "correo_error", "Falló la revisión del correo «%s»" % b["nombre"], r.error[:300],
                          {"busqueda_id": b["id"]})
    return r


def _revisar_con(almacen, b, cuenta, a, base, hoy, reg, detener, r, solo=None, rango=None, buscar_hasta=None,
                 manual=False):
    """`solo` (v3.5, «Procesar este» / «Procesar seleccionados»): las claves de los correos que hay que procesar AHORA,
    aunque ya se hubieran procesado (se rehacen todas sus acciones y se actualiza su registro, sin duplicarlo); se buscan
    con `rango` (otras fechas que las de la búsqueda) y hasta `buscar_hasta` resultados.
    v3.6.1 `manual` («Revisar ahora» en la interfaz): si no hay ninguno nuevo, se rehacen las acciones del MÁS RECIENTE
    que coincide (con la fecha de la búsqueda).  El horario automático (línea de órdenes) sigue solo con los nuevos."""
    forzar = solo is not None
    # v3.6.1: «Procesar también los que ya se procesaron»: cada revisión rehace las acciones de todos los que coinciden
    reprocesar = not forzar and bool((b.get("criterios") or {}).get("reprocesar"))
    rehacer = forzar or reprocesar
    c = criterios_con_rango(b["criterios"], rango) if rango else b["criterios"]
    maximo = int(b.get("max_por_vez") or MAX_POR_VEZ) if not forzar else max(len(solo), 1)
    limite = max(maximo * 3, 30) if not forzar else max(int(buscar_hasta or 0), RELACIONADOS_POR_PAGINA * 3, 30)
    lista, candidatos = _buscar_coincidentes(a, c, hoy, limite, reg)
    r.encontrados = len(candidatos)
    reg("La búsqueda devolvió %d correo(s); coinciden %d" % (len(lista), len(candidatos)))
    nuevos = []
    for m in candidatos:
        clave = clave_mensaje(m)
        previo = almacen.correo_procesado(b["id"], clave)
        if forzar:
            if clave in solo and clave not in [x[1] for x in nuevos]:
                nuevos.append((m, clave, previo))
            continue
        if previo and not reprocesar and (previo["estado"] in ("ok", "descartado")
                                          or int(previo.get("intentos") or 0) >= MAX_INTENTOS):
            r.ya_procesados += previo["estado"] == "ok"
            continue
        nuevos.append((m, clave, previo))
    if forzar:
        faltan = [k for k in solo if k not in [x[1] for x in nuevos]]
        if faltan:
            r.no_encontrados = len(faltan)
            reg("%d correo(s) elegido(s) ya no aparecen en la búsqueda (¿se movieron o se borraron?)" % len(faltan))
        reg("Procesar a mano %d correo(s) (aunque ya se hubieran procesado: se rehacen todas sus acciones)"
            % len(nuevos))
    elif manual and not nuevos and candidatos:
        m = candidatos[0]                       # (ordenados del más reciente al más antiguo)
        clave = clave_mensaje(m)
        nuevos = [(m, clave, almacen.correo_procesado(b["id"], clave))]
        rehacer = True
        pub = _resumen_publico(m)
        reg("No hay correos nuevos: como lo pediste tú («Revisar ahora»), se rehacen las acciones del más reciente: "
            "«%s» (%s)" % (pub["asunto"][:90], pub["fecha"] or "sin fecha"))
    elif reprocesar and any(p and p["estado"] in ("ok", "error") for _m, _k, p in nuevos):
        reg("«Procesar también los que ya se procesaron»: se rehacen las acciones de los que ya se habían procesado")
    if len(nuevos) > maximo:
        r.pendientes = len(nuevos) - maximo
        reg("Hay %d correo(s) nuevo(s): se procesan los %d más recientes (el resto, en la próxima revisión)"
            % (len(nuevos), maximo))
        nuevos = nuevos[:maximo]
    for m, clave, previo in nuevos:
        if detener is not None and detener.is_set():
            reg("Detenido por el usuario")
            break
        pub = _resumen_publico(m)
        reg("Abriendo «%s» (%s, %s)" % (pub["asunto"][:90], pub["remitente"], pub["fecha"] or "sin fecha"))
        try:
            det = a.abrir(m)
        except ErrorSesion:
            raise
        except Exception as e:         # noqa: BLE001 (un correo que no se abre no para los demás; se reintenta luego)
            texto = str(e).splitlines()[0] if str(e) else type(e).__name__
            r.no_abiertos.append("%s: %s" % (pub["asunto"][:60], texto))
            reg("  no se pudo abrir: %s (se intentará en la próxima revisión)" % texto)
            continue
        junto = _detalle_completo(m, det)
        ok, motivo = coincide(junto, c, hoy, fase="detalle")
        if not ok:
            r.descartados += 1
            reg("  no coincide al abrirlo: %s (no se procesa)" % motivo)
            if not (rehacer and previo and previo["estado"] in ("ok", "error")):  # (no se pierde lo que ya se hizo)
                almacen.marcar_correo_procesado(b["id"], clave, "descartado", asunto=pub["asunto"],
                                                remitente=pub["remitente"], fecha=pub["fecha"], mensaje=motivo)
            continue
        # a mano (`forzar`): se rehacen TODAS las acciones; en una revisión normal, solo las que faltaron
        hechas = [] if rehacer else ((previo or {}).get("hechas") or [])

        def descargar(nombres, carpeta, m=m, det=det):
            return a.descargar(m, det, nombres, carpeta)
        hecho = aplicar_acciones(b["acciones"], m, det, descargar, base, hoy, reg, hechas=hechas, reporte=b["nombre"])
        asunto = det.get("asunto") or pub["asunto"]
        remitente = nombre_de(det.get("remitente") or pub["remitente"]) or pub["remitente_correo"]
        p = {"clave": clave, "asunto": asunto, "remitente": remitente, "fecha": pub["fecha"],
             "archivos": hecho["archivos"], "valores": hecho["valores"], "errores": hecho["errores"],
             "reprocesado": bool(rehacer and previo and previo["estado"] in ("ok", "error"))}
        # en un reintento se juntan los valores/archivos del intento anterior (lo ya hecho no se repite)
        if previo and not rehacer:
            p["archivos"] = list(previo.get("archivos") or []) + p["archivos"]
            p["valores"] = [tuple(x) for x in previo.get("valores") or []] + p["valores"]
        estado = "error" if hecho["errores"] else "ok"
        mensaje = "; ".join(hecho["errores"])
        if forzar:
            mensaje = ("Procesado otra vez a mano. " if p["reprocesado"] else "Procesado a mano. ") + mensaje
        # INSERT OR REPLACE por (búsqueda, clave): volver a procesar ACTUALIZA el registro, no lo duplica
        almacen.marcar_correo_procesado(b["id"], clave, estado, asunto=asunto, remitente=remitente, fecha=pub["fecha"],
                                        archivos=p["archivos"], valores=p["valores"], hechas=hecho["hechas"],
                                        mensaje=mensaje.strip()[:500],
                                        intentos=1 if rehacer else int((previo or {}).get("intentos") or 0) + 1)
        r.procesados.append(p)


def revisar_varias(almacen, ids, abrir_adaptador, base, hoy=None, log=None, detener=None, carpeta_registros=None,
                   al_resultado=None, manual=False):
    """Revisa varias búsquedas; las de la misma cuenta comparten el navegador (o la conexión IMAP).  Si la sesión de
    una cuenta caducó, sus demás búsquedas no se intentan (mismo aviso).  `manual`: ver `_revisar_con`."""
    por_cuenta = {}
    for bid in ids:
        b = almacen.busqueda_correo(bid)
        if b is not None:
            por_cuenta.setdefault(b["cuenta_id"], []).append(b["id"])
    resultados = []
    for cuenta_id, bids in por_cuenta.items():
        cuenta = almacen.cuenta_correo(cuenta_id)
        if cuenta is None or len(bids) == 1:
            for bid in bids:
                if detener is not None and detener.is_set():
                    return resultados
                resultados.append(revisar_busqueda(almacen, bid, abrir_adaptador, base, hoy, log, detener,
                                                   carpeta_registros, manual=manual))
                if al_resultado:
                    al_resultado(resultados[-1])
            continue
        error, caducada = "", False
        try:
            with abrir_adaptador(cuenta) as a:
                for bid in bids:
                    if detener is not None and detener.is_set():
                        return resultados
                    r = revisar_busqueda(almacen, bid, abrir_adaptador, base, hoy, log, detener, carpeta_registros,
                                         adaptador=a, manual=manual)
                    resultados.append(r)
                    if al_resultado:
                        al_resultado(r)
                    if r.sesion_caducada:
                        error, caducada = r.error, True
                        break
        except (ErrorSesion, ErrorProveedor, ErrorCorreo) as e:
            error, caducada = str(e), isinstance(e, ErrorSesion)
            if caducada:
                almacen.marcar_sesion_correo(cuenta["id"], "caducada", error)
                avisos.avisar(almacen, "correo_sesion", "La sesión del correo «%s» caducó" % cuenta["nombre"],
                              "El bot no puede entrar en el buzón (pide iniciar sesión). Abre Correo y pulsa «Iniciar "
                              "sesión en el correo»: entras tú una vez en la ventana que se abre y el bot sigue solo.",
                              {"cuenta_id": cuenta["id"]})
        for bid in bids:                       # las que no se pudieron revisar (no se abrió el buzón / sesión caducada)
            if any(x.busqueda_id == bid for x in resultados):
                continue
            r = ResultadoCorreo(bid, (almacen.busqueda_correo(bid) or {}).get("nombre", "?"))
            r.error = error or "no se revisó"
            r.sesion_caducada = caducada
            almacen.anotar_revision_correo(bid, r.resumen())
            resultados.append(r)
            if al_resultado:
                al_resultado(r)
    return resultados


# ============================================================================== proveedores
def crear_adaptador(cuenta, carpeta_perfiles, oculto=True, navegador="chrome", log=None, detener=None,
                    esperar_login=0, carpeta_nativa=None):
    """El adaptador del proveedor de la cuenta (se usa con `with`).  `esperar_login` > 0 = ventana VISIBLE en la que
    el usuario inicia sesión él mismo (el bot espera a que cargue la bandeja hasta esos segundos)."""
    p = cuenta.get("proveedor")
    if p == "imap":
        from .correo_imap import AdaptadorImap
        return AdaptadorImap(cuenta, log=log)
    perfil = os.path.join(carpeta_perfiles, "correo_%d" % int(cuenta["id"]))
    if p == "gmail_web":
        from .correo_gmail import AdaptadorGmail
        return AdaptadorGmail(cuenta, perfil, oculto=oculto, navegador=navegador, log=log, detener=detener,
                              esperar_login=esperar_login)
    from .correo_outlook import AdaptadorOutlook
    return AdaptadorOutlook(cuenta, perfil, oculto=oculto, navegador=navegador, log=log, detener=detener,
                            esperar_login=esperar_login, carpeta_nativa=carpeta_nativa)


def a_json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)


def leer_json(texto, defecto):
    try:
        v = json.loads(texto) if texto else defecto
    except (TypeError, ValueError):
        return defecto
    return v if isinstance(v, type(defecto)) else defecto


def csv_de_tabla(filas):
    """Una tabla como texto CSV (para la vista previa)."""
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    for f in filas:
        w.writerow(f)
    return salida.getvalue()
