"""Pruebas de la versión 4.0: el «puente de errores» entre computadoras, el arranque sin ventana negra y el logotipo.

Lo que pidió el usuario: tiene el bot en varias computadoras de la misma red y quiere ver EN LA PRINCIPAL lo que falla
en las demás.  Aquí se comprueba que:

- se manda lo justo y NADA delicado (ni usuarios, ni contraseñas, ni cookies, ni correos, ni números largos);
- si la computadora principal está apagada, el fallo se guarda y se manda cuando vuelve (y no se duplica);
- sin la clave, con otra clave, demasiado grande o por otra ruta, el receptor dice que no y lo apunta SIN la clave;
- la pantalla (Ajustes e Historial) enseña y guarda lo que debe, y la clave de enviar no se devuelve nunca.

El receptor se abre en 127.0.0.1 (el propio equipo), nunca en la red: ninguna prueba sale a Internet ni a la red local.
Tampoco se tocan la base de datos real, el llavero, las tareas de Windows ni ninguna impresora.
"""

import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from test_servidor_ui import BaseApi  # noqa: E402
from webbot import puente  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402

CLAVE = "AAAA-BBBB-CCCC-DDDD"


# =========================================================== 1. lo que se tacha
class TestOcultarLoDelicado(unittest.TestCase):
    """`ocultar()` tacha lo que no puede salir de la computadora; lo que sirve para entender el fallo se queda."""

    def test_los_datos_de_acceso_de_un_paso_iniciar_sesion(self):
        t = puente.ocultar("Paso 2/9: Iniciar sesión en «Portal» (si hace falta) — Usuario: «pepe.lopez»; "
                           "contraseña «Mi-Clave-123»")
        self.assertNotIn("pepe", t)
        self.assertNotIn("Mi-Clave", t)
        self.assertIn("datos de acceso ocultos", t)

    def test_lo_que_escribe_un_paso_escribir(self):
        self.assertNotIn("pepe.lopez", puente.ocultar('Paso 3/9: Escribir «pepe.lopez» en «Usuario»'))

    def test_usuario_contrasena_token_y_cookie(self):
        t = puente.ocultar("usuario: pepe  password=Secreta1  token=abc123xyz  Cookie: sesion=9f8a")
        for malo in ("pepe", "Secreta1", "abc123xyz", "9f8a"):
            self.assertNotIn(malo, t)

    def test_correos_direcciones_con_parametros_y_la_cuenta_de_windows(self):
        t = puente.ocultar("avisar a pepe.lopez@empresa.com desde https://portal.ejemplo.com/rep?tok=S3CR3T&id=7 "
                           r"guardado en C:\Users\PepeLopez\Documents\x.pdf")
        self.assertNotIn("pepe.lopez@empresa.com", t)
        self.assertNotIn("S3CR3T", t)
        self.assertNotIn("PepeLopez", t)
        self.assertIn("portal.ejemplo.com", t)              # la página sí: hace falta para entenderlo
        self.assertIn(r"C:\Users\(usuario)", t)

    def test_los_numeros_largos_solo_el_final(self):
        t = puente.ocultar("comercio 004567891234 del corte")
        self.assertNotIn("004567891234", t)
        self.assertIn("1234", t)

    def test_lo_que_sirve_para_entender_el_fallo_se_queda(self):
        t = puente.ocultar("Error en el paso 4: No apareció «Comprobante Fiscal» (elemento #Statements_NCF) en 60 s")
        self.assertEqual(t, "Error en el paso 4: No apareció «Comprobante Fiscal» (elemento #Statements_NCF) en 60 s")
        self.assertEqual(puente.ocultar("Elegir «TIENDA 1» en «Localidad»"), "Elegir «TIENDA 1» en «Localidad»")

    def test_del_registro_solo_el_final_y_ya_limpio(self):
        texto = "\n".join("linea %d" % i for i in range(5000)) + "\nEscribir «pepe» en «Usuario»"
        r = puente.final_del_registro(texto)
        self.assertLessEqual(len(r), puente.MAX_REGISTRO + 60)
        self.assertIn("solo el final", r)
        self.assertNotIn("«pepe»", r)

    def test_el_paso_sale_del_mensaje(self):
        self.assertEqual(puente.paso_del_mensaje("Error en el paso 7: la descarga no llegó"), "paso 7")
        self.assertEqual(puente.paso_del_mensaje("algo raro"), "")


