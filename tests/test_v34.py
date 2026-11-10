"""Pruebas de la versión 3.4 (parte 1): «programación completa».

- `webbot/horario.py`: comprobar y normalizar la programación (días, varias horas, horarios distintos por día, cada N
  horas/minutos en un horario, mensual con días del mes / último día / «el primer lunes»…, fechas de inicio y fin),
  el texto en español, las próximas ejecuciones (último día del mes, años bisiestos, meses sin día 31, horas locales
  sin zona horaria) y la conversión desde la frecuencia antigua (''/'horas'/'diaria').
- `programador`: el XML del Programador de tareas (varios disparadores) se vuelve a leer con xml.etree; crear la tarea
  con el XML usa un `ejecutor` falso (NUNCA se llama a schtasks).
- `almacen`: columna nueva `vigilancias.programacion` en una base de datos de la 3.3 y tabla `programaciones`.
- `servidor_ui`: /api/horario, vigilancias con programación y su tarea de Windows (crear, sustituir, quitar),
  «Programar…» de reportes y Páginas con programación, «Próximas» del inicio.
Bases de datos temporales; ninguna notificación de Windows, ninguna tarea programada (schtasks nunca se ejecuta).
"""

import datetime as dt
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_v32 import pagina_simple  # noqa: E402
from test_v33 import flujo_reporte  # noqa: E402
from webbot import avisos, horario, programador  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen, ErrorAlmacen  # noqa: E402

NS = {"t": programador.NS_TAREA}
JUEVES = dt.datetime(2026, 10, 29, 10, 0)           # jueves 29/10/2026 10:00

EJEMPLO = {"reglas": [
    {"tipo": "semanal", "dias": ["lun", "mar", "mie", "jue", "vie"], "horas": ["09:00", "15:00"]},
    {"tipo": "intervalo", "dias": ["vie"], "cada_min": 120, "desde": "08:00", "hasta": "18:00"}]}


def _sin_schtasks(*a, **k):
    raise AssertionError("¡Una prueba intentó ejecutar schtasks de verdad!")


class TestNormalizar(unittest.TestCase):
    def test_forma_canonica_y_alias(self):
        p = horario.normalizar({"reglas": [
            {"tipo": "semanal", "dias": ["VIE", "MON", "miércoles", "lun"], "horas": ["15:00", "8:00", "08:00"]},
            {"tipo": "intervalo", "dias": "sáb,dom", "cada_horas": 2},
            {"tipo": "mensual", "dias_mes": [15, "1", "último", 15], "horas": ["07:00"], "meses": ["ene", 4, "jul", 10]},
            {"tipo": "mensual_semana", "semana": "ultima", "dia_semana": "viernes", "horas": "18:00"}],
            "inicio": "01/11/2026", "fin": "2026-12-31"})
        self.assertEqual(p["reglas"][0], {"tipo": "semanal", "dias": ["lun", "mie", "vie"], "horas": ["08:00", "15:00"]})
        self.assertEqual(p["reglas"][1], {"tipo": "intervalo", "dias": ["sab", "dom"], "cada_min": 120, "desde": "00:00",
                                          "hasta": "23:59"})
        self.assertEqual(p["reglas"][2], {"tipo": "mensual", "dias_mes": [1, 15, "ultimo"], "horas": ["07:00"],
                                          "meses": [1, 4, 7, 10]})
        self.assertEqual(p["reglas"][3], {"tipo": "mensual_semana", "semanas": ["ultima"], "dias": ["vie"],
                                          "horas": ["18:00"], "meses": list(range(1, 13))})
        self.assertEqual((p["inicio"], p["fin"]), ("2026-11-01", "2026-12-31"))
        # el JSON vuelve a dar lo mismo (forma estable, serializable)
        self.assertEqual(horario.desde_json(horario.a_json(p)), p)
        self.assertEqual(horario.normalizar(None), horario.vacia())
        self.assertTrue(horario.es_vacia(""))
        self.assertTrue(horario.es_vacia({"reglas": []}))
        self.assertFalse(horario.es_vacia(EJEMPLO))

    def test_errores_claros(self):
        malos = [
            ({"reglas": [{"tipo": "semanal", "dias": [], "horas": ["08:00"]}]}, "al menos un día"),
            ({"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["25:00"]}]}, "HH:MM"),
            ({"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": []}]}, "al menos una hora"),
            ({"reglas": [{"tipo": "semanal", "dias": ["xyz"], "horas": ["08:00"]}]}, "Día de la semana no válido"),
            ({"reglas": [{"tipo": "intervalo", "dias": ["lun"], "cada_min": 10}]}, "15 minutos"),
            ({"reglas": [{"tipo": "intervalo", "dias": ["lun"], "cada_min": 60, "desde": "18:00", "hasta": "08:00"}]},
             "debe ser después"),
            ({"reglas": [{"tipo": "mensual", "dias_mes": [], "horas": ["08:00"]}]}, "día del mes"),
            ({"reglas": [{"tipo": "mensual", "dias_mes": [32], "horas": ["08:00"]}]}, "de 1 a 31"),
            ({"reglas": [{"tipo": "mensual_semana", "semanas": [5], "dias": ["lun"], "horas": ["08:00"]}]}, "Semana"),
            ({"reglas": [{"tipo": "mensual", "dias_mes": [1], "horas": ["08:00"], "meses": [13]}]}, "Mes no válido"),
            ({"reglas": [{"tipo": "cada_luna", "dias": ["lun"]}]}, "Tipo de horario"),
            ({"reglas": [], "inicio": "2026-12-01", "fin": "2026-11-01"}, "anterior"),
            ({"reglas": [], "inicio": "2026-02-30"}, "no existe"),
            ("esto no es json", "no es válida"),
        ]
        for prog, texto in malos:
            with self.subTest(prog=prog):
                with self.assertRaises(horario.ErrorHorario) as cm:
                    horario.normalizar(prog)
                self.assertIn(texto, str(cm.exception))
        # con varios horarios el error dice cuál
        with self.assertRaises(horario.ErrorHorario) as cm:
            horario.normalizar({"reglas": [EJEMPLO["reglas"][0], {"tipo": "semanal", "dias": ["lun"], "horas": ["x"]}]})
        self.assertTrue(str(cm.exception).startswith("Horario 2:"))
        # más de 48 disparadores (límite del Programador de tareas)
        muchas = {"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["%02d:%02d" % (h, m) for h in range(12)
                                                                             for m in (0, 30)]}] * 3}
        with self.assertRaises(horario.ErrorHorario) as cm:
            horario.normalizar(muchas)
        self.assertIn("48", str(cm.exception))


