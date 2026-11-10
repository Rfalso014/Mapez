"""Pruebas de integración de la versión 3.3, con navegador OCULTO y el sitio de prueba.

«Mapear página» en webs que no son Portal (por la API de la interfaz, como lo usa el usuario: abre la dirección, el
usuario navega a mano y pulsa «Mapear»; aquí la propia página de prueba «navega como el usuario» con ?auto=1):
- `informes2_inicio.html?auto=1` → menú lateral → `informes2_historial.html` en la MISMA pestaña: etiquetas en celdas de
  tabla (sin <label>), fechas con bootstrap-datepicker, «Cuenta No.» con lupa y ventanita (se leen sus filas), lista
  nativa y «Ver Reporte» que abre el informe en OTRA pestaña; el desplegable del usuario de la barra no es un filtro.
  La Página creada desde el mapa se ejecuta y guarda el informe (CSV).
- `erp2_inicio.html?auto=1`: la consulta está DENTRO de un iframe (#tab0_Frame), con una lista de DevExpress, una fecha
  de DevExpress y el menú «Consultar» / «Vista Exportar» → «Exportar»: la Página se ejecuta dentro del marco y descarga.
- `nueva_pestana.html?auto=1`: el reporte se abre en una pestaña nueva antes de mapear: se mapea esa (y se puede elegir
  la otra).
- `sin_filtros.html` y `login.html`: mensaje claro y diagnóstico en registros/mapas/.
- `control_roto.html`: un control que falla al analizarlo no estropea el mapa.
Varias vigilancias (`portal.html`): la misma lista «Elegir corte» vigilada con dos reportes distintos; cada una ve su
novedad y descarga lo suyo una vez («Revisar todas» por la API y `--vigilancia-id` por línea de comandos); la página
Vigilancia muestra las tarjetas y «Añadir vigilancia» crea otra con valores.
Base de datos temporal, contraseñas en memoria, sin notificaciones de Windows ni tareas programadas.
"""

import contextlib
import datetime
import io
import json
import os
import sys
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from servidor_prueba import CORTE_NUEVO, ServidorPrueba  # noqa: E402
from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from test_servidor_ui import BaseApi  # noqa: E402
from webbot import paginas  # noqa: E402


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class BaseMapeo(BaseApi):
    @classmethod
    def setUpClass(cls):
        cls.web = ServidorPrueba().iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def setUp(self):
        super().setUp()
        self.web.estado["descargas"].clear()
        self.alm.guardar_ajustes({"timeout_paso": 15, "pausa_entre_pasos": 0})

    # ------------------------------------------------------------ utilidades
    def abrir(self, pagina):
        """«Mapear página» desde una dirección: abre el navegador (oculto en las pruebas) y espera a que esté listo."""
        self.api("POST", "mapa/iniciar", {"url": self.web.url_base + pagina})
        fin = time.monotonic() + 60
        while not (self.app.sesion_mapa and self.app.sesion_mapa.listo.is_set()) and time.monotonic() < fin:
            time.sleep(0.2)
        self.assertTrue(self.app.sesion_mapa.listo.is_set())
        self.addCleanup(self.terminar)

    def terminar(self):
        s = self.app.sesion_mapa
        if s is not None and not s.terminada.is_set():
            self.llamar("POST", "api/mapa/terminar", {})
            s.terminada.wait(30)

    def esperar_pestanas(self, condicion, segundos=20):
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            p = self.api("POST", "mapa/pestanas", {})["pestanas"]
            if condicion(p):
                return p
            time.sleep(0.3)
        self.fail("las pestañas no llegaron a lo esperado: %s" % p)

    def lanzar(self, ruta, datos):
        desde = self.app.eventos.ultimo
        t = self.api("POST", ruta, datos)
        fin, eventos = self.esperar_trabajo(t["id"], timeout=180)
        return fin, [e for e in eventos if e["seq"] > desde]

    def crear_pagina(self, m, accion, nombre):
        """«Guardar como Página…» por la API (como el botón de la interfaz)."""
        prop = self.api("POST", "mapa/propuesta", {"filtros": m["filtros"], "url": m["url"]})
        r = self.api("POST", "paginas", {"nombre": nombre, "filtros": m["filtros"], "url": m["url"], "accion": accion,
                                         "incluir": [f["k"] for f in prop["filtros"]],
                                         "nombres": {str(f["k"]): f["nombre"] for f in prop["filtros"]}})
        return r["id"], prop

    def ejecutar_pagina(self, pid, seleccion):
        self.terminar()                          # (un trabajo con navegador cada vez: se cierra el del mapeo)
        fin, eventos = self.lanzar("paginas/%d/ejecutar" % pid, {"seleccion": seleccion, "sin_navegador": True})
        self.assertEqual(fin["estado"], "ok", fin)
        return [a for e in eventos if e["tipo"] == "resultado" for a in e["archivos"]]

    def ids(self, pid):
        return {f["nombre"]: f for f in self.alm.obtener_pagina(pid)["data"]["filtros"]}

    @staticmethod
    def por_etiqueta(m):
        return {f["etiqueta"]: f for f in m["filtros"]}


