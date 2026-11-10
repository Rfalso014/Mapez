"""Plantillas de texto: fechas dinámicas y variables.  No importa playwright.

Ejemplos de uso dentro de cualquier texto de un paso:

    {hoy}                      -> 23/10/2026   (formato por defecto %d/%m/%Y)
    {hoy:%Y-%m-%d}             -> 2026-10-23   (cualquier formato strftime)
    {ayer}  {ayer:%d-%m}
    {dias:-7}                  -> hace 7 días  ({dias:3} = dentro de 3 días)
    {dias:-7:%d/%m/%Y}
    {inicio_mes} {fin_mes} {inicio_mes_anterior} {fin_mes_anterior}
    {lunes_semana} {lunes_semana_anterior} {domingo_semana_anterior} {inicio_anio}   (v3.6)
    {ext}                      -> extensión del archivo descargado (solo en nombres de descarga)
    {nombre}                   -> nombre original del archivo descargado (el que da la web), sin extensión
    {reporte}                  -> (v3.5) nombre completo del reporte (en una Página, el de la Página; en el correo, el de
                                  la búsqueda), tal cual: con sus espacios, comas, acentos y puntos («Ventas S.A.S.»)
    {secreto:nombre}           -> contraseña guardada en el Administrador de credenciales
    {cliente}                  -> variable propia definida en el flujo o con --var
    {fecha}  {fecha:%Y-%m-%d}  -> (v3.0) el día que se está descargando con «Repetir por días» (si no, hoy)
    {opcion}                   -> (v3.0) texto de la última opción elegida por un paso «Elegir opción»
    {{  y  }}                  -> llaves literales
"""

import calendar
import datetime
import re

FORMATO_FECHA = "%d/%m/%Y"

FECHAS = ("hoy", "ayer", "inicio_mes", "fin_mes", "inicio_mes_anterior", "fin_mes_anterior",
          # v3.6: semanas y año (el lunes es el primer día de la semana)
          "lunes_semana", "lunes_semana_anterior", "domingo_semana_anterior", "inicio_anio")
RESERVADAS = set(FECHAS) | {"dias", "ext", "nombre", "secreto", "fecha", "opcion", "reporte"}

AYUDA_PLANTILLAS = [
    ("{hoy}", "Fecha de hoy"),
    ("{ayer}", "Fecha de ayer"),
    ("{hoy:%d/%m/%Y}", "Hoy con formato dd/mm/aaaa"),
    ("{hoy:%Y-%m-%d}", "Hoy con formato aaaa-mm-dd"),
    ("{dias:-7}", "Hace 7 días"),
    ("{dias:-7:%d/%m/%Y}", "Hace 7 días con formato"),
    ("{inicio_mes}", "Primer día de este mes"),
    ("{fin_mes}", "Último día de este mes"),
    ("{inicio_mes_anterior}", "Primer día del mes anterior"),
    ("{fin_mes_anterior}", "Último día del mes anterior"),
    ("{lunes_semana}", "Lunes de esta semana"),
    ("{lunes_semana_anterior}", "Lunes de la semana pasada"),
    ("{domingo_semana_anterior}", "Domingo de la semana pasada"),
    ("{inicio_anio}", "1 de enero de este año"),
    ("{fecha}", "Día que se descarga (Repetir por días; si no, hoy)"),
    ("{fecha:%Y-%m-%d}", "Ese día con formato aaaa-mm-dd"),
    ("{reporte}", "Nombre completo del reporte"),
]


class ErrorPlantilla(ValueError):
    """La plantilla tiene un error (variable desconocida, llave sin cerrar, etc.)."""


def _como_fecha(hoy):
    if hoy is None:
        return datetime.datetime.now()
    if isinstance(hoy, datetime.datetime):
        return hoy
    if isinstance(hoy, datetime.date):
        return datetime.datetime(hoy.year, hoy.month, hoy.day)
    raise TypeError("«hoy» debe ser date o datetime")


def _inicio_mes(f):
    return f.replace(day=1)


def _fin_mes(f):
    return f.replace(day=calendar.monthrange(f.year, f.month)[1])


