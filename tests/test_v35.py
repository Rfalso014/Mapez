"""Pruebas de la versión 3.5 (parte 1): tres arreglos pedidos por el usuario.

1. «El bot no suele colocar el nombre completo del reporte»: plantilla {reporte}, nombre por defecto de las descargas
   («{reporte} {hoy:%Y-%m-%d}{ext}»), nombres con puntos y comas, la grabación, la conversión (una vez, con copia en
   «Versiones anteriores») de los reportes que guardaban con el nombre de la web, y la API del editor.  Con navegador
   oculto y el sitio de prueba: una descarga de verdad con el nombre completo de un reporte con puntos.
2. «Elegir carpeta con el explorador de Windows»: `webbot/dialogos.py` y POST /api/elegir con un elegidor FALSO (nunca
   se abre un diálogo de verdad: el de Tk queda parcheado para fallar), un diálogo a la vez, cancelar, y la seguridad
   (token y Origin) por HTTP.
3. Correo: «Correos relacionados» (todos los que cumplen la búsqueda, con otro rango de fechas, del más reciente al más
   antiguo, con su estado y «Cargar más») y «Procesar este / seleccionados» aunque ya se hubieran procesado (actualiza
   el registro, no lo duplica; aviso antes de duplicar filas de Excel).
Bases de datos temporales, contraseñas en memoria, ningún aviso de Windows, schtasks nunca se ejecuta, sin Internet.
"""

import datetime as dt
import http.client
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import bot  # noqa: E402
from test_v34_correo import ASUNTO, HOY, AdaptadorFalso, Base, buzon, mensaje  # noqa: E402
from webbot import VERSION, correo, dialogos, paginas, plantillas  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.ejecutor import Ejecutor, nombre_archivo_seguro, ruta_libre, separar_extension  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402
from webbot.grabador_web import GrabadorWeb  # noqa: E402

NOMBRE = "Ventas, Cobros y Comisiones – Empresa Ejemplo S.A.S."       # nombre largo, con comas, acentos y puntos


def _dialogo_real(*a, **k):
    raise AssertionError("¡Una prueba intentó abrir un diálogo de Windows de verdad!")


