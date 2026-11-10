"""Pruebas de la versión 3.7: «Avisos y vista» de lo programado (reportes, Páginas, vigilancias y correo).

- `horario`: el bloque `ejecucion` (avisar antes / al empezar / al terminar, en vivo o en segundo plano, la ventanita) se
  guarda junto a las reglas y se comprueba; las programaciones de antes (sin él) siguen igual.
- `programador`: con «Avisarme antes» los disparadores de la tarea de Windows se adelantan N minutos (también los que
  cruzan la medianoche: el día anterior; los mensuales se quedan en las 00:00) y el comando lleva `--aviso-antes N`,
  `--avisar-inicio`, `--avisar-fin`, `--ventanita` y `--visible`/`--oculto`.
- `almacen`: la tabla `en_curso` (lo que se ejecuta fuera de la interfaz) y la limpieza de procesos que ya no existen.
- `seguimiento` y la línea de comandos: el aviso previo con la espera (sin esperar de verdad: reloj falso), cancelar /
  empezar ya / ver en vivo, las notificaciones de empezar y terminar (con el resultado corto) y el progreso en la tabla.
- `servidor_ui`: «Programar…» con los avisos, el interruptor «En vivo / En segundo plano», lo de fuera en /api/inicio y
  el evento «externo».
- La ventanita (sin proceso aparte) y la interfaz con navegador oculto (Playwright).

Bases de datos temporales; ninguna notificación de Windows (notificador falso), ninguna tarea programada de verdad
(schtasks falso), ningún proceso de la ventanita, ninguna espera real.
"""

import contextlib
import datetime as dt
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import bot  # noqa: E402
from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from test_v33 import flujo_reporte  # noqa: E402
from webbot import avisos, horario, programador, seguimiento, ventanita  # noqa: E402
from webbot import ejecutor as mod_ejecutor  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen, ErrorAlmacen  # noqa: E402
from webbot.ejecutor import ResultadoEjecucion  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

NS = {"t": programador.NS_TAREA}
JUEVES = dt.datetime(2026, 10, 29, 10, 0)           # jueves 29/10/2026 10:00
AVISOS = {"avisar_antes": 5, "avisar_inicio": True, "avisar_fin": True, "en_vivo": False, "ventanita": True}


def _sin_schtasks(*a, **k):
    raise AssertionError("¡Una prueba intentó ejecutar schtasks de verdad!")


def _sin_ventanita(*a, **k):
    raise AssertionError("¡Una prueba intentó abrir la ventanita de verdad!")


class Reloj:
    """Reloj falso: `dormir` hace pasar el tiempo al momento."""

    def __init__(self, inicio):
        self.t = inicio
        self.dormido = 0.0

    def ahora(self):
        return self.t

    def dormir(self, s):
        self.dormido += s
        self.t += dt.timedelta(seconds=s)


class BaseSegura(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v37_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.toasts = []
        avisos.usar_notificador(lambda titulo, texto: self.toasts.append((titulo, texto)))
        self.addCleanup(avisos.usar_notificador, None)
        for objetivo, nombre, falso in ((programador, "_ejecutar", _sin_schtasks),
                                        (seguimiento, "abrir_ventanita_proceso", _sin_ventanita)):
            p = mock.patch.object(objetivo, nombre, falso)
            p.start()
            self.addCleanup(p.stop)
        self.ruta_db = os.path.join(self.tmp, "b.db")
        self.alm = Almacen(self.ruta_db)
        self.addCleanup(self.alm.cerrar)


# ============================================================================ horario: «Avisos y vista»
class TestProgramacion(unittest.TestCase):
    REGLA = {"tipo": "semanal", "dias": ["lun", "vie"], "horas": ["09:00"]}

    def test_se_guarda_y_se_comprueba(self):
        p = horario.normalizar({"reglas": [self.REGLA], "ejecucion": {"avisar_antes": "10", "en_vivo": 1}})
        self.assertEqual(p["ejecucion"], {"avisar_antes": 10, "avisar_inicio": True, "avisar_fin": True, "en_vivo": True,
                                          "ventanita": True})
        self.assertEqual(horario.desde_json(horario.a_json(p)), p)                    # ida y vuelta por JSON
        self.assertEqual(horario.ejecucion(p), p["ejecucion"])
        # las de antes: sin el bloque (y así se quedan)
        vieja = horario.normalizar({"reglas": [self.REGLA]})
        self.assertNotIn("ejecucion", vieja)
        self.assertIsNone(horario.ejecucion(vieja))
        self.assertEqual(programador.opciones_comando(vieja), {})
        # errores claros
        with self.assertRaises(horario.ErrorHorario) as cm:
            horario.normalizar({"reglas": [self.REGLA], "ejecucion": {"avisar_antes": 7}})
        self.assertIn("Avisarme antes", str(cm.exception))
        with self.assertRaises(horario.ErrorHorario) as cm:
            horario.normalizar({"reglas": [{"tipo": "intervalo", "dias": ["lun"], "cada_min": 15}],
                                "ejecucion": {"avisar_antes": 15}})
        self.assertIn("menos que «cada»", str(cm.exception))
        with self.assertRaises(horario.ErrorHorario):
            horario.normalizar({"reglas": [self.REGLA], "ejecucion": "sí"})

    def test_textos_avisos_y_vista(self):
        e = horario.normalizar({"reglas": [self.REGLA], "ejecucion": AVISOS})["ejecucion"]
        self.assertEqual(horario.describir_ejecucion(e),
                         "Avisa 5 min antes, al empezar y al terminar · en segundo plano · con la ventanita de progreso")
        self.assertEqual(horario.describir_ejecucion(dict(e, avisar_antes=0, avisar_inicio=False, avisar_fin=False,
                                                          en_vivo=True, ventanita=False)),
                         "Sin avisos · en vivo (navegador visible)")
        v = horario.vista({"reglas": [self.REGLA], "ejecucion": AVISOS}, ahora=JUEVES)
        self.assertEqual(v["ejecucion"], e)
        self.assertIn("5 min antes", v["ejecucion_texto"])
        # dos horas muy juntas y un mensual justo después de medianoche: se avisa (no es un error)
        a = horario.avisos({"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["09:00", "09:04"]},
                                       {"tipo": "mensual", "dias_mes": [1], "horas": ["00:02"]}], "ejecucion": AVISOS})
        self.assertTrue(any("muy seguidas (09:00 y 09:04)" in x for x in a), a)
        self.assertTrue(any("00:00" in x for x in a), a)

    def test_en_vivo_de_una_programacion_antigua(self):
        p = horario.con_en_vivo({"reglas": [self.REGLA]}, True)
        self.assertEqual(p["ejecucion"], dict(horario.EJECUCION_ANTIGUA, en_vivo=True))    # sin avisos, como antes
        p2 = horario.con_en_vivo(dict(p, ejecucion=AVISOS), True)
        self.assertEqual(p2["ejecucion"], dict(AVISOS, en_vivo=True))

    def test_siguiente_en(self):
        prog = {"reglas": [self.REGLA, {"tipo": "mensual", "dias_mes": [1], "horas": ["00:02"]}]}
        vie = dt.datetime(2026, 10, 30, 8, 55, 3)
        self.assertEqual(horario.siguiente_en(prog, vie, 5), dt.datetime(2026, 10, 30, 9, 0))
        self.assertIsNone(horario.siguiente_en(prog, dt.datetime(2026, 10, 30, 8, 0), 5))
        # el mensual de las 00:02 (la tarea se lanzó a las 00:00): faltan 2 minutos, no 5
        self.assertEqual(horario.siguiente_en(prog, dt.datetime(2026, 11, 1, 0, 0, 1), 5), dt.datetime(2026, 11, 1, 0, 2))