def _fecha_nombrada(nombre, ahora):
    if nombre == "hoy":
        return ahora
    if nombre == "ayer":
        return ahora - datetime.timedelta(days=1)
    if nombre == "inicio_mes":
        return _inicio_mes(ahora)
    if nombre == "fin_mes":
        return _fin_mes(ahora)
    if nombre == "lunes_semana":
        return ahora - datetime.timedelta(days=ahora.weekday())
    if nombre == "lunes_semana_anterior":
        return ahora - datetime.timedelta(days=ahora.weekday() + 7)
    if nombre == "domingo_semana_anterior":
        return ahora - datetime.timedelta(days=ahora.weekday() + 1)
    if nombre == "inicio_anio":
        return ahora.replace(month=1, day=1)
    anterior = _inicio_mes(ahora) - datetime.timedelta(days=1)  # último día del mes anterior
    if nombre == "fin_mes_anterior":
        return anterior
    if nombre == "inicio_mes_anterior":
        return _inicio_mes(anterior)
    raise ErrorPlantilla("Fecha desconocida: {%s}" % nombre)


def _formatear(fecha, formato):
    try:
        return fecha.strftime(formato)
    except ValueError as e:
        raise ErrorPlantilla("Formato de fecha no válido «%s»: %s" % (formato, e))


def _tokens(texto):
    """Divide el texto en ('lit', texto) y ('var', contenido)."""
    salida = []
    lit = []
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if c == "{":
            if texto[i + 1:i + 2] == "{":
                lit.append("{")
                i += 2
                continue
            fin = texto.find("}", i + 1)
            if fin < 0:
                raise ErrorPlantilla("Falta cerrar una llave «}» en: %s" % texto)
            if lit:
                salida.append(("lit", "".join(lit)))
                lit = []
            salida.append(("var", texto[i + 1:fin]))
            i = fin + 1
        elif c == "}":
            if texto[i + 1:i + 2] == "}":
                lit.append("}")
                i += 2
                continue
            raise ErrorPlantilla("Hay una llave «}» sin abrir en: %s (usa «}}» para una llave literal)" % texto)
        else:
            lit.append(c)
            i += 1
    if lit:
        salida.append(("lit", "".join(lit)))
    return salida


def renderizar(texto, variables=None, hoy=None, ext=None, nombre=None,
               resolver_secreto=None, enmascarar_secretos=False,
               formato_defecto=FORMATO_FECHA, fecha=None, reporte=None):
    """Sustituye las plantillas de `texto`.

    - hoy: fecha «de hoy» (inyectable para pruebas); por defecto, la actual.
    - ext / nombre: valores para {ext} y {nombre} (solo en nombres de descarga).
    - fecha: el día de {fecha} («Repetir por días»); por defecto, `hoy`.
    - reporte: (v3.5) el nombre del reporte para {reporte} (una variable propia «reporte» del flujo tiene prioridad).
    - resolver_secreto: función nombre -> contraseña.  Con enmascarar_secretos=True
      no se llama y se devuelve «********» (para registros).
    """
    if texto is None:
        return ""
    texto = str(texto)
    ahora = _como_fecha(hoy)
    variables = variables or {}
    partes = []
    for clase, cont in _tokens(texto):
        if clase == "lit":
            partes.append(cont)
            continue
        nombre_var, _, resto = cont.partition(":")
        nombre_var = nombre_var.strip()
        if nombre_var in FECHAS:
            fecha = _fecha_nombrada(nombre_var, ahora)
            partes.append(_formatear(fecha, resto if resto else formato_defecto))
        elif nombre_var == "fecha":
            dia = _como_fecha(fecha) if fecha is not None else ahora
            partes.append(_formatear(dia, resto if resto else formato_defecto))
        elif nombre_var == "dias":
            cantidad, _, formato = resto.partition(":")
            try:
                n = int(cantidad.strip())
            except ValueError:
                raise ErrorPlantilla("{dias:N} necesita un número entero, por ejemplo {dias:-7}: {%s}" % cont)
            fecha = ahora + datetime.timedelta(days=n)
            partes.append(_formatear(fecha, formato if formato else formato_defecto))
        elif nombre_var == "ext":
            if ext is None:
                raise ErrorPlantilla("{ext} solo se puede usar en el nombre de una descarga")
            partes.append(ext)
        elif nombre_var == "nombre":
            if nombre is None:
                raise ErrorPlantilla("{nombre} solo se puede usar en el nombre de una descarga")
            partes.append(nombre)
        elif nombre_var == "reporte" and not resto and "reporte" not in variables:
            if reporte is None:
                raise ErrorPlantilla("{reporte} solo se puede usar dentro de un reporte (es su nombre)")
            partes.append(str(reporte))
        elif nombre_var == "secreto":
            clave = resto.strip()
            if not clave:
                raise ErrorPlantilla("{secreto:nombre} necesita el nombre de la contraseña")
            if enmascarar_secretos:
                partes.append("********")
            elif resolver_secreto is None:
                raise ErrorPlantilla("No hay almacén de contraseñas disponible para {secreto:%s}" % clave)
            else:
                partes.append(resolver_secreto(clave))
        elif nombre_var == "opcion" and "opcion" not in variables:
            raise ErrorPlantilla("{opcion} solo se puede usar después de un paso «Elegir opción»")
        elif cont.strip() in variables:
            partes.append(str(variables[cont.strip()]))
        else:
            raise ErrorPlantilla("Variable desconocida: {%s}. Defínela en el flujo o con --var %s=valor"
                                 % (cont, nombre_var))
    return "".join(partes)