class TestMapeoInformes(BaseMapeo):
    def test_menu_en_la_misma_pestana_celdas_de_tabla_busqueda_y_ver_reporte(self):
        self.abrir("informes2_inicio.html?auto=1")
        self.esperar_pestanas(lambda p: p[0]["url"].endswith("informes2_historial.html"))
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        self.assertTrue(m["url"].endswith("informes2_historial.html"), m["url"])
        por = self.por_etiqueta(m)
        self.assertEqual({k: f["tipo"] for k, f in por.items()},
                         {"Fecha Inicial": "fecha", "Fecha Final": "fecha", "Cuenta No.": "texto", "Localidad": "lista_nativa",
                          "Ver Reporte": "accion"})                          # el desplegable del usuario no es un filtro
        self.assertEqual(m["avisos"], [])
        self.assertTrue(por["Cuenta No."]["busqueda"]["selectores"])
        self.assertEqual(por["Localidad"]["opciones"], ["Todos", "Zona Capital", "Santiago"])
        # «Leer opciones de la búsqueda»: abre la ventanita, lee la tabla y la cierra
        b = self.api("POST", "mapa/busqueda", {"k": por["Cuenta No."]["k"]})
        cuenta = self.por_etiqueta(b)["Cuenta No."]
        self.assertEqual(cuenta["opciones"], ["1110209 · Asociacion Ejemplo", "2220301 · Banco Uno Corriente",
                                              "3330402 · Banco Dos Ahorros"])
        m["filtros"] = b["filtros"]
        prop = self.api("POST", "mapa/propuesta", {"filtros": m["filtros"], "url": m["url"]})
        self.assertEqual((prop["accion"]["tipo"], prop["accion"]["pestana"]), ("guardar_pagina", 1))
        self.assertEqual([p["url"] for p in prop["llegada"]], [m["url"]])
        pid, _p = self.crear_pagina(m, {"tipo": "guardar_pagina", "generar_k": por["Ver Reporte"]["k"], "formato": "csv",
                                        "pestana": 1}, "Informes – Historial")
        i = self.ids(pid)
        self.assertEqual(i["Cuenta No."]["busqueda"]["filas"][1], ["2220301", "Banco Uno Corriente"])
        form = {f["nombre"]: f for f in self.api("POST", "paginas/%d/formulario" % pid, {"seleccion": {}})["filtros"]}
        self.assertEqual(len(form["Cuenta No."]["opciones_busqueda"]), 3)
        archivos = self.ejecutar_pagina(pid, {i["Fecha Inicial"]["id"]: {"valor": "2026-10-05"},
                                              i["Cuenta No."]["id"]: {"valor": "2220301 · Banco Uno Corriente"},
                                              i["Localidad"]["id"]: {"estrategia": "fija", "valor": "Santiago"}})
        self.assertEqual(len(archivos), 1)
        self.assertTrue(archivos[0].endswith(".csv"), archivos)
        with open(archivos[0], encoding="utf-8-sig") as fh:
            texto = fh.read()
        self.assertIn("2220301 Santiago,2026-10-05", texto)
        # «Guardar el mapa» también funciona con una página a la que se llegó a mano
        self.api("POST", "mapa/guardar", {"url": m["url"], "alcance": "todo", "filtros": m["filtros"]})
        self.assertEqual(len(self.alm.mapas(None)), 1)
        with open(self.alm.historial(pagina_id=pid)[0]["registro"], encoding="utf-8") as fh:
            self.assertIn("Clic en «2220301»", fh.read())

    def test_ver_reporte_como_imagen(self):
        self.abrir("informes2_historial.html?imagen=1")
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        ver = self.por_etiqueta(m)["Ver Reporte"]
        self.assertEqual(ver["tipo"], "accion")                    # <input type=image alt="Ver Reporte">
        self.assertIn("#MainContent_ibtnList", ver["selectores"])


