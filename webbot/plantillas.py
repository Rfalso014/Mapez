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
    {desde}  {hasta}           -> (v3.9) inicio y fin del periodo que se descarga con «Repetir por meses / quincenas» (con
                                  «Repetir por días», ese día; sin repetir, hoy).  {desde:%Y-%m-%d} con formato.
    {inicio_quincena_anterior} {fin_quincena_anterior}   (v3.9) la última quincena ya terminada (corte: el día 15 o el
                                  que elija el usuario)
    {dia_mes_anterior:15}      -> (v3.9) el día 15 del mes anterior; si ese mes no tiene ese día (30 en febrero), su último
                                  día.  {dia_mes_anterior:15:%Y-%m-%d} con formato
    {opcion}                   -> (v3.0) texto de la última opción elegida por un paso «Elegir opción»
    {{  y  }}                  -> llaves literales
"""

import calendar
import datetime
import re

FORMATO_FECHA = "%d/%m/%Y"

FECHAS = ("hoy", "ayer", "inicio_mes", "fin_mes", "inicio_mes_anterior", "fin_mes_anterior",
          # v3.6: semanas y año (el lunes es el primer día de la semana)
          "lunes_semana", "lunes_semana_anterior", "domingo_semana_anterior", "inicio_anio",
          # v3.9: la última quincena ya terminada (el mes se parte en el día de corte: el 15 si no se dice otro)
          "inicio_quincena_anterior", "fin_quincena_anterior")
PERIODO = ("desde", "hasta")         # v3.9: inicio y fin del periodo que se descarga (Repetir por meses / quincenas)
DIA_MES_ANTERIOR = "dia_mes_anterior"     # v3.9: {dia_mes_anterior:N} = el día N del mes anterior
RESERVADAS = set(FECHAS) | {"dias", "ext", "nombre", "secreto", "fecha", "opcion", "reporte", DIA_MES_ANTERIOR} | set(PERIODO)
CORTE_QUINCENA = 15                  # v3.9: día en que empieza la 2.ª quincena (si el reporte no dice otro)

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
    ("{dia_mes_anterior:15}", "Día 15 del mes anterior (si no existe, su último día)"),
    ("{lunes_semana}", "Lunes de esta semana"),
    ("{lunes_semana_anterior}", "Lunes de la semana pasada"),
    ("{domingo_semana_anterior}", "Domingo de la semana pasada"),
    ("{inicio_anio}", "1 de enero de este año"),
    ("{fecha}", "Día que se descarga (Repetir por días; si no, hoy)"),
    ("{fecha:%Y-%m-%d}", "Ese día con formato aaaa-mm-dd"),
    ("{inicio_quincena_anterior}", "Primer día de la última quincena terminada"),
    ("{fin_quincena_anterior}", "Último día de la última quincena terminada"),
    ("{desde}", "Inicio del periodo que se descarga (Repetir por meses / quincenas)"),
    ("{hasta}", "Fin del periodo que se descarga (Repetir por meses / quincenas)"),
    ("{desde:%Y-%m-%d}", "Inicio del periodo con formato aaaa-mm-dd"),
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


def validar_corte(corte):
    """v3.9: el día de corte de las quincenas (2–28: la 2.ª quincena empieza ese día).  Devuelve el entero."""
    if corte in (None, ""):
        return CORTE_QUINCENA
    try:
        c = int(corte)
    except (TypeError, ValueError):
        raise ErrorPlantilla("El día de corte de la quincena debe ser un número entre 2 y 28")
    if not 2 <= c <= 28:
        raise ErrorPlantilla("El día de corte de la quincena debe estar entre 2 y 28 (llegó %s)" % corte)
    return c


def quincenas_del_mes(anio, mes, corte=CORTE_QUINCENA):
    """v3.9: las dos quincenas del mes [(día 1, corte − 1), (corte, último día)] como pares de datetime.date."""
    corte = validar_corte(corte)
    fin = calendar.monthrange(anio, mes)[1]
    return [(datetime.date(anio, mes, 1), datetime.date(anio, mes, corte - 1)),
            (datetime.date(anio, mes, corte), datetime.date(anio, mes, fin))]


def quincena_anterior(hoy=None, corte=CORTE_QUINCENA, mitades=(1, 2)):
    """v3.9: (desde, hasta) de la última quincena YA TERMINADA antes de `hoy`.  `mitades`: (1,) solo la primera (del 1
    al corte − 1), (2,) solo la segunda (del corte a fin de mes).  Con corte 15: el 15/11 → 01/11–14/11; el 01/12 →
    15/11–30/11; el 12/11 → 15/10–31/10."""
    base = _como_fecha(hoy).date()
    anio, mes = base.year, base.month
    for _ in range(3):
        for n, (d, h) in reversed(list(enumerate(quincenas_del_mes(anio, mes, corte), 1))):
            if n in mitades and h < base:
                return d, h
        anio, mes = (anio, mes - 1) if mes > 1 else (anio - 1, 12)
    raise ErrorPlantilla("No se pudo calcular la quincena anterior")


def dia_del_mes_anterior(hoy, n):
    """v3.9: el día `n` (1–31) del mes anterior a `hoy`, como datetime.date; si ese mes no tiene ese día, su último día
    (30 → 28 o 29 en febrero; 31 = siempre el último día)."""
    base = _como_fecha(hoy).date()
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise ErrorPlantilla("{dia_mes_anterior:N} necesita el número del día (de 1 a 31)")
    if not 1 <= n <= 31:
        raise ErrorPlantilla("{dia_mes_anterior:N}: el día debe estar entre 1 y 31 (llegó %s)" % n)
    fin = base.replace(day=1) - datetime.timedelta(days=1)
    return fin.replace(day=min(n, fin.day))


def _fecha_nombrada(nombre, ahora, corte=CORTE_QUINCENA):
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
    if nombre in ("inicio_quincena_anterior", "fin_quincena_anterior"):
        d, h = quincena_anterior(ahora, corte)
        x = d if nombre == "inicio_quincena_anterior" else h
        return datetime.datetime(x.year, x.month, x.day)
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
               formato_defecto=FORMATO_FECHA, fecha=None, reporte=None, desde=None, hasta=None, corte=None):
    """Sustituye las plantillas de `texto`.

    - hoy: fecha «de hoy» (inyectable para pruebas); por defecto, la actual.
    - ext / nombre: valores para {ext} y {nombre} (solo en nombres de descarga).
    - fecha: el día de {fecha} («Repetir por días»); por defecto, `hoy`.
    - reporte: (v3.5) el nombre del reporte para {reporte} (una variable propia «reporte» del flujo tiene prioridad).
    - desde / hasta: (v3.9) el periodo de {desde} y {hasta}; por defecto, `fecha` (y si no, `hoy`).  Una variable propia
      del flujo con ese nombre tiene prioridad (reportes de antes).  corte: día de corte de las quincenas (15).
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
            fecha_n = _fecha_nombrada(nombre_var, ahora, corte if corte is not None else CORTE_QUINCENA)
            partes.append(_formatear(fecha_n, resto if resto else formato_defecto))
        elif nombre_var in PERIODO and nombre_var not in variables:
            limite = desde if nombre_var == "desde" else hasta
            if limite is None:
                limite = fecha
            dia = _como_fecha(limite) if limite is not None else ahora
            partes.append(_formatear(dia, resto if resto else formato_defecto))
        elif nombre_var == "fecha":
            dia = _como_fecha(fecha) if fecha is not None else ahora
            partes.append(_formatear(dia, resto if resto else formato_defecto))
        elif nombre_var == DIA_MES_ANTERIOR:              # v3.9: {dia_mes_anterior:15[:formato]}
            cantidad, _, formato = resto.partition(":")
            if not cantidad.strip().isdigit():
                raise ErrorPlantilla("{dia_mes_anterior:N} necesita el número del día, por ejemplo "
                                     "{dia_mes_anterior:15}: {%s}" % cont)
            d = dia_del_mes_anterior(ahora, int(cantidad.strip()))
            partes.append(_formatear(datetime.datetime(d.year, d.month, d.day), formato if formato else formato_defecto))
        elif nombre_var == "dias":
            cantidad, _, formato = resto.partition(":")
            try:
                n = int(cantidad.strip())
            except ValueError:
                raise ErrorPlantilla("{dias:N} necesita un número entero, por ejemplo {dias:-7}: {%s}" % cont)
            fecha_n = ahora + datetime.timedelta(days=n)
            partes.append(_formatear(fecha_n, formato if formato else formato_defecto))
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
    ("fin_mes_anterior", "fin del mes anterior"), ("inicio_quincena_anterior", "inicio de la quincena anterior"),
    ("fin_quincena_anterior", "fin de la quincena anterior"), ("inicio_anio", "1 de enero"),
    ("fecha", "el día que se descarga"), ("desde", "inicio del periodo"), ("hasta", "fin del periodo"),
)
_NOMBRES_RELATIVAS = dict(RELATIVAS)
# Fechas escritas tal cual que se reconocen como fecha fija (sin «aaaammdd»: un número de 8 cifras puede ser otra cosa;
# dd/mm antes que mm/dd: «10/11/2026» es el 10 de noviembre).
_FORMATOS_FIJA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%y", "%m/%d/%Y", "%d %b %Y")
_RX_RELATIVA = re.compile(r"^\{(%s|fecha|desde|hasta)(?::([^{}]+))?\}$" % "|".join(FECHAS))
_RX_DIAS = re.compile(r"^\{dias:\s*([+-]?\d+)\s*(?::([^{}]+))?\}$")
_RX_DIA_MES = re.compile(r"^\{dia_mes_anterior:\s*(\d{1,2})\s*(?::([^{}]+))?\}$")


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
    m = _RX_DIA_MES.match(s)
    if m and 1 <= int(m.group(1)) <= 31 and (m.group(2) is None or _formato_valido(m.group(2))):
        return {"modo": "relativa", "que": DIA_MES_ANTERIOR, "n": int(m.group(1)), "formato": m.group(2)}
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
        if que == DIA_MES_ANTERIOR:
            try:
                n = int(a.get("n"))
            except (TypeError, ValueError):
                raise ErrorPlantilla("«Día N del mes anterior» necesita un número")
            if not 1 <= n <= 31:
                raise ErrorPlantilla("«Día N del mes anterior»: el día debe estar entre 1 y 31")
            return "{%s:%d%s}" % (DIA_MES_ANTERIOR, n, (":" + formato) if formato else "")
        if que not in FECHAS and que not in ("fecha",) + PERIODO:
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
    elif a["que"] == DIA_MES_ANTERIOR:
        palabras = "día %d del mes anterior" % a["n"]
    else:
        palabras = _NOMBRES_RELATIVAS.get(a["que"], a["que"])
    return "%s · %s" % (palabras, vista)


