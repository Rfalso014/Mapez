"""Pruebas de la versión 3.9: lo que el usuario encontró al probar (17/11/2026).

1. «Imprimir los PDF que descargue» daba un error que no se entendía:
   - el mensaje traía el XML del progreso de PowerShell («#< CLIXML <Objs Version=…»): ahora se limpia y se dice en
     español qué pasó y qué hacer;
   - con una impresora que no saca papel («Microsoft Print to PDF», XPS, OneNote…) Windows abría una ventana
     preguntando dónde guardar, que nadie veía, y el bot se quedaba esperando: ahora se le dice el archivo
     («… (impreso).pdf», al lado del descargado) y, con los tipos que no son PDF, se avisa en vez de colgarse.
2. El botón de imprimir (o de guardar) del visor de PDF del navegador no es de la página: un paso grabado así no se
   puede ejecutar.  Ahora se salta (si el reporte ya imprime los PDF) o falla diciendo qué hacer.
3. «Descargar todas»: bajar un archivo por cada opción de la lista del reporte sin tocar los pasos guardados.

Nunca se imprime de verdad: todo lo que toca Windows (`_lanzar`, `_imprimir_pdf_windows`, `_enumerar`,
`_predeterminada`) se sustituye.  Tampoco se usan la base de datos real, el llavero, la red ni tareas de Windows.
"""

import datetime
import json
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

from servidor_prueba import ServidorPrueba  # noqa: E402
from test_servidor_ui import BaseApi  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot import impresion  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from test_integracion import BaseIntegracion  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

def _nunca(*a, **k):
    raise AssertionError("las pruebas NUNCA tocan impresoras de verdad")


IMPRESORAS = ["Impresora Oficina", "Microsoft Print to PDF", "Microsoft XPS Document Writer"]
CLIXML = ('#< CLIXML <Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04"><Obj S="progress" '
          'RefId="0"><MS><PR N="Record"><AV>Preparing modules for first use.</AV></PR></MS></Obj></Objs>')


