"""Pruebas de la versión 3.9: el menú lateral que se abre y se cierra (el reporte «rebotaba» en otros equipos).

Lo que contó el usuario (20/11/2026): en OTROS ordenadores el reporte del portal de pagos se quedaba dando vueltas
justo donde se abre la lista de comercios, «como si no distinguiera la página del menú de la izquierda».

Dos cosas, las dos reproducidas aquí con la página de prueba `pagos_menu.html`:

1. El paso «Clic en Consultas» es el acordeón del menú lateral: ABRE y CIERRA.  Donde el menú ya empieza abierto (otro
   tamaño de ventana, el navegador recuerda cómo estaba, otra página de entrada), ese clic lo CERRABA, el enlace del
   paso siguiente dejaba de verse y el bot se quedaba esperando (y la recuperación automática volvía a abrirlo y a
   cerrarlo).
2. El texto «Comprobante Fiscal» está dos veces: en el menú lateral y en una pestaña del cuerpo.  Un paso grabado
   sobre uno no debe pulsar el otro.

Navegador oculto, carpetas temporales, sin la base de datos real, sin red fuera del sitio de prueba.
"""

import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import BaseIntegracion  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

PAGINA = "pagos_menu.html"
# Selectores tal como los graba el bot en el menú lateral y en la pestaña del cuerpo
MENU = ['a:text-is("Consultas")', "#menuConsultas",
        "body:nth-of-type(1) > nav:nth-of-type(1) > div:nth-of-type(1) > a:nth-of-type(1)"]
ENLACE_MENU = ["#Statements_NCF", 'role=link[name="Comprobante Fiscal"]', 'a:text-is("Comprobante Fiscal")']
PESTANA = ["#tabNCF", 'a:text-is("Comprobante Fiscal")']


class BaseMenu(BaseIntegracion):
    def flujo(self, pasos, abierto=False, nombre="Pagos menú"):
        url = self.base + PAGINA + ("?menu=abierto" if abierto else "")
        f = Flujo(nombre=nombre, url=url)
        f.opciones.update(timeout_paso=8, timeout_descarga=20, pausa_entre_pasos=0)
        f.pasos = [Paso("abrir_url", url=url)] + pasos
        return f

    def pasos_del_reporte(self):
        """Lo que se grabó con el menú CERRADO: abrir «Consultas» y pulsar el enlace de dentro."""
        return [Paso("clic", selectores=MENU, objetivo="Consultas"),
                Paso("clic", selectores=ENLACE_MENU, objetivo="Comprobante Fiscal"),
                Paso("esperar_elemento", selectores=['#donde:has-text("desde el menú")']),
                Paso("descargar", selectores=["#ExcelButton"], objetivo="Excel", nombre="Pagos{ext}")]


class TestMenuLateralQueYaEstaAbierto(BaseMenu):
    def test_con_el_menu_cerrado_funciona(self):
        r = self.ejecutar(self.flujo(self.pasos_del_reporte()))
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual([os.path.basename(a) for a in r.archivos], ["Pagos.xls"])

    def test_con_el_menu_ya_abierto_no_se_cierra(self):
        """Antes: el clic cerraba el menú, el enlace desaparecía y el reporte se quedaba dando vueltas."""
        r = self.ejecutar(self.flujo(self.pasos_del_reporte(), abierto=True))
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertEqual([os.path.basename(a) for a in r.archivos], ["Pagos.xls"])
        self.assertIn("ya está abierto", log)                      # lo dice en el registro

    def test_el_paso_siguiente_desactivado_no_cuenta(self):
        """El paso que decide si hay que abrir el menú es el siguiente ACTIVO (los desactivados se saltan)."""
        pasos = self.pasos_del_reporte()
        pasos.insert(1, Paso("clic", selectores=["#noexiste"], objetivo="viejo", desactivado=True))
        r = self.ejecutar(self.flujo(pasos, abierto=True))
        self.assertTrue(r.ok, self.leer_log(r))


class TestMenuYPestanaConElMismoTexto(BaseMenu):
    """«Comprobante Fiscal» está en el menú lateral y en una pestaña del cuerpo: cada paso debe pulsar el suyo."""

    def pasos_hasta(self, selectores, desde):
        """Pulsa «Comprobante Fiscal» y comprueba, con un paso «esperar», cuál de los dos se pulsó."""
        return [Paso("clic", selectores=MENU, objetivo="Consultas"),
                Paso("clic", selectores=selectores, objetivo="Comprobante Fiscal"),
                Paso("esperar_elemento", selectores=['#donde:has-text("desde %s")' % desde])]

    def test_el_paso_del_menu_pulsa_el_del_menu(self):
        # el selector por texto es ambiguo (menú y pestaña): el bot tiene que quedarse con el del menú
        r = self.ejecutar(self.flujo(self.pasos_hasta(
            ['a:text-is("Comprobante Fiscal")', "#Statements_NCF"], "el menú")))
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertIn("había 2 elementos", log)              # y dice en el registro con cuál se quedó

    def test_el_paso_de_la_pestana_pulsa_la_pestana(self):
        r = self.ejecutar(self.flujo(self.pasos_hasta(
            ['a:text-is("Comprobante Fiscal")', "#tabNCF"], "la pestaña")))
        self.assertTrue(r.ok, self.leer_log(r))


if __name__ == "__main__":
    unittest.main()