# =========================================================== 2. la cola de salida
class BaseEquipos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_puente_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.central = Almacen(os.path.join(self.tmp, "central.db"))
        self.addCleanup(self.central.cerrar)
        self.caja = Almacen(os.path.join(self.tmp, "caja.db"))
        self.addCleanup(self.caja.cerrar)
        self.caja.guardar_ajustes({"enviar_errores_a": "http://192.168.1.50:8765", "nombre_equipo": "Caja 2"})
        self.caja.guardar_clave("enviar", CLAVE)
        self.mandados = []
        self.caido = False

    def abrir(self, url, datos, clave, espera=None):
        """Un «equipo central» de mentira: no hay red de por medio."""
        if self.caido:
            raise urllib.error.URLError("no se puede conectar")
        if clave != CLAVE:
            raise urllib.error.HTTPError(url, 401, "No", None, None)
        if len(datos) > puente.MAX_CUERPO:
            raise urllib.error.HTTPError(url, 413, "Demasiado grande", None, None)
        cuerpo = json.loads(datos.decode("utf-8"))
        self.mandados.append(cuerpo)
        self.central.guardar_error_recibido(cuerpo)
        return _Respuesta()


class _Respuesta:
    status = 200

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestColaYReenvio(BaseEquipos):
    def test_si_no_hay_a_donde_mandar_no_se_manda_ni_se_guarda(self):
        self.caja.guardar_ajustes({"enviar_errores_a": ""})
        self.assertFalse(puente.anotar_fallo(self.caja, "Informes", "Error en el paso 1: nada", abrir=self.abrir))
        self.assertEqual(self.caja.errores_en_cola(), [])
        self.assertEqual(self.mandados, [])

    def test_se_manda_en_cuanto_falla(self):
        puente.anotar_fallo(self.caja, "Informes", "Error en el paso 3: no apareció X", abrir=self.abrir)
        self.assertEqual(len(self.mandados), 1)
        self.assertEqual(self.mandados[0]["equipo"], "Caja 2")
        self.assertEqual(self.mandados[0]["reporte"], "Informes")
        self.assertEqual(self.mandados[0]["paso"], "paso 3")
        self.assertEqual(self.caja.errores_en_cola(), [], "ya se mandó: no debe quedar en la cola")

    def test_si_la_principal_esta_apagada_se_guarda_y_se_manda_despues(self):
        self.caido = True
        puente.anotar_fallo(self.caja, "Informes", "Error en el paso 3: no apareció X", abrir=self.abrir)
        puente.anotar_fallo(self.caja, "Pagos", "Error en el paso 1: nada", abrir=self.abrir)
        self.assertEqual(len(self.caja.errores_en_cola()), 2, "nada se pierde")
        self.assertEqual(self.mandados, [])
        self.assertGreaterEqual(self.caja.errores_en_cola()[0]["intentos"], 1, "queda apuntado que se intentó")
        self.caido = False
        mandados, pendientes, motivo = puente.vaciar_cola(self.caja, abrir=self.abrir)
        self.assertEqual((mandados, pendientes, motivo), (2, 0, ""))
        self.assertEqual(len(self.central.errores_recibidos()), 2)

    def test_lo_mismo_dos_veces_se_guarda_una_sola_vez(self):
        puente.anotar_fallo(self.caja, "Informes", "Error en el paso 3: X", abrir=self.abrir)
        cuerpo = self.mandados[0]
        puente.enviar("http://192.168.1.50:8765", CLAVE, cuerpo, abrir=self.abrir)   # el mismo, otra vez
        self.assertEqual(len(self.mandados), 2)
        self.assertEqual(len(self.central.errores_recibidos()), 1, "mismo uuid: una sola entrada")

    def test_con_otra_clave_no_entra_y_se_queda_en_la_cola(self):
        self.caja.guardar_clave("enviar", "CLAVE-QUE-NO-ES")
        puente.anotar_fallo(self.caja, "Informes", "Error en el paso 3: X", abrir=self.abrir)
        self.assertEqual(len(self.caja.errores_en_cola()), 1)
        self.assertIn("clave no coincide", self.caja.errores_en_cola()[0]["ultimo"])
        self.assertEqual(self.central.errores_recibidos(), [])

    def test_un_registro_enorme_no_hace_fallar_el_envio(self):
        cuerpo = puente.armar("Caja 2", "Informes", "Error en el paso 1: X")
        cuerpo["registro"] = "x" * (puente.MAX_CUERPO + 5000)        # a mano: más de lo que cabe
        ok, motivo = puente.enviar("http://192.168.1.50:8765", CLAVE, cuerpo, abrir=self.abrir)
        self.assertTrue(ok, motivo)
        self.assertIn("demasiado grande", self.mandados[0]["registro"])

    def test_no_se_manda_nada_delicado(self):
        registro = ("[08:10:05] Paso 2/9: Iniciar sesión en «Portal» (si hace falta) — Usuario: «pepe.lopez»; "
                    "contraseña «Mi-Clave-123»\n"
                    "[08:10:09] Paso 3/9: Escribir «pepe.lopez» en «Usuario»\n"
                    "[08:10:20] Cookie: sesion=9f8a7b; token=S3CR3T\n"
                    "[08:10:21] aviso a pepe.lopez@empresa.com del comercio 004567891234\n"
                    "[08:10:30] Error en el paso 4: no apareció «Comprobante Fiscal»")
        puente.anotar_fallo(self.caja, "Informes", "Error en el paso 4: no apareció «Comprobante Fiscal»",
                            registro=registro, abrir=self.abrir)
        crudo = json.dumps(self.mandados[0], ensure_ascii=False)
        for malo in ("pepe.lopez", "Mi-Clave-123", "9f8a7b", "S3CR3T", "empresa.com", "004567891234"):
            self.assertNotIn(malo, crudo, "¡se estaba mandando «%s»!" % malo)
        self.assertIn("Comprobante Fiscal", crudo, "lo que explica el fallo sí tiene que llegar")

    def test_el_gancho_manda_toda_ejecucion_que_acaba_mal(self):
        """`enganchar` es el único enchufe: cualquier reporte que falle en este equipo se cuenta."""
        from webbot.flujo import Flujo, Paso
        puente.enganchar(self.caja, abrir=self.abrir)
        rid = self.caja.guardar(Flujo(nombre="Comprobantes", pasos=[Paso("abrir_url", url="http://x/")]))
        self.caja.registrar_ejecucion(rid, "ok", "")
        self.assertEqual(self.mandados, [], "lo que sale bien no se manda")
        self.caja.registrar_ejecucion(rid, "error", "Error en el paso 5: la descarga no llegó")
        self.assertEqual(len(self.mandados), 1)
        self.assertEqual(self.mandados[0]["reporte"], "Comprobantes")
        self.assertIn("paso 5", self.mandados[0]["paso"])


