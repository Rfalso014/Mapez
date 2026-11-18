"""Pruebas de la versión 3.9 «Pagos»: lo que fallaba en un portal de pagos real.

Diagnóstico del 12/11/2026 (reporte «Comprobantes» del portal de Pagos):
- Fechas: los campos «DateFrom» / «DateTo» llevan bootstrap-datepicker 1.3.  El bot escribía la fecha con `fill` y el
  campo la enseñaba («OK»), pero el calendario no se enteraba (solo lee lo tecleado: keyup) y, al cerrarse con el clic
  siguiente (forceParse), volvía a poner SU fecha: el PDF salía con las fechas de la semana en curso, sin avisar.
  Ahora la fecha se pone con el propio calendario (bootstrap-datepicker, jQuery UI, flatpickr, Kendo o <input
  type=date>) y se comprueba; si no la acepta, el paso falla con un mensaje claro.  Los clics grabados dentro del
  calendario («‹», un día) junto a un paso que escribe la fecha se omiten.
- PDF: «PDF» abre el PDF en una pestaña nueva (visor de PDF del navegador).  El paso grabado «descargar Download» (un
  botón del visor, que no es de la página) esperaba para siempre.  Ahora el bot guarda el PDF de la pestaña (también si
  es un blob:) con el nombre de siempre y cierra esa pestaña; y al grabar, el clic que abre el PDF queda como descarga.
Página de prueba `pagos_consulta.html` (+ /api/pagos/… en el servidor de prueba).  Navegador oculto, carpetas
temporales, sin red, sin la base de datos real ni el llavero.
"""

import datetime
import os
import sys
import tempfile
import shutil
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import test_integracion  # noqa: E402
from test_integracion import BaseIntegracion  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot import mapeador  # noqa: E402
from webbot.ejecutor import Ejecutor, nombre_pdf  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402
from webbot.grabador_web import GrabadorWeb  # noqa: E402

PAGINA = "pagos_consulta.html"
NOMBRE = "{reporte} - {nombre} {hoy:%Y-%m-%d}{ext}"
# Selectores como los grabó el bot en el portal real (calendario bootstrap-datepicker)
CLIC_ANTERIOR = ['.datepicker-days th:text-is("«")', 'th.prev:text-is("«")', 'th:text-is("«")',
                 "div.datepicker > div:nth-of-type(1) > table:nth-of-type(1) > thead:nth-of-type(1) > tr:nth-of-type(1)"
                 " > th:nth-of-type(1)"]
CLIC_DIA_1 = ["div.datepicker > div:nth-of-type(1) > table:nth-of-type(1) > tbody:nth-of-type(1) > tr:nth-of-type(1)"
              " > td:nth-of-type(5)"]


def mes_anterior():
    """(primer día, último día) del mes anterior al de HOY DE VERDAD (el calendario de la página no deja fechas
    futuras y usa el reloj del navegador)."""
    hoy = datetime.date.today()
    fin = hoy.replace(day=1) - datetime.timedelta(days=1)
    return fin.replace(day=1).strftime("%d/%m/%Y"), fin.strftime("%d/%m/%Y")


class BasePagos(BaseIntegracion):
    def flujo(self, pasos, nombre="Pagos"):
        f = Flujo(nombre=nombre, url=self.base + PAGINA)
        f.opciones["timeout_paso"] = 8
        f.opciones["timeout_descarga"] = 20
        f.pasos = [Paso("abrir_url", url=self.base + PAGINA)] + pasos
        return f

    def leer(self, ruta, modo="rb"):
        with open(ruta, modo) as f:
            return f.read()


