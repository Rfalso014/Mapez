"""Pruebas de la v3.9: la fecha con UN calendario (rojo = Desde, azul = Hasta), «Descargar en esta fecha cada mes»,
«Imprimir los PDF que descargue» y la lista de todo lo que baja una ejecución grande.

1. Plantillas: {dia_mes_anterior:N} (con 31 = el último día y los días que no existen, p. ej. 30 en febrero) y la fecha
   elegida → la misma del mes anterior (01/10–31/10 → el mes anterior; 15/10–31/10 → del 15 al último día).
2. Qué campo recibe la fecha roja y cuál la azul (por el nombre, por el orden, con un solo campo) y lo que se guarda.
3. El horario del día 1 de cada mes: se crea, se cambia y se quita (tareas de Windows FALSAS: nunca schtasks).
4. «Imprimir los PDF…»: solo los PDF, con impresora falsa; si falla, la descarga sigue bien.
5. La lista de descargas: «para cada opción» y periodos (también con el navegador oculto contra el sitio de prueba).
6. Interfaz (navegador oculto, base de datos temporal): el calendario, la casilla de imprimir y la lista en vivo.

Sin la base de datos real, sin llavero, sin avisos, sin impresoras, sin tareas de Windows y sin red.
"""

import datetime
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from webbot import avisos, dialogos, filtros, horario, impresion, plantillas, programador, secretos  # noqa: E402
from webbot import fechas_reporte as mf  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.ejecutor import Ejecutor  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402
from webbot.lista_descargas import ListaDescargas, plural, tipo_archivo  # noqa: E402

D = datetime.date
HOY = D(2026, 11, 13)


def _nunca(*a, **k):
    raise AssertionError("¡Una prueba intentó usar Windows de verdad (impresora, diálogo o tarea)!")


def r(texto, hoy):
    return plantillas.renderizar(texto, hoy=hoy)


def reporte(nombre="Pagos", desde="{hoy:%d/%m/%Y}", hasta="{hoy:%Y-%m-%d}", n_desde="DateFrom", n_hasta="DateTo",
            al_reves=False):
    pasos = [Paso("escribir", selectores=["#" + n_desde], objetivo=n_desde, valor=desde, fecha_directa=True),
             Paso("escribir", selectores=["#" + n_hasta], objetivo=n_hasta, valor=hasta, fecha_directa=True)]
    if al_reves:
        pasos.reverse()
    return Flujo(nombre=nombre, url="http://pagos.ejemplo.com/", pasos=[Paso("abrir_url", url="http://pagos.ejemplo.com/")]
                 + pasos + [Paso("descargar", selectores=["#PDF"], objetivo="PDF", nombre="{reporte}{ext}")])


def valor_de(fl, objetivo):
    return next(p.valor for p in fl.pasos if p.objetivo == objetivo)


# ======================================================================== 1. plantillas «cada mes»
class TestDiaDelMesAnterior(unittest.TestCase):
    def test_dia_n_y_ultimo_dia(self):
        self.assertEqual(r("{dia_mes_anterior:15}", D(2026, 11, 13)), "15/10/2026")
        self.assertEqual(r("{dia_mes_anterior:31}", D(2026, 12, 1)), "30/11/2026")          # 31 = el último día
        self.assertEqual(r("{dia_mes_anterior:1:%Y-%m-%d}", D(2026, 1, 1)), "2025-12-01")

    def test_febrero_se_ajusta(self):
        self.assertEqual(r("{dia_mes_anterior:30}", D(2026, 3, 1)), "28/02/2026")
        self.assertEqual(r("{dia_mes_anterior:30}", D(2024, 3, 1)), "29/02/2024")           # bisiesto
        self.assertEqual(plantillas.dia_del_mes_anterior(D(2026, 3, 20), 29), D(2026, 2, 28))

    def test_errores(self):
        for t in ("{dia_mes_anterior}", "{dia_mes_anterior:0}", "{dia_mes_anterior:32}", "{dia_mes_anterior:x}"):
            with self.assertRaises(plantillas.ErrorPlantilla, msg=t):
                r(t, HOY)

    def test_analizar_componer_y_describir(self):
        a = plantillas.analizar_fecha("{dia_mes_anterior:15:%Y-%m-%d}")
        self.assertEqual(a, {"modo": "relativa", "que": "dia_mes_anterior", "n": 15, "formato": "%Y-%m-%d"})
        self.assertEqual(plantillas.plantilla_fecha(a), "{dia_mes_anterior:15:%Y-%m-%d}")
        self.assertEqual(plantillas.describir_fecha("{dia_mes_anterior:15}", HOY), "día 15 del mes anterior · 15/10/2026")
        self.assertEqual(plantillas.formato_de_fecha("{dia_mes_anterior:3}"), "%d/%m/%Y")
        self.assertEqual(plantillas.variables_usadas("{dia_mes_anterior:3}"), [])            # no es una variable propia
        self.assertTrue(filtros.es_fecha(Paso("escribir", selectores=["#x"], objetivo="Campo", valor="{dia_mes_anterior:3}")))
        self.assertTrue(plantillas.misma_fecha("{ayer}", "{ayer:%d/%m/%Y}"))
        self.assertFalse(plantillas.misma_fecha("{ayer}", "{hoy}"))


class TestLaMismaFechaCadaMes(unittest.TestCase):
    def cada_mes(self, desde, hasta, cuando, fmt="%d/%m/%Y"):
        return (r(plantillas.plantilla_cada_mes(desde, fmt), cuando), r(plantillas.plantilla_cada_mes(hasta, fmt), cuando))

    def test_plantillas(self):
        self.assertEqual(plantillas.plantilla_cada_mes(D(2026, 10, 1), "%d/%m/%Y"), "{inicio_mes_anterior:%d/%m/%Y}")
        self.assertEqual(plantillas.plantilla_cada_mes(D(2026, 10, 31)), "{fin_mes_anterior}")
        self.assertEqual(plantillas.plantilla_cada_mes(D(2026, 11, 30)), "{fin_mes_anterior}")      # el último de noviembre
        self.assertEqual(plantillas.plantilla_cada_mes(D(2026, 10, 30)), "{dia_mes_anterior:30}")   # no es el último
        self.assertEqual(plantillas.plantilla_cada_mes(D(2026, 10, 15), "%Y-%m-%d"), "{dia_mes_anterior:15:%Y-%m-%d}")

    def test_mes_entero(self):
        """01/10–31/10 + «cada mes»: el 1 de diciembre baja 01/11–30/11; el 1 de enero, 01/12–31/12."""
        self.assertEqual(self.cada_mes(D(2026, 10, 1), D(2026, 10, 31), D(2026, 12, 1)), ("01/11/2026", "30/11/2026"))
        self.assertEqual(self.cada_mes(D(2026, 10, 1), D(2026, 10, 31), D(2027, 1, 1)), ("01/12/2026", "31/12/2026"))
        self.assertEqual(self.cada_mes(D(2026, 10, 1), D(2026, 10, 31), D(2026, 3, 1)), ("01/02/2026", "28/02/2026"))

    def test_del_15_al_ultimo_dia(self):
        """15/10–31/10: cada mes, del 15 al ÚLTIMO día del mes anterior (también en febrero)."""
        self.assertEqual(self.cada_mes(D(2026, 10, 15), D(2026, 10, 31), D(2026, 12, 1)), ("15/11/2026", "30/11/2026"))
        self.assertEqual(self.cada_mes(D(2026, 10, 15), D(2026, 10, 31), D(2026, 3, 1)), ("15/02/2026", "28/02/2026"))
        self.assertEqual(self.cada_mes(D(2026, 10, 15), D(2026, 10, 31), D(2024, 3, 1)), ("15/02/2024", "29/02/2024"))

    def test_dia_que_no_existe_en_febrero(self):
        self.assertEqual(self.cada_mes(D(2026, 10, 10), D(2026, 10, 30), D(2026, 3, 1)), ("10/02/2026", "28/02/2026"))


