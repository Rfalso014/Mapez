"""Pruebas de integración de la versión 2.2 (navegador oculto + sitio local de prueba):

menús que solo se ven con el ratón encima (CSS :hover y tipo DevExpress con submenús aparte), la
recuperación automática del ejecutor y las listas con autocompletar (tipo Vuetify).
Nunca usan el ratón ni el teclado reales: el ratón es el de Playwright dentro del navegador oculto.
"""

import os
import sys
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion_v21 import BaseGrabacion  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

OBJETIVO = "Registro De Asistencia"
OPCION = "Detalles Ventas Mayorista"


class TestMenusConRaton(BaseGrabacion):
    def flujo_rapido(self, url, *pasos, timeout_paso=10):
        f = Flujo(nombre="Menú", url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=timeout_paso)
        f.pasos = [Paso("abrir_url", url=url)] + list(pasos)
        return f

    def test_css_graba_pasar_raton_y_reproduce(self):
        url = self.base + "menu_css.html"

        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#menu")
            pg.hover("ul.menu > li:nth-child(2) > a")                  # Inventario
            pg.wait_for_timeout(300)
            pg.hover("a:text-is('Movimientos')")
            pg.wait_for_timeout(300)
            pg.click("a:text-is('%s')" % OBJETIVO)
            pg.wait_for_selector("#resultado:has-text('Elegido')")
            pg.wait_for_timeout(300)

        flujo, _ = self.grabar(url, conducir)
        tipos = [p.tipo for p in flujo.pasos]
        self.assertEqual(tipos, ["abrir_url", "pasar_raton", "pasar_raton", "clic"], [p.descripcion() for p in flujo.pasos])
        inv, mov, clic = flujo.pasos[1:]
        self.assertTrue(inv.auto and mov.auto)
        self.assertEqual((inv.objetivo, mov.objetivo), ("Inventario", "Movimientos"))
        self.assertIn("Pasar el ratón sobre «Inventario»", inv.descripcion())
        self.assertEqual(clic.objetivo, OBJETIVO)
        # ida y vuelta por JSON y reproducción (sin recuperación: los pasos grabados bastan)
        f2 = Flujo.desde_json(flujo.a_json())
        self.assertTrue(f2.pasos[1].auto)
        self.opciones_rapidas(f2, timeout_paso=10, recuperacion_automatica=False)
        f2.pasos.append(Paso("esperar_texto", texto="Elegido: " + OBJETIVO))
        res = self.ejecutar(f2, nombre_perfil="perfil_css")
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))

    def test_dx_graba_pasar_raton_y_reproduce(self):
        url = self.base + "menu_dx.html"

        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#ctl00_menuPrincipal")
            pg.hover("#ctl00_menuPrincipal_DXI1_T span")               # Inventario
            pg.wait_for_timeout(350)
            pg.click("span:text-is('%s')" % OBJETIVO)
            pg.wait_for_selector("#resultado:has-text('Elegido')")
            pg.wait_for_timeout(300)

        flujo, _ = self.grabar(url, conducir)
        self.assertEqual([p.tipo for p in flujo.pasos], ["abrir_url", "pasar_raton", "clic"],
                         [p.descripcion() for p in flujo.pasos])
        raton = flujo.pasos[1]
        self.assertTrue(raton.auto)
        self.assertEqual(raton.selectores[0], "#ctl00_menuPrincipal_DXI1_T")
        f2 = Flujo.desde_json(flujo.a_json())
        self.opciones_rapidas(f2, timeout_paso=10, recuperacion_automatica=False)
        f2.pasos.append(Paso("esperar_texto", texto="Elegido: " + OBJETIVO))
        res = self.ejecutar(f2, nombre_perfil="perfil_dx")
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))

    def test_flujo_antiguo_solo_con_clics_se_recupera_css(self):
        f = self.flujo_rapido(self.base + "menu_css.html",
                              Paso("clic", selectores=['a:text-is("%s")' % OBJETIVO], objetivo=OBJETIVO),
                              Paso("esperar_texto", texto="Elegido: " + OBJETIVO))
        inicio = time.monotonic()
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        self.assertLess(time.monotonic() - inicio, 20)
        log = self.leer_log(res)
        self.assertIn("intentando abrir el menú pasando el ratón por «Inventario", log)
        self.assertIn("Movimientos", log)

    def test_flujo_antiguo_solo_con_clics_se_recupera_dx(self):
        f = self.flujo_rapido(self.base + "menu_dx.html",
                              Paso("clic", selectores=['.dxm-content span:text-is("%s")' % OBJETIVO], objetivo=OBJETIVO),
                              Paso("esperar_texto", texto="Elegido: " + OBJETIVO))
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        self.assertIn("intentando abrir el menú pasando el ratón por «Inventario»", self.leer_log(res))

    def test_sin_ids_se_exploran_los_menus(self):
        f = self.flujo_rapido(self.base + "menu_dx.html?sin_ids=1",
                              Paso("clic", selectores=['.dxm-content span:text-is("%s")' % OBJETIVO], objetivo=OBJETIVO),
                              Paso("esperar_texto", texto="Elegido: " + OBJETIVO))
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        self.assertIn("se prueban los menús", self.leer_log(res))

    def test_repetir_pasos_de_raton_anteriores(self):
        # El paso «pasar el ratón» se hizo, pero el submenú se cerró solo (la página se refrescó) y, sin ids
        # de DevExpress, no se sabe qué opción lo abre: se repite el paso de ratón anterior.
        f = self.flujo_rapido(self.base + "menu_dx.html?sin_ids=1&cerrar_ms=1200",
                              Paso("pasar_raton", selectores=[".dxm-main li:nth-child(2) .dxm-content"], objetivo="Inventario"),
                              Paso("esperar_segundos", segundos=1.5),
                              Paso("clic", selectores=['.dxm-popup span:text-is("%s")' % OBJETIVO], objetivo=OBJETIVO),
                              Paso("esperar_texto", texto="Elegido: " + OBJETIVO))
        res = self.ejecutar(f)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("intentando abrir el menú pasando el ratón por «Inventario»", log)
        self.assertNotIn("se prueban los menús", log)

    def test_sin_recuperacion_automatica_no_lo_encuentra(self):
        f = self.flujo_rapido(self.base + "menu_css.html",
                              Paso("clic", selectores=['a:text-is("%s")' % OBJETIVO], timeout=3), timeout_paso=3)
        f.opciones["recuperacion_automatica"] = False
        res = self.ejecutar(f)
        self.assertFalse(res.ok)
        self.assertNotIn("intentando abrir el menú", self.leer_log(res))

    def test_barra_modo_pasar_el_raton(self):
        url = self.base + "menu_css.html"

        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#menu")
            pg.get_by_role("button", name="Pasar el ratón").click()
            pg.hover("ul.menu > li:nth-child(2) > a")
            pg.click("ul.menu > li:nth-child(2) > a")               # marca, no hace clic en la página
            pg.wait_for_timeout(300)

        flujo, _ = self.grabar(url, conducir)
        self.assertEqual([p.tipo for p in flujo.pasos], ["abrir_url", "pasar_raton"])
        raton = flujo.pasos[1]
        self.assertFalse(raton.auto)
        self.assertEqual(raton.objetivo, "Inventario")


