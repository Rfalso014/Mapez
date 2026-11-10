"""Pruebas unitarias de la versión 3.0 (sin navegador): paso «Elegir opción» y sus estrategias, conversión de los
pares «abrir lista + clic en opción» (con la forma real de Portal), «Repetir por días» y la plantilla {fecha}, contraseñas
rechazadas (huella), base de datos v3 (notificaciones, vigilancia, actualización desde la v2), programar la vigilancia,
--vigilar, mapeador (pasos generados) y avisos de Windows inyectables."""

import contextlib
import datetime
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import avisos, mapeador, programador, secretos  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot import plantillas  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.flujo import ErrorFlujo, Flujo, Paso  # noqa: E402

CORTES = ["43 - 2026 (02/10/2026 - 08/10/2026)", "45 - 2026 (16/10/2026 - 22/10/2026)",
          "44 - 2026 (09/10/2026 - 15/10/2026)"]


class TestEstrategias(unittest.TestCase):
    def test_mas_reciente(self):
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "mas_reciente"), 1)
        self.assertEqual(mod_flujo.elegir_indice(["Agosto 2026", "Octubre 2026", "Septiembre 2026"], "mas_reciente"), 1)
        self.assertEqual(mod_flujo.elegir_indice(["2026-10-24", "2026-10-25", "2025-12-31"], "mas_reciente"), 1)
        self.assertEqual(mod_flujo.elegir_indice(["Semana 9", "Semana 12", "Semana 10"], "mas_reciente"), 1)
        # año antes que número: «1 - 2027» es más reciente que «52 - 2026»
        self.assertEqual(mod_flujo.elegir_indice(["52 - 2026", "1 - 2027"], "mas_reciente"), 1)

    def test_fija_primera_ultima_contiene(self):
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "fija", " 44 - 2026  (09/10/2026 - 15/10/2026) "), 2)
        self.assertIsNone(mod_flujo.elegir_indice(CORTES, "fija", "46 - 2026"))
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "primera"), 0)
        self.assertEqual(mod_flujo.elegir_indice(CORTES + [""], "ultima"), 2)
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "contiene", "16/10/2026"), 1)
        self.assertEqual(mod_flujo.elegir_indice(CORTES, "contiene", r"^4[34] "), 0)       # expresión regular
        self.assertIsNone(mod_flujo.elegir_indice([], "mas_reciente"))

    def test_paso_descripcion_y_validacion(self):
        p = Paso("elegir_opcion", selectores=["#corte"], objetivo="Elegir corte", estrategia="mas_reciente")
        self.assertEqual(p.descripcion(), "Elegir la opción más reciente en «Elegir corte»")
        self.assertEqual(p.problemas(), [])
        self.assertEqual(Paso.desde_dict(p.a_dict()).estrategia, "mas_reciente")
        self.assertIn("Falta el texto de la opción", Paso("elegir_opcion", selectores=["#a"]).problemas())
        self.assertTrue(Paso("elegir_opcion", selectores=["#a"], estrategia="otra").problemas())
        fija = Paso("elegir_opcion", selectores=["#a"], objetivo="Formato", valor="Excel")
        self.assertEqual(fija.descripcion(), "Elegir «Excel» en «Formato»")


def pasos_portal():
    """La forma real de los pasos grabados en Portal (v2.3): clic en «div» + clic en role=option."""
    ruta_div = "#app > div:nth-of-type(1) > main:nth-of-type(1) > form:nth-of-type(1) > div:nth-of-type(%d) > div:nth-of-type(1)"
    return [Paso("abrir_url", url="https://portal.ejemplo.com/portal/#/inicio-sesion"),
            Paso("clic", selectores=['role=link[name="Reportes"]'], objetivo="Reportes"),
            Paso("clic", selectores=[ruta_div % 2], objetivo="div"),
            Paso("clic", selectores=['role=option[name="Detalles Ventas Mayorista"]', "#v-menu-v-32 > div:nth-of-type(1)"],
                 objetivo="Detalles Ventas Mayorista"),
            Paso("clic", selectores=[ruta_div % 3], objetivo="div"),
            Paso("pasar_raton", selectores=["#v-menu-v-35 > div"], auto=True),
            Paso("clic", selectores=['role=option[name="44 - 2026 (09/10/2026 - 15/10/2026)"]'],
                 objetivo="44 - 2026 (09/10/2026 - 15/10/2026)"),
            Paso("clic", selectores=['role=button[name="Generar"]'], objetivo="Generar")]