# ======================================================================== 2. rojo → desde, azul → hasta
class TestRoles(unittest.TestCase):
    def roles(self, fl):
        campos, por_orden = mf.campos_de_fecha(fl)
        return {c["nombre"]: c["rol"] for c in campos}, por_orden

    def test_por_el_nombre(self):
        self.assertEqual(self.roles(reporte(al_reves=True)), ({"DateTo": "hasta", "DateFrom": "desde"}, False))
        self.assertEqual(self.roles(reporte(n_desde="FechaInicial", n_hasta="FechaFinal")),
                         ({"FechaInicial": "desde", "FechaFinal": "hasta"}, False))
        self.assertEqual(self.roles(reporte(n_desde="fecha_hasta", n_hasta="fecha_desde")),
                         ({"fecha_hasta": "hasta", "fecha_desde": "desde"}, False))

    def test_por_el_orden_si_el_nombre_no_lo_dice(self):
        self.assertEqual(self.roles(reporte(n_desde="Campo1", n_hasta="Campo2")), ({"Campo1": "desde", "Campo2": "hasta"}, True))

    def test_un_solo_campo(self):
        fl = reporte()
        del fl.pasos[2]
        self.assertEqual(self.roles(fl), ({"DateFrom": "unica"}, False))
        self.assertEqual(mf.aplicar_eleccion(fl, "2026-10-05", "2026-10-20")[0][:8], "paso 2 (")
        self.assertEqual(valor_de(fl, "DateFrom"), "05/10/2026")                             # solo la roja

    def test_rojo_al_desde_y_azul_al_hasta_con_su_formato(self):
        fl = reporte(al_reves=True)
        lineas = mf.aplicar_eleccion(fl, "2026-10-01", "2026-10-31")
        self.assertEqual(len(lineas), 2)
        self.assertEqual((valor_de(fl, "DateFrom"), valor_de(fl, "DateTo")), ("01/10/2026", "2026-10-31"))
        # el orden en que se tocan no importa: la fecha menor es el «Desde»
        mf.aplicar_eleccion(fl, "2026-10-31", "2026-10-01")
        self.assertEqual((valor_de(fl, "DateFrom"), valor_de(fl, "DateTo")), ("01/10/2026", "2026-10-31"))

    def test_cambiarlas(self):
        fl = reporte(n_desde="Campo1", n_hasta="Campo2")
        mf.aplicar_eleccion(fl, "2026-10-01", "2026-10-31", invertir=True)
        self.assertEqual((valor_de(fl, "Campo1"), valor_de(fl, "Campo2")), ("31/10/2026", "2026-10-01"))

    def test_sin_tocar_el_calendario_no_cambia_nada(self):
        fl = reporte(desde="{inicio_mes_anterior}", hasta="{fin_mes_anterior:%Y-%m-%d}")
        self.assertEqual(mf.aplicar_eleccion(fl, "2026-10-01", "2026-10-31", cambiadas=False), [])
        self.assertEqual((valor_de(fl, "DateFrom"), valor_de(fl, "DateTo")), ("{inicio_mes_anterior}", "{fin_mes_anterior:%Y-%m-%d}"))
        # «cada mes» con lo mismo que ya tenía: tampoco cambia (el formato por defecto escrito o no es lo mismo)
        self.assertEqual(mf.aplicar_eleccion(fl, "2026-10-01", "2026-10-31", cada_mes=True, cambiadas=False), [])

    def test_cada_mes_guarda_plantillas(self):
        fl = reporte()
        mf.aplicar_eleccion(fl, "2026-10-15", "2026-10-31", cada_mes=True)
        self.assertEqual((valor_de(fl, "DateFrom"), valor_de(fl, "DateTo")),
                         ("{dia_mes_anterior:15:%d/%m/%Y}", "{fin_mes_anterior:%Y-%m-%d}"))
        with self.assertRaises(mf.ErrorFechas):                                             # dos meses distintos
            mf.aplicar_eleccion(fl, "2026-09-20", "2026-10-19", cada_mes=True)

    def test_listas_por_fecha_y_la_mas_reciente(self):
        fl = Flujo(nombre="Cortes", pasos=[Paso("elegir_opcion", selectores=["#c"], objetivo="Corte", filtro="Corte",
                                                estrategia="mas_reciente")])
        self.assertEqual(mf.campos_de_fecha(fl)[0][0]["rol"], "unica")
        self.assertEqual(mf.aplicar_eleccion(fl, "2026-11-04", cambiadas=False, mas_reciente=True), [])
        mf.aplicar_eleccion(fl, "2026-11-04")
        self.assertEqual((fl.pasos[0].estrategia, fl.pasos[0].valor), ("por_fecha", "04/11/2026"))
        mf.aplicar_eleccion(fl, "2026-11-04", mas_reciente=True)
        self.assertEqual((fl.pasos[0].estrategia, fl.pasos[0].valor), ("mas_reciente", ""))

    def test_con_repetir_por_meses_el_rango_es_el_de_la_repeticion(self):
        fl = reporte(desde="{desde}", hasta="{hasta:%Y-%m-%d}")
        fl.opciones["repetir_dias"] = {"modo": "meses", "rango": "anterior"}
        mf.aplicar_eleccion(fl, "2026-08-01", "2026-10-31")
        self.assertEqual(fl.opciones["repetir_dias"], {"modo": "meses", "rango": "fijo", "desde": "2026-08-01", "hasta": "2026-10-31"})
        self.assertEqual((valor_de(fl, "DateFrom"), valor_de(fl, "DateTo")), ("{desde}", "{hasta:%Y-%m-%d}"))   # no se tocan
        self.assertEqual(len(mod_flujo.periodos_a_repetir(fl.opciones["repetir_dias"])), 3)
        mf.aplicar_eleccion(fl, "2026-08-01", "2026-10-31", cada_mes=True, cambiadas=False)
        self.assertEqual(fl.opciones["repetir_dias"]["rango"], "anterior")
        fl.opciones["repetir_dias"] = {"modo": "ultimos", "n": 3}
        with self.assertRaises(mf.ErrorFechas):
            mf.aplicar_eleccion(fl, "2026-10-01", "2026-10-31", cada_mes=True)

    def test_horario_cada_mes(self):
        p = mf.programacion_cada_mes("08:30")
        self.assertEqual(p["reglas"], [{"tipo": "mensual", "dias_mes": [1], "horas": ["08:30"], "meses": list(range(1, 13))}])
        self.assertTrue(mf.es_horario_cada_mes(p))
        self.assertEqual(mf.describir_cada_mes(p), "Se bajará solo el día 1 de cada mes a las 08:30")
        self.assertFalse(mf.es_horario_cada_mes({"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["07:00"]}]}))
        q = mf.programacion_cada_mes("07:00", {"modo": "quincenas", "corte": 16})
        self.assertEqual(q["reglas"][0]["dias_mes"], [1, 16])
        self.assertEqual(mf.describir_cada_mes(q), "Se bajará solo los días 1 y 16 de cada mes a las 07:00")
        with self.assertRaises(mf.ErrorFechas):
            mf.programacion_cada_mes("25:00")


# ======================================================================== 3. el horario del día 1 (con tareas falsas)
class BaseApp(unittest.TestCase):
    def setUp(self):
        for objeto, nombre in ((impresion, "_lanzar"), (impresion, "_imprimir_pdf_windows"), (impresion, "_enumerar"),
                               (impresion, "_predeterminada"), (dialogos, "_dialogo_tk"), (programador, "_ejecutar")):
            p = mock.patch.object(objeto, nombre, _nunca)
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp(prefix="botweb_v39f_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        avisos.usar_notificador(lambda t, x: None)
        self.addCleanup(avisos.usar_notificador, None)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.comandos = []
        self.tareas = []                                     # las tareas «de Windows» (falsas) que dice listar_tareas

        def ejecutar(cmd):
            self.comandos.append(list(cmd))
            nombre = cmd[cmd.index("/TN") + 1].split("\\")[-1] if "/TN" in cmd else ""
            if "/Create" in cmd and nombre not in [t["nombre"] for t in self.tareas]:
                self.tareas.append({"nombre": nombre, "proxima": "", "estado": "Listo"})
            if "/Delete" in cmd:
                self.tareas[:] = [t for t in self.tareas if t["nombre"] != nombre]
            return 0, "CORRECTO"
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "perfiles"),
                                 carpeta_registros=os.path.join(self.tmp, "registros"),
                                 carpeta_descargas=os.path.join(self.tmp, "descargas"), listar_tareas=lambda: list(self.tareas),
                                 oculto_forzado=True, hoy=HOY, ejecutar_tareas=ejecutar, abrir_dialogo=_nunca)
        self.app.listar_impresoras = lambda: {"impresoras": ["Impresora Oficina", "Impresora Bodega"],
                                              "predeterminada": "Impresora Oficina"}
        self.app.imprimir_archivo = _nunca
        self.addCleanup(self.app.detener)

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})


