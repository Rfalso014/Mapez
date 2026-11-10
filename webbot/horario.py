"""v3.4: «Programación completa» — CUÁNDO se ejecuta algo (una vigilancia, un reporte, una Página, un correo…).

Sin playwright ni tkinter: solo datos, para que lo use cualquier parte del bot.  La programación es un dict que se
guarda como JSON:

    {
      "reglas": [
        {"tipo": "semanal", "dias": ["lun", "mar", "mie", "jue", "vie"], "horas": ["09:00", "15:00"]},
        {"tipo": "intervalo", "dias": ["vie"], "cada_min": 120, "desde": "08:00", "hasta": "18:00"},
        {"tipo": "mensual", "dias_mes": [1, 15, "ultimo"], "horas": ["08:00"], "meses": [1, 2, ..., 12]},
        {"tipo": "mensual_semana", "semanas": [1, "ultima"], "dias": ["lun"], "horas": ["08:00"], "meses": [1, ..., 12]}
      ],
      "inicio": "2026-11-01",       (opcional, "" = desde ya)
      "fin": "2026-12-31"           (opcional, "" = sin fin; ese día incluido)
    }

- Sin reglas = solo a mano («Revisar ahora» / «Ejecutar»).
- `semanal`: esos días de la semana, a esas horas (varias).  Para «horas distintas según el día» se ponen varias reglas.
- `intervalo`: esos días, cada `cada_min` minutos (mínimo 15) de `desde` a `hasta` (las dos incluidas).
- `mensual`: esos días del mes (1–31 y/o "ultimo" = el último día del mes), a esas horas, en esos `meses`.
- `mensual_semana`: el primer/segundo/tercer/cuarto/último (`semanas`: 1–4 y/o "ultima") <día> (`dias`) del mes.
Días de la semana: "lun" "mar" "mie" "jue" "vie" "sab" "dom".  Horas: "HH:MM" (24 h).  Todo en hora LOCAL (sin
zonas horarias: igual que el Programador de tareas de Windows, que la respeta en los cambios de horario de verano).

v3.7 «Avisos y vista» (opcional, junto a `reglas`): `"ejecucion": {"avisar_antes": 5, "avisar_inicio": true,
"avisar_fin": true, "en_vivo": false, "ventanita": true}` — avisar N minutos antes (0, 1, 5, 10, 15 o 30), al empezar y al
terminar; ver la ejecución en vivo (navegador visible) o en segundo plano; la ventanita con la barra de progreso.  Las
programaciones sin `ejecucion` (las de antes) se quedan sin ella y funcionan como siempre (`ejecucion(prog)` = None).

Funciones: `normalizar` (comprueba y deja la forma canónica; error = `ErrorHorario`), `vacia`, `es_vacia`,
`desde_antiguo` (frecuencia ''/'horas'/'diaria' de la 3.0–3.3), `de_vigilancia`, `describir` (texto en español),
`proximas` (las próximas N fechas), `texto_fecha`, `avisos`, `vista` (todo junto para la interfaz), `a_json`/`desde_json`,
`n_disparadores` (cuántos disparadores tendrá la tarea de Windows).
"""

import calendar
import datetime as _dt
import json
import re
import unicodedata

DIAS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")       # índice = datetime.weekday()
NOMBRES_DIA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
PLURAL_DIA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos")
CORTO_DIA = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
NOMBRES_MES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
               "noviembre", "diciembre")
ORDINALES = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", "ultima": "último"}
TIPOS = ("semanal", "intervalo", "mensual", "mensual_semana")
NOMBRES_TIPO = {"semanal": "Días y horas", "intervalo": "Cada N horas en un horario", "mensual": "Mensual: días del mes",
                "mensual_semana": "Mensual: el primer/…/último día de la semana del mes"}
LABORABLES = ["lun", "mar", "mie", "jue", "vie"]
FIN_DE_SEMANA = ["sab", "dom"]
MIN_INTERVALO = 15             # minutos
MAX_INTERVALO = 23 * 60
MAX_REGLAS = 20
MAX_HORAS = 24
MAX_DISPARADORES = 48          # límite del Programador de tareas de Windows
DIAS_BUSQUEDA = 800            # hasta dónde se buscan las próximas ejecuciones (p. ej. un 29 de febrero)