class TestMapeoErp(BaseMapeo):
    def test_formulario_dentro_de_un_iframe_con_devexpress(self):
        self.abrir("erp2_inicio.html?auto=1")
        fin = time.monotonic() + 20
        m = {"filtros": []}
        while time.monotonic() < fin and "Almacén" not in self.por_etiqueta(m):
            time.sleep(0.5)
            m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        por = self.por_etiqueta(m)
        self.assertEqual({k: (f["tipo"], f["marco"]) for k, f in por.items() if k != "Vista Exportar"},
                         {"Almacén": ("lista", ["#tab0_Frame"]), "Fecha de corte": ("fecha", ["#tab0_Frame"]),
                          "Consultar": ("accion", ["#tab0_Frame"])})
        self.assertEqual(por["Almacén"]["opciones"], ["Central", "Santiago", "Este"])
        self.assertTrue(por["Vista Exportar"]["submenu"])
        prop = self.api("POST", "mapa/propuesta", {"filtros": m["filtros"], "url": m["url"]})
        self.assertEqual(prop["accion"]["tipo"], "menu_exportar")
        self.assertEqual(prop["accion"]["generar"]["marco"], ["#tab0_Frame"])
        # «Guardar el mapa» con filtros de un marco
        self.api("POST", "mapa/guardar", {"url": m["url"], "alcance": "todo", "filtros": m["filtros"]})
        self.assertEqual(self.alm.mapas(None)[0]["filtros"][0]["marco"], ["#tab0_Frame"])
        # la Página: abre el ERP, llega a la consulta (el iframe) y pone los filtros DENTRO del marco
        llegada_auto = [{"tipo": "abrir_url", "url": self.web.url_base + "erp2_inicio.html?auto=1"},
                        {"tipo": "esperar_elemento", "selectores": ["#ctl00_formContent_cbAlmacen"], "marco": ["#tab0_Frame"]}]
        r = self.api("POST", "paginas", {"nombre": "ERP – Existencias", "filtros": m["filtros"], "url": m["url"],
                                         "llegada": llegada_auto, "accion": {"tipo": "menu_exportar",
                                                                            "generar_k": por["Consultar"]["k"],
                                                                            "menu_texto": "Vista Exportar",
                                                                            "exportar_texto": "Exportar"}})
        i = self.ids(r["id"])
        self.assertEqual(i["Almacén"]["marco"], ["#tab0_Frame"])
        archivos = self.ejecutar_pagina(r["id"], {i["Almacén"]["id"]: {"estrategia": "fija", "valor": "Santiago"},
                                                  i["Fecha de corte"]["id"]: {"valor": "20/10/2026"}})
        self.assertEqual(self.web.estado["descargas"][-1], "ERP Santiago 20/10/2026")
        self.assertEqual(len(archivos), 1)