class TestApiFechas(BaseApp):
    def test_ver_y_guardar_con_cada_mes_y_quitarlo(self):
        rid = self.alm.guardar(reporte(al_reves=True))
        v = self.api("GET", "reportes/%d/fechas" % rid)
        self.assertEqual([(c["nombre"], c["rol"]) for c in v["campos"]], [("DateTo", "hasta"), ("DateFrom", "desde")])
        self.assertEqual((v["por_orden"], v["hoy"], v["cada_mes"]["programado"]), (False, "2026-11-13", False))
        # 01/10–31/10 + «cada mes» a las 06:30
        res = self.api("POST", "reportes/%d/fechas" % rid, {"desde": "2026-10-01", "hasta": "2026-10-31",
                                                           "cada_mes": {"activo": True, "hora": "06:30"}})
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual((valor_de(fl, "DateFrom"), valor_de(fl, "DateTo")),
                         ("{inicio_mes_anterior:%d/%m/%Y}", "{fin_mes_anterior:%Y-%m-%d}"))
        self.assertTrue(self.alm.versiones(rid))                                              # con su copia de antes
        self.assertEqual(res["horario"], "creado")
        self.assertEqual(res["cada_mes"], {"programado": True, "hora": "06:30", "otro_horario": "",
                                           "texto": "Se bajará solo el día 1 de cada mes a las 06:30"})
        g = self.alm.programacion("reporte:%d" % rid)
        self.assertEqual(g["programacion"]["reglas"], [{"tipo": "mensual", "dias_mes": [1], "horas": ["06:30"],
                                                        "meses": list(range(1, 13))}])
        self.assertEqual([c[1] for c in self.comandos], ["/Create"])                          # (con el XML, falso)
        self.assertEqual([t["nombre"] for t in self.tareas], ["Pagos"])
        # lo mismo otra vez: no se toca la tarea
        self.api("POST", "reportes/%d/fechas" % rid, {"desde": "2026-10-01", "hasta": "2026-10-31", "cambiadas": False,
                                                     "cada_mes": {"activo": True, "hora": "06:30"}})
        self.assertEqual(len(self.comandos), 1)
        # otra hora: se cambia
        self.api("POST", "reportes/%d/fechas" % rid, {"desde": "2026-10-01", "hasta": "2026-10-31", "cambiadas": False,
                                                     "cada_mes": {"activo": True, "hora": "08:00"}})
        self.assertEqual(self.alm.programacion("reporte:%d" % rid)["programacion"]["reglas"][0]["horas"], ["08:00"])
        # sin la casilla: se quita la tarea y lo guardado (las fechas siguen como estaban)
        res = self.api("POST", "reportes/%d/fechas" % rid, {"desde": "2026-10-01", "hasta": "2026-10-31", "cambiadas": False,
                                                           "cada_mes": {"activo": False}})
        self.assertEqual(res["horario"], "quitado")
        self.assertIsNone(self.alm.programacion("reporte:%d" % rid))
        self.assertEqual(self.tareas, [])
        self.assertEqual(self.comandos[-1][1], "/Delete")
        self.assertEqual(valor_de(self.alm.cargar_flujo(rid), "DateFrom"), "{inicio_mes_anterior:%d/%m/%Y}")

    def test_otro_horario_no_se_quita_sin_la_casilla(self):
        rid = self.alm.guardar(reporte())
        semanal = {"reglas": [{"tipo": "semanal", "dias": ["lun", "mar"], "horas": ["09:00"]}], "inicio": "", "fin": ""}
        self.alm.guardar_programacion("reporte:%d" % rid, semanal, "BotWeb\\Pagos")
        v = self.api("GET", "reportes/%d/fechas" % rid)
        self.assertFalse(v["cada_mes"]["programado"])
        self.assertIn("lunes", v["cada_mes"]["otro_horario"])
        res = self.api("POST", "reportes/%d/fechas" % rid, {"desde": "2026-10-05", "hasta": "2026-10-09"})
        self.assertIsNone(res["horario"])
        self.assertEqual(self.comandos, [])
        self.assertEqual(self.alm.programacion("reporte:%d" % rid)["programacion"]["reglas"][0]["tipo"], "semanal")
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual((valor_de(fl, "DateFrom"), valor_de(fl, "DateTo")), ("05/10/2026", "2026-10-09"))

    def test_sin_tarea_de_windows_se_quita_lo_guardado(self):
        rid = self.alm.guardar(reporte())
        self.alm.guardar_programacion("reporte:%d" % rid, mf.programacion_cada_mes("07:00"), "BotWeb\\Pagos")
        self.assertTrue(self.api("GET", "reportes/%d/fechas" % rid)["cada_mes"]["programado"])
        self.api("POST", "reportes/%d/fechas" % rid, {"desde": "2026-10-01", "cambiadas": False, "cada_mes": {"activo": False}})
        self.assertIsNone(self.alm.programacion("reporte:%d" % rid))
        self.assertEqual(self.comandos, [])                                               # no había tarea que borrar

    def test_repetir_por_quincenas(self):
        fl = reporte(desde="{desde}", hasta="{hasta}")
        fl.opciones["repetir_dias"] = {"modo": "quincenas", "rango": "fijo", "desde": "2026-09-01", "hasta": "2026-09-30",
                                       "corte": 16, "mitades": "ambas"}
        rid = self.alm.guardar(fl)
        v = self.api("GET", "reportes/%d/fechas" % rid)
        self.assertEqual((v["repetir"]["modo"], v["repetir"]["n"], v["repetir"]["desde"], v["repetir"]["hasta"]),
                         ("quincenas", 2, "2026-09-01", "2026-09-30"))
        self.api("POST", "reportes/%d/fechas" % rid, {"desde": "2026-09-01", "hasta": "2026-10-31", "cambiadas": False,
                                                     "cada_mes": {"activo": True, "hora": "07:00"}})
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual(fl.opciones["repetir_dias"]["rango"], "anterior")
        self.assertEqual(self.alm.programacion("reporte:%d" % rid)["programacion"]["reglas"][0]["dias_mes"], [1, 16])

    def test_errores_claros(self):
        rid = self.alm.guardar(reporte())
        with self.assertRaises(su.ErrorApi) as e:
            self.api("POST", "reportes/%d/fechas" % rid, {"desde": "2026-09-20", "hasta": "2026-10-19",
                                                         "cada_mes": {"activo": True}})
        self.assertIn("mismo mes", str(e.exception))
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "reportes/%d/fechas" % rid, {"desde": "ayer"})
        self.assertEqual(self.comandos, [])

    def test_imprimir_pdf_del_reporte(self):
        rid = self.alm.guardar(reporte())
        self.assertEqual(self.api("GET", "reportes")["reportes"][0]["imprimir_pdf"], {"activo": False, "impresora": ""})
        self.api("POST", "reportes/%d/imprimir" % rid, {"activo": True, "impresora": "Impresora Bodega"})
        self.assertEqual(self.alm.cargar_flujo(rid).opciones["imprimir_pdf"], {"activo": True, "impresora": "Impresora Bodega"})
        self.assertEqual(self.api("GET", "inicio")["reportes"][0]["imprimir_pdf"]["impresora"], "Impresora Bodega")

    def test_lista_de_descargas_en_el_estado(self):
        t = su.Trabajo("ejecutar", "Ejecutar «Pagos»")
        self.app._avisar_descargas(t, 7)({"titulo": "Pagos — 1 de 2 comercios", "items": []})
        self.assertEqual(self.api("GET", "estado")["descargas"]["reporte_id"], 7)
        eventos, _ = self.app.eventos.desde(0)
        self.assertEqual([e["tipo"] for e in eventos][-1], "descargas")
        self.app.lanzar("ejecutar", "Otro", lambda t: (True, ""))                          # otra ejecución: ya no vale
        self.assertIsNone(self.api("GET", "estado")["descargas"])


