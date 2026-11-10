"""Pruebas de la versión 3.2 («Páginas») sin navegador:

- Conversión del mapa real de Portal (forma copiada en solo lectura de `datos/bot.db`: mapa 1 + reporte 10, sin usuarios
  ni contraseñas, en `tests/fijos/portal_mapa.json`) en la Página «Portal – Reportes», una sola vez y sin tocar el
  reporte ni el mapa.
- Flujo construido desde la Página (llegada + filtros + acción), nombre de los archivos, combinaciones, formulario
  (más reciente primero, «nueva», listas dependientes desconocidas), dependencias detectadas, favoritos, `--filtro`.
- Base de datos: `ejecuciones` antigua (reporte_id NOT NULL) convertida sin perder filas; historial con páginas; regla de
  novedad para un filtro de una Página.
- API: el interruptor «Sin abrir navegador» llega al ejecutor (oculto), comando de la tarea programada de un favorito,
  «Abrir archivo» solo dentro de las descargas.
Base de datos temporal; nunca se crean tareas ni se abren archivos de verdad.
"""

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

from test_servidor_ui import BaseApi  # noqa: E402
from webbot import paginas, programador  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.ejecutor import ResultadoEjecucion  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

FIJO = os.path.join(RAIZ, "tests", "fijos", "portal_mapa.json")
C44 = "44 - 2026 (09/10/2026 - 15/10/2026)"
C43 = "43 - 2026 (02/10/2026 - 08/10/2026)"
C45 = "45 - 2026 (16/10/2026 - 22/10/2026)"


def real():
    with open(FIJO, encoding="utf-8") as f:
        d = json.load(f)
    return Flujo.desde_dict(d["reporte"]), d["mapa"]


def pagina_simple():
    """Página de prueba: pestaña, reporte, corte (depende del reporte), fecha, casilla; Generar + Descargar."""
    return paginas.normalizar({
        "url": "https://portal.example/r", "llegada": [Paso("abrir_url", url="https://portal.example/r").a_dict()],
        "filtros": [
            {"id": "f1", "tipo": "pestana", "nombre": "Pestaña", "en_nombre": False,
             "pestanas": [{"texto": "Corte", "selectores": ["#t1"]}, {"texto": "Crédito y Cobros", "selectores": ["#t2"]}],
             "defecto": {"estrategia": "fija", "valor": "Corte"}},
            {"id": "f2", "tipo": "lista", "nombre": "Seleccione reporte", "selectores": ["#rep"],
             "defecto": {"estrategia": "fija", "valor": "Mayorista"}},
            {"id": "f3", "tipo": "lista", "nombre": "Elegir corte", "selectores": ["#corte"], "depende_de": ["f2"],
             "defecto": {"estrategia": "mas_reciente", "valor": ""}},
            {"id": "f4", "tipo": "lista_nativa", "nombre": "Formato", "selectores": ["#fmt"], "en_nombre": False,
             "defecto": {"estrategia": "fija", "valor": "Excel"}},
            {"id": "f5", "tipo": "fecha", "nombre": "Desde", "selectores": ["#desde"], "en_nombre": False,
             "defecto": {"valor": "{ayer:%d/%m/%Y}"}},
            {"id": "f6", "tipo": "casilla", "nombre": "Solo vencidos", "selectores": ["#venc"], "defecto": {"marcado": False}}],
        "accion": {"tipo": "boton_descarga", "generar": {"selectores": ["#generar"], "objetivo": "Generar"},
                   "descargar": {"selectores": ["#descargar"], "objetivo": "Descargar"}}})