# ============================================================================ programador: disparadores adelantados
class TestXmlAdelantado(unittest.TestCase):
    def setUp(self):
        self.linea = programador.comando_bot(os.path.join(RAIZ, "bot.py"), ids=[3], python=r"C:\Py\pythonw.exe")

    def disparadores(self, prog):
        xml = programador.construir_xml_tarea(prog, self.linea, ahora=JUEVES, usuario="PC\\ana")
        raiz = ET.fromstring(xml)
        return xml, raiz.findall("t:Triggers/t:CalendarTrigger", NS)

    @staticmethod
    def dias(ct):
        return [x.tag.split("}")[1] for x in ct.find("t:ScheduleByWeek/t:DaysOfWeek", NS)]

    def test_sin_avisos_es_igual_que_antes(self):
        prog = {"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["09:00"]}]}
        a = programador.construir_xml_tarea(prog, self.linea, ahora=JUEVES, usuario="")
        b = programador.construir_xml_tarea(dict(prog, ejecucion=dict(AVISOS, avisar_antes=0)), self.linea, ahora=JUEVES,
                                            usuario="")
        self.assertEqual(a, b)
        self.assertIn("2026-10-29T09:00:00", a)

    def test_adelanta_y_cruza_la_medianoche(self):
        prog = {"reglas": [{"tipo": "semanal", "dias": ["lun", "vie"], "horas": ["00:03", "09:00"]},
                           {"tipo": "intervalo", "dias": ["lun"], "cada_min": 60, "desde": "00:00", "hasta": "05:00"},
                           {"tipo": "mensual", "dias_mes": [1, "ultimo"], "horas": ["00:02", "08:00"]},
                           {"tipo": "mensual_semana", "semanas": [1], "dias": ["lun"], "horas": ["00:04"]}],
                "inicio": "2026-11-02", "fin": "2026-12-31", "ejecucion": AVISOS}
        xml, cts = self.disparadores(prog)
        inicio = [c.find("t:StartBoundary", NS).text for c in cts]
        self.assertEqual(inicio, [
            "2026-11-01T23:58:00",          # lunes y viernes 00:03 → el día anterior (domingo y jueves) a las 23:58
            "2026-11-02T08:55:00",          # 09:00 → 08:55
            "2026-11-01T23:55:00",          # cada 1 h desde 00:00 → desde las 23:55 del domingo
            "2026-11-02T00:00:00",          # mensual 00:02 → se queda a las 00:00 del mismo día
            "2026-11-02T07:55:00",          # mensual 08:00 → 07:55
            "2026-11-02T00:00:00"])         # el primer lunes 00:04 → 00:00
        self.assertEqual(self.dias(cts[0]), ["Thursday", "Sunday"])
        self.assertEqual(self.dias(cts[1]), ["Monday", "Friday"])
        self.assertEqual(self.dias(cts[2]), ["Sunday"])
        rep = cts[2].find("t:Repetition", NS)
        self.assertEqual((rep.find("t:Interval", NS).text, rep.find("t:Duration", NS).text), ("PT1H", "PT5H1M"))
        self.assertEqual([d.text for d in cts[3].findall("t:ScheduleByMonth/t:DaysOfMonth/t:Day", NS)], ["1", "Last"])
        # el límite también se adelanta (si no, el aviso de las 00:03 del día siguiente al fin se lanzaría)
        self.assertTrue(all(c.find("t:EndBoundary", NS).text == "2026-12-31T23:54:59" for c in cts))
        # textos para la confirmación
        textos = [d["texto"] for d in programador.disparadores(prog, JUEVES)]
        self.assertIn("empieza el día anterior a las 23:58 para avisarte 5 min antes", textos[0])
        self.assertIn("empieza a las 08:55", textos[1])
        self.assertIn("no puede empezar el día anterior", textos[3])
        # siempre lo mismo (se puede comprobar)
        self.assertEqual(xml, self.disparadores(prog)[0])
        # sin fecha de inicio: hoy (o ayer, si cruza la medianoche)
        _xml, cts = self.disparadores({"reglas": [{"tipo": "semanal", "dias": ["dom"], "horas": ["00:01"]}],
                                       "ejecucion": dict(AVISOS, avisar_antes=30)})
        self.assertEqual(cts[0].find("t:StartBoundary", NS).text, "2026-10-28T23:31:00")
        self.assertEqual(self.dias(cts[0]), ["Saturday"])

    def test_comando_con_los_avisos(self):
        prog = {"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["09:00"]}], "ejecucion": AVISOS}
        bot_py = os.path.join(RAIZ, "bot.py")
        linea = programador.comando_bot(bot_py, ids=[3], python="py", **programador.opciones_comando(prog))
        self.assertTrue(linea.endswith("--id 3 --sin-ventana --oculto --aviso-antes 5 --avisar-inicio --avisar-fin "
                                       "--ventanita"), linea)
        vivo = dict(prog, ejecucion=dict(AVISOS, en_vivo=True, avisar_antes=0, ventanita=False))
        for kw, fin in (({"vigilancia_id": 7}, "--vigilancia-id 7 --vigilar --visible --avisar-inicio --avisar-fin"),
                        ({"correo_id": 2}, "--correo-id 2 --visible --avisar-inicio --avisar-fin"),
                        ({"pagina_id": 4, "favorito": "Mayorista"},
                         '--pagina-id 4 --favorito "Mayorista" --sin-ventana --visible --avisar-inicio --avisar-fin')):
            linea = programador.comando_bot(bot_py, python="py", **dict(kw, **programador.opciones_comando(vivo)))
            self.assertTrue(linea.endswith(fin), linea)
        # la línea de comandos entiende todo
        a = bot.analizar_argumentos(["--id", "3", "--sin-ventana", "--oculto", "--aviso-antes", "5", "--avisar-inicio",
                                     "--avisar-fin", "--ventanita"])
        self.assertEqual((a.aviso_antes, a.avisar_inicio, a.avisar_fin, a.ventanita), (5, True, True, True))

    @unittest.skipUnless(os.name == "nt", "solo en Windows")
    def test_el_programador_de_windows_acepta_el_xml_adelantado(self):
        """El propio Programador de tareas lee el XML (`NewTask(0).XmlText`, que NO registra ninguna tarea)."""
        prog = {"reglas": [{"tipo": "semanal", "dias": ["lun", "vie"], "horas": ["00:03"]},
                           {"tipo": "mensual", "dias_mes": [1], "horas": ["00:02"]}], "fin": "2026-12-31",
                "ejecucion": AVISOS}
        linea = programador.comando_bot(os.path.join(RAIZ, "bot.py"), ids=[3], python=r"C:\Py\pythonw.exe",
                                        **programador.opciones_comando(prog))
        xml = programador.construir_xml_tarea(prog, linea, "Prueba", ahora=JUEVES, nombre="Prueba #1")
        ruta = os.path.join(tempfile.mkdtemp(prefix="botweb_v37x_"), "t.xml")
        self.addCleanup(shutil.rmtree, os.path.dirname(ruta), True)
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
        self.assertIn("OK 2", r.stdout, r.stderr)


# ============================================================================ almacen: en_curso
class TestEnCurso(BaseSegura):
    def test_filas_y_limpieza(self):
        a = self.alm.crear_en_curso(tipo="reporte", nombre="Portal", objetivo_id=3, total=8)
        self.alm.actualizar_en_curso(a, paso=3, texto="Clic en «Generar»")
        f = self.alm.en_curso_id(a)
        self.assertEqual((f["tipo"], f["nombre"], f["paso"], f["total"], f["texto"], f["estado"], f["pid"]),
                         ("reporte", "Portal", 3, 8, "Clic en «Generar»", "en_curso", os.getpid()))
        self.assertFalse(f["terminado"])
        for k in ("id", "tipo", "nombre", "paso", "total", "texto", "inicio", "actualizado", "pid", "estado"):
            self.assertIn(k, f)
        # lo pide el usuario
        self.assertTrue(self.alm.pedir_en_curso(a, "detener"))
        self.assertEqual(self.alm.en_curso_id(a)["pedido"], "detener")
        with self.assertRaises(ErrorAlmacen):
            self.alm.pedir_en_curso(a, "borrar todo")
        with self.assertRaises(ErrorAlmacen):
            self.alm.actualizar_en_curso(a, estado="raro")
        # un proceso que ya no existe: su fila se borra sola
        b = self.alm.crear_en_curso(tipo="correo", nombre="Correo: X", pid=999999)
        self.assertEqual([x["id"] for x in self.alm.lista_en_curso(vivo=lambda pid: pid == os.getpid())], [a])
        self.assertIsNone(self.alm.en_curso_id(b))
        # terminada: se ve un rato (la ventanita enseña el resultado) y luego se borra
        self.alm.actualizar_en_curso(a, estado="ok", resumen="terminó bien: 1 archivo")
        self.assertFalse(self.alm.pedir_en_curso(a, "detener"))
        self.assertEqual(len(self.alm.lista_en_curso()), 1)
        luego = dt.datetime.now() + dt.timedelta(minutes=5)
        self.assertEqual(self.alm.lista_en_curso(ahora=luego), [])
        self.assertIsNone(self.alm.en_curso_id(a))

    def test_pid_vivo(self):
        from webbot.almacen import pid_vivo
        self.assertTrue(pid_vivo(os.getpid()))
        self.assertFalse(pid_vivo(None))
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self.assertFalse(pid_vivo(p.pid))

    def test_una_base_de_datos_anterior_gana_la_tabla(self):
        self.alm.cerrar()
        import sqlite3
        con = sqlite3.connect(self.ruta_db)
        con.execute("DROP TABLE en_curso")
        con.commit()
        con.close()
        alm = Almacen(self.ruta_db)
        self.addCleanup(alm.cerrar)
        self.assertEqual(alm.lista_en_curso(), [])


# ============================================================================ seguimiento
class R:
    """Resultados falsos (con los atributos de los de verdad)."""

    @staticmethod
    def ejecucion(ok=True, archivos=(), paso=None, error="", detenido=False):
        r = ResultadoEjecucion()
        r.ok, r.archivos, r.paso_fallido, r.error, r.detenido = ok, list(archivos), paso, error, detenido
        return r


class TestResumenCorto(unittest.TestCase):
    def test_textos(self):
        from webbot.correo import ResultadoCorreo
        from webbot.paginas import ResultadoPagina
        from webbot.vigilancia import ResultadoRevision
        rc = seguimiento.resumen_corto
        self.assertEqual(rc([R.ejecucion(archivos=["a.xlsx"])]), "terminó bien: 1 archivo")
        self.assertEqual(rc([R.ejecucion(archivos=["a", "b"]), R.ejecucion(archivos=["c"])]), "terminó bien: 3 archivos")
        self.assertEqual(rc([R.ejecucion()]), "terminó bien")
        self.assertEqual(rc([R.ejecucion(ok=False, paso=5, error="No apareció «Generar»")]),
                         "falló en el paso 5: No apareció «Generar»")
        self.assertEqual(rc([R.ejecucion(ok=False, detenido=True)]), "se detuvo (lo paraste tú)")
        v = ResultadoRevision(1, "Portal")
        v.ok = True
        self.assertEqual(rc([v]), "nada nuevo")
        v.nuevas = ["45 - 2026"]
        v.descargas = [("45 - 2026", R.ejecucion(archivos=["c.xlsx"]))]
        self.assertEqual(rc([v]), "novedad: «45 - 2026»; 1 archivo")
        c = ResultadoCorreo(2, "Ventas")
        c.ok = True
        self.assertEqual(rc([c]), "nada nuevo")
        c.procesados = [{"archivos": ["x.pdf"], "errores": [], "valores": []}]
        self.assertEqual(rc([c]), "1 correo procesado; 1 archivo")
        c.ok, c.error = False, "la sesión caducó"
        self.assertEqual(rc([c]), "falló: la sesión caducó")
        p = ResultadoPagina("Portal")
        p.n = 1
        p.resultados = [("con lo elegido", R.ejecucion(archivos=["p.xlsx"]))]
        p.archivos = ["p.xlsx"]
        self.assertEqual(rc([p]), "terminó bien: 1 archivo")
        self.assertEqual(rc([], 2), "no se pudo empezar (mira el registro)")
        self.assertEqual(seguimiento.duracion_texto(80), "1 min 20 s")
        self.assertEqual(seguimiento.duracion_texto(3900), "1 h 5 min")


class TestSeguimiento(BaseSegura):
    def seg(self, reloj, **kw):
        kw.setdefault("aviso_antes", 5)
        return seguimiento.Seguimiento(self.alm, "reporte", "PORTAL", 3, ahora=reloj.ahora, dormir=reloj.dormir,
                                       abrir_ventanita=lambda db, fila: self.ventanitas.append((db, fila)), **kw)

    def setUp(self):
        super().setUp()
        self.ventanitas = []

    def test_avisa_espera_y_empieza(self):
        reloj = Reloj(dt.datetime(2026, 10, 30, 12, 45, 0))
        s = self.seg(reloj, avisar_inicio=True, avisar_fin=True, ventanita=True)
        self.assertTrue(s.esperar_antes())
        self.assertEqual(reloj.t, dt.datetime(2026, 10, 30, 12, 50, 0))               # esperó hasta la hora
        self.assertEqual(self.toasts[0][0], "«PORTAL» se ejecutará en 5 min, a las 12:50")
        self.assertIn("segundo plano", self.toasts[0][1])
        self.assertEqual(self.ventanitas, [(self.alm.ruta, s.fila)])                  # la ventanita, mientras espera
        self.assertEqual(self.alm.en_curso_id(s.fila)["estado"], "esperando")
        s.empezar()
        self.assertEqual(self.toasts[1][0], "«PORTAL» se está ejecutando")
        f = self.alm.en_curso_id(s.fila)
        self.assertEqual((f["estado"], f["texto"]), ("en_curso", "Empezando…"))
        s.nuevo_flujo(4)
        s.progreso(0, "inicio", "Abrir la página")
        s.progreso(1, "inicio", "Clic en «Generar»")
        f = self.alm.en_curso_id(s.fila)
        self.assertEqual((f["paso"], f["total"], f["texto"]), (2, 4, "Clic en «Generar»"))
        self.assertEqual(ventanita.vista(f)["texto"], "Paso 2 de 4: Clic en «Generar»")
        s.resultado(R.ejecucion(archivos=["Portal 2026-10-30.xlsx"]))
        s.terminar(0)
        f = self.alm.en_curso_id(s.fila)
        self.assertEqual((f["estado"], f["resumen"], f["paso"]), ("ok", "terminó bien: 1 archivo", 4))
        self.assertEqual(self.toasts[2][0], "«PORTAL» terminó")
        self.assertTrue(self.toasts[2][1].startswith("Terminó bien: 1 archivo (tardó "), self.toasts[2][1])
        self.assertEqual(len(self.ventanitas), 1)                                     # una sola ventanita

    def test_espera_hasta_la_hora_programada(self):
        # mensual a las 00:02: la tarea se lanzó a las 00:00 (no puede ser el día anterior) → espera 2 min, no 5
        prog = {"reglas": [{"tipo": "mensual", "dias_mes": [1], "horas": ["00:02"]}], "ejecucion": AVISOS}
        reloj = Reloj(dt.datetime(2026, 11, 1, 0, 0, 0))
        s = self.seg(reloj, programacion=prog)
        self.assertTrue(s.esperar_antes())
        self.assertEqual(reloj.t, dt.datetime(2026, 11, 1, 0, 2))
        self.assertEqual(self.toasts[0][0], "«PORTAL» se ejecutará en 2 min, a las 00:02")

    def test_cancelar_empezar_ya_y_ver_en_vivo(self):
        reloj = Reloj(dt.datetime(2026, 10, 30, 12, 45, 0))
        s = self.seg(reloj)
        dormir = reloj.dormir

        def dormir_y_pedir(seg):                      # a los 10 s, el usuario pulsa «Cancelar esta ejecución»
            dormir(seg)
            if reloj.dormido >= 10 and s.fila is not None and not self.alm.en_curso_id(s.fila)["pedido"]:
                self.alm.pedir_en_curso(s.fila, "cancelar")
        s._dormir = dormir_y_pedir
        self.assertFalse(s.esperar_antes())
        self.assertLess(reloj.dormido, 12)
        f = self.alm.en_curso_id(s.fila)
        self.assertEqual((f["estado"], f["pedido"]), ("cancelado", ""))
        self.assertEqual(s.terminar(0), "cancelada: esta vez no se ejecuta")
        self.assertEqual(len(self.toasts), 1)                                         # solo el aviso previo
        # «Ver en vivo» y luego «Empezar ya»
        reloj = Reloj(dt.datetime(2026, 10, 30, 12, 45, 0))
        s = self.seg(reloj)
        pedidos = iter(["en_vivo", "ya"])

        def dormir2(seg):
            reloj.dormir(seg)
            p = next(pedidos, None)
            if p:
                self.alm.pedir_en_curso(s.fila, p)
        s._dormir = dormir2
        self.assertTrue(s.esperar_antes())
        self.assertTrue(s.visible)
        self.assertLess(reloj.dormido, 2)
        self.assertTrue(self.alm.en_curso_id(s.fila)["visible"])

    def test_sin_avisos_no_avisa_ni_espera(self):
        reloj = Reloj(dt.datetime(2026, 10, 30, 12, 45, 0))
        s = self.seg(reloj, aviso_antes=0)
        self.assertTrue(s.esperar_antes())
        self.assertEqual(reloj.dormido, 0)
        s.empezar()
        s.terminar(1)
        self.assertEqual(self.toasts, [])
        self.assertEqual(self.ventanitas, [])
        self.assertEqual(self.alm.en_curso_id(s.fila)["estado"], "error")

    def test_detener_desde_la_ventanita(self):
        s = self.seg(Reloj(dt.datetime(2026, 10, 30, 12, 45)), aviso_antes=0, cada=0.05)
        s.empezar()
        self.alm.pedir_en_curso(s.fila, "detener")
        self.assertTrue(s.detener.wait(5))                                            # llega al Event del ejecutor
        s.resultado(R.ejecucion(ok=False, detenido=True))
        s.terminar(1)
        self.assertEqual(self.alm.en_curso_id(s.fila)["estado"], "detenido")


# ============================================================================ la línea de comandos
class FalsoEjecutor:
    """No abre el navegador: va diciendo los pasos por `progreso`; «Mal» falla en el paso 2; «Lento» espera a que lo
    paren (Detener de la ventanita)."""
    vistos = []

    def __init__(self, flujo, carpeta_perfil=None, **kw):
        self.flujo, self.kw = flujo, kw
        FalsoEjecutor.vistos.append({"nombre": flujo.nombre, "oculto": kw.get("oculto"),
                                     "progreso": kw.get("progreso") is not None})

    def ejecutar(self):
        r = ResultadoEjecucion()
        r.total = len(self.flujo.pasos)
        r.ruta_log = "x.log"
        prog = self.kw.get("progreso") or (lambda *a: None)
        for i, p in enumerate(self.flujo.pasos):
            prog(i, "inicio", p.descripcion())
            if self.flujo.nombre == "Mal" and i == 1:
                r.ok, r.paso_fallido, r.error = False, 2, "no apareció «Generar»"
                return r
            if self.flujo.nombre == "Lento" and i == 1:
                if self.kw["detener"].wait(10):
                    r.detenido, r.paso_fallido = True, 2
                    return r
            prog(i, "ok", "")
        r.ok, r.archivos = True, ["Uno 2026-10-30.xlsx"]
        return r


class TestLineaDeComandos(BaseSegura):
    def setUp(self):
        super().setUp()
        FalsoEjecutor.vistos = []
        p = mock.patch.object(mod_ejecutor, "Ejecutor", FalsoEjecutor)
        p.start()
        self.addCleanup(p.stop)
        self.reloj = Reloj(dt.datetime(2026, 10, 30, 12, 45, 0))
        for nombre, falso in (("ahora_real", self.reloj.ahora), ("dormir_real", self.reloj.dormir)):
            p = mock.patch.object(seguimiento, nombre, falso)
            p.start()
            self.addCleanup(p.stop)
        self.ventanitas = []
        p = mock.patch.object(seguimiento, "abrir_ventanita_proceso", lambda db, fila: self.ventanitas.append(fila))
        p.start()
        self.addCleanup(p.stop)

        def flujo(nombre):
            return Flujo(nombre=nombre, url="http://ejemplo/", pasos=[
                Paso("abrir_url", url="http://ejemplo/"), Paso("clic", selectores=["#a"], objetivo="Generar"),
                Paso("clic", selectores=["#b"], objetivo="Descargar")])
        self.uno = self.alm.guardar(flujo("Uno"))
        self.mal = self.alm.guardar(flujo("Mal"))
        self.lento = self.alm.guardar(flujo("Lento"))

    def correr(self, *argumentos):
        salida = io.StringIO()
        base = ["--db", self.ruta_db, "--carpeta-flujos", os.path.join(self.tmp, "flujos"),
                "--perfil", os.path.join(self.tmp, "perfiles"), "--registros", os.path.join(self.tmp, "reg")]
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = bot.principal(list(argumentos) + base)
        return codigo, salida.getvalue()

    def fila(self):
        filas = self.alm._con().execute("SELECT id FROM en_curso ORDER BY id DESC").fetchall()
        return self.alm.en_curso_id(filas[0][0]) if filas else None

    def test_aviso_antes_inicio_y_fin(self):
        codigo, salida = self.correr("--id", str(self.uno), "--sin-ventana", "--oculto", "--aviso-antes", "5",
                                     "--avisar-inicio", "--avisar-fin", "--ventanita")
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(self.reloj.t, dt.datetime(2026, 10, 30, 12, 50))              # esperó 5 min (reloj falso)
        self.assertEqual([t for t, _x in self.toasts], ["«Uno» se ejecutará en 5 min, a las 12:50",
                                                        "«Uno» se está ejecutando", "«Uno» terminó"])
        self.assertTrue(self.toasts[2][1].startswith("Terminó bien: 1 archivo"), self.toasts[2])
        f = self.fila()
        self.assertEqual((f["tipo"], f["nombre"], f["objetivo_id"], f["estado"], f["paso"], f["total"]),
                         ("reporte", "Uno", self.uno, "ok", 3, 3))
        self.assertEqual(self.ventanitas, [f["id"]])
        self.assertEqual(FalsoEjecutor.vistos, [{"nombre": "Uno", "oculto": True, "progreso": True}])
        self.assertEqual(self.alm.ultima_ejecucion(self.uno)["resultado"], "ok")           # el historial, como siempre

    def test_el_fallo_en_el_aviso_del_final(self):
        codigo, _s = self.correr("--id", str(self.mal), "--sin-ventana", "--avisar-fin")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.toasts, [("«Mal» falló", self.toasts[0][1])])
        self.assertTrue(self.toasts[0][1].startswith("Falló en el paso 2: no apareció «Generar»"), self.toasts[0])
        self.assertEqual(self.reloj.dormido, 0)
        self.assertEqual(self.fila()["estado"], "error")

    def test_ver_en_vivo_mientras_espera(self):
        dormir = self.reloj.dormir

        def pedir(seg):
            dormir(seg)
            f = self.fila()
            if f and f["estado"] == "esperando" and not f["visible"]:
                self.alm.pedir_en_curso(f["id"], "en_vivo")
        with mock.patch.object(seguimiento, "dormir_real", pedir):
            codigo, _s = self.correr("--id", str(self.uno), "--sin-ventana", "--oculto", "--aviso-antes", "1")
        self.assertEqual(codigo, 0)
        self.assertEqual(FalsoEjecutor.vistos[0]["oculto"], False)                      # se abrió visible

    def test_detener_desde_la_ventanita(self):
        resultado = {}

        def correr():
            resultado["codigo"] = self.correr("--id", str(self.lento), "--sin-ventana", "--avisar-fin")[0]
        hilo = threading.Thread(target=correr)
        hilo.start()
        fin = time.monotonic() + 10
        otra = Almacen(self.ruta_db)                       # la ventanita: otro proceso, otra conexión
        self.addCleanup(otra.cerrar)
        while time.monotonic() < fin:
            f = self.fila()
            if f and f["paso"] == 2:
                otra.pedir_en_curso(f["id"], "detener")
                break
            time.sleep(0.05)
        hilo.join(15)
        self.assertEqual(resultado.get("codigo"), 1)
        self.assertEqual(self.fila()["estado"], "detenido")
        self.assertEqual(self.toasts[-1][0], "«Lento» se detuvo")

    def test_sin_opciones_es_como_antes(self):
        codigo, _s = self.correr("--id", str(self.uno), "--sin-ventana")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.toasts, [])
        self.assertEqual(self.ventanitas, [])
        self.assertEqual(self.reloj.dormido, 0)
        self.assertEqual(self.fila()["estado"], "ok")              # (pero la interfaz ve su progreso)
        # una tarea antigua con un reporte que no existe: el mismo error de siempre
        codigo, salida = self.correr("--id", "99", "--sin-ventana")
        self.assertEqual(codigo, 2)
        self.assertIn("No existe el reporte número 99", salida)