class SinDialogos(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(dialogos, "_dialogo_tk", _dialogo_real)
        p.start()
        self.addCleanup(p.stop)


# ============================================================================ 1. nombre completo del reporte
class TestPlantillaReporte(unittest.TestCase):
    def test_reporte_en_las_plantillas(self):
        r = plantillas.renderizar("{reporte} {hoy:%Y-%m-%d}{ext}", hoy=HOY, ext=".xlsx", nombre="report_xls",
                                  reporte=NOMBRE)
        self.assertEqual(r, NOMBRE + " 2026-10-29.xlsx")
        self.assertEqual(plantillas.renderizar("{reporte} - {nombre}{ext}", ext=".csv", nombre="report_xls",
                                               reporte="X"), "X - report_xls.csv")
        with self.assertRaises(plantillas.ErrorPlantilla):
            plantillas.renderizar("{reporte}")                     # fuera de un reporte no hay nombre
        # una variable propia «reporte» del flujo tiene prioridad (los flujos antiguos que la usaban siguen igual)
        self.assertEqual(plantillas.renderizar("{reporte}", variables={"reporte": "propio"}, reporte="X"), "propio")
        self.assertIn("reporte", plantillas.RESERVADAS)
        self.assertEqual(plantillas.variables_usadas("{reporte} {cliente}{ext}"), ["cliente"])
        f = Flujo(nombre="R", pasos=[Paso("descargar", selectores=["#d"], nombre="{reporte} {hoy:%Y-%m-%d}{ext}")])
        self.assertEqual(f.variables_necesarias(), [])
        self.assertEqual(f.problemas(), [])

    def test_el_nombre_completo_sobrevive_al_limpiar(self):
        nombre = plantillas.renderizar("{reporte} {hoy:%Y-%m-%d}{ext}", hoy=HOY, ext=".xlsx", reporte=NOMBRE)
        self.assertEqual(nombre_archivo_seguro(nombre), NOMBRE + " 2026-10-29.xlsx")     # comas, acentos, puntos
        self.assertEqual(nombre_archivo_seguro("Ventas: Norte/Sur? 2026.xlsx"), "Ventas_ Norte_Sur_ 2026.xlsx")
        # la extensión con puntos en el nombre
        self.assertEqual(separar_extension("Ventas S.A.S. 2026-10-29.xlsx"), ("Ventas S.A.S. 2026-10-29", ".xlsx"))
        self.assertEqual(separar_extension("Ventas S.A.S. 2026-10-29"), ("Ventas S.A.S. 2026-10-29", ""))
        self.assertEqual(separar_extension("Ventas S.A.S"), ("Ventas S.A", ".S"))       # (sin pista: se adivina)
        self.assertEqual(separar_extension("Ventas S.A.S", ""), ("Ventas S.A.S", ""))   # la extensión conocida manda
        self.assertEqual(separar_extension("report.xls"), ("report", ".xls"))

    def test_ruta_libre_con_puntos(self):
        tmp = tempfile.mkdtemp(prefix="botweb_v35_")
        self.addCleanup(shutil.rmtree, tmp, True)
        for nombre in ("Ventas S.A.S. 2026-10-29.xlsx", "Ventas S.A.S. 2026-10-29"):
            ruta = os.path.join(tmp, nombre)
            open(ruta, "w").close()
        self.assertEqual(os.path.basename(ruta_libre(os.path.join(tmp, "Ventas S.A.S. 2026-10-29.xlsx"))),
                         "Ventas S.A.S. 2026-10-29 (2).xlsx")
        self.assertEqual(os.path.basename(ruta_libre(os.path.join(tmp, "Ventas S.A.S. 2026-10-29"))),
                         "Ventas S.A.S. 2026-10-29 (2)")                # y no «Ventas S.A.S (2). 2026-10-29»

    def test_ejecutor_y_paginas_usan_el_nombre(self):
        ej = Ejecutor(Flujo(nombre=NOMBRE), carpeta_perfil="x", carpeta_registros="x", hoy=HOY)
        self.assertEqual(ej._r(mod_flujo.NOMBRE_DESCARGA_DEFECTO, ext=".xlsx", nombre="report_xls"),
                         NOMBRE + " 2026-10-29.xlsx")
        self.assertEqual(ej._r_log("{reporte}"), NOMBRE)
        # en una Página, {reporte} = el nombre de la Página
        data = paginas.normalizar({"url": "http://x/", "llegada": [{"tipo": "abrir_url", "url": "http://x/"}],
                                   "filtros": [], "nombre_archivo": "{reporte} {hoy:%Y-%m-%d}",
                                   "accion": {"tipo": "descargar", "generar": {"selectores": ["#g"]}}})
        self.assertIsNone(paginas.validar_plantilla(data, data["nombre_archivo"]))
        fl, _ = paginas.construir_flujo(data, "Portal – Reportes", {})
        ej = Ejecutor(fl, carpeta_perfil="x", carpeta_registros="x", hoy=HOY)
        self.assertEqual(ej._r(fl.pasos[-1].nombre, ext=".csv", nombre="x"), "Portal – Reportes 2026-10-29.csv")
        # en el correo, {reporte} = el nombre de la búsqueda
        ctx = dict(correo.contexto_prueba(), reporte="Ventas diarias, S.A.S.")
        self.assertEqual(correo.nombre_final("{reporte} {fecha_correo:%Y-%m-%d}", ctx), "Ventas diarias, S.A.S. 2026-01-31.xlsx")
        correo.normalizar_accion({"tipo": "adjuntos", "nombre": "{reporte} {fecha_correo:%Y-%m-%d}"})   # válida


class TestNombresDeDescarga(unittest.TestCase):
    def test_reconocer_el_nombre_de_la_web(self):
        for n in ("report_xls{ext}", "DetallesVentasMayorista{ext}", "Reporte {{1}}{ext}", "ventas.final{ext}"):
            self.assertTrue(mod_flujo.es_nombre_de_la_web(n), n)
        for n in ("", "{ext}", "{nombre}{ext}", "{reporte} {hoy:%Y-%m-%d}{ext}", "Ventas_{hoy:%Y-%m-%d}{ext}",
                  "Portal_{opcion}{ext}", "report_xls.xlsx", "Corte_{nombre}{ext}", "  {ext}", "{sin cerrar{ext}"):
            self.assertFalse(mod_flujo.es_nombre_de_la_web(n), n)

    def test_usar_el_nombre_del_reporte(self):
        f = Flujo(nombre=NOMBRE, pasos=[Paso("abrir_url", url="http://x/"),
                                        Paso("descargar", selectores=["#d"], nombre="report_xls{ext}")])
        self.assertEqual(mod_flujo.pasos_con_nombre_de_la_web(f), [1])
        self.assertEqual(mod_flujo.usar_nombre_del_reporte(f), [(1, "report_xls{ext}", "{reporte} {hoy:%Y-%m-%d}{ext}")])
        self.assertEqual(mod_flujo.usar_nombre_del_reporte(f), [])            # ya está
        # varias descargas: además el nombre de la web, para que no se pisen; con «Repetir por días», {fecha}
        f = Flujo(nombre="R", pasos=[Paso("descargar", selectores=["#a"], nombre="ventas{ext}"),
                                     Paso("descargar", selectores=["#b"], nombre="Clientes_{hoy:%Y-%m-%d}{ext}"),
                                     Paso("descargar", selectores=["#c"], nombre="")])
        f.opciones["repetir_dias"] = {"modo": "ultimos", "n": 3}
        cambios = mod_flujo.usar_nombre_del_reporte(f)
        self.assertEqual(cambios, [(0, "ventas{ext}", "{reporte} - {nombre} {fecha:%Y-%m-%d}{ext}")])
        self.assertEqual(f.pasos[1].nombre, "Clientes_{hoy:%Y-%m-%d}{ext}")   # elegido por el usuario: no se toca
        self.assertEqual(f.pasos[2].nombre, "")
        self.assertEqual(len(mod_flujo.usar_nombre_del_reporte(f, solo_de_la_web=False)), 1)   # (el vacío, a mano)

    def test_grabacion_pone_el_nombre_del_reporte(self):
        class Descarga:
            def __init__(self, nombre):
                self.suggested_filename = nombre

            def save_as(self, ruta):
                open(ruta, "w").close()

            def failure(self):
                return None
        tmp = tempfile.mkdtemp(prefix="botweb_v35_")
        self.addCleanup(shutil.rmtree, tmp, True)
        f = Flujo(nombre="Grabado")
        eventos = []
        g = GrabadorWeb(f, os.path.join(tmp, "p"), al_evento=lambda t, **d: eventos.append((t, d)), hoy=HOY,
                        carpeta_descargas_grabacion=os.path.join(tmp, "grab"))
        f.pasos.append(Paso("clic", selectores=["#d1"]))
        g._procesar_descarga(None, Descarga("report_xls.xlsx"))
        self.assertEqual((f.pasos[0].tipo, f.pasos[0].nombre), ("descargar", "{reporte} {hoy:%Y-%m-%d}{ext}"))
        self.assertTrue(any("nombre del reporte" in d.get("texto", "") for t, d in eventos if t == "estado"))
        # la segunda descarga del mismo reporte: las dos llevan también el nombre de la web
        f.pasos.append(Paso("clic", selectores=["#d2"]))
        g._procesar_descarga(None, Descarga("clientes.csv"))
        self.assertEqual([p.nombre for p in f.pasos], ["{reporte} - {nombre} {hoy:%Y-%m-%d}{ext}"] * 2)
        self.assertEqual(sorted(os.listdir(os.path.join(tmp, "grab"))), ["clientes.csv", "report_xls.xlsx"])


class TestConversionDeReportes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v35_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)

    def reporte(self, nombre, *nombres, **opciones):
        f = Flujo(nombre=nombre, url="http://x/", pasos=[Paso("abrir_url", url="http://x/")] +
                  [Paso("descargar", selectores=["#d%d" % i], nombre=n) for i, n in enumerate(nombres)])
        f.opciones.update(opciones)
        return self.alm.guardar(f)

    def test_una_sola_vez_con_copia(self):
        erp = self.reporte("ERP – Existencias, S.A.S.", "report_xls{ext}")
        portal = self.reporte("Portal Mayorista", "DetallesVentasMayorista{ext}", "Otro{ext}")
        propio = self.reporte("Propio", "Ventas_{hoy:%Y-%m-%d}{ext}")
        dias = self.reporte("Por días", "diario{ext}", repetir_dias={"modo": "ultimos", "n": 2})
        mensajes = bot.migrar_reportes(self.alm)
        textos = " ".join(mensajes)
        self.assertIn("«ERP – Existencias, S.A.S.»", textos)
        self.assertIn("report_xls{ext}", textos)
        self.assertNotIn("«Propio»", textos)
        self.assertEqual([p.nombre for p in self.alm.cargar_flujo(erp).pasos[1:]], ["{reporte} {hoy:%Y-%m-%d}{ext}"])
        self.assertEqual([p.nombre for p in self.alm.cargar_flujo(portal).pasos[1:]],
                         ["{reporte} - {nombre} {hoy:%Y-%m-%d}{ext}"] * 2)
        self.assertEqual(self.alm.cargar_flujo(propio).pasos[1].nombre, "Ventas_{hoy:%Y-%m-%d}{ext}")
        self.assertEqual(self.alm.cargar_flujo(dias).pasos[1].nombre, "{reporte} {fecha:%Y-%m-%d}{ext}")
        # copia de cada reporte cambiado (y solo de esos), que se puede restaurar
        self.assertEqual(self.alm.versiones(propio), [])
        v = self.alm.versiones(erp)
        self.assertEqual(len(v), 1)
        self.assertIn("v3.5", v[0]["motivo"])
        self.assertEqual(self.alm.flujo_de_version(v[0]["id"]).pasos[1].nombre, "report_xls{ext}")
        # un aviso en la campana
        n = [x for x in self.alm.notificaciones() if x["tipo"] == "nombres_descarga"]
        self.assertEqual(len(n), 1)
        self.assertEqual(sorted(n[0]["datos"]["reportes"]), sorted([erp, portal, dias]))
        # solo una vez: lo que se ponga después (p. ej. «Nombre que da la web» o una restauración) se respeta
        self.alm.restaurar_version(v[0]["id"])
        self.assertEqual(bot.migrar_reportes(self.alm), [])
        self.assertEqual(self.alm.cargar_flujo(erp).pasos[1].nombre, "report_xls{ext}")
        self.assertEqual(self.alm.meta(Almacen.META_NOMBRES_V35), "1")

    def test_base_vacia_y_reporte_danado(self):
        self.assertEqual(self.alm.migrar_nombres_descarga(), [])
        self.assertEqual(self.alm.meta(Almacen.META_NOMBRES_V35), "1")
        rid = self.reporte("Dañado", "x{ext}")
        with sqlite3.connect(self.alm.ruta) as c:
            c.execute("UPDATE reportes SET flujo = '{roto' WHERE id = ?", (rid,))
        self.assertEqual(self.alm.migrar_nombres_descarga(forzar=True), [])    # se deja como estaba