# =========================================================== 3. el receptor de verdad (en 127.0.0.1)
class TestReceptor(unittest.TestCase):
    """El servidor que escucha, hablado por HTTP de verdad pero contra 127.0.0.1 (nunca sale a la red)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_recep_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.alm = Almacen(os.path.join(self.tmp, "central.db"))
        self.addCleanup(self.alm.cerrar)
        self.apuntado = []
        self.r = puente.Receptor(self.alm, CLAVE, puerto=0, direccion="127.0.0.1",
                                 apuntar=self.apuntado.append)
        self.addCleanup(self.r.parar)

    def pedir(self, ruta="/api/errores", metodo="POST", cuerpo=None, clave=CLAVE, largo=None):
        datos = json.dumps(cuerpo if cuerpo is not None else {}).encode("utf-8") if metodo == "POST" else None
        req = urllib.request.Request(self.r.url + ruta, data=datos, method=metodo)
        if clave is not None:
            req.add_header("X-Bot-Clave", clave)
        if datos is not None:
            req.add_header("Content-Type", "application/json")
        if largo is not None:
            req.add_header("Content-Length", str(largo))
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, {}

    def test_nunca_escucha_en_todas_las_tarjetas_de_red(self):
        self.assertEqual(self.r.servidor.server_address[0], "127.0.0.1")
        self.assertNotEqual(self.r.servidor.server_address[0], "0.0.0.0")

    def test_con_la_clave_buena_se_guarda(self):
        cuerpo = puente.armar("Caja 2", "Informes", "Error en el paso 2: X")
        codigo, r = self.pedir(cuerpo=cuerpo)
        self.assertEqual(codigo, 200)
        self.assertTrue(r["ok"])
        lista = self.alm.errores_recibidos()
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["equipo"], "Caja 2")
        self.assertEqual(self.alm.errores_sin_leer(), 1)

    def test_sin_clave_o_con_otra_clave_se_rechaza(self):
        cuerpo = puente.armar("Caja 2", "Informes", "Error en el paso 2: X")
        self.assertEqual(self.pedir(cuerpo=cuerpo, clave=None)[0], 401)
        self.assertEqual(self.pedir(cuerpo=cuerpo, clave="OTRA-CLAVE-XX")[0], 401)
        self.assertEqual(self.alm.errores_recibidos(), [], "no se guarda nada de quien no tiene la clave")
        self.assertEqual(self.r.rechazos, 2)

    def test_lo_rechazado_se_apunta_pero_la_clave_nunca(self):
        self.pedir(cuerpo={}, clave="OTRA-CLAVE-XX")
        self.assertTrue(self.apuntado, "un intento rechazado tiene que quedar apuntado")
        texto = "\n".join(self.apuntado)
        self.assertIn("rechazado", texto)
        self.assertIn("127.0.0.1", texto)
        self.assertNotIn(CLAVE, texto)
        self.assertNotIn("OTRA-CLAVE-XX", texto)

    def test_demasiado_grande_se_rechaza(self):
        cuerpo = puente.armar("Caja 2", "Informes", "x")
        cuerpo["registro"] = "y" * (puente.MAX_CUERPO + 1000)
        self.assertEqual(self.pedir(cuerpo=cuerpo)[0], 413)
        self.assertEqual(self.alm.errores_recibidos(), [])

    def test_por_este_puente_no_se_puede_hacer_nada_mas(self):
        """Ni ejecutar reportes, ni leer archivos, ni consultar: solo entra el POST de los errores."""
        for ruta, metodo in (("/api/reportes", "POST"), ("/api/errores", "GET"), ("/", "GET"),
                             ("/api/errores/salud", "POST"), ("/api/ejecutar", "POST")):
            codigo, _r = self.pedir(ruta=ruta, metodo=metodo, cuerpo={} if metodo == "POST" else None)
            self.assertEqual(codigo, 404, "%s %s debería ser 404" % (metodo, ruta))

    def test_la_salud_dice_que_si_con_la_clave(self):
        self.assertEqual(self.pedir(ruta="/api/errores/salud", metodo="GET")[0], 200)
        self.assertEqual(self.pedir(ruta="/api/errores/salud", metodo="GET", clave=None)[0], 401)

    def test_lo_que_no_es_json_se_rechaza(self):
        req = urllib.request.Request(self.r.url + "/api/errores", data=b"<<no soy json>>", method="POST")
        req.add_header("X-Bot-Clave", CLAVE)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 400)

    def test_mandar_de_verdad_de_un_equipo_a_otro(self):
        """De punta a punta: la computadora que falla manda y la principal lo guarda (todo en 127.0.0.1)."""
        caja = Almacen(os.path.join(self.tmp, "caja.db"))
        self.addCleanup(caja.cerrar)
        caja.guardar_ajustes({"enviar_errores_a": self.r.url, "nombre_equipo": "Caja 7"})
        caja.guardar_clave("enviar", CLAVE)
        self.assertTrue(puente.anotar_fallo(caja, "Pagos", "Error en el paso 6: la descarga no llegó"))
        self.assertEqual(caja.errores_en_cola(), [])
        lista = self.alm.errores_recibidos()
        self.assertEqual([x["equipo"] for x in lista], ["Caja 7"])
        ok, texto = puente.probar(self.r.url, CLAVE, "Caja 7")
        self.assertTrue(ok, texto)
        self.assertFalse(puente.probar(self.r.url, "LA-QUE-NO-ES", "Caja 7")[0])


class TestReceptorNoSeEnciendeSinRed(unittest.TestCase):
    def test_hace_falta_una_clave(self):
        tmp = tempfile.mkdtemp(prefix="botweb_recep2_")
        self.addCleanup(shutil.rmtree, tmp, True)
        alm = Almacen(os.path.join(tmp, "c.db"))
        self.addCleanup(alm.cerrar)
        with self.assertRaises(puente.ErrorPuente):
            puente.Receptor(alm, "", puerto=0, direccion="127.0.0.1")

    def test_una_direccion_de_fuera_de_la_red_local_no_vale(self):
        tmp = tempfile.mkdtemp(prefix="botweb_recep3_")
        self.addCleanup(shutil.rmtree, tmp, True)
        alm = Almacen(os.path.join(tmp, "c.db"))
        self.addCleanup(alm.cerrar)
        for mala in ("0.0.0.0", "8.8.8.8"):
            with self.assertRaises(puente.ErrorPuente):
                puente.Receptor(alm, CLAVE, puerto=0, direccion=mala)

    def test_que_direcciones_son_de_la_red_local(self):
        for buena in ("192.168.1.50", "10.0.0.7", "172.20.3.4", "127.0.0.1"):
            self.assertTrue(puente.es_privada(buena), buena)
        for mala in ("8.8.8.8", "200.1.2.3", "no-es-una-ip"):
            self.assertFalse(puente.es_privada(mala), mala)
        self.assertFalse(puente.es_privada("127.0.0.1", con_local=False))


# =========================================================== 4. la pantalla (API)
class TestApiErrores(BaseApi):
    def test_al_principio_esta_todo_apagado(self):
        r = self.api("GET", "errores")
        self.assertFalse(r["recibir"]["activo"])
        self.assertFalse(r["recibir"]["pedido"])
        self.assertEqual(r["enviar"]["a"], "")
        self.assertEqual(r["lista"], [])
        self.assertEqual(r["sin_leer"], 0)

    def test_guardar_a_donde_mandar_sin_devolver_nunca_la_clave(self):
        r = self.api("PUT", "errores/enviar", {"a": "http://192.168.1.50:8765", "equipo": "Caja 2", "clave": CLAVE})
        self.assertEqual(r["enviar"]["a"], "http://192.168.1.50:8765")
        self.assertEqual(r["enviar"]["equipo"], "Caja 2")
        self.assertTrue(r["enviar"]["tiene_clave"])
        self.assertNotIn(CLAVE, json.dumps(r), "la clave de enviar no puede salir por la API")
        self.assertEqual(self.alm.clave("enviar"), CLAVE)

    def test_la_clave_no_sale_en_los_ajustes_normales(self):
        self.api("PUT", "errores/enviar", {"a": "http://192.168.1.50:8765", "clave": CLAVE})
        self.assertNotIn(CLAVE, json.dumps(self.api("GET", "ajustes")))

    def test_una_clave_nueva_para_recibir(self):
        r = self.api("POST", "errores/clave")
        clave = r["recibir"]["clave"]
        self.assertTrue(clave)
        self.assertNotEqual(self.api("POST", "errores/clave")["recibir"]["clave"], clave)

    def test_el_puerto_tiene_que_ser_razonable(self):
        codigo, r = self.llamar("PUT", "api/errores/recibir", {"activo": True, "puerto": 80})
        self.assertEqual(codigo, 400)
        self.assertIn("1024", r["error"])

    def test_la_lista_el_detalle_y_marcarlos_vistos(self):
        for i in (1, 2):
            self.alm.guardar_error_recibido({"uuid": "u%d" % i, "equipo": "Caja %d" % i, "reporte": "Informes",
                                             "mensaje": "Error en el paso %d: X" % i, "registro": "el registro %d" % i})
        self.assertEqual(self.api("GET", "estado")["errores_otros"], 2)
        r = self.api("GET", "errores")
        self.assertEqual([x["equipo"] for x in r["lista"]], ["Caja 2", "Caja 1"], "lo más nuevo primero")
        self.assertNotIn("registro", r["lista"][0], "la lista no arrastra los registros enteros")
        eid = r["lista"][0]["id"]
        det = self.api("GET", "errores/%d" % eid)
        self.assertEqual(det["error"]["registro"], "el registro 2")
        self.assertEqual(self.api("GET", "errores")["sin_leer"], 1, "abrirlo lo marca como visto")
        self.assertEqual(self.api("POST", "errores/vistos")["sin_leer"], 0)
        self.assertEqual(self.api("DELETE", "errores")["sin_leer"], 0)
        self.assertEqual(self.api("GET", "errores")["lista"], [])

    def test_un_error_que_ya_no_esta(self):
        self.assertEqual(self.llamar("GET", "api/errores/999")[0], 404)

    def test_probar_el_envio_cuando_no_hay_a_donde(self):
        r = self.api("POST", "errores/probar")
        self.assertFalse(r["ok"])
        self.assertIn("dirección", r["mensaje"])


# =========================================================== 4b. la pantalla (navegador oculto)
@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestPantallaErrores(BaseApi):
    """Que se vea lo que tiene que verse: la clave para copiar en Ajustes y la lista en Historial."""

    def pagina(self):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self.addCleanup(self._p.stop)
        nav = self._p.chromium.launch(channel="chrome", headless=True)
        self.addCleanup(nav.close)
        pg = nav.new_page(viewport={"width": 1280, "height": 900})
        self.errores_js = []
        pg.on("pageerror", lambda e: self.errores_js.append(str(e)))
        return pg

    def test_ajustes_ensena_la_clave_para_copiarla_y_guarda_a_donde_mandar(self):
        self.alm.guardar_clave("recibir", CLAVE)
        self.alm.guardar_ajustes({"recibir_errores": True})
        self.app.receptor = _ReceptorDeMentira()
        pg = self.pagina()
        pg.goto(self.srv.url_con_token("ajustes"), wait_until="load")
        pg.wait_for_selector("[data-copiar-clave]", timeout=20000)
        texto = pg.inner_text("#contenido")
        self.assertIn(CLAVE, texto, "la clave se enseña para copiarla en las otras computadoras")
        self.assertIn("192.168.1.50:8765", texto)
        pg.fill('#contenido input[placeholder="http://192.168.1.50:8765"]', "http://192.168.1.77:8765")
        pg.fill('#contenido input[placeholder="Caja 2"]', "Caja 9")
        pg.click("[data-enviar-guardar]")
        pg.wait_for_timeout(1200)
        a = self.alm.ajustes()
        self.assertEqual(a["enviar_errores_a"], "http://192.168.1.77:8765")
        self.assertEqual(a["nombre_equipo"], "Caja 9")
        self.assertEqual(self.errores_js, [])

    def test_historial_ensena_los_errores_de_otras_computadoras(self):
        self.alm.guardar_error_recibido({"uuid": "u1", "equipo": "Caja 2", "reporte": "Comprobantes",
                                         "paso": "paso 4", "mensaje": "Error en el paso 4: no apareció X",
                                         "registro": "el registro que llegó"})
        pg = self.pagina()
        pg.goto(self.srv.url_con_token("historial"), wait_until="load")
        pg.wait_for_selector("[data-error-otro]", timeout=20000)
        self.assertIn("Caja 2", pg.inner_text("[data-error-otro]"))
        self.assertEqual(pg.inner_text("#cuenta-errores"), "1", "el número sobre «Historial»")
        pg.click("[data-error-otro]")
        pg.wait_for_selector("pre.registro", timeout=20000)
        self.assertIn("el registro que llegó", pg.inner_text("pre.registro"))
        pg.wait_for_function("() => document.querySelector('#cuenta-errores').classList.contains('oculto')",
                             timeout=20000)
        self.assertEqual(self.alm.errores_sin_leer(), 0)
        self.assertEqual(self.errores_js, [])


class _ReceptorDeMentira:
    """Para la pantalla: se ve «encendido» sin abrir ningún puerto."""
    url = "http://192.168.1.50:8765"


# =========================================================== 5. sin ventana negra
class TestSinVentanaNegra(unittest.TestCase):
    """Con pythonw.exe no hay consola: los mensajes tienen que acabar en registros/consola.log."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_consola_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from webbot import consola
        self.consola = consola
        self.stdout, self.stderr = sys.stdout, sys.stderr
        self.addCleanup(self.restaurar)

    def restaurar(self):
        sys.stdout, sys.stderr = self.stdout, self.stderr

    def test_con_consola_no_se_toca_nada(self):
        self.assertTrue(self.consola.hay_consola())
        self.assertEqual(self.consola.preparar(self.tmp), "")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, self.consola.NOMBRE)))

    def test_sin_consola_los_mensajes_van_al_archivo(self):
        sys.stdout = sys.stderr = None
        self.assertFalse(self.consola.hay_consola())
        ruta = self.consola.preparar(self.tmp)
        self.assertEqual(ruta, os.path.join(self.tmp, "consola.log"))
        print("un mensaje del programa")
        print("un error", file=sys.stderr)
        sys.stdout.flush()
        texto = open(ruta, encoding="utf-8").read()
        self.restaurar()
        self.assertIn("un mensaje del programa", texto)
        self.assertIn("un error", texto)

    def test_si_no_se_puede_escribir_print_no_revienta(self):
        sys.stdout = sys.stderr = None
        ruta = os.path.join(self.tmp, "no-existe-esta-carpeta")
        open(ruta, "w").close()                       # un archivo donde debería ir la carpeta: no se puede crear
        self.assertEqual(self.consola.preparar(ruta), "")
        print("esto no debe reventar")                 # (si reventara, la prueba falla aquí)
        self.restaurar()

    def test_el_archivo_no_crece_sin_fin(self):
        ruta = os.path.join(self.tmp, self.consola.NOMBRE)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("x" * (self.consola.MAX_BYTES + 10))
        sys.stdout = sys.stderr = None
        self.consola.preparar(self.tmp)
        print("empieza otro")
        sys.stdout.flush()
        self.restaurar()
        self.assertTrue(os.path.exists(ruta + ".1"), "el grande se guarda aparte")
        self.assertLess(os.path.getsize(ruta), 1000)


