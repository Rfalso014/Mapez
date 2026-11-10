"""Pruebas de integración de la versión 3.3.1 (navegador OCULTO y el sitio de prueba).

A. Webs de una sola página (como Portal) que tras iniciar sesión van SIEMPRE a «Inicio»: un reporte grabado que empieza
   en una dirección profunda (`portal_spa.html#/reportes/corte`) y una Página creada mapeando esa página entera se
   ejecutan de principio a fin (el bot inicia sesión con los Accesos y vuelve a la dirección a la que iba).
B. Inicio de sesión tipo ERP (`erp_login.html`: Licencia + Usuario + contraseña de DevExpress con «clon» `_I_CLND`, nombres
   `ctl00$formContent$…`, ventanita «El campo LICENCIA esta vacio (es un dato obligatorio)»): un dato obligatorio vacío
   NO marca la contraseña como rechazada; la Licencia se toma de Accesos o se pide SOLO a ella; con la contraseña mala sí
   se marca (con lo que dijo la página) y la respuesta de la ventana rellena el campo de DevExpress; la marca puesta por un
   dato obligatorio se quita sola, y «Quitar marca de rechazada» por la API.
Base de datos temporal, contraseñas en memoria, sin notificaciones de Windows ni tareas programadas.
"""

import json
import os
import sys
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from servidor_prueba import ServidorPrueba  # noqa: E402
from test_integracion import CLAVE, HAY_PLAYWRIGHT, BaseIntegracion  # noqa: E402
from test_servidor_ui import BaseApi  # noqa: E402
from webbot import accesos as mod_accesos  # noqa: E402
from webbot import secretos  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

HOST = "127.0.0.1"
SECRETO_ERP = HOST + ":ctl00$formContent$txtContrasenia"     # como lo guarda el grabador (por el name)


def paso_login_erp(con_licencia=False):
    """El paso «Iniciar sesión» grabado en el ERP (como el del reporte «Erp» real), con o sin la Licencia."""
    campos = []
    if con_licencia:
        campos.append({"selectores": ["#ctl00_formContent_txtLicencia_I", 'input[name="ctl00$formContent$txtLicencia"]'],
                       "etiqueta": "Licencia", "tipo": "texto", "clave": "ctl00_formContent_txtLicencia_I", "valor": "L-77"})
    campos += [
        {"selectores": ["#ctl00_formContent_txtUsuario_I", 'input[name="ctl00$formContent$txtUsuario"]'],
         "etiqueta": "Usuario", "tipo": "texto", "clave": "ctl00_formContent_txtUsuario_I", "valor": "demo"},
        {"selectores": ["#ctl00_formContent_txtContrasenia_I", 'input[name="ctl00$formContent$txtContrasenia"]'],
         "etiqueta": "Contrasenia", "tipo": "clave", "clave": "ctl00_formContent_txtContrasenia_I",
         "secreto": SECRETO_ERP}]
    return Paso("iniciar_sesion", sitio=HOST, campos=campos,
                enviar={"selectores": ['.dxb span:text-is("Aceptar")', "#ctl00_formContent_btnAceptar_CD > span:nth-of-type(1)"],
                        "objetivo": "Aceptar"})


class Responder:
    """Hace de la ventana del bot: contesta cada pregunta con `funcion(solicitud)` (por las claves de sus campos, como la
    interfaz) y apunta las solicitudes."""

    def __init__(self, *funciones):
        self.funciones = list(funciones)
        self.solicitudes = []

    def __call__(self, solicitud, esperar):
        self.solicitudes.append(solicitud)
        if not self.funciones:
            return None
        return self.funciones.pop(0)(solicitud)