class TestApiNombres(SinDialogos):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="botweb_v35_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=self.tmp, carpeta_registros=self.tmp, listar_tareas=lambda: [],
                                 oculto_forzado=True, hoy=HOY, ejecutar_tareas=lambda c: (1, "no"))

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})

    def test_editor(self):
        f = Flujo(nombre=NOMBRE, pasos=[Paso("abrir_url", url="http://x/"),
                                        Paso("descargar", selectores=["#d"], nombre="report_xls{ext}")]).a_dict()
        d = self.api("POST", "flujo/describir", {"flujo": f})
        self.assertEqual(d["nombres_web"], [1])
        r = self.api("POST", "flujo/usar_nombre_reporte", {"flujo": f})
        self.assertEqual(r["cambios"], [{"paso": 1, "antes": "report_xls{ext}", "despues": "{reporte} {hoy:%Y-%m-%d}{ext}"}])
        self.assertEqual(r["flujo"]["pasos"][1]["nombre"], "{reporte} {hoy:%Y-%m-%d}{ext}")
        self.assertEqual(self.api("POST", "flujo/describir", {"flujo": r["flujo"]})["nombres_web"], [])
        v = self.api("POST", "plantilla", {"texto": "{reporte} {hoy:%Y-%m-%d}{ext}", "reporte": NOMBRE})
        self.assertEqual(v, {"vista": NOMBRE + " 2026-10-29.xlsx", "error": ""})
        v = self.api("POST", "plantilla", {"texto": "{reporte} - {nombre}{ext}"})
        self.assertEqual(v["vista"], "Nombre del reporte - nombre_que_da_la_web.xlsx")
        self.assertIn("{reporte}", [x[0] for x in self.api("GET", "ayuda")["plantillas"]])
        self.assertEqual(self.api("GET", "estado")["version"], VERSION)
        self.assertEqual(VERSION, "3.6")


