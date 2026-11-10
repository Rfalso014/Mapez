"""Programador de tareas de Windows (schtasks).

Las funciones `construir_*` solo CONSTRUYEN el comando (como lista de argumentos);
no ejecutan nada.  `crear` y `borrar` llaman de verdad a schtasks y exigen
`confirmado=True` (la ventana lo pasa solo después de que el usuario acepte).
La tarea se ejecuta con tu usuario y solo si tienes la sesión de Windows iniciada
(así puede usar tus contraseñas guardadas y el perfil del navegador).
"""

import os
import re
import subprocess
import sys

CARPETA_TAREAS = "BotWeb"
DIAS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
DIAS_ES = {"MON": "lunes", "TUE": "martes", "WED": "miércoles", "THU": "jueves",
           "FRI": "viernes", "SAT": "sábado", "SUN": "domingo"}
MAX_TR = 261  # límite de schtasks para /TR


class ErrorProgramador(ValueError):
    pass


def nombre_tarea(nombre):
    """Nombre completo de la tarea: «BotWeb\\<nombre limpio>»."""
    limpio = re.sub(r'[\\/:*?"<>|]+', "_", (nombre or "").strip()).strip(" .")
    if not limpio:
        raise ErrorProgramador("Escribe un nombre para la tarea")
    return "%s\\%s" % (CARPETA_TAREAS, limpio)


def _validar_hora(hora):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (hora or "").strip())
    if not m:
        raise ErrorProgramador("La hora debe tener el formato HH:MM (24 horas), por ejemplo 07:30")
    return "%02d:%s" % (int(m.group(1)), m.group(2))


def ejecutable_python(sin_consola=True):
    """pythonw.exe (sin ventana de consola) junto al python actual, si existe."""
    exe = sys.executable
    if sin_consola:
        carpeta, nombre = os.path.split(exe)
        if nombre.lower() == "python.exe":
            candidato = os.path.join(carpeta, "pythonw.exe")
            if os.path.exists(candidato):
                return candidato
    return exe


def _ruta_flujo_en_comando(ruta):
    """Una ruta absoluta; si el flujo está en la carpeta flujos/ del proyecto, solo su nombre
    (bot.py lo busca ahí) para que el comando no supere el límite de longitud del Programador."""
    ruta = os.path.abspath(ruta)
    from . import RAIZ
    if os.path.dirname(ruta).lower() == os.path.join(RAIZ, "flujos").lower():
        return os.path.splitext(os.path.basename(ruta))[0]
    return ruta