def por_etiqueta(solicitud, valores):
    """{"valores": {clave: valor}} con los valores dados por etiqueta («Licencia», «Contrasenia»…)."""
    res = {}
    for c in solicitud["campos"]:
        if c["etiqueta"] in valores:
            res[c["clave"]] = valores[c["etiqueta"]]
    return {"valores": res, "recordar": True}


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestLoginERP(BaseIntegracion):
    def setUp(self):
        super().setUp()
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)

    def flujo(self, login, pagina="erp_login.html"):
        f = Flujo(nombre="Erp", url=self.base + pagina)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=10)
        f.pasos = [Paso("abrir_url", url=self.base + pagina), login,
                   Paso("clic", selectores=["#accion"]), Paso("esperar_texto", texto="Acción 1 hecha")]
        return f

    def licencia_en_accesos(self):
        # guardada con el name de ASP.NET («$»): es el mismo campo que «ctl00_formContent_txtLicencia_I»
        self.alm.guardar_acceso(HOST, "ctl00$formContent$txtLicencia", "Licencia", "texto", valor="L-77")

    def test_flujo_sin_licencia_y_accesos_con_licencia_entra(self):
        secretos.guardar(SECRETO_ERP, CLAVE)
        self.licencia_en_accesos()
        res = self.ejecutar(self.flujo(paso_login_erp()), accesos=self.alm, pedir_acceso=Responder())
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("sesión iniciada", log)
        self.assertNotIn("intento 2", log)
        self.assertNotIn(CLAVE, log)

    def test_falta_la_licencia_se_pide_solo_ella_y_no_se_marca_la_contrasena(self):
        secretos.guardar(SECRETO_ERP, CLAVE)
        ventana = Responder(lambda s: por_etiqueta(s, {"Licencia": "L-77"}))
        res = self.ejecutar(self.flujo(paso_login_erp()), accesos=self.alm, pedir_acceso=ventana)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("LICENCIA esta vacio", log)
        self.assertIn("no es la contraseña", log)
        self.assertNotIn("marcada como rechazada", log)
        self.assertEqual(len(ventana.solicitudes), 1)
        sol = ventana.solicitudes[0]
        self.assertEqual([c["etiqueta"] for c in sol["campos"]], ["Licencia"])      # SOLO la licencia
        self.assertFalse(sol["rechazada"])
        self.assertEqual(sol["tipo"], "inicio_sesion")
        self.assertIsNone(secretos.rechazada(SECRETO_ERP))
        self.assertIsNone((self.alm.estado_clave(SECRETO_ERP) or {}).get("rechazada"))
        # la licencia queda en Accesos para la próxima vez
        self.assertIn("L-77", [a["valor"] for a in self.alm.accesos_de(HOST)])

    def test_licencia_que_la_web_no_recibio_se_vuelve_a_escribir(self):
        # el paso SÍ lleva la licencia, pero el primer envío llega sin ella (lo que pasó en el ERP real a las 12:41)
        secretos.guardar(SECRETO_ERP, CLAVE)
        ventana = Responder()
        res = self.ejecutar(self.flujo(paso_login_erp(con_licencia=True), "erp_login.html?borra_licencia=1"),
                            accesos=self.alm, pedir_acceso=ventana)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("se vuelve a escribir y se reintenta", log)
        self.assertEqual(ventana.solicitudes, [])
        self.assertIsNone(secretos.rechazada(SECRETO_ERP))

    def test_sin_ventana_y_sin_licencia_error_claro_sin_marcar(self):
        secretos.guardar(SECRETO_ERP, CLAVE)
        res = self.ejecutar(self.flujo(paso_login_erp()), accesos=self.alm)
        self.assertFalse(res.ok)
        self.assertIn("«Licencia» (dato obligatorio)", res.error)
        self.assertIsNone(secretos.rechazada(SECRETO_ERP))

    def test_contrasena_mala_se_marca_con_el_motivo_y_la_ventana_rellena_devexpress(self):
        secretos.guardar(SECRETO_ERP, "mala-1")
        self.licencia_en_accesos()
        ventana = Responder(lambda s: por_etiqueta(s, {"Contrasenia": CLAVE}))
        res = self.ejecutar(self.flujo(paso_login_erp()), accesos=self.alm, pedir_acceso=ventana)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("marcada como rechazada", log)
        self.assertEqual(len(ventana.solicitudes), 1)
        sol = ventana.solicitudes[0]
        self.assertEqual(sol["tipo"], "clave_fallida")
        self.assertIn("incorrectos", sol["error_pagina"])
        claves = [c["clave"] for c in sol["campos"]]
        self.assertEqual(len(claves), len(set(claves)))                    # nunca dos cajas con la misma clave
        self.assertEqual([c["etiqueta"] for c in sol["campos"] if c["tipo"] == "clave"], ["Contrasenia"])
        self.assertEqual(sol["usuario"], "demo")
        # la nueva contraseña funcionó: se guarda con su nombre y se quita la marca
        self.assertEqual(secretos.obtener(SECRETO_ERP), CLAVE)
        self.assertIsNone(secretos.rechazada(SECRETO_ERP))
        self.assertNotIn(CLAVE, log)

    def test_rechazo_guarda_lo_que_dijo_la_pagina(self):
        secretos.guardar(SECRETO_ERP, "mala-1")
        self.licencia_en_accesos()
        res = self.ejecutar(self.flujo(paso_login_erp()), accesos=self.alm)          # sin ventana (tarea programada)
        self.assertFalse(res.ok)
        self.assertTrue(secretos.rechazada(SECRETO_ERP))
        est = self.alm.estado_clave(SECRETO_ERP)
        self.assertTrue(est["rechazada"])
        self.assertIn("Usuario o contraseña incorrectos", est["motivo"])
        self.assertEqual(est["usuario"], "demo")

    def test_marca_puesta_por_un_dato_obligatorio_se_quita_sola(self):
        # como quedó el ERP real el 28/10: marcada «rechazada» por «El campo LICENCIA esta vacio»
        secretos.guardar(SECRETO_ERP, CLAVE)
        secretos.marcar_rechazada(SECRETO_ERP)
        self.alm.marcar_clave_rechazada(SECRETO_ERP, HOST, "demo",
                                        motivo="Mensaje El campo LICENCIA esta vacio (es un dato obligatorio) Aceptar")
        self.licencia_en_accesos()
        res = self.ejecutar(self.flujo(paso_login_erp()), accesos=self.alm)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("se quita la marca", log)
        self.assertIsNone(secretos.rechazada(SECRETO_ERP))
        self.assertFalse((self.alm.estado_clave(SECRETO_ERP) or {}).get("rechazada"))

    def test_entra_a_mano_mientras_se_pregunta_y_contesta_sin_contrasena(self):
        # lo del registro 2026-10-28_124129: mientras la ventana del bot preguntaba, el usuario entró a mano en el
        # navegador y contestó la ventana con la contraseña vacía → antes «Faltan datos… Contrasenia»; ahora se sigue
        secretos.guardar(SECRETO_ERP, "mala-1")
        self.licencia_en_accesos()
        ejecutor = {}

        def entrar_a_mano(solicitud):
            pg = ejecutor["ej"].paginas[0]
            if pg.is_visible("#ctl00_formContent_popMensaje_btnAceptar_CD"):
                pg.click("#ctl00_formContent_popMensaje_btnAceptar_CD")
            pg.click("#ctl00_formContent_txtContrasenia_I_CLND")
            pg.keyboard.type(CLAVE)
            pg.click("#ctl00_formContent_btnAceptar_CD")
            pg.wait_for_url("**/app.html", timeout=10000)
            return {"valores": {c["clave"]: "" for c in solicitud["campos"]}, "recordar": True}
        from webbot.ejecutor import Ejecutor
        f = self.flujo(paso_login_erp())
        ej = Ejecutor(f, carpeta_perfil=os.path.join(self.tmp, "perfil_mano"), carpeta_registros=self.registros,
                      carpeta_descargas=self.descargas, oculto=True, pausa_entre_pasos=0, accesos=self.alm,
                      pedir_acceso=Responder(entrar_a_mano))
        ejecutor["ej"] = ej
        res = ej.ejecutar()
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("se inició a mano", log)
        self.assertNotIn("Faltan datos", log)


