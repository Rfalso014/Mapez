"""v3.9 «¿De qué fecha?» con un solo calendario: la fecha roja es «Desde» y la azul «Hasta».  No importa playwright.

- `campos_de_fecha(flujo)`: los campos de fecha del reporte (pasos «Escribir» una fecha y listas «por fecha» / «la más
  reciente»), cada uno con su papel: «desde» (recibe la fecha roja), «hasta» (la azul), «unica» (el reporte solo tiene
  un campo de fecha: solo hay fecha roja) u «otra» (un tercer campo, que aquí no se toca).  El papel sale del nombre del
  campo (desde / from / inicio… y hasta / to / fin…) y, si el nombre no lo dice, del orden de los pasos (`por_orden`).
- `aplicar_eleccion(flujo, desde, hasta, …)`: escribe las fechas elegidas en los pasos, cada una con el formato de su
  campo: como fechas fijas o, con «Descargar en esta fecha cada mes», como esa fecha del mes anterior al día en que se
  ejecute ({inicio_mes_anterior}, {dia_mes_anterior:15}, {fin_mes_anterior}).  Si el reporte se repite (por días,
  meses o quincenas) las fechas elegidas son las de la repetición (los campos siguen con {desde} / {hasta} / {fecha}).
- `programacion_cada_mes(hora, conf)` / `es_horario_cada_mes(prog, conf)` / `describir_cada_mes(prog)`: el horario del
  día 1 de cada mes (con «Repetir por quincenas»: el día 1 y el día de corte) que se crea con la casilla.
"""

import datetime
import re

from . import filtros as mod_filtros
from . import flujo as mod_flujo
from . import horario
from . import plantillas

HORA_DEFECTO = "07:00"
ROLES = ("desde", "hasta", "unica", "otra")

# Palabras de los nombres de campo (también «DateFrom» / «DateTo»: se separan las palabras pegadas)
_RX_DESDE = re.compile(r"\b(desde|inicio|inicial|from|start|begin|ini)\b", re.IGNORECASE)
_RX_HASTA = re.compile(r"\b(hasta|fin|final|to|end|until|termino|término)\b", re.IGNORECASE)


class ErrorFechas(ValueError):
    pass


def _palabras(paso):
    t = " ".join([paso.objetivo or "", paso.filtro or ""] + list(paso.selectores[:1]))
    t = re.sub(r"([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])", r"\1 \2", t)          # «DateFrom» → «Date From»
    return re.sub(r"[\W_]+", " ", t)


def _es(rx, otro, texto):
    return bool(rx.search(texto)) and not otro.search(texto)


def campos_de_fecha(flujo):
    """([campos], por_orden).  Cada campo: {paso, nombre, valor, lista, estrategia, formato, rol}.  `por_orden` = True si
    el «Desde» y el «Hasta» se decidieron por el orden de los pasos (el nombre no lo decía): la interfaz deja
    cambiarlos."""
    campos = []
    for i, p in mod_filtros.pasos_filtro(flujo):
        lista = p.tipo == "elegir_opcion" and (p.estrategia or "fija") in ("por_fecha", "mas_reciente")
        if p.tipo != "escribir" and not lista:
            continue
        campos.append({"paso": i, "nombre": p.filtro or p.objetivo or "Fecha", "valor": p.valor or "", "lista": lista,
                       "estrategia": (p.estrategia or "fija") if lista else "",
                       "formato": plantillas.formato_de_fecha(p.valor) or "", "rol": "otra"})
    por_orden = False
    if len(campos) == 1:
        campos[0]["rol"] = "unica"
    elif campos:
        textos = {c["paso"]: _palabras(flujo.pasos[c["paso"]]) for c in campos}
        ini = next((c for c in campos if _es(_RX_DESDE, _RX_HASTA, textos[c["paso"]])), None)
        fin = next((c for c in campos if c is not ini and _es(_RX_HASTA, _RX_DESDE, textos[c["paso"]])), None)
        por_orden = ini is None or fin is None
        if ini is None:
            ini = next(c for c in campos if c is not fin)
        if fin is None:
            fin = next(c for c in campos if c is not ini)
        ini["rol"], fin["rol"] = "desde", "hasta"
    return campos, por_orden