class TestDescribir(unittest.TestCase):
    def test_textos(self):
        self.assertEqual(horario.describir(EJEMPLO),
                         "de lunes a viernes a las 09:00 y 15:00; los viernes cada 2 h de 08:00 a 18:00")
        casos = [
            ({"tipo": "semanal", "dias": list(horario.DIAS), "horas": ["07:00"]}, "todos los días a las 07:00"),
            ({"tipo": "semanal", "dias": ["sab", "dom"], "horas": ["10:00"]}, "los fines de semana a las 10:00"),
            ({"tipo": "semanal", "dias": ["lun", "mie", "vie"], "horas": ["08:00", "12:00", "16:00"]},
             "los lunes, miércoles y viernes a las 08:00, 12:00 y 16:00"),
            ({"tipo": "semanal", "dias": ["mar", "mie", "jue"], "horas": ["01:30"]}, "de martes a jueves a la 01:30"),
            ({"tipo": "semanal", "dias": ["dom"], "horas": ["09:00"]}, "los domingos a las 09:00"),
            ({"tipo": "intervalo", "dias": list(horario.DIAS), "cada_min": 240}, "todos los días cada 4 h"),
            ({"tipo": "intervalo", "dias": ["lun"], "cada_min": 90, "desde": "09:00", "hasta": "17:00"},
             "los lunes cada 1 h 30 min de 09:00 a 17:00"),
            ({"tipo": "intervalo", "dias": ["lun"], "cada_min": 30, "desde": "09:00", "hasta": "10:00"},
             "los lunes cada 30 min de 09:00 a 10:00"),
            ({"tipo": "mensual", "dias_mes": [1, 15], "horas": ["08:00"]}, "los días 1 y 15 de cada mes a las 08:00"),
            ({"tipo": "mensual", "dias_mes": ["ultimo"], "horas": ["23:00"]}, "el último día de cada mes a las 23:00"),
            ({"tipo": "mensual", "dias_mes": [1, "ultimo"], "horas": ["08:00"], "meses": [1, 7]},
             "el día 1 y el último día de enero y julio a las 08:00"),
            ({"tipo": "mensual_semana", "semanas": [1], "dias": ["lun"], "horas": ["08:00"]},
             "el primer lunes de cada mes a las 08:00"),
            ({"tipo": "mensual_semana", "semanas": [2, "ultima"], "dias": ["vie"], "horas": ["17:00"]},
             "el segundo y último viernes de cada mes a las 17:00"),
        ]
        for regla, texto in casos:
            with self.subTest(texto=texto):
                self.assertEqual(horario.describir({"reglas": [regla]}), texto)
        self.assertEqual(horario.describir({"reglas": []}), "solo a mano")
        self.assertEqual(horario.describir(None, "sin programar"), "sin programar")
        self.assertEqual(horario.describir(dict(EJEMPLO, inicio="2026-11-01", fin="2026-12-31")),
                         "de lunes a viernes a las 09:00 y 15:00; los viernes cada 2 h de 08:00 a 18:00 "
                         "(del 01/11/2026 al 31/12/2026)")
        self.assertIn("hasta el 31/12/2026", horario.describir(dict(EJEMPLO, fin="2026-12-31")))
        self.assertIn("no válida", horario.describir({"reglas": [{"tipo": "x"}]}))
        self.assertTrue(horario.avisos({"reglas": [{"tipo": "mensual", "dias_mes": [31], "horas": ["08:00"]}]}))
        self.assertEqual(horario.avisos(EJEMPLO), [])


def _f(texto):
    return dt.datetime.strptime(texto, "%Y-%m-%d %H:%M")