_ALIAS_DIA = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
              "lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}


class ErrorHorario(ValueError):
    pass


# v3.7: «Avisos y vista» de lo programado
AVISAR_ANTES = (0, 1, 5, 10, 15, 30)                 # minutos
EJECUCION_DEFECTO = {"avisar_antes": 5, "avisar_inicio": True, "avisar_fin": True, "en_vivo": False, "ventanita": True}
EJECUCION_ANTIGUA = {"avisar_antes": 0, "avisar_inicio": False, "avisar_fin": False, "en_vivo": False,
                     "ventanita": False}             # como se ejecutaba antes de la 3.7 (sin avisos, oculto)


def _si_no(x, defecto):
    if x is None:
        return defecto
    if isinstance(x, str):
        return x.strip().lower() in ("1", "true", "si", "sí", "on", "yes")
    return bool(x)


def _ejecucion(e):
    """Comprueba «Avisos y vista» y lo deja en su forma canónica (lo que falte, como en una programación nueva)."""
    if not isinstance(e, dict):
        raise ErrorHorario("«Avisos y vista» no es válido")
    antes = e.get("avisar_antes", EJECUCION_DEFECTO["avisar_antes"])
    if antes in (None, "", False):
        antes = 0
    try:
        antes = int(antes)
    except (TypeError, ValueError):
        raise ErrorHorario("«Avisarme antes»: elige No, 1, 5, 10, 15 o 30 minutos")
    if antes not in AVISAR_ANTES:
        raise ErrorHorario("«Avisarme antes»: elige No, 1, 5, 10, 15 o 30 minutos (llegó %s)" % antes)
    return {"avisar_antes": antes,
            "avisar_inicio": _si_no(e.get("avisar_inicio"), EJECUCION_DEFECTO["avisar_inicio"]),
            "avisar_fin": _si_no(e.get("avisar_fin"), EJECUCION_DEFECTO["avisar_fin"]),
            "en_vivo": _si_no(e.get("en_vivo"), EJECUCION_DEFECTO["en_vivo"]),
            "ventanita": _si_no(e.get("ventanita"), EJECUCION_DEFECTO["ventanita"])}


def ejecucion(prog):
    """«Avisos y vista» de una programación (dict canónico) o None si no tiene (programaciones de antes de la 3.7)."""
    if not isinstance(prog, dict) or prog.get("ejecucion") in (None, ""):
        return None
    try:
        return _ejecucion(prog["ejecucion"])
    except ErrorHorario:
        return None


def con_en_vivo(prog, en_vivo):
    """La programación con «Ver la ejecución en vivo» cambiado.  Si no tenía «Avisos y vista» (de antes de la 3.7), solo
    se añade eso: lo demás sigue como antes (sin avisos ni ventanita)."""
    p = normalizar(prog)
    e = dict(p.get("ejecucion") or EJECUCION_ANTIGUA)
    e["en_vivo"] = bool(en_vivo)
    p["ejecucion"] = e
    return p


def describir_ejecucion(e):
    """«Avisa 5 min antes, al empezar y al terminar · en segundo plano · con la ventanita de progreso»."""
    if not e:
        return "sin avisos, en segundo plano (como antes)"
    avisos_ = []
    if e["avisar_antes"]:
        avisos_.append("%d min antes" % e["avisar_antes"])
    if e["avisar_inicio"]:
        avisos_.append("al empezar")
    if e["avisar_fin"]:
        avisos_.append("al terminar")
    partes = ["avisa " + lista_y(avisos_) if avisos_ else "sin avisos",
              "en vivo (navegador visible)" if e["en_vivo"] else "en segundo plano"]
    if e["ventanita"]:
        partes.append("con la ventanita de progreso")
    texto = " · ".join(partes)
    return texto[0].upper() + texto[1:]


def _sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", str(t)) if unicodedata.category(c) != "Mn")


def vacia():
    return {"reglas": [], "inicio": "", "fin": ""}


def _dia(x):
    if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 6:
        return DIAS[x]
    k = _sin_tildes(x).strip().lower()[:3]
    if k in _ALIAS_DIA:
        return DIAS[_ALIAS_DIA[k]]
    raise ErrorHorario("Día de la semana no válido: %s" % x)