class TestFechasEnCalendario(BasePagos):
    def test_la_pagina_reproduce_el_fallo(self):
        """Sin el arreglo: lo escrito de golpe se ve en el campo, pero el siguiente clic lo deja en la fecha de antes."""
        from playwright.sync_api import sync_playwright
        desde, _hasta = mes_anterior()
        with sync_playwright() as p:
            nav = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = nav.new_page()
                pg.goto(self.base + PAGINA)
                antes = pg.input_value("#DateFrom")
                pg.fill("#DateFrom", desde)
                self.assertEqual(pg.input_value("#DateFrom"), desde)          # parece que funcionó…
                pg.click("#SearchButton")
                self.assertEqual(pg.input_value("#DateFrom"), antes)          # …pero el calendario lo devolvió
                self.assertEqual(pg.inner_text("#resultado").split(" ")[2], antes)
            finally:
                nav.close()

    def test_las_fechas_quedan_puestas_en_el_calendario(self):
        desde, hasta = mes_anterior()
        f = self.flujo([
            Paso("escribir", selectores=["#DateFrom", 'input[name="DateFrom"]'], objetivo="DateFrom", valor=desde,
                 fecha_directa=True),
            Paso("escribir", selectores=["#DateTo", 'input[name="DateTo"]'], objetivo="DateTo", valor=hasta,
                 fecha_directa=True),
            Paso("clic", selectores=["#SearchButton"], objetivo="Consultar"),
            Paso("esperar_elemento", selectores=['#resultado:text-is("Consulta del %s al %s (comercio 501)")' % (desde, hasta)])])
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertIn("(calendario bootstrap-datepicker: fecha puesta con el propio calendario; se ve «%s»)" % desde, log)

    def test_fecha_que_el_calendario_no_acepta_falla_con_mensaje_claro(self):
        futura = (datetime.date.today() + datetime.timedelta(days=40)).strftime("%d/%m/%Y")
        f = self.flujo([Paso("escribir", selectores=["#DateTo"], objetivo="DateTo", valor=futura, fecha_directa=True),
                        Paso("clic", selectores=["#SearchButton"], objetivo="Consultar")])
        r = self.ejecutar(f)
        self.assertFalse(r.ok)
        self.assertEqual(r.paso_fallido, 2)
        self.assertIn("El calendario de la página (bootstrap-datepicker) no aceptó la fecha «%s»" % futura, r.error)

    def test_campo_de_fecha_del_navegador(self):
        """<input type=date>: la fecha «dd/mm/aaaa» del reporte se pone como aaaa-mm-dd (antes `fill` la rechazaba)."""
        desde, hasta = mes_anterior()
        d, m, a = desde.split("/")
        f = self.flujo([
            Paso("escribir", selectores=["#FechaPago"], objetivo="Fecha de pago", valor=desde, fecha_directa=True),
            Paso("clic", selectores=["#SearchButton"], objetivo="Consultar"),
            Paso("esperar_elemento", selectores=['#resultado:has-text("pagado el %s-%s-%s")' % (a, m, d)])])
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertIn("(calendario del navegador: fecha puesta con el propio calendario; se ve «%s-%s-%s»)" % (a, m, d), log)

    def test_clics_grabados_en_el_calendario_se_omiten(self):
        """Como el reporte real con los clics del calendario activos: «‹» y «1» antes de escribir cada fecha."""
        desde, hasta = mes_anterior()
        f = self.flujo([
            Paso("clic", selectores=CLIC_ANTERIOR, objetivo="«"),
            Paso("clic", selectores=CLIC_DIA_1, objetivo="1"),
            Paso("escribir", selectores=["#DateFrom"], objetivo="DateFrom", valor=desde, fecha_directa=True),
            Paso("clic", selectores=CLIC_ANTERIOR, objetivo="«", desactivado=True),
            Paso("clic", selectores=['.datepicker-days td:text-is("31")', 'td.day:text-is("31")'], objetivo="31"),
            Paso("escribir", selectores=["#DateTo"], objetivo="DateTo", valor=hasta, fecha_directa=True),
            Paso("clic", selectores=["#SearchButton"], objetivo="Consultar"),
            Paso("esperar_elemento", selectores=['#resultado:text-is("Consulta del %s al %s (comercio 501)")' % (desde, hasta)])])
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual(log.count("clic dentro del calendario: se omite"), 3, log)

    def test_solo_se_omiten_los_clics_seguidos_de_una_fecha(self):
        tmp = tempfile.mkdtemp(prefix="botweb_v39_")
        self.addCleanup(shutil.rmtree, tmp, True)
        f = Flujo(nombre="x", url="http://127.0.0.1/", pasos=[
            Paso("clic", selectores=CLIC_ANTERIOR, objetivo="«"),                                         # 0: sí
            Paso("escribir", selectores=["#d"], valor="{inicio_mes_anterior}", fecha_directa=True),
            Paso("clic", selectores=['td.day:text-is("5")'], objetivo="5"),                               # 2: no
            Paso("clic", selectores=["#buscar"], objetivo="Buscar"),                                      # 3: no
            Paso("clic", selectores=['.ui-datepicker-calendar a:text-is("9")'], objetivo="9"),            # 4: sí
            Paso("escribir", selectores=["#h"], valor="09/10/2026"),
            Paso("clic", selectores=['.datepicker td:text-is("2")'], objetivo="2"),                       # 6: no
            Paso("escribir", selectores=["#c"], valor="Cliente 2"),
            # 8: no (una lista de comercios con el estilo «datepicker»: no es un calendario)
            Paso("clic", selectores=["div.datepicker > ul > li:nth-of-type(5)"], objetivo="TIENDA NORTE 10000000002"),
            Paso("escribir", selectores=["#d"], valor="01/10/2026", fecha_directa=True),
            Paso("clic", selectores=['.datepicker th.prev:text-is("‹")'], objetivo="‹"),                       # 10: sí
            Paso("clic", selectores=['.datepicker-switch'], objetivo="Octubre 2026"),                     # 11: sí
            Paso("escribir", selectores=["#d"], valor="01/10/2026", fecha_directa=True)])
        ej = Ejecutor(f, carpeta_perfil=os.path.join(tmp, "p"), carpeta_registros=os.path.join(tmp, "r"),
                      carpeta_descargas=os.path.join(tmp, "d"))
        self.assertEqual([i for i in range(len(f.pasos)) if ej._clic_de_calendario_sobrante(i)], [0, 4, 10, 11])


