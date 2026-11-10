"""Pruebas de integración de la versión 2.3 (navegador oculto + sitio local de prueba):

- Inicio de sesión inteligente: paso «Iniciar sesión (si hace falta)» con sesión ya abierta (se omite) o sin ella,
  contraseña que falta (se pide con los campos que detecta la página, incluida una «Licencia»), contraseña
  rechazada (se pregunta una vez y nunca se reenvían los mismos datos), sesión que caduca a mitad del reporte,
  ejecución desatendida sin ventana (error claro, código 1) y grabación que junta el inicio de sesión en un paso.
- Esperas de carga: rueda (Vuetify), postback de ASP.NET, jQuery.active, petición lenta, capa que tapa los clics,
  página que consulta cada 200 ms y espera que no debe darse por buena con un elemento que ya estaba.
Nunca usan el ratón ni el teclado reales, ni el Administrador de credenciales ni la base de datos reales.
"""

import contextlib
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

from test_integracion import CLAVE, BaseIntegracion  # noqa: E402
from test_integracion_v21 import BaseGrabacion  # noqa: E402
from webbot import accesos as mod_accesos  # noqa: E402
from webbot import secretos  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

SECRETO = "127.0.0.1:clave"


def paso_login(secreto=SECRETO, usuario="demo"):
    return Paso("iniciar_sesion", sitio="127.0.0.1", enviar={"selectores": ["#entrar"], "objetivo": "Entrar"},
                campos=[{"selectores": ["#usuario"], "etiqueta": "Usuario", "tipo": "texto", "clave": "usuario",
                         "valor": usuario},
                        {"selectores": ["#clave"], "etiqueta": "Contraseña", "tipo": "clave", "clave": "clave",
                         "secreto": secreto}])