def _dia(x, que):
    if x in (None, ""):
        return None
    if isinstance(x, datetime.datetime):
        return x.date()
    if isinstance(x, datetime.date):
        return x
    try:
        return datetime.date.fromisoformat(str(x))
    except ValueError:
        raise ErrorFechas("%s no es una fecha válida: «%s»" % (que, x)) from None


def aplicar_eleccion(flujo, desde, hasta=None, invertir=False, cada_mes=False, mas_reciente=False, cambiadas=True):
    """Escribe en `flujo` lo elegido en el calendario y devuelve las líneas de lo que cambió ([] = nada cambió).

    - desde / hasta: date o «AAAA-MM-DD» (la fecha roja y la azul; `hasta` vacío = un solo día).
    - invertir: la roja va al campo que se había decidido como «hasta» y al revés.
    - cada_mes: «Descargar en esta fecha cada mes» (la misma fecha del mes anterior, cada vez que se ejecute).
    - mas_reciente: las listas de fechas eligen «la más reciente» (sin fecha).
    - cambiadas: False = el usuario no tocó el calendario: solo se cambia lo que pida `cada_mes` / `mas_reciente`.
    """
    d = _dia(desde, "«Desde»")
    h = _dia(hasta, "«Hasta»")
    if d is None:
        raise ErrorFechas("Elige al menos una fecha en el calendario")
    if h is not None and h < d:
        d, h = h, d
    conf = flujo.opciones.get("repetir_dias")
    if isinstance(conf, dict) and (conf.get("modo") or "no") not in ("no", ""):
        return _aplicar_repetir(flujo, conf, d, h or d, cada_mes, cambiadas)
    campos, _ = campos_de_fecha(flujo)
    if not campos:
        raise ErrorFechas("Este reporte no tiene ningún campo de fecha")
    if cada_mes and h is not None and (d.year, d.month) != (h.year, h.month) and \
            any(c["rol"] in ("desde", "hasta") for c in campos):
        raise ErrorFechas("Para bajarlo cada mes, elige el «Desde» y el «Hasta» dentro del mismo mes")
    lineas = []
    for c in campos:
        rol = c["rol"]
        if invertir:
            rol = {"desde": "hasta", "hasta": "desde"}.get(rol, rol)
        if rol == "otra":
            continue
        dia = d if rol in ("desde", "unica") else (h or d)
        p = flujo.pasos[c["paso"]]
        fmt = c["formato"] or plantillas.FORMATO_FECHA
        if c["lista"] and mas_reciente:
            estrategia, valor = "mas_reciente", ""
        elif cada_mes:
            estrategia, valor = "por_fecha", plantillas.plantilla_cada_mes(dia, fmt)
        elif cambiadas:
            estrategia = "por_fecha"
            valor = plantillas.plantilla_fecha({"modo": "fija", "fecha": dia.isoformat(), "formato": fmt})
        else:
            continue
        if not c["lista"]:
            estrategia = p.estrategia
        if (p.estrategia or "") == (estrategia or "") and plantillas.misma_fecha(p.valor, valor):
            continue
        p.valor = valor
        p.estrategia = estrategia
        lineas.append("paso %d («%s»): %s" % (c["paso"] + 1, c["nombre"],
                                              plantillas.describir_fecha(valor) or "la más reciente"))
    return lineas


def _aplicar_repetir(flujo, conf, d, h, cada_mes, cambiadas):
    """Reporte con «Repetir…»: el rango elegido es el de la repetición (un archivo por día, mes o quincena)."""
    nuevo = dict(conf)
    if conf.get("modo") in mod_flujo.MODOS_PERIODO:
        if cada_mes:
            nuevo["rango"] = "anterior"
        elif cambiadas:
            nuevo.update(rango="fijo", desde=d.isoformat(), hasta=h.isoformat())
    else:
        if cada_mes:
            raise ErrorFechas("Este reporte se repite por días: para bajarlo cada mes, en el editor elige «Repetir: por "
                              "meses»")
        if cambiadas:
            nuevo.update(modo="fijo", desde=d.isoformat(), hasta=h.isoformat())
    if nuevo == conf:
        return []
    try:
        mod_flujo.validar_repetir_dias(nuevo)
    except mod_flujo.ErrorFlujo as e:
        raise ErrorFechas("Repetir: %s" % e) from None
    flujo.opciones["repetir_dias"] = nuevo
    return ["repetir: %s" % mod_flujo.describir_repetir_dias(nuevo)]