def variables_usadas(texto):
    """Lista de nombres de variable propia usados en el texto (sin fechas ni secretos)."""
    usadas = []
    try:
        for clase, cont in _tokens(texto or ""):
            if clase == "var":
                nombre = cont.partition(":")[0].strip()
                if nombre not in RESERVADAS and nombre not in usadas:
                    usadas.append(nombre)
    except ErrorPlantilla:
        pass
    return usadas


def secretos_usados(texto):
    """Lista de nombres de {secreto:...} usados en el texto."""
    res = []
    try:
        for clase, cont in _tokens(texto or ""):
            if clase == "var" and cont.partition(":")[0].strip() == "secreto":
                nombre = cont.partition(":")[2].strip()
                if nombre and nombre not in res:
                    res.append(nombre)
    except ErrorPlantilla:
        pass
    return res


def escapar(texto):
    """Escapa llaves para que un texto literal no se interprete como plantilla."""
    return str(texto).replace("{", "{{").replace("}", "}}")


def es_plantilla(texto):
    """True si el texto contiene alguna variable {…} (no solo llaves escapadas)."""
    try:
        return any(c == "var" for c, _ in _tokens(texto or ""))
    except ErrorPlantilla:
        return False


def validar(texto):
    """Devuelve None si la plantilla es sintácticamente válida, o el mensaje de error."""
    try:
        _tokens(texto or "")
    except ErrorPlantilla as e:
        return str(e)
    return None


# --- Detección de fechas al grabar -----------------------------------------

_FORMATOS_DETECTAR = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d", "%d.%m.%Y", "%Y%m%d"]
_PATRONES = {
    "%d/%m/%Y": r"\d{2}/\d{2}/\d{4}", "%Y-%m-%d": r"\d{4}-\d{2}-\d{2}",
    "%d-%m-%Y": r"\d{2}-\d{2}-\d{4}", "%d/%m/%y": r"\d{2}/\d{2}/\d{2}",
    "%Y/%m/%d": r"\d{4}/\d{2}/\d{2}", "%d.%m.%Y": r"\d{2}\.\d{2}\.\d{4}",
}


def _plantilla_fecha(nombre, formato):
    return "{%s}" % nombre if formato == FORMATO_FECHA else "{%s:%s}" % (nombre, formato)


# Fechas que se proponen al grabar, por orden de preferencia (si coinciden varias, gana la primera).
FECHAS_PROPUESTAS = ("hoy", "ayer", "inicio_mes", "fin_mes", "inicio_mes_anterior", "fin_mes_anterior")


def proponer_fecha_dinamica(texto, hoy=None):
    """Si `texto` es exactamente una fecha relativa (hoy, ayer, inicio/fin del mes o del mes anterior)
    en un formato habitual, devuelve la plantilla equivalente ('{hoy}', '{inicio_mes:%Y-%m-%d}', …);
    si no, None."""
    ahora = _como_fecha(hoy)
    for nombre in FECHAS_PROPUESTAS:
        fecha = _fecha_nombrada(nombre, ahora)
        for formato in _FORMATOS_DETECTAR:
            if texto == fecha.strftime(formato):
                return _plantilla_fecha(nombre, formato)
    return None


