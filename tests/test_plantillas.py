"""Pruebas de plantillas.py (fecha de «hoy» inyectada; sin navegador)."""

import datetime
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import plantillas as pl  # noqa: E402

HOY = datetime.date(2026, 3, 15)


def r(texto, **kw):
    kw.setdefault("hoy", HOY)
    return pl.renderizar(texto, **kw)


class TestFechas(unittest.TestCase):
    def test_hoy_y_ayer_formato_por_defecto(self):
        self.assertEqual(r("{hoy}"), "15/03/2026")
        self.assertEqual(r("{ayer}"), "14/03/2026")

    def test_formato_strftime_cualquiera(self):
        self.assertEqual(r("{hoy:%Y-%m-%d}"), "2026-03-15")
        self.assertEqual(r("{ayer:%d-%m}"), "14-03")
        self.assertEqual(r("{hoy:%m/%y}"), "03/26")

    def test_formato_con_dos_puntos(self):
        ahora = datetime.datetime(2026, 3, 15, 8, 5, 9)
        self.assertEqual(pl.renderizar("{hoy:%H:%M:%S}", hoy=ahora), "08:05:09")

    def test_ayer_cruza_mes_y_anio(self):
        self.assertEqual(r("{ayer}", hoy=datetime.date(2026, 1, 1)), "31/12/2025")
        self.assertEqual(r("{ayer}", hoy=datetime.date(2026, 3, 1)), "28/02/2026")
        self.assertEqual(r("{ayer}", hoy=datetime.date(2024, 3, 1)), "29/02/2024")

    def test_dias(self):
        self.assertEqual(r("{dias:-7}"), "08/03/2026")
        self.assertEqual(r("{dias:3}"), "18/03/2026")
        self.assertEqual(r("{dias:-7:%d/%m/%Y}"), "08/03/2026")
        self.assertEqual(r("{dias:-15:%Y%m%d}"), "20260228")
        self.assertEqual(r("{dias:0}"), "15/03/2026")

    def test_dias_no_numerico(self):
        with self.assertRaises(pl.ErrorPlantilla):
            r("{dias:abc}")

    def test_inicio_y_fin_de_mes(self):
        self.assertEqual(r("{inicio_mes}"), "01/03/2026")
        self.assertEqual(r("{fin_mes}"), "31/03/2026")
        self.assertEqual(r("{fin_mes}", hoy=datetime.date(2026, 2, 10)), "28/02/2026")
        self.assertEqual(r("{fin_mes}", hoy=datetime.date(2024, 2, 10)), "29/02/2024")
        self.assertEqual(r("{fin_mes:%Y-%m-%d}"), "2026-03-31")

    def test_mes_anterior(self):
        self.assertEqual(r("{inicio_mes_anterior}"), "01/02/2026")
        self.assertEqual(r("{fin_mes_anterior}"), "28/02/2026")
        # De enero se pasa a diciembre del año anterior.
        enero = datetime.date(2026, 1, 20)
        self.assertEqual(r("{inicio_mes_anterior}", hoy=enero), "01/12/2025")
        self.assertEqual(r("{fin_mes_anterior}", hoy=enero), "31/12/2025")

    def test_hoy_por_defecto_es_la_fecha_actual(self):
        self.assertEqual(pl.renderizar("{hoy:%Y-%m-%d}"), datetime.date.today().isoformat())

    def test_formato_defecto_configurable(self):
        self.assertEqual(r("{hoy}", formato_defecto="%Y/%m/%d"), "2026/03/15")