# ============================================================================ la interfaz (API)
class BaseApi(BaseSegura):
    def setUp(self):
        super().setUp()
        self.tareas = []
        self.llamadas = []

        def ejecutar(cmd):
            self.llamadas.append(list(cmd))
            if "/XML" in cmd:
                with open(cmd[cmd.index("/XML") + 1], "rb") as f:
                    self.llamadas[-1].append(f.read().decode("utf-16"))
                nombre = cmd[cmd.index("/TN") + 1].split("\\", 1)[1]
                if nombre not in [t["nombre"] for t in self.tareas]:
                    self.tareas.append({"nombre": nombre, "proxima": "30/10/2026 9:00:00", "estado": "Listo"})
            elif "/Delete" in cmd:
                nombre = cmd[cmd.index("/TN") + 1].split("\\", 1)[1]
                self.tareas[:] = [t for t in self.tareas if t["nombre"] != nombre]
            return 0, "CORRECTO"
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                                 listar_tareas=lambda: list(self.tareas), oculto_forzado=True, ejecutar_tareas=ejecutar)

    def api(self, metodo, ruta, datos=None, q=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, q or {})

    def xml(self):
        return [ll[-1] for ll in self.llamadas if "/XML" in ll][-1]


class TestApi(BaseApi):
    PROG = {"reglas": [{"tipo": "semanal", "dias": ["lun", "mar", "mie", "jue", "vie"], "horas": ["09:00"]}],
            "ejecucion": AVISOS}

    def test_programar_reporte_con_avisos_y_el_interruptor(self):
        rid = self.alm.guardar(flujo_reporte())
        pr = self.api("POST", "reportes/%d/programar" % rid, {"programacion": self.PROG})
        self.assertTrue(pr["programa"].endswith("--id %d --sin-ventana --oculto --aviso-antes 5 --avisar-inicio "
                                                "--avisar-fin --ventanita" % rid), pr["programa"])
        self.assertIn("empieza a las 08:55 para avisarte 5 min antes", pr["disparadores"][0])
        self.assertEqual((pr["en_vivo"], pr["ejecucion"]), (False, AVISOS))
        self.assertIn("5 min antes", pr["ejecucion_texto"])
        self.assertIn("T08:55:00", pr["xml"])
        self.assertEqual(self.llamadas, [])
        self.api("POST", "reportes/%d/programar" % rid, {"programacion": self.PROG, "confirmar": True})
        self.assertEqual(self.alm.programacion("reporte:%d" % rid)["programacion"]["ejecucion"], AVISOS)
        # «Lo programado» del Centro de control
        prog = [x for x in self.api("GET", "inicio")["programados"] if x["clave"] == "reporte:%d" % rid][0]
        self.assertEqual((prog["en_vivo"], prog["tiene_tarea"], prog["tipo"]), (False, True, "reporte"))
        # el interruptor: en vivo → la tarea pasa a --visible (se sustituye)
        r = self.api("POST", "en_vivo", {"clave": "reporte:%d" % rid, "en_vivo": True})
        self.assertEqual((r["en_vivo"], r["tarea_actualizada"]), (True, True))
        self.assertIn("--sin-ventana --visible --aviso-antes 5", self.xml())
        self.assertTrue(self.alm.programacion("reporte:%d" % rid)["programacion"]["ejecucion"]["en_vivo"])
        self.assertEqual(len(self.tareas), 1)
        r = self.api("POST", "en_vivo", {"clave": "reporte:%d" % rid, "en_vivo": False})
        self.assertIn("--sin-ventana --oculto --aviso-antes 5", self.xml())
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "en_vivo", {"clave": "reporte:999", "en_vivo": True})

    def test_programacion_antigua_y_vigilancia(self):
        rid = self.alm.guardar(flujo_reporte())
        vieja = {"reglas": self.PROG["reglas"]}
        pr = self.api("POST", "reportes/%d/programar" % rid, {"programacion": vieja})
        self.assertTrue(pr["programa"].endswith("--id %d --sin-ventana --oculto" % rid), pr["programa"])    # como antes
        self.assertIn("T09:00:00", pr["xml"])
        self.assertIsNone(pr["ejecucion"])
        # una vigilancia con horario y tarea: el interruptor la pasa a en vivo (solo eso: sin avisos, como antes)
        vid = self.alm.crear_vigilancia(reporte_id=rid, paso=2, programacion=vieja)
        self.api("POST", "vigilancias/%d/programar" % vid, {"confirmar": True})
        self.assertIn("--vigilancia-id %d --vigilar --oculto</Arguments>" % vid, self.xml())
        r = self.api("POST", "en_vivo", {"clave": "vigilancia:%d" % vid, "en_vivo": True})
        self.assertTrue(r["tarea_actualizada"])
        self.assertIn("--vigilancia-id %d --vigilar --visible</Arguments>" % vid, self.xml())
        self.assertEqual(self.alm.vigilancia_id(vid)["programacion"]["ejecucion"],
                         dict(horario.EJECUCION_ANTIGUA, en_vivo=True))

    def test_lo_de_fuera_en_el_inicio_y_en_los_eventos(self):
        f = self.alm.crear_en_curso(tipo="reporte", nombre="Portal", total=4)
        self.alm.actualizar_en_curso(f, paso=2, texto="Clic en «Generar»")
        ini = self.api("GET", "inicio")
        self.assertEqual([(x["nombre"], x["paso"], x["total"]) for x in ini["externos"]], [("Portal", 2, 4)])
        self.assertEqual(self.api("GET", "en_curso")["lista"][0]["id"], f)
        ev = self.api("GET", "eventos", q={"desde": ["0"], "espera": ["0"]})["eventos"]
        self.assertTrue(any(e["tipo"] == "externo" for e in ev))         # (lo emitió el inicio: la lista era nueva)
        ultimo = max(e["seq"] for e in ev)
        self.alm.actualizar_en_curso(f, paso=3, texto="Descargar")
        self.app._externos_cuando = 0
        ev = self.api("GET", "eventos", q={"desde": [str(ultimo)], "espera": ["2"]})["eventos"]
        ext = [e for e in ev if e["tipo"] == "externo"]
        self.assertEqual(ext[0]["lista"][0]["paso"], 3)
        # Detener desde la interfaz
        self.api("POST", "en_curso/%d/detener" % f)
        self.assertEqual(self.alm.en_curso_id(f)["pedido"], "detener")
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "en_curso/%d/borrar" % f)
        self.alm.actualizar_en_curso(f, estado="ok", resumen="terminó bien")
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "en_curso/%d/detener" % f)