class TestArranqueSinConsola(unittest.TestCase):
    """Los archivos con los que se abre el programa (lo que el usuario toca con doble clic)."""

    def leer(self, nombre):
        return open(os.path.join(RAIZ, nombre), encoding="utf-8", errors="replace").read()

    def test_estan_los_tres_archivos(self):
        for nombre in ("Bot Web.vbs", "iniciar_oculto.cmd", "iniciar.bat"):
            self.assertTrue(os.path.isfile(os.path.join(RAIZ, nombre)), nombre)

    def test_el_de_doble_clic_abre_sin_ventana(self):
        vbs = self.leer("Bot Web.vbs")
        self.assertIn("iniciar_oculto.cmd", vbs)
        self.assertIn(".Run(", vbs.replace("sh.Run(", ".Run("))
        self.assertIn(", 0, True", vbs, "la ventana va escondida (0)")
        cmd = self.leer("iniciar_oculto.cmd")
        self.assertIn("pythonw.exe", cmd)
        self.assertIn("bot.py", cmd)
        self.assertIn("consola.log", cmd, "los mensajes tienen que ir al archivo")

    def test_iniciar_bat_sigue_siendo_el_de_ver_los_mensajes(self):
        bat = self.leer("iniciar.bat")
        self.assertIn("python bot.py", bat)
        self.assertIn("MENSAJES", bat.upper())

    def test_el_programa_cuenta_si_se_cae(self):
        import bot
        self.assertTrue(hasattr(bot, "principal_protegido"))
        llamadas = []
        bot.principal = lambda argv=None: (_ for _ in ()).throw(RuntimeError("se rompió"))
        try:
            puente_real = puente.anotar_fallo
            puente.anotar_fallo = lambda *a, **k: llamadas.append(a)
            codigo = bot.principal_protegido([])
        finally:
            puente.anotar_fallo = puente_real
            import importlib
            importlib.reload(bot)
        self.assertEqual(codigo, 1)