class TestProximas(unittest.TestCase):
    def test_semana_y_ventana(self):
        res = horario.proximas(EJEMPLO, 9, JUEVES)
        self.assertEqual(res, [_f("2026-10-29 15:00"), _f("2026-10-30 08:00"), _f("2026-10-30 09:00"),
                               _f("2026-10-30 10:00"), _f("2026-10-30 12:00"), _f("2026-10-30 14:00"),
                               _f("2026-10-30 15:00"), _f("2026-10-30 16:00"), _f("2026-10-30 18:00")])
        # la hora «hasta» se incluye; el lunes siguiente vuelven las 09:00 (el fin de semana no hay nada)
        self.assertEqual(horario.proximas(EJEMPLO, 10, JUEVES)[-1], _f("2026-11-02 09:00"))
        # a la misma hora exacta no cuenta (ya pasó)
        self.assertEqual(horario.proximas(EJEMPLO, 1, _f("2026-10-29 15:00"))[0], _f("2026-10-30 08:00"))
        self.assertEqual(horario.proximas({"reglas": []}, 5, JUEVES), [])

    def test_horas_distintas_segun_el_dia(self):
        p = {"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["08:00", "14:00"]},
                        {"tipo": "semanal", "dias": ["vie"], "horas": ["10:00"]}]}
        self.assertEqual(horario.proximas(p, 4, JUEVES), [_f("2026-10-30 10:00"), _f("2026-11-02 08:00"),
                                                         _f("2026-11-02 14:00"), _f("2026-11-06 10:00")])
        # dos reglas a la misma hora el mismo día: una sola ejecución
        doble = {"reglas": [{"tipo": "semanal", "dias": ["vie"], "horas": ["10:00"]},
                            {"tipo": "intervalo", "dias": ["vie"], "cada_min": 60, "desde": "10:00", "hasta": "11:00"}]}
        self.assertEqual(horario.proximas(doble, 3, JUEVES), [_f("2026-10-30 10:00"), _f("2026-10-30 11:00"),
                                                             _f("2026-11-06 10:00")])

    def test_cada_minutos(self):
        p = {"reglas": [{"tipo": "intervalo", "dias": ["jue"], "cada_min": 15, "desde": "10:00", "hasta": "10:40"}]}
        self.assertEqual(horario.proximas(p, 3, JUEVES), [_f("2026-10-29 10:15"), _f("2026-10-29 10:30"),
                                                         _f("2026-11-05 10:00")])

    def test_ultimo_dia_del_mes_y_bisiestos(self):
        p = {"reglas": [{"tipo": "mensual", "dias_mes": ["ultimo"], "horas": ["23:00"]}]}
        res = horario.proximas(p, 6, JUEVES)
        self.assertEqual([d.strftime("%Y-%m-%d") for d in res],
                         ["2026-10-31", "2026-11-30", "2026-12-31", "2027-01-31", "2027-02-28", "2027-03-31"])
        res = horario.proximas(p, 1, _f("2028-02-01 00:00"))
        self.assertEqual(res, [_f("2028-02-29 23:00")])                      # 2028 es bisiesto
        # el día 31 solo en los meses que lo tienen (como el Programador de Windows)
        p31 = {"reglas": [{"tipo": "mensual", "dias_mes": [31], "horas": ["08:00"]}]}
        self.assertEqual([d.month for d in horario.proximas(p31, 4, JUEVES)], [10, 12, 1, 3])   # sin noviembre ni febrero
        # día 1 y 15 en algunos meses
        p = {"reglas": [{"tipo": "mensual", "dias_mes": [1, 15], "horas": ["08:00"], "meses": [1, 7]}]}
        self.assertEqual(horario.proximas(p, 3, JUEVES), [_f("2027-01-01 08:00"), _f("2027-01-15 08:00"),
                                                         _f("2027-07-01 08:00")])
        # 29 de febrero: se encuentra aunque falten años
        p29 = {"reglas": [{"tipo": "mensual", "dias_mes": [29], "horas": ["08:00"], "meses": [2]}]}
        self.assertEqual(horario.proximas(p29, 1, JUEVES), [_f("2028-02-29 08:00")])

    def test_primer_y_ultimo_dia_de_la_semana_del_mes(self):
        p = {"reglas": [{"tipo": "mensual_semana", "semanas": [1], "dias": ["lun"], "horas": ["08:00"]}]}
        self.assertEqual(horario.proximas(p, 3, JUEVES), [_f("2026-11-02 08:00"), _f("2026-12-07 08:00"),
                                                         _f("2027-01-04 08:00")])
        p = {"reglas": [{"tipo": "mensual_semana", "semanas": ["ultima"], "dias": ["vie"], "horas": ["17:00"]}]}
        self.assertEqual(horario.proximas(p, 3, JUEVES), [_f("2026-10-30 17:00"), _f("2026-11-27 17:00"),
                                                         _f("2026-12-25 17:00")])
        p = {"reglas": [{"tipo": "mensual_semana", "semanas": [2, 4], "dias": ["mar"], "horas": ["09:00"]}]}
        self.assertEqual(horario.proximas(p, 2, JUEVES), [_f("2026-11-10 09:00"), _f("2026-11-24 09:00")])

    def test_inicio_y_fin(self):
        p = dict(EJEMPLO, inicio="2026-11-04", fin="2026-11-05")
        res = horario.proximas(p, 10, JUEVES)
        self.assertEqual(res, [_f("2026-11-04 09:00"), _f("2026-11-04 15:00"), _f("2026-11-05 09:00"),
                               _f("2026-11-05 15:00")])
        self.assertEqual(horario.proximas(dict(EJEMPLO, fin="2026-10-01"), 5, JUEVES), [])

    def test_hora_local_sin_zona_horaria(self):
        # 29/03/2026 y 25/10/2026: cambios de hora en Europa; 08/03/2026 en EE. UU.  Se cuenta en hora local «de reloj»
        # (sin zona horaria), igual que el Programador de tareas de Windows: las 02:30 siguen siendo las 02:30.
        p = {"reglas": [{"tipo": "semanal", "dias": list(horario.DIAS), "horas": ["02:30"]}]}
        for dia in ("2026-03-29", "2026-10-25", "2026-03-08"):
            res = horario.proximas(p, 1, _f(dia + " 00:00"))
            self.assertEqual(res, [_f(dia + " 02:30")])
            self.assertIsNone(res[0].tzinfo)
        intervalo = {"reglas": [{"tipo": "intervalo", "dias": ["dom"], "cada_min": 60, "desde": "01:00", "hasta": "04:00"}]}
        self.assertEqual([d.hour for d in horario.proximas(intervalo, 4, _f("2026-03-29 00:00"))], [1, 2, 3, 4])

    def test_texto_fecha_y_vista(self):
        self.assertEqual(horario.texto_fecha(_f("2026-10-29 15:00"), JUEVES), "hoy 15:00")
        self.assertEqual(horario.texto_fecha(_f("2026-10-30 08:00"), JUEVES), "mañana 08:00")
        self.assertEqual(horario.texto_fecha(_f("2026-11-02 09:00"), JUEVES), "lunes 02/11/2026 09:00")
        v = horario.vista(EJEMPLO, 2, JUEVES)
        self.assertTrue(v["valida"])
        self.assertEqual(v["proximas"], [{"fecha": "2026-10-29T15:00", "texto": "hoy 15:00"},
                                         {"fecha": "2026-10-30T08:00", "texto": "mañana 08:00"}])
        self.assertEqual(v["disparadores"], 3)
        self.assertFalse(v["vacia"])
        self.assertEqual(horario.vista({"reglas": [{"tipo": "x"}]})["valida"], False)