def _dias(lista, obligatorio=True):
    if isinstance(lista, str):
        lista = [x for x in re.split(r"[,\s]+", lista) if x]
    vistos = {_dia(x) for x in (lista or [])}
    if obligatorio and not vistos:
        raise ErrorHorario("Elige al menos un día de la semana")
    return [d for d in DIAS if d in vistos]


def _hora(h):
    m = re.fullmatch(r"\s*([01]?\d|2[0-3])[:.]([0-5]\d)\s*", str(h or ""))
    if not m:
        raise ErrorHorario("La hora debe tener el formato HH:MM (24 horas), por ejemplo 07:30 (llegó «%s»)" % (h or ""))
    return "%02d:%s" % (int(m.group(1)), m.group(2))


def _horas(lista):
    if isinstance(lista, str):
        lista = [x for x in re.split(r"[,;\s]+", lista) if x]
    horas = sorted({_hora(h) for h in (lista or [])})
    if not horas:
        raise ErrorHorario("Pon al menos una hora")
    if len(horas) > MAX_HORAS:
        raise ErrorHorario("Demasiadas horas en un mismo horario (máximo %d): usa «Cada N horas»" % MAX_HORAS)
    return horas


def _minutos(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutos):
    return "%02d:%02d" % (minutos // 60, minutos % 60)


def _fecha(texto, que):
    texto = (texto or "").strip() if isinstance(texto, str) else texto
    if not texto:
        return ""
    if isinstance(texto, _dt.date):
        return texto.strftime("%Y-%m-%d")
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", texto) or re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
    if not m:
        raise ErrorHorario("La fecha %s debe ser AAAA-MM-DD (llegó «%s»)" % (que, texto))
    a, b, c = (int(x) for x in m.groups())
    anio, mes, dia = (a, b, c) if a > 31 else (c, b, a)
    try:
        return _dt.date(anio, mes, dia).strftime("%Y-%m-%d")
    except ValueError:
        raise ErrorHorario("La fecha %s no existe: %s" % (que, texto))


def _meses(lista):
    if lista in (None, "", []):
        return list(range(1, 13))
    res = set()
    for x in lista:
        try:
            n = int(x)
        except (TypeError, ValueError):
            k = _sin_tildes(x).strip().lower()[:3]
            n = next((i + 1 for i, nm in enumerate(NOMBRES_MES) if _sin_tildes(nm)[:3] == k), 0)
        if not 1 <= n <= 12:
            raise ErrorHorario("Mes no válido: %s" % x)
        res.add(n)
    return sorted(res)


def _es_ultimo(x):
    return isinstance(x, str) and _sin_tildes(x).strip().lower() in ("ultimo", "ultima", "last", "u")


def _regla(r):
    if not isinstance(r, dict):
        raise ErrorHorario("Horario no válido")
    tipo = (r.get("tipo") or "semanal").strip().lower()
    if tipo not in TIPOS:
        raise ErrorHorario("Tipo de horario no válido: %s" % tipo)
    if tipo == "semanal":
        return {"tipo": tipo, "dias": _dias(r.get("dias")), "horas": _horas(r.get("horas"))}
    if tipo == "intervalo":
        cada = r.get("cada_min")
        if cada in (None, "") and r.get("cada_horas") not in (None, ""):
            try:
                cada = int(float(r.get("cada_horas")) * 60)
            except (TypeError, ValueError):
                raise ErrorHorario("Indica cada cuántas horas")
        try:
            cada = int(cada)
        except (TypeError, ValueError):
            raise ErrorHorario("Indica cada cuántos minutos u horas")
        if not MIN_INTERVALO <= cada <= MAX_INTERVALO:
            raise ErrorHorario("«Cada»: entre %d minutos y %d horas" % (MIN_INTERVALO, MAX_INTERVALO // 60))
        desde = _hora(r.get("desde") or "00:00")
        hasta = _hora(r.get("hasta") or "23:59")
        if _minutos(hasta) < _minutos(desde):
            raise ErrorHorario("En «cada N horas», la hora «hasta» (%s) debe ser después de «desde» (%s)" % (hasta, desde))
        return {"tipo": tipo, "dias": _dias(r.get("dias")), "cada_min": cada, "desde": desde, "hasta": hasta}
    if tipo == "mensual":
        dias = set()
        ultimo = False
        crudos = r.get("dias_mes")
        if isinstance(crudos, (str, int)):
            crudos = [x for x in re.split(r"[,;\s]+", str(crudos)) if x]
        for x in crudos or []:
            if _es_ultimo(x):
                ultimo = True
                continue
            try:
                n = int(x)
            except (TypeError, ValueError):
                raise ErrorHorario("Día del mes no válido: %s" % x)
            if not 1 <= n <= 31:
                raise ErrorHorario("Día del mes no válido: %s (de 1 a 31)" % x)
            dias.add(n)
        if not dias and not ultimo:
            raise ErrorHorario("Elige al menos un día del mes (o «último día del mes»)")
        return {"tipo": tipo, "dias_mes": sorted(dias) + (["ultimo"] if ultimo else []), "horas": _horas(r.get("horas")),
                "meses": _meses(r.get("meses"))}
    # mensual_semana
    semanas = set()
    ultima = False
    crudas = r.get("semanas")
    if crudas in (None, "") and r.get("semana") not in (None, ""):
        crudas = [r.get("semana")]
    for x in crudas or []:
        if _es_ultimo(x):
            ultima = True
            continue
        try:
            n = int(x)
        except (TypeError, ValueError):
            raise ErrorHorario("Semana del mes no válida: %s" % x)
        if not 1 <= n <= 4:
            raise ErrorHorario("Semana del mes no válida: %s (primera a cuarta, o la última)" % x)
        semanas.add(n)
    if not semanas and not ultima:
        raise ErrorHorario("Elige qué semana del mes (primer, segundo… o último)")
    dias = r.get("dias")
    if dias in (None, "", []) and r.get("dia_semana") not in (None, ""):
        dias = [r.get("dia_semana")]
    return {"tipo": tipo, "semanas": sorted(semanas) + (["ultima"] if ultima else []), "dias": _dias(dias),
            "horas": _horas(r.get("horas")), "meses": _meses(r.get("meses"))}


def desde_json(texto):
    """Lee la programación guardada (texto JSON) → dict normalizado; texto vacío → None (no hay)."""
    if texto in (None, ""):
        return None
    if isinstance(texto, dict):
        return normalizar(texto)
    try:
        return normalizar(json.loads(texto))
    except ValueError as e:
        if isinstance(e, ErrorHorario):
            raise
        raise ErrorHorario("La programación guardada no se puede leer")


def a_json(prog):
    return json.dumps(normalizar(prog), ensure_ascii=False, sort_keys=True)


def normalizar(prog):
    """Comprueba la programación (dict o texto JSON) y la devuelve en su forma canónica (días y horas ordenados, sin
    repetidos, `meses` completos).  `None` o "" = vacía (solo a mano).  Error: `ErrorHorario` con el motivo en español."""
    if prog in (None, ""):
        return vacia()
    if isinstance(prog, str):
        try:
            prog = json.loads(prog)
        except ValueError:
            raise ErrorHorario("La programación no es válida")
    if not isinstance(prog, dict):
        raise ErrorHorario("La programación no es válida")
    reglas = prog.get("reglas") or []
    if not isinstance(reglas, list):
        raise ErrorHorario("La programación no es válida (reglas)")
    if len(reglas) > MAX_REGLAS:
        raise ErrorHorario("Demasiados horarios (máximo %d)" % MAX_REGLAS)
    res = {"reglas": [], "inicio": _fecha(prog.get("inicio"), "de inicio"), "fin": _fecha(prog.get("fin"), "de fin")}
    for i, r in enumerate(reglas):
        try:
            res["reglas"].append(_regla(r))
        except ErrorHorario as e:
            raise ErrorHorario(("Horario %d: %s" % (i + 1, e)) if len(reglas) > 1 else str(e))
    if res["inicio"] and res["fin"] and res["fin"] < res["inicio"]:
        raise ErrorHorario("La fecha de fin es anterior a la de inicio")
    if prog.get("ejecucion") not in (None, ""):          # v3.7: «Avisos y vista» (solo si lo tiene)
        res["ejecucion"] = _ejecucion(prog["ejecucion"])
        antes = res["ejecucion"]["avisar_antes"]
        for r in res["reglas"]:
            if antes and r["tipo"] == "intervalo" and r["cada_min"] <= antes:
                raise ErrorHorario("«Avisarme antes» (%d min) tiene que ser menos que «cada» (%s): si no, el aviso de la "
                                   "siguiente se cruzaría con la anterior" % (antes, describir_cada(r["cada_min"])))
    n = n_disparadores(res)
    if n > MAX_DISPARADORES:
        raise ErrorHorario("Demasiadas horas en total (%d): el Programador de tareas de Windows admite %d. Usa «Cada N "
                           "horas en un horario»." % (n, MAX_DISPARADORES))
    return res


def es_vacia(prog):
    try:
        return not normalizar(prog)["reglas"]
    except ErrorHorario:
        return True


def n_disparadores(prog):
    """Cuántos disparadores tendrá la tarea de Windows (uno por hora de cada regla; uno por regla «cada N horas»)."""
    return sum(1 if r["tipo"] == "intervalo" else len(r["horas"]) for r in prog.get("reglas") or [])


def desde_antiguo(frecuencia, cada_horas=None, hora="", dias=None):
    """La frecuencia de la 3.0–3.3 → programación.  Vigilancias: '' (solo a mano), 'horas' (cada N horas, todo el día),
    'diaria' (cada día a la hora).  Tareas: DIARIA, SEMANAL (+ `dias` MON…) y HORAS (cada N horas desde `hora`)."""
    f = (frecuencia or "").strip().lower()
    if f in ("", "nunca", "manual"):
        return vacia()
    if f in ("horas", "hourly", "cada_horas"):
        try:
            n = int(cada_horas or 0)
        except (TypeError, ValueError):
            n = 0
        n = min(max(n, 1), 23)
        desde = _hora(hora) if hora else "00:00"
        return normalizar({"reglas": [{"tipo": "intervalo", "dias": list(DIAS), "cada_min": n * 60, "desde": desde,
                                       "hasta": "23:59"}]})
    if f in ("diaria", "daily", "diario"):
        return normalizar({"reglas": [{"tipo": "semanal", "dias": list(DIAS), "horas": [hora or "07:00"]}]})
    if f in ("semanal", "weekly"):
        return normalizar({"reglas": [{"tipo": "semanal", "dias": list(dias or LABORABLES), "horas": [hora or "07:00"]}]})
    raise ErrorHorario("Frecuencia no válida: %s" % frecuencia)


def de_vigilancia(v):
    """La programación de una vigilancia: la de la columna `programacion` (3.4) o, si no tiene, la que sale de su
    frecuencia antigua."""
    texto = (v or {}).get("programacion")
    if isinstance(texto, dict):
        return normalizar(texto)
    if texto:
        try:
            return desde_json(texto)
        except ErrorHorario:
            pass
    try:
        return desde_antiguo((v or {}).get("frecuencia"), (v or {}).get("cada_horas"), (v or {}).get("hora") or "")
    except ErrorHorario:
        return vacia()


# ------------------------------------------------------------------------------------------- texto en español
def lista_y(cosas):
    cosas = [str(c) for c in cosas]
    if not cosas:
        return ""
    if len(cosas) == 1:
        return cosas[0]
    return ", ".join(cosas[:-1]) + " y " + cosas[-1]


def describir_dias(dias):
    idx = [DIAS.index(d) for d in dias]
    if len(idx) == 7:
        return "todos los días"
    if dias == LABORABLES:
        return "de lunes a viernes"
    if dias == FIN_DE_SEMANA:
        return "los fines de semana"
    if len(idx) >= 3 and idx == list(range(idx[0], idx[-1] + 1)):
        return "de %s a %s" % (NOMBRES_DIA[idx[0]], NOMBRES_DIA[idx[-1]])
    return "los " + lista_y(PLURAL_DIA[i] for i in idx)


def describir_horas(horas):
    if len(horas) == 1:
        return ("a la %s" if horas[0].startswith("01:") else "a las %s") % horas[0]
    return "a las " + lista_y(horas)


def describir_cada(minutos):
    h, m = divmod(int(minutos), 60)
    if h and m:
        return "%d h %d min" % (h, m)
    return ("%d h" % h) if h else ("%d min" % m)


def _de_meses(meses):
    if len(meses) == 12:
        return "de cada mes"
    return "de " + lista_y(NOMBRES_MES[m - 1] for m in meses)


def describir_regla(r):
    t = r["tipo"]
    if t == "semanal":
        return "%s %s" % (describir_dias(r["dias"]), describir_horas(r["horas"]))
    if t == "intervalo":
        todo = r["desde"] == "00:00" and r["hasta"] in ("23:59", "23:45", "23:30", "23:00")
        ventana = "" if todo else " de %s a %s" % (r["desde"], r["hasta"])
        return "%s cada %s%s" % (describir_dias(r["dias"]), describir_cada(r["cada_min"]), ventana)
    if t == "mensual":
        nums = [d for d in r["dias_mes"] if d != "ultimo"]
        partes = []
        if nums:
            partes.append(("el día %d" % nums[0]) if len(nums) == 1 else "los días " + lista_y(nums))
        if "ultimo" in r["dias_mes"]:
            partes.append("el último día")
        return "%s %s %s" % (" y ".join(partes), _de_meses(r["meses"]), describir_horas(r["horas"]))
    ords = lista_y(ORDINALES[s] for s in r["semanas"])
    return "el %s %s %s %s" % (ords, lista_y(NOMBRES_DIA[DIAS.index(d)] for d in r["dias"]), _de_meses(r["meses"]),
                               describir_horas(r["horas"]))


def _fecha_es(iso):
    return _dt.datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def describir(prog, vacio="solo a mano"):
    """Texto en español: «de lunes a viernes a las 09:00 y 15:00; los viernes cada 2 h de 08:00 a 18:00»."""
    try:
        p = normalizar(prog)
    except ErrorHorario as e:
        return "programación no válida: %s" % e
    if not p["reglas"]:
        return vacio
    texto = "; ".join(describir_regla(r) for r in p["reglas"])
    if p["inicio"] and p["fin"]:
        texto += " (del %s al %s)" % (_fecha_es(p["inicio"]), _fecha_es(p["fin"]))
    elif p["inicio"]:
        texto += " (desde el %s)" % _fecha_es(p["inicio"])
    elif p["fin"]:
        texto += " (hasta el %s)" % _fecha_es(p["fin"])
    return texto


def avisos(prog):
    """Cosas que conviene saber (no son errores): días 29–31 que no existen todos los meses."""
    res = []
    for r in normalizar(prog)["reglas"]:
        if r["tipo"] == "mensual":
            altos = [d for d in r["dias_mes"] if d != "ultimo" and d >= 29]
            if altos:
                res.append("Los meses que no tienen el día %s no se ejecuta ese día; si quieres el final de mes, elige "
                           "«último día del mes»." % lista_y(altos))
    p = normalizar(prog)
    e = ejecucion(p)
    if e and e["avisar_antes"]:
        # v3.7: dos ejecuciones demasiado juntas: mientras la primera avisa y espera, Windows no lanza la segunda
        for i, nombre in enumerate(NOMBRES_DIA):
            minutos = sorted({_minutos(hh) for r in p["reglas"] if r["tipo"] in ("semanal", "intervalo")
                              for hh in horas_del_dia(r, _dt.date(2026, 1, 5) + _dt.timedelta(days=i))})
            juntas = [(a, b) for a, b in zip(minutos, minutos[1:]) if b - a <= e["avisar_antes"]]
            if juntas:
                a, b = juntas[0]
                res.append("Los %s hay dos ejecuciones muy seguidas (%s y %s): con «Avisarme antes» de %d min, la segunda "
                           "no se haría. Elige menos minutos de aviso o sepáralas más." % (
                               PLURAL_DIA[i], _hhmm(a), _hhmm(b), e["avisar_antes"]))
                break
        if any(r["tipo"] in ("mensual", "mensual_semana") and any(_minutos(hh) < e["avisar_antes"] for hh in r["horas"])
               for r in p["reglas"]):
            res.append("En los horarios mensuales que son justo después de medianoche, el aviso llega a las 00:00 (un poco "
                       "menos de %d min antes)." % e["avisar_antes"])
    return res


def siguiente_en(prog, ahora, minutos):
    """v3.7: la ejecución programada que cae entre `ahora` y `ahora + minutos` (+1 min de margen), o None.  Sirve para
    saber a qué hora exacta hay que empezar cuando la tarea de Windows se lanzó antes para avisar."""
    try:
        p = normalizar(prog)
    except ErrorHorario:
        return None
    if not p["reglas"]:
        return None
    base = ahora.replace(second=0, microsecond=0) - _dt.timedelta(minutes=1)
    for cuando in proximas(p, 3, base):
        if ahora - _dt.timedelta(seconds=59) <= cuando <= ahora + _dt.timedelta(minutes=int(minutos) + 1):
            return cuando
    return None


# ------------------------------------------------------------------------------------------- próximas ejecuciones
def _ultimo_dia(fecha):
    return calendar.monthrange(fecha.year, fecha.month)[1]


def horas_del_dia(regla, fecha):
    """Las horas ("HH:MM") en que la regla se ejecuta ese día (lista vacía si no toca)."""
    t = regla["tipo"]
    dia = DIAS[fecha.weekday()]
    if t == "semanal":
        return list(regla["horas"]) if dia in regla["dias"] else []
    if t == "intervalo":
        if dia not in regla["dias"]:
            return []
        ini, fin = _minutos(regla["desde"]), _minutos(regla["hasta"])
        return [_hhmm(m) for m in range(ini, fin + 1, int(regla["cada_min"]))]
    if fecha.month not in regla["meses"]:
        return []
    ultimo = _ultimo_dia(fecha)
    if t == "mensual":
        toca = fecha.day in regla["dias_mes"] or ("ultimo" in regla["dias_mes"] and fecha.day == ultimo)
        return list(regla["horas"]) if toca else []
    if dia not in regla["dias"]:
        return []
    semana = (fecha.day - 1) // 7 + 1
    toca = semana in regla["semanas"] or ("ultima" in regla["semanas"] and fecha.day + 7 > ultimo)
    return list(regla["horas"]) if toca else []


def proximas(prog, n=5, ahora=None):
    """Las próximas `n` ejecuciones (datetime en hora local, sin zona horaria) DESPUÉS de `ahora`."""
    p = normalizar(prog)
    if not p["reglas"] or n <= 0:
        return []
    ahora = (ahora or _dt.datetime.now()).replace(second=0, microsecond=0)
    dia = ahora.date()
    if p["inicio"]:
        dia = max(dia, _dt.datetime.strptime(p["inicio"], "%Y-%m-%d").date())
    limite = ahora.date() + _dt.timedelta(days=DIAS_BUSQUEDA)
    if p["fin"]:
        limite = min(limite, _dt.datetime.strptime(p["fin"], "%Y-%m-%d").date())
    res = []
    while dia <= limite and len(res) < n:
        horas = sorted({h for r in p["reglas"] for h in horas_del_dia(r, dia)})
        for hh in horas:
            cuando = _dt.datetime.combine(dia, _dt.time(*map(int, hh.split(":"))))
            if cuando > ahora:
                res.append(cuando)
        dia += _dt.timedelta(days=1)
    return res[:n]


def texto_fecha(cuando, ahora=None):
    """«hoy 15:00», «mañana 08:00», «viernes 31/10/2026 08:00»."""
    ahora = ahora or _dt.datetime.now()
    hh = cuando.strftime("%H:%M")
    if cuando.date() == ahora.date():
        return "hoy " + hh
    if cuando.date() == ahora.date() + _dt.timedelta(days=1):
        return "mañana " + hh
    return "%s %s %s" % (NOMBRES_DIA[cuando.weekday()], cuando.strftime("%d/%m/%Y"), hh)


def vista(prog, n=5, ahora=None, vacio="solo a mano"):
    """Todo lo que muestra la interfaz: {valida, programacion, descripcion, proximas [{fecha, texto}], avisos,
    disparadores} o {valida: False, error}."""
    try:
        p = normalizar(prog)
    except ErrorHorario as e:
        return {"valida": False, "error": str(e)}
    ahora = ahora or _dt.datetime.now()
    return {"valida": True, "programacion": p, "vacia": not p["reglas"], "descripcion": describir(p, vacio),
            "proximas": [{"fecha": c.strftime("%Y-%m-%dT%H:%M"), "texto": texto_fecha(c, ahora)}
                         for c in proximas(p, n, ahora)],
            "avisos": avisos(p), "disparadores": n_disparadores(p), "ejecucion": ejecucion(p),
            "ejecucion_texto": describir_ejecucion(ejecucion(p))}
