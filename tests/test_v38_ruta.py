"""Pruebas de la v3.8 «La Ruta».

1. Motor: la estrategia «por_fecha» (coincide o falla, nunca baja otro) y los pasos sin valor (no se crean al mapear y se
   saltan al ejecutar, con su línea en el registro; un navegador oculto contra el sitio de prueba).
2. Interfaz (navegador oculto): la guía de inicio (también con 0 reportes), Páginas fuera del menú pero accesible, la lista
   de paradas tras mapear (X, Deshacer, «También encontré», vacíos) y el selector de fecha.

Base de datos temporal, contraseñas en memoria, avisos falsos; nunca se crean tareas de Windows.
"""

import datetime
import os
import shutil
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from webbot import avisos, filtros, mapeador, paginas, programador, secretos  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

CORTES = ["Corte 03/11/2026", "Corte 04/11/2026", "2026-11-05", "45 - 2026 (16/10/2026 - 22/10/2026)"]
FILTROS_MAPA = [
    {"k": 1, "tipo": "pestana", "etiqueta": "Reportes", "selectores": ["#p"], "activo": True, "orden": 1},
    {"k": 2, "tipo": "lista", "etiqueta": "Seleccione reporte", "selectores": ["#r"], "valor": "Ventas", "opciones": ["Ventas", "Cobros"], "orden": 2},
    {"k": 3, "tipo": "lista", "etiqueta": "Región", "selectores": ["#g"], "valor": "", "opciones": ["Norte", "Sur"], "orden": 3},
    {"k": 4, "tipo": "fecha", "etiqueta": "Desde", "selectores": ["#d"], "valor": "", "orden": 4},
    {"k": 5, "tipo": "casilla", "etiqueta": "Incluir anulados", "selectores": ["#a"], "marcado": True, "orden": 5},
    {"k": 6, "tipo": "accion", "etiqueta": "Exportar", "selectores": ["#e"], "descarga": True, "orden": 6}]


class TestPorFecha(unittest.TestCase):
    def test_coincide_con_la_fecha(self):
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "por_fecha", "04/11/2026"), 1)
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "por_fecha", "2026-11-04"), 1)
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "por_fecha", "05/11/2026"), 2)
        self.assertEqual(mod_flujo.elegir_indice(["4 de noviembre de 2026"], "por_fecha", "04.11.2026"), 0)

    def test_sin_esa_fecha_no_elige_otra(self):
        self.assertIsNone(mod_flujo.elegir_indice(CORTES, "por_fecha", "06/11/2026"))
        self.assertIsNone(mod_flujo.elegir_indice(["Noviembre 2026"], "por_fecha", "04/11/2026"))
        self.assertIsNone(mod_flujo.elegir_indice(CORTES, "por_fecha", "no es una fecha"))

    def test_dentro_de_un_periodo_y_antes_la_exacta(self):
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "por_fecha", "20/10/2026"), 3)
        self.assertEqual(mod_flujo.elegir_indice(["Semana (01/11/2026 - 07/11/2026)", "Corte 04/11/2026"], "por_fecha", "04/11/2026"), 1)

    def test_dia_mes_sin_adivinar(self):
        self.assertEqual(mod_flujo.fechas_en_texto("03/04/2026"), [datetime.date(2026, 4, 3)])
        self.assertEqual(mod_flujo.fechas_en_texto("11/25/2026"), [])

    def test_mas_reciente_no_cambia(self):
        self.assertEqual(mod_flujo.elegir_indice(CORTES[:2], "mas_reciente"), 1)

    def test_paso_filtros_y_pagina(self):
        p = Paso("elegir_opcion", selectores=["#c"], objetivo="Corte", estrategia="por_fecha", valor="{hoy:%d/%m/%Y}")
        self.assertEqual(p.problemas(), [])
        self.assertIn("fecha", p.descripcion())
        fl = Flujo(nombre="x", url="http://x/", pasos=[Paso("elegir_opcion", selectores=["#c"], objetivo="Corte", estrategia="mas_reciente")])
        lineas = filtros.guardar_predeterminado(fl, {"0": {"estrategia": "por_fecha", "valor": "{ayer:%d/%m/%Y}"}})
        self.assertEqual((fl.pasos[0].estrategia, fl.pasos[0].valor), ("por_fecha", "{ayer:%d/%m/%Y}"))
        self.assertEqual(len(lineas), 1)
        f = {"tipo": "lista", "nombre": "Corte", "selectores": ["#c"]}
        self.assertEqual(paginas.paso_de_filtro(f, {"estrategia": "por_fecha", "valor": "{hoy:%Y-%m-%d}"}).valor, "{hoy:%Y-%m-%d}")