class TestPdfEnPestana(BasePagos):
    def comprobar_pdf(self, ruta, *textos):
        datos = self.leer(ruta)
        self.assertTrue(datos.startswith(b"%PDF"), datos[:40])
        for t in textos:
            self.assertIn(t.encode("latin-1"), datos)

    def test_flujo_grabado_con_el_boton_download_del_visor(self):
        """El reporte tal como quedó grabado: clic «PDF» + «descargar Download» (pestaña 2, dentro del visor) + Excel."""
        desde, hasta = mes_anterior()
        f = self.flujo([
            Paso("escribir", selectores=["#DateFrom"], objetivo="DateFrom", valor=desde, fecha_directa=True),
            Paso("escribir", selectores=["#DateTo"], objetivo="DateTo", valor=hasta, fecha_directa=True),
            Paso("clic", selectores=["#PDFButton", 'role=button[name="PDF"]'], objetivo="PDF"),
            Paso("descargar", selectores=["#save"], nombre=NOMBRE, objetivo="Download", pagina=1,
                 marco=["iframe:nth-of-type(1)"]),
            Paso("descargar", selectores=["#ExcelButton", 'role=button[name="Excel"]'], nombre=NOMBRE,
                 objetivo="Excel")])
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        pdf = os.path.join(self.descargas, "Pagos - ReportePagos 2026-03-15.pdf")
        xls = os.path.join(self.descargas, "Pagos - ReportePagos 2026-03-15.xls")
        self.assertEqual(r.archivos, [pdf, xls])
        self.comprobar_pdf(pdf, "Desde %s" % desde, "Hasta %s" % hasta)
        self.assertIn("Desde;Hasta;Comercio\n%s;%s;501" % (desde, hasta), self.leer(xls, "r"))
        # v3.9: el PDF se pide con la sesión del navegador: no se abre (ni se cierra) ninguna pestaña
        self.assertIn("(el PDF se pidió al servidor sin abrir otra pestaña)", log)
        self.assertNotIn("se abrió en una pestaña", log)
        self.assertNotIn("se cierra la pestaña del PDF", log)
        self.assertIn("archivo guardado: %s" % pdf, log)
        self.assertEqual(self.servidor.estado["descargas"][-2:],
                         ["Pagos PDF 501 %s %s" % (desde, hasta), "Pagos Excel 501 %s %s" % (desde, hasta)])

    def test_descargar_con_el_boton_que_abre_el_pdf(self):
        """Como queda una grabación nueva: el propio botón «PDF» es el paso «descargar».  La primera vez el bot no sabe
        que abre un PDF (se abre la pestaña, se guarda y se cierra); a partir de ahí lo pide sin abrir nada."""
        f = self.flujo([Paso("descargar", selectores=["#PDFButton"], nombre="Uno{ext}", objetivo="PDF"),
                        Paso("descargar", selectores=["#PDFButton"], nombre="Dos{ext}", objetivo="PDF"),
                        Paso("descargar", selectores=["#ExcelButton"], nombre="Comprobantes{ext}", objetivo="Excel")])
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual([os.path.basename(a) for a in r.archivos], ["Uno.pdf", "Dos.pdf", "Comprobantes.xls"])
        self.comprobar_pdf(r.archivos[0], "Reporte de pagos")
        self.comprobar_pdf(r.archivos[1], "Reporte de pagos")
        self.assertEqual(log.count("(el PDF se abrió en una pestaña del navegador: se guarda su contenido)"), 1, log)
        self.assertEqual(log.count("(se cierra la pestaña del PDF)"), 1, log)
        self.assertEqual(log.count("(el PDF se pidió al servidor sin abrir otra pestaña)"), 1, log)

    def test_pdf_blob_en_pestana_nueva(self):
        desde, hasta = mes_anterior()
        f = self.flujo([
            Paso("escribir", selectores=["#DateFrom"], objetivo="DateFrom", valor=desde, fecha_directa=True),
            Paso("descargar", selectores=["#PDFBlobButton"], nombre="Blob {nombre}{ext}", objetivo="PDF (blob)"),
            Paso("clic", selectores=["#PDFBlobButton"], objetivo="PDF (blob)"),
            Paso("descargar", selectores=["#save"], nombre="Blob 2{ext}", objetivo="Download", pagina=2,
                 marco=["iframe:nth-of-type(1)"])])
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual([os.path.basename(a) for a in r.archivos], ["Blob documento.pdf", "Blob 2.pdf"])
        for a in r.archivos:
            self.comprobar_pdf(a, "Reporte de pagos blob", "Desde %s" % desde)

    def test_si_lo_que_abre_no_es_un_pdf_la_pestana_se_abre_igual(self):
        """Respaldo: el bot espera un PDF (el paso siguiente baja del visor), pero la web abre una página normal:
        se abre la pestaña de verdad, como habría hecho la web."""
        f = self.flujo([Paso("clic", selectores=["#OtraButton"], objetivo="Ver en otra pestaña"),
                        Paso("descargar", selectores=["#save"], objetivo="Download", pagina=1,
                             marco=["iframe:nth-of-type(1)"], nombre="X{ext}", opcional=True),
                        Paso("esperar_elemento", selectores=["#SearchButton"], pagina=1)])
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertIn("(lo que abría la página no era un PDF: se abre en otra pestaña como siempre)", log)

    def test_nombre_del_pdf(self):
        self.assertEqual(nombre_pdf("filename=ReporteComprobantes.pdf;", "https://pagos.ejemplo.com/x/ComprobantesPdf?a=1"),
                         "ReporteComprobantes.pdf")
        self.assertEqual(nombre_pdf("", "https://pagos.ejemplo.com/x/ComprobantesPdf?a=1"), "ComprobantesPdf.pdf")
        self.assertEqual(nombre_pdf("inline; filename*=UTF-8''Pagos%20Octubre.pdf", ""), "Pagos Octubre.pdf")
        self.assertEqual(nombre_pdf("", "blob:https://pagos.ejemplo.com/1234"), "documento.pdf")