# ============================================================================ la ventanita
class TestVentanita(unittest.TestCase):
    AHORA = dt.datetime(2026, 10, 30, 12, 47, 30)

    def test_vista(self):
        base = {"nombre": "PORTAL", "inicio": "2026-10-30 12:45:00", "empieza": "2026-10-30 12:50:00", "visible": False}
        v = ventanita.vista(dict(base, estado="esperando"), self.AHORA)
        self.assertEqual(v["texto"], "Se ejecutará a las 12:50 (en segundo plano)")
        self.assertEqual(v["botones"], ["en_vivo", "ya", "cancelar"])
        self.assertEqual(v["tiempo"], "Empieza dentro de 2:30")
        self.assertAlmostEqual(v["pct"], 50.0)
        self.assertEqual(ventanita.vista(dict(base, estado="esperando", visible=True), self.AHORA)["botones"],
                         ["ya", "cancelar"])
        v = ventanita.vista(dict(base, estado="en_curso", paso=3, total=8, texto="Clic en «Generar»", segundos=83))
        self.assertEqual((v["texto"], v["pct"], v["botones"]), ("Paso 3 de 8: Clic en «Generar»", 37.5, ["detener"]))
        self.assertEqual(v["tiempo"], "Lleva 1:23 · en segundo plano")
        v = ventanita.vista(dict(base, estado="en_curso", paso=0, total=0, texto="Revisando el correo", segundos=5))
        self.assertIsNone(v["pct"])                       # sin pasos que contar: barra que va y viene
        v = ventanita.vista(dict(base, estado="ok", resumen="terminó bien: 1 archivo", segundos=95))
        self.assertEqual((v["texto"], v["final"], v["botones"], v["tiempo"]),
                         ("Terminó bien: 1 archivo", True, ["cerrar"], "Tardó 1:35"))
        self.assertTrue(ventanita.vista(None)["cerrar"])

    def test_ventana_tk(self):
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as e:      # noqa: BLE001
            self.skipTest("tkinter sin escritorio: %s" % e)
        def destruir():
            try:
                root.destroy()
            except tk.TclError:
                pass
        self.addCleanup(destruir)
        root.withdraw()
        fila = {"nombre": "PORTAL", "estado": "en_curso", "paso": 2, "total": 4, "texto": "Clic", "segundos": 3,
                "inicio": "2026-10-30 12:45:00"}
        pedidos = []
        v = ventanita.Ventanita(root, lambda: fila, pedidos.append, cerrar_tras=0)
        self.assertTrue(v.actualizar())
        self.assertEqual(v.lbl_texto.cget("text"), "Paso 2 de 4: Clic")
        self.assertEqual(float(v.barra["value"]), 50.0)
        botones = v.zona_botones.winfo_children()
        self.assertEqual([b.cget("text") for b in botones], ["Detener"])
        botones[0].invoke()
        self.assertEqual(pedidos, ["detener"])
        fila.update(estado="ok", resumen="terminó bien: 1 archivo")
        self.assertTrue(v.actualizar())                   # enseña el resultado…
        self.assertEqual(v.lbl_texto.cget("text"), "Terminó bien: 1 archivo")
        self.assertFalse(v.actualizar())                  # …y se cierra sola
        with self.assertRaises(tk.TclError):
            root.winfo_exists()

    def test_sin_escritorio_no_pasa_nada(self):
        with mock.patch("tkinter.Tk", side_effect=RuntimeError("no display")):
            tmp = tempfile.mkdtemp(prefix="botweb_v37v_")
            self.addCleanup(shutil.rmtree, tmp, True)
            self.assertEqual(ventanita.principal(os.path.join(tmp, "b.db"), 1), 0)


