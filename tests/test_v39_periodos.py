"""Pruebas de la versión 3.9: repetir por meses / quincenas, paso «Imprimir», «para cada opción» y reportes encadenados.

Lo que pidió el usuario:
- «Bajar mes por mes» (del 01/02 al 30/06 → un archivo por mes; el 30/02 no existe: se usa el 28) y «por quincena» con el
  día de corte que decida el usuario (15 por defecto); ponerse al día (un rango) y programado (solo el periodo que acaba
  de terminar: {inicio_quincena_anterior} / {fin_quincena_anterior}, horario el día 1 y el día de corte).
- Paso «Imprimir» (el último archivo descargado o la página) en la impresora predeterminada o en otra.
- Reportes en cadena: «para cada opción» de una lista (un archivo por opción, sigue si una falla) y «Al terminar,
  ejecutar…» (sin círculos).  Combinables: cada quincena × cada opción.

Nada de esto toca la base de datos real, el Administrador de credenciales, tareas de Windows, avisos ni impresoras: las
impresoras se sustituyen siempre (NUNCA se imprime de verdad).  Los nombres de sitios y reportes son neutros.
"""

import datetime
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from webbot import filtros, horario, impresion, lote, plantillas, programador, secretos  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.ejecutor import ResultadoEjecucion  # noqa: E402
from webbot.flujo import ErrorFlujo, Flujo, Paso  # noqa: E402

D = datetime.date


def _nunca(*a, **k):
    raise AssertionError("¡Una prueba intentó usar la impresora o Windows de verdad!")


class SinImpresora(unittest.TestCase):
    """Base: todo lo que toca impresoras de verdad falla la prueba si se llama sin sustituir."""

    def setUp(self):
        for nombre in ("_enumerar", "_predeterminada", "_programa_que_imprime", "_lanzar", "_imprimir_pdf_windows"):
            p = mock.patch.object(impresion, nombre, _nunca)
            p.start()
            self.addCleanup(p.stop)