class TestAutocompletar(BaseGrabacion):
    def flujo(self, url, *pasos, timeout_paso=10):
        f = Flujo(nombre="Autocompletar", url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=timeout_paso)
        f.pasos = [Paso("abrir_url", url=url)] + list(pasos) + [
            Paso("clic", selectores=["#generar"]), Paso("esperar_texto", texto="Reporte: " + OPCION)]
        return f

    def test_grabacion_sin_escribir_y_etiqueta_mas_cuadro_en_un_solo_clic(self):
        url = self.base + "autocompletar.html"

        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#campo-reporte")
            pg.click("label.v-label")
            pg.click(".v-field__input")              # mismo campo, enseguida: se junta con el anterior
            pg.click("[role=option]:has-text('%s')" % OPCION)
            pg.wait_for_timeout(300)
            pg.click("#generar")
            pg.wait_for_selector("#resultado:has-text('Reporte:')")
            pg.wait_for_timeout(300)

        flujo, _ = self.grabar(url, conducir)
        activos = [p for p in flujo.pasos if not p.desactivado]
        self.assertEqual([p.tipo for p in activos], ["abrir_url", "clic", "clic", "clic"],
                         [p.descripcion() for p in flujo.pasos])
        self.assertFalse([p for p in activos if p.tipo == "escribir"])
        abrir_lista, opcion, generar = activos[1:]
        self.assertNotEqual(abrir_lista.objetivo, "Filtro por reporte")     # se quedó el clic en el cuadro
        self.assertEqual(opcion.objetivo, OPCION)
        self.assertEqual(generar.selectores[0], "#generar")
        f2 = Flujo.desde_json(flujo.a_json())
        self.opciones_rapidas(f2, timeout_paso=10)
        f2.pasos.append(Paso("esperar_texto", texto="Reporte: " + OPCION))
        res = self.ejecutar(f2, nombre_perfil="perfil_auto")
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))

    def test_escribir_con_el_valor_ya_puesto_no_espera(self):
        f = self.flujo(self.base + "autocompletar.html",
                       Paso("clic", selectores=[".v-field__input"]),
                       Paso("clic", selectores=['role=option[name="%s"]' % OPCION]),
                       Paso("escribir", selectores=["#input-12"], valor=OPCION, objetivo="Open"))
        inicio = time.monotonic()
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        self.assertLess(time.monotonic() - inicio, 15)
        self.assertIn("ya tenía el valor", self.leer_log(res))

    def test_etiqueta_y_cuadro_que_cierran_la_lista_se_recupera(self):
        f = self.flujo(self.base + "autocompletar.html?modo=alternar",
                       Paso("clic", selectores=["label.v-label"], objetivo="Filtro por reporte"),
                       Paso("clic", selectores=[".v-field__input"], objetivo="div"),
                       Paso("clic", selectores=['role=option[name="%s"]' % OPCION], objetivo=OPCION))
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        self.assertIn("clic de nuevo", self.leer_log(res))

    def test_escribir_en_la_lista_elige_la_opcion(self):
        # el campo no admite el ratón (pointer-events: none) → tras unos segundos se escribe igualmente
        # y se elige la opción con ese texto (si no, la web no se entera de la selección)
        f = self.flujo(self.base + "autocompletar.html",
                       Paso("escribir", selectores=["#input-12"], valor=OPCION, objetivo="Open"))
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        log = self.leer_log(res)
        self.assertIn("elegida la opción", log)