class TestConvertirListas(unittest.TestCase):
    def test_pares_con_la_forma_real_de_portal(self):
        pasos = pasos_portal()
        self.assertEqual(mod_flujo.pares_lista_opcion(pasos),
                         [(2, 3, "Detalles Ventas Mayorista"), (4, 6, "44 - 2026 (09/10/2026 - 15/10/2026)")])

    def test_convertir_bajo_pedido(self):
        f = Flujo(nombre="Portal", pasos=pasos_portal())
        mensajes = mod_flujo.convertir_listas(f, pares=[4], estrategias={4: "mas_reciente"})
        self.assertEqual(len(mensajes), 1)
        tipos = [p.tipo for p in f.pasos]
        self.assertEqual(tipos, ["abrir_url", "clic", "clic", "clic", "elegir_opcion", "clic"])
        nuevo = f.pasos[4]
        self.assertEqual(nuevo.estrategia, "mas_reciente")
        self.assertEqual(nuevo.selectores[0], pasos_portal()[4].selectores[0])
        self.assertEqual(nuevo.problemas(), [])
        # todos, con la opción fija (texto con paréntesis escapado como literal)
        g = Flujo(nombre="Portal", pasos=pasos_portal())
        mod_flujo.convertir_listas(g)
        self.assertEqual([p.tipo for p in g.pasos], ["abrir_url", "clic", "elegir_opcion", "elegir_opcion", "clic"])
        self.assertEqual(plantillas.renderizar(g.pasos[3].valor), "44 - 2026 (09/10/2026 - 15/10/2026)")
        self.assertEqual(mod_flujo.convertir_listas(g), [])          # ya no queda nada que convertir


class TestRepetirPorDias(unittest.TestCase):
    HOY = datetime.date(2026, 10, 26)

    def test_modos(self):
        d = mod_flujo.dias_a_repetir
        self.assertEqual(d(None, self.HOY), [])
        self.assertEqual(d({"modo": "no"}, self.HOY), [])
        self.assertEqual(d({"modo": "ayer"}, self.HOY), [datetime.date(2026, 10, 25)])
        self.assertEqual(d({"modo": "ultimos", "n": 3}, self.HOY),
                         [datetime.date(2026, 10, 23), datetime.date(2026, 10, 24), datetime.date(2026, 10, 25)])
        mes = d({"modo": "mes_hasta_ayer"}, self.HOY)
        self.assertEqual((mes[0], mes[-1], len(mes)), (datetime.date(2026, 10, 1), datetime.date(2026, 10, 25), 25))
        self.assertEqual(len(d({"modo": "mes_hasta_ayer"}, datetime.date(2026, 11, 1))), 31)    # el día 1: el mes anterior
        self.assertEqual(d({"modo": "fijo", "desde": "2026-10-26", "hasta": "2026-10-27"}, self.HOY),
                         [datetime.date(2026, 10, 26), datetime.date(2026, 10, 27)])

    def test_validacion(self):
        for malo in ({"modo": "fijo", "desde": "26/10/2026"}, {"modo": "fijo", "desde": "2026-10-27", "hasta": "2026-10-26"},
                     {"modo": "ultimos", "n": 0}, {"modo": "otro"}):
            with self.assertRaises(ErrorFlujo):
                mod_flujo.validar_repetir_dias(malo)
        f = Flujo(nombre="x", pasos=[Paso("abrir_url", url="http://a/")])
        f.opciones["repetir_dias"] = {"modo": "ultimos", "n": "x"}
        self.assertTrue(any("Repetir por días" in p for p in f.problemas()))

    def test_plantilla_fecha(self):
        r = plantillas.renderizar
        dia = datetime.date(2026, 10, 25)
        self.assertEqual(r("{fecha}", fecha=dia), "25/10/2026")
        self.assertEqual(r("Ventas_{fecha:%Y-%m-%d}", fecha=dia), "Ventas_2026-10-25")
        self.assertEqual(r("{fecha}", hoy=self.HOY), "26/10/2026")                # sin repetir: hoy
        f = Flujo(nombre="x", pasos=[Paso("escribir", selectores=["#f"], valor="{fecha}")])
        self.assertEqual(f.variables_necesarias(), [])


class TestContrasenasRechazadas(unittest.TestCase):
    def setUp(self):
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)

    def test_huella(self):
        secretos.guardar("h:clave", "uno")
        self.assertIsNone(secretos.rechazada("h:clave"))
        self.assertTrue(secretos.marcar_rechazada("h:clave"))
        self.assertTrue(secretos.rechazada("h:clave"))
        self.assertEqual(secretos.listar(), ["h:clave"])               # la huella no aparece como contraseña
        guardado = repr(secretos.almacen_actual().datos)
        self.assertNotIn("'uno'", guardado.replace("('BotWeb', 'h:clave'): 'uno'", ""))
        secretos.guardar("h:clave", "dos")                             # se cambió: ya no cuenta como rechazada
        self.assertIsNone(secretos.rechazada("h:clave"))
        self.assertFalse(secretos.marcar_rechazada("no-existe"))
        with self.assertRaises(secretos.ErrorSecreto):
            secretos.guardar("__rechazada__:x", "v")