# ======================================================================== 4. «Imprimir los PDF que descargue»
class TestImprimirPdf(unittest.TestCase):
    def setUp(self):
        for nombre in ("_lanzar", "_imprimir_pdf_windows", "_enumerar", "_predeterminada"):
            p = mock.patch.object(impresion, nombre, _nunca)               # nunca una impresora de verdad
            p.start()
            self.addCleanup(p.stop)

    def ejecutor(self, imprimir, activo=True, impresora=""):
        tmp = tempfile.mkdtemp(prefix="botweb_v39i_")
        self.addCleanup(shutil.rmtree, tmp, True)
        fl = reporte()
        fl.opciones["imprimir_pdf"] = {"activo": activo, "impresora": impresora}
        self.lineas = []
        ej = Ejecutor(fl, carpeta_perfil=os.path.join(tmp, "p"), carpeta_registros=tmp, carpeta_descargas=tmp,
                      log=self.lineas.append, imprimir=imprimir)
        self.archivos = []
        for n in ("Pagos.pdf", "Pagos.xlsx", "Pagos.csv", "Otro.PDF"):
            ruta = os.path.join(tmp, n)
            with open(ruta, "wb") as f:
                f.write(b"%PDF-1.4\n" if n.lower().endswith(".pdf") else b"a;b\n")
            self.archivos.append(ruta)
        return ej

    def test_solo_los_pdf(self):
        llamadas = []
        ej = self.ejecutor(lambda ruta, impresora, log=None: llamadas.append((os.path.basename(ruta), impresora)) or "Impresora Bodega",
                           impresora="Impresora Bodega")
        for a in self.archivos:
            ej._archivo_nuevo(a)
        self.assertEqual(llamadas, [("Pagos.pdf", "Impresora Bodega"), ("Otro.PDF", "Impresora Bodega")])
        self.assertEqual(ej.resultado.archivos, self.archivos)
        self.assertEqual([i["archivo"] for i in ej.resultado.impresiones], [self.archivos[0], self.archivos[3]])
        self.assertTrue(any(l.endswith("PDF enviado a imprimir: Pagos.pdf → Impresora Bodega") for l in self.lineas), self.lineas)

    def test_con_el_paso_imprimir_no_se_imprime_dos_veces(self):
        llamadas = []
        ej = self.ejecutor(lambda ruta, impresora, log=None: llamadas.append(os.path.basename(ruta)) or "Impresora Oficina")
        ej._archivo_nuevo(self.archivos[0])
        ej._paso_imprimir(Paso("imprimir", que_imprimir="archivo"), None, 10)
        self.assertEqual(llamadas, ["Pagos.pdf"])
        ej._archivo_nuevo(self.archivos[1])                               # un Excel: lo imprime el paso, no la casilla
        ej._paso_imprimir(Paso("imprimir", que_imprimir="archivo"), None, 10)
        self.assertEqual(llamadas, ["Pagos.pdf", "Pagos.xlsx"])

    def test_impresora_de_windows_por_defecto(self):
        llamadas = []
        ej = self.ejecutor(lambda ruta, impresora, log=None: llamadas.append(impresora) or "Impresora Oficina")
        ej._archivo_nuevo(self.archivos[0])
        self.assertEqual(llamadas, [""])
        self.assertTrue(any(l.endswith("PDF enviado a imprimir: Pagos.pdf → Impresora Oficina") for l in self.lineas))

    def test_si_falla_la_descarga_sigue_bien(self):
        def falla(ruta, impresora, log=None):
            raise impresion.ErrorImpresion("No hay ninguna impresora instalada en Windows")
        ej = self.ejecutor(falla)
        ej._archivo_nuevo(self.archivos[0])
        ej._archivo_nuevo(self.archivos[1])
        self.assertEqual(ej.resultado.archivos, self.archivos[:2])
        self.assertEqual(ej.resultado.sin_imprimir, [(self.archivos[0], "No hay ninguna impresora instalada en Windows")])
        self.assertTrue(any("No se pudo imprimir «Pagos.pdf»: No hay ninguna impresora instalada en Windows (el archivo sí se "
                            "descargó)" in l for l in self.lineas), self.lineas)
        ej.resultado.ok = True
        self.assertIn("1 PDF sin imprimir", ej.resultado.resumen())

    def test_sin_la_casilla_no_imprime(self):
        ej = self.ejecutor(_nunca, activo=False)
        for a in self.archivos:
            ej._archivo_nuevo(a)
        self.assertEqual(ej.resultado.impresiones, [])

    def test_por_defecto_usa_el_modulo_de_impresion(self):
        with mock.patch.object(impresion, "imprimir_archivo", return_value="Impresora Oficina") as falso:
            ej = self.ejecutor(None)
            ej._archivo_nuevo(self.archivos[0])
        falso.assert_called_once()

    def test_opcion_canonica(self):
        self.assertEqual(mod_flujo.imprimir_pdf({}), {"activo": False, "impresora": ""})
        self.assertEqual(mod_flujo.imprimir_pdf({"imprimir_pdf": True}), {"activo": True, "impresora": ""})
        self.assertEqual(mod_flujo.imprimir_pdf({"imprimir_pdf": {"activo": True, "impresora": " X "}}), {"activo": True, "impresora": "X"})