class TestVariablesYEscapes(unittest.TestCase):
    def test_variables_propias(self):
        self.assertEqual(r("Cliente {cliente} el {hoy}", variables={"cliente": "Acme"}), "Cliente Acme el 15/03/2026")

    def test_variable_desconocida(self):
        with self.assertRaises(pl.ErrorPlantilla) as cm:
            r("{cliente}")
        self.assertIn("cliente", str(cm.exception))

    def test_llaves_escapadas(self):
        self.assertEqual(r("{{hoy}} es {hoy}"), "{hoy} es 15/03/2026")
        self.assertEqual(r("a {{ b }} c"), "a { b } c")
        self.assertEqual(r("sin plantillas"), "sin plantillas")
        self.assertEqual(r(""), "")
        self.assertEqual(r(None), "")

    def test_llaves_mal_formadas(self):
        with self.assertRaises(pl.ErrorPlantilla):
            r("{hoy")
        with self.assertRaises(pl.ErrorPlantilla):
            r("hola }")

    def test_escapar_es_inverso(self):
        txt = "json {a: 1} fin"
        self.assertEqual(r(pl.escapar(txt)), txt)

    def test_ext_y_nombre(self):
        self.assertEqual(r("Ventas_{hoy:%Y-%m-%d}{ext}", ext=".csv"), "Ventas_2026-03-15.csv")
        self.assertEqual(r("{nombre}_{hoy:%Y}{ext}", ext=".xlsx", nombre="informe"), "informe_2026.xlsx")

    def test_ext_fuera_de_descargas_es_error(self):
        with self.assertRaises(pl.ErrorPlantilla):
            r("archivo{ext}")

    def test_formato_de_fecha_invalido(self):
        # strftime en Windows rechaza directivas desconocidas con ValueError: se convierte en ErrorPlantilla.
        try:
            datetime.date(2026, 1, 1).strftime("%")
        except ValueError:
            with self.assertRaises(pl.ErrorPlantilla):
                r("{hoy:%}")


class TestSecretos(unittest.TestCase):
    def test_secreto_se_resuelve_con_el_resolvedor(self):
        res = r("{secreto:portal:clave}", resolver_secreto=lambda n: "valor-de-" + n)
        self.assertEqual(res, "valor-de-portal:clave")

    def test_secreto_enmascarado_para_registros(self):
        llamadas = []
        res = r("pw={secreto:x}", enmascarar_secretos=True, resolver_secreto=lambda n: llamadas.append(n))
        self.assertEqual(res, "pw=********")
        self.assertEqual(llamadas, [])

    def test_secreto_sin_almacen(self):
        with self.assertRaises(pl.ErrorPlantilla):
            r("{secreto:x}")

    def test_secretos_usados(self):
        self.assertEqual(pl.secretos_usados("{secreto:a} y {secreto:b:c} y {secreto:a}"), ["a", "b:c"])
        self.assertEqual(pl.secretos_usados("nada"), [])


class TestAnalisis(unittest.TestCase):
    def test_variables_usadas_ignora_fechas_y_secretos(self):
        txt = "{cliente} {hoy} {dias:-1} {secreto:x} {ext} {mes} {{literal}}"
        self.assertEqual(pl.variables_usadas(txt), ["cliente", "mes"])

    def test_validar(self):
        self.assertIsNone(pl.validar("{hoy} {{}}"))
        self.assertIsNotNone(pl.validar("{hoy"))

    def test_es_plantilla(self):
        self.assertTrue(pl.es_plantilla("a {hoy}"))
        self.assertFalse(pl.es_plantilla("a {{hoy}}"))

    def test_proponer_fecha_dinamica(self):
        self.assertEqual(pl.proponer_fecha_dinamica("15/03/2026", HOY), "{hoy}")
        self.assertEqual(pl.proponer_fecha_dinamica("2026-03-15", HOY), "{hoy:%Y-%m-%d}")
        self.assertEqual(pl.proponer_fecha_dinamica("14/03/2026", HOY), "{ayer}")
        self.assertEqual(pl.proponer_fecha_dinamica("2026-03-14", HOY), "{ayer:%Y-%m-%d}")
        self.assertIsNone(pl.proponer_fecha_dinamica("10/03/2026", HOY))
        self.assertIsNone(pl.proponer_fecha_dinamica("hola", HOY))

    def test_proponer_y_renderizar_dan_el_original(self):
        for texto in ("15/03/2026", "2026-03-15", "15-03-2026", "14/03/2026", "2026-03-14"):
            plantilla = pl.proponer_fecha_dinamica(texto, HOY)
            self.assertEqual(r(plantilla), texto)

    def test_fechas_a_plantilla_en_nombres(self):
        self.assertEqual(pl.fechas_a_plantilla("reporte_2026-03-15", HOY), "reporte_{hoy:%Y-%m-%d}")
        self.assertEqual(pl.fechas_a_plantilla("rep 14-03-2026 v{1}", HOY), "rep {ayer:%d-%m-%Y} v{{1}}")
        self.assertEqual(pl.fechas_a_plantilla("ventas", HOY), "ventas")
        self.assertEqual(pl.fechas_a_plantilla("rep_2020-01-01", HOY), "rep_2020-01-01")


if __name__ == "__main__":
    unittest.main()