# =========================================================== 6. el logotipo
class TestLogotipo(unittest.TestCase):
    UI = os.path.join(RAIZ, "ui")

    def test_estan_las_tres_opciones_y_la_elegida(self):
        for nombre in ("logo-descarga.svg", "logo-ventana.svg", "logo-repetir.svg", "logo.svg"):
            self.assertTrue(os.path.isfile(os.path.join(self.UI, nombre)), nombre)

    def test_son_dibujos_planos_y_sin_nada_de_fuera(self):
        for nombre in ("logo-descarga.svg", "logo-ventana.svg", "logo-repetir.svg"):
            t = open(os.path.join(self.UI, nombre), encoding="utf-8").read()
            self.assertIn("<svg", t)
            self.assertIn('viewBox="0 0 40 40"', t)
            self.assertNotIn("Gradient", t, "plano: sin degradados")
            self.assertNotIn("http://www.w3.org/1999/xlink", t)
            self.assertNotIn("<image", t, "nada de fuera: solo formas")
            self.assertLess(len(t), 4000)

    def test_la_cabecera_y_la_pestana_usan_el_logotipo(self):
        html = open(os.path.join(self.UI, "index.html"), encoding="utf-8").read()
        self.assertIn('rel="icon" href="logo.svg"', html)
        self.assertIn('class="logo"', html)
        self.assertIn('src="logo.svg"', html)
        self.assertNotIn('>B</a>', html, "ya no es la letra suelta")

    def test_el_icono_del_acceso_directo_tiene_el_tamano_pequeno(self):
        """El instalador pone como icono el .ico que encuentre: tiene que tener también el de 16 px."""
        ruta = os.path.join(self.UI, "bot-web.ico")
        self.assertTrue(os.path.isfile(ruta))
        with open(ruta, "rb") as f:
            cabecera = f.read(6)
            reservado, tipo, cuantos = struct.unpack("<HHH", cabecera)
            self.assertEqual((reservado, tipo), (0, 1), "no parece un .ico")
            tamanos = set()
            for _ in range(cuantos):
                ancho = f.read(16)[0]
                tamanos.add(ancho or 256)
        self.assertIn(16, tamanos)
        self.assertIn(256, tamanos)


if __name__ == "__main__":
    unittest.main()