class PedirFalso:
    """Hace de la ventana: apunta cada solicitud y contesta con las respuestas dadas (None = Cancelar)."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.solicitudes = []

    def __call__(self, solicitud, esperar):
        self.solicitudes.append(solicitud)
        return self.respuestas.pop(0) if self.respuestas else None


class TestInicioSesion(BaseIntegracion):
    def flujo(self, *pasos, app="app.html", timeout_paso=10):
        f = Flujo(nombre="Login", url=self.base + app)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=timeout_paso)
        f.pasos = [Paso("abrir_url", url=self.base + app)] + list(pasos)
        return f

    def test_inicia_sesion_y_la_segunda_vez_se_omite(self):
        secretos.guardar(SECRETO, CLAVE)
        f = self.flujo(paso_login(), Paso("clic", selectores=["#accion"]), Paso("esperar_texto", texto="hecha"))
        res = self.ejecutar(f, nombre_perfil="perfil_sesion")
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("sesión iniciada en «127.0.0.1»", log)
        self.assertNotIn(CLAVE, log)
        # mismo perfil: la sesión sigue abierta y el formulario no aparece
        res2 = self.ejecutar(f, nombre_perfil="perfil_sesion")
        log2 = self.leer_log(res2)
        self.assertTrue(res2.ok, res2.resumen() + "\n" + log2)
        self.assertIn("ya había una sesión abierta: se omite", log2)
        self.assertNotIn("iniciando sesión", log2)

    def test_falta_la_contrasena_se_pide_con_los_campos_detectados(self):
        # la página pide además una «Licencia» que no estaba en el paso grabado; no hay contraseña guardada
        pedir = PedirFalso({"valores": {"clave": CLAVE, "licencia": "L-77"}, "recordar": True})
        accesos = mod_accesos.AccesosMemoria()
        app = "app.html?login=" + "login.html%3Flicencia%3D1"
        f = self.flujo(paso_login(), Paso("clic", selectores=["#accion"]), Paso("esperar_texto", texto="hecha"), app=app)
        mensajes = []
        res = self.ejecutar(f, pedir_acceso=pedir, accesos=accesos, log=mensajes.append)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertEqual(len(pedir.solicitudes), 1)
        sol = pedir.solicitudes[0]
        self.assertEqual(sol["host"], "127.0.0.1")
        self.assertFalse(sol["rechazada"])
        por_etiqueta = {c["etiqueta"]: c for c in sol["campos"]}
        self.assertIn("Licencia", por_etiqueta)
        self.assertEqual(por_etiqueta["Contraseña"]["tipo"], "clave")
        self.assertEqual(por_etiqueta["Contraseña"]["valor"], "")
        self.assertEqual(por_etiqueta["Usuario"]["valor"], "demo")
        # «Recordar»: la contraseña al almacén (con el nombre del paso) y la licencia a Accesos
        self.assertEqual(secretos.obtener(SECRETO), CLAVE)
        guardados = {a["clave"]: a for a in accesos.accesos_de("127.0.0.1")}
        self.assertEqual(guardados["licencia"]["valor"], "L-77")
        self.assertEqual(guardados["clave"]["secreto"], SECRETO)
        self.assertIsNone(guardados["clave"]["valor"])
        self.assertNotIn(CLAVE, log + "\n".join(mensajes) + json.dumps(accesos.listar_accesos()))

    def test_contrasena_rechazada_se_pregunta_una_vez(self):
        secretos.guardar(SECRETO, "mala-1")
        pedir = PedirFalso({"valores": {"clave": "mala-2"}, "recordar": True})
        f = self.flujo(paso_login(), Paso("clic", selectores=["#accion"]))
        res = self.ejecutar(f, pedir_acceso=pedir)
        log = self.leer_log(res)
        self.assertFalse(res.ok, log)
        self.assertEqual(res.paso_fallido, 2)
        self.assertEqual(len(pedir.solicitudes), 1)                         # se preguntó UNA vez
        self.assertTrue(pedir.solicitudes[0]["rechazada"])
        self.assertIn("rechazada", pedir.solicitudes[0]["mensaje"])
        self.assertIn("incorrectos", pedir.solicitudes[0]["error_pagina"])
        self.assertIn("intento 2", log)
        self.assertNotIn("intento 3", log)
        self.assertIn("volvió a rechazar", res.error)
        self.assertEqual(secretos.obtener(SECRETO), "mala-1")             # lo rechazado no se guarda
        self.assertNotIn("mala-2", log)

    def test_nunca_reenvia_los_mismos_datos(self):
        secretos.guardar(SECRETO, "mala-1")
        pedir = PedirFalso({"valores": {"clave": "mala-1"}, "recordar": True})
        res = self.ejecutar(self.flujo(paso_login(), Paso("clic", selectores=["#accion"])), pedir_acceso=pedir)
        log = self.leer_log(res)
        self.assertFalse(res.ok)
        self.assertIn("mismos datos", res.error)
        self.assertIn("intento 1", log)
        self.assertNotIn("intento 2", log)

    def test_sesion_que_caduca_a_mitad(self):
        secretos.guardar(SECRETO, CLAVE)
        f = self.flujo(paso_login(), Paso("clic", selectores=["#accion"]),
                       Paso("clic", selectores=["#accion"]), Paso("esperar_texto", texto="Acción 2 hecha"),
                       app="app.html?expira=1")
        res = self.ejecutar(f)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("pide iniciar sesión: se inicia sesión", log)
        self.assertIn("intento 2", log)

    def test_sin_paso_grabado_se_analiza_la_pagina_y_se_pide(self):
        # reporte grabado con la sesión ya abierta (sin pasos de inicio de sesión): la página pide entrar
        pedir = PedirFalso({"valores": {"usuario": "demo", "clave": CLAVE}, "recordar": True})
        accesos = mod_accesos.AccesosMemoria()
        f = self.flujo(Paso("clic", selectores=["#accion"]), Paso("esperar_texto", texto="hecha"))
        res = self.ejecutar(f, pedir_acceso=pedir, accesos=accesos)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        self.assertEqual([c["etiqueta"] for c in pedir.solicitudes[0]["campos"]], ["Usuario", "Contraseña"])
        self.assertEqual(secretos.obtener(SECRETO), CLAVE)                  # mismo nombre que usa el grabador
        self.assertEqual(accesos.accesos_de("127.0.0.1")[0]["valor"], "demo")
        # la próxima vez basta con lo guardado: no se pregunta nada
        pedir2 = PedirFalso()
        res2 = self.ejecutar(f, nombre_perfil="perfil_2", pedir_acceso=pedir2, accesos=accesos)
        self.assertTrue(res2.ok, res2.resumen() + "\n" + self.leer_log(res2))
        self.assertEqual(pedir2.solicitudes, [])

    def test_cancelar_falla_limpiamente(self):
        res = self.ejecutar(self.flujo(paso_login(), Paso("clic", selectores=["#accion"])), pedir_acceso=PedirFalso(None))
        self.assertFalse(res.ok)
        self.assertEqual(res.paso_fallido, 2)
        self.assertIn("cancelado por el usuario", res.error)

    def test_desatendido_sin_ventana_error_claro_y_codigo_1(self):
        import bot
        f = self.flujo(paso_login(), Paso("clic", selectores=["#accion"]))
        ruta = os.path.join(self.tmp, "login.json")
        f.guardar(ruta)
        salida, errores = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
            codigo = bot.principal(["--flujo", ruta, "--sin-ventana", "--oculto", "--registros", self.registros,
                                    "--perfil", os.path.join(self.tmp, "perfil_cli"), "--db", os.path.join(self.tmp, "b.db")])
        texto = salida.getvalue() + errores.getvalue()
        self.assertEqual(codigo, 1, texto)
        self.assertIn("Falta la contraseña de «127.0.0.1» (o fue rechazada). Abre el bot y ejecútalo una vez con la "
                      "ventana para guardarla.", texto)


class TestGrabarInicioSesion(BaseGrabacion):
    def test_formulario_tipo_devexpress_con_ojito_se_graba_en_un_paso(self):
        url = self.base + "app.html?login=" + "login.html%3Fdx%3D1"

        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#td_usuario")
            pg.click("#td_usuario", position={"x": 3, "y": 3})          # clic en el recuadro (td) del campo
            pg.fill("#usuario_I", "demo")
            pg.click("#td_clave", position={"x": 3, "y": 3})
            pg.click("#ojo")                                             # «ojito»: la contraseña se ve como texto
            pg.fill("#clave_I", CLAVE)
            pg.click("#entrar")
            pg.wait_for_selector("#accion")
            pg.wait_for_timeout(400)
            pg.click("#accion")
            pg.wait_for_timeout(400)

        flujo, eventos = self.grabar(url, conducir)
        tipos = [p.tipo for p in flujo.pasos]
        self.assertEqual(tipos, ["abrir_url", "iniciar_sesion", "clic"], [p.descripcion() for p in flujo.pasos])
        login = flujo.pasos[1]
        self.assertEqual(login.sitio, "127.0.0.1")
        self.assertEqual([(c["selectores"][0], c["tipo"]) for c in login.campos],
                         [("#usuario_I", "texto"), ("#clave_I", "clave")])
        self.assertEqual(login.campos[0]["valor"], "demo")
        self.assertEqual(login.campos[1]["secreto"], "127.0.0.1:ctl00$clave")
        self.assertEqual(login.enviar["selectores"][0], "#entrar")
        self.assertNotIn(CLAVE, flujo.a_json() + repr(eventos))
        self.assertTrue(any("agrupado" in d.get("texto", "") for t, d in eventos if t == "estado"))
        # se vuelve a ejecutar en un perfil limpio: el campo real está oculto bajo su «clon» (DevExpress)
        self.opciones_rapidas(flujo, timeout_paso=10)
        flujo.pasos.append(Paso("esperar_texto", texto="hecha"))
        res = self.ejecutar(Flujo.desde_json(flujo.a_json()), nombre_perfil="perfil_dx")
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("sesión iniciada", log)
        self.assertNotIn(CLAVE, log)


class TestEsperasDeCarga(BaseIntegracion):
    def flujo(self, modo, *pasos, ms=1300, timeout_paso=0.8, esperar_carga=True, sondeo=False):
        url = self.base + "carga.html?modo=%s&ms=%d%s" % (modo, ms, "&sondeo=1" if sondeo else "")
        f = Flujo(nombre="Carga " + modo, url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=timeout_paso, esperar_carga=esperar_carga)
        f.pasos = self.tramo(modo, ms, sondeo, *pasos)
        return f

    def tramo(self, modo, ms, sondeo=False, *pasos):
        """Abrir la página en un modo, «Generar» y pulsar «Siguiente», que solo existe (o deja de estar tapado)
        cuando la página termina: con un tiempo por paso (0,8 s) menor que la carga (1,3 s)."""
        url = self.base + "carga.html?modo=%s&ms=%d%s" % (modo, ms, "&sondeo=1" if sondeo else "")
        return [Paso("abrir_url", url=url), Paso("clic", selectores=["#generar"])] + list(pasos or [
            Paso("clic", selectores=["#siguiente"]), Paso("esperar_texto", texto="Siguiente pulsado")])

    def test_rueda_aspnet_jquery_peticion_lenta_y_capa(self):
        # una sola ejecución (un solo navegador) que recorre los cinco casos, uno tras otro
        f = Flujo(nombre="Cargas")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=0.8)
        modos = ("spinner", "aspnet", "jquery", "xhr", "capa")
        for modo in modos:
            f.pasos += self.tramo(modo, 1300)
        res = self.ejecutar(f, aviso_cada=1.0)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertIn("esperando a que termine de cargar", log)              # avisos mientras espera
        tramos = log.split("Abrir la página")[1:]
        self.assertEqual(len(tramos), 5)
        for modo, texto, tramo in zip(modos, ("v-overlay--active", "ASP.NET", "jQuery", "pendiente", "blockUI"), tramos):
            self.assertIn("de cargar", tramo, modo)
            self.assertIn(texto, tramo, modo)

    def test_sin_la_opcion_falla(self):
        res = self.ejecutar(self.flujo("spinner", esperar_carga=False))
        self.assertFalse(res.ok)
        self.assertEqual(res.paso_fallido, 3)

    def test_pagina_que_consulta_sin_parar_no_bloquea(self):
        f = self.flujo("xhr", Paso("clic", selectores=["#otro"]), Paso("esperar_texto", texto="Otro pulsado"),
                       ms=200, sondeo=True)
        inicio = time.monotonic()
        res = self.ejecutar(f, espera_red_max=6)
        dur = time.monotonic() - inicio
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertLess(dur, 15, log)
        self.assertNotIn("sigue ocupada", log)

    def test_espera_no_vale_con_lo_que_ya_estaba(self):
        url = self.base + "espera_vieja.html?ms=1300"
        f = Flujo(nombre="Vieja", url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=10)
        f.pasos = [Paso("abrir_url", url=url), Paso("clic", selectores=["#generar"]),
                   # grabado como en Portal: selector principal + ruta CSS que ya coincidía con el informe anterior
                   Paso("esperar_elemento", selectores=["div.informe-nuevo", ".marco > div:nth-of-type(1)"],
                        objetivo="ACME Detalles De Ventas Mayorista 24/10/2026 11:32 Canal..."),
                   # texto grabado otro día (otra fecha y hora): valen sus partes fijas
                   Paso("esperar_texto", texto="ACME Detalles De Ventas Mayorista 01/01/2020 08:00 Canal nuevo",
                        timeout=0.5)]
        res = self.ejecutar(f)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertNotIn("selector alternativo", log.split("Paso 4/4")[0].split("Paso 3/4")[1])
        self.assertIn("partes fijas", log)


if __name__ == "__main__":
    unittest.main()