def comando_bot(ruta_bot, ruta_flujo=None, python=None, oculto=True, variables=None, todos=False,
                ids=None, reportes=None, db=None, vigilar=False, pagina_id=None, favorito=None, vigilancia_id=None,
                correo_id=None, correos=False, aviso_antes=0, avisar_inicio=False, avisar_fin=False, ventanita=False):
    """Línea que ejecutará la tarea programada (valor de /TR).

    - `ids`: reportes guardados en la aplicación, por número (`--id N`; no cambia si se renombran).
    - `reportes`: reportes guardados, por nombre (`--reporte "Nombre"`).
    - `todos=True`: todos los reportes guardados (`--todos`).
    - `ruta_flujo`: un archivo de flujo (texto) o varios (lista), por compatibilidad (`--flujo`).
    - `db`: base de datos distinta de la de por defecto (`--db`).
    - `vigilar=True` (v3.0): en vez de ejecutar, revisa los filtros vigilados de esos reportes (`--vigilar`).
    - `pagina_id` (v3.2): una Página por su número (`--pagina-id N`), con `favorito` (`--favorito "Nombre"`).
    - `vigilancia_id` (v3.3): revisa solo esa vigilancia (`--vigilancia-id N --vigilar`).
    - `correo_id` (v3.4): revisa esa búsqueda de correo (`--correo-id N`); `correos=True`: todas las activas
      (`--correos`).
    - v3.7 «Avisos y vista»: `aviso_antes` (`--aviso-antes N`: avisa y espera N minutos antes de empezar; la tarea se
      lanza N minutos antes), `avisar_inicio` / `avisar_fin` (`--avisar-inicio` / `--avisar-fin`) y `ventanita`
      (`--ventanita`: la ventanita con la barra de progreso).  Sin ellos, el comando es el de siempre.
    Si hay más de un reporte, se ejecutan uno tras otro (lote)."""
    avisos = _argumentos_aviso(aviso_antes, avisar_inicio, avisar_fin, ventanita)
    python = python or ejecutable_python()
    partes = ['"%s"' % python, '"%s"' % os.path.abspath(ruta_bot)]
    if db:
        partes += ["--db", '"%s"' % os.path.abspath(db)]
    if correo_id is not None or correos:
        partes += ["--correo-id", str(int(correo_id))] if correo_id is not None else ["--correos"]
        return " ".join(partes + ["--oculto" if oculto else "--visible"] + avisos)
    if vigilancia_id is not None:
        partes += ["--vigilancia-id", str(int(vigilancia_id))]
        vigilar = True
    elif pagina_id is not None:
        partes += ["--pagina-id", str(int(pagina_id))]
        if favorito:
            if '"' in favorito:
                raise ErrorProgramador("El nombre del favorito no puede llevar comillas dobles: %s" % favorito)
            partes += ["--favorito", '"%s"' % favorito]
    elif todos:
        partes.append("--todos")
    else:
        rutas = [ruta_flujo] if isinstance(ruta_flujo, (str, os.PathLike)) else list(ruta_flujo or [])
        ids = [int(i) for i in (ids or [])]
        reportes = [str(n) for n in (reportes or [])]
        if not rutas and not ids and not reportes:
            raise ErrorProgramador("Elige al menos un reporte para programar")
        for i in ids:
            partes += ["--id", str(i)]
        for n in reportes:
            if '"' in n:
                raise ErrorProgramador("El nombre del reporte no puede llevar comillas dobles: %s" % n)
            partes += ["--reporte", '"%s"' % n]
        for r in rutas:
            unico = len(rutas) == 1 and not ids and not reportes
            partes += ["--flujo", '"%s"' % (os.path.abspath(r) if unico else _ruta_flujo_en_comando(r))]
    partes += (["--vigilar"] if vigilar else ["--sin-ventana"]) + ["--oculto" if oculto else "--visible"]
    for k, v in (variables or {}).items():
        partes += ["--var", '"%s=%s"' % (k, v)]
    return " ".join(partes + avisos)


def _argumentos_aviso(aviso_antes=0, avisar_inicio=False, avisar_fin=False, ventanita=False):
    res = []
    if aviso_antes:
        res += ["--aviso-antes", str(int(aviso_antes))]
    if avisar_inicio:
        res.append("--avisar-inicio")
    if avisar_fin:
        res.append("--avisar-fin")
    if ventanita:
        res.append("--ventanita")
    return res


def opciones_comando(programacion):
    """v3.7: lo que «Avisos y vista» de la programación añade a `comando_bot` (oculto/visible, avisos, ventanita).  Sin
    «Avisos y vista» (programaciones de antes): {} = el comando de siempre (oculto, sin avisos)."""
    from . import horario
    e = horario.ejecucion(programacion)
    if e is None:
        return {}
    return {"oculto": not e["en_vivo"], "aviso_antes": e["avisar_antes"], "avisar_inicio": e["avisar_inicio"],
            "avisar_fin": e["avisar_fin"], "ventanita": e["ventanita"]}