class TestLineaDeComandosConBaseDeDatos(BaseGrabacion):
    def test_reporte_guardado_en_la_aplicacion_por_nombre_e_id(self):
        import contextlib
        import io

        import bot
        from webbot.almacen import Almacen, nombre_perfil
        ruta_db = os.path.join(self.tmp, "bot.db")
        alm = Almacen(ruta_db)
        f = Flujo(nombre="Menú ERP", url=self.base + "menu_css.html")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=10)
        f.pasos = [Paso("abrir_url", url=self.base + "menu_css.html"),
                   Paso("pasar_raton", selectores=["ul.menu > li:nth-child(2) > a"], auto=True),
                   Paso("pasar_raton", selectores=['a:text-is("Movimientos")'], auto=True),
                   Paso("clic", selectores=['a:text-is("%s")' % OBJETIVO]),
                   Paso("esperar_texto", texto="Elegido: " + OBJETIVO)]
        rid = alm.guardar(f)
        alm.cerrar()
        perfiles = os.path.join(self.tmp, "perfiles")
        for args in (["--reporte", "Menú ERP"], ["--id", str(rid), "--id", str(rid)]):
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                codigo = bot.principal(args + ["--sin-ventana", "--oculto", "--db", ruta_db, "--registros", self.registros,
                                               "--carpeta-flujos", os.path.join(self.tmp, "flujos"),
                                               "--perfil", os.path.join(perfiles, nombre_perfil(rid))])
            self.assertEqual(codigo, 0, salida.getvalue())
            self.assertIn("Resultado: Terminado: 5 de 5 pasos", salida.getvalue())
        alm = Almacen(ruta_db)
        try:
            self.assertEqual([e["resultado"] for e in alm.historial(rid)], ["ok", "ok"])
        finally:
            alm.cerrar()


if __name__ == "__main__":
    unittest.main()