SECRETO_SPA = HOST + ":input-v-2"


def accesos_spa(accesos):
    """Accesos del sitio como los del Portal real (usuario por id de Vuetify y la contraseña por su nombre)."""
    secretos.guardar(SECRETO_SPA, CLAVE)
    accesos.guardar_acceso(HOST, "input-v-0", "Usuario (código)", "texto", valor="demo",
                           selectores=["#input-v-0", 'input[placeholder="Usuario (código)"]'])
    accesos.guardar_acceso(HOST, "input-v-2", "Contraseña", "clave", secreto=SECRETO_SPA,
                           selectores=["#input-v-2", 'input[placeholder="Contraseña"]'])


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestDireccionProfundaTrasIniciarSesion(BaseIntegracion):
    def flujo(self, pagina):
        f = Flujo(nombre="Reporte mapeado", url=self.base + pagina)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=12)
        f.pasos = [Paso("abrir_url", url=self.base + pagina),
                   Paso("clic", selectores=['role=tab[name="Corte"]', "button.v-btn.v-tab-item--selected"], objetivo="Corte"),
                   Paso("seleccionar", selectores=["#reporte"], valor="Detalles Ventas Mayorista",
                        etiqueta="Detalles Ventas Mayorista"),
                   Paso("elegir_opcion", selectores=["#corte"], objetivo="Elegir corte", estrategia="mas_reciente"),
                   Paso("descargar", selectores=["#generar"], nombre="Corte{ext}")]
        return f

    def comprobar(self, pagina):
        accesos = mod_accesos.AccesosMemoria()
        accesos_spa(accesos)
        res = self.ejecutar(self.flujo(pagina), accesos=accesos)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("sesión iniciada", log)
        self.assertIn("tras iniciar sesión la web fue a «", log)
        self.assertIn("#/inicio»: se vuelve a «", log)
        self.assertIn("ya está elegida", log)                       # la pestaña «Corte» ya estaba elegida
        self.assertEqual(len(res.archivos), 1)
        with open(res.archivos[0], encoding="utf-8") as fh:
            self.assertIn("44 - 2026", fh.read())
        self.assertNotIn(CLAVE, log)

    def test_reporte_que_empieza_en_la_direccion_profunda(self):
        self.comprobar("portal_spa.html#/reportes/corte")

    def test_la_web_cambia_la_direccion_al_inicio_de_sesion(self):
        self.comprobar("portal_spa.html?redir=1#/reportes/corte")

    def test_paso_iniciar_sesion_tras_la_direccion_profunda(self):
        accesos = mod_accesos.AccesosMemoria()
        accesos_spa(accesos)
        f = self.flujo("portal_spa.html#/reportes/corte")
        f.pasos.insert(1, Paso("iniciar_sesion", sitio=HOST, enviar={"selectores": ["#btn-entrar"]}, campos=[
            {"selectores": ["#input-v-0"], "etiqueta": "Usuario", "tipo": "texto", "clave": "input-v-0", "valor": "demo"},
            {"selectores": ["#input-v-2"], "etiqueta": "Contraseña", "tipo": "clave", "clave": "input-v-2",
             "secreto": SECRETO_SPA}]))
        res = self.ejecutar(f, accesos=accesos)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("se vuelve a «", log)

    def test_pagina_de_inicio_de_sesion_no_se_vuelve_a_abrir(self):
        from webbot.ejecutor import hay_que_volver
        self.assertTrue(hay_que_volver("https://portal.ejemplo.com/portal/#/inicio",
                                       "https://portal.ejemplo.com/portal/#/reportes/corte"))
        self.assertFalse(hay_que_volver("https://portal.ejemplo.com/portal/#/inicio",
                                        "https://portal.ejemplo.com/portal/#/inicio-sesion"))
        self.assertFalse(hay_que_volver("https://erp.ejemplo.com/app_menu.aspx?x=1",
                                        "https://erp.ejemplo.com/app_1000_login.aspx"))
        self.assertFalse(hay_que_volver("https://x.com/inicio", "https://x.com/"))
        self.assertFalse(hay_que_volver("https://x.com/app/#/inicio", "https://x.com/app/"))
        self.assertFalse(hay_que_volver("https://x.com/r?a=1", "https://x.com/r?a=2"))
        self.assertTrue(hay_que_volver("https://x.com/home", "https://x.com/reportes/ventas"))


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestPaginaDeMapaCompleto(BaseApi):
    """«Mapear página» de toda la página `#/reportes/corte` → «Guardar como Página» → ejecutarla (otro navegador, sin
    sesión: inicia sesión con los Accesos, la web va a «Inicio» y el bot vuelve a la página del formulario)."""

    @classmethod
    def setUpClass(cls):
        cls.web = ServidorPrueba().iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def setUp(self):
        super().setUp()
        self.alm.guardar_ajustes({"timeout_paso": 15, "pausa_entre_pasos": 0})

    def terminar(self):
        s = self.app.sesion_mapa
        if s is not None and not s.terminada.is_set():
            self.llamar("POST", "api/mapa/terminar", {})
            s.terminada.wait(30)

    def test_pagina_creada_mapeando_toda_la_pagina_funciona(self):
        accesos_spa(self.alm)
        # el usuario abre la web, entra y va a Reportes a mano (aquí lo hace la propia página con ?auto=1)
        self.api("POST", "mapa/iniciar", {"url": self.web.url_base + "portal_spa.html?auto=1#/inicio-sesion"})
        fin = time.monotonic() + 60
        while not (self.app.sesion_mapa and self.app.sesion_mapa.listo.is_set()) and time.monotonic() < fin:
            time.sleep(0.2)
        self.addCleanup(self.terminar)
        fin = time.monotonic() + 20
        while time.monotonic() < fin:
            p = self.api("POST", "mapa/pestanas", {})["pestanas"]
            if p and p[0]["url"].endswith("#/reportes/corte"):
                break
            time.sleep(0.3)
        m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        self.assertTrue(m["url"].endswith("portal_spa.html#/reportes/corte"), m["url"])
        por = {f["etiqueta"]: f for f in m["filtros"]}
        self.assertIn("Seleccione reporte", por)
        prop = self.api("POST", "mapa/propuesta", {"filtros": m["filtros"], "url": m["url"]})
        self.assertEqual([p["url"] for p in prop["llegada"]], [m["url"]])
        r = self.api("POST", "paginas", {"nombre": "Portal – Reportes", "filtros": m["filtros"], "url": m["url"],
                                         "accion": {"tipo": "descargar", "generar_k": por["Generar"]["k"]},
                                         "incluir": [f["k"] for f in prop["filtros"]],
                                         "nombres": {str(f["k"]): f["nombre"] for f in prop["filtros"]}})
        pid = r["id"]
        self.terminar()
        filtros = {f["nombre"]: f for f in self.alm.obtener_pagina(pid)["data"]["filtros"]}
        seleccion = {filtros["Seleccione reporte"]["id"]: {"estrategia": "fija", "valor": "Detalles Ventas Mayorista"},
                     filtros["Elegir corte"]["id"]: {"estrategia": "mas_reciente"}}
        desde = self.app.eventos.ultimo
        t = self.api("POST", "paginas/%d/ejecutar" % pid, {"seleccion": seleccion, "sin_navegador": True})
        fin, eventos = self.esperar_trabajo(t["id"], timeout=180)
        registros = [e.get("registro") for e in eventos if e["seq"] > desde and e["tipo"] == "resultado"]
        log = ""
        if registros and registros[0]:
            with open(registros[0], encoding="utf-8") as fh:
                log = fh.read()
        self.assertEqual(fin["estado"], "ok", str(fin) + "\n" + log)
        archivos = [a for e in eventos if e["seq"] > desde and e["tipo"] == "resultado" for a in e["archivos"]]
        self.assertEqual(len(archivos), 1, log)
        self.assertIn("se vuelve a «", log)