def fechas_a_plantilla(texto, hoy=None):
    """Sustituye dentro de un texto (p. ej. un nombre de archivo) las fechas de hoy/ayer
    por su plantilla y escapa el resto de llaves.
    Ej.: 'rep_2026-10-23' -> 'rep_{hoy:%Y-%m-%d}'."""
    ahora = _como_fecha(hoy)
    candidatos = {}
    for nombre in ("hoy", "ayer"):
        fecha = _fecha_nombrada(nombre, ahora)
        for formato in _PATRONES:
            candidatos.setdefault(fecha.strftime(formato), (nombre, formato))
    patron = re.compile("|".join("(?<!\\d)%s(?!\\d)" % p for p in _PATRONES.values()))
    salida = []
    pos = 0
    for m in patron.finditer(texto):
        salida.append(escapar(texto[pos:m.start()]))
        encontrado = m.group(0)
        if encontrado in candidatos:
            salida.append(_plantilla_fecha(*candidatos[encontrado]))
        else:
            salida.append(escapar(encontrado))
        pos = m.end()
    salida.append(escapar(texto[pos:]))
    return "".join(salida)


# --- v3.6: el campo de fecha de la interfaz («campoFecha») ----------------------------------------------------------
#
# La interfaz enseña las fechas con un calendario (fecha FIJA) o con botones («Hoy», «Ayer», «Hace 7 días»…: fecha que
# CAMBIA SOLA en cada ejecución) y un formato con ejemplos («28/10/2026»), pero lo que se guarda sigue siendo el mismo
# texto de siempre: «15/10/2026», «{ayer:%d/%m/%Y}», «{dias:-7}»…  `analizar_fecha` lee ese texto y `plantilla_fecha` lo
# vuelve a escribir (`ui/app.js` hace lo mismo con analizarFecha / componerFecha; las pruebas comprueban que coinciden).

# Formatos que se ofrecen (con un ejemplo de verdad en la interfaz): (formato, nota).  El primero es el de siempre.
FORMATOS_FECHA = (
    ("%d/%m/%Y", ""), ("%Y-%m-%d", "como los campos de fecha"), ("%d-%m-%Y", ""), ("%m/%d/%Y", "el mes primero"),
    ("%d.%m.%Y", ""), ("%Y/%m/%d", ""), ("%d/%m/%y", "año con 2 cifras"), ("%Y%m%d", "sin separadores"),
    ("%d %b %Y", "mes en inglés"),
)
# Fechas que cambian solas (orden de los botones de la interfaz) con su nombre en palabras.  «dias» = hace / dentro de N
# días; «fecha» = el día que se descarga con «Repetir por días».
RELATIVAS = (
    ("hoy", "hoy"), ("ayer", "ayer"), ("dias", "hace N días"), ("lunes_semana", "lunes de esta semana"),
    ("lunes_semana_anterior", "lunes de la semana pasada"), ("domingo_semana_anterior", "domingo de la semana pasada"),
    ("inicio_mes", "inicio de este mes"), ("fin_mes", "fin de este mes"), ("inicio_mes_anterior", "inicio del mes anterior"),
    ("fin_mes_anterior", "fin del mes anterior"), ("inicio_anio", "1 de enero"), ("fecha", "el día que se descarga"),
)
_NOMBRES_RELATIVAS = dict(RELATIVAS)
# Fechas escritas tal cual que se reconocen como fecha fija (sin «aaaammdd»: un número de 8 cifras puede ser otra cosa;
# dd/mm antes que mm/dd: «10/11/2026» es el 10 de noviembre).
_FORMATOS_FIJA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%y", "%m/%d/%Y", "%d %b %Y")
_RX_RELATIVA = re.compile(r"^\{(%s|fecha)(?::([^{}]+))?\}$" % "|".join(FECHAS))
_RX_DIAS = re.compile(r"^\{dias:\s*([+-]?\d+)\s*(?::([^{}]+))?\}$")


def _formato_valido(formato):
    try:
        datetime.date(2026, 10, 28).strftime(formato)
    except ValueError:
        return False
    return bool(formato) and "%" in formato