def construir_comando_crear(nombre, ruta_bot, ruta_flujo=None, hora="07:00", frecuencia="DIARIA", dias=None,
                            python=None, oculto=True, variables=None, todos=False, ids=None, reportes=None, db=None,
                            vigilar=False, cada_horas=None, pagina_id=None, favorito=None, vigilancia_id=None):
    """Lista de argumentos de `schtasks /Create …` (no ejecuta nada).

    Qué se ejecuta: `ids` (reportes guardados por número), `reportes` (por nombre), `todos=True`
    (todos los reportes guardados) o `ruta_flujo` (archivo(s) .json, compatibilidad).
    Frecuencia: DIARIA, SEMANAL (`dias`) o (v3.0) HORAS (cada `cada_horas` horas desde `hora`); `vigilar=True` programa
    la revisión de los filtros vigilados (`--vigilar`)."""
    tn = nombre_tarea(nombre)
    st = _validar_hora(hora)
    tr = comando_bot(ruta_bot, ruta_flujo, python=python, oculto=oculto, variables=variables, todos=todos,
                     ids=ids, reportes=reportes, db=db, vigilar=vigilar, pagina_id=pagina_id, favorito=favorito,
                     vigilancia_id=vigilancia_id)
    if len(tr) > MAX_TR:
        raise ErrorProgramador("La ruta del bot es demasiado larga para el Programador de tareas "
                               "(%d caracteres, máximo %d). Mueve el proyecto a una carpeta más corta%s."
                               % (len(tr), MAX_TR, " o programa «Todos los reportes»" if not todos else ""))
    cmd = ["schtasks", "/Create", "/TN", tn, "/TR", tr]
    f = (frecuencia or "").upper()
    if f in ("DIARIA", "DAILY", "DIARIO"):
        cmd += ["/SC", "DAILY"]
    elif f in ("HORAS", "HOURLY", "CADA_HORAS"):
        try:
            n = int(cada_horas)
        except (TypeError, ValueError):
            raise ErrorProgramador("Indica cada cuántas horas (1 a 23)")
        if not 1 <= n <= 23:
            raise ErrorProgramador("Cada cuántas horas: entre 1 y 23")
        cmd += ["/SC", "HOURLY", "/MO", str(n)]
    elif f in ("SEMANAL", "WEEKLY"):
        dias = [d.upper() for d in (dias or [])]
        if not dias:
            raise ErrorProgramador("Elige al menos un día de la semana")
        malos = [d for d in dias if d not in DIAS]
        if malos:
            raise ErrorProgramador("Día no válido: %s (usa %s)" % (", ".join(malos), ",".join(DIAS)))
        ordenados = [d for d in DIAS if d in dias]
        cmd += ["/SC", "WEEKLY", "/D", ",".join(ordenados)]
    else:
        raise ErrorProgramador("Frecuencia no válida: %s (usa DIARIA, SEMANAL o HORAS)" % frecuencia)
    cmd += ["/ST", st, "/F"]
    return cmd


# ============================================================ v3.4: programación completa (XML)
# `schtasks /Create` por línea de comandos solo admite UN disparador por tarea.  Para «lunes a viernes a las 9 y a las
# 15, y los viernes cada 2 h de 8 a 18» se crea la tarea con un XML del Programador de tareas (varios disparadores):
# `schtasks /Create /XML archivo.xml /TN BotWeb\nombre /F`.  El XML va en UTF-16, como lo espera schtasks.
NS_TAREA = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_DIAS_XML = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MESES_XML = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")
LIMITE_EJECUCION = "PT12H"      # si el bot se quedara colgado, Windows lo para a las 12 h (antes: 72 h)


def separar_comando(linea):
    """`"C:\\…\\pythonw.exe" "C:\\…\\bot.py" --id 3 …` → ("C:\\…\\pythonw.exe", '"C:\\…\\bot.py" --id 3 …')."""
    linea = (linea or "").strip()
    if linea.startswith('"'):
        fin = linea.find('"', 1)
        if fin < 0:
            raise ErrorProgramador("Comando no válido: %s" % linea)
        return linea[1:fin], linea[fin + 1:].strip()
    exe, _, args = linea.partition(" ")
    return exe, args.strip()


def usuario_actual():
    """«DOMINIO\\usuario» de la sesión de Windows (la tarea se ejecuta con tu usuario, solo con la sesión iniciada)."""
    usuario = os.environ.get("USERNAME") or ""
    dominio = os.environ.get("USERDOMAIN") or ""
    return ("%s\\%s" % (dominio, usuario)) if dominio and usuario else usuario


def _iso_duracion(minutos):
    minutos = int(minutos)
    if minutos >= 24 * 60:
        return "P1D"
    h, m = divmod(minutos, 60)
    return "PT" + ("%dH" % h if h else "") + ("%dM" % m if m else "") if minutos else "PT0M"