# ============================================================================ 2. elegir carpeta / archivo
class TestDialogos(SinDialogos):
    def test_elegir_en_su_propio_hilo(self):
        visto = {}

        def falso(tipo, inicial, filtros, titulo):
            visto.update(hilo=threading.current_thread().name, tipo=tipo, inicial=inicial, filtros=filtros, titulo=titulo)
            return r"C:\Reportes\Ventas, S.A.S"
        self.assertEqual(dialogos.elegir("carpeta", "C:\\x", abrir=falso), r"C:\Reportes\Ventas, S.A.S")
        self.assertEqual(visto["hilo"], "dialogo-carpeta")
        self.assertNotEqual(visto["hilo"], threading.current_thread().name)
        self.assertEqual(visto["titulo"], "Elegir carpeta")
        dialogos.elegir("guardar", "", [["Excel", "*.xlsx"], ["mal"], ["CSV", "*.csv"]], "Archivo", abrir=falso)
        self.assertEqual(visto["filtros"], [("Excel", "*.xlsx"), ("CSV", "*.csv"), ("Todos los archivos", "*.*")])
        self.assertIsNone(dialogos.elegir("archivo", abrir=lambda *a: None))            # cancelar
        with self.assertRaises(dialogos.ErrorDialogo) as e:
            dialogos.elegir("carpeta", abrir=lambda *a: (_ for _ in ()).throw(RuntimeError("sin escritorio")))
        self.assertIn("Escribe la ruta a mano", str(e.exception))
        with self.assertRaises(dialogos.ErrorDialogo):
            dialogos.elegir("otra cosa", abrir=falso)
        with self.assertRaises(dialogos.ErrorDialogo):                                   # (el Tk real está parcheado)
            dialogos.elegir("carpeta")

    def test_un_dialogo_a_la_vez(self):
        dentro, maximo, cerrojo = [0], [0], threading.Lock()

        def lento(*a):
            with cerrojo:
                dentro[0] += 1
                maximo[0] = max(maximo[0], dentro[0])
            time.sleep(0.15)
            with cerrojo:
                dentro[0] -= 1
            return "C:\\x"
        hilos = [threading.Thread(target=dialogos.elegir, args=("carpeta",), kwargs={"abrir": lento}) for _ in range(3)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(10)
        self.assertEqual(maximo[0], 1)

    def test_carpeta_existente(self):
        tmp = tempfile.mkdtemp(prefix="botweb_v35_")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertEqual(dialogos.carpeta_existente(os.path.join(tmp, "no", "existe", "x.xlsx")), tmp)
        self.assertEqual(dialogos.carpeta_existente(""), "")


class TestApiElegir(SinDialogos):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="botweb_v35_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.llamadas = []
        self.respuesta = os.path.join(self.tmp, "Elegida, S.A.S")

        def falso(tipo, inicial, filtros, titulo):
            self.llamadas.append((tipo, inicial, filtros, titulo))
            return self.respuesta
        self.descargas = os.path.join(self.tmp, "descargas")
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=self.tmp, carpeta_registros=self.tmp, listar_tareas=lambda: [],
                                 carpeta_descargas=self.descargas, oculto_forzado=True, hoy=HOY,
                                 ejecutar_tareas=lambda c: (1, "no"), abrir_dialogo=falso)

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})

    def test_elegir(self):
        self.assertEqual(self.api("POST", "elegir", {"tipo": "carpeta"}), {"ruta": self.respuesta, "cancelado": False})
        self.assertEqual(self.llamadas[-1][:2], ("carpeta", self.descargas))                 # vacío = la de descargas
        self.api("POST", "elegir", {"tipo": "carpeta", "inicial": "migracion"})
        self.assertEqual(self.llamadas[-1][1], os.path.join(self.descargas, "migracion"))   # relativa = dentro
        self.api("POST", "elegir", {"tipo": "carpeta", "inicial": "Correo\\{fecha_correo:%Y-%m}"})
        self.assertEqual(self.llamadas[-1][1], os.path.join(self.descargas, "Correo\\"))    # la parte fija
        self.api("POST", "elegir", {"tipo": "guardar", "inicial": "C:\\Reportes\\Ventas.xlsx",
                                    "filtros": [["Excel", "*.xlsx"]], "titulo": "Archivo Excel"})
        self.assertEqual(self.llamadas[-1], ("guardar", "C:\\Reportes\\Ventas.xlsx",
                                             [("Excel", "*.xlsx"), ("Todos los archivos", "*.*")], "Archivo Excel"))
        self.respuesta = None
        self.assertEqual(self.api("POST", "elegir", {"tipo": "archivo"}), {"ruta": None, "cancelado": True})
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "elegir", {"tipo": "disco"})
        with self.assertRaises(su.ErrorApi) as e:
            self.api("GET", "elegir")
        self.assertEqual(e.exception.codigo, 405)

    def test_por_http_con_token_y_origen(self):
        srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(srv.parar)

        def pedir(cabeceras):
            c = http.client.HTTPConnection("127.0.0.1", srv.puerto, timeout=10)
            try:
                cuerpo = json.dumps({"tipo": "carpeta"})
                c.request("POST", "/api/elegir", cuerpo, dict({"Content-Type": "application/json",
                                                               "Host": "127.0.0.1:%d" % srv.puerto}, **cabeceras))
                r = c.getresponse()
                return r.status, json.loads(r.read().decode("utf-8"))
            finally:
                c.close()
        self.assertEqual(pedir({})[0], 401)                                           # sin token
        self.assertEqual(pedir({"X-Bot-Token": self.app.token, "Origin": "http://otra.web"})[0], 403)
        self.assertEqual(pedir({"X-Bot-Token": self.app.token, "Sec-Fetch-Site": "cross-site"})[0], 403)
        n = len(self.llamadas)
        self.assertEqual(n, 0)                                                         # nada se abrió
        estado, datos = pedir({"X-Bot-Token": self.app.token, "Origin": "http://127.0.0.1:%d" % srv.puerto})
        self.assertEqual((estado, datos["ruta"]), (200, self.respuesta))

    def test_la_interfaz_tiene_elegir_en_todas_las_rutas(self):
        with open(os.path.join(RAIZ, "ui", "app.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("function campoRuta(inp, opc)", js)
        for trozo in ("campoRuta(o.carpeta_descargas", "campoRuta(f.carpeta_descargas", "campoRuta(carpetaPag",
                      "tipo: 'guardar', filtros: FILTROS_EXCEL", "tipo: 'guardar', filtros: FILTROS_ANOTAR",
                      "campoRuta(campo('carpeta'", "campoRuta(inp, { tipo: 'carpeta'"):
            self.assertIn(trozo, js)
        self.assertEqual(js.count("campoRuta(campo('carpeta'"), 2)                    # adjuntos y cuerpo del correo


# ============================================================================ 3. correos relacionados
def buzon_largo():
    """El buzón de la 3.4 + correos más antiguos que el rango de la búsqueda (7 días)."""
    return buzon() + [mensaje("v%d" % i, d, (9, 0)) for i, d in enumerate((12, 20, 40, 80, 200))]


class TestRelacionados(Base):
    def revisar(self, bid, falso, **k):
        return correo.revisar_busqueda(self.alm, bid, falso, self.base, HOY, carpeta_registros=os.path.join(self.tmp, "reg"),
                                       **k)

    def test_rangos_y_ayudas(self):
        c = correo.normalizar_criterios({"asunto": "X", "fecha": "ultimos", "dias": 7})
        self.assertEqual(correo.criterios_con_rango(c, "busqueda"), c)
        self.assertEqual(correo.criterios_con_rango(c, "todas")["fecha"], "cualquiera")
        self.assertEqual((correo.criterios_con_rango(c, "90")["fecha"], correo.criterios_con_rango(c, "90")["dias"]),
                         ("ultimos", 90))
        self.assertEqual(c["dias"], 7)                                                    # no cambia la búsqueda
        for malo in ("abc", "0", "99999"):
            with self.assertRaises(correo.ErrorCorreo):
                correo.criterios_con_rango(c, malo)
        acc = correo.normalizar_acciones([{"tipo": "tabla", "archivo": "a.xlsx", "modo": "agregar"},
                                          {"tipo": "tabla", "archivo": "b.xlsx", "modo": "reemplazar"},
                                          {"tipo": "texto", "etiqueta": "Total:", "archivo": "v.csv"},
                                          {"tipo": "texto", "etiqueta": "Total:"}, {"tipo": "adjuntos"}])
        self.assertEqual(len(correo.acciones_que_agregan(acc)), 2)
        self.assertEqual(correo.estado_de(None), ("nuevo", "nuevo"))
        self.assertEqual(correo.estado_de({"estado": "ok", "cuando": "2026-10-29 10:00"}),
                         ("procesado", "ya procesado el 2026-10-29 10:00"))

    def test_lista_con_estados_paginas_y_rango(self):
        bid = self.busqueda()
        falso = AdaptadorFalso(buzon_largo())
        self.revisar(bid, falso)                                     # a1, a2 ok; a5 con error
        crit = self.alm.busqueda_correo(bid)["criterios"]
        # con las fechas de la búsqueda (7 días): solo los de la búsqueda
        r = correo.correos_relacionados(falso, crit, HOY, "busqueda", almacen=self.alm, busqueda_id=bid)
        self.assertEqual([m["asunto"][-10:] for m in r["mensajes"]], ["29/10/2026", "28/10/2026", "27/10/2026"])
        # 30 días: también a4 (hace 10 días) y v0, v1 (12 y 20 días), del más reciente al más antiguo
        r = correo.correos_relacionados(falso, crit, HOY, "30", almacen=self.alm, busqueda_id=bid)
        ms = r["mensajes"]
        self.assertEqual(len(ms), 6)
        self.assertEqual([m["mas_reciente"] for m in ms], [True] + [False] * 5)
        self.assertEqual([m["estado"] for m in ms], ["procesado", "procesado", "error", "nuevo", "nuevo", "nuevo"])
        self.assertTrue(ms[0]["estado_texto"].startswith("ya procesado el "))
        self.assertEqual(ms[0]["archivos"], [os.path.join(self.base, "migracion", "Ventas 2026-10-29.xlsx")])
        self.assertEqual(ms[0]["adjuntos"], ["SUPERVISION VENTAS EJEMPLO V1.4.xlsx"])
        self.assertFalse(r["hay_mas"])
        self.assertNotIn("a3", [m["clave"] for m in ms])                                   # otro remitente
        # todas las fechas, de 3 en 3 («Cargar más»)
        r1 = correo.correos_relacionados(falso, crit, HOY, "todas", 0, 3, almacen=self.alm, busqueda_id=bid)
        r2 = correo.correos_relacionados(falso, crit, HOY, "todas", 3, 3, almacen=self.alm, busqueda_id=bid)
        r3 = correo.correos_relacionados(falso, crit, HOY, "todas", 6, 3, almacen=self.alm, busqueda_id=bid)
        self.assertEqual((r1["hay_mas"], r2["hay_mas"], r3["hay_mas"]), (True, True, False))
        todas = [m["clave"] for m in r1["mensajes"] + r2["mensajes"] + r3["mensajes"]]
        self.assertEqual(len(todas), 9)
        self.assertEqual(len(set(todas)), 9)
        self.assertFalse(r2["mensajes"][0]["mas_reciente"])
        self.assertEqual(r3["mensajes"][-1]["fecha"][:10], (HOY - dt.timedelta(days=200)).strftime("%d/%m/%Y"))
        # sin abrir los correos: más rápido, los adjuntos no se saben
        falso.abiertos.clear()
        r = correo.correos_relacionados(falso, crit, HOY, "30", abrir=False)
        self.assertEqual(falso.abiertos, [])
        self.assertIsNone(r["mensajes"][0]["adjuntos"])
        # la lista NUNCA procesa nada
        self.assertEqual(len(self.alm.procesados_correo(bid, incluir_descartados=True)), 3)

    def test_procesar_a_mano_aunque_ya_se_procesara(self):
        bid = self.busqueda()
        falso = AdaptadorFalso(buzon_largo())
        self.revisar(bid, falso)
        n_hist = len(self.alm.historial(correo_id=bid))
        crit = self.alm.busqueda_correo(bid)["criterios"]
        ms = correo.correos_relacionados(falso, crit, HOY, "30", almacen=self.alm, busqueda_id=bid)["mensajes"]
        a1, a4 = ms[0]["clave"], ms[3]["clave"]
        antes = self.alm.correo_procesado(bid, a1)
        self.avisos.clear()
        falso.abiertos.clear()
        r = self.revisar(bid, falso, solo=[a1, a4], rango="30")
        self.assertTrue(r.ok, r.error)
        self.assertEqual(falso.abiertos, ["a1", "a4"])                         # solo los elegidos
        self.assertEqual([p["reprocesado"] for p in r.procesados], [True, False])
        # a1 se procesó otra vez: TODAS sus acciones (otra descarga «(2)»), y su registro se actualiza (no se duplica)
        self.assertEqual(r.procesados[0]["archivos"], [os.path.join(self.base, "migracion", "Ventas 2026-10-29 (2).xlsx")])
        self.assertEqual(r.procesados[0]["valores"], [("Total ventas", "1.234")])
        with sqlite3.connect(self.alm.ruta) as c:
            filas = c.execute("SELECT COUNT(*) FROM correos_procesados WHERE busqueda_id = ? AND clave = ?",
                              (bid, a1)).fetchone()[0]
        self.assertEqual(filas, 1)
        despues = self.alm.correo_procesado(bid, a1)
        self.assertEqual((despues["estado"], despues["intentos"]), ("ok", 1))
        self.assertIn("Procesado otra vez a mano", despues["mensaje"])
        self.assertGreaterEqual(despues["cuando"], antes["cuando"])
        self.assertEqual(despues["archivos"], r.procesados[0]["archivos"])
        # a4 (de hace 10 días, fuera de la búsqueda) se procesó con el rango de 30 días
        self.assertEqual(self.alm.correo_procesado(bid, a4)["estado"], "ok")
        self.assertTrue(os.path.isfile(os.path.join(self.base, "migracion", "Ventas 2026-10-19.xlsx")))
        # avisos e historial como siempre; procesar a mano no cambia la «última revisión»
        titulos = [n["titulo"] for n in self.alm.notificaciones()]
        self.assertIn("Procesado otra vez «%s»: 1 archivo guardado, Total ventas: 1.234" % (ASUNTO % "29/10/2026"), titulos)
        self.assertEqual(len(self.avisos), 1)
        h = self.alm.historial(correo_id=bid)
        self.assertEqual(len(h), n_hist + 1)
        self.assertEqual(h[0]["resultado"], "ok")
        with open(h[0]["registro"], encoding="utf-8") as f:
            self.assertIn("Procesar a mano", f.read())
        self.assertNotIn("Procesar a mano", self.alm.busqueda_correo(bid)["ultimo_resultado"] or "")
        # la próxima revisión normal no los repite
        falso.abiertos.clear()
        self.revisar(bid, falso)
        self.assertNotIn("a1", falso.abiertos)
        self.assertNotIn("a4", falso.abiertos)
        # un correo que ya no está en el buzón
        r = self.revisar(bid, falso, solo=["falso:borrado|2026-10-01T09:00"], rango="todas")
        self.assertEqual((r.no_encontrados, r.procesados), (1, []))
        self.assertIn("ya no aparecen en el buzón", r.resumen())


class TestApiRelacionados(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(dialogos, "_dialogo_tk", _dialogo_real)
        p.start()
        self.addCleanup(p.stop)
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                                 carpeta_descargas=self.base, listar_tareas=lambda: [], oculto_forzado=True, hoy=HOY,
                                 ejecutar_tareas=lambda c: (1, "no"))
        self.falso = AdaptadorFalso(buzon_largo())
        self.app._fabrica_correo = lambda t, ver=False, esperar_login=0: self.falso

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})

    def esperar(self):
        self.app.trabajo.hilo.join(30)
        self.assertFalse(self.app.trabajo.hilo.is_alive())

    def eventos(self, tipo):
        return [e for e in self.app.eventos.desde(0)[0] if e["tipo"] == tipo]

    def test_lista_y_procesar(self):
        bid = self.busqueda(acciones=[{"tipo": "adjuntos", "coincide": "supervision ventas", "carpeta": "migracion"},
                                      {"tipo": "tabla", "n": 1, "archivo": "ventas.csv", "modo": "agregar"}])
        d = self.api("GET", "correo")
        self.assertIn("todas", d["rangos"])
        self.assertEqual(d["busquedas"][0]["agrega"], ["copiar la tabla 1 a «ventas.csv» (agrega filas)"])
        t = self.api("POST", "correo/busquedas/%d/relacionados" % bid, {"rango": "30", "limite": 4})
        self.assertEqual(t["tipo"], "correo_relacionados")
        self.esperar()
        ev = self.eventos("correo_relacionados")[-1]
        self.assertEqual((ev["trabajo"], ev["ok"], ev["busqueda_id"], ev["hay_mas"]), (t["id"], True, bid, True))
        self.assertEqual(len(ev["mensajes"]), 4)
        self.assertTrue(ev["mensajes"][0]["mas_reciente"])
        self.assertEqual({m["estado"] for m in ev["mensajes"]}, {"nuevo"})
        claves = [m["clave"] for m in ev["mensajes"][:2]]
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "correo/busquedas/%d/relacionados" % bid, {"rango": "mil años"})
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "correo/busquedas/%d/procesar" % bid, {"claves": []})
        # nuevos: se procesan sin preguntar
        t = self.api("POST", "correo/busquedas/%d/procesar" % bid, {"claves": claves, "rango": "30", "buscar_hasta": 9})
        self.assertEqual(t["tipo"], "correo")
        self.esperar()
        ev = self.eventos("correo")[-1]
        self.assertTrue(ev["a_mano"])
        self.assertEqual(sorted(ev["claves"]), sorted(claves))
        with open(os.path.join(self.base, "ventas.csv"), encoding="utf-8-sig") as f:
            filas = f.read().strip().splitlines()
        # otra vez: ya procesados y la tabla AGREGA filas → se pide confirmación (nada se lanza)
        r = self.api("POST", "correo/busquedas/%d/procesar" % bid, {"claves": claves[:1], "rango": "30"})
        self.assertTrue(r["confirmar"])
        self.assertIn("repetidas", r["mensaje"])
        self.assertEqual(r["ya_procesados"], 1)
        n_trab = len(self.eventos("trabajo"))
        self.assertEqual(len(self.eventos("trabajo")), n_trab)
        t = self.api("POST", "correo/busquedas/%d/procesar" % bid, {"claves": claves[:1], "rango": "30", "confirmar": True})
        self.esperar()
        self.assertEqual(self.app.trabajo.estado, "ok", self.app.trabajo.resumen)
        with open(os.path.join(self.base, "ventas.csv"), encoding="utf-8-sig") as f:
            self.assertGreater(len(f.read().strip().splitlines()), len(filas))      # (el usuario lo aceptó)
        with sqlite3.connect(self.alm.ruta) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM correos_procesados WHERE busqueda_id = ?",
                                       (bid,)).fetchone()[0], 2)
        # la lista lo marca ya procesado
        self.api("POST", "correo/busquedas/%d/relacionados" % bid, {"rango": "30", "limite": 4})
        self.esperar()
        ms = self.eventos("correo_relacionados")[-1]["mensajes"]
        self.assertEqual(ms[0]["estado"], "procesado")
        self.assertEqual(ms[1]["estado"], "error")           # (a2 no trae la tabla: esa acción falla, se apunta igual)

    def test_sesion_caducada(self):
        bid = self.busqueda()
        self.falso.sesion = False
        self.api("POST", "correo/busquedas/%d/relacionados" % bid, {"rango": "todas"})
        self.esperar()
        ev = self.eventos("correo_relacionados")[-1]
        self.assertEqual((ev["ok"], ev["sesion_caducada"]), (False, True))
        self.assertEqual(self.alm.cuenta_correo(self.alm.busqueda_correo(bid)["cuenta_id"])["estado_sesion"], "caducada")