COMERCIOS = ["TIENDA CENTRO 10000000001", "TIENDA NORTE 10000000002", "TIENDA SUR II 10000000003",
             "TIENDA PLAYA 10000000004", "TIENDA AEROPUERTO 10000000005"]


class TestParaCadaComercio(BasePagos):
    """La lista de comercios del portal: propia (no un <select>), con buscador, una cabecera de grupo (la empresa, que
    NO es un comercio) y cada comercio con su nombre y su número en una etiqueta aparte."""

    def pasos_reporte(self, eleccion):
        desde, hasta = mes_anterior()
        return [
            eleccion,
            Paso("clic", selectores=CLIC_ANTERIOR, objetivo="«", desactivado=True),
            Paso("escribir", selectores=["#DateFrom"], objetivo="DateFrom", valor=desde, fecha_directa=True),
            Paso("escribir", selectores=["#DateTo"], objetivo="DateTo", valor=hasta, fecha_directa=True),
            Paso("clic", selectores=["#PDFButton"], objetivo="PDF"),
            Paso("descargar", selectores=["#save"], nombre=NOMBRE, objetivo="Download", pagina=1,
                 marco=["iframe:nth-of-type(1)"]),
            Paso("descargar", selectores=["#ExcelButton"], nombre=NOMBRE, objetivo="Excel")]

    def test_leer_la_lista_sin_cabecera_ni_buscador(self):
        f = self.flujo([Paso("elegir_opcion", selectores=["#LocationIdlabel"], objetivo="Comercio", estrategia="ultima")])
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual(r.opciones_leidas[1]["opciones"], COMERCIOS)
        self.assertIn("→ «TIENDA AEROPUERTO 10000000005» (ultima; 5 opciones)", log)

    def test_cada_comercio_un_pdf_y_un_excel(self):
        desde, hasta = mes_anterior()
        f = self.flujo(self.pasos_reporte(
            Paso("elegir_opcion", selectores=["#LocationIdlabel"], objetivo="Comercio", estrategia="cada_una")))
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertIn("Para cada opción de «Comercio»: 5 opciones", log)
        self.assertIn("Terminado: 5 opciones de «Comercio», ", r.resumen())         # (no «… de -3 pasos»)
        self.assertNotIn("desactivados", r.resumen())
        # el PDF de cada comercio se pide sin abrir ninguna pestaña (antes se abría y se cerraba una por comercio)
        self.assertEqual(log.count("(el PDF se pidió al servidor sin abrir otra pestaña)"), 5, log)
        self.assertNotIn("se cierra la pestaña del PDF", log)
        nombres = [os.path.basename(a) for a in r.archivos]
        esperados = []
        for c in COMERCIOS:
            esperados += ["Pagos - ReportePagos 2026-03-15 - %s.pdf" % c, "Pagos - ReportePagos 2026-03-15 - %s.xls" % c]
        self.assertEqual(nombres, esperados)
        for n, a in enumerate(r.archivos):
            numero = 501 + n // 2
            if a.endswith(".pdf"):
                self.comprobar_pdf(a, "Comercio %d" % numero, "Desde %s" % desde, "Hasta %s" % hasta)
            else:
                self.assertIn("%s;%s;%d" % (desde, hasta, numero), self.leer(a, "r"))

    def test_los_que_marque(self):
        f = self.flujo(self.pasos_reporte(
            Paso("elegir_opcion", selectores=["#LocationIdlabel"], objetivo="Comercio", estrategia="marcadas",
                 valores=[COMERCIOS[3], COMERCIOS[1]])))
        f.pasos[-1].nombre = "{reporte} {opcion}{ext}"
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual([os.path.basename(a) for a in r.archivos],
                         ["Pagos - ReportePagos 2026-03-15 - %s.pdf" % COMERCIOS[3], "Pagos %s.xls" % COMERCIOS[3],
                          "Pagos - ReportePagos 2026-03-15 - %s.pdf" % COMERCIOS[1], "Pagos %s.xls" % COMERCIOS[1]])
        excel = [x.split(" ")[2] for x in self.servidor.estado["descargas"] if x.startswith("Pagos Excel")]
        self.assertEqual(excel[-2:], ["504", "502"])

    comprobar_pdf = TestPdfEnPestana.comprobar_pdf


