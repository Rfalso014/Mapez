"""Pruebas de la versión 3.3 sin navegador.

- Vigilancia: VARIAS vigilancias de la misma lista (Página y reporte) con otros valores en los filtros de antes, cada una
  con sus opciones vistas, su novedad y su descarga automática (no se mezclan); los avisos dicen de qué vigilancia son;
  la marca «nueva» del formulario junta las de todas.  Conversión desde la tabla antigua (una vigilancia por reporte /
  Página) con copia de seguridad del archivo ANTES de cambiar nada.  API (/api/vigilancias, y las de la 3.2 siguen),
  programar una vigilancia (`--vigilancia-id N`), `--vigilar` / `--vigilancia-id` por línea de comandos.
- Mapear: nombres legibles a partir del name/id de ASP.NET, avisos del mapa vacío, «Ver Reporte» → guardar la página,
  menú de exportar de DevExpress, pasos de una Página en un marco (iframe) y con «búsqueda» (lupa + fila).
Bases de datos temporales; ninguna notificación de Windows, ninguna tarea programada.
"""

import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_v32 import C43, C44, C45, pagina_simple  # noqa: E402
from webbot import avisos, filtros, mapeador, paginas, programador, vigilancia  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.ejecutor import ResultadoEjecucion  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

C42 = "42 - 2026 (25/09/2026 - 01/10/2026)"


def _res(ok=True, extra=None, archivos=None):
    r = ResultadoEjecucion()
    r.ok, r.extra, r.archivos = ok, extra, list(archivos or [])
    return r


class WebFalsa:
    """Ejecutor falso de una Página: la lista «Elegir corte» depende de «Seleccione reporte» (`cortes[reporte]`);
    «descarga» lo elegido (reporte, corte)."""

    def __init__(self, cortes):
        self.cortes = {k: list(v) for k, v in cortes.items()}
        self.descargas = []
        self.lecturas = []

    @staticmethod
    def _elegido(flujo, nombre):
        p = next(p for p in flujo.pasos if p.filtro == nombre)
        return filtros.desescapar(p.valor)

    def crear(self, flujo, reporte_id=None, hasta=None, al_final=None, **extra):
        web = self

        class Ej:
            lineas_inicio = []

            def ejecutar(self):
                reporte = web._elegido(flujo, "Seleccione reporte")
                if al_final is not None:
                    web.lecturas.append(reporte)
                    return _res(extra=list(web.cortes[reporte]))
                corte = web._elegido(flujo, "Elegir corte")
                web.descargas.append((reporte, corte))
                return _res(archivos=["C:/descargas/%s - %s.xlsx" % (reporte, corte.split(" ")[0])])
        return Ej()


class ReporteFalso:
    """Ejecutor falso de un reporte: el paso 2 (corte) depende del paso 1 (reporte), que la vigilancia cambia con
    `filtros` (sus `valores`)."""

    def __init__(self, cortes):
        self.cortes = cortes
        self.descargas = []

    def crear(self, flujo, reporte_id=None, hasta=None, al_final=None, filtros=None, **extra):
        web = self
        reporte = (filtros or {}).get(1, {}).get("valor") or flujo.pasos[1].valor

        class Ej:
            def ejecutar(self):
                if al_final is not None:
                    return _res(extra=list(web.cortes[reporte]))
                web.descargas.append((reporte, filtros_mod_desescapar(flujo.pasos[2].valor)))
                return _res(archivos=["C:/d/%s.csv" % reporte])
        return Ej()


def filtros_mod_desescapar(v):
    return filtros.desescapar(v)


def flujo_reporte():
    return Flujo(nombre="Portal (reporte)", url="https://portal.example/", pasos=[
        Paso("abrir_url", url="https://portal.example/"),
        Paso("elegir_opcion", selectores=["#rep"], objetivo="Seleccione reporte", valor="Mayorista"),
        Paso("elegir_opcion", selectores=["#corte"], objetivo="Elegir corte", estrategia="mas_reciente"),
        Paso("descargar", selectores=["#d"], nombre="{opcion}{ext}")])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v33_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.toasts = []
        avisos.usar_notificador(lambda titulo, texto: self.toasts.append((titulo, texto)))
        self.addCleanup(avisos.usar_notificador, None)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)