CAMPO = '.v-input[data-campo="%s"] .v-field'


class TestVigilanciaDeCualquierReporte(BaseApi):
    """C. «＋ Añadir vigilancia» con cualquier reporte guardado (también con las listas grabadas como clics, como el
    reporte «POrtal» real) o Página."""

    @classmethod
    def setUpClass(cls):
        cls.web = ServidorPrueba().iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def setUp(self):
        super().setUp()
        self.web.estado["descargas"].clear()
        self.web.estado["nuevo_corte"] = False
        self.alm.guardar_ajustes({"timeout_paso": 15, "pausa_entre_pasos": 0})
        from servidor_prueba import cortes_portal
        url = self.web.url_base + "portal.html?ms=300"
        # «POrtal»: las listas grabadas como «clic en div» + «clic en la opción» (forma real), Generar y Descargar
        f = Flujo(nombre="POrtal", url=url)
        f.pasos = [Paso("abrir_url", url=url),
                   Paso("clic", selectores=[CAMPO % "reporte"], objetivo="div"),
                   Paso("clic", selectores=['role=option[name="Detalles Ventas Mayorista"]']),
                   Paso("clic", selectores=[CAMPO % "corte"], objetivo="div"),
                   Paso("clic", selectores=['role=option[name="%s"]' % cortes_portal("Detalles Ventas Mayorista")[-1]]),
                   Paso("descargar", selectores=["#generar"], nombre="Portal_{opcion}{ext}")]
        self.rid_clics = self.alm.guardar(f)
        g = Flujo(nombre="Con elegir", url=url)
        g.pasos = [Paso("abrir_url", url=url),
                   Paso("elegir_opcion", selectores=[CAMPO % "reporte"], objetivo="Seleccione reporte",
                        estrategia="fija", valor="Detalles Ventas Mayorista"),
                   Paso("elegir_opcion", selectores=[CAMPO % "corte"], objetivo="Elegir corte", estrategia="mas_reciente")]
        self.rid_elegir = self.alm.guardar(g)
        h = Flujo(nombre="Sin listas", url=url)
        h.pasos = [Paso("abrir_url", url=url), Paso("clic", selectores=["#generar"])]
        self.rid_sin = self.alm.guardar(h)
        n = Flujo(nombre="Nativa", url=url)
        n.pasos = [Paso("abrir_url", url=url), Paso("seleccionar", selectores=["#formato"], valor="xlsx", etiqueta="Excel")]
        self.rid_nativa = self.alm.guardar(n)
        from test_v32 import pagina_simple
        self.pid = self.alm.guardar_pagina("Portal – Reportes", pagina_simple())

    def test_listado_con_todos_los_candidatos(self):
        d = self.api("GET", "vigilancia")
        rep = {x["nombre"]: x for x in d["reportes"]}
        self.assertEqual(set(rep), {"POrtal", "Con elegir", "Sin listas", "Nativa"})
        self.assertTrue(rep["POrtal"]["con_listas"])
        self.assertEqual(rep["POrtal"]["pasos"], [])
        self.assertEqual([(x["par"], x["periodo"]) for x in rep["POrtal"]["listas_clic"]], [(1, False), (3, True)])
        self.assertIn("Lista donde se eligió «44 - 2026 (", rep["POrtal"]["listas_clic"][1]["descripcion"])
        self.assertEqual(len(rep["Con elegir"]["pasos"]), 2)
        self.assertFalse(rep["Sin listas"]["con_listas"])
        self.assertEqual([x["paso"] for x in rep["Nativa"]["selects"]], [1])
        self.assertEqual([p["nombre"] for p in d["paginas"]], ["Portal – Reportes"])

    def test_anadir_a_un_reporte_con_listas_grabadas_como_clics(self):
        v = self.api("POST", "vigilancias", {"reporte_id": self.rid_clics, "par": 3, "auto_descargar": True})["vigilancia"]
        fl = self.alm.cargar_flujo(self.rid_clics)
        self.assertEqual([p.tipo for p in fl.pasos], ["abrir_url", "clic", "clic", "elegir_opcion", "descargar"])
        self.assertEqual(fl.pasos[3].estrategia, "mas_reciente")                 # «44 - 2026 (…)» parece un corte
        self.assertEqual(v["paso"], 3)
        versiones = self.alm.versiones(self.rid_clics)
        self.assertEqual(len(versiones), 1)
        self.assertIn("vigilarla", versiones[0]["motivo"])
        # la otra lista (sin fecha) también: se queda con la opción grabada y la primera vigilancia se renumera bien
        v2 = self.api("POST", "vigilancias", {"reporte_id": self.rid_clics, "par": 1})["vigilancia"]
        fl = self.alm.cargar_flujo(self.rid_clics)
        self.assertEqual([p.tipo for p in fl.pasos], ["abrir_url", "elegir_opcion", "elegir_opcion", "descargar"])
        self.assertEqual((fl.pasos[1].estrategia, fl.pasos[1].valor), ("fija", "Detalles Ventas Mayorista"))
        self.assertEqual(v2["paso"], 1)
        self.assertEqual(self.alm.vigilancia_id(v["id"])["paso"], 2)
        self.assertEqual(len(self.alm.versiones(self.rid_clics)), 2)
        # y funciona de verdad: primera revisión (referencia), llega el corte 45 → aviso y descarga
        t = self.api("POST", "vigilancias/%d/revisar" % v["id"], {})
        fin, _ev = self.esperar_trabajo(t["id"], timeout=180)
        self.assertEqual(fin["estado"], "ok", fin)
        self.web.estado["nuevo_corte"] = True
        t = self.api("POST", "vigilancias/%d/revisar" % v["id"], {})
        fin, eventos = self.esperar_trabajo(t["id"], timeout=180)
        self.assertEqual(fin["estado"], "ok", fin)
        nuevas = [e["nuevas"] for e in eventos if e["tipo"] == "vigilancia"]
        self.assertEqual(len(nuevas[-1]), 1)
        self.assertTrue(nuevas[-1][0].startswith("45 - 2026"))
        self.assertEqual(len(self.web.estado["descargas"]), 1)

    def test_anadir_a_un_reporte_con_elegir_opcion_a_una_nativa_y_a_una_pagina(self):
        v = self.api("POST", "vigilancias", {"reporte_id": self.rid_elegir, "paso": 2})["vigilancia"]
        self.assertEqual(v["paso"], 2)
        self.assertEqual(self.alm.versiones(self.rid_elegir), [])                # no se cambia nada
        v = self.api("POST", "vigilancias", {"reporte_id": self.rid_nativa, "seleccionar": 1})["vigilancia"]
        fl = self.alm.cargar_flujo(self.rid_nativa)
        self.assertEqual((fl.pasos[1].tipo, fl.pasos[1].estrategia, fl.pasos[1].valor), ("elegir_opcion", "fija", "Excel"))
        self.assertEqual(len(self.alm.versiones(self.rid_nativa)), 1)
        v = self.api("POST", "vigilancias", {"pagina_id": self.pid, "filtro": "f3"})["vigilancia"]
        self.assertEqual(v["filtro"], "f3")
        # lo que ya no existe da un error claro
        codigo, r = self.llamar("POST", "api/vigilancias", {"reporte_id": self.rid_elegir, "par": 1})
        self.assertEqual(codigo, 400, r)
        self.assertIn("ya no está", r.get("error", ""))

    @unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
    def test_en_la_interfaz(self):
        from playwright.sync_api import sync_playwright
        errores = []
        with sync_playwright() as p:
            nav = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = nav.new_page()
                pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errores.append(str(e)))
                pg.goto(self.srv.url_con_token("vigilancia"), wait_until="load")
                pg.wait_for_selector("#contenido [data-pagina='vigilancia'] button[data-anadir-vigilancia]")
                texto = pg.inner_text("#contenido")
                for nombre in ("POrtal", "Con elegir", "Nativa", "Portal – Reportes"):
                    self.assertIn(nombre, texto)
                self.assertIn("grabada(s) como clics", texto)
                # «＋ Añadir vigilancia» de arriba: todos los reportes y Páginas, con buscador
                pg.click("#contenido button[data-anadir-vigilancia]")
                pg.wait_for_selector(".modal [data-candidatos-vigilancia] li[data-candidato]")
                self.assertEqual(pg.locator(".modal li[data-candidato]").count(), 5)
                pg.fill(".modal input[type=search]", "sin")
                self.assertEqual(pg.locator(".modal li[data-candidato]").count(), 1)
                pg.click(".modal li[data-candidato='reporte-%d']" % self.rid_sin)       # sin listas: se explica
                pg.wait_for_selector(".modal [data-sin-listas]:not(.oculto)")
                self.assertIn("no tiene ninguna lista", pg.inner_text(".modal [data-sin-listas]"))
                pg.fill(".modal input[type=search]", "portal")
                pg.click(".modal li[data-candidato='reporte-%d']" % self.rid_clics)
                pg.wait_for_selector(".modal [data-modal-vigilancia] select[aria-label='Filtro vigilado']")
                sel = pg.locator(".modal select[aria-label='Filtro vigilado']")
                opciones = sel.locator("option").all_inner_texts()
                self.assertEqual(len(opciones), 2, opciones)
                self.assertTrue(any("Lista donde se eligió «44 - 2026" in o for o in opciones), opciones)
                # v3.6.1: por defecto, la lista de cortes (la que cambia) y «Descargar automáticamente» marcado
                self.assertEqual(sel.input_value(), "par:3")
                self.assertTrue(pg.locator(".modal input[aria-label='Descargar automáticamente lo nuevo']").is_checked())
                self.assertEqual(pg.locator(".modal [data-aviso-lista-fija]:not(.oculto)").count(), 0)
                otra = [o for o in sel.locator("option").evaluate_all("os => os.map(o => o.value)") if o != "par:3"][0]
                sel.select_option(otra)                                   # una lista que no cambia: se avisa
                pg.wait_for_selector(".modal [data-aviso-lista-fija]:not(.oculto)")
                self.assertIn("casi nunca cambia", pg.inner_text(".modal [data-aviso-lista-fija]"))
                sel.select_option("par:3")
                pg.wait_for_selector(".modal [data-aviso-lista-fija].oculto", state="attached")
                pg.wait_for_selector(".modal [data-convertir-lista]:not(.oculto)")
                self.assertEqual(pg.locator(".modal select[aria-label='Al ejecutar el reporte, elegir']").input_value(),
                                 "mas_reciente")
                pg.fill(".modal input[aria-label='Nombre de la vigilancia']", "Cortes")
                pg.click(".modal .pie button:has-text('Añadir vigilancia')")
                pg.wait_for_selector("#modal-fondo.oculto", state="attached")
                pg.wait_for_function("() => document.querySelectorAll('#contenido .vigilancia-tarjeta').length === 1")
                # el botón de la tarjeta de la Página sigue funcionando
                pg.click("#contenido button[data-anadir='pagina-%d']" % self.pid)
                pg.wait_for_selector(".modal [data-modal-vigilancia] select[aria-label='Lista vigilada']")
                pg.click(".modal .pie button:has-text('Añadir vigilancia')")
                pg.wait_for_selector("#modal-fondo.oculto", state="attached")
                pg.wait_for_function("() => document.querySelectorAll('#contenido .vigilancia-tarjeta').length === 2")
            finally:
                nav.close()
        self.assertEqual(errores, [])
        v = self.alm.lista_vigilancias(reporte_id=self.rid_clics)
        self.assertEqual([(x["nombre"], x["paso"]) for x in v], [("Cortes", 3)])
        self.assertEqual(self.alm.cargar_flujo(self.rid_clics).pasos[3].tipo, "elegir_opcion")
        self.assertEqual(len(self.alm.lista_vigilancias(pagina_id=self.pid)), 1)