# ======================================================================== 5. la lista de descargas
class TestListaDescargas(unittest.TestCase):
    def setUp(self):
        self.avisos = []

    def ultimo(self):
        return self.avisos[-1]

    def test_para_cada_opcion_sin_saber_las_opciones(self):
        l = ListaDescargas("Pagos", self.avisos.append, periodos=["octubre 2026"], modo_periodo="meses", lista="Comercio",
                           por_pase=2)
        self.assertTrue(self.ultimo()["por_leer"])
        self.assertIn("las opciones de «Comercio» (se sabrá cuántas al leer la lista)", self.ultimo()["resumen"])
        l.opciones_leidas(0, ["TIENDA %d" % n for n in range(1, 18)])
        self.assertEqual(self.ultimo()["resumen"], "Se van a bajar 17 comercios × 1 mes = 34 archivos")
        for n in range(1, 6):
            l.empezar(0, "TIENDA %d" % n)
            l.archivo("C:/x/Pagos - TIENDA %d.pdf" % n)
            l.archivo("C:/x/Pagos - TIENDA %d.xls" % n)
            l.terminar(n != 3, "paso 6: No llegó ninguna descarga")
        l.empezar(0, "TIENDA 6")
        d = self.ultimo()
        self.assertEqual(d["titulo"], "Pagos — 6 de 17 comercios")
        self.assertEqual([it["estado"] for it in d["items"][:7]], ["listo", "listo", "fallo", "listo", "listo", "descargando", "pendiente"])
        self.assertEqual([a["tipo"] for a in d["items"][0]["archivos"]], ["PDF", "Excel"])
        self.assertEqual(d["items"][2]["motivo"], "paso 6: No llegó ninguna descarga")
        l.cerrar(detenido=True)
        d = self.ultimo()
        self.assertTrue(d["terminado"])
        self.assertEqual((d["items"][5]["estado"], d["items"][5]["motivo"]), ("fallo", "Detenido por ti"))
        self.assertEqual((d["listos"], d["fallos"], d["sin_hacer"]), (4, 2, 11))
        self.assertEqual(d["titulo"], "Pagos — 6 de 17 comercios")

    def test_opciones_marcadas_por_periodos(self):
        l = ListaDescargas("Informes", self.avisos.append, periodos=["septiembre 2026", "octubre 2026"],
                           modo_periodo="meses", lista="Sucursal", opciones=["Norte", "Sur"])
        self.assertEqual(self.ultimo()["resumen"], "Se van a bajar 2 sucursales × 2 meses = 4 archivos")
        self.assertEqual([(it["periodo_texto"], it["texto"]) for it in self.ultimo()["items"]],
                         [("septiembre 2026", "Norte"), ("septiembre 2026", "Sur"), ("octubre 2026", "Norte"), ("octubre 2026", "Sur")])
        self.assertTrue(self.ultimo()["con_periodos"])
        self.assertEqual(self.ultimo()["titulo"], "Informes — 0 de 4 descargas")

    def test_solo_periodos_y_fallo_que_para(self):
        l = ListaDescargas("Ventas", self.avisos.append, periodos=["01/11/2026", "02/11/2026", "03/11/2026"], por_pase=1)
        self.assertEqual(self.ultimo()["resumen"], "Se van a bajar 3 días = 3 archivos")
        l.empezar(0)
        l.archivo("C:/x/Ventas.csv")
        l.terminar(True)
        l.empezar(1)
        l.terminar(False, "No llegó ninguna descarga")
        l.cerrar(error="No llegó ninguna descarga")
        self.assertEqual([it["estado"] for it in self.ultimo()["items"]], ["listo", "fallo", "sin_hacer"])
        self.assertEqual(self.ultimo()["items"][2]["motivo"], "No se llegó a bajar")

    def test_una_lista_distinta_en_otro_pase(self):
        l = ListaDescargas("Pagos", self.avisos.append, periodos=["septiembre 2026", "octubre 2026"], modo_periodo="meses",
                           lista="Comercio")
        l.opciones_leidas(0, ["A", "B"])
        self.assertEqual(len(self.ultimo()["items"]), 4)
        l.opciones_leidas(1, ["A", "B", "C"])
        self.assertEqual([(it["periodo"], it["texto"]) for it in self.ultimo()["items"]],
                         [(0, "A"), (0, "B"), (1, "A"), (1, "B"), (1, "C")])
        l.fallo_pase(1, "No se pudo leer la lista")
        self.assertEqual([it["estado"] for it in self.ultimo()["items"]][2:], ["fallo"] * 3)

    def test_palabras(self):
        self.assertEqual([plural(x, 2) for x in ("Comercio", "Sucursal", "Región", "Mes", "Tipo de reporte", "«Tienda»")],
                         ["comercios", "sucursales", "regiones", "mes", "opciones", "tiendas"])
        self.assertEqual(plural("Comercio", 1), "comercio")
        self.assertEqual([tipo_archivo(x) for x in ("a.PDF", "b.xlsx", "c.xls", "d.csv", "e.html", "f.bin")],
                         ["PDF", "Excel", "Excel", "CSV", "HTML", "BIN"])


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestListaConElNavegador(unittest.TestCase):
    """El sitio de prueba del portal de Pagos (navegador oculto): cada comercio × cada mes, con la lista en vivo y la
    impresora falsa."""

    @classmethod
    def setUpClass(cls):
        from servidor_prueba import ServidorPrueba
        cls.servidor = ServidorPrueba().iniciar()
        cls.base = cls.servidor.url_base

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v39l_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)

    def flujo(self, eleccion, desde, hasta):
        from test_v39_pagos import NOMBRE
        url = self.base + "pagos_consulta.html"
        f = Flujo(nombre="Pagos", url=url)
        f.opciones.update(timeout_paso=8, timeout_descarga=20)
        f.pasos = [Paso("abrir_url", url=url), eleccion,
                   Paso("escribir", selectores=["#DateFrom"], objetivo="DateFrom", valor=desde, fecha_directa=True),
                   Paso("escribir", selectores=["#DateTo"], objetivo="DateTo", valor=hasta, fecha_directa=True),
                   Paso("descargar", selectores=["#PDFButton"], nombre=NOMBRE, objetivo="PDF"),
                   Paso("descargar", selectores=["#ExcelButton"], nombre=NOMBRE, objetivo="Excel")]
        return f

    def ejecutar(self, f):
        self.avisos, self.impresas = [], []
        ej = Ejecutor(f, carpeta_perfil=os.path.join(self.tmp, "perfil"), carpeta_registros=os.path.join(self.tmp, "r"),
                      carpeta_descargas=os.path.join(self.tmp, "d"), oculto=True, pausa_entre_pasos=0,
                      lista_descargas=self.avisos.append,
                      imprimir=lambda ruta, impresora, log=None: self.impresas.append(os.path.basename(ruta)) or "Impresora Oficina")
        return ej.ejecutar()

    def test_cada_comercio_con_la_lista_en_vivo_e_imprimiendo_solo_los_pdf(self):
        hoy = datetime.date.today()
        fin = hoy.replace(day=1) - datetime.timedelta(days=1)
        f = self.flujo(Paso("elegir_opcion", selectores=["#LocationIdlabel"], objetivo="Comercio", estrategia="cada_una"),
                       fin.replace(day=1).strftime("%d/%m/%Y"), fin.strftime("%d/%m/%Y"))
        f.opciones["imprimir_pdf"] = {"activo": True, "impresora": ""}
        res = self.ejecutar(f)
        with open(res.ruta_log, encoding="utf-8") as fh:
            log = fh.read()
        self.assertTrue(res.ok, log)
        self.assertTrue(self.avisos[0]["por_leer"])                                        # antes de leer la lista
        self.assertIn("Se van a bajar 5 comercios = 10 archivos", [a["resumen"] for a in self.avisos])
        estados = [tuple(it["estado"] for it in a["items"]) for a in self.avisos if a["items"]]
        self.assertIn(("listo", "descargando", "pendiente", "pendiente", "pendiente"), estados)
        final = self.avisos[-1]
        self.assertTrue(final["terminado"])
        self.assertEqual(final["titulo"], "Pagos — 5 de 5 comercios")
        self.assertEqual([it["estado"] for it in final["items"]], ["listo"] * 5)
        self.assertEqual([[a["tipo"] for a in it["archivos"]] for it in final["items"]], [["PDF", "Excel"]] * 5)
        self.assertEqual([[a["impreso"] for a in it["archivos"]] for it in final["items"]], [[True, None]] * 5)
        self.assertEqual(len(self.impresas), 5)
        self.assertTrue(all(n.endswith(".pdf") for n in self.impresas), self.impresas)       # nunca el Excel
        self.assertEqual(log.count("PDF enviado a imprimir: "), 5)

    def test_comercios_marcados_por_meses(self):
        hoy = datetime.date.today()
        fin = hoy.replace(day=1) - datetime.timedelta(days=1)                               # (la página no deja fechas futuras)
        ini = (fin.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
        f = self.flujo(Paso("elegir_opcion", selectores=["#LocationIdlabel"], objetivo="Comercio", estrategia="marcadas",
                            valores=["TIENDA NORTE 10000000002", "TIENDA PLAYA 10000000004"]), "{desde}", "{hasta}")
        f.opciones["repetir_dias"] = {"modo": "meses", "rango": "fijo", "desde": ini.isoformat(), "hasta": fin.isoformat()}
        res = self.ejecutar(f)
        with open(res.ruta_log, encoding="utf-8") as fh:
            log = fh.read()
        self.assertTrue(res.ok, log)
        self.assertEqual(self.avisos[0]["resumen"], "Se van a bajar 2 comercios × 2 meses = 8 archivos")   # desde el principio
        final = self.avisos[-1]
        self.assertEqual(final["titulo"], "Pagos — 4 de 4 descargas")
        self.assertEqual([(it["periodo"], it["texto"], it["estado"]) for it in final["items"]],
                         [(0, "TIENDA NORTE 10000000002", "listo"), (0, "TIENDA PLAYA 10000000004", "listo"),
                          (1, "TIENDA NORTE 10000000002", "listo"), (1, "TIENDA PLAYA 10000000004", "listo")])
        self.assertEqual(final["archivos"], 8)
        self.assertEqual(self.impresas, [])                                                  # sin la casilla
        pdf = sorted(x for x in self.servidor.estado["descargas"] if x.startswith("Pagos PDF"))[-4:]
        self.assertEqual(len(pdf), 4)


# ======================================================================== 6. interfaz
@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestInterfaz(BaseApp):
    def setUp(self):
        super().setUp()
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)

    def navegador(self, ancho=1280, alto=900):
        from playwright.sync_api import sync_playwright
        if getattr(self, "_nav", None) is None:
            self._p = sync_playwright().start()
            self.addCleanup(self._p.stop)
            self._nav = self._p.chromium.launch(channel="chrome", headless=True)
            self.addCleanup(self._nav.close)
        pg = self._nav.new_page(viewport={"width": ancho, "height": alto})
        self.errores = getattr(self, "errores", [])
        pg.on("console", lambda m: self.errores.append(m.text) if m.type == "error" and "ERR_NO_BUFFER_SPACE" not in m.text
              else None)
        pg.on("pageerror", lambda e: self.errores.append(str(e)))
        return pg

    def abrir_fecha(self, pg, rid):
        """v3.9: el calendario se abre desde «📅 Programar…» (la fila ya no tiene el chip «Fecha: …»)."""
        estado = "#contenido [data-estado-prog='%d']" % rid
        pg.wait_for_selector(estado, timeout=15000)
        pg.click("#contenido [data-programar='%d']" % rid)
        pg.wait_for_selector(".modal [data-cm-calendario]", timeout=15000)
        pg.click(".modal [data-cm-calendario]")
        pg.wait_for_selector(".modal [data-calendario-rango]")
        return estado

    def esperar_texto(self, pg, selector, texto, timeout=10000):
        pg.wait_for_function("([s, t]) => { const e = document.querySelector(s); return !!e && e.textContent.includes(t); }",
                             arg=[selector, texto], timeout=timeout)

    def test_calendario_rojo_azul_y_cada_mes(self):
        rid = self.alm.guardar(reporte(al_reves=True))
        pg = self.navegador()
        pg.goto(self.srv.url_con_token(), wait_until="load")
        chip = self.abrir_fecha(pg, rid)
        m = ".modal "
        self.assertEqual(pg.inner_text(m + "[data-ahora-baja]"), "Ahora baja: el día de hoy (cada día cambia)")
        self.assertEqual(pg.inner_text(m + "[data-resumen-fecha]"), "Bajará el 13/11/2026 (si se ejecuta hoy)")
        self.assertEqual((pg.inner_text(m + "[data-campo-rojo]"), pg.inner_text(m + "[data-campo-azul]")), ("DateFrom", "DateTo"))
        self.assertEqual(pg.locator(m + "[data-sin-cada-mes]").count(), 0)
        # mes y año con sus listas; 01/10 (rojo) y 31/10 (azul)
        pg.select_option(m + "[data-rc-anio]", "2025")
        self.assertEqual(pg.locator(m + "[data-dia='2025-11-01']").count(), 1)
        pg.select_option(m + "[data-rc-anio]", "2026")
        pg.click(m + "[aria-label='Mes anterior']")
        pg.click(m + "[data-dia='2026-10-01']")
        self.esperar_texto(pg, m + "[data-resumen-fecha]", "ahora toca el día «Hasta»")
        pg.click(m + "[data-dia='2026-10-31']")
        self.assertEqual(pg.inner_text(m + "[data-resumen-fecha]"), "Bajará del 01/10/2026 al 31/10/2026")
        clases = pg.evaluate("""() => ['2026-10-01', '2026-10-15', '2026-10-31', '2026-10-02'].map((d) =>
            document.querySelector('.modal [data-dia="' + d + '"]').className)""")
        self.assertEqual(clases, ["rc-dia desde", "rc-dia entre", "rc-dia hasta", "rc-dia entre"])
        colores = pg.evaluate("""() => ['desde', 'hasta'].map((c) => getComputedStyle(document.querySelector('.modal .rc-dia.' + c)).backgroundColor)""")
        self.assertEqual(colores, ["rgb(198, 40, 40)", "rgb(21, 101, 192)"])                 # rojo y azul
        self.assertEqual(pg.locator(m + "[data-ahora-baja]").count(), 0)
        # «cada mes»
        pg.check(m + "[data-cada-mes]")
        self.esperar_texto(pg, m + "[data-explica-cada-mes]", "el mes anterior entero")
        self.esperar_texto(pg, m + "[data-explica-cada-mes]", "el 01/12/2026 bajará del 01/11/2026 al 30/11/2026")
        self.esperar_texto(pg, m + "[data-estado-cada-mes]", "Al guardar: se bajará solo el día 1 de cada mes a las 07:00")
        pg.click(".modal .pie button:has-text('Guardar la fecha')")
        pg.wait_for_function("s => document.querySelector(s).textContent.includes('el mes anterior')", arg=chip, timeout=10000)
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual((valor_de(fl, "DateFrom"), valor_de(fl, "DateTo")),
                         ("{inicio_mes_anterior:%d/%m/%Y}", "{fin_mes_anterior:%Y-%m-%d}"))
        self.assertEqual(self.alm.programacion("reporte:%d" % rid)["programacion"]["reglas"][0]["dias_mes"], [1])
        self.assertEqual([c[1] for c in self.comandos], ["/Create"])
        # al volver a abrirla: lo de ahora en palabras, la casilla marcada y el horario
        self.abrir_fecha(pg, rid)
        self.assertEqual(pg.inner_text(m + "[data-ahora-baja]"), "Ahora baja: el mes anterior (cada mes)")
        self.assertTrue(pg.is_checked(m + "[data-cada-mes]"))
        self.assertEqual(pg.inner_text(m + "[data-estado-cada-mes]"), "Se bajará solo el día 1 de cada mes a las 07:00")
        self.assertEqual(pg.get_attribute(m + "[data-dia='2026-10-01']", "class"), "rc-dia desde")
        # quitar la casilla: se quita el horario; las fechas no cambian
        pg.uncheck(m + "[data-cada-mes]")
        self.esperar_texto(pg, m + "[data-estado-cada-mes]", "ya no se bajará solo cada mes")
        pg.click(".modal .pie button:has-text('Guardar la fecha')")
        pg.wait_for_selector(".modal", state="detached", timeout=10000)
        fin = 0
        while self.alm.programacion("reporte:%d" % rid) is not None and fin < 50:
            pg.wait_for_timeout(100)
            fin += 1
        self.assertIsNone(self.alm.programacion("reporte:%d" % rid))
        self.assertEqual(valor_de(self.alm.cargar_flujo(rid), "DateFrom"), "{inicio_mes_anterior:%d/%m/%Y}")
        # misma interpretación de {dia_mes_anterior} en la interfaz y en Python
        for t in ("{dia_mes_anterior:15}", "{dia_mes_anterior:30:%Y-%m-%d}"):
            self.assertEqual(pg.evaluate("t => window.__botFechas.analizar(t)", t), plantillas.analizar_fecha(t))
            self.assertEqual(pg.evaluate("t => window.__botFechas.componer(window.__botFechas.analizar(t))", t), t)
        self.assertEqual(self.errores, [])

    def test_un_solo_campo_y_abrir_sin_cambiar(self):
        fl = reporte(desde="{ayer:%d/%m/%Y}")
        del fl.pasos[2]
        rid = self.alm.guardar(fl)
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("reportes"), wait_until="load")
        self.abrir_fecha(pg, rid)
        m = ".modal "
        self.assertEqual(pg.inner_text(m + "[data-ahora-baja]"), "Ahora baja: el día anterior (cada día cambia)")
        self.assertNotIn("Hasta", pg.inner_text(m + ".rc-ley"))
        self.assertEqual(pg.locator(m + "[data-mapa-fechas]").count(), 0)
        # abrir y guardar sin tocar nada: no cambia nada
        pg.click(".modal .pie button:has-text('Guardar la fecha')")
        pg.wait_for_selector(".modal", state="detached", timeout=10000)
        self.assertEqual(valor_de(self.alm.cargar_flujo(rid), "DateFrom"), "{ayer:%d/%m/%Y}")
        self.assertEqual(self.alm.versiones(rid), [])
        # un solo campo: solo la fecha roja
        self.abrir_fecha(pg, rid)
        pg.click(m + "[data-dia='2026-11-05']")
        pg.click(m + "[data-dia='2026-11-09']")
        self.assertEqual(pg.locator(m + ".rc-dia.desde").count(), 1)
        self.assertEqual(pg.locator(m + ".rc-dia.hasta").count(), 0)
        self.assertEqual(pg.inner_text(m + "[data-resumen-fecha]"), "Bajará el 09/11/2026")
        pg.click(".modal .pie button:has-text('Guardar la fecha')")
        pg.wait_for_selector(".modal", state="detached", timeout=10000)
        self.assertEqual(valor_de(self.alm.cargar_flujo(rid), "DateFrom"), "09/11/2026")
        self.assertEqual(self.comandos, [])
        self.assertEqual(self.errores, [])

    def test_casilla_imprimir_en_la_fila_y_en_el_editor(self):
        rid = self.alm.guardar(reporte())
        pg = self.navegador()
        pg.goto(self.srv.url_con_token(), wait_until="load")
        estado = "#contenido [data-estado-prog='%d']" % rid
        pg.wait_for_selector(estado, timeout=15000)
        self.assertEqual(pg.inner_text(estado).strip(), "Sin programar")
        pg.click("#contenido [data-programar='%d']" % rid)          # v3.9: todo se cambia desde «Programar…»
        pg.wait_for_selector(".modal [data-casilla-imprimir]")
        self.assertTrue(pg.is_disabled(".modal [data-impresora-pdf]"))
        pg.check(".modal [data-imprimir-pdf]")
        pg.wait_for_selector(".modal [data-impresora-pdf] option[value='Impresora Bodega']", state="attached")
        pg.select_option(".modal [data-impresora-pdf]", "Impresora Bodega")
        pg.select_option(".modal [data-cm-modo]", "no")             # solo imprimir: sin horario
        pg.click(".modal .pie button:has-text('Agregar a programar')")
        pg.wait_for_selector(".modal [data-casilla-imprimir]", state="detached", timeout=15000)
        fin = time.monotonic() + 10
        while time.monotonic() < fin and "imprimir_pdf" not in self.alm.cargar_flujo(rid).opciones:
            pg.wait_for_timeout(200)
        self.assertEqual(self.alm.cargar_flujo(rid).opciones["imprimir_pdf"], {"activo": True, "impresora": "Impresora Bodega"})
        # en el editor, a la vista (no dentro de un desplegable)
        pg.evaluate("id => { location.hash = '#/editor/' + id; }", rid)
        caja = "#contenido [data-casilla-imprimir]"
        pg.wait_for_selector(caja, timeout=15000)
        self.assertTrue(pg.is_visible(caja))
        self.assertTrue(pg.is_checked(caja + " [data-imprimir-pdf]"))
        self.assertEqual(pg.input_value(caja + " [data-impresora-pdf]"), "Impresora Bodega")
        pg.uncheck(caja + " [data-imprimir-pdf]")
        pg.click("#contenido .barra-herr button.primario:has-text('Guardar')")
        pg.wait_for_function("() => document.querySelector('#subtitulo').textContent.includes('guardado')", timeout=10000)
        self.assertFalse(self.alm.cargar_flujo(rid).opciones["imprimir_pdf"]["activo"])
        self.assertEqual(self.errores, [])

    def test_lista_de_descargas_en_vivo(self):
        rid = self.alm.guardar(reporte())
        pg = self.navegador(360, 800)
        pg.goto(self.srv.url_con_token(), wait_until="load")
        pg.wait_for_selector("#contenido [data-pagina='inicio']", timeout=15000)
        self.assertEqual(pg.locator("#descargas.oculto").count(), 1)
        t = su.Trabajo("ejecutar", "Ejecutar «Pagos»")
        self.app.trabajo = t
        self.app.eventos.emitir("trabajo", trabajo=t.id, estado="en_curso", tipo_trabajo="ejecutar", descripcion=t.descripcion)
        nombres = ["TIENDA %d" % n for n in range(1, 18)]
        nombres[1] = "TIENDA CON UN NOMBRE MUY LARGO QUE NO CABE " + "X" * 60
        lista = ListaDescargas("Pagos", self.app._avisar_descargas(t, rid), periodos=["octubre 2026"], modo_periodo="meses",
                               lista="Comercio", por_pase=2)
        caja = "#descargas"
        self.esperar_texto(pg, caja, "se sabrá cuántas al leer la lista")
        lista.opciones_leidas(0, nombres)
        self.esperar_texto(pg, caja + " [data-descargas-resumen]", "Se van a bajar 17 comercios × 1 mes = 34 archivos")
        for k in range(3):
            lista.empezar(0, nombres[k])
            lista.archivo("C:/x/a%d.pdf" % k)
            lista.archivo("C:/x/a%d.xlsx" % k)
            lista.terminar(k != 2, "No llegó ninguna descarga")
        lista.empezar(0, nombres[3])
        self.esperar_texto(pg, caja + " [data-descargas-titulo]", "Pagos — 4 de 17 comercios")
        estados = pg.evaluate("() => [...document.querySelectorAll('#descargas li')].slice(0, 5).map((li) => li.dataset.estado + ' ' + li.querySelector('.desc-ico').textContent)")
        self.assertEqual(estados, ["listo ✔", "listo ✔", "fallo ✖", "descargando ⟳", "pendiente ·"])
        self.assertIn("PDF ✔ Excel ✔", pg.inner_text("#descargas li:nth-child(1)"))
        self.assertIn("falló: No llegó ninguna descarga", pg.inner_text("#descargas li:nth-child(3)"))
        self.assertEqual(pg.locator("#descargas [data-cerrar-descargas]").count(), 0)
        for ancho in (360, 1280):
            pg.set_viewport_size({"width": ancho, "height": 800})
            pg.wait_for_timeout(150)
            self.assertTrue(pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth"), ancho)
            ancho_li = pg.evaluate("() => { const l = document.querySelector('#descargas ol'); return l.scrollWidth <= l.clientWidth; }")
            self.assertTrue(ancho_li, ancho)                                                  # los nombres largos bajan de línea
        # al terminar se queda como resumen (también al recargar) hasta que se cierra
        lista.cerrar(error="Detenido")
        self.esperar_texto(pg, caja, "Terminado: ")
        pg.reload(wait_until="load")
        self.esperar_texto(pg, caja + " [data-descargas-titulo]", "Pagos — 4 de 17 comercios")
        pg.click("#descargas [data-cerrar-descargas]")
        pg.wait_for_selector("#descargas.oculto", state="attached")
        self.assertEqual(self.errores, [])


if __name__ == "__main__":
    unittest.main()