class TestConversionMapaReal(unittest.TestCase):
    def test_pagina_portal_desde_el_mapa_real(self):
        fl, mapa = real()
        nombre, data, k_a_id, lecturas = paginas.convertir_reporte_y_mapa(fl, mapa)
        self.assertEqual(nombre, "Portal – Reportes")
        self.assertEqual([p["tipo"] for p in data["llegada"]], ["abrir_url"])          # los pasos antes del 1.er filtro
        self.assertEqual(data["llegada"][0]["url"], "https://portal.ejemplo.com/portal/#/reportes/corte")
        tipos = [(f["tipo"], f["nombre"]) for f in data["filtros"]]
        self.assertEqual(tipos[0], ("pestana", "Pestaña"))
        self.assertEqual([t["texto"] for t in data["filtros"][0]["pestanas"]], ["Corte", "Crédito y Cobros"])
        self.assertEqual(len(data["filtros"]), 6)
        for f in data["filtros"]:
            self.assertNotIn("Open", f["nombre"])                                       # reglas de nombres de la 3.1
        nombres = [f["nombre"] for f in data["filtros"]]
        self.assertEqual(len(set(n.lower() for n in nombres)), len(nombres))           # sin repetidos
        self.assertIn("Formato a Exportar", nombres)
        por = {f["nombre"]: f for f in data["filtros"]}
        # valores por defecto = lo que elegían los pasos del reporte 10
        self.assertEqual(por["Corte"]["defecto"], {"estrategia": "mas_reciente", "valor": ""})
        defectos = [f["defecto"].get("valor") for f in data["filtros"][2:]]
        self.assertEqual(defectos, ["Portal", "Cartera General", C44, "📊 Excel"])
        # acción: el reporte solo pulsaba «Generar» → Generar + «Descargar» (se habilita al terminar)
        self.assertEqual(data["accion"]["tipo"], "boton_descarga")
        self.assertEqual(data["accion"]["generar"]["objetivo"], "Generar")
        self.assertIn('role=button[name="Descargar"]', data["accion"]["descargar"]["selectores"])
        # en el nombre del archivo: no el formato ni la lista repetida de la barra superior
        self.assertFalse(por["Formato a Exportar"]["en_nombre"])
        self.assertFalse(por["Corte"]["en_nombre"])
        self.assertEqual(paginas.validar(data), [])
        self.assertEqual({fid for fid, _o, _p in lecturas}, {f["id"] for f in data["filtros"][1:]})
        fl2, idx = paginas.construir_flujo(data, nombre, paginas.combinaciones(data, paginas.seleccion_base(data))[0][0])
        self.assertEqual([p.tipo for p in fl2.pasos], ["abrir_url", "clic", "elegir_opcion", "elegir_opcion",
                                                       "elegir_opcion", "elegir_opcion", "elegir_opcion", "clic", "descargar"])
        self.assertEqual(fl2.problemas(), [])
        self.assertEqual(idx[data["filtros"][1]["id"]], 2)

    def test_convertir_una_vez_sin_tocar_el_reporte(self):
        tmp = tempfile.mkdtemp(prefix="botweb_v32_")
        self.addCleanup(shutil.rmtree, tmp, True)
        alm = Almacen(os.path.join(tmp, "b.db"))
        self.addCleanup(alm.cerrar)
        fl, mapa = real()
        fl.nombre = "Reporte mapeado"
        rid = alm.guardar(fl)
        mid = alm.guardar_mapa(rid, mapa["url"], mapa["alcance"], mapa["filtros"])
        antes = (alm.obtener(rid)["flujo"], alm.mapa(mid)["filtros"])
        mensajes = paginas.convertir_mapas(alm)
        self.assertEqual(len(mensajes), 1)
        self.assertIn("«Portal – Reportes»", mensajes[0])
        p = alm.listar_paginas()
        self.assertEqual([x["nombre"] for x in p], ["Portal – Reportes"])
        self.assertEqual(p[0]["host"], "portal.ejemplo.com")
        self.assertEqual(p[0]["data"]["perfil"], "reporte_%d" % rid)                 # la sesión ya iniciada
        self.assertEqual((alm.obtener(rid)["flujo"], alm.mapa(mid)["filtros"]), antes)  # no se cambia nada
        cortes = [x for x in alm.opciones_pagina(p[0]["id"]) if len(x["opciones"]) > 100]
        self.assertTrue(cortes)
        self.assertEqual(alm.notificaciones()[0]["tipo"], "pagina")
        self.assertEqual(paginas.convertir_mapas(alm), [])                           # solo una vez
        self.assertEqual(len(alm.listar_paginas()), 1)