class TestMapeoPestanaNueva(BaseMapeo):
    def test_el_reporte_se_abre_en_otra_pestana_antes_de_mapear(self):
        self.abrir("nueva_pestana.html?auto=1")
        p = self.esperar_pestanas(lambda p: len(p) == 2 and p[1]["url"].endswith("informes2_historial.html"))
        self.assertTrue(p[1]["activa"])
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        self.assertEqual(m["pestana"], 1)
        por = self.por_etiqueta(m)
        self.assertNotIn("Idioma", por)                                 # no la pestaña del portal
        self.assertEqual(por["Fecha Inicial"]["pagina"], 1)
        # la otra pestaña también se puede elegir
        m0 = self.api("POST", "mapa/mapear", {"alcance": "todo", "pestana": 0})
        self.assertIn("Idioma", self.por_etiqueta(m0))
        m = self.api("POST", "mapa/mapear", {"alcance": "todo", "pestana": 1})
        pid, prop = self.crear_pagina(m, {"tipo": "guardar_pagina", "generar_k": por["Ver Reporte"]["k"], "formato": "csv",
                                          "pestana": 1}, "Historial (pestaña nueva)")
        self.assertEqual(prop["accion"]["pestana"], 1)                  # la Página abre el formulario en la 1.ª pestaña
        self.assertEqual({f["pagina"] for f in self.alm.obtener_pagina(pid)["data"]["filtros"]}, {0})
        archivos = self.ejecutar_pagina(pid, {})
        self.assertEqual(len(archivos), 1)
        with open(archivos[0], encoding="utf-8-sig") as fh:
            self.assertIn(datetime.date.today().strftime("%Y-%m-%d"), fh.read())     # fecha por defecto: {hoy}


