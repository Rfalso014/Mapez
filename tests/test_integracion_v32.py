"""Pruebas de integración de la versión 3.2 («Páginas»), con navegador OCULTO y el sitio de prueba:

- `portal.html?boton=1` (como la web real: «Generar» y después el botón «Descargar», que se habilita al terminar;
  «Elegir corte» depende de «Seleccione reporte»): crear la Página desde un mapa por la API (llegada, filtros con
  nombre, dependencias detectadas en el navegador, acción adivinada), ejecutarla con valores elegidos (archivo y
  nombre), varias opciones = varias ejecuciones, opciones que se traen bajo pedido (y se guardan), favorito con «la
  más reciente», `--pagina/--favorito/--filtro`, vigilancia que marca «nueva» y descarga sola.
- Página que pide iniciar sesión, ejecutada sin abrir navegador: la pregunta llega igualmente a la interfaz.
- `informes.html` (fechas + lista nativa + «Ver Reporte» que abre el informe en otra pestaña → CSV) y
  `erp_consulta.html` (menú «Vista Exportar» → «Exportar» con el ratón encima).
- La interfaz: la lista de Páginas y el formulario se abren sin errores en la consola.
Base de datos temporal, contraseñas en memoria, sin notificaciones de Windows ni tareas programadas.
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from servidor_prueba import CORTE_NUEVO, ServidorPrueba, cortes_portal  # noqa: E402
from test_integracion import CLAVE, HAY_PLAYWRIGHT  # noqa: E402
from test_integracion_v23 import SECRETO, paso_login  # noqa: E402
from test_servidor_ui import BaseApi  # noqa: E402
from webbot import mapeador, paginas, secretos  # noqa: E402
from webbot.ejecutor import Ejecutor  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

REPORTE = "Detalles Ventas Mayorista"
CORTES = cortes_portal(REPORTE)
C44, C43, C42, C41, C40 = CORTES[-1], CORTES[-2], CORTES[-3], CORTES[-4], CORTES[-5]
MENSUALES = cortes_portal("Resumen de Ventas")


def mapear(url, dependencias=False):
    """Mapa de una página del sitio de prueba (navegador oculto); con `dependencias`, también las detecta."""
    tmp = tempfile.mkdtemp(prefix="botweb_mapa32_")
    try:
        f = Flujo(nombre="Mapa", url=url, pasos=[Paso("abrir_url", url=url)])
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=8)

        def al_final(ej, pg):
            filtros = mapeador.escanear(ej, pg)
            if dependencias:
                return mapeador.detectar_dependencias(ej, pg, filtros)
            return {"filtros": filtros, "dependencias": {}, "lecturas": []}
        res = Ejecutor(f, carpeta_perfil=os.path.join(tmp, "p"), carpeta_registros=tmp, oculto=True, pausa_entre_pasos=0,
                       al_final=al_final).ejecutar()
        return res.extra if res.ok else None, res.resumen()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestPaginasPortal(BaseApi):
    @classmethod
    def setUpClass(cls):
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

    # ------------------------------------------------------------ utilidades
    def crear_pagina(self, nombre="Portal (prueba)", lecturas=True):
        m = self.mapa
        data, k = paginas.desde_mapa(m["filtros"], url=self.url, dependencias=m["dependencias"])
        data["opciones"].update(pausa_entre_pasos=0, timeout_paso=10)
        lect = []
        if lecturas:
            lect = paginas.lecturas_de_mapa(m["filtros"], k) + [
                (k[int(x["k"])], x["opciones"], {k[int(a)]: b for a, b in x["padres"].items() if int(a) in k})
                for x in m["lecturas"] if int(x["k"]) in k]
        pid, _n = paginas.guardar_nueva(self.alm, nombre, data, lect)
        self.ids = {f["nombre"]: f["id"] for f in data["filtros"]}
        return pid

    def lanzar(self, ruta, datos, al_evento=None):
        desde = self.app.eventos.ultimo
        t = self.api("POST", ruta, datos)
        fin, eventos = self.esperar_trabajo(t["id"], timeout=180, al_evento=al_evento)
        return fin, [e for e in eventos if e["seq"] > desde]

    def form(self, pid, seleccion=None):
        v = self.api("POST", "paginas/%d/formulario" % pid, {"seleccion": seleccion or {}})
        return {f["nombre"]: f for f in v["filtros"]}

    @staticmethod
    def contenido(ruta):
        with open(ruta, encoding="utf-8") as fh:
            return fh.read()

    # ------------------------------------------------------------ pruebas
    def test_crear_pagina_desde_el_mapa_por_la_api(self):
        t = self.api("POST", "mapa/iniciar", {"url": self.url})
        fin = time.monotonic() + 60
        while not (self.app.sesion_mapa and self.app.sesion_mapa.listo.is_set()) and time.monotonic() < fin:
            time.sleep(0.2)
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        por = {f["etiqueta"]: f for f in m["filtros"]}
        self.assertIn("Descargar", por)                                  # botón deshabilitado hasta generar
        d = self.api("POST", "mapa/dependencias", {})
        self.assertEqual(d["dependencias"], {str(por["Elegir corte"]["k"]): [por["Seleccione reporte"]["k"]]})
        prop = self.api("POST", "mapa/propuesta", {"filtros": d["filtros"], "url": m["url"]})
        self.assertEqual([p["tipo"] for p in prop["llegada"]], ["abrir_url"])
        self.assertEqual(prop["accion"]["tipo"], "boton_descarga")
        self.assertEqual((prop["accion"]["generar"]["objetivo"], prop["accion"]["descargar"]["objetivo"]),
                         ("Generar", "Descargar"))
        self.assertNotIn("Open", [f["nombre"] for f in prop["filtros"]])
        accion = {"tipo": "boton_descarga", "generar_k": por["Generar"]["k"], "descargar_k": por["Descargar"]["k"]}
        r = self.api("POST", "paginas", {"nombre": "Portal – Reportes", "filtros": d["filtros"], "url": m["url"],
                                         "dependencias": d["dependencias"], "lecturas": d["lecturas"], "accion": accion,
                                         "llegada": prop["llegada"]})
        self.api("POST", "mapa/terminar", {})
        estado, _ = self.esperar_trabajo(t["trabajo"]["id"])
        self.assertEqual(estado["estado"], "ok", estado)
        v = self.api("GET", "paginas/%d" % r["id"])
        self.assertEqual(v["nombre"], "Portal – Reportes")
        nombres = [f["nombre"] for f in v["filtros"]]
        self.assertEqual(nombres, ["Pestaña", "Filtro por sistema", "Seleccione reporte", "Elegir corte",
                                   "Formato a Exportar"])
        por_n = {f["nombre"]: f for f in v["filtros"]}
        self.assertEqual(por_n["Elegir corte"]["depende_nombres"], ["Seleccione reporte"])
        self.assertEqual([o["texto"] for o in por_n["Pestaña"]["opciones"]], ["Corte", "Crédito y Cobros"])
        corte = por_n["Elegir corte"]
        self.assertEqual(corte["opciones"][0]["texto"], C44)                     # de la más reciente a la más antigua
        self.assertTrue(corte["opciones"][0]["mas_reciente"])
        self.assertEqual(corte["eleccion"], {"estrategia": "mas_reciente", "valor": ""})
        self.assertEqual(v["problemas"], [])
        self.assertTrue(v["sin_navegador"])
        self.assertEqual(v["accion_pasos"][-1][:10], "Descargar:")

    def test_generar_y_descargar_con_valores_y_varias(self):
        pid = self.crear_pagina()
        i = self.ids
        sel = {i["Seleccione reporte"]: {"estrategia": "fija", "valor": REPORTE},
               i["Elegir corte"]: {"estrategia": "fija", "valor": C42},
               i["Formato a Exportar"]: {"estrategia": "fija", "valor": "CSV"}}
        fin, eventos = self.lanzar("paginas/%d/ejecutar" % pid, {"seleccion": sel, "sin_navegador": True})
        self.assertEqual(fin["estado"], "ok", fin)
        res = [e for e in eventos if e["tipo"] == "resultado"][-1]
        self.assertEqual(len(res["archivos"]), 1)
        self.assertEqual(os.path.basename(res["archivos"][0]),
                         "Portal (prueba) - Portal - %s - %s.csv" % (REPORTE, C42.replace("/", "_")))
        self.assertIn(C42, self.contenido(res["archivos"][0]))
        self.assertEqual(self.web.estado["descargas"], [C42])                    # solo el botón «Descargar»
        self.assertIn("Página «Portal (prueba)»", self.contenido(res["registro"]))
        self.assertEqual(self.alm.historial(pagina_id=pid)[0]["resultado"], "ok")
        filas = [f for f in self.alm.opciones_pagina(pid, i["Elegir corte"]) if f["fuente"] == "ejecucion"]
        self.assertEqual(filas[0]["opciones"], CORTES)                            # la ejecución leyó la lista entera
        self.assertEqual(filas[0]["padres"][i["Seleccione reporte"]], REPORTE)
        # Wednesday: cortes 40, 41, 42 → 3 archivos (uno por corte)
        self.web.estado["descargas"].clear()
        sel[i["Elegir corte"]] = {"valores": [C40, C41, C42]}
        fin, eventos = self.lanzar("paginas/%d/ejecutar" % pid, {"seleccion": sel})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertIn("3 de 3 bien", fin["resumen"])
        archivos = sorted(os.path.basename(a) for e in eventos if e["tipo"] == "resultado" for a in e["archivos"])
        self.assertEqual(archivos, sorted("Portal (prueba) - Portal - %s - %s%s.csv" % (REPORTE, c.replace("/", "_"), x)
                                          for c, x in ((C40, ""), (C41, ""), (C42, " (2)"))))   # el 42 ya estaba
        self.assertEqual(self.web.estado["descargas"], [C40, C41, C42])
        self.assertEqual([e["n"] for e in eventos if e["tipo"] == "lote"], [1, 2, 3])
        self.assertEqual(len(self.alm.historial(pagina_id=pid)), 4)

    def test_opciones_bajo_demanda_y_actualizar(self):
        pid = self.crear_pagina()
        i = self.ids
        otro = {i["Seleccione reporte"]: {"estrategia": "fija", "valor": "Resumen de Ventas"}}
        corte = self.form(pid, otro)["Elegir corte"]
        self.assertTrue(corte["desconocida"])                                      # no se conocen sus cortes
        fin, eventos = self.lanzar("paginas/%d/traer" % pid, {"seleccion": otro, "filtro": i["Elegir corte"]})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(self.web.estado["descargas"], [])                          # no genera ni descarga nada
        self.assertTrue([e for e in eventos if e["tipo"] == "pagina_opciones" and e["ok"]])
        corte = self.form(pid, otro)["Elegir corte"]
        self.assertFalse(corte["desconocida"])
        self.assertEqual([o["texto"] for o in corte["opciones"]], list(reversed(MENSUALES)))
        fila = [f for f in self.alm.opciones_pagina(pid, i["Elegir corte"]) if f["fuente"] == "traer"][0]
        self.assertEqual(fila["padres"][i["Seleccione reporte"]], "Resumen de Ventas")
        self.assertEqual(self.form(pid)["Elegir corte"]["opciones"][0]["texto"], C44)   # la otra sigue igual
        # «Actualizar opciones»: llegó el corte 45
        self.web.estado["nuevo_corte"] = True
        fin, _ev = self.lanzar("paginas/%d/actualizar" % pid, {"seleccion": {}})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(self.form(pid)["Elegir corte"]["mas_reciente"], CORTE_NUEVO)

    def test_favorito_mas_reciente_y_linea_de_comandos(self):
        import bot
        pid = self.crear_pagina()
        i = self.ids
        self.api("POST", "paginas/%d/favoritos" % pid, {"nombre": "Mayorista", "seleccion": {
            i["Seleccione reporte"]: {"estrategia": "fija", "valor": REPORTE},
            i["Elegir corte"]: {"estrategia": "mas_reciente", "valor": ""},
            i["Formato a Exportar"]: {"estrategia": "fija", "valor": "CSV"}}})
        self.web.estado["nuevo_corte"] = True                                       # llegó el 45: «la más reciente»
        fin, eventos = self.lanzar("paginas/%d/ejecutar" % pid, {"favorito": "Mayorista"})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(self.web.estado["descargas"], [CORTE_NUEVO])
        archivo = [a for e in eventos if e["tipo"] == "resultado" for a in e["archivos"]][0]
        self.assertIn(CORTE_NUEVO.replace("/", "_"), os.path.basename(archivo))      # lo elegido de verdad
        # línea de comandos: --pagina + --favorito + --filtro
        self.web.estado["descargas"].clear()
        args = ["--db", self.alm.ruta, "--oculto", "--perfil", os.path.join(self.tmp, "perfil_cli"),
                "--registros", os.path.join(self.tmp, "registros"), "--descargas", os.path.join(self.tmp, "descargas_cli")]
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = bot.principal(args + ["--pagina", "Portal (prueba)", "--favorito", "Mayorista", "--filtro",
                                           "Elegir corte=" + C43])
        self.assertEqual(codigo, 0, salida.getvalue())
        self.assertEqual(self.web.estado["descargas"], [C43])
        self.assertEqual(os.listdir(os.path.join(self.tmp, "descargas_cli")),
                         ["Portal (prueba) - Portal - %s - %s.csv" % (REPORTE, C43.replace("/", "_"))])
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = bot.principal(args + ["--pagina-id", str(pid), "--filtro", "No existe=1"])
        self.assertEqual(codigo, 2)
        self.assertIn("No hay ningún filtro «No existe»", salida.getvalue())
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = bot.principal(args + ["--pagina", "Portal (prueba)", "--favorito", "Otro"])
        self.assertEqual(codigo, 2)

    def test_vigilancia_marca_nueva_y_descarga_sola(self):
        pid = self.crear_pagina()
        i = self.ids
        self.api("POST", "paginas/%d/favoritos" % pid, {"nombre": "Mayorista CSV", "seleccion": {
            i["Seleccione reporte"]: {"estrategia": "fija", "valor": REPORTE},
            i["Formato a Exportar"]: {"estrategia": "fija", "valor": "CSV"}}})
        self.api("PUT", "paginas/%d/vigilancia" % pid, {"filtro": i["Elegir corte"], "favorito": "Mayorista CSV",
                                                        "auto_descargar": True})
        fin, _ev = self.lanzar("paginas/%d/vigilancia/revisar" % pid, {})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertIn("primera revisión", fin["resumen"])
        self.assertEqual(self.web.estado["descargas"], [])
        self.web.estado["nuevo_corte"] = True
        fin, eventos = self.lanzar("paginas/%d/vigilancia/revisar" % pid, {})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual([e["nuevas"] for e in eventos if e["tipo"] == "vigilancia"], [[CORTE_NUEVO]])
        self.assertEqual(self.web.estado["descargas"], [CORTE_NUEVO])                # descargada una vez
        corte = self.form(pid)["Elegir corte"]
        self.assertTrue(corte["vigilado"])
        self.assertEqual((corte["opciones"][0]["texto"], corte["opciones"][0]["nueva"]), (CORTE_NUEVO, True))
        self.assertFalse(any(o["nueva"] for o in corte["opciones"][1:]))
        # v3.3: el aviso dice de qué vigilancia es (la del favorito «Mayorista CSV»)
        self.assertEqual(self.alm.notificaciones()[0]["titulo"],
                         "Llegó un corte nuevo en «Portal (prueba)» (Mayorista CSV): " + CORTE_NUEVO)
        self.assertEqual(self.alm.pendientes_pagina(pid, i["Elegir corte"]), [])
        fin, _ev = self.lanzar("paginas/%d/vigilancia/revisar" % pid, {})                # no se vuelve a descargar
        self.assertEqual(self.web.estado["descargas"], [CORTE_NUEVO])
        lista = self.api("GET", "vigilancia")["paginas"]
        self.assertEqual(lista[0]["opciones"][0]["texto"], CORTE_NUEVO)

    def test_pagina_en_la_interfaz(self):
        from playwright.sync_api import sync_playwright
        pid = self.crear_pagina()
        errores = []
        with sync_playwright() as p:
            nav = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = nav.new_page()
                pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errores.append(str(e)))
                pg.goto(self.srv.url_con_token("reportes"), wait_until="load")
                pg.wait_for_selector("#contenido [data-paginas-guardadas] li")
                self.assertIn("Portal (prueba)", pg.inner_text("#contenido"))
                pg.click("#contenido [data-paginas-guardadas] button:has-text('Abrir')")
                pg.wait_for_selector("#contenido .pagina-form .filtro")
                self.assertEqual(pg.locator("#contenido .pagina-form .filtro").count(), 5)
                sel = pg.locator("#contenido [data-filtro='%s'] select" % self.ids["Elegir corte"]).first
                self.assertEqual(sel.locator("option").first.inner_text(), "La más reciente (hoy: %s)" % C44)
                fondo = pg.locator("#sin-navegador-pagina")
                self.assertTrue(fondo.is_checked())
                self.assertIn("invisible", pg.get_attribute("label[for='sin-navegador-pagina']", "title"))
                self.assertIn("Generar y descargar", pg.inner_text("#contenido"))
                pg.click("#contenido details.config-pagina summary")
                pg.wait_for_selector("#contenido details.config-pagina[open] table")
            finally:
                nav.close()
        self.assertEqual(errores, [])


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestPaginasOtrasWebs(BaseApi):
    @classmethod
    def setUpClass(cls):
        cls.web = ServidorPrueba().iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def lanzar(self, ruta, datos, al_evento=None):
        desde = self.app.eventos.ultimo
        t = self.api("POST", ruta, datos)
        fin, eventos = self.esperar_trabajo(t["id"], timeout=180, al_evento=al_evento)
        return fin, [e for e in eventos if e["seq"] > desde]

    def test_inicio_de_sesion_preguntado_sin_abrir_navegador(self):
        base = self.web.url_base
        data = {"url": base + "app.html", "llegada": [Paso("abrir_url", url=base + "app.html").a_dict(), paso_login().a_dict()],
                "filtros": [], "accion": {"tipo": "guardar_pagina", "generar": {"selectores": ["#accion"], "objetivo": "Hacer acción"},
                                          "formato": "html", "pestana": 0},
                "nombre_archivo": "{pagina}", "opciones": {"pausa_entre_pasos": 0, "timeout_paso": 10}}
        pid, _n = paginas.guardar_nueva(self.alm, "App con login", data)
        self.app.oculto_forzado = None               # manda el interruptor: «Sin abrir navegador» = oculto
        contestadas = []

        def al_evento(ev):
            if ev["tipo"] == "pregunta":
                pend = self.api("GET", "preguntas")["preguntas"]
                self.assertEqual(pend[0]["solicitud"]["host"], "127.0.0.1")
                self.api("POST", "preguntas/" + ev["id"], {"respuesta": {"valores": {"clave": CLAVE}, "recordar": True}})
                contestadas.append(ev["id"])
        fin, eventos = self.lanzar("paginas/%d/ejecutar" % pid, {"seleccion": {}, "sin_navegador": True}, al_evento)
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(len(contestadas), 1)                    # la ventana de la contraseña sale en el bot
        self.assertEqual(secretos.obtener(SECRETO), CLAVE)
        res = [e for e in eventos if e["tipo"] == "resultado"][-1]
        self.assertEqual(os.path.basename(res["archivos"][0]), "App con login.html")
        with open(res["registro"], encoding="utf-8") as fh:
            self.assertIn("oculto", fh.read().splitlines()[0])

    def test_informes_fechas_lista_y_informe_en_otra_pestana(self):
        url = self.web.url_base + "informes.html"
        m, err = mapear(url)
        self.assertIsNotNone(m, err)
        tipos = {f["etiqueta"]: f["tipo"] for f in m["filtros"]}
        self.assertEqual((tipos["Fecha desde"], tipos["Fecha hasta"], tipos["Cuenta"], tipos["Ver Reporte"]),
                         ("fecha", "fecha", "lista_nativa", "accion"))
        gen = next(f for f in m["filtros"] if f["etiqueta"] == "Ver Reporte")
        data, _k = paginas.desde_mapa(m["filtros"], url=url, accion={
            "tipo": "guardar_pagina", "generar": {"selectores": gen["selectores"], "objetivo": "Ver Reporte"},
            "formato": "csv", "pestana": 1})
        data["opciones"].update(pausa_entre_pasos=0, timeout_paso=10)
        ids = {f["nombre"]: f["id"] for f in data["filtros"]}
        self.assertEqual(data["filtros"][0]["defecto"], {"valor": "{hoy:%d/%m/%Y}"})
        pid, nombre = paginas.guardar_nueva(self.alm, None, data)
        self.assertEqual(nombre, "Informes")
        fin, eventos = self.lanzar("paginas/%d/ejecutar" % pid, {"seleccion": {
            ids["Fecha desde"]: {"valor": "05/10/2026"}, ids["Fecha hasta"]: {"valor": "20/10/2026"},
            ids["Cuenta"]: {"estrategia": "fija", "valor": "Banco Tres 003"}}})
        self.assertEqual(fin["estado"], "ok", fin)
        archivo = [a for e in eventos if e["tipo"] == "resultado" for a in e["archivos"]][0]
        self.assertEqual(os.path.basename(archivo), "Informes - 05_10_2026 - 20_10_2026 - Banco Tres 003.csv")
        with open(archivo, encoding="utf-8-sig") as fh:
            texto = fh.read()
        self.assertIn("Banco Tres 003,05/10/2026,20/10/2026", texto)

    def test_erp_menu_exportar(self):
        url = self.web.url_base + "erp_consulta.html"
        m, err = mapear(url)
        self.assertIsNotNone(m, err)
        gen = next(f for f in m["filtros"] if f["etiqueta"] == "Consultar")
        incluir = [f["k"] for f in m["filtros"] if f["tipo"] in ("lista_nativa", "fecha")]
        data, _k = paginas.desde_mapa(m["filtros"], url=url, incluir=incluir, accion={
            "tipo": "menu_exportar", "generar": {"selectores": gen["selectores"], "objetivo": "Consultar"},
            "menu": [{"texto": "Vista Exportar"}], "exportar": {"texto": "Exportar"}})
        data["opciones"].update(pausa_entre_pasos=0, timeout_paso=10)
        ids = {f["nombre"]: f["id"] for f in data["filtros"]}
        pid, _n = paginas.guardar_nueva(self.alm, "ERP – Consulta", data)
        fin, eventos = self.lanzar("paginas/%d/ejecutar" % pid, {"seleccion": {
            ids["Almacén"]: {"estrategia": "fija", "valor": "Santiago"}, ids["Fecha de corte"]: {"valor": "20/10/2026"}}})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(self.web.estado["descargas"][-1], "ERP Santiago 20/10/2026")
        archivo = [a for e in eventos if e["tipo"] == "resultado" for a in e["archivos"]][0]
        self.assertEqual(os.path.basename(archivo), "ERP – Consulta - Santiago - 20_10_2026.csv")


if __name__ == "__main__":
    unittest.main()