class TestPaginaModelo(unittest.TestCase):
    def test_flujo_y_nombre_de_archivo(self):
        data = pagina_simple()
        sel = paginas.seleccion_base(data, seleccion={"f3": {"estrategia": "fija", "valor": C43}})
        combos = paginas.preparar(data, sel)
        self.assertEqual(len(combos), 1)
        fl, idx = paginas.construir_flujo(data, "Portal – Reportes", combos[0][0], combos[0][1])
        self.assertEqual([p.tipo for p in fl.pasos], ["abrir_url", "clic", "elegir_opcion", "elegir_opcion",
                                                      "elegir_opcion", "escribir", "marcar", "clic", "descargar"])
        self.assertEqual(fl.pasos[1].selectores, ["#t1"])
        self.assertEqual(fl.pasos[idx["f3"]].filtro, "Elegir corte")
        self.assertEqual(fl.pasos[-1].nombre, "{pagina} - {Seleccione reporte} - {Elegir corte}{ext}")
        self.assertEqual(fl.variables["Elegir corte"], C43)
        self.assertEqual(fl.problemas(), [])
        self.assertEqual(fl.variables_necesarias(), [])
        # varias opciones: una ejecución por combinación y el filtro que varía va en el nombre
        data["filtros"][2]["en_nombre"] = False
        sel = paginas.seleccion_base(data, seleccion={"f3": {"valores": ["40 - 2026 (x)", "41 - 2026 (y)"]},
                                                      "f4": {"valores": ["Excel", "CSV"]}})
        combos = paginas.preparar(data, sel)
        self.assertEqual(len(combos), 4)
        self.assertEqual(combos[0][1], ["f3", "f4"])
        fl, _ = paginas.construir_flujo(data, "P", combos[0][0], combos[0][1])
        self.assertEqual(fl.pasos[-1].nombre, "{pagina} - {Seleccione reporte} - {Elegir corte} - {Formato}{ext}")
        # plantilla propia (con fechas) y errores
        data["nombre_archivo"] = "Comisiones {Elegir corte} {hoy:%Y-%m-%d}"
        self.assertEqual(paginas.validar(data), [])
        data["nombre_archivo"] = "{No existe}"
        self.assertIn("no hay ningún filtro «No existe»", " ".join(paginas.validar(data)))
        # v3.8: un filtro sin opción ya no es un error: el ejecutor salta ese paso (y lo dice en el registro)
        self.assertTrue(paginas.preparar(pagina_simple(), {"f2": {"estrategia": "fija", "valor": ""}}))

    def test_formulario_mas_reciente_nueva_y_dependientes(self):
        data = pagina_simple()
        filas = [{"filtro": "f2", "padres": {}, "opciones": ["Mayorista", "Ventas"], "actualizado": "2026-10-26 08:00:00",
                  "fuente": "mapa"},
                 {"filtro": "f3", "padres": {"f2": "Mayorista"}, "opciones": [C43, C44, C45], "actualizado": "2026-10-26 08:00:00",
                  "fuente": "ejecucion"}]
        form = {f["id"]: f for f in paginas.formulario(data, filas, novedades={"f3": [C45]}, vigilado="f3")}
        corte = form["f3"]
        self.assertEqual([o["texto"] for o in corte["opciones"]], [C45, C44, C43])        # de la más reciente
        self.assertEqual((corte["mas_reciente"], corte["actual"]), (C45, C45))
        self.assertTrue(corte["opciones"][0]["nueva"] and corte["vigilado"])
        self.assertFalse(corte["desconocida"])
        self.assertEqual(paginas.actualizado(list(form.values())), "2026-10-26 08:00:00")
        self.assertEqual([o["texto"] for o in form["f1"]["opciones"]], ["Corte", "Crédito y Cobros"])
        # otro reporte: no se conoce su lista de cortes → hay que traerla
        form = {f["id"]: f for f in paginas.formulario(data, filas, {"f2": {"estrategia": "fija", "valor": "Ventas"}})}
        self.assertTrue(form["f3"]["desconocida"])
        self.assertIn("«Seleccione reporte» = «Ventas»", form["f3"]["nota"])

    def test_detectar_dependencias(self):
        data = pagina_simple()
        data["filtros"][2]["depende_de"] = []
        filas = [{"filtro": "f3", "padres": {"f2": "Mayorista"}, "opciones": [C43, C44]},
                 {"filtro": "f3", "padres": {"f2": "Mayorista"}, "opciones": [C43, C44, C45]}]     # llegó el 45: no cuenta
        self.assertEqual(paginas.detectar_dependencias(data, filas), [])
        filas.append({"filtro": "f3", "padres": {"f2": "Ventas"}, "opciones": ["Agosto 2026", "Septiembre 2026"]})
        cambios = paginas.detectar_dependencias(data, filas)
        self.assertEqual(data["filtros"][2]["depende_de"], ["f2"])
        self.assertIn("«Elegir corte» depende de «Seleccione reporte»", cambios[0])
        data["filtros"][2].update(depende_de=[], depende_manual=True)                   # puesto a mano: no se toca
        self.assertEqual(paginas.detectar_dependencias(data, filas), [])

    def test_favoritos_y_linea_de_comandos(self):
        data = pagina_simple()
        nombre = paginas.guardar_favorito(data, "Mayorista más reciente", {"f2": {"estrategia": "fija", "valor": "Mayorista"},
                                                                        "f3": {"estrategia": "mas_reciente", "valor": ""}})
        self.assertEqual(paginas.buscar_favorito(data, "mayorista MÁS reciente".replace("MÁS", "más"))["nombre"], nombre)
        sel = paginas.seleccion_base(data, favorito=nombre, seleccion=paginas.resolver_cli(data, ["Elegir corte=" + C43]))
        self.assertEqual(sel["f3"], {"valores": [C43]})
        self.assertEqual(sel["f2"], {"estrategia": "fija", "valor": "Mayorista"})
        sel = paginas.resolver_cli(data, ["elegir corte=más reciente", "Solo vencidos=sí", "Desde={hoy}"])
        self.assertEqual(sel, {"f3": {"estrategia": "mas_reciente", "valor": ""}, "f6": {"marcado": True},
                               "f5": {"valores": ["{hoy}"]}})
        sel = paginas.resolver_cli(data, ["Elegir corte=" + C43, "Elegir corte=" + C44])
        self.assertEqual(len(paginas.combinaciones(data, paginas.seleccion_base(data, seleccion=sel))), 2)
        for malo in (["No existe=1"], ["Elegir corte"]):
            with self.assertRaises(paginas.ErrorPagina):
                paginas.resolver_cli(data, malo)
        with self.assertRaises(paginas.ErrorPagina):
            paginas.buscar_favorito(data, "otro")
        paginas.borrar_favorito(data, nombre)
        self.assertEqual(data["favoritos"], [])

    def test_nombres(self):
        self.assertEqual(paginas.nombre_sugerido("https://portal.ejemplo.com/portal/#/reportes/corte"), "Portal – Reportes")
        self.assertEqual(paginas.nombre_sugerido("https://erp.ejemplo.com/Pages/Consulta.aspx"), "ERP – Consulta")
        self.assertEqual(paginas.nombre_sugerido("http://127.0.0.1:8000/informes.html?x=1"), "Informes")
        for malo in ("Open", "", "a{b}", "x:y", "pagina"):
            with self.assertRaises(paginas.ErrorPagina):
                paginas.validar_nombre_filtro(malo)

    def test_comando_programado_de_un_favorito(self):
        cmd = programador.construir_comando_crear("Portal – Reportes - Mayorista", os.path.join(RAIZ, "bot.py"),
                                                  hora="07:30", pagina_id=3, favorito="Mayorista")
        tr = cmd[cmd.index("/TR") + 1]
        self.assertIn('--pagina-id 3 --favorito "Mayorista" --sin-ventana --oculto', tr)
        self.assertEqual(cmd[:4], ["schtasks", "/Create", "/TN", "BotWeb\\Portal – Reportes - Mayorista"])
        tr = programador.comando_bot(os.path.join(RAIZ, "bot.py"), pagina_id=3, vigilar=True)
        self.assertIn("--pagina-id 3 --vigilar --oculto", tr)
        with self.assertRaises(programador.ErrorProgramador):
            programador.comando_bot("bot.py", pagina_id=1, favorito='a"b')