class TestMapeoSinFiltros(BaseMapeo):
    def test_pagina_sin_filtros_explica_y_guarda_diagnostico(self):
        self.abrir("sin_filtros.html")
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        self.assertEqual(m["filtros"], [])
        self.assertIn("No se encontró ningún control de formulario", m["avisos"][0])
        carpeta = m["diagnostico"]
        self.assertTrue(carpeta.startswith(os.path.join(self.tmp, "registros", "mapas")), carpeta)
        self.assertEqual(sorted(os.listdir(carpeta)), ["LEEME.txt", "captura.png", "diagnostico.json"])
        with open(os.path.join(carpeta, "diagnostico.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        self.assertTrue(d["url"].endswith("sin_filtros.html"))
        self.assertEqual(d["pestanas"][0]["url"], d["url"])
        self.terminar()
        registros = os.path.join(self.tmp, "registros")
        logs = [x for x in os.listdir(registros) if x.endswith(".log")]
        with open(os.path.join(registros, logs[0]), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("Mapear toda la página: pestaña 1 de 1", log)
        self.assertIn("diagnóstico del mapa guardado en", log)

    def test_pagina_de_inicio_de_sesion(self):
        self.abrir("login.html")
        self.api("POST", "mapa/pestanas", {})
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        self.assertIn("inicio de sesión", m["avisos"][0])
        with open(os.path.join(m["diagnostico"], "diagnostico.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        clave = [c for doc in d["controles"] for c in doc["controles"] if c.get("tipo") == "password"]
        self.assertTrue(clave)
        self.assertFalse([c for c in clave if "valor" in c])            # nunca el valor de una contraseña


class TestMapeoControlRoto(BaseMapeo):
    def test_un_control_que_falla_no_estropea_el_mapa(self):
        self.abrir("control_roto.html")
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        por = self.por_etiqueta(m)
        self.assertEqual({k: f["tipo"] for k, f in por.items()},
                         {"Almacén": "lista_nativa", "Fecha de corte": "fecha", "Descargar": "accion"})
        self.assertEqual([e["control"] for e in m["errores"]], ["input#roto"])
        self.assertIn("componente roto", m["errores"][0]["error"])
        self.assertTrue(any("no se pudieron analizar" in a for a in m["avisos"]))
        self.assertTrue(os.path.isdir(m["diagnostico"]))
        prop = self.api("POST", "mapa/propuesta", {"filtros": m["filtros"], "url": m["url"]})
        self.assertEqual(prop["accion"]["tipo"], "descargar")
        pid, _p = self.crear_pagina(m, {"tipo": "descargar", "generar_k": por["Descargar"]["k"]}, "Consulta rota")
        i = self.ids(pid)
        archivos = self.ejecutar_pagina(pid, {i["Almacén"]["id"]: {"estrategia": "fija", "valor": "Este"},
                                              i["Fecha de corte"]["id"]: {"valor": "01/10/2026"}})
        self.assertEqual(self.web.estado["descargas"][-1], "ERP Este 01/10/2026")
        self.assertEqual(len(archivos), 1)


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestVariasVigilanciasPortal(BaseApi):
    @classmethod
    def setUpClass(cls):
        from test_integracion_v32 import mapear
        cls.web = ServidorPrueba().iniciar()
        cls.url = cls.web.url_base + "portal.html?ms=200&boton=1"
        cls.mapa, cls.error_mapa = mapear(cls.url, dependencias=True)

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def setUp(self):
        super().setUp()
        self.assertIsNotNone(self.mapa, self.error_mapa)
        self.web.estado.update(nuevo_corte=False)
        self.web.estado["descargas"].clear()
        self.addCleanup(self.web.estado.update, {"nuevo_corte": False})
        m = self.mapa
        data, k = paginas.desde_mapa(m["filtros"], url=self.url, dependencias=m["dependencias"])
        data["opciones"].update(pausa_entre_pasos=0, timeout_paso=10)
        lect = paginas.lecturas_de_mapa(m["filtros"], k) + [
            (k[int(x["k"])], x["opciones"], {k[int(a)]: b for a, b in x["padres"].items() if int(a) in k})
            for x in m["lecturas"] if int(x["k"]) in k]
        self.pid, _n = paginas.guardar_nueva(self.alm, "Portal (prueba)", data, lect)
        self.ids = {f["nombre"]: f["id"] for f in data["filtros"]}

    def lanzar(self, ruta, datos):
        desde = self.app.eventos.ultimo
        t = self.api("POST", ruta, datos)
        fin, eventos = self.esperar_trabajo(t["id"], timeout=240)
        return fin, [e for e in eventos if e["seq"] > desde]

    def crear(self, reporte, nombre=""):
        return self.api("POST", "vigilancias", {
            "pagina_id": self.pid, "filtro": self.ids["Elegir corte"], "auto_descargar": True, "nombre": nombre,
            "valores": {self.ids["Seleccione reporte"]: {"estrategia": "fija", "valor": reporte}}})["vigilancia"]["id"]

    def test_misma_lista_con_dos_reportes_cada_una_descarga_lo_suyo(self):
        v1 = self.crear("Detalles Ventas Mayorista")
        v2 = self.crear("Resumen de Ventas", nombre="Ventas")
        fin, _ev = self.lanzar("vigilancias/revisar", {})                 # «Revisar todas»: la referencia
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(fin["resumen"].count("primera revisión"), 2, fin["resumen"])
        self.assertEqual(self.web.estado["descargas"], [])
        self.web.estado["nuevo_corte"] = True             # llega el corte semanal 45 y el mensual «Octubre 2026»
        fin, eventos = self.lanzar("vigilancias/revisar", {})
        self.assertEqual(fin["estado"], "ok", fin)
        nuevas = {e["vigilancia_id"]: e["nuevas"] for e in eventos if e["tipo"] == "vigilancia"}
        self.assertEqual(nuevas, {v1: [CORTE_NUEVO], v2: ["Octubre 2026"]})
        self.assertEqual(sorted(self.web.estado["descargas"]), sorted([CORTE_NUEVO, "Octubre 2026"]))
        titulos = sorted(n["titulo"] for n in self.alm.notificaciones())
        self.assertEqual(titulos, ["Llegó un corte nuevo en «Portal (prueba)» (Detalles Ventas Mayorista): " + CORTE_NUEVO,
                                   "Llegó un periodo nuevo en «Portal (prueba)» (Ventas): Octubre 2026"])
        # la página Vigilancia: las dos, con su novedad ya descargada
        d = self.api("GET", "vigilancia")
        pag = next(x for x in d["paginas"] if x["id"] == self.pid)
        self.assertEqual([v["opciones"][0]["texto"] for v in pag["vigilancias"]], [CORTE_NUEVO, "Octubre 2026"])
        self.assertTrue(all(v["opciones"][0]["descargada"] for v in pag["vigilancias"]))
        # por línea de comandos, UNA vigilancia (la tarea programada): nada nuevo, no se descarga otra vez
        import bot
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = bot.principal(["--vigilancia-id", str(v2), "--db", self.alm.ruta, "--oculto",
                                    "--registros", os.path.join(self.tmp, "registros"),
                                    "--descargas", os.path.join(self.tmp, "descargas_cli"),
                                    "--carpeta-flujos", os.path.join(self.tmp, "fl")])
        self.assertEqual(codigo, 0, salida.getvalue())
        self.assertIn("[vigilancia %d]" % v2, salida.getvalue())
        self.assertIn("nada nuevo", salida.getvalue())
        self.assertEqual(len(self.web.estado["descargas"]), 2)

    def test_pagina_vigilancia_en_la_interfaz(self):
        from playwright.sync_api import sync_playwright
        self.crear("Detalles Ventas Mayorista")
        self.crear("Resumen de Ventas")
        errores = []
        with sync_playwright() as p:
            nav = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = nav.new_page()
                pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errores.append(str(e)))
                pg.goto(self.srv.url_con_token("vigilancia"), wait_until="load")
                pg.wait_for_selector("#contenido [data-pagina='vigilancia'] .vigilancia-tarjeta")
                self.assertEqual(pg.locator("#contenido .vigilancia-tarjeta").count(), 2)
                texto = pg.inner_text("#contenido")
                self.assertIn("Detalles Ventas Mayorista", texto)
                self.assertIn("Resumen de Ventas", texto)
                # «Añadir vigilancia»: la misma lista con otro reporte
                pg.locator("#contenido button[data-anadir^='pagina-']").first.click()     # (el de la tarjeta de la Página)
                sel = pg.locator(".modal [data-valores-vigilancia] select[data-filtro='%s']" % self.ids["Seleccione reporte"])
                sel.wait_for()
                opciones = sel.locator("option").all_inner_texts()
                self.assertIn("Resumen de Ventas", opciones)
                sel.select_option("Resumen de Ventas")
                pg.fill(".modal input[aria-label='Nombre de la vigilancia']", "Ventas (otra)")
                pg.click(".modal .pie button:has-text('Añadir vigilancia')")
                pg.wait_for_selector("#modal-fondo.oculto", state="attached")
                pg.wait_for_function("() => document.querySelectorAll('#contenido .vigilancia-tarjeta').length === 3")
            finally:
                nav.close()
        self.assertEqual(errores, [])
        nueva = self.alm.lista_vigilancias(pagina_id=self.pid)[-1]
        self.assertEqual((nueva["nombre"], nueva["filtro"]), ("Ventas (otra)", self.ids["Elegir corte"]))
        self.assertEqual(nueva["valores"], {self.ids["Seleccione reporte"]: {"estrategia": "fija", "valor": "Resumen de Ventas"}})


if __name__ == "__main__":
    unittest.main()
