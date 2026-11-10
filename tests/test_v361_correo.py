"""Pruebas de la versión 3.6.1 «Correo»: lo que fallaba con el Outlook real.

- Al abrir el correo, el Outlook real solo enseña el NOMBRE del remitente («…_FROM»); la dirección está en la ficha de
  contacto que sale al pasar el ratón, y la fecha va en el texto de «…_DATETIME».  El bot leía el remitente vacío, el
  correo «no coincidía» al abrirlo y se descartaba SIN hacer las acciones (copiar texto, tabla…).
- Los descartados hasta la 3.6 (pudieron ser lecturas erróneas) se olvidan UNA vez para que se vuelvan a mirar.
- «Procesar también los que ya se procesaron» (criterio `reprocesar`): cada revisión rehace las acciones.

Página de prueba `correo_outlook.html?como_real=1`.  Base de datos temporal, sin notificaciones ni tareas programadas.
"""

import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion_v34_correo import BaseCorreo  # noqa: E402
from webbot import correo  # noqa: E402


class TestCriterio(unittest.TestCase):
    def test_reprocesar_se_guarda_y_se_describe(self):
        c = correo.normalizar_criterios({"asunto": "Ventas", "reprocesar": 1})
        self.assertIs(c["reprocesar"], True)
        self.assertIn("también los ya procesados", correo.describir_criterios(c))
        self.assertIs(correo.normalizar_criterios({"asunto": "Ventas"})["reprocesar"], False)


class TestFechaAmbigua(unittest.TestCase):
    """«11/1/2026»: 1 de noviembre (M/D) y 11 de enero (D/M) son domingo los dos: gana la más cercana a hoy; y en la fila
    manda el title de la fecha de llegada, no una fecha que venga en el asunto."""

    def test_mismo_dia_de_la_semana_gana_la_mas_cercana(self):
        import datetime
        import types
        from unittest import mock

        class Hoy(datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 11, 2)
        falso = types.SimpleNamespace(date=Hoy, datetime=datetime.datetime, timedelta=datetime.timedelta)
        with mock.patch.object(correo, "datetime", falso):
            self.assertEqual(correo.leer_fecha("Sun 11/1/2026 3:30 PM").date(), datetime.date(2026, 11, 1))
            self.assertEqual(correo.leer_fecha("Fri 10/30/2026 10:20 AM").date(), datetime.date(2026, 10, 30))

    def test_en_la_fila_manda_el_title_de_la_fecha(self):
        from webbot.correo_outlook import _RX_TITLE_FECHA
        self.assertTrue(_RX_TITLE_FECHA.match("Sun 11/1/2026 3:30 PM"))
        self.assertFalse(_RX_TITLE_FECHA.match("Reportes Ventas RESUMEN AL 01/11/2026 Sun 11/1/2026"))


class TestOutlookReal(BaseCorreo):
    def cuenta_real(self):
        return self.cuenta(pagina="correo_outlook.html?como_real=1")

    def procesados(self, bid):
        return self.api("GET", "correo/busquedas/%d" % bid)["busqueda"]["procesados"]

    def test_remitente_de_la_ficha_y_hace_las_acciones(self):
        b = self.busqueda(self.cuenta_real()["id"])
        fin, evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        self.assertEqual([e["procesados"] for e in evs if e["tipo"] == "correo"], [2], fin.get("resumen"))
        ps = self.procesados(b["id"])
        self.assertEqual(sorted(p["valores"][0][1] for p in ps), ["1.234", "987"])       # copió el texto
        self.assertTrue(all("reportes@ejemplo.com" not in (p["mensaje"] or "") for p in ps))
        with open(self.api("GET", "correo/busquedas/%d" % b["id"])["historial"][0]["registro"], encoding="utf-8") as f:
            log = f.read()
        self.assertNotIn("no coincide al abrirlo", log)

    def test_procesar_tambien_los_ya_procesados(self):
        b = self.busqueda(self.cuenta_real()["id"], criterios={
            "asunto": "RESUMEN DE VENTAS EMPRESA", "remitente": "reportes@ejemplo.com", "fecha": "ultimos", "dias": 7,
            "adjunto": "supervision ventas", "reprocesar": True})
        self.assertTrue(b["criterios"]["reprocesar"])
        for vuelta in range(2):
            fin, evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
            self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
            self.assertEqual([e["procesados"] for e in evs if e["tipo"] == "correo"], [2], (vuelta, fin.get("resumen")))
        self.assertEqual(len(self.web.estado["correo_descargas"]), 4)                     # se rehízo todo
        self.assertEqual(len(self.procesados(b["id"])), 2)                                # sin duplicar registros

    def test_los_descartados_de_antes_se_vuelven_a_mirar_una_vez(self):
        b = self.busqueda(self.cuenta_real()["id"])
        fin, _ = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        for p in self.alm.procesados_correo(b["id"]):                  # como los que el bot leyó mal hasta la 3.6
            self.alm.marcar_correo_procesado(b["id"], p["clave"], "descartado", mensaje="el remitente no contiene …")
        self.assertEqual(self.alm.olvidar_descartados_correo(), 2)      # (al abrir la 3.6.1, una sola vez)
        self.assertEqual(self.alm.olvidar_descartados_correo(), 0)
        fin, evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        self.assertEqual([e["procesados"] for e in evs if e["tipo"] == "correo"], [2], fin.get("resumen"))

    def test_revisar_ahora_sin_nuevos_rehace_el_mas_reciente(self):
        b = self.busqueda(self.cuenta_real()["id"])
        fin, _ = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        for _vez in range(2):                                          # cada vez que lo pide, aunque no haya nuevos
            fin, evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
            self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
            self.assertEqual([e["procesados"] for e in evs if e["tipo"] == "correo"], [1], fin.get("resumen"))
            self.assertIn("Total ventas: 1.234", fin["resumen"])          # el de hoy (el más reciente)
        h = self.api("GET", "correo/busquedas/%d" % b["id"])
        self.assertEqual(len(h["busqueda"]["procesados"]), 2)             # sin duplicar registros
        with open(h["historial"][0]["registro"], encoding="utf-8") as f:
            self.assertIn("No hay correos nuevos: como lo pediste tú («Revisar ahora»), se rehacen las acciones del "
                          "más reciente", f.read())

if __name__ == "__main__":
    unittest.main()