# ============================================================================ integración (navegador oculto)
try:
    from test_integracion import HAY_PLAYWRIGHT, BaseIntegracion
except ImportError:                          # pragma: no cover
    HAY_PLAYWRIGHT, BaseIntegracion = False, unittest.TestCase


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestDescargaConElNombreDelReporte(BaseIntegracion):
    def test_descarga_real_con_nombre_completo(self):
        f = Flujo(nombre="Ventas, Cobros – Empresa S.A.S.", url=self.base + "multiples.html")
        f.opciones.update(timeout_paso=15, pausa_entre_pasos=0)
        f.pasos = [Paso("abrir_url", url=self.base + "multiples.html"),
                   Paso("descargar", selectores=["#d1"], nombre=mod_flujo.NOMBRE_DESCARGA_DEFECTO),
                   Paso("descargar", selectores=["#d1"], nombre=mod_flujo.NOMBRE_DESCARGA_DEFECTO),
                   Paso("descargar", selectores=["#d2"], nombre=mod_flujo.NOMBRE_DESCARGA_VARIAS)]
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen())
        self.assertEqual([os.path.basename(a) for a in res.archivos],
                         ["Ventas, Cobros – Empresa S.A.S. 2026-03-15.csv",
                          "Ventas, Cobros – Empresa S.A.S. 2026-03-15 (2).csv",
                          "Ventas, Cobros – Empresa S.A.S. - clientes 2026-03-15.csv"])
        with open(res.archivos[2], encoding="utf-8") as fh:
            self.assertIn("clientes,7", fh.read())