class BaseImpresion(unittest.TestCase):
    """Sustituye todo lo que toca Windows; `self.llamadas` recoge lo que se habría impreso."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v39imp_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.llamadas = []
        self.paginas = 3
        self.error_pdf = None
        self.programas = {}            # (ext, verbo) -> comando («» = Windows no sabe imprimirlo)

        def pdf_windows(ruta, impresora, salida=None, tiempo=300):
            self.llamadas.append({"ruta": ruta, "impresora": impresora, "salida": salida})
            if self.error_pdf is not None:
                raise self.error_pdf
            if salida:                 # como la impresora de verdad: deja el archivo
                with open(salida, "wb") as f:
                    f.write(b"%PDF-1.4 impreso\n")
            return self.paginas

        for nombre, valor in (("_enumerar", lambda: list(IMPRESORAS)),
                              ("_predeterminada", lambda: IMPRESORAS[0]),
                              ("_imprimir_pdf_windows", pdf_windows),
                              ("_programa_que_imprime", lambda ext, verbo="print": self.programas.get((ext, verbo), "")),
                              ("_lanzar", lambda ruta, verbo, parametros=None: 42)):
            p = mock.patch.object(impresion, nombre, valor)
            p.start()
            self.addCleanup(p.stop)

    def archivo(self, nombre="Pagos.pdf", datos=b"%PDF-1.4\n"):
        ruta = os.path.join(self.tmp, nombre)
        with open(ruta, "wb") as f:
            f.write(datos)
        return ruta


class TestImpresoraQueGuardaArchivo(BaseImpresion):
    def test_a_una_impresora_que_pregunta_donde_guardar_se_le_dice_el_archivo(self):
        pdf = self.archivo()
        lineas = []
        usada = impresion.imprimir_archivo(pdf, "Microsoft Print to PDF", log=lineas.append)
        self.assertEqual(usada, "Microsoft Print to PDF")
        salida = os.path.join(self.tmp, "Pagos (impreso).pdf")
        self.assertEqual(self.llamadas, [{"ruta": pdf, "impresora": "Microsoft Print to PDF", "salida": salida}])
        self.assertTrue(os.path.isfile(salida))
        self.assertEqual(lineas, ["«Pagos.pdf» se imprimió en «Microsoft Print to PDF»: 3 páginas en %s" % salida])
        self.assertTrue(os.path.isfile(pdf))                      # el descargado sigue ahí

    def test_no_pisa_el_archivo_anterior(self):
        pdf = self.archivo()
        impresion.imprimir_archivo(pdf, "Microsoft Print to PDF")
        impresion.imprimir_archivo(pdf, "Microsoft Print to PDF")
        self.assertEqual([os.path.basename(x["salida"]) for x in self.llamadas],
                         ["Pagos (impreso).pdf", "Pagos (impreso 2).pdf"])

    def test_xps_guarda_un_xps(self):
        impresion.imprimir_archivo(self.archivo(), "Microsoft XPS Document Writer")
        self.assertTrue(self.llamadas[0]["salida"].endswith("Pagos (impreso).xps"))

    def test_con_un_excel_avisa_en_vez_de_colgarse(self):
        self.programas[(".csv", "printto")] = "EXCEL.EXE /q %1"
        self.programas[(".csv", "print")] = "EXCEL.EXE /q %1"
        with self.assertRaises(impresion.ErrorImpresion) as e:
            impresion.imprimir_archivo(self.archivo("Pagos.csv", b"a;b\n"), "Microsoft Print to PDF")
        self.assertIn("no saca papel", str(e.exception))
        self.assertIn("elige una impresora de papel", str(e.exception))
        self.assertEqual(self.llamadas, [])

    def test_impresora_normal_con_pdf_sin_lector(self):
        lineas = []
        impresion.imprimir_archivo(self.archivo(), "Impresora Oficina", log=lineas.append)
        self.assertEqual(self.llamadas[0]["salida"], None)         # a papel: sin archivo de salida
        self.assertIn("enviado a la impresora «Impresora Oficina»", lineas[0])

    def test_que_impresoras_guardan_archivo(self):
        for n in ("Microsoft Print to PDF", "Imprimir en PDF (Microsoft)", "Microsoft XPS Document Writer",
                  "OneNote (Desktop)", "PDF24", "Fax"):
            self.assertTrue(impresion.imprime_a_un_archivo(n), n)
        for n in ("Impresora Oficina", "Impresora Almacén", "HP LaserJet 400", "", None):
            self.assertFalse(impresion.imprime_a_un_archivo(n), n)


class TestMensajesDeImpresion(BaseImpresion):
    def test_el_xml_de_powershell_no_llega_al_usuario(self):
        self.assertEqual(impresion._limpiar_powershell(CLIXML + " algo más"), "Preparing modules for first use. algo más")
        motivo = impresion._motivo_impresion(CLIXML, "Impresora Oficina")
        self.assertNotIn("CLIXML", motivo)
        self.assertNotIn("<", motivo)
        self.assertTrue(motivo.startswith("Windows no pudo imprimir en «Impresora Oficina»"), motivo)

    def test_mensajes_en_espanol_segun_el_fallo(self):
        self.assertIn("puede que esté apagada, desconectada",
                      impresion._motivo_impresion("No existe la impresora Impresora Oficina", "Impresora Oficina"))
        self.assertIn("que no tiene trabajos atascados",
                      impresion._motivo_impresion("The handle is invalid", "Impresora Oficina"))
        self.assertIn("protegido con contraseña",
                      impresion._motivo_impresion("Windows.Data.Pdf: password required", "Impresora Oficina"))

    def test_impresora_que_no_existe(self):
        with self.assertRaises(impresion.ErrorImpresion) as e:
            impresion.imprimir_archivo(self.archivo(), "No Existe Esta")
        self.assertIn("No existe la impresora «No Existe Esta»", str(e.exception))
        self.assertIn("Impresora Oficina", str(e.exception))

    def test_si_falla_la_impresion_el_pdf_sigue_descargado(self):
        self.error_pdf = impresion.ErrorImpresion("Windows no pudo imprimir en «Impresora Oficina»")
        pdf = self.archivo()
        with self.assertRaises(impresion.ErrorImpresion):
            impresion.imprimir_archivo(pdf, "Impresora Oficina")
        self.assertTrue(os.path.isfile(pdf))


class TestPowerShellDelPdf(unittest.TestCase):
    """El guion de PowerShell: sin barras de progreso y con el error en una línea «ERROR=…»."""

    def test_el_guion_calla_el_progreso_y_devuelve_el_error(self):
        guion = impresion.PS_IMPRIMIR_PDF
        self.assertIn("$ProgressPreference = 'SilentlyContinue'", guion)
        self.assertIn("try {", guion)
        self.assertIn("Write-Output ('ERROR=' + $_.Exception.Message)", guion)
        self.assertIn("Write-Output ('PAGINAS=' + $pdf.PageCount)", guion)


# ============================================================================ «Descargar todas»
class TestListasParaTodas(unittest.TestCase):
    def test_las_listas_del_reporte(self):
        f = Flujo(nombre="Pagos", url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"),
            Paso("elegir_opcion", selectores=["#l"], objetivo="Localidad", filtro="Localidad", estrategia="fija",
                 valor="TIENDA UNO"),
            Paso("elegir_opcion", selectores=["#f"], objetivo="Formato", estrategia="cada_una"),
            Paso("elegir_opcion", selectores=["#x"], objetivo="Otra", estrategia="fija", valor="x", desactivado=True),
            Paso("descargar", selectores=["#bajar"], objetivo="Excel")])
        self.assertEqual(mod_flujo.listas_para_todas(f),
                         [{"paso": 1, "nombre": "Localidad", "estrategia": "fija", "ya": False},
                          {"paso": 2, "nombre": "Formato", "estrategia": "cada_una", "ya": True}])
        self.assertEqual(mod_flujo.listas_para_todas(Flujo(nombre="x", url="u", pasos=[Paso("descargar", selectores=["#b"])])), [])


class TestDescargarTodas(BaseApi):
    """La API «Descargar todas» con el sitio de prueba: un archivo por comercio, sin tocar el reporte guardado."""

    @classmethod
    def setUpClass(cls):
        cls.web = ServidorPrueba().iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    COMERCIOS = ["TIENDA CENTRO 10000000001", "TIENDA NORTE 10000000002", "TIENDA SUR II 10000000003",
                 "TIENDA PLAYA 10000000004", "TIENDA AEROPUERTO 10000000005"]

    def reporte(self, con_lista=True):
        url = self.web.url_base + "pagos_consulta.html"
        pasos = [Paso("abrir_url", url=url)]
        if con_lista:
            pasos.append(Paso("elegir_opcion", selectores=["#LocationIdlabel"], objetivo="Comercio", filtro="Comercio",
                              estrategia="fija", valor=self.COMERCIOS[0]))
        pasos.append(Paso("descargar", selectores=["#ExcelButton"], objetivo="Excel", nombre="{reporte}{ext}"))
        f = Flujo(nombre="Pagos" if con_lista else "Pagos sin lista", url=url, pasos=pasos)
        f.opciones.update(timeout_paso=15, timeout_descarga=30, pausa_entre_pasos=0)
        return self.alm.guardar(f)

    def test_la_fila_del_reporte_dice_que_se_puede_descargar_todo(self):
        rid = self.reporte()
        fila = next(r for r in self.api("GET", "reportes")["reportes"] if r["id"] == rid)
        self.assertEqual(fila["todas"], [{"paso": 1, "nombre": "Comercio", "estrategia": "fija", "ya": False,
                                          "opciones": 0}])
        # con las opciones ya leídas (las guarda cada ejecución), la interfaz puede decir cuántas son
        self.alm.guardar_opciones_filtro(rid, 1, ["Seleccione…"] + self.COMERCIOS, {}, "", "prueba")
        self.assertEqual(self.api("GET", "reportes/%d/todas" % rid)["listas"][0]["opciones"], 5)
        sin = self.reporte(con_lista=False)
        fila = next(r for r in self.api("GET", "reportes")["reportes"] if r["id"] == sin)
        self.assertEqual(fila["todas"], [])

    def test_un_reporte_sin_lista_lo_dice_claro(self):
        rid = self.reporte(con_lista=False)
        codigo, r = self.llamar("POST", "api/reportes/%d/todas" % rid, {})
        self.assertEqual(codigo, 400)
        self.assertIn("no tiene ninguna lista de opciones que recorrer", r["error"])
        self.assertIn("Mapear página", r["error"])

    def test_baja_un_archivo_por_comercio_y_no_cambia_el_reporte(self):
        rid = self.reporte()
        t = self.api("POST", "reportes/%d/todas" % rid, {"paso": 1})
        self.assertIn("Descargar todas las opciones de «Comercio»", t["descripcion"])
        fin, eventos = self.esperar_trabajo(t["id"], timeout=240)
        self.assertEqual(fin["estado"], "ok", fin)
        archivos = [os.path.basename(a) for e in eventos if e["tipo"] == "resultado" for a in e["archivos"]]
        self.assertEqual(archivos, ["Pagos - %s.xls" % c for c in self.COMERCIOS], archivos)
        # el reporte guardado sigue como estaba (una sola opción fija)
        p = self.alm.cargar_flujo(rid).pasos[1]
        self.assertEqual((p.estrategia, p.valor), ("fija", self.COMERCIOS[0]))
        self.assertEqual([x.split(" ")[2] for x in self.web.estado["descargas"] if x.startswith("Pagos Excel")],
                         ["501", "502", "503", "504", "505"])


# ============================================================================ «Cada mes: bajar todo e imprimir»
class TestCadaMes(BaseApi):
    """Una sola ventana lo deja todo puesto: todas las opciones, las fechas del mes anterior, imprimir y el horario.
    Las tareas de Windows son falsas (`ejecutar_tareas` de la prueba) y nunca se imprime de verdad."""

    COMERCIOS = ["TIENDA CENTRO 10000000001", "TIENDA NORTE 10000000002", "TIENDA SUR II 10000000003"]

    def setUp(self):
        super().setUp()
        for nombre, valor in (("_enumerar", lambda: ["Impresora Oficina", "Microsoft Print to PDF"]),
                              ("_predeterminada", lambda: "Microsoft Print to PDF"),
                              ("_imprimir_pdf_windows", _nunca), ("_lanzar", _nunca)):
            x = mock.patch.object(impresion, nombre, valor)
            x.start()
            self.addCleanup(x.stop)
        self.tareas = []
        self.app.listar_tareas = lambda: list(self.tareas)
        self.app.ejecutar_tareas = self.falsas_tareas

    def falsas_tareas(self, cmd):
        if "/Create" in cmd:                      # como schtasks /F: si ya existe una con ese nombre, la sustituye
            n = cmd[cmd.index("/TN") + 1].split("\\")[-1]
            self.tareas[:] = [t for t in self.tareas if t["nombre"] != n]
            self.tareas.append({"nombre": n, "comando": " ".join(cmd)})
        if "/Delete" in cmd:
            n = cmd[cmd.index("/TN") + 1].split("\\")[-1]
            self.tareas[:] = [t for t in self.tareas if t["nombre"] != n]
        return 0, "OK"

    def reporte(self, con_lista=True, desde="01/10/2026", hasta="31/10/2026"):
        pasos = [Paso("abrir_url", url="http://127.0.0.1/")]
        if con_lista:
            pasos.append(Paso("elegir_opcion", selectores=["#l"], objetivo="Localidad", filtro="Localidad",
                              estrategia="fija", valor=self.COMERCIOS[0]))
        pasos += [Paso("escribir", selectores=["#DateFrom"], objetivo="Fecha Desde", valor=desde, fecha_directa=True),
                  Paso("escribir", selectores=["#DateTo"], objetivo="Fecha Hasta", valor=hasta, fecha_directa=True),
                  Paso("descargar", selectores=["#pdf"], objetivo="PDF", nombre="{reporte}{ext}"),
                  Paso("descargar", selectores=["#excel"], objetivo="Excel", nombre="{reporte}{ext}")]
        rid = self.alm.guardar(Flujo(nombre="Pagos" if con_lista else "Pagos sin lista", url="http://127.0.0.1/",
                                     pasos=pasos))
        if con_lista:
            self.alm.guardar_opciones_filtro(rid, 1, self.COMERCIOS, {}, "", "prueba")
        return rid

    def test_la_ventana_dice_como_esta_todo(self):
        rid = self.reporte()
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertEqual({k: v["lista"][k] for k in ("nombre", "opciones", "activo")},
                         {"nombre": "Localidad", "opciones": 3, "activo": False})
        self.assertEqual(v["lista"]["textos"], self.COMERCIOS)
        self.assertEqual(v["fechas"]["campos"], 2)
        self.assertEqual(v["fechas"]["mes_completo"], "Bajará el mes anterior entero (del día 1 al último día)")
        self.assertIsNone(v["fechas"]["parcial"])
        self.assertFalse(v["fechas"]["ya"])
        self.assertEqual(v["archivos_por_opcion"], 2)
        self.assertEqual(v["imprimir"]["sugerida"], "Impresora Oficina")      # papel antes que «guardar en archivo»
        self.assertFalse(v["imprimir"]["a_archivo"])
        self.assertEqual(v["cuando"], {"activo": False, "modo": "no", "dia": 1, "hora": "07:00",
                                       "dia_semana": "lun", "texto": "Sin programar", "otro_horario": ""})

    def test_dejarlo_programado_lo_pone_todo_de_una_vez(self):
        rid = self.reporte()
        r = self.api("POST", "reportes/%d/cada_mes" % rid,
                     {"todas": True, "fechas": "mes_completo", "dia": 1, "hora": "07:00",
                      "imprimir": {"activo": True, "impresora": "Impresora Oficina"}})
        self.assertEqual(r["cambios"], ["«Localidad»: todas las opciones, una tras otra",
                                        "paso 3 («Fecha Desde»): inicio del mes anterior · 01/10/2026",
                                        "paso 4 («Fecha Hasta»): fin del mes anterior · 31/10/2026",
                                        "imprimir los PDF en «Impresora Oficina»",
                                        "Cada mes, día 1 a las 07:00"])
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual(fl.pasos[1].estrategia, "cada_una")
        self.assertEqual([fl.pasos[2].valor, fl.pasos[3].valor],
                         ["{inicio_mes_anterior:%d/%m/%Y}", "{fin_mes_anterior:%d/%m/%Y}"])
        self.assertEqual(fl.opciones["imprimir_pdf"], {"activo": True, "impresora": "Impresora Oficina"})
        self.assertEqual([t["nombre"] for t in self.tareas], ["Pagos"])       # la tarea de Windows (falsa en la prueba)
        self.assertEqual(self.alm.programacion("reporte:%d" % rid)["tarea"], r"BotWeb\Pagos")
        # se guardó una copia para poder deshacerlo
        self.assertEqual([x["motivo"] for x in self.alm.versiones(rid)],
                         ["antes de programar «cada mes: bajar todo e imprimir»"])
        # y al volver a abrir la ventana se ve lo que hay puesto
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertEqual(v["cuando"], {"activo": True, "modo": "mes", "dia": 1, "hora": "07:00",
                                       "dia_semana": "lun", "texto": "Cada mes, día 1 a las 07:00", "otro_horario": ""})
        self.assertTrue(v["lista"]["activo"])
        self.assertTrue(v["fechas"]["ya"])
        self.assertTrue(v["imprimir"]["activo"])
        fila = next(x for x in self.api("GET", "reportes")["reportes"] if x["id"] == rid)
        self.assertEqual(fila["cada_mes"]["texto"],
                         "Cada mes, día 1 a las 07:00 · todas las opciones de «Localidad» (3) · del mes anterior · imprime")
        self.assertTrue(fila["cada_mes"]["activo"])
        # y sale en «Vigilancia» («que aparezca ya programado en vigilancia»)
        prog = self.api("GET", "programados")["reportes"]
        self.assertEqual([(x["id"], x["texto"]) for x in prog], [(rid, fila["cada_mes"]["texto"])])

    def test_otro_dia_y_hora(self):
        rid = self.reporte()
        self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "cuando": {"modo": "mes", "dia": 5, "hora": "21:30"},
                                                        "imprimir": {"activo": False}})
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertEqual((v["cuando"]["modo"], v["cuando"]["dia"], v["cuando"]["hora"]), ("mes", 5, "21:30"))
        self.assertEqual(v["cuando"]["texto"], "Cada mes, día 5 a las 21:30")
        self.assertFalse(v["imprimir"]["activo"])

    def test_los_mismos_dias_del_mes_anterior(self):
        rid = self.reporte(desde="15/10/2026", hasta="31/10/2026")
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertEqual({k: v["fechas"]["parcial"][k] for k in ("desde", "hasta")}, {"desde": 15, "hasta": 31})
        self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "fechas": "mismos_dias",
                                                        "imprimir": {"activo": False}})
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual([fl.pasos[2].valor, fl.pasos[3].valor],
                         ["{dia_mes_anterior:15:%d/%m/%Y}", "{fin_mes_anterior:%d/%m/%Y}"])

    def test_no_tocar_las_fechas(self):
        rid = self.reporte()
        self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "fechas": "no_tocar",
                                                        "imprimir": {"activo": False}})
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual([fl.pasos[2].valor, fl.pasos[3].valor], ["01/10/2026", "31/10/2026"])

    def test_un_reporte_sin_lista_se_puede_programar_igual(self):
        rid = self.reporte(con_lista=False)
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertIsNone(v["lista"])
        r = self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": True, "impresora": ""}})
        self.assertIn("Cada mes, día 1 a las 07:00", r["cambios"])
        self.assertEqual([t["nombre"] for t in self.tareas], ["Pagos sin lista"])

    def test_avisa_antes_de_pisar_otro_horario(self):
        rid = self.reporte()
        self.api("POST", "reportes/%d/programar" % rid,
                 {"programacion": {"reglas": [{"tipo": "semanal", "dias": ["lun", "mar"], "horas": ["08:00"]}]},
                  "confirmar": True})
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertIn("lunes", v["cuando"]["otro_horario"].lower())
        codigo, r = self.llamar("POST", "api/reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": False}})
        self.assertEqual(codigo, 400)
        self.assertIn("ya tiene otro horario", r["error"])
        self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": False}, "confirmar": True})
        self.assertEqual(self.api("GET", "reportes/%d/cada_mes" % rid)["cuando"]["activo"], True)

    def test_cada_dia_y_cada_semana(self):
        rid = self.reporte()
        self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": False},
                                                        "cuando": {"modo": "dia", "hora": "06:15"}})
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertEqual((v["cuando"]["modo"], v["cuando"]["hora"], v["cuando"]["otro_horario"]), ("dia", "06:15", ""))
        self.assertEqual(v["cuando"]["texto"], "Cada día a las 06:15")
        self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": False},
                                                        "cuando": {"modo": "semana", "dia_semana": "vie", "hora": "18:00"}})
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertEqual((v["cuando"]["modo"], v["cuando"]["dia_semana"]), ("semana", "vie"))
        self.assertEqual(v["cuando"]["texto"], "Cada semana, los viernes a las 18:00")
        self.assertEqual([t["nombre"] for t in self.tareas], ["Pagos"])      # una sola tarea, sustituida

    def test_sin_programar_deja_los_pasos_pero_quita_la_tarea(self):
        rid = self.reporte()
        self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": False},
                                                        "cuando": {"modo": "mes", "dia": 1}})
        self.assertEqual(len(self.tareas), 1)
        r = self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": True, "impresora": "Impresora Oficina"},
                                                            "cuando": {"modo": "no"}})
        self.assertIn("ya no se ejecuta solo", r["cambios"])
        self.assertEqual(self.tareas, [])
        self.assertTrue(self.alm.cargar_flujo(rid).opciones["imprimir_pdf"]["activo"])   # lo demás sí se guarda
        self.assertEqual(self.alm.cargar_flujo(rid).pasos[1].estrategia, "cada_una")
        self.assertEqual(self.api("GET", "programados")["reportes"], [])

    def test_la_fila_dice_sin_programar_cuando_no_lo_esta(self):
        rid = self.reporte()
        fila = next(x for x in self.api("GET", "reportes")["reportes"] if x["id"] == rid)
        self.assertEqual(fila["cada_mes"]["texto"], "Sin programar")
        self.assertFalse(fila["cada_mes"]["activo"])

    def test_un_horario_raro_se_ve_tal_cual_y_no_se_pisa_sin_avisar(self):
        rid = self.reporte()
        self.api("POST", "reportes/%d/programar" % rid,
                 {"programacion": {"reglas": [{"tipo": "intervalo", "dias": ["lun", "mar"], "cada_horas": 2,
                                               "desde": "08:00", "hasta": "18:00"}]}, "confirmar": True})
        fila = next(x for x in self.api("GET", "reportes")["reportes"] if x["id"] == rid)
        self.assertIn("cada 2 h", fila["cada_mes"]["texto"])
        self.assertTrue(fila["cada_mes"]["activo"])
        prog = self.api("GET", "programados")["reportes"]
        self.assertEqual(len(prog), 1)
        codigo, r = self.llamar("POST", "api/reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": False}})
        self.assertEqual(codigo, 400)
        self.assertIn("ya tiene otro horario", r["error"])

    def test_quitarlo_es_igual_de_facil(self):
        rid = self.reporte()
        self.api("POST", "reportes/%d/cada_mes" % rid, {"todas": True, "imprimir": {"activo": True, "impresora": "Impresora Oficina"}})
        r = self.api("POST", "reportes/%d/cada_mes" % rid, {"quitar": True})
        self.assertEqual(r["cambios"], ["ya no se ejecuta solo", "ya no imprime los PDF"])
        self.assertEqual(self.tareas, [])
        self.assertFalse(self.alm.cargar_flujo(rid).opciones["imprimir_pdf"]["activo"])
        # los pasos se quedan como estaban (sigue en «todas» y con las fechas del mes anterior)
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual(fl.pasos[1].estrategia, "cada_una")
        self.assertEqual(fl.pasos[2].valor, "{inicio_mes_anterior:%d/%m/%Y}")
        self.assertFalse(self.api("GET", "reportes/%d/cada_mes" % rid)["cuando"]["activo"])

    def test_ejecutar_ahora_baja_todas_sin_tocar_lo_guardado(self):
        rid = self.reporte()
        antes = self.alm.cargar_flujo(rid).a_json()
        lanzados = []
        self.app._lanzar_uno = lambda fl, r, ver, lento, variables, descripcion=None: lanzados.append((fl, descripcion)) or su.Trabajo("ejecutar", descripcion or "")
        r = self.api("POST", "reportes/%d/cada_mes" % rid, {"probar": True, "todas": True, "fechas": "mes_completo",
                                                            "imprimir": {"activo": True, "impresora": "Impresora Oficina"}})
        self.assertTrue(r["todas"])
        fl, desc = lanzados[0]
        self.assertEqual(desc, "Descargar todas las opciones de «Localidad» de «Pagos» (3)")
        self.assertEqual(fl.pasos[1].estrategia, "cada_una")
        self.assertEqual(fl.pasos[2].valor, "{inicio_mes_anterior:%d/%m/%Y}")
        self.assertEqual(fl.opciones["imprimir_pdf"], {"activo": True, "impresora": "Impresora Oficina"})
        self.assertEqual(self.alm.cargar_flujo(rid).a_json(), antes)          # lo guardado, intacto
        self.assertEqual(self.tareas, [])

    def test_probar_ahora_con_una_opcion_no_cambia_nada(self):
        rid = self.reporte()
        antes = self.alm.cargar_flujo(rid).a_json()
        lanzados = []
        self.app._lanzar_uno = lambda fl, r, ver, lento, variables, descripcion=None: lanzados.append((fl, descripcion)) or su.Trabajo("ejecutar", descripcion or "")
        r = self.api("POST", "reportes/%d/cada_mes" % rid, {"probar": True, "fechas": "mes_completo",
                                                            "imprimir": {"activo": True, "impresora": "Impresora Oficina"}})
        self.assertTrue(r["probando"])
        fl, desc = lanzados[0]
        self.assertEqual(desc, "Probar «Pagos» con una opción")
        self.assertEqual((fl.pasos[1].estrategia, fl.pasos[1].valor), ("fija", self.COMERCIOS[0]))
        self.assertEqual(fl.pasos[2].valor, "{inicio_mes_anterior:%d/%m/%Y}")
        self.assertEqual(fl.opciones["imprimir_pdf"], {"activo": True, "impresora": "Impresora Oficina"})
        self.assertEqual(self.alm.cargar_flujo(rid).a_json(), antes)          # lo guardado, intacto
        self.assertEqual(self.tareas, [])


class TestLoQueHaceLaTareaProgramada(unittest.TestCase):
    """El camino de la tarea de Windows (bot.py --id N --sin-ventana --oculto) es una ejecución normal: recorre todas
    las opciones e imprime los PDF (la casilla es del reporte, no de la ventana)."""

    def test_el_comando_de_la_tarea_es_una_ejecucion_normal(self):
        from webbot import programador
        cmd = programador.comando_bot(os.path.join(RAIZ, "bot.py"), ids=[7], oculto=True)
        self.assertIn("--id 7", cmd)
        self.assertIn("--sin-ventana", cmd)
        self.assertIn("--oculto", cmd)
        for prohibido in ("--hasta", "--visible", "--filtro"):
            self.assertNotIn(prohibido, cmd)

    def test_una_ejecucion_oculta_sin_interfaz_imprime_los_pdf(self):
        """Sin `imprimir=` (como en la tarea programada) se usa el módulo de impresión de Windows."""
        from webbot.ejecutor import Ejecutor
        tmp = tempfile.mkdtemp(prefix="botweb_v39tarea_")
        self.addCleanup(shutil.rmtree, tmp, True)
        fl = Flujo(nombre="Pagos", url="http://127.0.0.1/", pasos=[Paso("abrir_url", url="http://127.0.0.1/")])
        fl.opciones["imprimir_pdf"] = {"activo": True, "impresora": "Impresora Oficina"}
        ruta = os.path.join(tmp, "Pagos.pdf")
        with open(ruta, "wb") as f:
            f.write(b"%PDF-1.4\n")
        ej = Ejecutor(fl, carpeta_perfil=os.path.join(tmp, "p"), carpeta_registros=tmp, carpeta_descargas=tmp,
                      oculto=True)
        with mock.patch.object(impresion, "imprimir_archivo", return_value="Impresora Oficina") as falso:
            ej._archivo_nuevo(ruta)
        falso.assert_called_once()
        self.assertEqual(falso.call_args[0][:2], (ruta, "Impresora Oficina"))
        self.assertEqual([i["archivo"] for i in ej.resultado.impresiones], [ruta])


# ============================================================================ v3.9: una carpeta por mes
class TestNombreDeLaCarpeta(unittest.TestCase):
    """El nombre lleva primero el año y el mes (para que se ordenen solas) y luego el mes en palabras."""

    def test_cada_modo(self):
        d = datetime.date
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 11, 1), d(2026, 11, 30)), "2026-11 noviembre")
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 2, 1), d(2026, 2, 28)), "2026-02 febrero")
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 11, 1), d(2026, 11, 15)), "2026-11 noviembre 1a quincena")
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 11, 16), d(2026, 11, 30)), "2026-11 noviembre 2a quincena")
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 11, 17), d(2026, 11, 17)), "2026-11-17")
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 11, 17)), "2026-11-17")
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 11, 5), d(2026, 11, 20)), "2026-11 noviembre 05-20")
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 10, 1), d(2026, 11, 15)), "2026-10-01 a 2026-11-15")
        self.assertEqual(mod_flujo.carpeta_de_periodo(d(2026, 11, 30), d(2026, 11, 1)), "2026-11 noviembre")  # al revés

    def test_sin_tildes_ni_caracteres_raros(self):
        prohibidos = set('<>:"/\\|?*')
        for mes in range(1, 13):
            for desde, hasta in ((datetime.date(2026, mes, 1), datetime.date(2026, mes, 28)),
                                 (datetime.date(2026, mes, 1), datetime.date(2026, mes, 14))):
                nombre = mod_flujo.carpeta_de_periodo(desde, hasta)
                self.assertFalse(prohibidos & set(nombre), nombre)
                self.assertEqual(nombre, nombre.encode("ascii", "ignore").decode("ascii"), nombre)

    def test_la_opcion(self):
        self.assertFalse(mod_flujo.carpeta_por_periodo({}))
        self.assertFalse(mod_flujo.carpeta_por_periodo({"carpeta_por_periodo": "si"}))
        self.assertTrue(mod_flujo.carpeta_por_periodo({"carpeta_por_periodo": True}))


class TestCarpetaPorMes(BaseIntegracion):
    """Los archivos de cada mes (o quincena, o día) caen en su carpeta, también con «para cada opción»."""

    COMERCIOS = ["TIENDA CENTRO 10000000001", "TIENDA NORTE 10000000002", "TIENDA SUR II 10000000003",
                 "TIENDA PLAYA 10000000004", "TIENDA AEROPUERTO 10000000005"]

    def flujo(self, con_lista=False, carpeta_paso="", periodos=None):
        url = self.base + "pagos_consulta.html"
        pasos = [Paso("abrir_url", url=url)]
        if con_lista:
            pasos.append(Paso("elegir_opcion", selectores=["#LocationIdlabel"], objetivo="Localidad",
                              filtro="Localidad", estrategia="cada_una"))
        pasos += [Paso("escribir", selectores=["#DateFrom"], objetivo="Fecha Desde", valor="{desde:%d/%m/%Y}",
                       fecha_directa=True),
                  Paso("escribir", selectores=["#DateTo"], objetivo="Fecha Hasta", valor="{hasta:%d/%m/%Y}",
                       fecha_directa=True),
                  Paso("descargar", selectores=["#ExcelButton"], objetivo="Excel", nombre="{reporte}{ext}",
                       carpeta=carpeta_paso)]
        f = Flujo(nombre="Pagos del mes", url=url, pasos=pasos)
        f.opciones.update(timeout_paso=15, timeout_descarga=30, pausa_entre_pasos=0, carpeta_por_periodo=True)
        if periodos:
            f.opciones["repetir_dias"] = periodos
        return f

    def archivos(self, carpeta=None):
        raiz = carpeta or self.descargas
        res = []
        for base, _dirs, ficheros in os.walk(raiz):
            for f in ficheros:
                res.append(os.path.relpath(os.path.join(base, f), raiz).replace("\\", "/"))
        return sorted(res)

    def test_sin_repeticion_usa_las_fechas_del_reporte(self):
        f = self.flujo()
        f.pasos[1].valor, f.pasos[2].valor = "01/10/2026", "31/10/2026"
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual(self.archivos(), ["Pagos del mes/2026-10 octubre/Pagos del mes.xls"])
        self.assertIn("(los archivos de este periodo se guardan en:", log)
        self.assertIn("los archivos se guardaron en", r.resumen())

    def test_sin_fechas_usa_el_mes_de_hoy(self):
        f = self.flujo()
        f.pasos[1].valor = f.pasos[2].valor = ""          # sin fecha: pasos que se saltan
        r = self.ejecutar(f)
        self.assertTrue(r.ok, self.leer_log(r))
        self.assertEqual(self.archivos(), ["Pagos del mes/2026-03 marzo/Pagos del mes.xls"])   # HOY = 15/03/2026

    def test_una_carpeta_por_mes_con_ponerse_al_dia(self):
        f = self.flujo(periodos={"modo": "meses", "rango": "fijo", "desde": "2026-01-01", "hasta": "2026-02-28"})
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        # con una carpeta por mes, los nombres no llevan el periodo (no se pueden pisar)
        self.assertEqual(self.archivos(), ["Pagos del mes/2026-01 enero/Pagos del mes.xls",
                                           "Pagos del mes/2026-02 febrero/Pagos del mes.xls"])
        self.assertEqual(len(r.carpetas), 2)
        self.assertIn("2 carpetas", r.resumen())

    def test_quincenas_y_dias(self):
        f = self.flujo(periodos={"modo": "quincenas", "rango": "fijo", "desde": "2026-01-01", "hasta": "2026-01-31",
                                 "corte": 16, "mitades": "ambas"})
        r = self.ejecutar(f)
        self.assertTrue(r.ok, self.leer_log(r))
        self.assertEqual([a.split("/")[1] for a in self.archivos()],
                         ["2026-01 enero 1a quincena", "2026-01 enero 2a quincena"])
        shutil.rmtree(self.descargas, ignore_errors=True)
        g = self.flujo(periodos={"modo": "fijo", "desde": "2026-01-05", "hasta": "2026-01-06"})
        g.pasos[1].valor, g.pasos[2].valor = "{fecha:%d/%m/%Y}", "{fecha:%d/%m/%Y}"
        r = self.ejecutar(g)
        self.assertTrue(r.ok, self.leer_log(r))
        self.assertEqual([a.split("/")[1] for a in self.archivos()], ["2026-01-05", "2026-01-06"])

    def test_todas_las_opciones_del_mes_en_la_misma_carpeta(self):
        f = self.flujo(con_lista=True)
        f.pasos[2].valor, f.pasos[3].valor = "01/10/2026", "31/10/2026"
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual(self.archivos(),
                         sorted("Pagos del mes/2026-10 octubre/Pagos del mes - %s.xls" % c for c in self.COMERCIOS))
        self.assertEqual(len(r.carpetas), 1)

    def test_la_carpeta_del_paso_manda_y_el_mes_va_dentro(self):
        propia = os.path.join(self.tmp, "PDFs")
        f = self.flujo(carpeta_paso=propia)
        f.pasos[1].valor, f.pasos[2].valor = "01/10/2026", "31/10/2026"
        r = self.ejecutar(f)
        self.assertTrue(r.ok, self.leer_log(r))
        self.assertEqual(self.archivos(propia), ["2026-10 octubre/Pagos del mes.xls"])   # sin el nombre del reporte
        self.assertEqual(self.archivos(), [])

    def test_no_pisa_lo_que_ya_estaba(self):
        f = self.flujo()
        f.pasos[1].valor, f.pasos[2].valor = "01/10/2026", "31/10/2026"
        self.assertTrue(self.ejecutar(f).ok)
        r = self.ejecutar(f)
        self.assertTrue(r.ok, self.leer_log(r))
        self.assertEqual(self.archivos(), ["Pagos del mes/2026-10 octubre/Pagos del mes (2).xls",
                                           "Pagos del mes/2026-10 octubre/Pagos del mes.xls"])

    def test_sin_la_casilla_todo_sigue_como_antes(self):
        f = self.flujo()
        f.opciones.pop("carpeta_por_periodo")
        f.pasos[1].valor, f.pasos[2].valor = "01/10/2026", "31/10/2026"
        r = self.ejecutar(f)
        self.assertTrue(r.ok, self.leer_log(r))
        self.assertEqual(self.archivos(), ["Pagos del mes.xls"])


class TestCarpetaMesEnLaVentana(BaseApi):
    """La casilla de la ventana «Programar»: se guarda, se ve y «Probar ahora» la usa sin tocar lo guardado."""

    def reporte(self):
        f = Flujo(nombre="Pagos", url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"),
            Paso("escribir", selectores=["#d"], objetivo="Fecha Desde", valor="01/10/2026", fecha_directa=True),
            Paso("descargar", selectores=["#b"], objetivo="Excel", nombre="{reporte}{ext}")])
        return self.alm.guardar(f)

    def test_ver_y_guardar(self):
        rid = self.reporte()
        v = self.api("GET", "reportes/%d/cada_mes" % rid)
        self.assertFalse(v["carpeta"]["activo"])
        self.assertTrue(v["carpeta"]["ejemplo"].endswith(os.path.join("Pagos", mod_flujo.carpeta_de_periodo(
            *__import__("webbot.fechas_reporte", fromlist=["x"]).mes_anterior()))), v["carpeta"]["ejemplo"])
        r = self.api("POST", "reportes/%d/cada_mes" % rid, {"carpeta_mes": True, "imprimir": {"activo": False},
                                                            "fechas": "no_tocar", "cuando": {"modo": "no"}})
        self.assertIn("cada mes en su propia carpeta", r["cambios"])
        self.assertTrue(self.alm.cargar_flujo(rid).opciones["carpeta_por_periodo"])
        self.assertTrue(self.api("GET", "reportes/%d/cada_mes" % rid)["carpeta"]["activo"])
        # y se puede quitar
        r = self.api("POST", "reportes/%d/cada_mes" % rid, {"carpeta_mes": False, "imprimir": {"activo": False},
                                                            "fechas": "no_tocar", "cuando": {"modo": "no"}})
        self.assertIn("todo en la misma carpeta (sin carpeta por mes)", r["cambios"])
        self.assertNotIn("carpeta_por_periodo", self.alm.cargar_flujo(rid).opciones)

    def test_probar_ahora_la_usa_sin_guardarla(self):
        rid = self.reporte()
        antes = self.alm.cargar_flujo(rid).a_json()
        lanzados = []
        self.app._lanzar_uno = lambda fl, r, ver, lento, variables, descripcion=None: lanzados.append(fl) or su.Trabajo("ejecutar", "")
        self.api("POST", "reportes/%d/cada_mes" % rid, {"probar": True, "carpeta_mes": True, "fechas": "no_tocar",
                                                        "imprimir": {"activo": False}})
        self.assertTrue(lanzados[0].opciones["carpeta_por_periodo"])
        self.assertEqual(self.alm.cargar_flujo(rid).a_json(), antes)


if __name__ == "__main__":
    unittest.main()