class TestBaseDeDatosV3(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v3_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_actualiza_una_base_de_la_v2(self):
        ruta = os.path.join(self.tmp, "v2.db")
        con = sqlite3.connect(ruta)
        con.executescript("""CREATE TABLE reportes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, url TEXT NOT NULL
            DEFAULT '', flujo TEXT NOT NULL, creado TEXT NOT NULL, modificado TEXT NOT NULL, eliminado TEXT, origen TEXT NOT NULL DEFAULT '');
            CREATE TABLE ejecuciones (id INTEGER PRIMARY KEY AUTOINCREMENT, reporte_id INTEGER NOT NULL, cuando TEXT NOT NULL,
            resultado TEXT NOT NULL, mensaje TEXT NOT NULL DEFAULT '', archivos TEXT NOT NULL DEFAULT '[]', duracion REAL);
            INSERT INTO reportes(nombre, flujo, creado, modificado) VALUES ('Viejo', '{"version": 3, "nombre": "Viejo", "pasos": []}', 'x', 'x');
            INSERT INTO ejecuciones(reporte_id, cuando, resultado) VALUES (1, '2026-10-24 10:00:00', 'ok');""")
        con.commit()
        con.close()
        alm = Almacen(ruta)
        self.addCleanup(alm.cerrar)
        h = alm.historial()
        self.assertEqual((h[0]["nombre"], h[0]["registro"], h[0]["captura"]), ("Viejo", "", ""))
        alm.registrar_ejecucion(1, "error", "x", registro="r.log", captura="c.png")
        self.assertEqual(alm.historial()[0]["captura"], "c.png")
        self.assertEqual(alm.vigilancias(), [])

    def test_notificaciones_y_vigilancia(self):
        alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(alm.cerrar)
        a = alm.crear_notificacion("clave_rechazada", "T", "uno", {"host": "h"})
        b = alm.crear_notificacion("clave_rechazada", "T", "dos", {"host": "h"})
        self.assertEqual(a, b)                                   # sin leer: no se repite
        self.assertEqual(alm.notificaciones()[0]["texto"], "dos")
        alm.marcar_notificaciones_de("clave_rechazada", "host", "h")
        self.assertEqual(alm.no_leidas(), 0)
        self.assertNotEqual(alm.crear_notificacion("clave_rechazada", "T", "tres"), a)
        rid = alm.guardar(Flujo(nombre="R", pasos=[Paso("abrir_url", url="http://a/")]))
        alm.guardar_vigilancia(rid, 1, auto_descargar=True, frecuencia="horas", cada_horas=4)
        self.assertEqual(alm.vigilancia(rid)["cada_horas"], 4)
        self.assertEqual(alm.registrar_opciones(rid, 1, ["44"]), ([], True))
        self.assertEqual(alm.registrar_opciones(rid, 1, ["44", "45"]), (["45"], False))
        self.assertEqual(alm.pendientes_de_descargar(rid, 1), ["45"])
        alm.marcar_descargada(rid, 1, "45", ["C:/x/Portal_45.csv"])
        self.assertEqual(alm.pendientes_de_descargar(rid, 1), [])
        self.assertEqual(alm.opciones_vistas(rid, 1)[-1]["archivos"], ["Portal_45.csv"])
        with self.assertRaises(Exception):
            alm.guardar_vigilancia(rid, 1, frecuencia="semanal")
        alm.eliminar(rid)
        alm.borrar_definitivo(rid)
        self.assertIsNone(alm.vigilancia(rid))


class TestProgramarVigilancia(unittest.TestCase):
    def test_comando_vigilar_cada_horas(self):
        cmd = programador.construir_comando_crear("Vigilar Portal", r"C:\Bots\bot.py", python=r"C:\Python\pythonw.exe",
                                                  frecuencia="HORAS", cada_horas=4, hora="08:00", ids=[3], vigilar=True)
        tr = cmd[cmd.index("/TR") + 1]
        self.assertEqual(tr, '"C:\\Python\\pythonw.exe" "C:\\Bots\\bot.py" --id 3 --vigilar --oculto')
        self.assertEqual(cmd[cmd.index("/SC") + 1:cmd.index("/SC") + 4], ["HOURLY", "/MO", "4"])
        with self.assertRaises(programador.ErrorProgramador):
            programador.construir_comando_crear("x", "b.py", frecuencia="HORAS", cada_horas=30, ids=[1])
        diaria = programador.construir_comando_crear("x", "b.py", frecuencia="DIARIA", hora="07:30", ids=[1], vigilar=True)
        self.assertIn("--vigilar", diaria[diaria.index("/TR") + 1])
        self.assertNotIn("--sin-ventana", diaria[diaria.index("/TR") + 1])

    def test_cli_vigilar_sin_vigilancias(self):
        import bot
        tmp = tempfile.mkdtemp(prefix="botweb_vig_")
        self.addCleanup(shutil.rmtree, tmp, True)
        errores = io.StringIO()
        with contextlib.redirect_stderr(errores), contextlib.redirect_stdout(io.StringIO()):
            codigo = bot.principal(["--vigilar", "--db", os.path.join(tmp, "b.db")])
        self.assertEqual(codigo, 2)
        self.assertIn("filtro vigilado", errores.getvalue())


class TestMapeadorPasos(unittest.TestCase):
    FILTROS = [{"k": 0, "tipo": "pestana", "etiqueta": "Corte", "selectores": ['role=tab[name="Corte"]'], "orden": 0},
               {"k": 1, "tipo": "lista", "etiqueta": "Filtro por sistema", "valor": "Portal", "selectores": ["#s"], "orden": 1},
               {"k": 2, "tipo": "lista", "etiqueta": "Elegir corte", "valor": "", "selectores": ["#c"], "orden": 2},
               {"k": 3, "tipo": "fecha", "tipo_campo": "text", "etiqueta": "Fecha", "valor": "26/10/2026", "selectores": ["#f"], "orden": 3},
               {"k": 4, "tipo": "accion", "etiqueta": "Generar", "selectores": ["#g"], "orden": 4},
               {"k": 5, "tipo": "casilla", "etiqueta": "Solo vencidos", "marcado": False, "selectores": ["#v"], "orden": 5}]

    def test_generar_pasos(self):
        pasos = mapeador.generar_pasos(self.FILTROS, [
            {"k": 4, "modo": "descargar", "nombre": "Corte_{opcion}{ext}"}, {"k": 2, "estrategia": "mas_reciente"},
            {"k": 1}, {"k": 3, "fecha": "ayer"}, {"k": 0}, {"k": 5, "marcado": True}])
        self.assertEqual([p.tipo for p in pasos], ["clic", "elegir_opcion", "elegir_opcion", "escribir", "marcar", "descargar"])
        self.assertEqual((pasos[1].estrategia, plantillas.renderizar(pasos[1].valor)), ("fija", "Portal"))
        self.assertEqual(pasos[2].estrategia, "mas_reciente")
        self.assertEqual(pasos[3].valor, "{ayer:%d/%m/%Y}")
        self.assertTrue(pasos[4].marcado)
        self.assertEqual(pasos[5].nombre, "Corte_{opcion}{ext}")
        self.assertTrue(all(not p.problemas() for p in pasos))
        self.assertEqual(mapeador.formato_fecha({"tipo_campo": "date"}), "%Y-%m-%d")
        self.assertEqual(mapeador.formato_fecha({"valor": "2026-10-26"}), "%Y-%m-%d")

    def test_aplicar_y_punto_de_mapeo(self):
        f = Flujo(nombre="I", pasos=pasos_portal())
        self.assertEqual(mapeador.punto_de_mapeo(f), 2)              # el primer «clic para abrir la lista»
        nuevos = [Paso("elegir_opcion", selectores=["#c"], estrategia="mas_reciente")]
        g = mapeador.aplicar_pasos(f.copia(), nuevos, 2, "reemplazar")
        self.assertEqual([p.tipo for p in g.pasos], ["abrir_url", "clic", "elegir_opcion"])
        g = mapeador.aplicar_pasos(f.copia(), nuevos, 2, "anadir")
        self.assertEqual(len(g.pasos), len(f.pasos) + 1)

    def test_script_reutiliza_los_selectores_del_grabador(self):
        js = mapeador.script_mapeador()
        self.assertIn("function candidatos(el, soloEstable)", js)
        self.assertIn("window.__botMapear", js)
        self.assertNotIn("crearBarra", js)


class TestAvisos(unittest.TestCase):
    def test_inyectable_y_sin_toast_en_pruebas(self):
        self.assertTrue(avisos.avisos_desactivados())                 # unittest cargado: nunca hay toast real
        self.assertFalse(avisos.toast_windows("t", "x"))
        recibidos = []
        avisos.usar_notificador(lambda t, x: recibidos.append((t, x)))
        self.addCleanup(avisos.usar_notificador, None)

        class Falso:
            def crear_notificacion(self, tipo, titulo, texto, datos):
                recibidos.append(("db", tipo))
                return 7
        self.assertEqual(avisos.avisar(Falso(), "vigilancia", "Llegó un corte nuevo", "45"), 7)
        self.assertEqual(recibidos, [("db", "vigilancia"), ("Llegó un corte nuevo", "45")])


if __name__ == "__main__":
    unittest.main()
