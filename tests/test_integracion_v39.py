"""Pruebas de integración de la versión 3.9 (navegador oculto + página de prueba `informes_periodos.html`):

- cada quincena × las opciones marcadas (una falla: se apunta y se sigue), con el periodo en los campos de fecha y en el
  nombre de los archivos;
- «para cada opción» anidado (cada sucursal × cada tabla) con «Aquí termina…» y un paso «Imprimir» después (una vez);
- el mes que acaba de terminar × todas las opciones de una lista (sin «Seleccione…»);
- «Imprimir» la página (se guarda como PDF y se manda a la impresora elegida).
La impresora SIEMPRE es falsa (nunca se imprime de verdad); sin red, sin base de datos ni contraseñas reales.
"""

import csv
import datetime
import os
import sys
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import BaseIntegracion  # noqa: E402
from webbot import impresion  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

D = datetime.date


def _nunca(*a, **k):
    raise AssertionError("¡Una prueba intentó imprimir de verdad!")


class TestPeriodosYOpciones(BaseIntegracion):
    def setUp(self):
        super().setUp()
        self.impresos = []
        p = mock.patch.object(impresion, "imprimir_archivo",
                              lambda ruta, impresora="", log=None: self.impresos.append((ruta, impresora)) or
                              (impresora or "Impresora Oficina"))
        p.start()
        self.addCleanup(p.stop)
        for nombre in ("_lanzar", "_imprimir_pdf_windows"):
            q = mock.patch.object(impresion, nombre, _nunca)
            q.start()
            self.addCleanup(q.stop)

    def flujo(self, *pasos):
        url = self.base + "informes_periodos.html"
        f = Flujo(nombre="Informe", url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=8)
        f.pasos = [Paso("abrir_url", url=url),
                   Paso("escribir", selectores=["#desde"], objetivo="Fecha desde", valor="{desde:%d/%m/%Y}"),
                   Paso("escribir", selectores=["#hasta"], objetivo="Fecha hasta", valor="{hasta:%d/%m/%Y}")] + list(pasos)
        return f

    @staticmethod
    def consultar_y_descargar(nombre="Informe{ext}", **kw):
        return [Paso("clic", selectores=["#consultar"]),
                Paso("descargar", selectores=["#descargar"], nombre=nombre, timeout=3, **kw)]

    def filas(self, ruta):
        with open(ruta, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))[1]

    def test_cada_quincena_por_las_opciones_marcadas(self):
        f = self.flujo(Paso("elegir_opcion", selectores=["#tabla"], objetivo="Tabla", estrategia="marcadas",
                            valores=["Ventas", "Roto"]), *self.consultar_y_descargar())
        f.opciones["repetir_dias"] = {"modo": "quincenas", "desde": "2026-02-01", "hasta": "2026-02-30", "corte": 15}
        res = self.ejecutar(f)
        log = self.leer_log(res)
        nombres = sorted(os.path.basename(a) for a in res.archivos)
        self.assertEqual(nombres, ["Informe 2026-02-01 a 2026-02-14 - Ventas.csv", "Informe 2026-02-15 a 2026-02-28 - Ventas.csv"],
                         log)
        self.assertEqual(self.filas(os.path.join(self.descargas, nombres[1])), ["Ventas", "Norte", "15/02/2026", "28/02/2026"])
        self.assertEqual(res.periodos, [(D(2026, 2, 1), D(2026, 2, 14)), (D(2026, 2, 15), D(2026, 2, 28))])
        self.assertIn("=== Periodo 1.ª quincena de febrero 2026 (01/02 a 14/02): del 01/02/2026 al 14/02/2026 (1 de 2) ===", log)
        self.assertIn("=== Opción «Roto» de «Tabla» (2 de 2) ===", log)
        self.assertIn("La opción «Roto» falló", log)
        # «Roto» falla en las dos quincenas: el reporte queda como fallido, diciendo qué falló
        self.assertFalse(res.ok)
        self.assertIn("En «Tabla» fallaron 2 opciones (las demás opciones se descargaron bien)", res.error)
        self.assertIn("«Roto» en 1.ª quincena de febrero 2026 (01/02 a 14/02): paso 6:", res.error)

    def test_anidado_con_fin_de_la_repeticion_e_imprimir_una_vez(self):
        f = self.flujo(Paso("elegir_opcion", selectores=["#sucursal"], objetivo="Sucursal", estrategia="cada_una"),
                       Paso("elegir_opcion", selectores=["#tabla"], objetivo="Tabla", estrategia="marcadas",
                            valores=["Ventas", "Pagos"]),
                       *self.consultar_y_descargar("{reporte} {opcion}{ext}", fin_bucle=True),
                       Paso("imprimir", impresora="Impresora Bodega"))
        res = self.ejecutar(f)          # sin repetir: {desde} = {hasta} = hoy (15/03/2026)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertEqual(sorted(os.path.basename(a) for a in res.archivos), [
            "Informe Pagos - Norte.csv", "Informe Pagos - Sur.csv", "Informe Ventas - Norte.csv", "Informe Ventas - Sur.csv"])
        self.assertEqual(self.filas(res.archivos[-1]), ["Pagos", "Sur", "15/03/2026", "15/03/2026"])
        # «Imprimir» va después de «Aquí termina»: una sola vez, con el último archivo
        self.assertEqual(self.impresos, [(res.archivos[-1], "Impresora Bodega")])
        self.assertEqual(res.impresiones, [{"archivo": res.archivos[-1], "impresora": "Impresora Bodega"}])
        self.assertEqual([x["bien"] for x in res.opciones_bucle], [["Ventas", "Pagos"], ["Ventas", "Pagos"], ["Norte", "Sur"]])

    def test_el_mes_que_acaba_de_terminar_por_todas_las_opciones(self):
        f = self.flujo(Paso("elegir_opcion", selectores=["#tabla"], objetivo="Tabla", estrategia="cada_una"),
                       *self.consultar_y_descargar("{reporte} {desde:%Y-%m}{ext}"))
        f.opciones["repetir_dias"] = {"modo": "meses", "rango": "anterior"}
        res = self.ejecutar(f)          # hoy (inyectado) = 15/03/2026 → febrero
        log = self.leer_log(res)
        self.assertEqual(sorted(os.path.basename(a) for a in res.archivos),
                         ["Informe 2026-02 - Pagos.csv", "Informe 2026-02 - Ventas.csv"], log)
        self.assertIn("Para cada opción de «Tabla»: 3 opciones: «Ventas», «Pagos», «Roto»", log)    # sin «Seleccione…»
        self.assertNotIn("Seleccione una tabla (", log)
        self.assertEqual(self.filas(res.archivos[0])[2:], ["01/02/2026", "28/02/2026"])
        self.assertFalse(res.ok)
        self.assertIn("En «Tabla» falló 1 opción", res.error)
        self.assertIn("«Roto» en febrero 2026: paso 6", res.error)
        self.assertIn("Error en el paso 4", res.resumen())

    def test_imprimir_la_pagina(self):
        f = self.flujo(Paso("elegir_opcion", selectores=["#tabla"], objetivo="Tabla", valor="Ventas"),
                       Paso("clic", selectores=["#consultar"]), Paso("esperar_texto", texto="Consulta Ventas"),
                       Paso("imprimir", que_imprimir="pagina"))
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        self.assertEqual(len(self.impresos), 1)
        ruta, impresora = self.impresos[0]
        self.assertEqual(impresora, "")
        self.assertTrue(ruta.startswith(os.path.join(self.registros, "impresiones")), ruta)
        self.assertTrue(ruta.endswith(".pdf") and os.path.getsize(ruta) > 500, ruta)
        self.assertEqual(res.archivos, [])                       # lo impreso no cuenta como descarga

    def test_imprimir_sin_archivo_falla_explicando_por_que(self):
        res = self.ejecutar(self.flujo(Paso("imprimir")))
        self.assertFalse(res.ok)
        self.assertIn("Todavía no se ha descargado ningún archivo que imprimir", res.error)
        self.assertEqual(self.impresos, [])


if __name__ == "__main__":
    unittest.main()