class TestConversionAntigua(unittest.TestCase):
    def test_frecuencias_de_la_3_3(self):
        self.assertEqual(horario.desde_antiguo(""), horario.vacia())
        self.assertEqual(horario.desde_antiguo("horas", 4)["reglas"],
                         [{"tipo": "intervalo", "dias": list(horario.DIAS), "cada_min": 240, "desde": "00:00",
                           "hasta": "23:59"}])
        self.assertEqual(horario.describir(horario.desde_antiguo("horas", 4)), "todos los días cada 4 h")
        self.assertEqual(horario.describir(horario.desde_antiguo("diaria", hora="06:30")), "todos los días a las 06:30")
        # las de las tareas (DIARIA / SEMANAL / HORAS)
        self.assertEqual(horario.describir(horario.desde_antiguo("SEMANAL", hora="07:00", dias=["MON", "WED"])),
                         "los lunes y miércoles a las 07:00")
        self.assertEqual(horario.describir(horario.desde_antiguo("HORAS", 3, "08:00")), "todos los días cada 3 h de 08:00 a 23:59")
        with self.assertRaises(horario.ErrorHorario):
            horario.desde_antiguo("semanita")

    def test_de_vigilancia(self):
        self.assertEqual(horario.describir(horario.de_vigilancia({"frecuencia": "diaria", "hora": "08:00",
                                                                  "programacion": ""})), "todos los días a las 08:00")
        nueva = {"frecuencia": "programa", "programacion": horario.a_json(EJEMPLO), "hora": "", "cada_horas": None}
        self.assertEqual(horario.de_vigilancia(nueva), horario.normalizar(EJEMPLO))
        # programación guardada estropeada → se usa la frecuencia antigua (aquí: ninguna)
        self.assertEqual(horario.de_vigilancia({"frecuencia": "programa", "programacion": "{roto"}), horario.vacia())