# ============================================================================ A. periodos
class TestPeriodos(unittest.TestCase):
    p = staticmethod(mod_flujo.periodos_a_repetir)

    def test_por_meses_con_el_30_de_febrero(self):
        r = self.p({"modo": "meses", "desde": "01/02/2026", "hasta": "30/06/2026"})
        self.assertEqual(r, [(D(2026, 2, 1), D(2026, 2, 28)), (D(2026, 3, 1), D(2026, 3, 31)), (D(2026, 4, 1), D(2026, 4, 30)),
                             (D(2026, 5, 1), D(2026, 5, 31)), (D(2026, 6, 1), D(2026, 6, 30))])
        self.assertEqual(self.p({"modo": "meses", "desde": "2026-02-01", "hasta": "2026-02-30"}),
                         [(D(2026, 2, 1), D(2026, 2, 28))])                              # 30/02 → 28/02
        self.assertEqual(self.p({"modo": "meses", "desde": "2024-02-01", "hasta": "30/02/2024"}),
                         [(D(2024, 2, 1), D(2024, 2, 29))])                              # bisiesto
        self.assertEqual(mod_flujo.fecha_flexible("31/04/2026"), D(2026, 4, 30))
        self.assertEqual(mod_flujo.fecha_flexible("2026-2-31"), D(2026, 2, 28))
        # cruza el año; los extremos se recortan a las fechas elegidas
        self.assertEqual(self.p({"modo": "meses", "desde": "2025-12-10", "hasta": "2026-01-20"}),
                         [(D(2025, 12, 10), D(2025, 12, 31)), (D(2026, 1, 1), D(2026, 1, 20))])

    def test_por_quincenas_con_corte(self):
        q = {"modo": "quincenas", "desde": "2026-02-01", "hasta": "2026-03-31"}
        self.assertEqual(self.p(q), [(D(2026, 2, 1), D(2026, 2, 14)), (D(2026, 2, 15), D(2026, 2, 28)),
                                     (D(2026, 3, 1), D(2026, 3, 14)), (D(2026, 3, 15), D(2026, 3, 31))])
        self.assertEqual(self.p(dict(q, corte=16, hasta="2026-02-30")),
                         [(D(2026, 2, 1), D(2026, 2, 15)), (D(2026, 2, 16), D(2026, 2, 28))])
        self.assertEqual(self.p(dict(q, mitades="primera")), [(D(2026, 2, 1), D(2026, 2, 14)), (D(2026, 3, 1), D(2026, 3, 14))])
        self.assertEqual(self.p(dict(q, mitades="segunda", corte=10, desde="2024-02-01", hasta="2024-02-29")),
                         [(D(2024, 2, 10), D(2024, 2, 29))])
        self.assertEqual(plantillas.quincenas_del_mes(2026, 2, 28), [(D(2026, 2, 1), D(2026, 2, 27)), (D(2026, 2, 28), D(2026, 2, 28))])

    def test_solo_el_que_acaba_de_terminar(self):
        m = {"modo": "meses", "rango": "anterior"}
        self.assertEqual(self.p(m, D(2026, 3, 1)), [(D(2026, 2, 1), D(2026, 2, 28))])
        self.assertEqual(self.p(m, D(2026, 1, 15)), [(D(2025, 12, 1), D(2025, 12, 31))])
        q = {"modo": "quincenas", "rango": "anterior"}
        casos = {D(2026, 11, 15): (D(2026, 11, 1), D(2026, 11, 14)), D(2026, 11, 12): (D(2026, 10, 15), D(2026, 10, 31)),
                 D(2026, 12, 1): (D(2026, 11, 15), D(2026, 11, 30)), D(2026, 1, 3): (D(2025, 12, 15), D(2025, 12, 31)),
                 D(2024, 3, 1): (D(2024, 2, 15), D(2024, 2, 29))}
        for hoy, esperado in casos.items():
            self.assertEqual(self.p(q, hoy), [esperado], hoy)
        self.assertEqual(self.p(dict(q, corte=20), D(2026, 11, 20)), [(D(2026, 11, 1), D(2026, 11, 19))])
        self.assertEqual(self.p(dict(q, mitades="primera"), D(2026, 11, 12)), [(D(2026, 10, 1), D(2026, 10, 14))])
        self.assertEqual(self.p(dict(q, mitades="segunda"), D(2026, 11, 20)), [(D(2026, 10, 15), D(2026, 10, 31))])

    def test_validacion(self):
        for malo in ({"modo": "meses", "desde": "x"}, {"modo": "meses", "desde": "2026-03-01", "hasta": "2026-01-01"},
                     {"modo": "quincenas", "desde": "2026-01-01", "corte": 29}, {"modo": "quincenas", "desde": "2026-01-01", "corte": 1},
                     {"modo": "quincenas", "desde": "2026-01-01", "mitades": "tercera"}, {"modo": "meses", "rango": "otro"},
                     {"modo": "meses", "desde": "2000-01-01", "hasta": "2026-01-01"}, {"modo": "meses", "desde": "2026-13-01"}):
            with self.assertRaises(ErrorFlujo, msg=str(malo)):
                mod_flujo.validar_repetir_dias(malo)
        mod_flujo.validar_repetir_dias({"modo": "meses", "rango": "anterior"})          # sin fechas: vale
        f = Flujo(nombre="x", pasos=[Paso("abrir_url", url="http://a/")])
        f.opciones["repetir_dias"] = {"modo": "quincenas", "desde": "zz"}
        self.assertTrue(any(p.startswith("Repetir por quincenas:") for p in f.problemas()), f.problemas())

    def test_los_reportes_de_antes_siguen_igual(self):
        # «Repetir por días» de siempre: mismos días, y como periodos (día, día)
        conf = {"modo": "ultimos", "n": 2}
        self.assertEqual(mod_flujo.dias_a_repetir(conf, D(2026, 10, 26)), [D(2026, 10, 24), D(2026, 10, 25)])
        self.assertEqual(self.p(conf, D(2026, 10, 26)), [(D(2026, 10, 24),) * 2, (D(2026, 10, 25),) * 2])
        self.assertEqual(mod_flujo.dias_a_repetir({"modo": "meses", "rango": "anterior"}, D(2026, 3, 1)), [])
        self.assertEqual(self.p(None), [])
        with self.assertRaises(ErrorFlujo):                    # por días sigue pidiendo AAAA-MM-DD
            mod_flujo.validar_repetir_dias({"modo": "fijo", "desde": "26/10/2026"})
        # un reporte guardado (JSON) con «repetir_dias» de antes se lee y se escribe igual
        f = Flujo(nombre="R", pasos=[Paso("abrir_url", url="http://a/")])
        f.opciones["repetir_dias"] = {"modo": "fijo", "desde": "2026-10-01", "hasta": "2026-10-03"}
        g = Flujo.desde_json(f.a_json())
        self.assertEqual(g.opciones["repetir_dias"], f.opciones["repetir_dias"])
        self.assertEqual(g.a_dict(), f.a_dict())
        self.assertNotIn("valores", g.pasos[0].a_dict())

    def test_describir(self):
        dp = mod_flujo.describir_periodo
        self.assertEqual(dp(D(2026, 2, 1), D(2026, 2, 28)), "febrero 2026")
        self.assertEqual(dp(D(2026, 2, 1), D(2026, 2, 14)), "1.ª quincena de febrero 2026 (01/02 a 14/02)")
        self.assertEqual(dp(D(2026, 2, 15), D(2026, 2, 28)), "2.ª quincena de febrero 2026 (15/02 a 28/02)")
        self.assertEqual(dp(D(2026, 2, 10), D(2026, 2, 12)), "del 10/02/2026 al 12/02/2026")
        self.assertEqual(mod_flujo.describir_repetir_dias({"modo": "meses", "desde": "2026-02-01", "hasta": "2026-06-30"}),
                         "por meses, del 2026-02-01 al 2026-06-30")
        self.assertIn("la 2.ª empieza el día 16", mod_flujo.describir_repetir_dias(
            {"modo": "quincenas", "rango": "anterior", "corte": 16}))
        r = ResultadoEjecucion()
        r.ok, r.completados, r.periodos = True, 8, [(D(2026, 2, 1), D(2026, 2, 28)), (D(2026, 3, 1), D(2026, 3, 31))]
        self.assertIn("Terminado: 2 periodos (febrero 2026 a marzo 2026)", r.resumen())