class TestAlmacenV32(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v32a_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_ejecuciones_antiguas_se_convierten(self):
        ruta = os.path.join(self.tmp, "vieja.db")
        con = sqlite3.connect(ruta)
        con.executescript("""
            CREATE TABLE reportes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, url TEXT NOT NULL DEFAULT '',
              flujo TEXT NOT NULL, creado TEXT NOT NULL, modificado TEXT NOT NULL, eliminado TEXT, origen TEXT NOT NULL DEFAULT '');
            CREATE TABLE ejecuciones (id INTEGER PRIMARY KEY AUTOINCREMENT, reporte_id INTEGER NOT NULL REFERENCES reportes(id)
              ON DELETE CASCADE, cuando TEXT NOT NULL, resultado TEXT NOT NULL, mensaje TEXT NOT NULL DEFAULT '',
              archivos TEXT NOT NULL DEFAULT '[]', duracion REAL, registro TEXT NOT NULL DEFAULT '',
              captura TEXT NOT NULL DEFAULT '');
            INSERT INTO reportes(nombre, flujo, creado, modificado) VALUES ('Ventas', '{"pasos": []}', 'x', 'x');
            INSERT INTO ejecuciones(reporte_id, cuando, resultado, archivos) VALUES (1, '2026-10-25 08:00:00', 'ok', '["a.csv"]');
            INSERT INTO ejecuciones(reporte_id, cuando, resultado) VALUES (1, '2026-10-26 08:00:00', 'error');
        """)
        con.commit()
        con.close()
        alm = Almacen(ruta)
        self.addCleanup(alm.cerrar)
        h = alm.historial()
        self.assertEqual([(e["id"], e["resultado"], e["nombre"]) for e in h], [(2, "error", "Ventas"), (1, "ok", "Ventas")])
        self.assertEqual(h[1]["archivos"], ["a.csv"])
        pid = alm.guardar_pagina("Portal – Reportes", pagina_simple())
        self.assertTrue(alm.registrar_ejecucion(None, "ok", archivos=[r"C:\d\x.xlsx"], pagina_id=pid))
        self.assertFalse(alm.registrar_ejecucion(None, "ok", pagina_id=999))
        h = alm.historial()
        self.assertEqual((h[0]["nombre"], h[0]["pagina_id"], h[0]["reporte_id"]), ("Portal – Reportes", pid, None))
        self.assertEqual([e["nombre"] for e in alm.historial(1)], ["Ventas", "Ventas"])
        self.assertEqual(len(alm.historial(pagina_id=pid)), 1)
        self.assertEqual(alm.listar_paginas()[0]["resultado"], "ok")
        alm.cerrar()
        alm2 = Almacen(ruta)                                    # abrirla otra vez no vuelve a convertir nada
        self.addCleanup(alm2.cerrar)
        self.assertEqual(len(alm2.historial()), 3)
        alm2.borrar_pagina(pid)
        self.assertEqual(len(alm2.historial()), 2)

    def test_novedad_en_un_filtro_de_pagina(self):
        alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(alm.cerrar)
        pid = alm.guardar_pagina("P", pagina_simple())
        alm.guardar_vigilancia_pagina(pid, "f3", auto_descargar=True, favorito="Mayorista")
        self.assertTrue(alm.registrar_opciones_pagina(pid, "f3", [C43, C44], detalle=True)["primera"])
        det = alm.registrar_opciones_pagina(pid, "f3", ["45 - 2023 (x)", C43, C44, C45], detalle=True)
        self.assertEqual(det["nuevas"], [C45])                       # «45 - 2023» es antiguo: no es novedad
        self.assertEqual(alm.pendientes_pagina(pid, "f3"), [C45])
        self.assertEqual(alm.novedades_pagina(pid, "f3"), [C45])
        alm.marcar_descargada_pagina(pid, "f3", C45, [r"C:\d\a.xlsx"])
        self.assertEqual(alm.pendientes_pagina(pid, "f3"), [])
        self.assertEqual(alm.vigilancias_paginas()[0]["favorito"], "Mayorista")
        self.assertEqual(alm.resumen_inicio()["paginas"], 1)
        alm.guardar_opciones_pagina(pid, "f3", [C43], {"f2": "Mayorista"}, "ejecucion")
        alm.guardar_opciones_pagina(pid, "f3", [C44], {"f2": "Mayorista"}, "actualizar")       # misma combinación: se cambia
        self.assertEqual([(f["opciones"], f["padres"], f["fuente"]) for f in alm.opciones_pagina(pid, "f3")],
                         [([C44], {"f2": "Mayorista"}, "actualizar")])


class _EjecutorFalso:
    vistos = []

    def __init__(self, flujo, **kw):
        _EjecutorFalso.vistos.append({"oculto": kw.get("oculto"), "pedir_acceso": kw.get("pedir_acceso"),
                                      "pasos": [p.tipo for p in flujo.pasos], "perfil": kw.get("carpeta_perfil")})
        self.lineas_inicio = []

    def ejecutar(self):
        r = ResultadoEjecucion()
        r.ok = True
        return r


class TestApiPaginas(BaseApi):
    def crear(self):
        from webbot import paginas as mp
        pid, _n = mp.guardar_nueva(self.alm, "Portal – Reportes", pagina_simple(),
                                   [("f2", ["Mayorista", "Ventas"], {}), ("f3", [C43, C44], {"f2": "Mayorista"})])
        return pid

    def test_interruptor_sin_abrir_navegador(self):
        pid = self.crear()
        self.app.oculto_forzado = None                      # (el ejecutor es falso: no se abre ningún navegador)
        _EjecutorFalso.vistos = []
        with mock.patch("webbot.ejecutor.Ejecutor", _EjecutorFalso):
            for sin in (True, False, None):
                datos = {"seleccion": {}} if sin is None else {"seleccion": {}, "sin_navegador": sin}
                t = self.api("POST", "paginas/%d/ejecutar" % pid, datos)
                fin, _ev = self.esperar_trabajo(t["id"])
                self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual([v["oculto"] for v in _EjecutorFalso.vistos], [True, False, True])   # por defecto: sin navegador
        self.assertTrue(all(v["pedir_acceso"] is not None for v in _EjecutorFalso.vistos))  # se puede preguntar igual
        self.assertTrue(_EjecutorFalso.vistos[0]["perfil"].endswith("pagina_%d" % pid))
        self.assertEqual(_EjecutorFalso.vistos[0]["pasos"][-2:], ["clic", "descargar"])
        self.assertEqual([e["resultado"] for e in self.alm.historial(pagina_id=pid)], ["ok", "ok", "ok"])
        v = self.api("GET", "paginas/%d" % pid)
        self.assertTrue(v["sin_navegador"])
        self.assertEqual([f["nombre"] for f in v["filtros"]], ["Pestaña", "Seleccione reporte", "Elegir corte",
                                                               "Formato", "Desde", "Solo vencidos"])
        lista = self.api("GET", "paginas")["paginas"]
        self.assertEqual((lista[0]["nombre"], lista[0]["resultado"]), ("Portal – Reportes", "ok"))
        # más de 10 ejecuciones: se pide confirmación
        r = self.api("POST", "paginas/%d/ejecutar" % pid, {"seleccion": {"f3": {"valores": ["%d - 2026" % n for n in range(30, 41)]}}})
        self.assertEqual((r["confirmar"], r["n"]), (True, 11))

    def test_favoritos_programar_y_configurar(self):
        pid = self.crear()
        r = self.api("POST", "paginas/%d/favoritos" % pid, {"nombre": "Mayorista", "seleccion": {
            "f2": {"estrategia": "fija", "valor": "Mayorista"}, "f3": {"estrategia": "mas_reciente", "valor": ""}}})
        self.assertEqual(r["favoritos"][0]["nombre"], "Mayorista")
        self.assertIn("Elegir corte: la más reciente", r["favoritos"][0]["descripcion"])
        with mock.patch.object(programador, "MAX_TR", 2000):           # (la base de datos temporal alarga el comando)
            pr = self.api("POST", "paginas/%d/programar" % pid, {"favorito": "Mayorista", "frecuencia": "DIARIA",
                                                                  "hora": "08:00"})
        self.assertFalse(pr["creada"])                                   # sin confirmar no se crea nada
        self.assertIn('--pagina-id %d --favorito "Mayorista" --sin-ventana --oculto' % pid, pr["comando"])
        self.assertEqual(pr["tarea"], "BotWeb\\Portal – Reportes - Mayorista")
        codigo, err = self.llamar("POST", "api/paginas/%d/programar" % pid, {"favorito": "No existe"})
        self.assertEqual(codigo, 400, err)
        # configurar: renombrar un filtro y la plantilla del nombre
        v = self.api("GET", "paginas/%d" % pid)
        data = v["data"]
        data["filtros"][3]["nombre"] = "Formato a exportar"
        data["nombre_archivo"] = "{pagina} {Elegir corte}"
        v = self.api("PUT", "paginas/%d" % pid, {"nombre": "Portal", "data": data})
        self.assertEqual((v["nombre"], v["filtros"][3]["nombre"]), ("Portal", "Formato a exportar"))
        data["filtros"][3]["nombre"] = "Open"
        codigo, err = self.llamar("PUT", "api/paginas/%d" % pid, {"data": data})
        self.assertEqual(codigo, 400, err)
        v = self.api("POST", "paginas/%d/predeterminado" % pid, {"seleccion": {"f3": {"valores": [C43]}}})
        self.assertEqual(next(f for f in v["filtros"] if f["id"] == "f3")["defecto"], {"estrategia": "fija", "valor": C43})
        codigo, _e = self.llamar("DELETE", "api/paginas/%d" % pid, {})
        self.assertEqual(codigo, 400)                                    # hay que confirmarlo
        self.api("DELETE", "paginas/%d" % pid, {"confirmar": True})
        self.assertEqual(self.api("GET", "paginas")["paginas"], [])

    def test_abrir_archivo_solo_en_descargas(self):
        abiertos = []
        self.app.abrir_en_sistema = lambda ruta, carpeta=False: abiertos.append((os.path.basename(ruta), carpeta))
        os.makedirs(os.path.join(self.tmp, "descargas"), exist_ok=True)
        dentro = os.path.join(self.tmp, "descargas", "Portal.xlsx")
        with open(dentro, "w") as f:
            f.write("x")
        self.api("POST", "archivos/abrir", {"ruta": dentro})
        self.api("POST", "archivos/carpeta", {"ruta": dentro})
        self.assertEqual(abiertos, [("Portal.xlsx", False), ("Portal.xlsx", True)])
        fuera = os.path.join(self.tmp, "otro.xlsx")
        with open(fuera, "w") as f:
            f.write("x")
        codigo, _e = self.llamar("POST", "api/archivos/abrir", {"ruta": fuera})
        self.assertEqual(codigo, 403)
        exe = os.path.join(self.tmp, "descargas", "malo.exe")
        with open(exe, "w") as f:
            f.write("x")
        codigo, _e = self.llamar("POST", "api/archivos/abrir", {"ruta": exe})
        self.assertEqual(codigo, 400)
        self.assertEqual(len(abiertos), 2)


if __name__ == "__main__":
    unittest.main()
