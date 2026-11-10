"""Pruebas de integración: sitio local de prueba + navegador oculto (Chrome vía Playwright).

Nunca usan el ratón ni el teclado reales ni ventanas visibles, y las contraseñas viven
en un almacén en memoria (no se toca el Administrador de credenciales de Windows).
"""

import contextlib
import datetime
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from servidor_prueba import ServidorPrueba  # noqa: E402
from webbot import secretos  # noqa: E402
from webbot.ejecutor import Ejecutor  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402
from webbot.grabador_web import GrabadorWeb  # noqa: E402

try:
    import playwright  # noqa: F401
    HAY_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    HAY_PLAYWRIGHT = False

HOY = datetime.date(2026, 3, 15)
CLAVE = "clave-de-prueba-123"


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class BaseIntegracion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = ServidorPrueba().iniciar()
        cls.base = cls.servidor.url_base

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.almacen = secretos.AlmacenMemoria()
        secretos.usar_almacen(self.almacen)
        self.addCleanup(secretos.usar_almacen, None)
        self.descargas = os.path.join(self.tmp, "descargas")
        self.registros = os.path.join(self.tmp, "registros")

    def ejecutar(self, flujo, nombre_perfil="perfil_ejec", **kw):
        kw.setdefault("pausa_entre_pasos", 0)      # las pruebas no necesitan la pausa de 0,3 s entre pasos
        ej = Ejecutor(flujo, carpeta_perfil=os.path.join(self.tmp, nombre_perfil),
                      carpeta_registros=self.registros, carpeta_descargas=self.descargas,
                      oculto=True, hoy=HOY, **kw)
        return ej.ejecutar()

    def leer_log(self, resultado):
        with open(resultado.ruta_log, encoding="utf-8") as f:
            return f.read()


class TestEjecutor(BaseIntegracion):
    def flujo_a_mano(self):
        f = Flujo(nombre="Prueba A", url=self.base + "index.html", variables={"cliente": "acme"})
        f.opciones["timeout_paso"] = 15
        f.pasos = [
            Paso("abrir_url", url="{base}index.html".replace("{base}", self.base)),
            Paso("escribir", selectores=["#usuario"], valor="demo"),
            Paso("escribir", selectores=["#clave"], valor="{secreto:prueba:clave}"),
            Paso("clic", selectores=['role=button[name="Entrar"]']),
            Paso("esperar_elemento", selectores=["#generar"]),
            Paso("escribir", selectores=["#fecha"], valor="{hoy:%Y-%m-%d}"),
            Paso("seleccionar", selectores=["#cliente"], valor="{cliente}"),
            Paso("clic", selectores=["#generar"]),
            Paso("esperar_texto", texto="Reporte listo"),
            Paso("esperar_elemento", selectores=["#resultado"]),
            Paso("clic", selectores=["#resultado"], boton="derecho"),
            Paso("descargar", selectores=['role=menuitem[name="Exportar CSV"]'],
                 nombre="Reporte_{hoy:%Y-%m-%d}_{cliente}{ext}"),
        ]
        return f

    def test_a_flujo_escrito_a_mano_descarga_renombrada(self):
        secretos.guardar("prueba:clave", CLAVE)
        mensajes = []
        res = self.ejecutar(self.flujo_a_mano(), log=mensajes.append)
        self.assertTrue(res.ok, res.resumen())
        self.assertEqual(res.completados, 12)
        destino = os.path.join(self.descargas, "Reporte_2026-03-15_acme.csv")
        self.assertEqual(res.archivos, [destino])
        with open(destino, encoding="utf-8") as f:
            contenido = f.read()
        self.assertIn("2026-03-15,acme,1234", contenido)
        # El registro existe, tiene los pasos y NO contiene la contraseña.
        log = self.leer_log(res)
        self.assertIn("Paso 12/12", log)
        self.assertIn("OK (", log)
        self.assertNotIn(CLAVE, log)
        self.assertNotIn(CLAVE, "\n".join(mensajes))
        self.assertRegex(os.path.basename(res.ruta_log), r"^\d{4}-\d{2}-\d{2}_\d{6}\.log$")

    def test_paso_opcional_que_falla_se_omite_y_obligatorio_se_detiene(self):
        f = Flujo(nombre="Prueba C", url=self.base + "index.html")
        f.pasos = [
            Paso("abrir_url", url=self.base + "index.html"),
            Paso("clic", selectores=["#no-existe"], opcional=True, timeout=1, nota="aviso que a veces sale"),
            Paso("escribir", selectores=["#usuario"], valor="demo"),
            Paso("clic", selectores=["#tampoco-existe"], timeout=1),
            Paso("escribir", selectores=["#usuario"], valor="no debe ejecutarse"),
        ]
        res = self.ejecutar(f)
        self.assertFalse(res.ok)
        self.assertEqual(res.omitidos, 1)
        self.assertEqual(res.completados, 2)
        self.assertEqual(res.paso_fallido, 4)
        self.assertTrue(res.ruta_captura.endswith("_error_paso4.png"))
        self.assertTrue(os.path.getsize(res.ruta_captura) > 1000)
        log = self.leer_log(res)
        self.assertIn("OMITIDO", log)
        self.assertIn("ERROR", log)
        self.assertNotIn("no debe ejecutarse", log)

    def test_falta_contrasena_guardada_no_abre_el_navegador(self):
        res = self.ejecutar(self.flujo_a_mano())      # sin guardar el secreto
        self.assertFalse(res.ok)
        self.assertIn("prueba:clave", res.error)
        self.assertEqual(res.completados, 0)