# ============================================================================ la interfaz (navegador oculto)
@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestInterfaz(BaseApi):
    def setUp(self):
        super().setUp()
        from webbot import secretos
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        self.rid = self.alm.guardar(Flujo(nombre="Ventas", url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"), Paso("clic", selectores=["#a"], objetivo="Generar")]))
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)
        self.addCleanup(self.app.detener)

    def navegador(self):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self.addCleanup(self._p.stop)
        nav = self._p.chromium.launch(channel="chrome", headless=True)
        self.addCleanup(nav.close)
        pg = nav.new_page(viewport={"width": 1366, "height": 900})
        self.errores = []
        pg.on("console", lambda m: self.errores.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: self.errores.append(str(e)))
        return pg

    def test_programar_con_avisos_y_vista(self):
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("editor/%d" % self.rid), wait_until="load")
        pg.click("#contenido button:has-text('Programar…')", timeout=15000)
        pg.wait_for_selector(".modal [data-cuando-avisos]", timeout=15000)
        bloque = ".modal [data-cuando-avisos]"
        self.assertIn("Avisos y vista", pg.locator(bloque + " > summary").inner_text())
        # lo de por defecto de una programación nueva
        self.assertEqual(pg.locator(bloque + " select[data-ejec-antes]").input_value(), "5")
        self.assertTrue(pg.locator(bloque + " input[data-ejec='avisar_inicio']").is_checked())
        self.assertTrue(pg.locator(bloque + " input[data-ejec='avisar_fin']").is_checked())
        self.assertTrue(pg.locator(bloque + " input[data-ejec-vista='fondo']").is_checked())
        self.assertTrue(pg.locator(bloque + " input[data-ejec='ventanita']").is_checked())
        textos = pg.locator(bloque).inner_text()
        for t in ("Avisarme antes", "Avisar cuando empieza", "Avisar cuando termina (con el resultado)",
                  "Ver la ejecución en vivo (navegador visible)", "En segundo plano (oculto)",
                  "Mostrar una ventanita con la barra de progreso"):
            self.assertIn(t, textos)
        # 10 minutos antes, en vivo, sin aviso al empezar
        pg.select_option(bloque + " select[data-ejec-antes]", "10")
        pg.click(bloque + " input[data-ejec='avisar_inicio']")
        pg.click(bloque + " input[data-ejec-vista='vivo']")
        pg.wait_for_function("() => /10 min antes/.test(document.querySelector('.modal [data-cuando-ejecucion]')?.textContent || '')",
                             timeout=10000)
        pg.click(".modal .pie button:has-text('Ver lo que se creará y crear…')")
        pg.wait_for_selector(".modal [data-confirmar-avisos]", timeout=10000)
        self.assertIn("en vivo", pg.locator(".modal [data-confirmar-avisos]").inner_text())
        self.assertIn("Se verá en vivo (navegador visible)", pg.locator(".modal [data-confirmar-tarea]").inner_text())
        self.assertIn("para avisarte 10 min antes", pg.locator(".modal [data-confirmar-tarea]").inner_text())
        pg.click(".modal .pie button:has-text('Crear la tarea')")
        pg.wait_for_function("() => /Tarea de Windows creada/.test(document.querySelector('#toasts').textContent)",
                             timeout=10000)
        xml = self.xml()
        self.assertIn("--id %d --sin-ventana --visible --aviso-antes 10 --avisar-fin --ventanita</Arguments>" % self.rid,
                      xml)
        e = self.alm.programacion("reporte:%d" % self.rid)["programacion"]["ejecucion"]
        self.assertEqual(e, {"avisar_antes": 10, "avisar_inicio": False, "avisar_fin": True, "en_vivo": True,
                             "ventanita": True})
        # al volver a abrir «Programar…» se ve lo guardado
        pg.click("#contenido button:has-text('Programar…')")
        pg.wait_for_selector(".modal [data-cuando-avisos] select[data-ejec-antes]", timeout=15000)
        self.assertEqual(pg.locator(".modal select[data-ejec-antes]").input_value(), "10")
        self.assertTrue(pg.locator(".modal input[data-ejec-vista='vivo']").is_checked())
        self.assertFalse(pg.locator(".modal input[data-ejec='avisar_inicio']").is_checked())
        self.assertEqual(self.errores, [])

    def test_centro_de_control_en_curso_y_lo_programado(self):
        prog = {"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["09:00"]}], "ejecucion": AVISOS}
        self.api("POST", "reportes/%d/programar" % self.rid, {"programacion": prog, "confirmar": True})
        f = self.alm.crear_en_curso(tipo="reporte", nombre="Ventas (tarea)", objetivo_id=self.rid, total=4)
        self.alm.actualizar_en_curso(f, paso=2, texto="Clic en «Generar»")
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("inicio"), wait_until="load")
        fila = "[data-en-curso] li[data-en-curso-id='ext:%d']" % f
        pg.wait_for_selector(fila, timeout=15000)
        self.assertIn("Paso 2 de 4: Clic en «Generar»", pg.locator(fila).inner_text())
        self.assertIn("tarea de Windows", pg.locator(fila).inner_text())
        self.assertEqual(pg.locator(fila + " [role=progressbar]").get_attribute("aria-valuenow"), "50")
        # avanza (lo escribe la tarea en la base de datos): la interfaz se entera sola (evento «externo»)
        self.alm.actualizar_en_curso(f, paso=3, texto="Descargar")
        pg.wait_for_function("s => /Paso 3 de 4: Descargar/.test(document.querySelector(s)?.textContent || '')", arg=fila,
                             timeout=10000)
        self.assertEqual(pg.locator(fila + " [role=progressbar]").get_attribute("aria-valuenow"), "75")
        self.assertIn("en curso", pg.locator("[data-kpi='curso']").inner_text().lower())
        self.assertEqual(pg.locator("[data-kpi='curso'] .num").inner_text().split("\n")[0], "1")
        pg.click(fila + " button[data-pedir='detener']")
        pg.wait_for_function("() => /Deteniendo/.test(document.querySelector('#toasts').textContent)", timeout=10000)
        self.assertEqual(self.alm.en_curso_id(f)["pedido"], "detener")
        # termina: enseña el resultado
        self.alm.actualizar_en_curso(f, estado="ok", resumen="terminó bien: 1 archivo", paso=4)
        pg.wait_for_function("s => /Terminó bien: 1 archivo/.test(document.querySelector(s)?.textContent || '')",
                             arg=fila, timeout=10000)
        # «Lo programado»: el interruptor «En vivo / En segundo plano»
        seg = "[data-programados] [data-en-vivo='reporte:%d']" % self.rid
        pg.wait_for_selector(seg)
        self.assertEqual(pg.locator(seg + " button[data-modo='fondo']").get_attribute("aria-pressed"), "true")
        self.assertIn("5 min antes", pg.locator("[data-programados] li[data-programado='reporte:%d']" % self.rid).inner_text())
        pg.click(seg + " button[data-modo='vivo']")
        pg.wait_for_function("() => /se verá en vivo/.test(document.querySelector('#toasts').textContent)", timeout=10000)
        self.assertIn("--sin-ventana --visible --aviso-antes 5", self.xml())
        pg.wait_for_function("s => document.querySelector(s + \" button[data-modo='vivo']\")?.getAttribute('aria-pressed') === 'true'",
                             arg=seg, timeout=10000)
        self.assertEqual(self.errores, [])

    def test_esperando_para_empezar(self):
        ahora = dt.datetime.now()
        f = self.alm.crear_en_curso(tipo="reporte", nombre="Ventas", estado="esperando",
                                    empieza=(ahora + dt.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"))
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("inicio"), wait_until="load")
        fila = "[data-en-curso] li[data-en-curso-id='ext:%d']" % f
        pg.wait_for_selector(fila, timeout=15000)
        texto = pg.locator(fila).inner_text()
        self.assertIn("Se ejecutará a las", texto)
        self.assertIn("empieza en", texto)
        for b in ("Ver en vivo", "Empezar ya", "Cancelar esta ejecución"):
            self.assertIn(b, texto)
        pg.click(fila + " button[data-pedir='cancelar']")
        pg.wait_for_function("() => /Cancelada/.test(document.querySelector('#toasts').textContent)", timeout=10000)
        self.assertEqual(self.alm.en_curso_id(f)["pedido"], "cancelar")
        self.assertEqual(self.errores, [])


if __name__ == "__main__":
    unittest.main()