def disparadores(programacion, ahora=None, adelanto=None):
    """La programación (v3.4, `horario`) → lista de disparadores del Programador de tareas, cada uno un dict:
    {tipo: semana|mes|mes_semana, hora "HH:MM", dias [lun…], dias_mes [1…, "ultimo"], semanas [1…, "ultima"],
     meses [1…12], cada_min, duracion_min (repetición, o None), inicio "AAAA-MM-DD", fin "AAAA-MM-DD"|"" , texto}.

    v3.7: `adelanto` (minutos; por defecto el «Avisarme antes» de la programación, 0 si no tiene) adelanta cada
    disparador para que el bot avise antes (`--aviso-antes N`: avisa, espera y empieza a la hora de verdad).  Lleva
    también `hora_real` y, si cambió, `inicio_hora` ("AAAA-MM-DDTHH:MM:SS") y `fin_hora` (el límite, también adelantado)."""
    import datetime as dt
    from . import horario
    p = horario.normalizar(programacion)
    if not p["reglas"]:
        raise ErrorProgramador("No hay nada que programar: elige los días y las horas")
    ahora = ahora or dt.datetime.now()
    inicio = p["inicio"] or ahora.strftime("%Y-%m-%d")
    res = []
    for r in p["reglas"]:
        base = {"inicio": inicio, "fin": p["fin"], "cada_min": None, "duracion_min": None}
        if r["tipo"] == "intervalo":
            # la última ejecución (a la hora «hasta») tiene que caber: duración = hasta − desde + 1 minuto
            dur = horario._minutos(r["hasta"]) - horario._minutos(r["desde"]) + 1
            res.append(dict(base, tipo="semana", hora=r["desde"], dias=list(r["dias"]), cada_min=r["cada_min"],
                            duracion_min=dur, texto=horario.describir_regla(r)))
            continue
        for hh in r["horas"]:
            if r["tipo"] == "semanal":
                d = dict(base, tipo="semana", hora=hh, dias=list(r["dias"]))
                d["texto"] = horario.describir_regla(dict(r, horas=[hh]))
            elif r["tipo"] == "mensual":
                d = dict(base, tipo="mes", hora=hh, dias_mes=list(r["dias_mes"]), meses=list(r["meses"]))
                d["texto"] = horario.describir_regla(dict(r, horas=[hh]))
            else:
                d = dict(base, tipo="mes_semana", hora=hh, semanas=list(r["semanas"]), dias=list(r["dias"]),
                         meses=list(r["meses"]))
                d["texto"] = horario.describir_regla(dict(r, horas=[hh]))
            res.append(d)
    if adelanto is None:
        e = horario.ejecucion(p)
        adelanto = e["avisar_antes"] if e else 0
    return [_adelantar(d, int(adelanto or 0)) for d in res]


def _adelantar(d, minutos):
    """v3.7: el disparador `minutos` antes.  Semanal y «cada N horas»: si cruza la medianoche, a la misma hora del día
    ANTERIOR (los días de la semana y la fecha de inicio retroceden un día).  Mensual (días del mes / «el primer lunes»):
    el día anterior no siempre se puede decir igual («el último día» − 1, «el primer lunes» − 1 puede caer en el mes
    anterior), así que se queda a las 00:00 del mismo día: el aviso llega algo más tarde (el bot espera hasta la hora de
    verdad, ver `horario.siguiente_en`)."""
    import datetime as dt
    from . import horario
    d = dict(d, hora_real=d["hora"])
    if minutos <= 0:
        return d
    real = horario._minutos(d["hora"])
    dia = dt.datetime.strptime(d["inicio"], "%Y-%m-%d")
    if real >= minutos:
        nuevo, cruza = real - minutos, False
    elif d["tipo"] == "semana":
        nuevo, cruza = real - minutos + 24 * 60, True
    else:
        nuevo, cruza = 0, False                       # mensual: se queda en las 00:00 del mismo día
    if cruza:
        d["dias"] = [horario.DIAS[(horario.DIAS.index(x) - 1) % 7] for x in d["dias"]]
        d["dias"] = [x for x in horario.DIAS if x in d["dias"]]
        dia -= dt.timedelta(days=1)
    d["hora"] = horario._hhmm(nuevo)
    d["inicio_hora"] = "%sT%s:00" % (dia.strftime("%Y-%m-%d"), d["hora"])
    if d["fin"]:
        fin = dt.datetime.strptime(d["fin"], "%Y-%m-%d") + dt.timedelta(hours=23, minutes=59, seconds=59)
        d["fin_hora"] = (fin - dt.timedelta(minutes=minutos)).strftime("%Y-%m-%dT%H:%M:%S")
    if cruza:
        d["texto"] += " (empieza el día anterior a las %s para avisarte %d min antes)" % (d["hora"], minutos)
    elif real < minutos:
        d["texto"] += (" (empieza a las 00:00 para avisarte antes: en los horarios mensuales no puede empezar el día "
                       "anterior)")
    else:
        d["texto"] += " (empieza a las %s para avisarte %d min antes)" % (d["hora"], minutos)
    return d