class TestGrabador(BaseIntegracion):
    def grabar(self, conducir, flujo=None):
        """Graba oculto: `conducir(grabador)` se ejecuta en el hilo de trabajo y maneja la página."""
        flujo = flujo or Flujo(nombre="Grabado", url=self.base + "index.html")
        eventos = []

        def al_evento(tipo, **datos):
            eventos.append((tipo, datos))

        grab = GrabadorWeb(flujo, os.path.join(self.tmp, "perfil_grab"), oculto=True,
                           al_evento=al_evento, hoy=HOY,
                           carpeta_descargas_grabacion=os.path.join(self.tmp, "grabacion"))
        error = []

        def trabajo():
            try:
                grab.grabar(flujo.url)
            except BaseException as e:  # pragma: no cover
                error.append(e)

        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()
        self.assertTrue(grab.esperar_listo(60), "el navegador no arrancó")
        try:
            grab.solicitar(conducir).result(timeout=90)
            grab.detener()
        except BaseException:
            grab.detener()
            raise
        finally:
            hilo.join(30)
        self.assertFalse(hilo.is_alive(), "el hilo de grabación no terminó")
        self.assertEqual(error, [])
        return flujo, eventos

    def test_b_graba_y_reejecuta(self):
        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#usuario")
            pg.fill("#usuario", "demo")
            pg.fill("#clave", CLAVE)
            pg.get_by_role("button", name="Entrar").click()
            pg.wait_for_selector("#generar")
            pg.fill("#fecha", HOY.isoformat())
            # La lista se maneja con el teclado (eventos reales; select_option envía eventos sintéticos
            # que el grabador ignora a propósito, igual que los clics lanzados por scripts de la página).
            pg.focus("#cliente")
            pg.keyboard.press("ArrowDown")
            pg.keyboard.press("ArrowDown")
            pg.click("#generar")
            # Barra flotante: «Esperar a un elemento» y luego clic sobre lo que hay que esperar.
            pg.get_by_role("button", name="Esperar a un elemento").click()
            pg.click("#resultado")                       # espera automática hasta que sea visible (≈2 s)
            # Barra flotante: «Esperar texto…»
            pg.get_by_role("button", name="Esperar texto…").click()
            pg.locator("#__bot_host__ input").fill("Reporte listo")
            pg.get_by_role("button", name="Añadir").click()
            pg.click("#resultado", button="right")
            pg.click("#m-csv")
            pg.wait_for_timeout(800)

        flujo, eventos = self.grabar(conducir)
        tipos = [p.tipo for p in flujo.pasos]
        # v2.3: usuario + contraseña + «Entrar» se graban como un único paso «Iniciar sesión (si hace falta)».
        self.assertEqual(tipos, [
            "abrir_url", "iniciar_sesion", "escribir", "seleccionar", "clic",
            "esperar_elemento", "esperar_texto", "clic", "descargar"], tipos)
        abrir, login, fecha, cliente, generar, espera_el, espera_txt, derecho, desc = flujo.pasos

        self.assertEqual(abrir.url, self.base + "index.html")
        self.assertEqual(login.sitio, "127.0.0.1")
        usuario, clave = login.campos
        self.assertEqual((usuario["selectores"][0], usuario["tipo"], usuario["valor"]), ("#usuario", "texto", "demo"))
        # Contraseña: nunca en claro; va al almacén de secretos.
        self.assertEqual((clave["selectores"][0], clave["tipo"]), ("#clave", "clave"))
        self.assertEqual(clave["secreto"], "127.0.0.1:clave")
        self.assertNotIn("valor", clave)
        self.assertEqual(secretos.obtener("127.0.0.1:clave"), CLAVE)
        self.assertNotIn(CLAVE, flujo.a_json())
        self.assertNotIn(CLAVE, repr(eventos))
        self.assertEqual(login.enviar["selectores"][0], 'role=button[name="Entrar"]')
        self.assertEqual(fecha.valor, HOY.isoformat())
        self.assertEqual((cliente.selectores[0], cliente.valor, cliente.etiqueta), ("#cliente", "globex", "Globex"))
        self.assertEqual(generar.selectores[0], "#generar")
        self.assertEqual(espera_el.selectores[0], "#resultado")
        self.assertEqual(espera_txt.texto, "Reporte listo")
        self.assertEqual(derecho.boton, "derecho")
        self.assertEqual(derecho.selectores[0], "#resultado")
        self.assertEqual(desc.selectores[0], "#m-csv")
        self.assertIn('role=menuitem[name="Exportar CSV"]', desc.selectores)   # alternativa por rol + nombre
        # v3.5: el archivo se llama como el reporte (nombre completo) + la fecha; el de la web es {nombre}
        self.assertEqual(desc.nombre, "{reporte} {hoy:%Y-%m-%d}{ext}")
        self.assertTrue(all(len(p.selectores) >= 1 for p in flujo.pasos if p.tipo in ("clic", "escribir")))
        # La barra flotante no genera pasos propios y se ofreció convertir la fecha.
        sugerencias = [d for t, d in eventos if t == "sugerencia"]
        self.assertEqual([s["plantilla"] for s in sugerencias], ["{hoy:%Y-%m-%d}"])

        # El usuario acepta la fecha dinámica y renombra la descarga con una plantilla.
        fecha.valor = sugerencias[0]["plantilla"]
        desc.nombre = "Reporte_{hoy:%Y-%m-%d}_{cliente}{ext}"
        flujo.variables["cliente"] = "globex"
        flujo.opciones["timeout_paso"] = 15
        # Round-trip JSON conserva todo.
        flujo2 = Flujo.desde_json(flujo.a_json())
        self.assertEqual(flujo2.a_dict(), flujo.a_dict())

        # Se vuelve a ejecutar lo grabado, en otro perfil limpio y con otro almacén de secretos.
        secretos.usar_almacen(secretos.AlmacenMemoria())
        secretos.guardar("127.0.0.1:clave", CLAVE)
        res = self.ejecutar(flujo2, nombre_perfil="perfil_ejec_b")
        self.assertTrue(res.ok, res.resumen())
        destino = os.path.join(self.descargas, "Reporte_2026-03-15_globex.csv")
        self.assertEqual(res.archivos, [destino])
        with open(destino, encoding="utf-8") as f:
            self.assertIn("2026-03-15,globex,1234", f.read())
        self.assertNotIn(CLAVE, self.leer_log(res))

    def test_grabacion_de_pestana_nueva(self):
        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#usuario")
            pg.fill("#usuario", "demo")
            pg.fill("#clave", CLAVE)
            pg.get_by_role("button", name="Entrar").click()
            pg.wait_for_selector("#ayuda")
            with g.contexto.expect_page() as nueva:
                pg.click("#ayuda")
            ayuda = nueva.value
            ayuda.wait_for_selector("#entendido")
            g.paginas  # la nueva pestaña ya está registrada
            ayuda.click("#entendido")
            ayuda.wait_for_timeout(500)

        flujo, _ = self.grabar(conducir)
        ultimo = flujo.pasos[-1]
        self.assertEqual((ultimo.tipo, ultimo.pagina), ("clic", 1))
        self.assertEqual(ultimo.selectores[0], "#entendido")
        self.assertTrue(all(p.pagina == 0 for p in flujo.pasos[:-1]))
        self.assertEqual(flujo.pasos[-2].selectores[0], "#ayuda")
        # Se re-ejecuta y se comprueba el efecto en la pestaña 2.
        flujo.pasos.append(Paso("esperar_texto", texto="Gracias", pagina=1))
        flujo.opciones["timeout_paso"] = 15
        res = self.ejecutar(flujo, nombre_perfil="perfil_ejec_pop")
        self.assertTrue(res.ok, res.resumen())


    def test_grabacion_dentro_de_un_iframe(self):
        def conducir(g):
            pg = g.paginas[0]
            pg.goto(self.base + "marco.html")
            pg.frame_locator("#panel").locator("#entendido").click()
            pg.wait_for_timeout(500)

        flujo, _ = self.grabar(conducir)
        ultimo = flujo.pasos[-1]
        self.assertEqual(ultimo.tipo, "clic")
        self.assertEqual(ultimo.selectores[0], "#entendido")
        self.assertEqual(ultimo.marco, ["#panel"])
        flujo.pasos.append(Paso("esperar_elemento", selectores=['p:text-is("Gracias")'], marco=["#panel"]))
        flujo.pasos[0].url = self.base + "marco.html"
        flujo.opciones["timeout_paso"] = 15
        res = self.ejecutar(flujo, nombre_perfil="perfil_ejec_marco")
        self.assertTrue(res.ok, res.resumen())