def analizar_fecha(texto):
    """Lee una fecha guardada para el campo de fecha de la interfaz.  Devuelve un dict:

    - {"modo": "vacia"}                                       → ""
    - {"modo": "fija", "fecha": "2026-10-15", "formato": "%d/%m/%Y"}      → «15/10/2026»
    - {"modo": "relativa", "que": "ayer", "n": None, "formato": "%d/%m/%Y"} → «{ayer:%d/%m/%Y}»
    - {"modo": "relativa", "que": "dias", "n": -7, "formato": None}        → «{dias:-7}» (formato None = el de siempre)
    - {"modo": "mano", "texto": …}                             → cualquier otra cosa (se escribe a mano)
    """
    t = "" if texto is None else str(texto)
    if not t.strip():
        return {"modo": "vacia"}
    s = t.strip()
    m = _RX_RELATIVA.match(s)
    if m and (m.group(2) is None or _formato_valido(m.group(2))):
        return {"modo": "relativa", "que": m.group(1), "n": None, "formato": m.group(2)}
    m = _RX_DIAS.match(s)
    if m and (m.group(2) is None or _formato_valido(m.group(2))):
        return {"modo": "relativa", "que": "dias", "n": int(m.group(1)), "formato": m.group(2)}
    if s == t and "{" not in s and "}" not in s:
        for formato in _FORMATOS_FIJA:
            try:
                d = datetime.datetime.strptime(s, formato)
            except ValueError:
                continue
            if d.strftime(formato) == s:          # (exacta: con sus ceros; «1/2/2026» se escribe a mano)
                return {"modo": "fija", "fecha": d.strftime("%Y-%m-%d"), "formato": formato}
    return {"modo": "mano", "texto": t}


def plantilla_fecha(a):
    """Lo contrario de `analizar_fecha`: el texto que se guarda (y que el bot escribe)."""
    modo = (a or {}).get("modo") or "vacia"
    formato = a.get("formato") or None
    if modo == "vacia":
        return ""
    if modo == "mano":
        return str(a.get("texto") or "")
    if formato is not None and not _formato_valido(formato):
        raise ErrorPlantilla("Formato de fecha no válido «%s»" % formato)
    if modo == "fija":
        try:
            d = datetime.datetime.strptime(str(a.get("fecha") or ""), "%Y-%m-%d")
        except ValueError:
            raise ErrorPlantilla("Fecha no válida: %s (se espera AAAA-MM-DD)" % a.get("fecha"))
        return escapar(d.strftime(formato or FORMATO_FECHA))
    if modo == "relativa":
        que = a.get("que")
        if que == "dias":
            try:
                n = int(a.get("n"))
            except (TypeError, ValueError):
                raise ErrorPlantilla("«Hace N días» necesita un número")
            return "{dias:%d%s}" % (n, (":" + formato) if formato else "")
        if que not in FECHAS and que != "fecha":
            raise ErrorPlantilla("Fecha desconocida: %s" % que)
        return "{%s%s}" % (que, (":" + formato) if formato else "")
    raise ErrorPlantilla("Modo de fecha desconocido: %s" % modo)


def formato_de_fecha(texto):
    """El formato de una fecha guardada («{ayer:%Y-%m-%d}» → «%Y-%m-%d», «15/10/2026» → «%d/%m/%Y»), o None."""
    a = analizar_fecha(texto)
    if a["modo"] in ("fija", "relativa"):
        return a.get("formato") or FORMATO_FECHA
    return None


def describir_fecha(texto, hoy=None):
    """En palabras, para la interfaz y los registros: «ayer · 28/10/2026», «hace 7 días · 22/10/2026», «fecha fija ·
    15/10/2026».  Lo que no se entiende se devuelve tal cual."""
    a = analizar_fecha(texto)
    if a["modo"] == "vacia":
        return ""
    if a["modo"] == "mano":
        return str(texto)
    try:
        vista = renderizar(plantilla_fecha(a), hoy=hoy) if a["modo"] == "relativa" else str(texto).strip()
    except ErrorPlantilla:
        return str(texto)
    if a["modo"] == "fija":
        return "fecha fija · " + vista
    if a["que"] == "dias":
        n = a["n"]
        palabras = "hoy" if n == 0 else ("hace %d día%s" % (-n, "" if n == -1 else "s") if n < 0 else
                                         "dentro de %d día%s" % (n, "" if n == 1 else "s"))
    else:
        palabras = _NOMBRES_RELATIVAS.get(a["que"], a["que"])
    return "%s · %s" % (palabras, vista)
