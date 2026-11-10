"""Pruebas de la versión 2.2 sin navegador: almacén de reportes (SQLite), migración de los .json antiguos,
lotes por id, línea de comandos --reporte / --id / --todos y tareas programadas por número de reporte.
Siempre con bases de datos temporales (nunca datos/bot.db) y sin crear tareas programadas."""

import contextlib
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import bot  # noqa: E402
from webbot import ejecutor as mod_ejecutor  # noqa: E402
from webbot import lote, programador  # noqa: E402
from webbot.almacen import Almacen, ErrorAlmacen, nombre_perfil, validar_nombre  # noqa: E402
from webbot.ejecutor import ResultadoEjecucion  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402


def flujo(nombre, url="http://ejemplo/", pasos=None):
    f = Flujo(nombre=nombre, url=url)
    f.pasos = pasos if pasos is not None else [Paso("abrir_url", url=url), Paso("clic", selectores=["#a"])]
    return f


class BaseAlmacen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_alm_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ruta_db = os.path.join(self.tmp, "datos", "bot.db")
        self.alm = Almacen(self.ruta_db)
        self.addCleanup(self.alm.cerrar)


class TestAlmacen(BaseAlmacen):
    def test_guardar_listar_obtener_y_actualizar(self):
        a = self.alm.guardar(flujo("Ventas", "http://a/"))
        b = self.alm.guardar(flujo("Clientes", "http://b/"))
        self.assertTrue(os.path.isfile(self.ruta_db))
        self.assertEqual([r["nombre"] for r in self.alm.listar()], ["Clientes", "Ventas"])     # por nombre
        r = self.alm.obtener(a)
        self.assertEqual((r["nombre"], r["url"]), ("Ventas", "http://a/"))
        self.assertRegex(r["creado"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(self.alm.obtener_por_nombre("ventas")["id"], a)                      # sin distinguir mayúsculas
        f = self.alm.cargar_flujo(a)
        self.assertEqual(f.nombre, "Ventas")
        self.assertEqual([p.tipo for p in f.pasos], ["abrir_url", "clic"])
        f.pasos.append(Paso("pasar_raton", selectores=["#m"], auto=True))
        self.assertEqual(self.alm.guardar(f, a), a)
        self.assertTrue(self.alm.cargar_flujo(a).pasos[-1].auto)
        self.assertEqual(self.alm.resolver("Clientes"), b)
        self.assertEqual(self.alm.resolver(b), b)
        with self.assertRaises(ErrorAlmacen):
            self.alm.resolver("No existe")
        with self.assertRaises(ErrorAlmacen):
            self.alm.cargar_flujo(999)

    def test_nombres_unicos_y_validos(self):
        self.alm.guardar(flujo("Ventas"))
        with self.assertRaises(ErrorAlmacen) as e:
            self.alm.guardar(flujo("VENTAS"))
        self.assertIn("Ya existe", str(e.exception))
        for malo in ("", "   ", 'Con "comillas"', "x" * 81):
            with self.assertRaises(ErrorAlmacen):
                validar_nombre(malo)
        self.assertEqual(validar_nombre("  Ventas   de  hoy "), "Ventas de hoy")
        self.assertEqual(self.alm.nombre_libre("Ventas"), "Ventas (copia)")
        self.assertEqual(self.alm.nombre_libre("Otro"), "Otro")

    def test_renombrar_conserva_id_historial_y_perfil(self):
        a = self.alm.guardar(flujo("Ventas"))
        self.alm.registrar_ejecucion(a, "ok", archivos=[r"C:\d\v.csv"])
        perfil = nombre_perfil(a)
        self.alm.guardar(flujo("Otro"))
        with self.assertRaises(ErrorAlmacen):
            self.alm.renombrar(a, "otro")
        self.alm.renombrar(a, "Ventas diarias")
        self.assertEqual(self.alm.obtener(a)["nombre"], "Ventas diarias")
        self.assertEqual(self.alm.cargar_flujo(a).nombre, "Ventas diarias")
        self.assertEqual(self.alm.ultima_ejecucion(a)["archivos"], ["v.csv"])
        self.assertEqual(nombre_perfil(a), perfil)                       # el perfil va por id
        self.assertEqual(perfil, "reporte_%d" % a)

    def test_duplicar(self):
        a = self.alm.guardar(flujo("Ventas"))
        b = self.alm.duplicar(a)
        c = self.alm.duplicar(a)
        self.assertEqual([self.alm.obtener(x)["nombre"] for x in (b, c)], ["Ventas (copia)", "Ventas (copia 2)"])
        self.assertEqual(len(self.alm.cargar_flujo(b).pasos), 2)
        self.assertIsNone(self.alm.ultima_ejecucion(b))

    def test_papelera_restaurar_y_borrar(self):
        a = self.alm.guardar(flujo("Ventas"))
        self.alm.registrar_ejecucion(a, "ok")
        self.alm.eliminar(a)
        self.assertEqual(self.alm.listar(), [])
        self.assertIsNone(self.alm.obtener(a))
        self.assertEqual([r["nombre"] for r in self.alm.papelera()], ["Ventas"])
        with self.assertRaises(ErrorAlmacen):
            self.alm.eliminar(a)
        # mientras está en la papelera su nombre queda libre; al recuperarlo no se pisa
        nuevo = self.alm.guardar(flujo("Ventas"))
        self.assertEqual(self.alm.restaurar(a), "Ventas (recuperado)")
        self.assertEqual(self.alm.cargar_flujo(a).nombre, "Ventas (recuperado)")
        self.assertEqual(self.alm.ultima_ejecucion(a)["resultado"], "ok")                # el historial vuelve
        with self.assertRaises(ErrorAlmacen):
            self.alm.borrar_definitivo(nuevo)                                         # solo desde la papelera
        self.alm.eliminar(nuevo)
        self.alm.borrar_definitivo(nuevo)
        self.assertIsNone(self.alm.obtener(nuevo, incluir_eliminados=True))
        self.assertEqual(self.alm.papelera(), [])

    def test_historial(self):
        a = self.alm.guardar(flujo("Ventas"))
        self.assertIsNone(self.alm.ultima_ejecucion(a))
        self.alm.registrar_ejecucion(a, "error", "Error en el paso 3", cuando=datetime.datetime(2026, 3, 15, 8, 30, 5))
        res = ResultadoEjecucion()
        res.ok = True
        res.archivos = [r"C:\x\a.csv"]
        self.alm.registrar_resultado(a, res)
        h = self.alm.historial(a)
        self.assertEqual([e["resultado"] for e in h], ["ok", "error"])                # la más reciente primero
        self.assertEqual(h[1]["cuando"], "2026-03-15 08:30:05")
        self.assertEqual(h[0]["archivos"], ["a.csv"])
        fila = self.alm.listar()[0]
        self.assertEqual((fila["resultado"], fila["mensaje"]), ("ok", ""))
        self.assertEqual(lote.texto_resultado(fila), "Bien")
        self.assertFalse(self.alm.registrar_ejecucion(999, "ok"))                     # reporte inexistente

    def test_exportar_e_importar(self):
        a = self.alm.guardar(flujo("Ventas"))
        ruta = os.path.join(self.tmp, "ventas.json")
        self.alm.exportar(a, ruta)
        with open(ruta, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["nombre"], "Ventas")
        b = self.alm.importar_archivo(ruta)
        self.assertEqual(self.alm.obtener(b)["nombre"], "Ventas (2)")
        with open(os.path.join(self.tmp, "roto.json"), "w") as fh:
            fh.write("{no es json")
        with self.assertRaises(ErrorAlmacen):
            self.alm.importar_archivo(os.path.join(self.tmp, "roto.json"))

    def test_acceso_desde_dos_hilos_a_la_vez(self):
        errores = []

        def trabajo(prefijo):
            try:
                for i in range(25):
                    rid = self.alm.guardar(flujo("%s %d" % (prefijo, i)))
                    self.alm.registrar_ejecucion(rid, "ok")
                    self.alm.listar()
            except Exception as e:  # pragma: no cover
                errores.append(e)
            finally:
                self.alm.liberar_hilo()

        hilos = [threading.Thread(target=trabajo, args=(p,)) for p in ("A", "B")]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(60)
        self.assertEqual(errores, [])
        self.assertEqual(len(self.alm.listar()), 50)
        self.assertEqual(len(self.alm.historial(limite=100)), 50)
        # y otra instancia (otro proceso, p. ej. una tarea programada) ve lo mismo
        otra = Almacen(self.ruta_db)
        try:
            self.assertEqual(len(otra.listar()), 50)
        finally:
            otra.cerrar()


class TestMigracion(BaseAlmacen):
    def test_importa_los_json_y_el_historial_una_sola_vez(self):
        carpeta = os.path.join(self.tmp, "flujos")
        perfiles = os.path.join(self.tmp, "perfiles")
        os.makedirs(carpeta)
        os.makedirs(os.path.join(perfiles, "Ventas"))                        # perfil antiguo (por nombre)
        flujo("Ventas", "http://a/").guardar(os.path.join(carpeta, "Ventas.json"))
        antiguo = {"nombre": "Clientes", "url": "http://b/", "pasos": [{"tipo": "abrir_url", "url": "http://b/"}]}
        with open(os.path.join(carpeta, "clientes.json"), "w", encoding="utf-8") as fh:
            json.dump(antiguo, fh)                                           # formato antiguo (sin versión ni opciones)
        with open(os.path.join(carpeta, "roto.json"), "w") as fh:
            fh.write("{no es json")
        with open(os.path.join(carpeta, "_historial.json"), "w", encoding="utf-8") as fh:
            json.dump({"Ventas.json": {"ultima": "2026-10-20 07:00:01", "resultado": "ok", "mensaje": "",
                                       "archivos": ["v.csv"]}}, fh)
        os.makedirs(os.path.join(carpeta, "_papelera"))
        self.alm.guardar(flujo("Ventas"))                                    # ya había uno con ese nombre
        res = self.alm.migrar_carpeta(carpeta, perfiles)
        self.assertEqual(sorted(a for a, _, _ in res["importados"]), ["Ventas.json", "clientes.json"])
        self.assertEqual([a for a, _ in res["errores"]], ["roto.json"])
        self.assertEqual(res["historial"], 1)
        nombres = {n: rid for _, rid, n in res["importados"]}
        self.assertEqual(sorted(nombres), ["Clientes", "Ventas (2)"])
        self.assertEqual(self.alm.ultima_ejecucion(nombres["Ventas (2)"])["cuando"], "2026-10-20 07:00:01")
        self.assertEqual(self.alm.cargar_flujo(nombres["Clientes"]).opcion("timeout_paso"), 60)
        # los archivos importados se mueven a _importados (el roto se queda para que el usuario lo vea)
        self.assertEqual(sorted(os.listdir(os.path.join(carpeta, "_importados"))),
                         ["Ventas.json", "_historial.json", "clientes.json"])
        self.assertEqual(sorted(os.listdir(carpeta)), ["_importados", "_papelera", "roto.json"])
        # el perfil del navegador antiguo pasa a ser el del reporte (no se pierde la sesión)
        self.assertTrue(os.path.isdir(os.path.join(perfiles, nombre_perfil(nombres["Ventas (2)"]))))
        self.assertFalse(os.path.exists(os.path.join(perfiles, "Ventas")))
        # se recuerda el archivo de origen (para las tareas programadas antiguas con --flujo)
        self.assertEqual(self.alm.obtener_por_origen(r"C:\x\flujos\clientes.json")["id"], nombres["Clientes"])
        self.assertEqual(self.alm.obtener_por_origen("Ventas")["id"], nombres["Ventas (2)"])
        # una segunda vez no importa nada
        res2 = self.alm.migrar_carpeta(carpeta, perfiles)
        self.assertEqual(res2["importados"], [])
        self.assertEqual(len(self.alm.listar()), 3)

    def test_carpeta_inexistente(self):
        self.assertEqual(self.alm.migrar_carpeta(os.path.join(self.tmp, "no"))["importados"], [])


class FalsoEjecutor:
    """Sustituye al ejecutor real: no abre el navegador; falla si el reporte se llama «Mal»."""
    llamadas = []

    def __init__(self, flujo, carpeta_perfil=None, **kw):
        self.flujo = flujo
        FalsoEjecutor.llamadas.append((flujo.nombre, carpeta_perfil, flujo.url))

    def ejecutar(self):
        r = ResultadoEjecucion()
        r.total = len(self.flujo.pasos)
        r.ruta_log = "x.log"
        if self.flujo.nombre == "Mal":
            r.ok, r.paso_fallido, r.error = False, 2, "no apareció"
        else:
            r.ok = True
        return r


class TestLoteYLineaDeComandos(BaseAlmacen):
    def setUp(self):
        super().setUp()
        FalsoEjecutor.llamadas = []
        p = mock.patch.object(mod_ejecutor, "Ejecutor", FalsoEjecutor)
        p.start()
        self.addCleanup(p.stop)
        self.a = self.alm.guardar(flujo("Uno"))
        self.b = self.alm.guardar(flujo("Mal"))
        self.c = self.alm.guardar(flujo("Tres"))
        self.alm.cerrar()

    def correr(self, *argumentos):
        salida, errores = io.StringIO(), io.StringIO()
        base = ["--sin-ventana", "--db", self.ruta_db, "--carpeta-flujos", os.path.join(self.tmp, "flujos"),
                "--perfil", os.path.join(self.tmp, "perfiles"), "--registros", os.path.join(self.tmp, "reg")]
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
            codigo = bot.principal(list(argumentos) + base)
        return codigo, salida.getvalue() + errores.getvalue()

    def test_lote_por_ids_anota_el_historial_y_usa_el_perfil_por_id(self):
        alm = Almacen(self.ruta_db)
        self.addCleanup(alm.cerrar)
        res = lote.ejecutar_lote([self.a, self.b, 99], carpeta_perfiles=os.path.join(self.tmp, "p"),
                                 carpeta_registros=self.tmp, almacen=alm)
        self.assertEqual([i.estado for i in res.items], ["ok", "error", "error"])
        self.assertIn("No se pudo abrir", res.items[2].mensaje)
        self.assertEqual([alm.ultima_ejecucion(x)["resultado"] for x in (self.a, self.b)], ["ok", "error"])
        self.assertEqual(FalsoEjecutor.llamadas[0][1], os.path.join(self.tmp, "p", nombre_perfil(self.a)))

    def test_reporte_por_nombre(self):
        codigo, salida = self.correr("--reporte", "Uno")
        self.assertEqual(codigo, 0, salida)
        self.assertEqual([n for n, _, _ in FalsoEjecutor.llamadas], ["Uno"])
        alm = Almacen(self.ruta_db)
        self.addCleanup(alm.cerrar)
        self.assertEqual(alm.ultima_ejecucion(self.a)["resultado"], "ok")

    def test_id_repetible_y_codigo_1_si_falla_alguno(self):
        codigo, salida = self.correr("--id", str(self.c), "--id", str(self.b))
        self.assertEqual(codigo, 1, salida)
        self.assertEqual([n for n, _, _ in FalsoEjecutor.llamadas], ["Tres", "Mal"])
        self.assertIn("1 de 2 reportes bien", salida)

    def test_todos(self):
        codigo, salida = self.correr("--todos")
        self.assertEqual(codigo, 1, salida)
        self.assertEqual(sorted(n for n, _, _ in FalsoEjecutor.llamadas), ["Mal", "Tres", "Uno"])
        self.assertIn("2 de 3 reportes bien", salida)

    def test_url_con_un_solo_reporte(self):
        codigo, salida = self.correr("--reporte", "uno", "--url", "http://otra/")
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(FalsoEjecutor.llamadas[0][2], "http://otra/")

    def test_no_existe_codigo_2(self):
        self.assertEqual(self.correr("--reporte", "Nada")[0], 2)
        self.assertEqual(self.correr("--id", "999")[0], 2)
        self.assertEqual(self.correr("--flujo", "NoExiste")[0], 2)
        self.assertEqual(FalsoEjecutor.llamadas, [])

    def test_flujo_antiguo_ya_importado_se_busca_en_la_base_de_datos(self):
        # una tarea programada con la v2.1 lleva --flujo "C:\...\flujos\Ventas diarias.json"; el archivo
        # ya se importó (y se movió): se ejecuta el reporte importado
        carpeta = os.path.join(self.tmp, "flujos")
        os.makedirs(carpeta)
        flujo("Ventas diarias").guardar(os.path.join(carpeta, "Ventas diarias.json"))
        codigo, salida = self.correr("--reporte", "Uno")                      # abre la base de datos → importa
        self.assertEqual(codigo, 0, salida)
        self.assertIn("Se importaron 1 reporte", salida)
        codigo, salida = self.correr("--flujo", os.path.join(carpeta, "Ventas diarias.json"))
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(FalsoEjecutor.llamadas[-1][0], "Ventas diarias")

    def test_flujo_archivo_sigue_funcionando_sin_tocar_la_base_de_datos(self):
        ruta = os.path.join(self.tmp, "suelto.json")
        flujo("Suelto").guardar(ruta)
        os.remove(self.ruta_db)
        codigo, salida = self.correr("--flujo", ruta)
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(FalsoEjecutor.llamadas[0][0], "Suelto")
        self.assertFalse(os.path.exists(self.ruta_db))

    def test_sin_nada_que_ejecutar(self):
        self.assertEqual(bot.principal(["--sin-ventana"]), 2)
        vacia = os.path.join(self.tmp, "vacia.db")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bot.principal(["--sin-ventana", "--todos", "--db", vacia,
                                            "--carpeta-flujos", os.path.join(self.tmp, "nada")]), 2)

    def test_argumentos(self):
        a = bot.analizar_argumentos(["--reporte", "A", "--reporte", "B", "--id", "3", "--id", "4", "--db", "x.db"])
        self.assertEqual((a.reporte, a.id, a.db), (["A", "B"], [3, 4], "x.db"))


class TestProgramadorPorReporte(unittest.TestCase):
    BOT = r"C:\Bots\bot.py"
    PY = r"C:\Python\pythonw.exe"

    def tr(self, cmd):
        return cmd[cmd.index("/TR") + 1]

    def test_por_ids(self):
        cmd = programador.construir_comando_crear("Ventas", self.BOT, None, "06:00", python=self.PY, ids=[3, 7])
        self.assertEqual(self.tr(cmd), '"C:\\Python\\pythonw.exe" "C:\\Bots\\bot.py" --id 3 --id 7 --sin-ventana --oculto')

    def test_por_nombre_y_base_de_datos(self):
        cmd = programador.construir_comando_crear("V", self.BOT, None, "06:00", python=self.PY, reportes=["Ventas diarias"],
                                                  db=r"D:\otra\bot.db")
        self.assertEqual(self.tr(cmd), '"C:\\Python\\pythonw.exe" "C:\\Bots\\bot.py" --db "D:\\otra\\bot.db" '
                                       '--reporte "Ventas diarias" --sin-ventana --oculto')
        with self.assertRaises(programador.ErrorProgramador):
            programador.comando_bot(self.BOT, python=self.PY, reportes=['con "comillas"'])

    def test_nada_que_programar(self):
        with self.assertRaises(programador.ErrorProgramador):
            programador.construir_comando_crear("X", self.BOT, None, "06:00", python=self.PY, ids=[])

    def test_la_ventana_programa_por_id(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:          # pragma: no cover
            self.skipTest("no hay pantalla para tkinter")
        root.withdraw()
        try:
            dlg = bot.DialogoProgramar(root, 5, "Ventas", {}, seleccionados=[5, 8], n_todos=3)
            self.assertIn("--id 5 --sin-ventana", self.tr(dlg._comando()))
            dlg.v_modo.set("seleccion")
            self.assertIn("--id 5 --id 8", self.tr(dlg._comando()))
            dlg.v_modo.set("todos")
            self.assertIn("--todos", self.tr(dlg._comando()))
            dlg.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