try:
    from test_integracion_v34_correo import ADJ as ADJ_WEB, BaseCorreo
except ImportError:                          # pragma: no cover
    BaseCorreo = unittest.TestCase


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestRelacionadosOutlook(BaseCorreo):
    """El buzón de prueba que imita Outlook (navegador oculto), por la API como el usuario."""

    def test_relacionados_y_procesar_otra_vez(self):
        c = self.cuenta()
        b = self.busqueda(c["id"])
        fin, _evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        # la lista con 30 días: m1 y m2 (procesados) y m4 (hace 10 días: su adjunto es un .zip, al abrirlo no coincide)
        fin, evs = self.lanzar("correo/busquedas/%d/relacionados" % b["id"], {"rango": "30"})
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        ms = [e for e in evs if e["tipo"] == "correo_relacionados"][0]["mensajes"]
        self.assertEqual(len(ms), 3)
        self.assertTrue(ms[0]["mas_reciente"])
        self.assertEqual([m["estado"] for m in ms], ["procesado", "procesado", "nuevo"])
        self.assertIn(ADJ_WEB, ms[0]["adjuntos"])
        self.assertFalse(ms[2]["coincide"])
        hoy = self.hoy.strftime("%Y-%m-%d")
        # «Procesar otra vez» el más reciente: se descarga de nuevo y su registro se actualiza
        fin, evs = self.lanzar("correo/busquedas/%d/procesar" % b["id"], {"claves": [ms[0]["clave"]], "rango": "30"})
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        with open(self.archivo("migracion", "Ventas %s (2).xlsx" % hoy), "rb") as f:
            self.assertEqual(f.read(), b"xlsx-de-hoy")
        procesados = self.api("GET", "correo/busquedas/%d/procesados" % b["id"])["procesados"]
        self.assertEqual(len(procesados), 2)                       # sin duplicar
        p = next(x for x in procesados if x["clave"] == ms[0]["clave"])
        self.assertIn("Procesado otra vez a mano", p["mensaje"])
        self.assertEqual(p["archivos"], [self.archivo("migracion", "Ventas %s (2).xlsx" % hoy)])


if __name__ == "__main__":
    unittest.main()