class TestPlantillasPeriodo(unittest.TestCase):
    def test_desde_hasta(self):
        r = plantillas.renderizar
        self.assertEqual(r("{desde:%Y-%m-%d} a {hasta}", desde=D(2026, 2, 1), hasta=D(2026, 2, 28)), "2026-02-01 a 28/02/2026")
        self.assertEqual(r("{desde}|{hasta}", hoy=D(2026, 2, 3)), "03/02/2026|03/02/2026")       # sin repetir: hoy
        self.assertEqual(r("{desde}", fecha=D(2026, 1, 9)), "09/01/2026")                       # por días: ese día
        self.assertEqual(r("{desde}", variables={"desde": "Bogotá"}), "Bogotá")                  # variable de antes
        self.assertIn("desde", plantillas.RESERVADAS)
        self.assertEqual(Flujo(pasos=[Paso("escribir", selectores=["#d"], valor="{desde}")]).variables_necesarias(), [])

    def test_quincena_anterior(self):
        r = plantillas.renderizar
        self.assertEqual(r("{inicio_quincena_anterior} {fin_quincena_anterior}", hoy=D(2026, 11, 12)), "15/10/2026 31/10/2026")
        self.assertEqual(r("{inicio_quincena_anterior:%Y-%m-%d}", hoy=D(2026, 11, 15)), "2026-11-01")
        self.assertEqual(r("{fin_quincena_anterior}", hoy=D(2026, 11, 20), corte=20), "19/11/2026")
        self.assertEqual(r("{fin_mes_anterior}", hoy=D(2024, 3, 1)), "29/02/2024")
        self.assertIn("{inicio_quincena_anterior}", [x[0] for x in plantillas.AYUDA_PLANTILLAS])

    def test_calendario_de_la_interfaz(self):
        a = plantillas.analizar_fecha("{desde:%d/%m/%Y}")
        self.assertEqual(a, {"modo": "relativa", "que": "desde", "n": None, "formato": "%d/%m/%Y"})
        self.assertEqual(plantillas.plantilla_fecha(a), "{desde:%d/%m/%Y}")
        self.assertEqual(plantillas.plantilla_fecha(plantillas.analizar_fecha("{fin_quincena_anterior}")), "{fin_quincena_anterior}")
        self.assertEqual(plantillas.describir_fecha("{hasta}", D(2026, 2, 3)), "fin del periodo · 03/02/2026")
        for v in ("{desde:%Y-%m-%d}", "{hasta}", "{inicio_quincena_anterior}"):
            self.assertTrue(filtros.es_fecha(Paso("escribir", selectores=["#x"], objetivo="Campo", valor=v)), v)
        textos = [s["texto"] for s in filtros._sugerencias_fecha("{ayer}")]
        self.assertIn("inicio del periodo", textos)
        self.assertIn("fin de la quincena anterior", textos)

    def test_corte_del_reporte(self):
        self.assertEqual(mod_flujo.corte_de({"repetir_dias": {"modo": "quincenas", "corte": 16}}), 16)
        self.assertEqual(mod_flujo.corte_de({"corte_quincena": 10}), 10)
        self.assertEqual(mod_flujo.corte_de({}), 15)
        self.assertEqual(mod_flujo.corte_de({"corte_quincena": 99}), 15)