class TestXmlTarea(unittest.TestCase):
    def setUp(self):
        self.prog = {"reglas": EJEMPLO["reglas"] + [
            {"tipo": "mensual", "dias_mes": [1, 15, "ultimo"], "horas": ["07:00"], "meses": [1, 6]},
            {"tipo": "mensual_semana", "semanas": [1, "ultima"], "dias": ["lun", "vie"], "horas": ["06:00"]}],
            "fin": "2026-12-31"}
        self.linea = programador.comando_bot(os.path.join(RAIZ, "bot.py"), vigilancia_id=7, python=r"C:\Py\pythonw.exe")

    def leer(self, xml):
        raiz = ET.fromstring(xml)
        self.assertEqual(raiz.tag, "{%s}Task" % programador.NS_TAREA)
        return raiz

    def test_disparadores(self):
        xml = programador.construir_xml_tarea(self.prog, self.linea, "Vigilar X", usuario="PC\\ana", ahora=JUEVES,
                                              nombre="Vigilar X #7")
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-16"?>'))
        raiz = self.leer(xml)
        self.assertEqual(raiz.find("t:RegistrationInfo/t:URI", NS).text, "\\BotWeb\\Vigilar X #7")
        disp = raiz.findall("t:Triggers/t:CalendarTrigger", NS)
        self.assertEqual(len(disp), 5)                          # 09:00, 15:00, cada 2 h, mensual, mensual_semana
        inicio = [d.find("t:StartBoundary", NS).text for d in disp]
        self.assertEqual(inicio, ["2026-10-29T09:00:00", "2026-10-29T15:00:00", "2026-10-29T08:00:00",
                                  "2026-10-29T07:00:00", "2026-10-29T06:00:00"])
        self.assertTrue(all(d.find("t:EndBoundary", NS).text == "2026-12-31T23:59:59" for d in disp))
        dias = [x.tag.split("}")[1] for x in disp[0].find("t:ScheduleByWeek/t:DaysOfWeek", NS)]
        self.assertEqual(dias, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        self.assertIsNone(disp[0].find("t:Repetition", NS))
        # «cada 2 h de 08:00 a 18:00»: repetición con la última (18:00) dentro
        rep = disp[2].find("t:Repetition", NS)
        self.assertEqual((rep.find("t:Interval", NS).text, rep.find("t:Duration", NS).text), ("PT2H", "PT10H1M"))
        self.assertEqual([x.tag.split("}")[1] for x in disp[2].find("t:ScheduleByWeek/t:DaysOfWeek", NS)], ["Friday"])
        # mensual: días 1, 15 y el último; solo enero y junio
        sm = disp[3].find("t:ScheduleByMonth", NS)
        self.assertEqual([d.text for d in sm.findall("t:DaysOfMonth/t:Day", NS)], ["1", "15", "Last"])
        self.assertEqual([m.tag.split("}")[1] for m in sm.find("t:Months", NS)], ["January", "June"])
        # el primer y el último lunes/viernes del mes, todos los meses
        sw = disp[4].find("t:ScheduleByMonthDayOfWeek", NS)
        self.assertEqual([w.text for w in sw.findall("t:Weeks/t:Week", NS)], ["1", "Last"])
        self.assertEqual([x.tag.split("}")[1] for x in sw.find("t:DaysOfWeek", NS)], ["Monday", "Friday"])
        self.assertEqual(len(list(sw.find("t:Months", NS))), 12)
        # con tu usuario, solo con la sesión iniciada; no dos a la vez; el programa y sus argumentos
        self.assertEqual(raiz.find("t:Principals/t:Principal/t:UserId", NS).text, "PC\\ana")
        self.assertEqual(raiz.find("t:Principals/t:Principal/t:LogonType", NS).text, "InteractiveToken")
        self.assertEqual(raiz.find("t:Principals/t:Principal/t:RunLevel", NS).text, "LeastPrivilege")
        self.assertEqual(raiz.find("t:Settings/t:MultipleInstancesPolicy", NS).text, "IgnoreNew")
        self.assertEqual(raiz.find("t:Actions/t:Exec/t:Command", NS).text, r"C:\Py\pythonw.exe")
        args = raiz.find("t:Actions/t:Exec/t:Arguments", NS).text
        self.assertTrue(args.startswith('"%s"' % os.path.join(RAIZ, "bot.py")), args)
        self.assertTrue(args.endswith("--vigilancia-id 7 --vigilar --oculto"), args)
        # con fecha de inicio: los disparadores empiezan ese día
        xml = programador.construir_xml_tarea(dict(EJEMPLO, inicio="2027-01-04"), self.linea, ahora=JUEVES, usuario="")
        raiz = self.leer(xml)
        self.assertEqual(raiz.find("t:Triggers/t:CalendarTrigger/t:StartBoundary", NS).text, "2027-01-04T09:00:00")
        self.assertIsNone(raiz.find("t:Triggers/t:CalendarTrigger/t:EndBoundary", NS))
        self.assertIsNone(raiz.find("t:Principals/t:Principal/t:UserId", NS))
        # todo el día cada 4 h: la repetición dura un día
        xml = programador.construir_xml_tarea(horario.desde_antiguo("horas", 4), self.linea, ahora=JUEVES)
        rep = self.leer(xml).find("t:Triggers/t:CalendarTrigger/t:Repetition", NS)
        self.assertEqual((rep.find("t:Interval", NS).text, rep.find("t:Duration", NS).text), ("PT4H", "P1D"))
        textos = [d["texto"] for d in programador.disparadores(self.prog, JUEVES)]
        self.assertEqual(textos[:3], ["de lunes a viernes a las 09:00", "de lunes a viernes a las 15:00",
                                      "los viernes cada 2 h de 08:00 a 18:00"])
        with self.assertRaises(programador.ErrorProgramador):
            programador.construir_xml_tarea({"reglas": []}, self.linea)
        self.assertEqual(programador.separar_comando('"C:\\a b\\p.exe" "x y" --id 1'), ("C:\\a b\\p.exe", '"x y" --id 1'))
        self.assertEqual(programador._iso_duracion(90), "PT1H30M")

    def test_crear_con_xml_usa_utf16_y_borra_el_archivo(self):
        xml = programador.construir_xml_tarea(EJEMPLO, self.linea, ahora=JUEVES, usuario="PC\\ana")
        tmp = tempfile.mkdtemp(prefix="botweb_v34_")
        self.addCleanup(shutil.rmtree, tmp, True)
        with self.assertRaises(programador.ErrorProgramador):
            programador.crear_con_xml("X", xml, ejecutor=_sin_schtasks, carpeta=tmp)      # sin confirmar: nada
        vistos = []

        def falso(cmd):
            ruta = cmd[cmd.index("/XML") + 1]
            with open(ruta, "rb") as f:
                datos = f.read()
            vistos.append((cmd, datos))
            self.assertTrue(datos.startswith(b"\xff\xfe"))                     # UTF-16 con BOM
            self.assertEqual(len(ET.parse(ruta).getroot().findall("t:Triggers/t:CalendarTrigger", NS)), 3)
            return 0, "CORRECTO"
        self.assertEqual(programador.crear_con_xml("Mi tarea", xml, confirmado=True, ejecutor=falso, carpeta=tmp),
                         "CORRECTO")
        cmd = vistos[0][0]
        self.assertEqual(cmd[:3], ["schtasks", "/Create", "/XML"])
        self.assertEqual(cmd[3:], [cmd[3], "/TN", "BotWeb\\Mi tarea", "/F"])
        self.assertEqual(os.listdir(tmp), [])                                  # el XML temporal se borró
        with self.assertRaises(programador.ErrorProgramador) as cm:
            programador.crear_con_xml("X", xml, confirmado=True, ejecutor=lambda c: (1, "ERROR: acceso denegado"),
                                      carpeta=tmp)
        self.assertIn("acceso denegado", str(cm.exception))
        self.assertEqual(os.listdir(tmp), [])

    @unittest.skipUnless(os.name == "nt", "solo en Windows")
    def test_el_programador_de_windows_acepta_el_xml(self):
        """El propio Programador de tareas lee el XML (`NewTask(0).XmlText`, que NO registra ninguna tarea)."""
        xml = programador.construir_xml_tarea(self.prog, self.linea, "Prueba", ahora=JUEVES, nombre="Prueba #1")
        tmp = tempfile.mkdtemp(prefix="botweb_v34_")
        self.addCleanup(shutil.rmtree, tmp, True)
        ruta = os.path.join(tmp, "t.xml")
        with open(ruta, "w", encoding="utf-16") as f:
            f.write(xml)
        ps = ("$s = New-Object -ComObject Schedule.Service; $s.Connect(); $t = $s.NewTask(0); "
              "$t.XmlText = [IO.File]::ReadAllText('%s'); Write-Output ('OK ' + $t.Triggers.Count)" % ruta)
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                               text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as e:
            self.skipTest("PowerShell no disponible: %s" % e)
        if "OK" not in r.stdout and ("Schedule.Service" in r.stderr or "COM" in r.stderr):
            self.skipTest("El servicio del Programador de tareas no está disponible: %s" % r.stderr[:200])
        self.assertIn("OK 5", r.stdout, r.stderr)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v34_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        avisos.usar_notificador(lambda titulo, texto: None)
        self.addCleanup(avisos.usar_notificador, None)
        p = mock.patch.object(programador, "_ejecutar", _sin_schtasks)       # schtasks de verdad: nunca
        p.start()
        self.addCleanup(p.stop)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)