class _PaginaFalsa:
    def __init__(self):
        self.cerrada = False

    def is_closed(self):
        return self.cerrada


class _DescargaFalsa:
    suggested_filename = "ReportePagos.pdf"

    def save_as(self, ruta):
        with open(ruta, "wb") as f:
            f.write(b"%PDF-1.4\n")

    def failure(self):
        return None


class TestGrabarPdfEnPestana(unittest.TestCase):
    def test_el_clic_que_abre_el_pdf_queda_como_descarga(self):
        tmp = tempfile.mkdtemp(prefix="botweb_v39g_")
        self.addCleanup(shutil.rmtree, tmp, True)
        f = Flujo(nombre="Pagos", url="https://pagos.ejemplo.com/")
        f.pasos = [Paso("abrir_url", url=f.url), Paso("clic", selectores=["#PDFButton"], objetivo="PDF")]
        eventos = []
        g = GrabadorWeb(f, os.path.join(tmp, "perfil"), al_evento=lambda tipo, **d: eventos.append((tipo, d)),
                        carpeta_descargas_grabacion=os.path.join(tmp, "grabacion"))
        principal, visor = _PaginaFalsa(), _PaginaFalsa()
        g.paginas = [principal, visor]
        g._procesar_pdf(visor)
        g._procesar_pdf(visor)                                   # la misma pestaña otra vez: nada nuevo
        self.assertEqual([p.tipo for p in f.pasos], ["abrir_url", "descargar"])
        self.assertEqual((f.pasos[1].selectores, f.pasos[1].nombre), (["#PDFButton"], mod_flujo.NOMBRE_DESCARGA_DEFECTO))
        # lo que se pulse en el visor («Download») y su descarga no son pasos nuevos
        g._procesar_evento(visor, None, {"tipo": "clic", "candidatos": ["#save"], "objetivo": "Download"})
        g._procesar_descarga(visor, _DescargaFalsa())
        self.assertEqual([p.tipo for p in f.pasos], ["abrir_url", "descargar"])
        self.assertTrue(any("Se abrió un PDF en una pestaña" in d.get("texto", "") for t, d in eventos if t == "estado"))