class TestVariasVigilanciasPagina(Base):
    def test_misma_lista_con_otros_valores_no_se_mezcla(self):
        pid = self.alm.guardar_pagina("Portal – Reportes", pagina_simple())
        web = WebFalsa({"Mayorista": [C42, C43], "Cartera": [C42, C43]})
        v1 = self.alm.crear_vigilancia(pagina_id=pid, filtro="f3", valores={"f2": {"estrategia": "fija", "valor": "Mayorista"}},
                                       auto_descargar=True)
        v2 = self.alm.crear_vigilancia(pagina_id=pid, filtro="f3", auto_descargar=True,
                                       valores={"f2": {"estrategia": "fija", "valor": "Cartera"}})
        self.assertEqual([v["id"] for v in self.alm.lista_vigilancias(pagina_id=pid)], [v1, v2])
        for vid in (v1, v2):                                       # primera revisión: la referencia
            r = vigilancia.revisar_vigilancia(self.alm, vid, web.crear)
            self.assertTrue(r.ok and r.primera)
        self.assertEqual(web.lecturas, ["Mayorista", "Cartera"])
        # llega el corte 44 de Mayorista el lunes; el de Cartera, el martes
        web.cortes["Mayorista"].append(C44)
        r1 = vigilancia.revisar_vigilancia(self.alm, v1, web.crear)
        r2 = vigilancia.revisar_vigilancia(self.alm, v2, web.crear)
        self.assertEqual((r1.nuevas, r2.nuevas), ([C44], []))
        self.assertEqual(web.descargas, [("Mayorista", C44)])
        web.cortes["Cartera"].append(C44)               # el MISMO texto, en la otra vigilancia: también es nuevo ahí
        r2 = vigilancia.revisar_vigilancia(self.alm, v2, web.crear)
        self.assertEqual(r2.nuevas, [C44])
        self.assertEqual(web.descargas, [("Mayorista", C44), ("Cartera", C44)])
        self.assertEqual((self.alm.pendientes_vigilancia(v1), self.alm.pendientes_vigilancia(v2)), ([], []))
        r1 = vigilancia.revisar_vigilancia(self.alm, v1, web.crear)                      # no se vuelve a descargar
        self.assertEqual((r1.nuevas, r1.descargas, len(web.descargas)), ([], [], 2))
        # los avisos dicen de qué vigilancia son (y se dan por leídos al descargarse)
        titulos = sorted(n["titulo"] for n in self.alm.notificaciones())
        self.assertEqual(titulos, ["Llegó un corte nuevo en «Portal – Reportes» (Cartera): " + C44,
                                   "Llegó un corte nuevo en «Portal – Reportes» (Mayorista): " + C44])
        self.assertEqual({n["datos"]["vigilancia_id"] for n in self.alm.notificaciones()}, {v1, v2})
        self.assertTrue(all(n["leida"] for n in self.alm.notificaciones()))
        self.assertEqual(len(self.toasts), 2)
        # la marca «nueva» del formulario junta las de las dos vigilancias de la lista
        self.assertEqual(self.alm.novedades_pagina(pid, "f3"), [C44])
        form = paginas.formulario(paginas.normalizar(self.alm.obtener_pagina(pid)["data"]), [], None,
                                  {"f3": self.alm.novedades_pagina(pid, "f3")}, ["f3"])
        corte = next(f for f in form if f["id"] == "f3")
        self.assertTrue(corte["vigilado"])

    def test_descargar_a_mano_una_opcion_de_una_vigilancia(self):
        pid = self.alm.guardar_pagina("P", pagina_simple())
        web = WebFalsa({"Mayorista": [C43], "Cartera": [C43]})
        vid = self.alm.crear_vigilancia(pagina_id=pid, filtro="f3", valores={"f2": {"estrategia": "fija", "valor": "Cartera"}})
        vigilancia.revisar_vigilancia(self.alm, vid, web.crear)
        res = vigilancia.descargar_vigilancia(self.alm, vid, C43, web.crear)
        self.assertTrue(res.ok)
        self.assertEqual(web.descargas, [("Cartera", C43)])                  # con los valores de ESA vigilancia
        self.assertIsNotNone(self.alm.opciones_de_vigilancia(vid)[0]["descargada"])

    def test_cambiar_lo_que_vigila_olvida_lo_visto(self):
        pid = self.alm.guardar_pagina("P", pagina_simple())
        vid = self.alm.crear_vigilancia(pagina_id=pid, filtro="f3")
        self.alm.registrar_opciones_vigilancia(vid, [C43])
        self.alm.actualizar_vigilancia(vid, auto_descargar=True, frecuencia="horas", cada_horas=3)
        self.assertEqual(len(self.alm.opciones_de_vigilancia(vid)), 1)            # cambiar la frecuencia no
        self.alm.actualizar_vigilancia(vid, valores={"f2": {"estrategia": "fija", "valor": "Otro"}})
        self.assertEqual(self.alm.opciones_de_vigilancia(vid), [])                # cambiar los valores sí
        with self.assertRaises(Exception):
            self.alm.actualizar_vigilancia(vid, frecuencia="semanal")
        self.alm.borrar_pagina(pid)
        self.assertIsNone(self.alm.vigilancia_id(vid))