# --- v3.9: «Descargar en esta fecha cada mes» ---------------------------------------------------------------------
def plantilla_cada_mes(dia, formato=None):
    """La fecha elegida en el calendario (datetime.date) → esa fecha DEL MES ANTERIOR al día en que se ejecute: el día
    1 → {inicio_mes_anterior}; el último día de su mes (31/10, 30/11, 28/02…) → {fin_mes_anterior}; otro día N →
    {dia_mes_anterior:N} (si el mes anterior no tiene ese día, su último día).  Con el formato del campo."""
    fin = calendar.monthrange(dia.year, dia.month)[1]
    if dia.day == 1:
        a = {"modo": "relativa", "que": "inicio_mes_anterior", "n": None, "formato": formato}
    elif dia.day == fin:
        a = {"modo": "relativa", "que": "fin_mes_anterior", "n": None, "formato": formato}
    else:
        a = {"modo": "relativa", "que": DIA_MES_ANTERIOR, "n": dia.day, "formato": formato}
    return plantilla_fecha(a)


def misma_fecha(a, b):
    """True si dos valores guardados son la misma fecha («{ayer}» = «{ayer:%d/%m/%Y}»: el formato por defecto escrito o
    no)."""
    x, y = analizar_fecha(a), analizar_fecha(b)
    if x["modo"] != y["modo"]:
        return False
    if x["modo"] in ("fija", "relativa"):
        def clave(z):
            return z.get("fecha"), z.get("que"), z.get("n"), z.get("formato") or FORMATO_FECHA
        return clave(x) == clave(y)
    return str(a or "") == str(b or "")