class TestNombresPorPeriodo(unittest.TestCase):
    def test_nombre_con_periodo(self):
        n = mod_flujo.nombre_con_periodo
        self.assertEqual(n("{reporte} {hoy:%Y-%m-%d}{ext}"), "{reporte} {desde:%Y-%m-%d} a {hasta:%Y-%m-%d}{ext}")
        self.assertEqual(n("{reporte} {hoy:%d-%m}{ext}"), "{reporte} {desde:%d-%m} a {hasta:%d-%m}{ext}")
        self.assertEqual(n("Informe{ext}"), "Informe {desde:%Y-%m-%d} a {hasta:%Y-%m-%d}{ext}")
        self.assertEqual(n(""), "{nombre} {desde:%Y-%m-%d} a {hasta:%Y-%m-%d}{ext}")
        self.assertEqual(n("", "guardar_pagina"), "Pagina_{desde:%Y-%m-%d} a {hasta:%Y-%m-%d}")
        for ya in ("{reporte} {desde:%Y}{ext}", "X {fecha:%Y%m%d}{ext}", "{hasta}{ext}"):
            self.assertEqual(n(ya), ya)
        self.assertEqual(mod_flujo.nombre_descarga_defecto(por_periodos=True), "{reporte} {desde:%Y-%m-%d} a {hasta:%Y-%m-%d}{ext}")
        f = Flujo(nombre="Informes", pasos=[Paso("descargar", selectores=["#d"], nombre="report_xls{ext}")])
        f.opciones["repetir_dias"] = {"modo": "meses", "rango": "anterior"}
        mod_flujo.usar_nombre_del_reporte(f)
        self.assertEqual(f.pasos[0].nombre, "{reporte} {desde:%Y-%m-%d} a {hasta:%Y-%m-%d}{ext}")
        # los archivos de dos meses no se pisan
        vistas = [mod_flujo.vista_archivo(f.pasos[0].nombre, reporte="Informes", raiz=RAIZ, desde=d, hasta=h)[0]
                  for d, h in mod_flujo.periodos_a_repetir({"modo": "meses", "desde": "2026-02-01", "hasta": "2026-03-31"})]
        self.assertEqual(vistas, ["Informes 2026-02-01 a 2026-02-28.xlsx", "Informes 2026-03-01 a 2026-03-31.xlsx"])

    def test_poner_el_periodo_en_las_fechas(self):
        f = Flujo(nombre="R", pasos=[Paso("abrir_url", url="http://a/"),
                                     Paso("escribir", selectores=["#hasta"], objetivo="Fecha hasta", valor="{hoy:%Y-%m-%d}"),
                                     Paso("escribir", selectores=["#desde"], objetivo="Fecha desde", valor="01/10/2026"),
                                     Paso("escribir", selectores=["#cliente"], objetivo="Cliente", valor="Mi Empresa")])
        msj = mod_flujo.usar_periodo_en_fechas(f)
        self.assertEqual([p.valor for p in f.pasos[1:]], ["{hasta:%Y-%m-%d}", "{desde}", "Mi Empresa"])
        self.assertEqual(len(msj), 2)
        with self.assertRaises(ErrorFlujo):
            mod_flujo.usar_periodo_en_fechas(Flujo(pasos=[Paso("abrir_url", url="http://a/")]))


class TestHorarioPorPeriodo(unittest.TestCase):
    def test_reglas(self):
        self.assertEqual(horario.regla_periodo("meses")["dias_mes"], [1])
        self.assertEqual(horario.regla_periodo("quincenas", 16)["dias_mes"], [1, 16])
        self.assertEqual(horario.regla_periodo("quincenas", 16, "primera")["dias_mes"], [16])
        self.assertEqual(horario.regla_periodo("quincenas", 16, "segunda")["dias_mes"], [1])
        with self.assertRaises(horario.ErrorHorario):
            horario.regla_periodo("quincenas", 29)
        self.assertIsNone(horario.programacion_de_periodo({"modo": "ultimos", "n": 3}))
        self.assertIsNone(horario.programacion_de_periodo(None))

    def test_tarea_de_windows_dia_1_y_dia_de_corte(self):
        p = horario.programacion_de_periodo({"modo": "quincenas", "rango": "anterior", "corte": 16}, horas=["06:30"])
        self.assertIn("el día 1 y el día 16", p["texto"])
        prox = horario.proximas(p, 4, datetime.datetime(2026, 11, 12, 8, 0))
        self.assertEqual([c.strftime("%d/%m %H:%M") for c in prox], ["16/11 06:30", "01/12 06:30", "16/12 06:30", "01/01 06:30"])
        # solo se construye el XML: no se crea ninguna tarea
        xml = programador.construir_xml_tarea(p, '"C:\\py\\pythonw.exe" "C:\\bot\\bot.py" --id 3', usuario="PC\\usuario",
                                              ahora=datetime.datetime(2026, 11, 12, 8, 0), adelanto=0)
        self.assertIn("<ScheduleByMonth>", xml)
        self.assertIn("<Day>1</Day>", xml)
        self.assertIn("<Day>16</Day>", xml)
        self.assertEqual(xml.count("<CalendarTrigger>"), 1)
        m = horario.programacion_de_periodo({"modo": "meses", "rango": "fijo", "desde": "2026-01-01"})
        self.assertIn("el día 1", m["texto"])
        self.assertIn("solo el que acaba de terminar", m["texto"])          # avisa: con un rango bajaría todo


# ============================================================================ B. imprimir
class TestPasoImprimir(unittest.TestCase):
    def test_modelo(self):
        p = Paso("imprimir")
        self.assertEqual(p.descripcion(), "Imprimir el último archivo descargado en la impresora predeterminada")
        q = Paso("imprimir", que_imprimir="pagina", impresora="Impresora Oficina")
        self.assertEqual(q.descripcion(), "Imprimir la página que se ve en ese momento en la impresora «Impresora Oficina»")
        self.assertEqual(Paso.desde_dict(q.a_dict()).a_dict(), q.a_dict())
        self.assertEqual(p.problemas(), [])
        self.assertTrue(Paso("imprimir", que_imprimir="fax").problemas())
        self.assertTrue(Paso("imprimir", impresora='Mala"').problemas())
        self.assertIn("imprimir", mod_flujo.TIPOS)
        self.assertEqual(mod_flujo.NOMBRES_TIPO["imprimir"], "Imprimir")


