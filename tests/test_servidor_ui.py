"""Pruebas de la interfaz nueva (v3.0): API del servidor local (token, origen, reportes, ejecutar contra el sitio de
prueba en modo oculto con su progreso, pregunta «iniciar sesión» ida y vuelta, accesos, mapear por la API) y la prueba de
humo de la página (`--smoke-web`: carga la interfaz en un navegador oculto y recorre todas sus páginas sin errores).

Base de datos temporal, contraseñas en memoria, sin notificaciones de Windows ni tareas programadas reales.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from servidor_prueba import ServidorPrueba, cortes_portal  # noqa: E402
from test_integracion import CLAVE, HAY_PLAYWRIGHT  # noqa: E402
from test_integracion_v23 import SECRETO, paso_login  # noqa: E402
from webbot import avisos, secretos  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402


class BaseApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_ui_")
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
                                 oculto_forzado=True,
                                 # v3.6.1: NUNCA tareas de Windows de verdad (guardar un horario ya crea la tarea)
                                 ejecutar_tareas=lambda cmd: (1, "(prueba: nunca se crean tareas)"))
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)
        self.addCleanup(self.app.detener)

    def llamar(self, metodo, ruta, datos=None, token=True, cabeceras=None, crudo=False):
        cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
        req = urllib.request.Request(self.srv.url + ruta.lstrip("/"), data=cuerpo, method=metodo)
        if cuerpo is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("X-Bot-Token", self.app.token)
        for k, v in (cabeceras or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                datos = r.read()
                return r.status, (datos if crudo else json.loads(datos.decode("utf-8")))
        except urllib.error.HTTPError as e:
            datos = e.read()
            try:
                return e.code, json.loads(datos.decode("utf-8"))
            except ValueError:
                return e.code, {}

    def api(self, metodo, ruta, datos=None):
        codigo, r = self.llamar(metodo, "api/" + ruta, datos)
        self.assertEqual(codigo, 200, r)
        return r

    def esperar_trabajo(self, trabajo_id, timeout=120, al_evento=None):
        """Lee los eventos hasta que termine el trabajo.  Devuelve (estado final, eventos)."""
        desde, eventos = 0, []
        fin = time.monotonic() + timeout
        while time.monotonic() < fin:
            r = self.api("GET", "eventos?desde=%d&espera=2" % desde)
            for ev in r["eventos"]:
                desde = max(desde, ev["seq"])
                eventos.append(ev)
                if al_evento:
                    al_evento(ev)
                if ev["tipo"] == "trabajo" and ev.get("trabajo") == trabajo_id and ev["estado"] != "en_curso":
                    return ev, eventos
        self.fail("el trabajo no terminó: %s" % [e["tipo"] for e in eventos][-20:])


class TestSeguridad(BaseApi):
    def test_token_y_origen(self):
        codigo, r = self.llamar("GET", "api/estado", token=False)
        self.assertEqual(codigo, 401)
        codigo, r = self.llamar("GET", "api/estado", cabeceras={"X-Bot-Token": "otro"}, token=False)
        self.assertEqual(codigo, 401)
        codigo, r = self.llamar("GET", "api/estado")
        self.assertEqual(codigo, 200)
        self.assertEqual(r["version"], "3.6")
        codigo, _ = self.llamar("GET", "api/estado", cabeceras={"Origin": "http://evil.example.com"})
        self.assertEqual(codigo, 403)
        codigo, _ = self.llamar("GET", "api/estado", cabeceras={"Host": "evil.example.com"})
        self.assertEqual(codigo, 403)
        codigo, _ = self.llamar("POST", "api/reportes", {"flujo": {}}, cabeceras={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(codigo, 403)
        codigo, _ = self.llamar("GET", "api/estado", cabeceras={"Origin": self.srv.url.rstrip("/")})
        self.assertEqual(codigo, 200)
        # la página se sirve sin token, con cabeceras de seguridad; fuera de ui/ no se sirve nada
        codigo, html = self.llamar("GET", "", token=False, crudo=True)
        self.assertEqual(codigo, 200)
        self.assertIn(b"app.js", html)
        for ruta in ("..%2Fwebbot%2Fsecretos.py", "../bot.py", "%2e%2e/bot.py"):
            codigo, _ = self.llamar("GET", ruta, token=False, crudo=True)
            self.assertEqual(codigo, 404, ruta)
        req = urllib.request.Request(self.srv.url)
        with urllib.request.urlopen(req) as r:
            self.assertIn("default-src 'self'", r.headers.get("Content-Security-Policy"))
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")


class TestReportes(BaseApi):
    def test_crud_y_papelera(self):
        f = Flujo(nombre="Ventas", url="http://127.0.0.1/", pasos=[Paso("abrir_url", url="http://127.0.0.1/")])
        r = self.api("POST", "reportes", {"flujo": f.a_dict()})
        rid = r["id"]
        self.assertEqual([x["nombre"] for x in self.api("GET", "reportes")["reportes"]], ["Ventas"])
        d = self.api("GET", "reportes/%d" % rid)
        self.assertEqual(d["pasos"][0]["descripcion"], "Abrir la página http://127.0.0.1/")
        flujo = d["flujo"]
        flujo["pasos"].append({"tipo": "esperar_texto", "texto": "listo"})
        self.api("PUT", "reportes/%d" % rid, {"flujo": flujo, "nombre": "Ventas diarias"})
        self.assertEqual(self.alm.cargar_flujo(rid).pasos[-1].texto, "listo")
        self.assertEqual(self.alm.obtener(rid)["nombre"], "Ventas diarias")
        codigo, err = self.llamar("POST", "api/reportes", {"flujo": f.a_dict(), "nombre": "ventas diarias"})
        self.assertEqual(codigo, 400)
        self.assertIn("Ya existe", err["error"])
        copia = self.api("POST", "reportes/%d/duplicar" % rid, {})["id"]
        self.api("DELETE", "reportes/%d" % copia)
        self.assertEqual([x["id"] for x in self.api("GET", "papelera")["reportes"]], [copia])
        codigo, _ = self.llamar("DELETE", "api/papelera/%d" % copia, {})            # sin confirmar: no se borra
        self.assertEqual(codigo, 400)
        self.api("POST", "papelera/%d/restaurar" % copia, {})
        self.assertEqual(len(self.api("GET", "reportes")["reportes"]), 2)
        # utilidades del editor: describir y convertir listas
        flujo["pasos"] += [{"tipo": "clic", "selectores": ["#lista"], "objetivo": "div"},
                           {"tipo": "clic", "selectores": ['role=option[name="45 - 2026"]'], "objetivo": "45 - 2026"}]
        des = self.api("POST", "flujo/describir", {"flujo": flujo})
        self.assertEqual(des["pares"], [[2, 3, "45 - 2026"]])
        conv = self.api("POST", "flujo/convertir_listas", {"flujo": flujo, "estrategias": {"2": "mas_reciente"}})
        self.assertEqual(conv["flujo"]["pasos"][-1]["tipo"], "elegir_opcion")
        self.assertEqual(conv["flujo"]["pasos"][-1]["estrategia"], "mas_reciente")
        self.assertEqual(self.api("POST", "plantilla", {"texto": "{secreto:x}"})["vista"], "********")
        aj = self.api("PUT", "ajustes", {"ajustes": {"timeout_paso": 30, "desconocido": 1}})["ajustes"]
        self.assertEqual(aj["timeout_paso"], 30)
        self.assertNotIn("desconocido", aj)


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestEjecutarPorLaApi(BaseApi):
    @classmethod
    def setUpClass(cls):
        cls.web = ServidorPrueba().iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def test_ejecutar_con_progreso_y_pregunta_de_acceso(self):
        base = self.web.url_base
        f = Flujo(nombre="Login", url=base + "app.html")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=10)
        f.pasos = [Paso("abrir_url", url=base + "app.html"), paso_login(), Paso("clic", selectores=["#accion"]),
                   Paso("esperar_texto", texto="hecha")]
        rid = self.api("POST", "reportes", {"flujo": f.a_dict()})["id"]
        t = self.api("POST", "ejecutar", {"ids": [rid]})
        self.assertEqual(t["estado"], "en_curso")
        codigo, err = self.llamar("POST", "api/ejecutar", {"ids": [rid]})              # uno a la vez
        self.assertEqual(codigo, 409, err)
        contestadas = []

        def al_evento(ev):
            if ev["tipo"] == "pregunta":                     # falta la contraseña: la página pregunta
                pend = self.api("GET", "preguntas")["preguntas"]
                self.assertEqual(pend[0]["solicitud"]["host"], "127.0.0.1")
                self.api("POST", "preguntas/" + ev["id"], {"respuesta": {"valores": {"clave": CLAVE}, "recordar": True}})
                contestadas.append(ev["id"])
        fin, eventos = self.esperar_trabajo(t["id"], al_evento=al_evento)
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(len(contestadas), 1)
        progreso = [e for e in eventos if e["tipo"] == "progreso" and e["estado"] == "ok"]
        self.assertEqual([e["i"] for e in progreso], [0, 1, 2, 3])
        self.assertTrue(all(e["total"] == 4 for e in progreso))
        self.assertEqual(secretos.obtener(SECRETO), CLAVE)
        self.assertNotIn(CLAVE, json.dumps(eventos))
        hist = self.api("GET", "historial")["historial"]
        self.assertEqual(hist[0]["resultado"], "ok")
        reg = self.api("GET", "historial/%d/registro" % hist[0]["id"])
        self.assertIn("sesión iniciada", reg["texto"])
        self.assertNotIn(CLAVE, reg["texto"])
        # Accesos: el sitio aparece con la contraseña guardada; se cambia por la API
        sitio = next(s for s in self.api("GET", "accesos")["sitios"] if s["host"] == "127.0.0.1")
        self.assertEqual(sitio["estado"], "guardada")
        self.assertEqual(sitio["reportes"][0]["nombre"], "Login")
        self.api("POST", "accesos/127.0.0.1/clave", {"contrasena": "otra-clave", "clave": "clave"})
        self.assertEqual(secretos.obtener(SECRETO), "otra-clave")
        self.assertNotIn("otra-clave", json.dumps(self.api("GET", "accesos")) + json.dumps(self.alm.listar_accesos()))

    def test_mapear_y_crear_pasos_por_la_api(self):
        url = self.web.url_base + "portal.html?ms=200"
        t = self.api("POST", "mapa/iniciar", {"url": url})
        fin = time.monotonic() + 60
        while not (self.app.sesion_mapa and self.app.sesion_mapa.listo.is_set()) and time.monotonic() < fin:
            time.sleep(0.2)
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        por = {f["etiqueta"]: f for f in m["filtros"]}
        k = por["Seleccione reporte"]["k"]
        m = self.api("POST", "mapa/actualizar", {"k": k, "valor": "Detalles Ventas Mayorista"})
        por = {f["etiqueta"]: f for f in m["filtros"]}
        self.assertEqual(por["Elegir corte"]["opciones"], cortes_portal("Detalles Ventas Mayorista"))
        elecciones = [{"k": por["Seleccione reporte"]["k"], "estrategia": "fija", "valor": "Detalles Ventas Mayorista"},
                      {"k": por["Elegir corte"]["k"], "estrategia": "mas_reciente"},
                      {"k": por["Generar"]["k"], "modo": "descargar"}]
        r = self.api("POST", "mapa/crear_pasos", {"filtros": m["filtros"], "elecciones": elecciones, "destino": "nuevo",
                                                    "nombre": "Portal mapeado", "url": url})
        self.api("POST", "mapa/guardar", {"reporte_id": r["id"], "url": url, "alcance": "todo", "filtros": m["filtros"]})
        self.api("POST", "mapa/terminar", {})
        estado, _ = self.esperar_trabajo(t["trabajo"]["id"])
        self.assertEqual(estado["estado"], "ok", estado)
        fl = self.alm.cargar_flujo(r["id"])
        self.assertEqual([p.tipo for p in fl.pasos], ["abrir_url", "elegir_opcion", "elegir_opcion", "descargar"])
        self.assertEqual(fl.pasos[2].estrategia, "mas_reciente")
        self.assertEqual(len(self.alm.mapas(r["id"])), 1)


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestVentanasDeLaPagina(BaseApi):
    def test_ventana_la_contrasena_fallo(self):
        """Una pregunta «clave_fallida» del hilo de trabajo se ve como ventana en la página y se contesta desde ella."""
        import threading
        from playwright.sync_api import sync_playwright
        from webbot.accesos import PeticionAcceso
        trabajo = su.Trabajo("ejecutar", "prueba")
        pedir = self.app._pedir_acceso(trabajo)
        respuesta = {}
        sol = {"host": "portal.ejemplo.com", "tipo": "clave_fallida", "rechazada": True, "usuario": "usuario1",
               "mensaje": "La contraseña fue rechazada por la página.", "error_pagina": "Credenciales inválidas",
               "campos": [{"clave": "usuario", "etiqueta": "Usuario", "tipo": "texto", "valor": "usuario1"},
                          {"clave": "clave", "etiqueta": "Contraseña", "tipo": "clave", "valor": ""}]}
        hilo = threading.Thread(target=lambda: respuesta.update(r=pedir(sol, lambda ev: ev.wait(60))), daemon=True)
        errores = []
        with sync_playwright() as p:
            nav = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = nav.new_page()
                pg.on("pageerror", lambda e: errores.append(str(e)))
                pg.goto(self.srv.url_con_token(), wait_until="load")
                pg.wait_for_selector("#contenido [data-pagina='inicio']")
                hilo.start()
                pg.wait_for_selector("#modal-titulo")
                self.assertEqual(pg.inner_text("#modal-titulo"), "La contraseña de «portal.ejemplo.com» falló")
                self.assertIn("rechazó la contraseña guardada del usuario «usuario1»", pg.inner_text(".modal"))
                clave = pg.locator(".modal input[type=password]")
                clave.fill("nueva-123")
                pg.click(".modal button:has-text('Mostrar')")
                self.assertEqual(pg.locator(".modal .campo-clave input").get_attribute("type"), "text")
                pg.click(".modal button:has-text('Guardar y reintentar')")
                hilo.join(20)
                pg.wait_for_selector("#modal-fondo.oculto", state="attached")
            finally:
                nav.close()
        self.assertEqual(respuesta["r"], {"valores": {"usuario": "usuario1", "clave": "nueva-123"}, "recordar": True})
        self.assertEqual(errores, [])


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestPruebaDeHumoWeb(unittest.TestCase):
    def test_smoke_web(self):
        import bot
        salida = io.StringIO()
        try:
            with contextlib.redirect_stdout(salida):
                codigo = bot.principal(["--smoke-web"])
        finally:
            secretos.usar_almacen(None)
        self.assertEqual(codigo, 0, salida.getvalue())
        self.assertIn("sin errores", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