class TestGrabarPdfReal(BasePagos):
    """Grabación de verdad (navegador oculto): pulsar «PDF» y luego «Excel»; al repetirla se guardan los dos."""
    grabar = test_integracion.TestGrabador.grabar

    def test_grabar_y_repetir_pdf_en_pestana(self):
        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#PDFButton")
            pg.wait_for_timeout(500)
            pg.click("#PDFButton")
            fin = 0
            while len(g.paginas) < 2 and fin < 50:
                pg.wait_for_timeout(100)
                fin += 1
            g.paginas[-1].wait_for_load_state("load")
            pg.wait_for_timeout(800)
            pg.bring_to_front()
            pg.click("#ExcelButton")
            pg.wait_for_timeout(1500)

        flujo, eventos = self.grabar(conducir, Flujo(nombre="Pagos", url=self.base + PAGINA))
        tipos = [(p.tipo, p.objetivo) for p in flujo.pasos if not p.desactivado]
        self.assertEqual(tipos, [("abrir_url", ""), ("descargar", "PDF"), ("descargar", "Excel")], tipos)
        flujo.opciones["timeout_paso"] = 8
        flujo.opciones["timeout_descarga"] = 20
        r = self.ejecutar(flujo)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual(sorted(os.path.splitext(a)[1] for a in r.archivos), [".pdf", ".xls"])


class TestBotonDelVisorDePdf(BasePagos):
    """El visor de PDF del navegador tiene sus propios botones (guardar, imprimir) que NO son de la página: un paso
    grabado sobre ellos no se puede ejecutar.  (En el portal de pagos la gente imprime con ese icono.)"""

    def pasos(self, selector="#print"):
        return [Paso("clic", selectores=["#PDFBlobButton"], objetivo="PDF (blob)"),
                Paso("clic", selectores=[selector], objetivo="Imprimir", pagina=1)]

    def test_sin_la_casilla_falla_diciendo_que_hacer(self):
        f = self.flujo(self.pasos())
        r = self.ejecutar(f)
        self.assertFalse(r.ok)
        self.assertEqual(r.paso_fallido, 3)
        self.assertIn("botón del visor de PDF del navegador", r.error)
        self.assertIn("marca «Imprimir los PDF que descargue»", r.error)

    def test_con_la_casilla_se_salta(self):
        f = self.flujo(self.pasos())
        f.opciones["imprimir_pdf"] = {"activo": True, "impresora": "Impresora Que No Se Usa"}
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertIn("este botón es del visor de PDF del navegador y no se puede pulsar", log)

    def test_un_boton_igual_pero_de_la_pagina_si_se_pulsa(self):
        """El mismo nombre de selector en una página normal (no un PDF) se pulsa como siempre."""
        f = self.flujo([Paso("clic", selectores=["#SearchButton"], objetivo="Consultar"),
                        Paso("esperar_elemento", selectores=['#resultado:has-text("Consulta del")'])])
        r = self.ejecutar(f)
        self.assertTrue(r.ok, self.leer_log(r))


# ============================================================================ v3.9: «Mapear la página» y la lista propia
from test_integracion_v33 import BaseMapeo  # noqa: E402