class TestIdentidadCampos(unittest.TestCase):
    def test_mismo_campo_escrito_de_varias_formas(self):
        i = mod_accesos.identidad_campo
        base = i("ctl00$formContent$txtContrasenia")
        self.assertEqual(base, "ctl00_formcontent_txtcontrasenia")
        for t in ("ctl00_formContent_txtContrasenia_I", "ctl00_formContent_txtContrasenia_I_CLND",
                  "#ctl00_formContent_txtContrasenia_I"):
            self.assertEqual(i(t), base, t)
        self.assertEqual(i("erp.ejemplo.com:ctl00$formContent$txtContrasenia", "erp.ejemplo.com"), base)
        self.assertEqual(mod_accesos.identidades_de_selectores(['input[name="ctl00$formContent$txtLicencia"]']),
                         ["ctl00_formcontent_txtlicencia"])

    def test_tipo_de_fallo(self):
        t = mod_accesos.tipo_de_fallo
        self.assertEqual(t("Mensaje El campo LICENCIA esta vacio (es un dato obligatorio) Aceptar"), "obligatorio")
        self.assertEqual(t("Este campo es requerido"), "obligatorio")
        self.assertEqual(t("Usuario o contraseña incorrectos"), "credencial")
        self.assertEqual(t("Credenciales inválidas"), "credencial")
        self.assertEqual(t(""), "")
        self.assertTrue(mod_accesos.nombra_campo("El campo LICENCIA esta vacio", "Licencia"))
        self.assertTrue(mod_accesos.nombra_campo("El campo LICENCIA esta vacio", "", "ctl00$formContent$txtLicencia"))
        self.assertFalse(mod_accesos.nombra_campo("El campo LICENCIA esta vacio", "Usuario", "ctl00_formContent_txtUsuario_I"))