class TestAlmacenV34(Base):
    def test_migracion_desde_la_3_3(self):
        rid = self.alm.guardar(flujo_reporte())
        vid = self.alm.crear_vigilancia(reporte_id=rid, paso=2, frecuencia="diaria", hora="08:00")
        vid2 = self.alm.crear_vigilancia(reporte_id=rid, paso=2, nombre="b", frecuencia="horas", cada_horas=6)
        self.alm.cerrar()
        con = sqlite3.connect(os.path.join(self.tmp, "b.db"))          # la base de datos como la dejaba la 3.3
        con.execute("ALTER TABLE vigilancias DROP COLUMN programacion")
        con.execute("DROP TABLE programaciones")
        con.commit()
        con.close()
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        cols = {f[1] for f in self.alm._con().execute("PRAGMA table_info(vigilancias)")}
        self.assertIn("programacion", cols)
        v = self.alm.vigilancia_id(vid)
        self.assertEqual((v["frecuencia"], v["hora"]), ("diaria", "08:00"))             # lo antiguo sigue ahí
        self.assertEqual(horario.describir(v["programacion"]), "todos los días a las 08:00")
        self.assertEqual(horario.describir(self.alm.vigilancia_id(vid2)["programacion"]), "todos los días cada 6 h")
        # guardar una programación: manda sobre la frecuencia antigua
        v = self.alm.actualizar_vigilancia(vid, programacion=EJEMPLO)
        self.assertEqual((v["frecuencia"], v["hora"], v["cada_horas"]), ("programa", "", None))
        self.assertEqual(v["programacion"], horario.normalizar(EJEMPLO))
        crudo = self.alm._con().execute("SELECT programacion FROM vigilancias WHERE id = ?", (vid,)).fetchone()[0]
        self.assertEqual(horario.desde_json(crudo), horario.normalizar(EJEMPLO))
        # sin reglas = solo a mano
        v = self.alm.actualizar_vigilancia(vid, programacion={"reglas": []})
        self.assertEqual((v["frecuencia"], v["programacion"]["reglas"]), ("", []))
        # la API antigua (solo frecuencia) borra la programación guardada
        self.alm.actualizar_vigilancia(vid, programacion=EJEMPLO)
        v = self.alm.actualizar_vigilancia(vid, frecuencia="horas", cada_horas=3)
        self.assertEqual(horario.describir(v["programacion"]), "todos los días cada 3 h")
        with self.assertRaises(ErrorAlmacen):
            self.alm.actualizar_vigilancia(vid, programacion={"reglas": [{"tipo": "semanal", "dias": [], "horas": []}]})
        with self.assertRaises(ErrorAlmacen):
            self.alm.actualizar_vigilancia(vid, frecuencia="semanal")             # sigue sin valer (3.0)
        # crear con programación
        vid3 = self.alm.crear_vigilancia(reporte_id=rid, paso=2, nombre="c", programacion=EJEMPLO)
        self.assertEqual(self.alm.vigilancia_id(vid3)["frecuencia"], "programa")

    def test_programaciones(self):
        self.assertIsNone(self.alm.programacion("reporte:1"))
        self.alm.guardar_programacion("reporte:1", EJEMPLO, "BotWeb\\Ventas")
        self.alm.guardar_programacion("pagina:2:Mayorista", horario.desde_antiguo("diaria", hora="07:00"), "BotWeb\\P - Mayorista")
        g = self.alm.programacion("reporte:1")
        self.assertEqual((g["programacion"], g["tarea"]), (horario.normalizar(EJEMPLO), "BotWeb\\Ventas"))
        self.assertEqual([x["clave"] for x in self.alm.lista_programaciones()], ["pagina:2:Mayorista", "reporte:1"])
        self.assertEqual([x["clave"] for x in self.alm.lista_programaciones("pagina:")], ["pagina:2:Mayorista"])
        self.alm.borrar_programacion("reporte:1")
        self.assertIsNone(self.alm.programacion("reporte:1"))
        with self.assertRaises(ErrorAlmacen):
            self.alm.guardar_programacion("x", {"reglas": [{"tipo": "nada"}]})


