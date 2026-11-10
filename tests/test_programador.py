"""Pruebas de programador.py: SOLO se construyen comandos; nunca se crea una tarea real."""

import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import programador as pg  # noqa: E402

BOT = r"C:\Bots\bot.py"
FLUJO = r"C:\Bots\flujos\ventas.json"
PY = r"C:\Python\pythonw.exe"


class TestComandos(unittest.TestCase):
    def test_diario(self):
        cmd = pg.construir_comando_crear("Ventas", BOT, FLUJO, "7:30", python=PY)
        self.assertEqual(cmd[:2], ["schtasks", "/Create"])
        self.assertEqual(cmd[cmd.index("/TN") + 1], "BotWeb\\Ventas")
        self.assertEqual(cmd[cmd.index("/SC") + 1], "DAILY")
        self.assertEqual(cmd[cmd.index("/ST") + 1], "07:30")
        self.assertIn("/F", cmd)
        tr = cmd[cmd.index("/TR") + 1]
        self.assertEqual(tr, '"C:\\Python\\pythonw.exe" "C:\\Bots\\bot.py" --flujo "C:\\Bots\\flujos\\ventas.json" '
                             '--sin-ventana --oculto')

    def test_semanal_ordena_dias(self):
        cmd = pg.construir_comando_crear("Sem", BOT, FLUJO, "18:00", frecuencia="semanal",
                                         dias=["fri", "MON", "WED"], python=PY)
        self.assertEqual(cmd[cmd.index("/SC") + 1], "WEEKLY")
        self.assertEqual(cmd[cmd.index("/D") + 1], "MON,WED,FRI")

    def test_variables_en_la_tarea(self):
        cmd = pg.construir_comando_crear("V", BOT, FLUJO, "09:00", python=PY, variables={"cliente": "Acme"})
        self.assertTrue(cmd[cmd.index("/TR") + 1].endswith('--var "cliente=Acme"'))

    def test_visible_opcional(self):
        cmd = pg.construir_comando_crear("V", BOT, FLUJO, "09:00", python=PY, oculto=False)
        self.assertTrue(cmd[cmd.index("/TR") + 1].endswith("--sin-ventana --visible"))

    def test_validaciones(self):
        for hora in ("25:00", "7", "07:60", "abc", ""):
            with self.assertRaises(pg.ErrorProgramador):
                pg.construir_comando_crear("V", BOT, FLUJO, hora, python=PY)
        with self.assertRaises(pg.ErrorProgramador):
            pg.construir_comando_crear("V", BOT, FLUJO, "07:00", frecuencia="semanal", dias=[], python=PY)
        with self.assertRaises(pg.ErrorProgramador):
            pg.construir_comando_crear("V", BOT, FLUJO, "07:00", frecuencia="semanal", dias=["XXX"], python=PY)
        with self.assertRaises(pg.ErrorProgramador):
            pg.construir_comando_crear("V", BOT, FLUJO, "07:00", frecuencia="mensual", python=PY)
        with self.assertRaises(pg.ErrorProgramador):
            pg.construir_comando_crear("   ", BOT, FLUJO, "07:00", python=PY)

    def test_ruta_demasiado_larga(self):
        with self.assertRaises(pg.ErrorProgramador):
            pg.construir_comando_crear("V", BOT, "C:\\" + "a" * 300 + ".json", "07:00", python=PY)

    def test_nombre_se_limpia(self):
        self.assertEqual(pg.nombre_tarea('Ventas: "mes"/1'), "BotWeb\\Ventas_ _mes_1")

    def test_borrar_y_consultar(self):
        self.assertEqual(pg.construir_comando_borrar("Ventas"), ["schtasks", "/Delete", "/TN", "BotWeb\\Ventas", "/F"])
        self.assertEqual(pg.construir_comando_consultar("Ventas")[:2], ["schtasks", "/Query"])

    def test_como_texto(self):
        txt = pg.como_texto(["schtasks", "/TN", "BotWeb\\Mi tarea"])
        self.assertEqual(txt, 'schtasks /TN "BotWeb\\Mi tarea"')


class TestSeguridad(unittest.TestCase):
    """crear/borrar exigen confirmación; con un ejecutor falso no se llama a schtasks de verdad."""

    def test_sin_confirmacion_no_hace_nada(self):
        llamadas = []
        cmd = pg.construir_comando_crear("V", BOT, FLUJO, "07:00", python=PY)
        with self.assertRaises(pg.ErrorProgramador):
            pg.crear(cmd, confirmado=False, ejecutor=lambda c: llamadas.append(c) or (0, ""))
        with self.assertRaises(pg.ErrorProgramador):
            pg.borrar("V", confirmado=False, ejecutor=lambda c: llamadas.append(c) or (0, ""))
        self.assertEqual(llamadas, [])

    def test_con_confirmacion_usa_el_ejecutor_inyectado(self):
        llamadas = []
        cmd = pg.construir_comando_crear("V", BOT, FLUJO, "07:00", python=PY)
        pg.crear(cmd, confirmado=True, ejecutor=lambda c: llamadas.append(c) or (0, "correcto"))
        pg.borrar("V", confirmado=True, ejecutor=lambda c: llamadas.append(c) or (0, "correcto"))
        self.assertEqual(llamadas[0], cmd)
        self.assertEqual(llamadas[1][1], "/Delete")

    def test_error_de_schtasks(self):
        cmd = pg.construir_comando_crear("V", BOT, FLUJO, "07:00", python=PY)
        with self.assertRaises(pg.ErrorProgramador):
            pg.crear(cmd, confirmado=True, ejecutor=lambda c: (1, "Acceso denegado"))


if __name__ == "__main__":
    unittest.main()