class TestQuitarMarcaApi(BaseApi):
    def test_quitar_marca_de_rechazada(self):
        secretos.guardar(SECRETO_ERP, CLAVE)
        self.alm.guardar_acceso(HOST, "ctl00_formContent_txtContrasenia_I", "Contrasenia", "clave", secreto=SECRETO_ERP)
        secretos.marcar_rechazada(SECRETO_ERP)
        self.alm.marcar_clave_rechazada(SECRETO_ERP, HOST, "demo", motivo="El campo LICENCIA esta vacio")
        sitio = next(s for s in self.api("GET", "accesos")["sitios"] if s["host"] == HOST)
        self.assertEqual(sitio["estado"], "rechazada")
        campo = next(c for c in sitio["campos"] if c["tipo"] == "clave")
        self.assertIn("LICENCIA", campo["motivo"])
        self.assertTrue(campo["motivo_obligatorio"])
        self.api("POST", "accesos/%s/quitar_rechazo" % HOST, {})
        self.assertIsNone(secretos.rechazada(SECRETO_ERP))
        self.assertFalse(self.alm.estado_clave(SECRETO_ERP)["rechazada"])
        sitio = next(s for s in self.api("GET", "accesos")["sitios"] if s["host"] == HOST)
        self.assertEqual(sitio["estado"], "guardada")
        self.assertEqual(secretos.obtener(SECRETO_ERP), CLAVE)            # la contraseña no se toca


if __name__ == "__main__":
    unittest.main()