class TestSinValor(unittest.TestCase):
    def test_que_pasos_no_tienen_valor(self):
        self.assertTrue(Paso("elegir_opcion", selectores=["#a"]).sin_valor())
        self.assertTrue(Paso("elegir_opcion", selectores=["#a"], estrategia="contiene", valor="  ").sin_valor())
        self.assertTrue(Paso("elegir_opcion", selectores=["#a"], estrategia="por_fecha").sin_valor())
        self.assertTrue(Paso("escribir", selectores=["#a"], fecha_directa=True).sin_valor())
        self.assertFalse(Paso("elegir_opcion", selectores=["#a"], estrategia="mas_reciente").sin_valor())
        self.assertFalse(Paso("clic", selectores=["#a"]).sin_valor())
        self.assertFalse(Paso("descargar", selectores=["#a"]).sin_valor())

    def test_no_bloquea_el_reporte(self):
        fl = Flujo(nombre="x", url="http://x/", pasos=[Paso("abrir_url", url="http://x/"), Paso("elegir_opcion", selectores=["#a"])])
        self.assertEqual(fl.problemas(), [])
        self.assertIn("Falta el texto de la opción", fl.pasos[1].problemas())       # (el editor lo sigue señalando)

    def test_al_mapear_no_genera_paso(self):
        pasos, usados = mapeador.generar_pasos(FILTROS_MAPA, [
            {"k": 2, "estrategia": "fija", "valor": "Ventas"}, {"k": 3, "estrategia": "fija", "valor": ""},
            {"k": 6, "modo": "descargar"}], con_filtros=True)
        self.assertEqual([p.objetivo for p in pasos], ["Seleccione reporte", "Exportar"])
        self.assertEqual([f["k"] for f in usados], [2, 6])

    def test_lista_por_fecha_al_mapear(self):
        p = mapeador.generar_pasos(FILTROS_MAPA, [{"k": 3, "estrategia": "por_fecha", "valor": "{hoy:%d/%m/%Y}"}])[0]
        self.assertEqual((p.estrategia, p.valor), ("por_fecha", "{hoy:%d/%m/%Y}"))
        with self.assertRaises(mapeador.ErrorMapeo):
            mapeador.generar_pasos(FILTROS_MAPA, [{"k": 3, "estrategia": "por_fecha", "valor": "{nada"}])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v38_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        avisos.usar_notificador(lambda t, x: None)
        self.addCleanup(avisos.usar_notificador, None)
        original = programador._ejecutar
        programador._ejecutar = lambda cmd: (_ for _ in ()).throw(AssertionError("schtasks de verdad: %s" % cmd))
        self.addCleanup(setattr, programador, "_ejecutar", original)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                                 carpeta_descargas=os.path.join(self.tmp, "d"), listar_tareas=lambda: [], oculto_forzado=True,
                                 ejecutar_tareas=lambda cmd: (0, "CORRECTO"), abrir_dialogo=lambda *a: None)
        self.addCleanup(self.app.detener)

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})

    def reporte_con_fecha(self, nombre="Ventas"):
        return self.alm.guardar(Flujo(nombre=nombre, url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"),
            Paso("escribir", selectores=["#d"], objetivo="Desde", filtro="Desde", fecha_directa=True, valor="{hoy:%d/%m/%Y}"),
            Paso("descargar", selectores=["#g"], objetivo="Exportar", nombre="{reporte}{ext}")]))


