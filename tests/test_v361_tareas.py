"""Pruebas de la 3.6.1: «pongo la hora de hoy con el aviso de minutos antes y no lo hace».

- Con «Avisarme N min antes» la tarea de Windows arranca N minutos antes.  Si la hora es dentro de menos de N minutos
  (se acaba de poner), ese arranque ya pasó: el servidor lanza ahora el mismo programa (que avisa y espera a la hora).
- Al guardar el horario de una vigilancia se crea su tarea de Windows directamente (sin la ventana «Falta un paso»); si
  Windows no la crea, se dice claro.

Nunca se crean tareas ni se lanza el bot de verdad: `ejecutar_tareas` y `lanzar_proceso` son falsos.
"""

import datetime
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_servidor_ui import BaseApi  # noqa: E402
from webbot import horario  # noqa: E402

VIERNES = datetime.datetime(2026, 10, 30, 14, 38, 30)


def prog(hora, antes=1):
    return {"reglas": [{"tipo": "semanal", "dias": ["lun", "mar", "mie", "jue", "vie"], "horas": [hora]}],
            "ejecucion": {"avisar_antes": antes, "avisar_inicio": True, "avisar_fin": True, "en_vivo": False,
                          "ventanita": True}}


class TestArrancarSiYaPasoElAviso(BaseApi):
    def setUp(self):
        super().setUp()
        self.lanzados = []
        self.app.lanzar_proceso = self.lanzados.append

    def arrancar(self, p, ahora=VIERNES):
        res = {}
        hecho = self.app._arrancar_si_ya_paso_el_aviso(horario.normalizar(p), "pythonw bot.py --vigilancia-id 4 "
                                                       "--aviso-antes 1", "Vigilar PORTAL #4", res, ahora=ahora)
        return hecho, res

    def test_hora_dentro_de_menos_minutos_que_el_aviso_se_arranca_ya(self):
        hecho, res = self.arrancar(prog("14:39"))                  # a las 14:38:30, con 1 min de aviso
        self.assertTrue(hecho)
        self.assertEqual(res["arrancada"], "14:39")
        self.assertEqual(self.lanzados, ["pythonw bot.py --vigilancia-id 4 --aviso-antes 1"])

    def test_con_tiempo_de_sobra_lo_hace_windows(self):
        self.assertEqual(self.arrancar(prog("14:45", antes=5)), (False, {}))   # arranca a las 14:40: Windows llega
        self.assertEqual(self.arrancar(prog("14:30")), (False, {}))             # ya pasó: mañana
        self.assertEqual(self.arrancar(prog("14:39", antes=0)), (False, {}))    # sin aviso: la hora exacta
        self.assertEqual(self.lanzados, [])

    def test_sin_lanzador_nunca_lanza_el_bot(self):
        self.app.lanzar_proceso = None                            # (lo que tiene la Aplicacion salvo la de verdad)
        self.assertEqual(self.arrancar(prog("14:39")), (False, {}))

    def test_la_aplicacion_nueva_no_lanza_nada(self):
        from webbot import servidor_ui
        self.assertIsNone(servidor_ui.Aplicacion(self.alm).lanzar_proceso)


if __name__ == "__main__":
    unittest.main()