class TestLineaDeComandos(BaseIntegracion):
    def test_sin_ventana_oculto_con_variables_y_url(self):
        import bot
        f = Flujo(nombre="CLI", url="http://sitio-que-se-sustituye/")
        f.opciones["timeout_paso"] = 15
        f.pasos = TestEjecutor.flujo_a_mano(self).pasos
        f.pasos[0].url = "http://sitio-que-se-sustituye/index.html"
        f.pasos[6].valor = "{cliente}"
        f.variables = {}
        ruta = os.path.join(self.tmp, "cli.json")
        f.guardar(ruta)
        secretos.guardar("prueba:clave", CLAVE)
        salida = io.StringIO()
        argv = ["--flujo", ruta, "--sin-ventana", "--oculto", "--url", self.base + "index.html",
                "--var", "cliente=globex", "--descargas", self.descargas, "--registros", self.registros,
                "--perfil", os.path.join(self.tmp, "perfil_cli")]
        with contextlib.redirect_stdout(salida):
            codigo = bot.principal(argv)
        self.assertEqual(codigo, 0, salida.getvalue())
        self.assertNotIn(CLAVE, salida.getvalue())
        archivos = os.listdir(self.descargas)
        self.assertEqual(len(archivos), 1)
        self.assertRegex(archivos[0], r"^Reporte_\d{4}-\d{2}-\d{2}_globex\.csv$")

    def test_codigo_de_salida_1_si_falla_un_paso(self):
        import bot
        f = Flujo(nombre="CLI error")
        f.pasos = [Paso("abrir_url", url=self.base + "index.html"),
                   Paso("clic", selectores=["#nada"], timeout=1)]
        ruta = os.path.join(self.tmp, "cli_error.json")
        f.guardar(ruta)
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = bot.principal(["--flujo", ruta, "--sin-ventana", "--oculto", "--registros", self.registros,
                                    "--perfil", os.path.join(self.tmp, "perfil_cli2")])
        self.assertEqual(codigo, 1)
        self.assertIn("ERROR", salida.getvalue())
        self.assertTrue(any(n.endswith(".png") for n in os.listdir(self.registros)))


if __name__ == "__main__":
    unittest.main()