# ------------------------------------------------------------------ «Descargar en esta fecha cada mes»: el horario
def _reglas(conf, hora):
    if isinstance(conf, dict) and conf.get("modo") == "quincenas":
        return [horario.regla_periodo("quincenas", conf.get("corte") or plantillas.CORTE_QUINCENA,
                                      conf.get("mitades") or "ambas", [hora])]
    return [horario.regla_periodo("meses", horas=[hora])]


def programacion_cada_mes(hora=None, conf=None, ejecucion=None):
    """El horario de «cada mes»: el día 1 a `hora` (con «Repetir por quincenas», también el día de corte), con
    «Avisos y vista» (`ejecucion`; si no, los de una programación nueva)."""
    try:
        p = {"reglas": _reglas(conf, horario._hora(hora or HORA_DEFECTO)), "inicio": "", "fin": "",
             "ejecucion": ejecucion or dict(horario.EJECUCION_DEFECTO)}
        return horario.normalizar(p)
    except horario.ErrorHorario as e:
        raise ErrorFechas(str(e)) from None


def programacion_mensual(dia=1, hora=None, ejecucion=None):
    """v3.9 «Cada mes: bajar todo e imprimir»: el horario del día `dia` de cada mes a `hora` (día 1..28, para que exista
    en todos los meses)."""
    dia = int(dia or 1)
    if not 1 <= dia <= 28:
        raise ErrorFechas("El día del mes tiene que estar entre 1 y 28 (así existe en todos los meses)")
    try:
        p = {"reglas": [{"tipo": "mensual", "dias_mes": [dia], "meses": list(range(1, 13)),
                         "horas": [horario._hora(hora or HORA_DEFECTO)]}], "inicio": "", "fin": "",
             "ejecucion": ejecucion or dict(horario.EJECUCION_DEFECTO)}
        return horario.normalizar(p)
    except horario.ErrorHorario as e:
        raise ErrorFechas(str(e)) from None


DIAS_SEMANA = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")


def programacion_sencilla(modo, dia=1, hora=None, dia_semana="lun", ejecucion=None):
    """v3.9: los horarios de la ventana «Programar»: «mes» (día N de cada mes), «dia» (todos los días), «semana» (un día
    de la semana).  Devuelve None con «no» (sin programar)."""
    if modo in (None, "", "no"):
        return None
    hora = horario._hora(hora or HORA_DEFECTO)
    ejecucion = ejecucion or dict(horario.EJECUCION_DEFECTO)
    if modo == "mes":
        return programacion_mensual(dia, hora, ejecucion)
    if modo in ("dia", "semana"):
        if modo == "dia":
            dias = list(DIAS_SEMANA)
        else:
            d = str(dia_semana or "lun").lower()[:3]
            if d not in DIAS_SEMANA:
                raise ErrorFechas("Día de la semana no válido: %s" % dia_semana)
            dias = [d]
        try:
            return horario.normalizar({"reglas": [{"tipo": "semanal", "dias": dias, "horas": [hora]}],
                                       "inicio": "", "fin": "", "ejecucion": ejecucion})
        except horario.ErrorHorario as e:
            raise ErrorFechas(str(e)) from None
    raise ErrorFechas("Cuándo no válido: %s" % modo)


def como_esta_programado(prog):
    """v3.9: lee un horario y dice si es uno de los sencillos de la ventana: {modo, dia, hora, dia_semana, otro}."""
    vacio = {"modo": "no", "dia": 1, "hora": HORA_DEFECTO, "dia_semana": "lun", "otro": ""}
    if not prog or not (prog.get("reglas") or []):
        return vacio
    dia = dia_del_mes_de(prog)
    if dia is not None:
        return dict(vacio, modo="mes", dia=dia, hora=hora_de(prog))
    try:
        p = horario.normalizar(prog)
    except horario.ErrorHorario:
        return dict(vacio, otro="programación no válida")
    reglas = p["reglas"]
    if len(reglas) == 1 and reglas[0]["tipo"] == "semanal" and len(reglas[0]["horas"]) == 1 \
            and not p["inicio"] and not p["fin"]:
        dias = reglas[0]["dias"]
        if len(dias) == 7:
            return dict(vacio, modo="dia", hora=reglas[0]["horas"][0])
        if len(dias) == 1:
            return dict(vacio, modo="semana", dia_semana=dias[0], hora=reglas[0]["horas"][0])
    return dict(vacio, otro=horario.describir(prog))