class TestApiV34(Base):
    def setUp(self):
        super().setUp()
        self.tareas = []                 # lo que «ve» el bot en el Programador de Windows (falso)
        self.llamadas = []

        def ejecutar(cmd):
            self.llamadas.append(list(cmd))
            if "/XML" in cmd:
                with open(cmd[cmd.index("/XML") + 1], "rb") as f:
                    self.llamadas[-1].append(f.read().decode("utf-16"))
                self.tareas.append({"nombre": cmd[cmd.index("/TN") + 1].split("\\", 1)[1], "proxima": "30/10/2026 9:00:00",
                                    "estado": "Listo"})
            elif "/Delete" in cmd:
                nombre = cmd[cmd.index("/TN") + 1].split("\\", 1)[1]
                self.tareas[:] = [t for t in self.tareas if t["nombre"] != nombre]
            return 0, "CORRECTO"
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                                 listar_tareas=lambda: list(self.tareas), oculto_forzado=True, ejecutar_tareas=ejecutar)

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})

    def test_horario(self):
        r = self.api("POST", "horario", {"programacion": EJEMPLO, "n": 3})
        self.assertTrue(r["valida"])
        self.assertEqual(r["descripcion"], "de lunes a viernes a las 09:00 y 15:00; los viernes cada 2 h de 08:00 a 18:00")
        self.assertEqual(len(r["proximas"]), 3)
        self.assertEqual(r["disparadores"], 3)
        r = self.api("POST", "horario", {"programacion": {"reglas": [{"tipo": "semanal", "dias": [], "horas": ["8:00"]}]}})
        self.assertEqual((r["valida"], r["error"]), (False, "Elige al menos un día de la semana"))
        r = self.api("POST", "horario", {"programacion": {"reglas": []}, "vacio": "Sin programar"})
        self.assertEqual((r["valida"], r["vacia"], r["descripcion"], r["proximas"]), (True, True, "Sin programar", []))

    def test_vigilancia_con_programacion_y_su_tarea(self):
        rid = self.alm.guardar(flujo_reporte())
        v = self.api("POST", "vigilancias", {"reporte_id": rid, "paso": 2, "nombre": "Mayorista", "programacion": EJEMPLO})
        v = v["vigilancia"]
        vid = v["id"]
        self.assertEqual(v["frecuencia"], "programa")
        self.assertEqual(v["cuando"], "de lunes a viernes a las 09:00 y 15:00; los viernes cada 2 h de 08:00 a 18:00")
        self.assertTrue(v["proxima"])
        # sin tarea en Windows: se dice (y en el inicio sale «sin tarea»)
        self.assertFalse(self.api("GET", "vigilancias/%d" % vid)["vigilancia"]["tarea"]["existe"])
        pagina = self.api("GET", "vigilancia")
        self.assertFalse(pagina["reportes"][0]["vigilancias"][0]["tarea"]["existe"])
        prox = [x for x in self.api("GET", "inicio")["proximas"] if x.get("vigilancia_id") == vid]
        self.assertEqual(len(prox), 1)
        self.assertTrue(prox[0]["sin_tarea"])
        self.assertRegex(prox[0]["cuando"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")
        # vista previa de la tarea (sin confirmar: no se llama a schtasks)
        pr = self.api("POST", "vigilancias/%d/programar" % vid)
        self.assertEqual(self.llamadas, [])
        self.assertFalse(pr["creada"])
        self.assertEqual(pr["tarea"], "BotWeb\\Vigilar Portal (reporte) - Mayorista #%d" % vid)
        self.assertIn("schtasks /Create /XML", pr["comando"])
        self.assertTrue(pr["programa"].endswith("--vigilancia-id %d --vigilar --oculto" % vid), pr["programa"])
        self.assertEqual(len(ET.fromstring(pr["xml"]).findall("t:Triggers/t:CalendarTrigger", NS)), 3)
        self.assertEqual(pr["disparadores"], ["de lunes a viernes a las 09:00", "de lunes a viernes a las 15:00",
                                              "los viernes cada 2 h de 08:00 a 18:00"])
        self.assertFalse(pr["existe"])
        # crear (confirmado): schtasks /Create /XML con el XML en UTF-16
        pr = self.api("POST", "vigilancias/%d/programar" % vid, {"confirmar": True})
        self.assertTrue(pr["creada"])
        self.assertEqual(len(self.llamadas), 1)
        cmd = self.llamadas[0]
        self.assertEqual(cmd[:3], ["schtasks", "/Create", "/XML"])
        self.assertIn("<ScheduleByWeek>", cmd[-1])
        t = self.api("GET", "vigilancias/%d" % vid)["vigilancia"]["tarea"]
        self.assertTrue(t["existe"])
        self.assertEqual(t["proxima"], "30/10/2026 9:00:00")
        self.assertFalse([x for x in self.api("GET", "inicio")["proximas"] if x.get("vigilancia_id") == vid][0]["sin_tarea"])
        # se renombra la vigilancia: la tarea nueva sustituye a la vieja (que se borra)
        self.api("PUT", "vigilancias/%d" % vid, {"nombre": "Cartera"})
        pr = self.api("POST", "vigilancias/%d/programar" % vid)
        self.assertEqual(pr["sustituye"], ["Vigilar Portal (reporte) - Mayorista #%d" % vid])
        self.api("POST", "vigilancias/%d/programar" % vid, {"confirmar": True})
        self.assertEqual([x["nombre"] for x in self.tareas], ["Vigilar Portal (reporte) - Cartera #%d" % vid])
        self.assertIn("/Delete", self.llamadas[-1])
        # otra programación pasada en la petición (sin guardarla)
        otra = {"reglas": [{"tipo": "mensual", "dias_mes": ["ultimo"], "horas": ["20:00"]}]}
        pr = self.api("POST", "vigilancias/%d/programar" % vid, {"programacion": otra})
        self.assertEqual(pr["descripcion"], "el último día de cada mes a las 20:00")
        # quitar la tarea
        q = self.api("POST", "vigilancias/%d/quitar_tarea" % vid)
        self.assertFalse(q["borrada"])
        self.assertIn("schtasks /Delete", q["comandos"][0])
        self.assertTrue(self.tareas)
        self.assertTrue(self.api("POST", "vigilancias/%d/quitar_tarea" % vid, {"confirmar": True})["borrada"])
        self.assertEqual(self.tareas, [])
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "vigilancias/%d/quitar_tarea" % vid, {"confirmar": True})
        # programación no válida: error claro
        with self.assertRaises(su.ErrorApi) as cm:
            self.api("PUT", "vigilancias/%d" % vid, {"programacion": {"reglas": [{"tipo": "intervalo", "dias": ["lun"],
                                                                                   "cada_min": 5}]}})
        self.assertIn("15 minutos", str(cm.exception))
        # solo a mano: no hay nada que programar
        self.api("PUT", "vigilancias/%d" % vid, {"programacion": {"reglas": []}})
        with self.assertRaises(su.ErrorApi) as cm:
            self.api("POST", "vigilancias/%d/programar" % vid)
        self.assertIn("no tiene horario", str(cm.exception))

    def test_compatibilidad_con_la_3_3(self):
        rid = self.alm.guardar(flujo_reporte())
        vid = self.alm.crear_vigilancia(reporte_id=rid, paso=2, frecuencia="horas", cada_horas=4)
        v = self.api("GET", "vigilancias/%d" % vid)["vigilancia"]
        self.assertEqual(v["cuando"], "todos los días cada 4 h")
        # la petición antigua (frecuencia) sigue dando el comando de siempre
        with mock.patch.object(programador, "MAX_TR", 2000):
            pr = self.api("POST", "vigilancias/%d/programar" % vid, {"frecuencia": "HORAS", "cada_horas": 4, "hora": "08:00"})
        self.assertIn("/SC HOURLY /MO 4", pr["comando"])
        # y sin frecuencia, con su programación (convertida de la antigua)
        pr = self.api("POST", "vigilancias/%d/programar" % vid)
        self.assertEqual(pr["descripcion"], "todos los días cada 4 h")
        self.assertIn("/XML", pr["comando"])
        # PUT con la frecuencia antigua
        v = self.api("PUT", "vigilancias/%d" % vid, {"frecuencia": "diaria", "hora": "06:30"})["vigilancia"]
        self.assertEqual((v["frecuencia"], v["hora"], v["cuando"]), ("diaria", "06:30", "todos los días a las 06:30"))
        self.assertEqual(self.llamadas, [])

    def test_programar_reporte_y_pagina(self):
        rid = self.alm.guardar(flujo_reporte())
        g = self.api("GET", "reportes/%d/programar" % rid)
        self.assertEqual((g["guardada"], g["existe"], g["tarea"]), (None, False, "BotWeb\\Portal (reporte)"))
        pr = self.api("POST", "reportes/%d/programar" % rid, {"programacion": EJEMPLO})
        self.assertFalse(pr["creada"])
        self.assertTrue(pr["programa"].endswith("--id %d --sin-ventana --oculto" % rid), pr["programa"])
        self.assertEqual(self.llamadas, [])
        self.assertIsNone(self.alm.programacion("reporte:%d" % rid))           # solo se guarda al crear la tarea
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "reportes/%d/programar" % rid, {"programacion": {"reglas": []}})
        self.api("POST", "reportes/%d/programar" % rid, {"programacion": EJEMPLO, "confirmar": True})
        g = self.api("GET", "reportes/%d/programar" % rid)
        self.assertEqual((g["guardada"], g["existe"]), (horario.normalizar(EJEMPLO), True))
        self.assertEqual(g["descripcion"], horario.describir(EJEMPLO))
        # el inicio enseña la tarea con su horario en español
        fila = [x for x in self.api("GET", "inicio")["proximas"] if x.get("nombre") == "Portal (reporte)"][0]
        self.assertEqual(fila["cuando_texto"], horario.describir(EJEMPLO))
        # se renombra el reporte y se vuelve a programar: sustituye a la tarea vieja
        self.alm.renombrar(rid, "Ventas")
        pr = self.api("POST", "reportes/%d/programar" % rid, {"programacion": EJEMPLO})
        self.assertEqual(pr["sustituye"], ["Portal (reporte)"])
        # quitar la tarea
        q = self.api("POST", "reportes/%d/quitar_tarea" % rid)
        self.assertEqual(q["tareas"], ["Portal (reporte)"])
        self.api("POST", "reportes/%d/quitar_tarea" % rid, {"confirmar": True})
        self.assertEqual(self.tareas, [])
        self.assertIsNone(self.alm.programacion("reporte:%d" % rid))
        # la forma antigua (frecuencia) sigue igual
        with mock.patch.object(programador, "MAX_TR", 2000):
            pr = self.api("POST", "reportes/%d/programar" % rid, {"frecuencia": "SEMANAL", "dias": ["MON"], "hora": "07:00"})
        self.assertIn("/SC WEEKLY /D MON", pr["comando"])
        # Página (con favorito)
        data = pagina_simple()
        data["favoritos"] = [{"nombre": "Mayorista", "valores": {}}]
        pid = self.alm.guardar_pagina("Portal – Reportes", data)
        g = self.api("POST", "paginas/%d/programar" % pid, {"favorito": "Mayorista", "consultar": True})
        self.assertEqual((g["guardada"], g["tarea"]), (None, "BotWeb\\Portal – Reportes - Mayorista"))
        mensual = {"reglas": [{"tipo": "mensual_semana", "semanas": [1], "dias": ["lun"], "horas": ["08:00"]}]}
        pr = self.api("POST", "paginas/%d/programar" % pid, {"favorito": "Mayorista", "programacion": mensual})
        self.assertIn('--pagina-id %d --favorito "Mayorista"' % pid, pr["programa"])
        self.assertEqual(pr["descripcion"], "el primer lunes de cada mes a las 08:00")
        self.api("POST", "paginas/%d/programar" % pid, {"favorito": "Mayorista", "programacion": mensual, "confirmar": True})
        self.assertIn("<ScheduleByMonthDayOfWeek>", self.llamadas[-1][-1])
        g = self.api("POST", "paginas/%d/programar" % pid, {"favorito": "Mayorista", "consultar": True})
        self.assertEqual((g["guardada"], g["existe"]), (horario.normalizar(mensual), True))
        self.api("POST", "paginas/%d/programar" % pid, {"favorito": "Mayorista", "quitar": True, "confirmar": True})
        self.assertEqual(self.tareas, [])


if __name__ == "__main__":
    unittest.main()