class TestVariasVigilanciasReporte(Base):
    def test_dos_vigilancias_del_mismo_paso_con_otro_reporte(self):
        rid = self.alm.guardar(flujo_reporte())
        web = ReporteFalso({"Mayorista": [C43], "Cartera": [C42]})
        v1 = self.alm.crear_vigilancia(reporte_id=rid, paso=2, auto_descargar=True)
        v2 = self.alm.crear_vigilancia(reporte_id=rid, paso=2, auto_descargar=True,
                                       valores={"1": {"estrategia": "fija", "valor": "Cartera"}}, nombre="Cartera")
        for vid in (v1, v2):
            vigilancia.revisar_vigilancia(self.alm, vid, web.crear)
        web.cortes["Cartera"] = [C42, C43]
        r1 = vigilancia.revisar_vigilancia(self.alm, v1, web.crear)
        r2 = vigilancia.revisar_vigilancia(self.alm, v2, web.crear)
        self.assertEqual((r1.nuevas, r2.nuevas), ([], [C43]))
        self.assertEqual(web.descargas, [("Cartera", C43)])
        self.assertIn("(Cartera)", self.alm.notificaciones()[0]["titulo"])
        self.assertEqual(self.alm.novedades(rid, 2), [C43])
        # compatibilidad: «la» vigilancia del reporte es la principal (sin otros valores)
        self.assertEqual(self.alm.vigilancia(rid)["id"], v1)
        self.assertEqual(len(self.alm.vigilancias()), 2)
        self.alm.borrar_vigilancia(rid)
        self.assertEqual(self.alm.lista_vigilancias(), [])