def construir_xml_tarea(programacion, comando, descripcion="", usuario=None, ahora=None, nombre=None, adelanto=None):
    """XML (texto) de una tarea del Programador de tareas con un disparador por hora (y uno con repetición por cada
    «cada N horas»).  `comando` = la línea de `comando_bot`.  La tarea se ejecuta con `usuario` (por defecto el de la
    sesión) SOLO si tiene la sesión iniciada (InteractiveToken), sin privilegios elevados, y no se lanza dos veces a la
    vez.  No crea nada: solo devuelve el texto.  v3.7: `adelanto` = minutos que se adelantan los disparadores para avisar
    antes (por defecto, el «Avisarme antes» de la programación; ver `disparadores`)."""
    import xml.etree.ElementTree as ET
    ET.register_namespace("", NS_TAREA)
    q = lambda t: "{%s}%s" % (NS_TAREA, t)  # noqa: E731

    def sub(padre, etiqueta, texto=None):
        e = ET.SubElement(padre, q(etiqueta))
        if texto is not None:
            e.text = str(texto)
        return e

    tarea = ET.Element(q("Task"), {"version": "1.2"})
    info = sub(tarea, "RegistrationInfo")
    sub(info, "Description", descripcion or "Bot Web")
    sub(info, "Author", "Bot Web")
    if nombre:
        sub(info, "URI", "\\" + nombre_tarea(nombre))
    trig = sub(tarea, "Triggers")
    for d in disparadores(programacion, ahora, adelanto):
        ct = sub(trig, "CalendarTrigger")
        if d["cada_min"]:
            rep = sub(ct, "Repetition")
            sub(rep, "Interval", _iso_duracion(d["cada_min"]))
            sub(rep, "Duration", _iso_duracion(d["duracion_min"]))
            sub(rep, "StopAtDurationEnd", "false")
        sub(ct, "StartBoundary", d.get("inicio_hora") or "%sT%s:00" % (d["inicio"], d["hora"]))
        if d["fin"]:
            sub(ct, "EndBoundary", d.get("fin_hora") or "%sT23:59:59" % d["fin"])
        sub(ct, "Enabled", "true")
        if d["tipo"] == "semana":
            sw = sub(ct, "ScheduleByWeek")
            dias = sub(sw, "DaysOfWeek")
            for x in d["dias"]:
                sub(dias, _DIAS_XML[_DIAS_ES.index(x)])
            sub(sw, "WeeksInterval", "1")
        elif d["tipo"] == "mes":
            sm = sub(ct, "ScheduleByMonth")
            dm = sub(sm, "DaysOfMonth")
            for x in d["dias_mes"]:
                sub(dm, "Day", "Last" if x == "ultimo" else x)
            _meses_xml(sub(sm, "Months"), d["meses"], sub)
        else:
            sm = sub(ct, "ScheduleByMonthDayOfWeek")
            ws = sub(sm, "Weeks")
            for x in d["semanas"]:
                sub(ws, "Week", "Last" if x == "ultima" else x)
            dias = sub(sm, "DaysOfWeek")
            for x in d["dias"]:
                sub(dias, _DIAS_XML[_DIAS_ES.index(x)])
            _meses_xml(sub(sm, "Months"), d["meses"], sub)
    pr = sub(sub(tarea, "Principals"), "Principal", None)
    pr.set("id", "Author")
    usuario = usuario_actual() if usuario is None else usuario
    if usuario:
        sub(pr, "UserId", usuario)
    sub(pr, "LogonType", "InteractiveToken")          # solo con la sesión de Windows iniciada (sin guardar contraseña)
    sub(pr, "RunLevel", "LeastPrivilege")
    st = sub(tarea, "Settings")
    sub(st, "MultipleInstancesPolicy", "IgnoreNew")
    sub(st, "DisallowStartIfOnBatteries", "false")
    sub(st, "StopIfGoingOnBatteries", "false")
    sub(st, "AllowHardTerminate", "true")
    sub(st, "StartWhenAvailable", "false")
    sub(st, "RunOnlyIfNetworkAvailable", "false")
    idle = sub(st, "IdleSettings")
    sub(idle, "StopOnIdleEnd", "false")
    sub(idle, "RestartOnIdle", "false")
    sub(st, "AllowStartOnDemand", "true")
    sub(st, "Enabled", "true")
    sub(st, "Hidden", "false")
    sub(st, "RunOnlyIfIdle", "false")
    sub(st, "WakeToRun", "false")
    sub(st, "ExecutionTimeLimit", LIMITE_EJECUCION)
    sub(st, "Priority", "7")
    acciones = sub(tarea, "Actions")
    acciones.set("Context", "Author")
    exe, args = separar_comando(comando)
    ex = sub(acciones, "Exec")
    sub(ex, "Command", exe)
    if args:
        sub(ex, "Arguments", args)
    cuerpo = ET.tostring(tarea, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + cuerpo


_DIAS_ES = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")


def _meses_xml(padre, meses, sub):
    for m in meses:
        sub(padre, _MESES_XML[int(m) - 1])


def construir_comando_xml(nombre, ruta_xml):
    """`schtasks /Create /XML <archivo> /TN BotWeb\\<nombre> /F` (no ejecuta nada)."""
    return ["schtasks", "/Create", "/XML", ruta_xml, "/TN", nombre_tarea(nombre), "/F"]


RUTA_XML_EJEMPLO = r"%TEMP%\botweb_tarea.xml"


def crear_con_xml(nombre, xml, confirmado=False, ejecutor=None, carpeta=None):
    """Crea (o sustituye) la tarea con ese XML.  Sin `confirmado=True` no hace nada (seguridad).  El XML se escribe en
    UTF-16 en un archivo temporal que se borra al terminar."""
    import tempfile
    if not confirmado:
        raise ErrorProgramador("La creación de la tarea necesita la confirmación del usuario")
    fd, ruta = tempfile.mkstemp(prefix="botweb_", suffix=".xml", dir=carpeta)
    try:
        with os.fdopen(fd, "w", encoding="utf-16", newline="\r\n") as f:
            f.write(xml)
        codigo, salida = (ejecutor or _ejecutar)(construir_comando_xml(nombre, ruta))
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass
    if codigo != 0:
        raise ErrorProgramador("schtasks falló (código %s): %s" % (codigo, salida.strip()))
    return salida.strip()


def construir_comando_borrar(nombre):
    return ["schtasks", "/Delete", "/TN", nombre_tarea(nombre), "/F"]


def construir_comando_consultar(nombre):
    return ["schtasks", "/Query", "/TN", nombre_tarea(nombre), "/FO", "LIST"]


def como_texto(cmd):
    """Comando como texto legible (para mostrar al usuario antes de confirmar)."""
    return " ".join('"%s"' % a if (" " in a or not a) and not a.startswith('"') else a for a in cmd)


def lanzar_desacoplado(linea):
    """v3.6.1: lanza `linea` (el mismo programa que la tarea de Windows) en otro proceso, sin ventana y sin esperarlo."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0) |         getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    from . import RAIZ
    subprocess.Popen(linea, cwd=RAIZ, creationflags=flags, close_fds=True)


def _ejecutar(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="mbcs", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def crear(cmd, confirmado=False, ejecutor=None):
    """Crea la tarea.  Sin `confirmado=True` no hace nada (seguridad)."""
    if not confirmado:
        raise ErrorProgramador("La creación de la tarea necesita la confirmación del usuario")
    codigo, salida = (ejecutor or _ejecutar)(cmd)
    if codigo != 0:
        raise ErrorProgramador("schtasks falló (código %s): %s" % (codigo, salida.strip()))
    return salida.strip()


def borrar(nombre, confirmado=False, ejecutor=None):
    if not confirmado:
        raise ErrorProgramador("Borrar la tarea necesita la confirmación del usuario")
    codigo, salida = (ejecutor or _ejecutar)(construir_comando_borrar(nombre))
    if codigo != 0:
        raise ErrorProgramador("schtasks falló (código %s): %s" % (codigo, salida.strip()))
    return salida.strip()


def consultar(nombre, ejecutor=None):
    codigo, salida = (ejecutor or _ejecutar)(construir_comando_consultar(nombre))
    return codigo == 0, salida.strip()


def listar_tareas(ejecutor=None):
    """Tareas del bot (carpeta BotWeb) con su próxima ejecución: [{nombre, proxima, estado}].  Solo LEE (schtasks
    /Query); si no se puede, devuelve []."""
    import csv
    import io
    try:
        codigo, salida = (ejecutor or _ejecutar)(["schtasks", "/Query", "/FO", "CSV", "/NH"])
    except OSError:
        return []
    if codigo != 0:
        return []
    res, vistos = [], set()
    for fila in csv.reader(io.StringIO(salida)):
        if len(fila) < 3 or not fila[0].startswith("\\%s\\" % CARPETA_TAREAS):
            continue
        nombre = fila[0].split("\\", 2)[-1]
        if nombre in vistos:
            continue
        vistos.add(nombre)
        res.append({"nombre": nombre, "proxima": fila[1], "estado": fila[2]})
    return res