class TestApi(Base):
    def test_el_reporte_dice_sus_fechas(self):
        rid = self.reporte_con_fecha()
        f = self.api("GET", "reportes")["reportes"][0]["fechas"]
        self.assertEqual([(x["paso"], x["nombre"], x["valor"], x["lista"], x["formato"]) for x in f],
                         [(1, "Desde", "{hoy:%d/%m/%Y}", False, "%d/%m/%Y")])
        self.assertEqual(self.api("GET", "inicio")["reportes"][0]["fechas"][0]["paso"], 1)
        self.api("POST", "reportes/%d/filtros/predeterminado" % rid, {"elecciones": {"1": {"estrategia": "fija", "valor": "{ayer:%d/%m/%Y}"}}})
        self.assertEqual(self.alm.cargar_flujo(rid).pasos[1].valor, "{ayer:%d/%m/%Y}")
        self.assertTrue(self.alm.versiones(rid))                                    # con su copia anterior

    def test_guia_solo_en_la_aplicacion_y_una_vez(self):
        self.assertFalse(self.api("GET", "estado")["guia_pendiente"])
        self.app.guia_al_abrir = True
        self.assertTrue(self.api("GET", "estado")["guia_pendiente"])
        self.api("PUT", "ajustes", {"ajustes": {"guia_vista": True}})
        self.assertFalse(self.api("GET", "estado")["guia_pendiente"])


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestEjecucion(Base):
    def test_salta_vacios_y_falla_si_la_fecha_no_ha_salido(self):
        from webbot.ejecutor import Ejecutor
        pagina = os.path.join(self.tmp, "p.html")
        with open(pagina, "w", encoding="utf-8") as f:
            f.write('<select id="c"><option>Corte 03/11/2026</option><option>Corte 04/11/2026</option></select>'
                    '<select id="r"><option>Elegida</option><option>Otra</option></select>'
                    '<input id="t" value="sin tocar"><button id="b" onclick="document.title=\'pulsado\'">B</button>')
        url = "file:///" + pagina.replace("\\", "/")

        def correr(valor):
            fl = Flujo(nombre="x", url=url, pasos=[Paso("abrir_url", url=url),
                Paso("elegir_opcion", selectores=["#r"], objetivo="Región"),
                Paso("escribir", selectores=["#t"], objetivo="Texto"),
                Paso("elegir_opcion", selectores=["#c"], objetivo="Corte", estrategia="por_fecha", valor=valor),
                Paso("clic", selectores=["#b"], objetivo="B")])
            fl.opciones["esperar_carga"] = False
            ej = Ejecutor(fl, oculto=True, carpeta_registros=self.tmp, carpeta_descargas=self.tmp, carpeta_perfil=os.path.join(self.tmp, "perfil"))
            return ej.ejecutar()
        bien = correr("04/11/2026")
        self.assertTrue(bien.ok, bien.resumen())
        self.assertEqual((bien.sin_valor, bien.completados), (2, 3))
        self.assertIn("2 sin valor, saltados", bien.resumen())
        with open(bien.ruta_log, encoding="utf-8") as f:
            self.assertEqual(f.read().count("sin valor: se salta este paso"), 2)
        mal = correr("09/11/2026")
        self.assertFalse(mal.ok)
        self.assertIn("El reporte del 09/11/2026 todavía no ha salido", mal.error)
        self.assertEqual(mal.paso_fallido, 4)


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestInterfaz(Base):
    def setUp(self):
        super().setUp()
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)

    def navegador(self, ancho=1366, alto=768):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self.addCleanup(self._p.stop)
        nav = self._p.chromium.launch(channel="chrome", headless=True)
        self.addCleanup(nav.close)
        pg = nav.new_page(viewport={"width": ancho, "height": alto})
        self.errores = []
        pg.on("console", lambda m: self.errores.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: self.errores.append(str(e)))
        return pg

    def recorrer_guia(self, pg):
        vistos = []
        while True:
            vistos.append(pg.locator(".guia-globo strong").inner_text())
            r = pg.evaluate("""() => { const c = document.querySelector('.guia-globo').getBoundingClientRect();
                return c.left >= 0 && c.top >= 0 && c.right <= innerWidth && c.bottom <= innerHeight; }""")
            self.assertTrue(r, "el globo se sale de la pantalla en «%s»" % vistos[-1])
            b = pg.locator("[data-guia-siguiente]")
            fin = b.inner_text() == "Terminar"
            b.click()
            if fin:
                return vistos

    def test_guia_con_cero_reportes(self):
        self.app.guia_al_abrir = True
        pg = self.navegador()
        pg.goto(self.srv.url_con_token(), wait_until="load")
        pg.wait_for_selector(".guia-globo", timeout=15000)
        self.assertEqual(self.recorrer_guia(pg), ["Empieza aquí", "Con un clic lo bajas", "Elige de qué fecha", "Que se haga solo"])
        pg.wait_for_selector("#guia", state="detached")
        pg.wait_for_function("() => true")
        fin = 0
        while not self.alm.ajustes()["guia_vista"] and fin < 50:
            pg.wait_for_timeout(100)
            fin += 1
        self.assertTrue(self.alm.ajustes()["guia_vista"])
        self.assertEqual(self.errores, [])

    def test_guia_con_reportes_saltar_y_volver_a_verla(self):
        self.reporte_con_fecha()
        self.app.guia_al_abrir = True
        pg = self.navegador()
        pg.goto(self.srv.url_con_token(), wait_until="load")
        pg.wait_for_selector(".guia-globo", timeout=15000)
        pasos = pg.evaluate("() => window.__botGuia.pasos().map((p) => p.sel)")
        self.assertEqual(pasos, ['[data-guia="nuevo"]', ".fila-rep [data-ejecutar]", "[data-chip-fecha]", "[data-programar]"])
        pg.click("[data-guia-saltar]")
        pg.wait_for_selector("#guia", state="detached")
        pg.click("#contenido [data-ver-guia]")
        pg.wait_for_selector(".guia-globo")
        pg.keyboard.press("Escape")                                     # Esc = saltar
        pg.wait_for_selector("#guia", state="detached")
        pg.evaluate("() => { location.hash = '#/ajustes'; }")
        pg.click("#contenido [data-pagina='ajustes'] [data-ver-guia]", timeout=15000)
        pg.wait_for_selector(".guia-globo", timeout=10000)
        self.assertEqual(pg.evaluate("() => location.hash"), "#/inicio")
        pg.set_viewport_size({"width": 900, "height": 600})             # se recoloca
        pg.wait_for_timeout(500)
        self.assertTrue(pg.evaluate("""() => { const c = document.querySelector('.guia-globo').getBoundingClientRect();
            return c.right <= innerWidth && c.left >= 0; }"""))
        self.assertEqual(self.errores, [])

    def test_la_guia_no_sale_sola_en_las_pruebas(self):
        pg = self.navegador()
        pg.goto(self.srv.url_con_token(), wait_until="load")
        pg.wait_for_selector("#contenido [data-guia='nuevo']", timeout=15000)
        self.assertEqual(pg.locator("#guia").count(), 0)

    def test_menu_con_textos_y_paginas_fuera_pero_accesibles(self):
        pid, _ = paginas.guardar_nueva(self.alm, "Portal", {
            "url": "http://127.0.0.1/", "llegada": [Paso("abrir_url", url="http://127.0.0.1/").a_dict()],
            "filtros": [{"id": "f1", "tipo": "lista", "nombre": "Corte", "selectores": ["#c"], "defecto": {"estrategia": "fija", "valor": "45 - 2026"}}],
            "accion": {"tipo": "descargar", "generar": {"selectores": ["#e"], "objetivo": "Exportar"}}})
        pg = self.navegador()
        pg.goto(self.srv.url_con_token(), wait_until="load")
        pg.wait_for_selector("#contenido [data-guia='nuevo']", timeout=15000)
        textos = [x.strip() for x in pg.locator("#menu a").all_inner_texts()]
        self.assertEqual(textos, ["Inicio", "Reportes", "Vigilancia", "Correo", "Historial", "Ajustes", "Mapear", "Grabar", "Accesos"])
        self.assertEqual(pg.locator("#menu a[data-ruta='paginas']").count(), 0)
        self.assertEqual(pg.locator("#menu a[data-ruta='inicio'].activo").count(), 1)
        self.assertEqual(pg.locator("#contenido button:has-text('Usar una página')").count(), 0)
        self.assertFalse(any(o.startswith("Ir a Páginas") for o in pg.evaluate("() => window.__botPaleta.opciones().map((o) => o.texto)")))
        pg.evaluate("() => { location.hash = '#/paginas'; }")          # la dirección vieja lleva a Reportes
        zona = "#contenido [data-paginas-guardadas] li[data-pagina-id='%d']" % pid
        pg.wait_for_selector(zona, timeout=15000)
        pg.click(zona + " button:has-text('Abrir')")
        pg.wait_for_selector("#contenido .pagina-form", timeout=15000)
        self.assertEqual(pg.locator("#menu a[data-ruta='reportes'].activo").count(), 1)
        pg.click("#contenido button:has-text('Reportes')")
        pg.wait_for_selector(zona, timeout=15000)
        self.assertEqual(self.errores, [])

    def mapear(self, pg, filtros_mapa=None):
        def estado(route):
            r = route.fetch()
            d = r.json()
            d["mapeando"] = True
            route.fulfill(response=r, json=d)
        pg.route("**/api/estado", estado)
        pg.route("**/api/mapa/mapear", lambda route: route.fulfill(json={
            "filtros": filtros_mapa or FILTROS_MAPA, "url": "http://127.0.0.1/reportes", "pestana": 0, "pestanas": [], "avisos": []}))
        pg.route("**/api/mapa/guardar", lambda route: route.fulfill(json={"ok": True}))
        pg.goto(self.srv.url_con_token("mapear"), wait_until="load")
        pg.click("#contenido button:has-text('Mapear toda la página')", timeout=15000)
        pg.wait_for_selector("#contenido [data-paradas] .parada", timeout=15000)

    def test_paradas_x_deshacer_tambien_y_vacios(self):
        pg = self.navegador()
        self.mapear(pg)
        pg.wait_for_function("() => document.querySelector('[data-resumen-pasos]').textContent.includes('se saltará 1 vacío')")
        self.assertEqual(pg.locator("#contenido table").count(), 0)
        self.assertEqual(pg.locator("#contenido button:has-text('Guardar como Página')").count(), 0)
        self.assertEqual(pg.locator("#contenido [data-crear-pasos]").count(), 1)
        orden = lambda: pg.evaluate("() => [...document.querySelectorAll('[data-paradas] .parada')].map((x) => x.dataset.parada)")
        self.assertEqual(orden(), ["1", "2", "3", "4", "6"])            # la casilla no viene marcada por defecto
        self.assertEqual(pg.locator("[data-paradas] .parada.vacia").evaluate("x => x.dataset.parada"), "3")
        self.assertTrue(pg.locator(".parada[data-parada='3'] [data-sin-elegir]").is_visible())
        self.assertEqual(pg.inner_text("[data-cuenta-pasos]"), "4")
        # la X y «Deshacer»
        pg.click("[data-quitar='1']")
        self.assertEqual(orden(), ["2", "3", "4", "6"])
        self.assertEqual(pg.inner_text("[data-cuenta-pasos]"), "3")
        pg.click("[data-deshacer='1']")
        self.assertEqual(orden(), ["1", "2", "3", "4", "6"])
        # «También encontré»
        pg.click("[data-anadir-parada='5']")
        self.assertEqual(orden(), ["1", "2", "3", "4", "5", "6"])
        pg.click("[data-quitar='5']")
        self.assertEqual(pg.locator("[data-anadir-parada='5']").count(), 1)
        # quitar la pestaña y guardar: ni lo quitado ni lo vacío generan pasos
        pg.click("[data-quitar='1']")
        pg.click("[data-crear-pasos]")
        pg.wait_for_function("() => /#\\/editor\\/\\d+/.test(location.hash)", timeout=15000)
        rid = int(pg.evaluate("() => location.hash.split('/').pop()"))
        self.assertEqual([p.objetivo for p in self.alm.cargar_flujo(rid).pasos if p.tipo != "abrir_url"], ["Seleccione reporte", "Desde", "Exportar"])
        self.assertEqual(self.errores, [])

    def test_lo_secundario_va_a_tambien_encontre_por_grupos(self):
        extra = [dict(FILTROS_MAPA[1], k=7, etiqueta="Moneda", secundario=True, orden=7, grupo="Avanzado"),
                 dict(FILTROS_MAPA[3], k=8, etiqueta="Hasta", secundario=True, orden=8, grupo="Avanzado"),
                 dict(FILTROS_MAPA[1], k=9, etiqueta="Sucursal", secundario=True, orden=9)]
        pg = self.navegador()
        self.mapear(pg, FILTROS_MAPA + extra)
        self.assertEqual(pg.locator("[data-paradas] .parada[data-parada='7']").count(), 0)
        filas = pg.evaluate("() => [...document.querySelectorAll('[data-tambien] li')].map((x) => x.dataset.grupo ? 'G:' + x.dataset.grupo : x.querySelector('.nom').textContent)")
        self.assertEqual(filas, ["Incluir anulados", "Sucursal", "G:Avanzado", "Moneda", "Hasta"])
        pg.click("[data-anadir-parada='8']")
        self.assertEqual(pg.locator("[data-paradas] .parada[data-parada='8']").count(), 1)
        self.assertEqual(self.errores, [])

    def test_fecha_de_una_parada_y_del_chip(self):
        pg = self.navegador()
        self.mapear(pg)
        pg.click("[data-fecha-parada='4']")
        zona = ".modal [data-selector-fecha]"
        pg.wait_for_selector(zona)
        hoy = datetime.date.today()
        fmt = "%d/%m/%Y"
        baja = lambda n: pg.inner_text(zona + " [data-baja='%d'] em" % n)
        self.assertNotIn("null", pg.inner_text(zona))                   # (lo que no toca enseñar no sale como texto)
        self.assertEqual(baja(1), (hoy + datetime.timedelta(days=1)).strftime(fmt))
        self.assertEqual(pg.get_attribute(zona + " [data-opcion-fecha='hoy']", "aria-pressed"), "true")
        self.assertEqual(pg.get_attribute(zona + " [data-dia='%s']" % hoy.isoformat(), "aria-pressed"), "true")
        pg.click(zona + " [data-opcion-fecha='ayer']")
        self.assertEqual(baja(0), (hoy - datetime.timedelta(days=1)).strftime(fmt))
        pg.click(zona + " [aria-label='Mes siguiente']")
        pg.click(zona + " [aria-label='Mes anterior']")
        pg.click(zona + " [data-dia='%s']" % hoy.replace(day=15).isoformat())
        self.assertEqual(pg.get_attribute(zona + " [data-opcion-fecha='exacta']", "aria-pressed"), "true")
        self.assertEqual(baja(2), hoy.replace(day=15).strftime(fmt))
        pg.click(".modal .pie button:has-text('Aceptar')")
        self.assertIn(hoy.replace(day=15).strftime(fmt), pg.inner_text("[data-fecha-parada='4']"))
        self.assertEqual(self.errores, [])

    def test_chip_del_reporte_guarda_la_fecha(self):
        rid = self.reporte_con_fecha()
        rl = self.alm.guardar(Flujo(nombre="Cortes", url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"),
            Paso("elegir_opcion", selectores=["#c"], objetivo="Corte", filtro="Corte", estrategia="mas_reciente")]))
        pg = self.navegador()
        pg.goto(self.srv.url_con_token(), wait_until="load")
        chip = "#contenido [data-chip-fecha='%d']" % rid
        pg.wait_for_selector(chip, timeout=15000)
        self.assertIn("Fecha: el día de hoy", pg.inner_text(chip))
        pg.click(chip)
        pg.click(".modal [data-opcion-fecha='ayer']")
        pg.click(".modal .pie button:has-text('Guardar la fecha')")
        pg.wait_for_function("s => document.querySelector(s).textContent.includes('el día anterior')", arg=chip, timeout=10000)
        self.assertEqual(self.alm.cargar_flujo(rid).pasos[1].valor, "{ayer:%d/%m/%Y}")
        # la lista «la más reciente» no se convierte hasta que se elige
        chip2 = "#contenido [data-chip-fecha='%d']" % rl
        self.assertIn("la más reciente", pg.inner_text(chip2))
        self.assertEqual(self.alm.cargar_flujo(rl).pasos[1].estrategia, "mas_reciente")
        pg.click(chip2)
        self.assertEqual(pg.get_attribute(".modal [data-opcion-fecha='reciente']", "aria-pressed"), "true")
        pg.click(".modal [data-opcion-fecha='hoy']")
        pg.click(".modal .pie button:has-text('Guardar la fecha')")
        pg.wait_for_function("s => document.querySelector(s).textContent.includes('el día de hoy')", arg=chip2, timeout=10000)
        p = self.alm.cargar_flujo(rl).pasos[1]
        self.assertEqual((p.estrategia, p.valor), ("por_fecha", "{hoy:%d/%m/%Y}"))
        self.assertEqual(self.errores, [])

    def test_tren_en_la_barra_de_trabajo(self):
        pg = self.navegador()
        pg.goto(self.srv.url_con_token(), wait_until="load")
        pg.wait_for_selector("#contenido [data-guia='nuevo']", timeout=15000)
        self.assertEqual(pg.locator("#trabajo .via .tren").count(), 1)
        self.app.eventos.emitir("trabajo", trabajo="t1", estado="en_curso", tipo_trabajo="ejecutar", descripcion="Ejecutar «X»")
        self.app.eventos.emitir("progreso", trabajo="t1", i=1, estado="inicio", texto="Descargar", total=2)
        pg.wait_for_function("() => document.querySelector('#trabajo .tren').style.left === '100%'", timeout=10000)
        self.assertEqual(pg.locator("#contenido .fila-curso .via .tren").count(), 1)
        alturas = pg.evaluate("""() => ['#trabajo .via', '.fila-curso .via', '#trabajo .tren'].map((s) => document.querySelector(s).offsetHeight)""")
        self.assertEqual(alturas, [6, 6, 28])                           # la vía es una línea y el tren se ve entero
        self.assertEqual(self.errores, [])


if __name__ == "__main__":
    unittest.main()