class TestConversionV32(unittest.TestCase):
    ANTIGUO = """
        DROP TABLE vigilancias; DROP TABLE opciones_vigiladas;
        CREATE TABLE vigilancias (reporte_id INTEGER PRIMARY KEY, paso INTEGER NOT NULL, activa INTEGER NOT NULL DEFAULT 1,
            auto_descargar INTEGER NOT NULL DEFAULT 0, frecuencia TEXT NOT NULL DEFAULT '', cada_horas INTEGER,
            hora TEXT NOT NULL DEFAULT '', ultima_revision TEXT, ultimo_resultado TEXT NOT NULL DEFAULT '',
            descargar_sin_fecha INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE opciones_vistas (reporte_id INTEGER NOT NULL, paso INTEGER NOT NULL, texto TEXT NOT NULL,
            primera_vez TEXT NOT NULL, orden INTEGER NOT NULL DEFAULT 0, nueva INTEGER NOT NULL DEFAULT 0, descargada TEXT,
            archivos TEXT NOT NULL DEFAULT '[]', sin_orden INTEGER NOT NULL DEFAULT 0, novedad TEXT,
            PRIMARY KEY (reporte_id, paso, texto));
        CREATE TABLE vigilancias_paginas (pagina_id INTEGER PRIMARY KEY, filtro TEXT NOT NULL, activa INTEGER NOT NULL DEFAULT 1,
            auto_descargar INTEGER NOT NULL DEFAULT 0, favorito TEXT NOT NULL DEFAULT '', descargar_sin_fecha INTEGER NOT NULL
            DEFAULT 0, frecuencia TEXT NOT NULL DEFAULT '', cada_horas INTEGER, hora TEXT NOT NULL DEFAULT '',
            ultima_revision TEXT, ultimo_resultado TEXT NOT NULL DEFAULT '');
        CREATE TABLE opciones_vistas_paginas (pagina_id INTEGER NOT NULL, filtro TEXT NOT NULL, texto TEXT NOT NULL,
            primera_vez TEXT NOT NULL, orden INTEGER NOT NULL DEFAULT 0, nueva INTEGER NOT NULL DEFAULT 0, descargada TEXT,
            archivos TEXT NOT NULL DEFAULT '[]', sin_orden INTEGER NOT NULL DEFAULT 0, novedad TEXT,
            PRIMARY KEY (pagina_id, filtro, texto));
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v33c_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ruta = os.path.join(self.tmp, "bot.db")

    def base_antigua(self, filas=True):
        """Una base de datos con las tablas de vigilancia de la 3.2 (una por reporte / por Página)."""
        alm = Almacen(self.ruta)
        rid = alm.guardar(flujo_reporte())
        pid = alm.guardar_pagina("Portal – Reportes", pagina_simple())
        alm.cerrar()
        con = sqlite3.connect(self.ruta)
        con.executescript(self.ANTIGUO)
        if filas:
            con.executescript("""
                INSERT INTO vigilancias VALUES (%(r)d, 2, 1, 1, 'horas', 4, '', '2026-10-26 08:00:00', 'nada nuevo', 0);
                INSERT INTO opciones_vistas VALUES (%(r)d, 2, '%(c43)s', '2026-10-20 08:00:00', 1, 0, NULL, '[]', 0, NULL);
                INSERT INTO opciones_vistas VALUES (%(r)d, 2, '%(c44)s', '2026-10-25 08:00:00', 0, 1, NULL, '[]', 0, '2026-10-25 08:00:00');
                INSERT INTO opciones_vistas VALUES (%(r)d, 3, 'Excel', '2026-10-20 08:00:00', 0, 0, NULL, '[]', 0, NULL);
                INSERT INTO vigilancias_paginas VALUES (%(p)d, 'f3', 1, 0, 'Mayorista', 0, 'diaria', NULL, '07:00', NULL, '');
                INSERT INTO opciones_vistas_paginas VALUES (%(p)d, 'f3', '%(c44)s', '2026-10-25 08:00:00', 0, 0,
                    '2026-10-25 09:00:00', '["a.xlsx"]', 0, '2026-10-25 08:00:00');
                """ % {"r": rid, "p": pid, "c43": C43, "c44": C44})
        con.commit()
        con.close()
        return rid, pid

    def test_convierte_con_copia_de_seguridad_antes(self):
        rid, pid = self.base_antigua()
        alm = Almacen(self.ruta)
        self.addCleanup(alm.cerrar)
        copia = self.ruta + ".antes-v3.3"
        self.assertEqual(alm.copia_v33, copia)
        # la copia es la base de datos tal cual estaba (con la tabla antigua)
        con = sqlite3.connect(copia)
        self.assertEqual([f[1] for f in con.execute("PRAGMA table_info(vigilancias)")][0], "reporte_id")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM opciones_vistas").fetchone()[0], 3)
        con.close()
        vigs = alm.lista_vigilancias()
        self.assertEqual([(v["tipo"], v.get("reporte_id"), v.get("pagina_id")) for v in vigs],
                         [("reporte", rid, None), ("pagina", None, pid)])
        vr, vp = vigs
        self.assertEqual((vr["paso"], vr["auto_descargar"], vr["frecuencia"], vr["cada_horas"], vr["ultimo_resultado"]),
                         (2, 1, "horas", 4, "nada nuevo"))
        self.assertEqual((vp["filtro"], vp["favorito"], vp["hora"]), ("f3", "Mayorista", "07:00"))
        self.assertEqual([o["texto"] for o in alm.opciones_de_vigilancia(vr["id"])], [C44, C43])
        self.assertEqual(alm.pendientes_vigilancia(vr["id"]), [C44])
        self.assertEqual(alm.opciones_de_vigilancia(vp["id"])[0]["archivos"], ["a.xlsx"])
        tablas = {f[0] for f in alm._con().execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"vigilancias_v32", "opciones_vistas_v32", "vigilancias_paginas_v32",
                         "opciones_vistas_paginas_v32"} <= tablas)
        self.assertNotIn("vigilancias_paginas", tablas)
        # lo visto de un paso sin vigilancia (3.2) sirve de referencia a una vigilancia nueva de ese paso
        nueva = alm.crear_vigilancia(reporte_id=rid, paso=3)
        self.assertEqual([o["texto"] for o in alm.opciones_de_vigilancia(nueva)], ["Excel"])
        # abrirla otra vez no vuelve a convertir ni a copiar
        alm.cerrar()
        alm2 = Almacen(self.ruta)
        self.addCleanup(alm2.cerrar)
        self.assertEqual(alm2.copia_v33, "")
        self.assertEqual(len(alm2.lista_vigilancias()), 3)
        self.assertFalse(os.path.exists(copia + " (2)"))

    def test_tablas_antiguas_vacias_tambien_con_copia(self):
        self.base_antigua(filas=False)                               # como la base de datos real del usuario
        alm = Almacen(self.ruta)
        self.addCleanup(alm.cerrar)
        self.assertTrue(os.path.isfile(self.ruta + ".antes-v3.3"))
        self.assertEqual(alm.lista_vigilancias(), [])
        self.assertIn("antes-v3.3", alm.meta("vigilancias_v33"))

    def test_base_nueva_sin_copia(self):
        alm = Almacen(self.ruta)
        self.addCleanup(alm.cerrar)
        self.assertEqual(alm.copia_v33, "")
        self.assertFalse(os.path.exists(self.ruta + ".antes-v3.3"))


class TestApiVigilancias(Base):
    def setUp(self):
        super().setUp()
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                                 listar_tareas=lambda: [], oculto_forzado=True,
                                 ejecutar_tareas=lambda cmd: (1, "(prueba: nunca se crean tareas)"))

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})

    def test_crear_listar_cambiar_borrar(self):
        pid = self.alm.guardar_pagina("Portal – Reportes", pagina_simple())
        rid = self.alm.guardar(flujo_reporte())
        a = self.api("POST", "vigilancias", {"pagina_id": pid, "filtro": "f3", "valores": {"f2": {"estrategia": "fija",
                                                                                                  "valor": "Mayorista"}}})
        b = self.api("POST", "vigilancias", {"pagina_id": pid, "filtro": "f3", "nombre": "Cartera", "auto_descargar": True,
                                             "valores": {"f2": {"estrategia": "fija", "valor": "Cartera"}}})
        c = self.api("POST", "vigilancias", {"reporte_id": rid, "paso": 2})
        self.assertEqual(a["vigilancia"]["etiqueta"], "Mayorista")
        self.assertEqual(b["vigilancia"]["etiqueta"], "Cartera")
        self.assertEqual(c["vigilancia"]["que"], "Paso 3: Elegir corte")
        d = self.api("GET", "vigilancia")
        pagina = next(x for x in d["paginas"] if x["id"] == pid)
        self.assertEqual([v["id"] for v in pagina["vigilancias"]], [a["vigilancia"]["id"], b["vigilancia"]["id"]])
        self.assertEqual(pagina["vigilancias"][0]["valores_texto"], ["Seleccione reporte = Mayorista"])
        self.assertEqual(next(x for x in d["reportes"] if x["id"] == rid)["vigilancias"][0]["id"], c["vigilancia"]["id"])
        self.assertEqual((d["total"], d["activas"]), (3, 3))
        vid = b["vigilancia"]["id"]
        v = self.api("PUT", "vigilancias/%d" % vid, {"activa": False, "frecuencia": "diaria", "hora": "06:30"})["vigilancia"]
        self.assertEqual((v["activa"], v["frecuencia"], v["hora"], v["auto_descargar"]), (0, "diaria", "06:30", 1))
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "vigilancias", {"pagina_id": pid, "filtro": "f5"})        # una fecha no se vigila
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "vigilancias", {"reporte_id": rid, "paso": 0})            # «Abrir» no es una lista
        # la página dice qué listas vigila (para la marca del formulario)
        vista = self.api("GET", "paginas/%d" % pid)
        self.assertEqual(len(vista["vigilancias"]), 2)
        self.assertTrue(next(f for f in vista["filtros"] if f["id"] == "f3")["vigilado"])
        # programar UNA vigilancia: --vigilancia-id N (sin crear la tarea)
        with mock.patch.object(programador, "MAX_TR", 2000):        # (la base de datos temporal tiene una ruta larga)
            pr = self.api("POST", "vigilancias/%d/programar" % vid, {"frecuencia": "HORAS", "cada_horas": 4, "hora": "08:00"})
        self.assertFalse(pr["creada"])
        self.assertIn("--vigilancia-id %d --vigilar --oculto" % vid, pr["comando"])
        self.assertIn("#%d" % vid, pr["tarea"])
        self.api("DELETE", "vigilancias/%d" % vid)
        self.assertEqual(len(self.alm.lista_vigilancias(pagina_id=pid)), 1)
        # compatibilidad 3.2: la vigilancia «de la página» sigue respondiendo (la principal)
        self.assertEqual(self.api("GET", "paginas/%d/vigilancia" % pid)["vigilancia"]["id"], a["vigilancia"]["id"])

    def test_programador_y_linea_de_comandos(self):
        tr = programador.comando_bot(os.path.join(RAIZ, "bot.py"), vigilancia_id=7)
        self.assertTrue(tr.endswith("--vigilancia-id 7 --vigilar --oculto"), tr)
        import bot
        errores = io.StringIO()
        with contextlib.redirect_stderr(errores), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bot.principal(["--vigilancia-id", "99", "--db", self.alm.ruta]), 2)
        self.assertIn("No existe la vigilancia número 99", errores.getvalue())
        pid = self.alm.guardar_pagina("P", pagina_simple())
        self.alm.crear_vigilancia(pagina_id=pid, filtro="f3", activa=False)            # pausada: «--vigilar» no la revisa
        errores = io.StringIO()
        with contextlib.redirect_stderr(errores), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bot.principal(["--vigilar", "--db", self.alm.ruta]), 2)
        self.assertIn("filtro vigilado", errores.getvalue())


class TestMapeadorV33(unittest.TestCase):
    def test_accion_adivinada(self):
        ver = {"k": 4, "tipo": "accion", "etiqueta": "Ver Reporte", "selectores": ["#ver"], "orden": 4, "pagina": 0}
        a = paginas.adivinar_accion([ver])
        self.assertEqual((a["tipo"], a["pestana"], a["generar"]["selectores"]), ("guardar_pagina", 1, ["#ver"]))
        consultar = {"k": 1, "tipo": "accion", "etiqueta": "Consultar", "selectores": ["#c"], "marco": ["#tab0_Frame"], "orden": 1}
        vista = {"k": 2, "tipo": "accion", "etiqueta": "Vista Exportar", "selectores": ["#v"], "marco": ["#tab0_Frame"],
                 "submenu": True, "orden": 2}
        a = paginas.adivinar_accion([consultar, vista])
        self.assertEqual(a["tipo"], "menu_exportar")
        self.assertEqual((a["generar"]["marco"], a["menu"][0]["objetivo"], a["exportar"]["objetivo"]),
                         (["#tab0_Frame"], "Vista Exportar", "Exportar"))
        data = paginas.normalizar({"url": "u", "filtros": [], "accion": a})
        pasos = paginas.pasos_accion(data)
        self.assertEqual([(p.tipo, p.marco) for p in pasos], [("clic", ["#tab0_Frame"]), ("pasar_raton", ["#tab0_Frame"]),
                                                             ("descargar", ["#tab0_Frame"])])

    def test_pagina_en_un_marco_y_campo_con_busqueda(self):
        mapa = [{"k": 0, "tipo": "lista", "etiqueta": "Almacén", "selectores": ["#alm"], "marco": ["#tab0_Frame"],
                 "pagina": 0, "orden": 0, "opciones": ["Central", "Este"], "valor": "Central"},
                {"k": 1, "tipo": "texto", "etiqueta": "Cuenta No.", "selectores": ["#cta"], "orden": 1, "valor": "",
                 "busqueda": {"selectores": ["#lupa"], "filas": [["1110209", "Asociacion Ejemplo"]], "tabla": "#grid"}}]
        data, k = paginas.desde_mapa(mapa, url="u", accion={"tipo": "descargar", "generar": {"selectores": ["#x"]}})
        fl, _i = paginas.construir_flujo(data, "P", {k[0]: {"estrategia": "fija", "valor": "Este"},
                                                     k[1]: {"valor": "1110209 · Asociacion Ejemplo"}})
        self.assertEqual([(p.tipo, p.marco) for p in fl.pasos[1:4]], [("elegir_opcion", ["#tab0_Frame"]), ("clic", []),
                                                                      ("clic", [])])
        self.assertEqual(fl.pasos[2].selectores, ["#lupa"])
        self.assertEqual(fl.pasos[3].selectores, ['#grid td:text-is("1110209")', 'td:text-is("1110209")'])
        fl, _i = paginas.construir_flujo(data, "P", {k[0]: {"estrategia": "fija", "valor": "Este"}, k[1]: {"valor": "999"}})
        self.assertEqual(fl.pasos[2].tipo, "escribir")                  # un texto que no es una fila: se escribe

    def test_avisos_del_mapa(self):
        vacio = {"filtros": [], "errores": [], "infos": [{"marco": [], "listo": "complete", "controles": 0, "url": "u",
                                                           "titulo": "Noticias"}]}
        self.assertIn("No se encontró ningún control", mapeador.avisos_del_mapa(vacio)[0])
        cargando = {"filtros": [], "errores": [], "infos": [{"marco": [], "listo": "loading", "controles": 3}]}
        self.assertIn("todavía se está cargando", mapeador.avisos_del_mapa(cargando)[0])
        login = {"filtros": [{"k": 0}], "errores": [], "infos": [{"marco": [], "clave": True, "controles": 3}]}
        self.assertIn("inicio de sesión", mapeador.avisos_del_mapa(login)[0])
        marcos = {"filtros": [{"k": 0}], "errores": [{"marco": "#f", "error": "no se pudo leer el marco: x"}], "infos": []}
        self.assertIn("No se pudieron leer 1 marco", mapeador.avisos_del_mapa(marcos)[0])
        self.assertEqual([f["pagina"] for f in mapeador.con_pestana([{"k": 0, "pagina": 2}], 0)], [0])

    def test_pasos_del_mapa_llevan_marco_y_pestana(self):
        f = {"k": 0, "tipo": "lista_nativa", "etiqueta": "Almacén", "selectores": ["#a"], "marco": ["#tab0_Frame"],
             "pagina": 1, "valor": "Central"}
        p = mapeador.paso_de_filtro(f, {"estrategia": "fija", "valor": "Central"})
        self.assertEqual((p.tipo, p.marco, p.pagina), ("elegir_opcion", ["#tab0_Frame"], 1))


if __name__ == "__main__":
    unittest.main()