class TestMapearListaDeFilas(BaseMapeo):
    """«Mapear toda la página» no encontraba la lista de comercios: no es un <select>, no tiene role=listbox ni
    aria-haspopup y todo lo suyo (el campo con el valor y los radios de cada fila) está oculto.  Ahora se reconoce por
    el recuadro visible + la lista cerrada de filas con radios ocultos."""

    def mapa(self):
        self.abrir(PAGINA)
        return self.api("POST", "mapa/mapear", {"alcance": "todo"})

    def test_la_lista_de_comercios_sale_con_su_etiqueta_y_sus_opciones(self):
        m = self.mapa()
        por = self.por_etiqueta(m)
        self.assertIn("Comercio", por, sorted(por))
        f = por["Comercio"]
        self.assertEqual(f["tipo"], "lista")
        self.assertEqual(f["valor"], COMERCIOS[0])                      # lo que enseña el recuadro
        self.assertEqual(f["opciones"], COMERCIOS)                      # sin la cabecera del grupo ni el buscador
        self.assertEqual(m["errores"], [])
        # las fechas y los botones siguen saliendo
        self.assertEqual(por["Desde"]["tipo"], "fecha")
        self.assertEqual(por["Hasta"]["tipo"], "fecha")
        self.assertEqual(por["Consultar"]["tipo"], "accion")

    def test_la_barra_de_la_web_y_un_grupo_de_botones_no_son_listas(self):
        m = self.mapa()
        listas = [f for f in m["filtros"] if f["tipo"] in ("lista", "lista_nativa")]
        self.assertEqual([f["etiqueta"] for f in listas], ["Comercio"], listas)
        textos = " | ".join((f.get("etiqueta") or "") for f in m["filtros"])
        for fuera in ("Inicio", "Movimientos", "Ayuda", "Resumen", "Detalle", "Gráfico", "Vista", "Buscar"):
            self.assertNotIn(fuera, textos)

    def test_el_paso_del_mapa_recorre_todos_los_comercios(self):
        m = self.mapa()
        por = self.por_etiqueta(m)
        pasos = mapeador.generar_pasos(m["filtros"], [
            {"k": por["Comercio"]["k"], "estrategia": "cada_una"},
            {"k": por["Desde"]["k"], "fecha": "plantilla", "valor": "{inicio_mes_anterior:%d/%m/%Y}"},
            {"k": por["Hasta"]["k"], "fecha": "plantilla", "valor": "{fin_mes_anterior:%d/%m/%Y}"},
            {"k": por["Consultar"]["k"], "modo": "clic"}])
        self.assertEqual([(p.tipo, p.estrategia if p.tipo == "elegir_opcion" else p.objetivo) for p in pasos],
                         [("elegir_opcion", "cada_una"), ("escribir", "Desde"), ("escribir", "Hasta"),
                          ("clic", "Consultar")])
        # el reporte baja el Excel con su botón (no es un botón de «acción» que el mapeo reconozca por su texto)
        pasos.append(Paso("descargar", selectores=["#ExcelButton"], objetivo="Excel", nombre="Comercios{ext}"))
        self.terminar()                      # (un trabajo con navegador cada vez)
        f = Flujo(nombre="Pagos mapeado", url=self.web.url_base + PAGINA)
        f.opciones.update(timeout_paso=15, timeout_descarga=20, pausa_entre_pasos=0)
        f.pasos = [Paso("abrir_url", url=f.url)] + pasos
        tmp = tempfile.mkdtemp(prefix="botweb_v39mapa_")
        self.addCleanup(shutil.rmtree, tmp, True)
        ej = Ejecutor(f, carpeta_perfil=os.path.join(tmp, "perfil"), carpeta_registros=os.path.join(tmp, "reg"),
                      carpeta_descargas=os.path.join(tmp, "desc"), oculto=True, hoy=datetime.date(2026, 3, 15),
                      pausa_entre_pasos=0)
        r = ej.ejecutar()
        with open(r.ruta_log, encoding="utf-8") as x:
            log = x.read()
        self.assertTrue(r.ok, log)
        self.assertEqual([os.path.basename(a) for a in r.archivos],
                         ["Comercios - %s.xls" % c for c in COMERCIOS], log)

    def test_paso_con_las_que_marque(self):
        f = {"tipo": "lista", "etiqueta": "Comercio", "selectores": ["#LocationIdlabel"], "valor": COMERCIOS[0]}
        paso = mapeador.paso_de_filtro(f, {"estrategia": "marcadas", "valores": [COMERCIOS[1], COMERCIOS[2]]})
        self.assertEqual((paso.tipo, paso.estrategia, paso.valores, paso.valor),
                         ("elegir_opcion", "marcadas", [COMERCIOS[1], COMERCIOS[2]], ""))
        self.assertEqual(paso.problemas(), [])
        self.assertTrue(mapeador.paso_de_filtro(f, {"estrategia": "marcadas", "valores": []}).sin_valor())


if __name__ == "__main__":
    unittest.main()