class TestImpresion(SinImpresora):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="botweb_v39_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.enviados = []
        self.impresoras = ["Impresora Oficina", "Impresora Bodega"]
        self.defecto = "Impresora Oficina"
        self.verbos = {(".xlsx", "print"), (".xlsx", "printto"), (".csv", "print")}
        self.codigo = 42
        for nombre, f in (("_enumerar", lambda: list(self.impresoras)), ("_predeterminada", lambda: self.defecto),
                          ("_programa_que_imprime", lambda ext, verbo="print": "prog" if (ext, verbo) in self.verbos else ""),
                          ("_lanzar", self.lanzar), ("_imprimir_pdf_windows", self.pdf)):
            p = mock.patch.object(impresion, nombre, f)
            p.start()
            self.addCleanup(p.stop)

    def lanzar(self, ruta, verbo, parametros=None):
        self.enviados.append(("shell", os.path.basename(ruta), verbo, parametros))
        return self.codigo

    def pdf(self, ruta, impresora, salida=None, tiempo=300):
        self.enviados.append(("pdf", os.path.basename(ruta), impresora))
        return 3

    def archivo(self, nombre):
        ruta = os.path.join(self.tmp, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("x")
        return ruta

    def test_predeterminada_y_otra(self):
        log = []
        self.assertEqual(impresion.imprimir_archivo(self.archivo("Informe.xlsx"), log=log.append), "Impresora Oficina")
        self.assertEqual(impresion.imprimir_archivo(self.archivo("Informe.xlsx"), "impresora bodega"), "Impresora Bodega")
        self.assertEqual(self.enviados, [("shell", "Informe.xlsx", "print", None),
                                         ("shell", "Informe.xlsx", "printto", '"Impresora Bodega"')])
        self.assertEqual(log, ["enviado a la impresora «Impresora Oficina»: Informe.xlsx"])
        self.assertEqual(impresion.impresoras(), {"impresoras": self.impresoras, "predeterminada": "Impresora Oficina"})

    def test_pdf_sin_programa_usa_el_lector_de_windows(self):
        log = []
        impresion.imprimir_archivo(self.archivo("Pagos.pdf"), log=log.append)
        impresion.imprimir_archivo(self.archivo("Pagos.pdf"), "Impresora Bodega")
        self.assertEqual(self.enviados, [("pdf", "Pagos.pdf", "Impresora Oficina"), ("pdf", "Pagos.pdf", "Impresora Bodega")])
        self.assertIn("3 páginas, con el lector de PDF de Windows", log[0])

    def test_errores_que_se_entienden(self):
        e = impresion.ErrorImpresion
        with self.assertRaisesRegex(e, "No existe el archivo"):
            impresion.imprimir_archivo(os.path.join(self.tmp, "no.xlsx"))
        with self.assertRaisesRegex(e, "ningún programa que sepa imprimir archivos .docx"):
            impresion.imprimir_archivo(self.archivo("a.docx"))
        with self.assertRaisesRegex(e, "no deja elegir la impresora"):
            impresion.imprimir_archivo(self.archivo("a.csv"), "Impresora Bodega")
        with self.assertRaisesRegex(e, "No existe la impresora «Otra». Impresoras instaladas: «Impresora Oficina», «Impresora Bodega»"):
            impresion.imprimir_archivo(self.archivo("a.xlsx"), "Otra")
        self.codigo = 31
        with self.assertRaisesRegex(e, "ningún programa"):
            impresion.imprimir_archivo(self.archivo("a.xlsx"))
        self.codigo = 5
        with self.assertRaisesRegex(e, "acceso denegado"):
            impresion.imprimir_archivo(self.archivo("a.xlsx"))
        self.defecto = ""
        with self.assertRaisesRegex(e, "no tiene impresora predeterminada"):
            impresion.imprimir_archivo(self.archivo("a.xlsx"))
        self.impresoras = []
        with self.assertRaisesRegex(e, "No hay ninguna impresora instalada"):
            impresion.imprimir_archivo(self.archivo("a.xlsx"))
        self.assertEqual([x for x in self.enviados if x[0] == "pdf"], [])


# ============================================================================ C1. para cada opción (modelo)
class TestParaCadaOpcion(unittest.TestCase):
    def test_estrategias(self):
        ei = mod_flujo.elegir_indice
        textos = ["Seleccione una tabla", "Ventas", "Pagos", "-- Elija --"]
        self.assertEqual(ei(textos, "cada_una"), 1)
        self.assertEqual(ei(textos, "marcadas", ["pagos"]), 2)
        self.assertIsNone(ei(textos, "marcadas", []))
        self.assertTrue(mod_flujo.es_marcador_de_lista("-- Seleccione --"))
        self.assertTrue(mod_flujo.es_marcador_de_lista("---"))
        self.assertFalse(mod_flujo.es_marcador_de_lista("Sucursal Selección Norte"))
        p = Paso("elegir_opcion", selectores=["#t"], objetivo="Tabla", estrategia="cada_una")
        self.assertEqual(mod_flujo.opciones_del_bucle(p, textos + ["Ventas", " "]), ["Ventas", "Pagos"])
        m = Paso("elegir_opcion", selectores=["#t"], estrategia="marcadas", valores=["Pagos", "Ventas"])
        self.assertEqual(mod_flujo.opciones_del_bucle(m, textos), ["Pagos", "Ventas"])
        self.assertIn("una tras otra las opciones «Pagos», «Ventas»", m.descripcion())
        self.assertEqual(Paso.desde_dict(m.a_dict()).valores, ["Pagos", "Ventas"])
        self.assertIn("Marca al menos una opción de la lista", Paso("elegir_opcion", selectores=["#t"], estrategia="marcadas").problemas())
        self.assertFalse(p.sin_valor())
        self.assertTrue(mod_flujo.es_bucle(p) and mod_flujo.es_bucle(m))
        self.assertFalse(mod_flujo.es_bucle(Paso("elegir_opcion", selectores=["#t"], estrategia="cada_una", desactivado=True)))

    def test_hasta_donde_se_repite(self):
        c = lambda **k: Paso("clic", selectores=["#x"], **k)                                # noqa: E731
        b = lambda **k: Paso("elegir_opcion", selectores=["#l"], estrategia="cada_una", **k)  # noqa: E731
        pasos = [c(), b(), c(), c(fin_bucle=True), c()]
        self.assertEqual(mod_flujo.fin_del_bucle(pasos, 1), 4)
        self.assertEqual(mod_flujo.fin_del_bucle([c(), b(), c()], 1), 3)                  # sin marca: hasta el final
        anidado = [b(), c(), b(), c(fin_bucle=True), c()]
        self.assertEqual(mod_flujo.fin_del_bucle(anidado, 0), 4)                          # la marca cierra los dos
        self.assertEqual(mod_flujo.fin_del_bucle(anidado, 2), 4)
        self.assertEqual(mod_flujo.fin_del_bucle([b(), c(fin_bucle=True, desactivado=True), c()], 0), 3)
        self.assertEqual(mod_flujo.fin_del_bucle([b(fin_bucle=True), c()], 0), 1)

    def test_usar_filtros_con_un_paso_para_cada_opcion(self):
        f = Flujo(nombre="R", pasos=[Paso("abrir_url", url="http://a/"),
                                     Paso("elegir_opcion", selectores=["#t"], objetivo="Tabla", estrategia="marcadas",
                                          valores=["Ventas"])])
        filas = [{"paso": 1, "opciones": ["Ventas", "Pagos"], "padres": {}, "actualizado": "hoy", "fuente": "ejecucion",
                  "firma": "#t"}]
        d = filtros.datos_panel(f, filas)
        self.assertEqual(d[0]["seleccion"], ["Ventas"])
        self.assertEqual(d[0]["estrategia_guardada"], "marcadas")
        g, _l = filtros.aplicar(f, {1: {"estrategia": "cada_una", "valor": ""}})
        self.assertEqual(g.pasos[1].estrategia, "cada_una")


# ============================================================================ C2. reportes encadenados
class EjecutorFalso:
    """Hace como que ejecuta: devuelve bien o mal según `fallan` (nombres de reportes)."""
    hechos = []
    fallan = set()

    def __init__(self, flujo, **kw):
        self.flujo = flujo

    def ejecutar(self):
        EjecutorFalso.hechos.append(self.flujo.nombre)
        r = ResultadoEjecucion()
        r.total = 1
        r.ok = self.flujo.nombre not in EjecutorFalso.fallan
        if not r.ok:
            r.error, r.paso_fallido = "falló a propósito", 1
        else:
            r.archivos = [self.flujo.nombre + ".xlsx"]
        return r


class TestEncadenar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v39_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        EjecutorFalso.hechos, EjecutorFalso.fallan = [], set()
        self.ids = {}
        for n in ("Ventas", "Pagos", "Informes", "Cartera"):
            self.ids[n] = self.alm.guardar(Flujo(nombre=n, url="http://erp.ejemplo.com/", pasos=[
                Paso("abrir_url", url="http://erp.ejemplo.com/")]))

    def encadenar(self, nombre, *siguientes, cuando="bien"):
        fl = self.alm.cargar_flujo(self.ids[nombre])
        fl.opciones["al_terminar"] = {"reportes": [self.ids[s] for s in siguientes], "cuando": cuando}
        self.alm.guardar(fl, self.ids[nombre])

    def lote(self, *nombres, **kw):
        log = []
        res = lote.ejecutar_lote([self.ids[n] for n in nombres], os.path.join(self.tmp, "perfiles"),
                                 os.path.join(self.tmp, "registros"), almacen=self.alm, fabrica_ejecutor=EjecutorFalso,
                                 log=log.append, **kw)
        return res, log

    def test_cadena_simple_y_condicion(self):
        self.encadenar("Ventas", "Pagos", "Informes")
        res, log = self.lote("Ventas")
        self.assertEqual(EjecutorFalso.hechos, ["Ventas", "Pagos", "Informes"])
        self.assertTrue(res.ok)
        self.assertIn("BIEN    Pagos (después de «Ventas»)", res.resumen())
        self.assertIn("Al terminar «Ventas» se ejecutará «Pagos»", log)
        # si falla y la cadena es «solo si termina bien», no sigue
        EjecutorFalso.hechos, EjecutorFalso.fallan = [], {"Ventas"}
        res, _log = self.lote("Ventas")
        self.assertEqual(EjecutorFalso.hechos, ["Ventas"])
        # «siempre»: sigue aunque falle
        self.encadenar("Ventas", "Pagos", cuando="siempre")
        EjecutorFalso.hechos = []
        res, _log = self.lote("Ventas")
        self.assertEqual(EjecutorFalso.hechos, ["Ventas", "Pagos"])
        self.assertFalse(res.ok)

    def test_sin_circulos_ni_repetidos(self):
        self.encadenar("Ventas", "Pagos")
        self.encadenar("Pagos", "Informes")
        self.encadenar("Informes", "Ventas")             # (guardado a mano: la interfaz no lo deja)
        res, log = self.lote("Ventas")
        self.assertEqual(EjecutorFalso.hechos, ["Ventas", "Pagos", "Informes"])
        self.assertTrue(any("así no hay círculos" in x for x in log), log)
        # en un lote que ya los tiene, no se repiten
        EjecutorFalso.hechos = []
        self.lote("Pagos", "Ventas")
        self.assertEqual(EjecutorFalso.hechos, ["Pagos", "Informes", "Ventas"])
        # un reporte encadenado que ya no existe: aviso, y sigue
        self.alm.eliminar(self.ids["Informes"])
        EjecutorFalso.hechos = []
        res, log = self.lote("Pagos")
        self.assertEqual(EjecutorFalso.hechos, ["Pagos"])
        self.assertTrue(any("ya no existe" in x for x in log), log)

    def test_buscar_circulo(self):
        g = {1: [2], 2: [3], 3: [], 4: [1]}
        self.assertIsNone(lote.buscar_circulo(1, [2], lambda x: g.get(x, [])))
        self.assertEqual(lote.buscar_circulo(3, [4], lambda x: g.get(x, [])), [3, 4, 1, 2, 3])
        self.assertEqual(lote.buscar_circulo(5, [5], lambda x: []), [5, 5])

    def test_ejecucion_suelta_y_validacion(self):
        self.encadenar("Ventas", "Pagos")
        fl = self.alm.cargar_flujo(self.ids["Ventas"])
        self.assertEqual(mod_flujo.reportes_siguientes(fl, True), [self.ids["Pagos"]])
        self.assertEqual(mod_flujo.reportes_siguientes(fl, False), [])
        res = lote.ejecutar_encadenados(fl, self.ids["Ventas"], True, carpeta_perfiles=os.path.join(self.tmp, "p"),
                                        carpeta_registros=os.path.join(self.tmp, "r"), almacen=self.alm,
                                        fabrica_ejecutor=EjecutorFalso)
        self.assertEqual(EjecutorFalso.hechos, ["Pagos"])
        self.assertEqual(res.items[0].despues_de, "Ventas")
        self.assertIsNone(lote.ejecutar_encadenados(fl, self.ids["Ventas"], False, carpeta_perfiles="", carpeta_registros="",
                                                    almacen=self.alm, fabrica_ejecutor=EjecutorFalso))
        for malo in ({"reportes": ["x"]}, {"reportes": [0]}, {"reportes": [1], "cuando": "nunca"}, "x"):
            with self.assertRaises(ErrorFlujo):
                mod_flujo.validar_al_terminar(malo)
        self.assertEqual(mod_flujo.validar_al_terminar({"reportes": ["3", 3, 4]}), {"reportes": [3, 4], "cuando": "bien"})


# ============================================================================ API de la interfaz
class TestApi(SinImpresora):
    def setUp(self):
        super().setUp()
        from webbot import avisos
        from webbot import servidor_ui as su
        self.tmp = tempfile.mkdtemp(prefix="botweb_v39_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        avisos.usar_notificador(lambda t, x: None)
        self.addCleanup(avisos.usar_notificador, None)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.descargas = os.path.join(self.tmp, "descargas")
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "perfiles"),
                                 carpeta_registros=os.path.join(self.tmp, "registros"), carpeta_descargas=self.descargas,
                                 listar_tareas=lambda: [], oculto_forzado=True, hoy=D(2026, 11, 12),
                                 ejecutar_tareas=lambda c: (1, "(prueba: sin tareas)"), abrir_dialogo=_nunca)
        self.addCleanup(self.app.detener)
        self.impresos = []
        self.app.imprimir_archivo = lambda ruta, impresora="", log=None: self.impresos.append((ruta, impresora)) or "Impresora Oficina"
        self.app.listar_impresoras = lambda: {"impresoras": ["Impresora Oficina"], "predeterminada": "Impresora Oficina"}

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})

    def flujo(self, **op):
        f = Flujo(nombre="Informes", url="http://erp.ejemplo.com/", pasos=[
            Paso("abrir_url", url="http://erp.ejemplo.com/"),
            Paso("escribir", selectores=["#desde"], objetivo="Fecha desde", valor="{hoy:%d/%m/%Y}"),
            Paso("escribir", selectores=["#hasta"], objetivo="Fecha hasta", valor="{hoy:%d/%m/%Y}")])
        f.opciones.update(op)
        return f

    def test_describir_periodos_y_usar_periodo(self):
        f = self.flujo(repetir_dias={"modo": "quincenas", "desde": "2026-10-01", "hasta": "2026-11-30", "corte": 15})
        r = self.api("POST", "flujo/describir", {"flujo": f.a_dict()})
        self.assertEqual([x["texto"] for x in r["periodos"]], [
            "1.ª quincena de octubre 2026 (01/10 a 14/10)", "2.ª quincena de octubre 2026 (15/10 a 31/10)",
            "1.ª quincena de noviembre 2026 (01/11 a 14/11)", "2.ª quincena de noviembre 2026 (15/11 a 30/11)"])
        self.assertEqual([x["sin_terminar"] for x in r["periodos"]], [False, False, True, True])
        self.assertEqual(r["dias"], [])
        r = self.api("POST", "flujo/usar_periodo", {"flujo": f.a_dict()})
        self.assertEqual([p.get("valor") for p in r["flujo"]["pasos"][1:]], ["{desde}", "{hasta}"])
        ayuda = self.api("GET", "ayuda")
        self.assertIn("quincenas", ayuda["modos_periodo"])
        self.assertIn("marcadas", ayuda["estrategias"])
        self.assertEqual(ayuda["tipos"]["imprimir"], "Imprimir")

    def test_guardar_rechaza_errores_y_circulos(self):
        from webbot.servidor_ui import ErrorApi
        with self.assertRaisesRegex(ErrorApi, "Repetir por meses"):
            self.api("POST", "reportes", {"flujo": self.flujo(repetir_dias={"modo": "meses", "desde": "x"}).a_dict()})
        a = self.api("POST", "reportes", {"flujo": self.flujo().a_dict()})["id"]
        fb = self.flujo(al_terminar={"reportes": [a]})
        fb.nombre = "Pagos"
        b = self.api("POST", "reportes", {"flujo": fb.a_dict()})["id"]
        fa = self.flujo(al_terminar={"reportes": [b]})
        with self.assertRaisesRegex(ErrorApi, "círculo.*«Informes» → «Pagos» → «Informes»"):
            self.api("PUT", "reportes/%d" % a, {"flujo": fa.a_dict()})
        with self.assertRaisesRegex(ErrorApi, "a sí mismo"):
            self.api("PUT", "reportes/%d" % a, {"flujo": self.flujo(al_terminar={"reportes": [a]}).a_dict()})
        with self.assertRaisesRegex(ErrorApi, "no existe el reporte número 99"):
            self.api("PUT", "reportes/%d" % a, {"flujo": self.flujo(al_terminar={"reportes": [99]}).a_dict()})
        fb.opciones["al_terminar"] = {}
        self.api("PUT", "reportes/%d" % b, {"flujo": fb.a_dict()})
        self.api("PUT", "reportes/%d" % a, {"flujo": fa.a_dict()})                    # ya no hay círculo
        self.assertEqual(self.alm.cargar_flujo(a).opciones["al_terminar"], {"reportes": [b]})

    def test_imprimir_un_archivo_y_las_impresoras(self):
        os.makedirs(self.descargas)
        ruta = os.path.join(self.descargas, "Informes.pdf")
        with open(ruta, "w") as f:
            f.write("x")
        r = self.api("POST", "archivos/imprimir", {"ruta": ruta})
        self.assertEqual((r["impresora"], r["archivo"]), ("Impresora Oficina", "Informes.pdf"))
        self.assertEqual(self.impresos, [(ruta, "")])
        from webbot.servidor_ui import ErrorApi
        with self.assertRaisesRegex(ErrorApi, "no está en la carpeta de descargas"):
            self.api("POST", "archivos/imprimir", {"ruta": os.path.join(self.tmp, "otro.pdf")})
        self.assertEqual(self.api("GET", "impresoras")["predeterminada"], "Impresora Oficina")

    def test_programar_propone_el_horario_del_periodo(self):
        rid = self.alm.guardar(self.flujo(repetir_dias={"modo": "quincenas", "rango": "anterior", "corte": 16}))
        r = self.api("GET", "reportes/%d/programar" % rid)
        self.assertEqual(r["sugerida"]["reglas"][0]["dias_mes"], [1, 16])
        rid2 = self.alm.guardar(Flujo(nombre="Sin repetir", pasos=[Paso("abrir_url", url="http://a/")]))
        self.assertIsNone(self.api("GET", "reportes/%d/programar" % rid2)["sugerida"])


if __name__ == "__main__":
    unittest.main()
