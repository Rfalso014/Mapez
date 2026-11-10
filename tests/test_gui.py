"""Pruebas de la ventana (tkinter) sin interacción humana: se llama a los métodos del panel «Reportes»
y de la lista de pasos con los cuadros de diálogo sustituidos.  No se usa el ratón ni el teclado reales.
La base de datos de reportes es siempre una temporal (nunca datos/bot.db)."""

import gc
import json
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import bot  # noqa: E402
from servidor_prueba import ServidorPrueba  # noqa: E402
from webbot import secretos  # noqa: E402
from webbot.almacen import nombre_perfil  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

try:
    import playwright  # noqa: F401
    HAY_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    HAY_PLAYWRIGHT = False


_RAIZ_TK = None


def _raiz_tk():
    """Un único intérprete Tk para todas las pruebas (varios en el mismo proceso dan problemas con los hilos)."""
    global _RAIZ_TK
    if _RAIZ_TK is None:
        _RAIZ_TK = tk.Tk()
        _RAIZ_TK.withdraw()
    return _RAIZ_TK


def tearDownModule():
    global _RAIZ_TK
    gc.collect()
    if _RAIZ_TK is not None:
        _RAIZ_TK.destroy()
        _RAIZ_TK = None


class BaseGui(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Toplevel(_raiz_tk())
        except tk.TclError:                     # pragma: no cover
            self.skipTest("no hay pantalla para tkinter")
        self.root.withdraw()
        self.tmp = tempfile.mkdtemp(prefix="botweb_gui_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(self._cerrar_ventana)
        self.almacen_claves = secretos.AlmacenMemoria()
        secretos.usar_almacen(self.almacen_claves)
        self.addCleanup(secretos.usar_almacen, None)
        self.carpeta = os.path.join(self.tmp, "flujos")
        os.makedirs(self.carpeta)
        self.cajas = []                          # mensajes que la ventana habría mostrado
        for nombre in ("showinfo", "showerror", "showwarning"):
            p = mock.patch.object(bot.messagebox, nombre, side_effect=lambda t, m, **kw: self.cajas.append((t, m)))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(bot.messagebox, "askyesno", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.respuesta_cambios = False           # askyesnocancel: False = descartar los cambios
        p = mock.patch.object(bot.messagebox, "askyesnocancel", side_effect=lambda *a, **kw: self.respuesta_cambios)
        p.start()
        self.addCleanup(p.stop)
        self.nombres = []                        # respuestas de simpledialog.askstring, en orden
        self.preguntas = []
        p = mock.patch.object(bot.simpledialog, "askstring", side_effect=self._askstring)
        p.start()
        self.addCleanup(p.stop)
        self.args = bot.analizar_argumentos(
            ["--carpeta-flujos", self.carpeta, "--registros", os.path.join(self.tmp, "reg"),
             "--perfil", os.path.join(self.tmp, "perf"), "--descargas", os.path.join(self.tmp, "desc"),
             "--db", os.path.join(self.tmp, "bot.db"), "--oculto"])
        self.app = bot.App(self.root, self.args)
        self.almacen = self.app.almacen

    def _askstring(self, titulo, mensaje, **kw):
        self.preguntas.append((titulo, kw.get("initialvalue")))
        return self.nombres.pop(0) if self.nombres else None

    def _cerrar_ventana(self):
        hilo = getattr(self.app, "hilo", None)
        if hilo is not None:
            hilo.join(30)                       # el hilo de trabajo no debe soltar objetos de Tk al terminar
        self.app.almacen.cerrar()
        self.app = None
        self.root.destroy()
        self.root = None
        gc.collect()

    def guardar(self, nombre, pasos, url="http://127.0.0.1/"):
        """Guarda un reporte en la base de datos de la ventana y devuelve su id."""
        f = Flujo(nombre=nombre, url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=3)
        f.pasos = pasos
        return self.almacen.guardar(f)

    def filas(self):
        return {self.app.arbol_rep.item(i, "values")[1]: self.app.arbol_rep.item(i, "values")
                for i in self.app.arbol_rep.get_children()}

    def esperar(self, condicion, segundos=90):
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            self.root.update()
            if condicion():
                return True
            time.sleep(0.05)
        return False


class TestPanelReportes(BaseGui):
    def test_lista_marcas_duplicar_renombrar_abrir_y_eliminar(self):
        a = self.guardar("Ventas", [Paso("abrir_url", url="http://a/")], url="http://a/")
        b = self.guardar("Clientes", [Paso("abrir_url", url="http://b/")], url="http://b/")
        self.almacen.registrar_ejecucion(a, "ok")
        self.almacen.registrar_ejecucion(b, "error", "fallo")
        app = self.app
        app._refrescar_reportes()
        filas = self.filas()
        self.assertEqual(sorted(filas), ["Clientes", "Ventas"])
        self.assertEqual(filas["Ventas"][2], "http://a/")
        self.assertEqual(filas["Ventas"][4], "Bien")
        self.assertRegex(filas["Ventas"][3], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual(filas["Clientes"][4], "Falló")
        self.assertEqual(filas["Clientes"][0], "☐")
        # marcar con la casilla (el clic en la primera columna)
        app.marcados.add(a)
        app._refrescar_reportes()
        self.assertEqual(app.arbol_rep.item(str(a), "values")[0], "☑")
        self.assertIn("1 marcado", app.v_rep_info.get())
        # duplicar el seleccionado
        app.arbol_rep.selection_set(str(a))
        app._rep_duplicar()
        self.assertIn("Ventas (copia)", self.filas())
        self.assertEqual(len(app.arbol_rep.get_children()), 3)
        # renombrar: conserva el id (y por tanto el perfil del navegador y el historial)
        app.arbol_rep.selection_set(str(a))
        self.nombres = ["Ventas diarias"]
        app._rep_renombrar()
        self.assertEqual(self.almacen.obtener(a)["nombre"], "Ventas diarias")
        self.assertEqual(self.almacen.ultima_ejecucion(a)["resultado"], "ok")
        self.assertIn("Ventas diarias", self.filas())
        # abrir (o doble clic) lo carga en el editor
        app.arbol_rep.selection_set(str(b))
        app._rep_abrir()
        self.assertEqual((app.v_nombre.get(), app.v_url.get(), app.reporte_id), ("Clientes", "http://b/", b))
        self.assertNotIn("*", app.root.title())
        # eliminar: se pide confirmación y va a la papelera (recuperable)
        app._rep_eliminar()
        self.assertIsNone(self.almacen.obtener(b))
        self.assertEqual([r["nombre"] for r in self.almacen.papelera()], ["Clientes"])
        self.assertEqual(len(app.arbol_rep.get_children()), 2)
        self.assertIsNone(app.reporte_id)
        dlg = bot.DialogoPapelera(self.root, self.almacen, al_cambiar=app._refrescar_reportes)
        dlg.arbol.selection_set(str(b))
        dlg._recuperar()
        dlg.destroy()
        self.assertIn("Clientes", self.filas())

    def test_ejecutar_sin_marcar_avisa(self):
        self.app._ejecutar_reportes(solo_marcados=True)
        self.assertTrue(any("Marca" in m for _, m in self.cajas), self.cajas)
        self.assertFalse(self.app.trabajando)

    def test_guardar_pide_solo_el_nombre_y_despues_actualiza(self):
        app = self.app
        app.v_url.set("http://x/")
        app.flujo.pasos = [Paso("abrir_url", url="http://x/"), Paso("clic", selectores=["#a"])]
        app._refrescar_lista()
        app._actualizar_titulo()
        self.assertTrue(app.root.title().startswith("Nuevo reporte*"))
        self.nombres = ["Mi reporte"]
        with mock.patch.object(bot.filedialog, "asksaveasfilename") as dialogo_archivo:
            self.assertTrue(app._guardar())
        dialogo_archivo.assert_not_called()                    # nada de archivos
        rid = app.reporte_id
        self.assertEqual(self.almacen.obtener(rid)["nombre"], "Mi reporte")
        self.assertEqual(self.preguntas[-1], ("Guardar reporte", "Nuevo reporte"))
        self.assertIn("Mi reporte", self.filas())
        app._actualizar_titulo()
        self.assertTrue(app.root.title().startswith("Mi reporte —"), app.root.title())
        # un cambio marca el título con «*»; «Guardar» actualiza el mismo reporte sin preguntar
        app.flujo.pasos.append(Paso("esperar_segundos", segundos=1))
        app._actualizar_titulo()
        self.assertTrue(app.root.title().startswith("Mi reporte*"))
        n_preguntas = len(self.preguntas)
        self.assertTrue(app._guardar())
        self.assertEqual(len(self.preguntas), n_preguntas)
        self.assertEqual(app.reporte_id, rid)
        self.assertEqual(len(self.almacen.cargar_flujo(rid).pasos), 3)
        self.assertFalse(app._hay_cambios_sin_guardar())
        # «Guardar como…» pide otro nombre y crea otro reporte
        self.nombres = ["Mi reporte (copia)"]
        self.assertTrue(app._guardar(como_nuevo=True))
        self.assertNotEqual(app.reporte_id, rid)
        self.assertEqual(sorted(self.filas()), ["Mi reporte", "Mi reporte (copia)"])

    def test_nombre_repetido_se_vuelve_a_pedir(self):
        self.guardar("Ventas", [Paso("abrir_url", url="http://a/")])
        app = self.app
        app.flujo.pasos = [Paso("abrir_url", url="http://x/")]
        self.nombres = ["ventas", "Ventas 2"]                   # mayúsculas/minúsculas no cuentan
        self.assertTrue(app._guardar())
        self.assertTrue(any("Ya existe" in m for _, m in self.cajas), self.cajas)
        self.assertEqual(app.flujo.nombre, "Ventas 2")
        # cancelar el nombre no guarda nada
        app._nuevo_flujo(confirmar=False)
        app.flujo.pasos = [Paso("abrir_url", url="http://y/")]
        self.nombres = []
        self.assertFalse(app._guardar())
        self.assertEqual(len(self.almacen.listar()), 2)

    def test_cambios_sin_guardar_se_preguntan_antes_de_abrir_otro(self):
        a = self.guardar("A", [Paso("abrir_url", url="http://a/")])
        b = self.guardar("B", [Paso("abrir_url", url="http://b/")])
        app = self.app
        app._refrescar_reportes()
        app._cargar_reporte(a)
        app.flujo.pasos.append(Paso("clic", selectores=["#nuevo"]))
        app.arbol_rep.selection_set(str(b))
        self.respuesta_cambios = None                            # Cancelar: se queda en A
        app._rep_abrir()
        self.assertEqual(app.reporte_id, a)
        self.respuesta_cambios = True                            # Sí: guarda A y abre B
        app._rep_abrir()
        self.assertEqual(app.reporte_id, b)
        self.assertEqual(len(self.almacen.cargar_flujo(a).pasos), 2)
        app.flujo.pasos.append(Paso("clic", selectores=["#otro"]))
        app.arbol_rep.selection_set(str(a))
        self.respuesta_cambios = False                           # No: descarta los cambios de B
        app._rep_abrir()
        self.assertEqual(app.reporte_id, a)
        self.assertEqual(len(self.almacen.cargar_flujo(b).pasos), 1)

    def test_al_terminar_la_grabacion_pide_el_nombre(self):
        app = self.app
        app.v_url.set("http://x/")
        perfil_grabacion = os.path.join(self.tmp, "perfil_grabado")
        os.makedirs(perfil_grabacion)
        app._perfil_sin_guardar = perfil_grabacion
        app.args.perfil = None                                    # como en la ventana normal
        app.flujo.pasos = [Paso("abrir_url", url="http://x/"), Paso("clic", selectores=["#a"])]
        self.nombres = ["Grabado hoy"]
        with mock.patch.object(bot, "carpeta", side_effect=lambda n: os.path.join(self.tmp, n)):
            app._ofrecer_guardar_grabacion()
        self.assertEqual(self.preguntas[-1][0], "Guardar la grabación")
        rid = app.reporte_id
        self.assertEqual(self.almacen.obtener(rid)["nombre"], "Grabado hoy")
        # el perfil del navegador de la grabación (con la sesión iniciada) pasa a ser el del reporte
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "perfiles", nombre_perfil(rid))))
        self.assertFalse(os.path.exists(perfil_grabacion))

    def test_exportar_e_importar_archivo(self):
        a = self.guardar("Ventas", [Paso("abrir_url", url="http://a/"), Paso("clic", selectores=["#x"])])
        app = self.app
        app._cargar_reporte(a)
        destino = os.path.join(self.tmp, "copia.json")
        with mock.patch.object(bot.filedialog, "asksaveasfilename", return_value=destino):
            app._exportar()
        with open(destino, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["nombre"], "Ventas")
        with mock.patch.object(bot.filedialog, "askopenfilename", return_value=destino):
            app._importar()
        self.assertEqual(app.flujo.nombre, "Ventas (2)")           # el nombre ya existía
        self.assertEqual(sorted(self.filas()), ["Ventas", "Ventas (2)"])

    def test_los_flujos_antiguos_se_importan_al_abrir_la_ventana(self):
        f = Flujo(nombre="Antiguo", url="http://viejo/")
        f.pasos = [Paso("abrir_url", url="http://viejo/")]
        f.guardar(os.path.join(self.carpeta, "Antiguo.json"))
        otra = tk.Toplevel(_raiz_tk())
        otra.withdraw()
        app2 = bot.App(otra, self.args)
        try:
            self.assertIn("Antiguo", [r["nombre"] for r in app2.reportes])
            self.assertTrue(os.path.isfile(os.path.join(self.carpeta, "_importados", "Antiguo.json")))
            self.assertFalse(os.path.exists(os.path.join(self.carpeta, "Antiguo.json")))
        finally:
            app2.almacen.cerrar()
            otra.destroy()


class TestListaDePasos(BaseGui):
    def test_activar_desactivar_y_convertir_en_contrasena(self):
        app = self.app
        app.flujo.pasos = [Paso("abrir_url", url="http://x/"),
                           Paso("escribir", selectores=["#clave"], valor="Secreta{{1}}", objetivo="Contraseña")]
        app._refrescar_lista(1)
        app.arbol.selection_set("1")
        app._alternar_desactivado()
        self.assertTrue(app.flujo.pasos[1].desactivado)
        self.assertIn("desactivado", app.arbol.item("1", "tags"))
        self.assertIn("(desactivado)", app.arbol.item("1", "values")[1])
        app._alternar_desactivado()
        self.assertFalse(app.flujo.pasos[1].desactivado)
        # el texto en claro no aparece en la lista
        self.assertNotIn("Secreta", " ".join(str(v) for v in app.arbol.item("1", "values")))
        # convertir en contraseña
        self.nombres = ["portal:clave"]
        app.arbol.selection_set("1")
        app._convertir_contrasena()
        self.assertEqual(app.flujo.pasos[1].valor, "{secreto:portal:clave}")
        self.assertEqual(secretos.obtener("portal:clave"), "Secreta{1}")
        self.assertNotIn("Secreta", app.flujo.a_json())

    def test_pasar_el_raton_automatico_se_distingue(self):
        app = self.app
        app.flujo.pasos = [Paso("abrir_url", url="http://x/"),
                           Paso("pasar_raton", selectores=["#inv"], objetivo="Inventario", auto=True),
                           Paso("clic", selectores=["#adm"], objetivo="Administrar")]
        app._refrescar_lista()
        self.assertEqual(app.arbol.item("1", "values")[1], "Pasar el ratón (automático)")
        self.assertEqual(app.arbol.item("1", "values")[2], "«Inventario»")
        self.assertIn("auto", app.arbol.item("1", "tags"))
        dlg = bot.DialogoPaso(self.root, app.flujo.pasos[1], {}, {})
        dlg.update()
        dlg.vars["objetivo"].set("Inventario (menú)")
        dlg._aceptar()
        self.assertEqual(app.flujo.pasos[1].objetivo, "Inventario (menú)")
        self.assertTrue(app.flujo.pasos[1].auto)

    def test_dialogo_del_paso_muestra_la_espera_aprendida_y_guarda_desactivado(self):
        paso = Paso("clic", selectores=["#a"], espera_grabada=40)
        dlg = bot.DialogoPaso(self.root, paso, {}, {"timeout_paso": 60, "timeout_descarga": 600})
        dlg.update()
        texto = dlg.lbl_espera.cget("text")
        self.assertIn("40", texto)
        self.assertIn("150", texto)                 # 40 × 3 + 30
        dlg.vars["desactivado"].set(True)
        dlg.vars["timeout"].set("20")
        dlg._aceptar()
        self.assertTrue(paso.desactivado)
        self.assertEqual(paso.timeout, 20.0)
        self.assertEqual(paso.espera_grabada, 40)

    def test_opcion_recuperacion_automatica(self):
        app = self.app
        self.assertTrue(app.v_recup.get())
        app.v_recup.set(False)
        app._formulario_a_flujo()
        self.assertFalse(app.flujo.opcion("recuperacion_automatica"))


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestLoteDesdeLaVentana(BaseGui):
    @classmethod
    def setUpClass(cls):
        cls.servidor = ServidorPrueba().iniciar()
        cls.base = cls.servidor.url_base

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()

    def test_lote_visible_en_el_panel_con_resumen(self):
        bien = self.guardar("Bien", [Paso("abrir_url", url=self.base + "index.html"),
                                     Paso("escribir", selectores=["#usuario"], valor="demo")], url=self.base)
        mal = self.guardar("Mal", [Paso("abrir_url", url=self.base + "index.html"),
                                   Paso("clic", selectores=["#no-existe"], timeout=1)], url=self.base)
        resumenes = []

        class FalsoResumen:
            def __init__(self, padre, titulo, texto):
                resumenes.append(texto)

            def grab_set(self):
                pass

        app = self.app
        app._refrescar_reportes()
        app.marcados = {bien, mal}
        with mock.patch.object(bot, "DialogoResumen", FalsoResumen):
            app._ejecutar_reportes(solo_marcados=True)
            self.assertTrue(app.trabajando)
            self.assertTrue(self.esperar(lambda: not app.trabajando and resumenes), "el lote no terminó")
        self.assertEqual(len(resumenes), 1)
        self.assertIn("1 de 2 reportes bien, 1 fallaron", resumenes[0])
        self.assertIn("FALLÓ   Mal", resumenes[0])
        filas = {nombre: valores[4] for nombre, valores in self.filas().items()}
        self.assertEqual(filas, {"Bien": "Bien", "Mal": "Falló"})
        # cada reporte usó su perfil por id
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "perf", nombre_perfil(bien))))


if __name__ == "__main__":
    unittest.main()