def texto_cuando(estado):
    """v3.9: «Cada mes, día 1 a las 07:00» / «Cada día a las 07:00» / «Cada semana, los lunes a las 07:00»."""
    if estado.get("otro"):
        return estado["otro"]
    modo, hora = estado.get("modo"), estado.get("hora") or HORA_DEFECTO
    if modo == "mes":
        return "Cada mes, día %d a las %s" % (estado.get("dia") or 1, hora)
    if modo == "dia":
        return "Cada día a las %s" % hora
    if modo == "semana":
        i = DIAS_SEMANA.index(estado.get("dia_semana") or "lun")
        return "Cada semana, los %s a las %s" % (horario.NOMBRES_DIA[i], hora)
    return "Sin programar"


def dia_del_mes_de(prog):
    """El día del mes de un horario «una vez al mes» simple, o None si el horario es otra cosa."""
    try:
        p = horario.normalizar(prog)
    except (horario.ErrorHorario, AttributeError, TypeError):
        return None
    reglas = p.get("reglas") or []
    if len(reglas) != 1 or reglas[0]["tipo"] != "mensual" or p.get("inicio") or p.get("fin"):
        return None
    r = reglas[0]
    if len(r["dias_mes"]) != 1 or len(r["horas"]) != 1 or len(r["meses"]) != 12:
        return None
    return r["dias_mes"][0] if isinstance(r["dias_mes"][0], int) else None


def mes_anterior(hoy=None):
    """(primer día, último día) del mes anterior a `hoy`."""
    hoy = hoy or datetime.date.today()
    fin = datetime.date(hoy.year, hoy.month, 1) - datetime.timedelta(days=1)
    return fin.replace(day=1), fin


def dias_guardados(flujo):
    """v3.9: los días del mes que ya tienen puestos los campos «Desde» y «Hasta» (para ofrecer «los mismos días del mes
    anterior»): (dia_desde, dia_hasta) o None si no se sabe o ya es el mes entero."""
    campos, _ = campos_de_fecha(flujo)
    dias = {}
    for c in campos:
        if c["rol"] not in ("desde", "hasta", "unica"):
            continue
        a = plantillas.analizar_fecha(c["valor"])
        if a["modo"] == "fija":
            try:
                dias[c["rol"]] = datetime.date.fromisoformat(a["fecha"]).day
            except (ValueError, TypeError, KeyError):
                return None
        elif a["modo"] == "relativa" and a.get("que") == plantillas.DIA_MES_ANTERIOR and a.get("n"):
            dias[c["rol"]] = int(a["n"])
        elif a["modo"] == "relativa" and a.get("que") == "inicio_mes_anterior":
            dias[c["rol"]] = 1
        elif a["modo"] == "relativa" and a.get("que") == "fin_mes_anterior":
            dias[c["rol"]] = 31
        else:
            return None
    d = dias.get("desde", dias.get("unica"))
    h = dias.get("hasta", dias.get("unica"))
    if d is None or h is None or (d == 1 and h == 31):
        return None
    return d, h


def es_horario_cada_mes(prog, conf=None):
    """True si `prog` es justo el horario de «cada mes» (sea cual sea la hora y los avisos)."""
    try:
        p = horario.normalizar(prog)
    except horario.ErrorHorario:
        return False
    if len(p["reglas"]) != 1 or p["reglas"][0]["tipo"] != "mensual" or p["inicio"] or p["fin"]:
        return False
    r = p["reglas"][0]
    esperada = _reglas(conf, HORA_DEFECTO)[0]
    return r["dias_mes"] == esperada["dias_mes"] and r["meses"] == esperada["meses"] and len(r["horas"]) == 1


def hora_de(prog):
    try:
        return horario.normalizar(prog)["reglas"][0]["horas"][0]
    except (horario.ErrorHorario, IndexError, KeyError):
        return HORA_DEFECTO


def describir_cada_mes(prog):
    """«Se bajará solo el día 1 de cada mes a las 07:00» (o «los días 1 y 15 de cada mes…»)."""
    p = horario.normalizar(prog)
    r = p["reglas"][0]
    dias = [str(x) for x in r["dias_mes"]]
    que = ("el día %s" % dias[0]) if len(dias) == 1 else "los días %s" % horario.lista_y(dias)
    return "Se bajará solo %s de cada mes a las %s" % (que, horario.lista_y(r["horas"]))
