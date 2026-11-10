"""Pruebas de la versión 3.7: instalar el bot en otro PC («Instalar Bot Web.cmd»).

1. `navegador`: si Chrome no está instalado se usa Edge (y al revés), con UNA línea en el registro, y se recuerda para
   el resto del proceso; si no hay ninguno, un error claro; los demás errores (perfil en uso…) no cambian de
   navegador.  También `lanzar` (navegador oculto auxiliar y --smoke-web) y `buscar_ejecutable`.
2. La ventana de la interfaz (`servidor_ui.buscar_navegador_app` / `abrir_ventana`) funciona con solo Edge o solo Chrome.
3. Las tareas programadas usan el pythonw.exe del entorno (.venv) desde el que se ejecuta el bot.
4. requirements.txt incluye openpyxl, y el instalador y el desinstalador son un solo archivo .cmd cada uno.

Sin navegador de verdad (Playwright simulado), sin tareas de Windows y sin tocar el registro.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import navegador, programador, servidor_ui  # noqa: E402

FALTA = ("BrowserType.launch_persistent_context: Chromium distribution '%s' is not found at "
         "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\nRun \"playwright install %s\"")


class _Chromium:
    """Imita `playwright.chromium`: los canales de `faltan` dan el error de Playwright «not found»."""

    def __init__(self, faltan=(), otro_error=None):
        self.faltan = set(faltan)
        self.otro_error = otro_error
        self.llamadas = []

    def _abrir(self, channel, **kw):
        self.llamadas.append(channel)
        if channel in self.faltan:
            raise Exception(FALTA % (channel, channel))
        if self.otro_error:
            raise Exception(self.otro_error)
        return "contexto-" + channel

    def launch_persistent_context(self, carpeta, channel=None, **kw):
        return self._abrir(channel, **kw)

    def launch(self, channel=None, **kw):
        return self._abrir(channel, **kw)


class _Playwright:
    def __init__(self, **kw):
        self.chromium = _Chromium(**kw)


class PruebaRespaldoNavegador(unittest.TestCase):
    def setUp(self):
        navegador._sustituto.clear()
        self.tmp = tempfile.mkdtemp(prefix="botweb_v37i_")
        self.lineas = []

    def tearDown(self):
        navegador._sustituto.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sin_chrome_usa_edge_y_lo_recuerda(self):
        pw = _Playwright(faltan={"chrome"})
        ctx = navegador.abrir_contexto(pw, self.tmp, "chrome", oculto=True, log=self.lineas.append)
        self.assertEqual(ctx, "contexto-msedge")
        self.assertEqual(pw.chromium.llamadas, ["chrome", "msedge"])
        self.assertEqual(self.lineas, ["Chrome no está instalado en este equipo: se usa Edge."])
        # la segunda vez va directo a Edge, sin otro intento ni otra línea
        ctx = navegador.abrir_contexto(pw, self.tmp, "chrome", oculto=True, log=self.lineas.append)
        self.assertEqual(ctx, "contexto-msedge")
        self.assertEqual(pw.chromium.llamadas, ["chrome", "msedge", "msedge"])
        self.assertEqual(len(self.lineas), 1)
        self.assertEqual(navegador.canal_efectivo("chrome"), "msedge")

    def test_sin_edge_usa_chrome(self):
        pw = _Playwright(faltan={"msedge"})
        ctx = navegador.abrir_contexto(pw, self.tmp, "msedge", log=self.lineas.append)
        self.assertEqual(ctx, "contexto-chrome")
        self.assertEqual(self.lineas, ["Edge no está instalado en este equipo: se usa Chrome."])

    def test_con_chrome_no_cambia_nada(self):
        pw = _Playwright()
        self.assertEqual(navegador.abrir_contexto(pw, self.tmp, "chrome", log=self.lineas.append), "contexto-chrome")
        self.assertEqual(pw.chromium.llamadas, ["chrome"])
        self.assertEqual(self.lineas, [])

    def test_sin_ninguno_error_claro(self):
        pw = _Playwright(faltan={"chrome", "msedge"})
        with self.assertRaises(navegador.ErrorNavegador) as e:
            navegador.abrir_contexto(pw, self.tmp, "chrome", log=self.lineas.append)
        self.assertIn("ni Edge", str(e.exception))
        self.assertEqual(navegador.canal_efectivo("chrome"), "chrome")       # no se queda recordado

    def test_otro_error_no_cambia_de_navegador(self):
        pw = _Playwright(otro_error="Target page, context or browser has been closed (perfil en uso)")
        with self.assertRaises(navegador.ErrorNavegador) as e:
            navegador.abrir_contexto(pw, self.tmp, "chrome", log=self.lineas.append)
        self.assertEqual(pw.chromium.llamadas, ["chrome"])
        self.assertIn("No se pudo abrir Chrome", str(e.exception))
        self.assertEqual(self.lineas, [])

    def test_edge_falla_por_otra_cosa_tras_faltar_chrome(self):
        pw = _Playwright(faltan={"chrome"})
        pw.chromium.otro_error = "perfil en uso"
        with self.assertRaises(navegador.ErrorNavegador) as e:
            navegador.abrir_contexto(pw, self.tmp, "chrome", log=self.lineas.append)
        self.assertIn("No se pudo abrir Edge", str(e.exception))

    def test_lanzar_tambien_cambia(self):
        pw = _Playwright(faltan={"chrome"})
        self.assertEqual(navegador.lanzar(pw, "chrome", log=self.lineas.append, headless=True), "contexto-msedge")
        self.assertEqual(len(self.lineas), 1)

    def test_sin_log_usa_print_y_no_falla_sin_consola(self):
        pw = _Playwright(faltan={"chrome"})
        with mock.patch("builtins.print") as p:
            self.assertEqual(navegador.lanzar(pw, "chrome"), "contexto-msedge")
        p.assert_called_once()
        navegador._sustituto.clear()
        with mock.patch("builtins.print", side_effect=OSError("sin consola")):
            self.assertEqual(navegador.lanzar(pw, "chrome"), "contexto-msedge")

    def test_navegador_no_valido(self):
        with self.assertRaises(navegador.ErrorNavegador):
            navegador.abrir_contexto(_Playwright(), self.tmp, "firefox")
        with self.assertRaises(navegador.ErrorNavegador):
            navegador.lanzar(_Playwright(), "firefox")

    def test_falta_navegador(self):
        self.assertTrue(navegador.falta_navegador(Exception(FALTA % ("chrome", "chrome"))))
        self.assertFalse(navegador.falta_navegador(Exception("net::ERR_NAME_NOT_RESOLVED")))
        self.assertFalse(navegador.falta_navegador(Exception("Target closed")))


class PruebaBuscarEjecutable(unittest.TestCase):
    def test_en_archivos_de_programa(self):
        edge = os.path.join("C:\\PF86", "Microsoft", "Edge", "Application", "msedge.exe")
        with mock.patch.dict(os.environ, {"ProgramFiles": "C:\\PF", "ProgramFiles(x86)": "C:\\PF86",
                                          "ProgramW6432": "C:\\PF", "LOCALAPPDATA": "C:\\LA"}), \
                mock.patch("os.path.isfile", side_effect=lambda r: r == edge):
            self.assertEqual(navegador.buscar_ejecutable("msedge"), edge)

    def test_en_app_paths_del_registro(self):
        import winreg
        chrome = "D:\\Otro sitio\\chrome.exe"

        class _Clave:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def abrir(raiz, clave, *a):
            if raiz == winreg.HKEY_LOCAL_MACHINE and clave.endswith("chrome.exe"):
                return _Clave()
            raise OSError("no está")

        with mock.patch("os.path.isfile", side_effect=lambda r: r == chrome), \
                mock.patch.object(winreg, "OpenKey", side_effect=abrir), \
                mock.patch.object(winreg, "QueryValue", return_value='"%s"' % chrome):
            self.assertEqual(navegador.buscar_ejecutable("chrome"), chrome)

    def test_no_instalado(self):
        import winreg
        with mock.patch("os.path.isfile", return_value=False), \
                mock.patch.object(winreg, "OpenKey", side_effect=OSError("no")):
            self.assertIsNone(navegador.buscar_ejecutable("chrome"))


class PruebaVentanaInterfaz(unittest.TestCase):
    def _con(self, rutas):
        return mock.patch.object(navegador, "buscar_ejecutable", side_effect=lambda n: rutas.get(n))

    def test_solo_edge(self):
        with self._con({"msedge": "C:\\E\\msedge.exe"}), mock.patch("shutil.which", return_value=None):
            self.assertEqual(servidor_ui.buscar_navegador_app(), "C:\\E\\msedge.exe")

    def test_solo_chrome(self):
        with self._con({"chrome": "C:\\C\\chrome.exe"}), mock.patch("shutil.which", return_value=None):
            self.assertEqual(servidor_ui.buscar_navegador_app(), "C:\\C\\chrome.exe")

    def test_ninguno_abre_el_navegador_predeterminado(self):
        with self._con({}), mock.patch("shutil.which", return_value=None), \
                mock.patch("subprocess.Popen") as popen, mock.patch("webbrowser.open", return_value=True) as web:
            self.assertTrue(servidor_ui.abrir_ventana("http://127.0.0.1:1/"))
        popen.assert_not_called()
        web.assert_called_once()

    def test_abrir_ventana_con_solo_edge_usa_app(self):
        with self._con({"msedge": "C:\\E\\msedge.exe"}), mock.patch("subprocess.Popen") as popen, \
                mock.patch.object(servidor_ui, "carpeta", return_value=tempfile.gettempdir()):
            self.assertTrue(servidor_ui.abrir_ventana("http://127.0.0.1:1/"))
        args = popen.call_args[0][0]
        self.assertEqual(args[0], "C:\\E\\msedge.exe")
        self.assertIn("--app=http://127.0.0.1:1/", args)


class PruebaTareasConVenv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v37v_")
        self.scripts = os.path.join(self.tmp, "app", ".venv", "Scripts")
        os.makedirs(self.scripts)
        for n in ("python.exe", "pythonw.exe"):
            open(os.path.join(self.scripts, n), "wb").close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_desde_python_del_venv(self):
        with mock.patch.object(sys, "executable", os.path.join(self.scripts, "python.exe")):
            self.assertEqual(programador.ejecutable_python(), os.path.join(self.scripts, "pythonw.exe"))
            cmd = programador.comando_bot(os.path.join(self.tmp, "app", "bot.py"), ids=[3])
        self.assertTrue(cmd.startswith('"%s" ' % os.path.join(self.scripts, "pythonw.exe")), cmd)

    def test_desde_pythonw_del_venv(self):
        # (el acceso directo «Bot Web» abre el bot con el pythonw.exe del venv)
        with mock.patch.object(sys, "executable", os.path.join(self.scripts, "pythonw.exe")):
            self.assertEqual(programador.ejecutable_python(), os.path.join(self.scripts, "pythonw.exe"))


class PruebaArchivosInstalador(unittest.TestCase):
    CARPETA = os.path.join(RAIZ, "instalador")

    def test_requirements_con_openpyxl(self):
        with open(os.path.join(RAIZ, "requirements.txt"), encoding="utf-8") as f:
            nombres = [l.split(">")[0].split("=")[0].strip().lower() for l in f if l.strip() and not l.startswith("#")]
        self.assertEqual(sorted(nombres), ["keyring", "openpyxl", "playwright"])

    def test_cmd_de_un_solo_archivo(self):
        for nombre in ("Instalar Bot Web.cmd", "Desinstalar Bot Web.cmd"):
            with open(os.path.join(self.CARPETA, nombre), "rb") as f:
                datos = f.read()
            self.assertFalse(datos.startswith(b"\xef\xbb\xbf"), nombre)          # sin BOM (cmd lo leería mal)
            parte_cmd = datos.split(b"\n#>")[0]
            parte_cmd.decode("ascii")                                         # la parte de cmd, solo ASCII
            self.assertTrue(datos.startswith(b"<# :"), nombre)
            self.assertIn(b"-NoProfile -ExecutionPolicy Bypass", parte_cmd)
            texto = datos.decode("utf-8")
            self.assertNotIn("\n", texto.replace("\r\n", ""), nombre + ": debe tener finales de línea CRLF")

    def test_instalador_no_copia_datos(self):
        with open(os.path.join(self.CARPETA, "Instalar Bot Web.cmd"), encoding="utf-8") as f:
            texto = f.read()
        for carpeta in ("'datos'", "'perfiles'", "'registros'", "'descargas'", "'.git'", "'tests'", "'__pycache__'"):
            self.assertIn(carpeta, texto)
        self.assertIn("flujos\\*.json", texto)
        self.assertIn("https://github.com/Rfalso014/Mapez/archive/refs/heads/main.zip", texto)

    def test_desinstalador_usa_el_servicio_de_secretos(self):
        from webbot import secretos
        with open(os.path.join(self.CARPETA, "Desinstalar Bot Web.cmd"), encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("$Servicio = '%s'" % secretos.SERVICIO, texto)
        self.assertIn("'\\BotWeb\\'", texto)
        self.assertEqual(programador.CARPETA_TAREAS, "BotWeb")


if __name__ == "__main__":
    unittest.main()
