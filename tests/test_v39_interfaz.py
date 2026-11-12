"""Pruebas de la interfaz de la versión 3.9 (navegador oculto, base de datos temporal):

- «Repetir: por quincenas» con día de corte, la vista previa («Se bajarán 4 archivos…»), el aviso «Ningún paso usa el
  periodo» con «Ponerlo en los campos de fecha», y lo que se guarda;
- «Al terminar, ejecutar otro reporte» (casillas) y el paso «Imprimir» con la lista de impresoras (FALSA: nunca se
  imprime ni se pregunta a Windows).
Sin tareas de Windows, sin avisos, sin diálogos de Windows, sin red.
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

from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from webbot import avisos, dialogos, impresion, secretos  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

HOY = datetime.date(2026, 11, 12)


def _nunca(*a, **k):
    raise AssertionError("¡Una prueba intentó usar Windows de verdad (diálogo o impresora)!")


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestEditorV39(unittest.TestCase):
    def setUp(self):
        for objeto, nombre in ((dialogos, "_dialogo_tk"), (impresion, "_lanzar"), (impresion, "_imprimir_pdf_windows"),
                               (impresion, "_enumerar"), (impresion, "_predeterminada")):
            p = mock.patch.object(objeto, nombre, _nunca)
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp(prefix="botweb_v39ui_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        avisos.usar_notificador(lambda t, x: None)
        self.addCleanup(avisos.usar_notificador, None)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "perfiles"),
                                 carpeta_registros=os.path.join(self.tmp, "registros"),
                                 carpeta_descargas=os.path.join(self.tmp, "descargas"), listar_tareas=lambda: [],
                                 oculto_forzado=True, hoy=HOY, ejecutar_tareas=lambda c: (1, "(prueba)"),
                                 abrir_dialogo=_nunca)
        self.app.listar_impresoras = lambda: {"impresoras": ["Impresora Oficina", "Impresora Bodega"],
                                              "predeterminada": "Impresora Oficina"}
        self.app.imprimir_archivo = _nunca
        self.addCleanup(self.app.detener)
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)

    def navegador(self):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self.addCleanup(self._p.stop)
        nav = self._p.chromium.launch(channel="chrome", headless=True)
        self.addCleanup(nav.close)
        pg = nav.new_page(viewport={"width": 1366, "height": 900})
        self.errores = []
        # (ERR_NO_BUFFER_SPACE: Windows sin sockets libres un momento, no es un error de la página)
        pg.on("console", lambda m: self.errores.append(m.text) if m.type == "error" and "ERR_NO_BUFFER_SPACE" not in m.text
              else None)
        pg.on("pageerror", lambda e: self.errores.append(str(e)))
        return pg

    def esperar_texto(self, pg, selector, texto, timeout=10000):
        pg.wait_for_function("([s, t]) => { const e = document.querySelector(s); return !!e && e.textContent.includes(t); }",
                             arg=[selector, texto], timeout=timeout)

    def poner(self, pg, etiqueta, valor):
        """Los días de «Desde / hasta» van detrás del calendario: se escriben en su campo (como lo haría el calendario)."""
        pg.evaluate("""([e, v]) => { const i = document.querySelector('input[aria-label="' + e + '"]'); i.value = v;
                        i.dispatchEvent(new Event('input', { bubbles: true })); i.dispatchEvent(new Event('change', { bubbles: true })); }""",
                    [etiqueta, valor])

    def test_repetir_por_quincenas_al_terminar_e_imprimir(self):
        rid = self.alm.guardar(Flujo(nombre="Informes", url="http://erp.ejemplo.com/", pasos=[
            Paso("abrir_url", url="http://erp.ejemplo.com/"),
            Paso("escribir", selectores=["#desde"], objetivo="Fecha desde", valor="{hoy:%d/%m/%Y}"),
            Paso("escribir", selectores=["#hasta"], objetivo="Fecha hasta", valor="{hoy:%d/%m/%Y}"),
            Paso("descargar", selectores=["#d"], objetivo="Exportar", nombre="{reporte} {hoy:%Y-%m-%d}{ext}")]))
        otro = self.alm.guardar(Flujo(nombre="Pagos", pasos=[Paso("abrir_url", url="http://erp.ejemplo.com/pagos")]))
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("editor/%d" % rid), wait_until="load")
        zona = "#contenido details[data-repetir='1']"
        pg.wait_for_selector(zona + " summary", timeout=15000)
        pg.click(zona + " summary")
        pg.select_option(zona + " select[data-repetir-tipo]", "quincenas")
        pg.fill(zona + " input[data-repetir-corte]", "16")
        pg.dispatch_event(zona + " input[data-repetir-corte]", "change")
        self.poner(pg, "Repetir desde el día", "2026-10-01")
        self.poner(pg, "Repetir hasta el día", "2026-11-30")
        vista = zona + " [data-repetir-vista]"
        self.esperar_texto(pg, vista, "Se bajarán 4 archivos (uno por quincena): 1.ª quincena de octubre 2026 (01/10 a 15/10), "
                                      "2.ª quincena de octubre 2026 (16/10 a 31/10)")
        self.esperar_texto(pg, vista, "todavía no han terminado")              # noviembre (hoy es 12/11)
        self.assertTrue(pg.locator(zona + " select[data-repetir-mitades]").is_visible())
        # ningún paso usa el periodo: el botón lo pone en los dos campos de fecha
        pg.click(zona + " button[data-usar-periodo]")
        self.esperar_texto(pg, "#contenido tr[data-indice='1']", "{desde}")
        self.esperar_texto(pg, "#contenido tr[data-indice='2']", "{hasta}")
        pg.wait_for_selector(zona + " [data-repetir-sin-periodo].oculto", state="attached")
        # «Al terminar, ejecutar…»
        cadena = "#contenido details[data-al-terminar='1']"
        pg.click(cadena + " summary")
        pg.check(cadena + " input[data-al-terminar='%d']" % otro)
        # paso «Imprimir» con la lista de impresoras
        pg.click("#contenido button:has-text('Insertar paso al final')")
        pg.select_option(".modal select[aria-label='Tipo de paso']", "imprimir")
        pg.click(".modal button:has-text('Siguiente')")
        pg.wait_for_selector(".modal input[data-impresora]")
        pg.click(".modal button[data-ver-impresoras]")
        pg.click(".modal button[data-impresora-elegir='Impresora Bodega']")
        self.assertEqual(pg.input_value(".modal input[data-impresora]"), "Impresora Bodega")
        pg.click(".modal button:has-text('Aceptar')")
        self.esperar_texto(pg, "#contenido tr[data-indice='4']", "en la impresora «Impresora Bodega»")
        pg.click("#contenido .barra-herr button.primario:has-text('Guardar')")
        pg.wait_for_function("() => document.querySelector('#subtitulo').textContent.includes('guardado')", timeout=10000)
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual(fl.opciones["repetir_dias"], {"modo": "quincenas", "rango": "fijo", "desde": "2026-10-01",
                                                       "hasta": "2026-11-30", "corte": 16, "mitades": "ambas"})
        self.assertEqual(fl.opciones["al_terminar"], {"reportes": [otro], "cuando": "bien"})
        self.assertEqual([p.valor for p in fl.pasos[1:3]], ["{desde}", "{hasta}"])
        self.assertEqual((fl.pasos[4].tipo, fl.pasos[4].impresora, fl.pasos[4].que_imprimir), ("imprimir", "Impresora Bodega", "archivo"))
        self.assertEqual(self.errores, [])

    def test_para_cada_opcion_en_el_paso_y_reportes_de_antes(self):
        rid = self.alm.guardar(Flujo(nombre="Tablas", url="http://erp.ejemplo.com/", pasos=[
            Paso("abrir_url", url="http://erp.ejemplo.com/"),
            Paso("elegir_opcion", selectores=["#tabla"], objetivo="Tabla", valor="Ventas"),
            Paso("descargar", selectores=["#d"], objetivo="Exportar")]))
        self.alm.guardar_opciones_filtro(rid, 1, ["Ventas", "Pagos", "Inventario"], {}, "#tabla", "actualizar")
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("editor/%d" % rid), wait_until="load")
        pg.wait_for_selector("#contenido tr[data-indice='1']", timeout=15000)
        # sin repetir: la sección está cerrada y dice «No repetir»
        self.assertEqual(pg.input_value("#contenido select[data-repetir-tipo]"), "no")
        pg.locator("#contenido tr[data-indice='1'] button:has-text('Editar')").click()
        pg.select_option(".modal select[aria-label='Qué opción elegir']", "marcadas")
        pg.wait_for_selector(".modal [data-ayuda-bucle]:not(.oculto)")
        pg.wait_for_selector(".modal input[data-opcion-conocida='Pagos']")
        pg.check(".modal input[data-opcion-conocida='Pagos']")
        pg.check(".modal input[data-opcion-conocida='Inventario']")
        self.assertEqual(pg.input_value(".modal textarea[data-valores-opcion]"), "Pagos\nInventario")
        pg.click(".modal button:has-text('Aceptar')")
        self.esperar_texto(pg, "#contenido tr[data-indice='1']", "una tras otra las opciones «Pagos», «Inventario»")
        self.esperar_texto(pg, "#contenido tr[data-indice='1']", "para cada opción")
        # el paso de después ofrece «Aquí termina…»
        pg.locator("#contenido tr[data-indice='2'] button:has-text('Editar')").click()
        pg.check(".modal input[data-fin-bucle]")
        pg.click(".modal button:has-text('Aceptar')")
        self.esperar_texto(pg, "#contenido tr[data-indice='2']", "aquí termina «para cada opción»")
        pg.click("#contenido .barra-herr button.primario:has-text('Guardar')")
        pg.wait_for_function("() => document.querySelector('#subtitulo').textContent.includes('guardado')", timeout=10000)
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual((fl.pasos[1].estrategia, fl.pasos[1].valores), ("marcadas", ["Pagos", "Inventario"]))
        self.assertTrue(fl.pasos[2].fin_bucle)
        self.assertIsNone(fl.opciones.get("repetir_dias"))
        self.assertNotIn("al_terminar", fl.opciones)
        self.assertEqual(self.errores, [])


if __name__ == "__main__":
    unittest.main()
