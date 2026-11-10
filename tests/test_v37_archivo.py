"""Pruebas de la versión 3.7: «Archivo descargado» (nombre y carpeta) en todas las partes de la interfaz.

Petición del usuario (30/10): «Poder renombrar y elegir dónde se quiere guardar el archivo en todas las funciones de la
página. Que aparezca cuando terminan el proceso de mapeo. Cuando le dan a configurar.»

1. Python: `flujo.nombre_con_ext` / `nombre_sin_ext` (el nombre se escribe sin la extensión), `pasos_que_guardan`,
   `flujo.vista_archivo` y `paginas.vista_archivo` («Se guardará como: … en …», calculado como el Ejecutor), la API
   (`POST /api/plantilla` con «archivo», la propuesta de «Guardar como Página», «Guardar como Página» y «Crear pasos»
   con nombre y carpeta) y que SIN tocar nada todo queda como antes.
2. Interfaz (navegador oculto): el editor del reporte (una y dos descargas; el mismo dato que «Guardar como» del paso),
   «Configurar esta página», y al terminar de mapear («Guardar como Página…» y «Crear pasos»; el mapa se simula
   interceptando `mapa/mapear`: no se abre ningún otro navegador ni web).

Base de datos temporal, contraseñas en memoria, sin avisos de Windows, sin tareas programadas, sin diálogos de Windows.
"""

import datetime
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from webbot import RAIZ as RAIZ_BOT  # noqa: E402
from webbot import avisos, dialogos, paginas, plantillas, secretos  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

HOY = datetime.date(2026, 10, 30)
NOMBRE = "POrtal Ventas, S.A.S."

# Un mapa como el que devuelve «Mapear página» (mapeador.js)
FILTROS_MAPA = [
    {"k": 0, "tipo": "lista", "etiqueta": "Seleccione reporte", "valor": "Mayorista", "selectores": ["#rep"], "orden": 0,
     "opciones": ["Mayorista", "Detalle"]},
    {"k": 1, "tipo": "lista", "etiqueta": "Elegir corte", "valor": "45 - 2026", "selectores": ["#corte"], "orden": 1,
     "opciones": ["45 - 2026", "44 - 2026"]},
    {"k": 2, "tipo": "accion", "etiqueta": "Exportar", "selectores": ["#exportar"], "orden": 2, "descarga": True},
]


def _dialogo_real(*a, **k):
    raise AssertionError("¡Una prueba intentó abrir un diálogo de Windows de verdad!")


class Base(unittest.TestCase):
    carpeta_forzada = True

    def setUp(self):
        p = mock.patch.object(dialogos, "_dialogo_tk", _dialogo_real)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp(prefix="botweb_v37_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        avisos.usar_notificador(lambda t, x: None)
        self.addCleanup(avisos.usar_notificador, None)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.descargas = os.path.join(self.tmp, "descargas") if self.carpeta_forzada else None
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "perfiles"),
                                 carpeta_registros=os.path.join(self.tmp, "registros"), carpeta_descargas=self.descargas,
                                 listar_tareas=lambda: [], oculto_forzado=True, hoy=HOY,
                                 ejecutar_tareas=lambda c: (1, "(prueba: sin tareas)"), abrir_dialogo=_dialogo_real)
        self.addCleanup(self.app.detener)

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})


# ============================================================================ 1. Python
class TestNombreSinExtension(unittest.TestCase):
    def test_con_y_sin_ext(self):
        self.assertEqual(mod_flujo.NOMBRE_ARCHIVO_DEFECTO, "{reporte} {hoy:%Y-%m-%d}")
        self.assertEqual(mod_flujo.nombre_con_ext(mod_flujo.NOMBRE_ARCHIVO_DEFECTO), mod_flujo.NOMBRE_DESCARGA_DEFECTO)
        self.assertEqual(mod_flujo.nombre_con_ext("  Ventas {hoy:%Y}  "), "Ventas {hoy:%Y}{ext}")
        self.assertEqual(mod_flujo.nombre_con_ext("{nombre}{ext}.bak"), "{nombre}{ext}.bak")      # {ext} en medio
        self.assertEqual(mod_flujo.nombre_con_ext(""), "")                                       # vacío = la web
        self.assertEqual(mod_flujo.nombre_con_ext(None), "")
        for t in (mod_flujo.NOMBRE_DESCARGA_DEFECTO, mod_flujo.NOMBRE_DESCARGA_VARIAS, "report_xls{ext}",
                  "{nombre}{ext}", "Corte_{opcion}{ext}", ""):
            self.assertEqual(mod_flujo.nombre_con_ext(mod_flujo.nombre_sin_ext(t)), t, t)     # ida y vuelta exacta
        self.assertEqual(mod_flujo.nombre_sin_ext("{nombre}{ext}.bak"), "{nombre}{ext}.bak")

    def test_pasos_que_guardan(self):
        f = Flujo(nombre="R", pasos=[Paso("abrir_url", url="http://x/"), Paso("descargar", selectores=["#a"]),
                                     Paso("descargar", selectores=["#b"], desactivado=True),
                                     Paso("guardar_pagina", formato="pdf", nombre="Informe")])
        self.assertEqual(mod_flujo.pasos_que_guardan(f), [1, 3])


class TestVistaArchivo(unittest.TestCase):
    def test_como_el_ejecutor(self):
        raiz = os.path.join(tempfile.gettempdir(), "bot")
        v = mod_flujo.vista_archivo
        self.assertEqual(v(mod_flujo.NOMBRE_DESCARGA_DEFECTO, reporte=NOMBRE, hoy=HOY, raiz=raiz),
                         (NOMBRE + " 2026-10-30.xlsx", os.path.join(raiz, "descargas")))
        # vacío = el nombre que da la web; carpeta propia del paso relativa = dentro de la del reporte
        base = os.path.join(raiz, "Reportes")
        self.assertEqual(v("", hoy=HOY, carpeta=base, subcarpeta="Portal\\{hoy:%Y}", raiz=raiz),
                         ("nombre_que_da_la_web.xlsx", os.path.join(base, "Portal\\2026")))
        # la carpeta del paso absoluta manda; «Guardar página» pone la extensión del formato
        otra = os.path.join(raiz, "Otra")
        self.assertEqual(v("Informe_{hoy:%Y}", "guardar_pagina", hoy=HOY, formato="pdf", carpeta=base, subcarpeta=otra),
                         ("Informe_2026.pdf", otra))
        # el bot abierto con otra carpeta de descargas (--descargas) manda sobre la del reporte (como el Ejecutor)
        self.assertEqual(v("x{ext}", carpeta=base, carpeta_forzada=otra)[1], os.path.abspath(otra))
        # caracteres que Windows no admite: como nombre_archivo_seguro
        self.assertEqual(v("A/B: {hoy:%d/%m}{ext}", hoy=HOY)[0], "A_B_ 30_10.xlsx")
        self.assertEqual(v("{secreto:clave}{ext}", hoy=HOY)[0], "_.xlsx")          # nunca la contraseña («********»)
        with self.assertRaises(plantillas.ErrorPlantilla):
            v("{cliente}{ext}", hoy=HOY)
        self.assertEqual(v("{cliente}{ext}", hoy=HOY, variables={"cliente": "Acme"})[0], "Acme.xlsx")

    def test_pagina_igual_que_sus_pasos(self):
        data = paginas.normalizar({
            "url": "http://x/", "llegada": [],
            "filtros": [{"id": "f1", "tipo": "lista", "nombre": "Seleccione reporte", "defecto": {"estrategia": "fija",
                                                                                                "valor": "Mayorista"}},
                        {"id": "f2", "tipo": "lista", "nombre": "Elegir corte"},
                        {"id": "f3", "tipo": "texto", "nombre": "Cliente", "en_nombre": False}],
            "accion": {"tipo": "descargar", "generar": {"selectores": ["#e"], "objetivo": "Exportar"}}})
        # la plantilla de siempre: la misma que pone pasos_accion en el paso «Descargar»
        paso = paginas.pasos_accion(data)[-1]
        self.assertEqual(paso.nombre, "{pagina} - {Seleccione reporte} - {Elegir corte}{ext}")
        archivo, carpeta = paginas.vista_archivo(data, "Portal – Reportes", hoy=HOY, raiz=self._raiz())
        self.assertEqual(archivo, "Portal – Reportes - Mayorista - «Elegir corte».xlsx")      # «la más reciente»
        self.assertEqual(carpeta, os.path.join(self._raiz(), "descargas"))
        # lo escrito sin guardar todavía
        self.assertEqual(paginas.vista_archivo(data, "Portal", plantilla="{pagina} {hoy:%Y-%m-%d}", hoy=HOY,
                                               carpeta="C:\\Reportes")[0:2], ("Portal 2026-10-30.xlsx", "C:\\Reportes"))
        with self.assertRaises(paginas.ErrorPagina) as e:
            paginas.vista_archivo(data, "Portal", plantilla="{Corte}")
        self.assertIn("no hay ningún filtro «Corte»", str(e.exception))
        # «Guardar página»: la extensión del formato
        data["accion"] = {"tipo": "guardar_pagina", "formato": "csv", "generar": {"selectores": ["#v"], "objetivo": "Ver"}}
        self.assertTrue(paginas.vista_archivo(data, "Portal", hoy=HOY)[0].endswith(".csv"))

    @staticmethod
    def _raiz():
        return os.path.join(tempfile.gettempdir(), "bot")


class TestApi(Base):
    def test_plantilla_con_archivo(self):
        r = self.api("POST", "plantilla", {"archivo": "descargar", "texto": "{reporte} {hoy:%Y-%m-%d}", "reporte": NOMBRE})
        self.assertEqual(r["archivo"], NOMBRE + " 2026-10-30.xlsx")
        self.assertEqual(r["carpeta"], os.path.abspath(self.descargas))                     # la del bot (forzada)
        self.assertEqual(r["ruta"], os.path.join(r["carpeta"], r["archivo"]))
        self.assertEqual(r["error"], "")
        r = self.api("POST", "plantilla", {"archivo": "descargar", "texto": "", "subcarpeta": "Portal"})
        self.assertEqual((r["archivo"], r["carpeta"]), ("nombre_que_da_la_web.xlsx",
                                                        os.path.join(os.path.abspath(self.descargas), "Portal")))
        r = self.api("POST", "plantilla", {"archivo": "descargar", "texto": "{cliente} {opcion}",
                                           "variables": {"cliente": "Acme"}})
        self.assertEqual(r["archivo"], "Acme opción elegida.xlsx")
        r = self.api("POST", "plantilla", {"archivo": "guardar_pagina", "texto": "Informe", "formato": "pdf"})
        self.assertEqual(r["archivo"], "Informe.pdf")
        r = self.api("POST", "plantilla", {"archivo": "descargar", "texto": "Ventas }"})
        self.assertIn("llave", r["error"])
        self.assertEqual(r["archivo"], "")
        # sin «archivo»: igual que antes
        self.assertEqual(self.api("POST", "plantilla", {"texto": "{reporte} {hoy:%Y-%m-%d}{ext}", "reporte": "X"}),
                         {"vista": "X 2026-10-30.xlsx", "error": ""})

    def test_plantilla_de_una_pagina(self):
        pid, _ = paginas.guardar_nueva(self.alm, "Portal – Reportes", {
            "url": "http://x/", "llegada": [Paso("abrir_url", url="http://x/").a_dict()], "filtros": [
                {"id": "f1", "tipo": "lista", "nombre": "Corte", "selectores": ["#c"],
                 "defecto": {"estrategia": "fija", "valor": "45 - 2026"}}],
            "accion": {"tipo": "descargar", "generar": {"selectores": ["#e"], "objetivo": "Exportar"}}})
        r = self.api("POST", "plantilla", {"archivo": "pagina", "texto": "", "pagina_id": pid})
        self.assertEqual(r["archivo"], "Portal – Reportes - 45 - 2026.xlsx")
        r = self.api("POST", "plantilla", {"archivo": "pagina", "texto": "{pagina} {hoy:%Y-%m-%d}", "pagina": {
            "nombre": "Otro", "data": self.alm.obtener_pagina(pid)["data"]}})
        self.assertEqual(r["archivo"], "Otro 2026-10-30.xlsx")
        r = self.api("POST", "plantilla", {"archivo": "pagina", "texto": "{Nada}", "pagina_id": pid})
        self.assertIn("no hay ningún filtro", r["error"])

    def test_propuesta_y_guardar_como_pagina(self):
        self.alm.guardar_ajustes(dict(self.alm.ajustes(), carpeta_descargas="C:\\Reportes"))
        p = self.api("POST", "mapa/propuesta", {"filtros": FILTROS_MAPA, "url": "http://127.0.0.1/reportes"})
        self.assertEqual((p["nombre_archivo"], p["carpeta_descargas"]), ("{pagina} - {variantes}", "C:\\Reportes"))
        comun = {"filtros": FILTROS_MAPA, "url": "http://127.0.0.1/reportes", "incluir": [0, 1],
                 "accion": {"tipo": "descargar", "generar_k": 2}}
        # sin tocar nada (o sin enviarlo, como antes): lo de siempre
        r = self.api("POST", "paginas", dict(comun, nombre="A"))
        d = self.alm.obtener_pagina(r["id"])["data"]
        self.assertEqual((d["nombre_archivo"], d["opciones"]["carpeta_descargas"]), ("{pagina} - {variantes}", "C:\\Reportes"))
        r = self.api("POST", "paginas", dict(comun, nombre="B", nombre_archivo=p["nombre_archivo"],
                                             carpeta_descargas=p["carpeta_descargas"]))
        d = self.alm.obtener_pagina(r["id"])["data"]
        self.assertEqual((d["nombre_archivo"], d["opciones"]["carpeta_descargas"]), ("{pagina} - {variantes}", "C:\\Reportes"))
        # con nombre y carpeta
        r = self.api("POST", "paginas", dict(comun, nombre="C", nombre_archivo="{pagina} {hoy:%Y-%m-%d}",
                                             carpeta_descargas="D:\\Portal"))
        d = self.alm.obtener_pagina(r["id"])["data"]
        self.assertEqual((d["nombre_archivo"], d["opciones"]["carpeta_descargas"]), ("{pagina} {hoy:%Y-%m-%d}", "D:\\Portal"))
        self.assertEqual(paginas.pasos_accion(d)[-1].nombre, "{pagina} {hoy:%Y-%m-%d}{ext}")
        with self.assertRaises(su.ErrorApi) as e:
            self.api("POST", "paginas", dict(comun, nombre="D", nombre_archivo="{Corte}"))
        self.assertIn("no hay ningún filtro «Corte»", str(e.exception))

    def test_crear_pasos_con_carpeta(self):
        eleccion = [{"k": 0, "estrategia": "fija", "valor": "Mayorista"},
                    {"k": 2, "modo": "descargar", "nombre": "Cortes {hoy:%Y}{ext}"}]
        datos = {"filtros": FILTROS_MAPA, "elecciones": eleccion, "destino": "nuevo", "nombre": "Mapeado",
                 "url": "http://127.0.0.1/reportes"}
        r = self.api("POST", "mapa/crear_pasos", datos)                         # sin carpeta: la de siempre
        fl = self.alm.cargar_flujo(r["id"])
        self.assertEqual(fl.opcion("carpeta_descargas"), "")
        self.assertEqual([p.nombre for p in fl.pasos if p.tipo == "descargar"], ["Cortes {hoy:%Y}{ext}"])
        r = self.api("POST", "mapa/crear_pasos", dict(datos, nombre="Mapeado 2", carpeta_descargas=" D:\\Cortes "))
        self.assertEqual(self.alm.cargar_flujo(r["id"]).opcion("carpeta_descargas"), "D:\\Cortes")
        # sobre un reporte existente: sin carpeta no cambia la suya; con carpeta, sí
        rid = self.alm.guardar(Flujo(nombre="Portal", url="http://127.0.0.1/reportes", opciones=dict(
            mod_flujo.OPCIONES_DEFECTO, carpeta_descargas="E:\\Portal"), pasos=[Paso("abrir_url", url="http://127.0.0.1/")]))
        self.api("POST", "mapa/crear_pasos", dict(datos, destino="anadir", reporte_id=rid, hasta=1))
        self.assertEqual(self.alm.cargar_flujo(rid).opcion("carpeta_descargas"), "E:\\Portal")
        self.api("POST", "mapa/crear_pasos", dict(datos, destino="reemplazar", reporte_id=rid, hasta=1,
                                                  carpeta_descargas="F:\\Nueva"))
        self.assertEqual(self.alm.cargar_flujo(rid).opcion("carpeta_descargas"), "F:\\Nueva")

    def test_la_interfaz_tiene_archivo_descargado_en_todas_partes(self):
        with open(os.path.join(RAIZ, "ui", "app.js"), encoding="utf-8") as f:
            js = f.read()
        for trozo in ("'data-archivo-descargado': '1'", "'data-archivo-descargado': 'pagina'",
                      "'data-archivo-descargado': 'mapa'",
                      "campoRuta(o.carpeta_descargas", "campoRuta(carpetaPag", "campoRuta(carpetaArch"):
            self.assertIn(trozo, js)
        self.assertEqual(js.count("campoRuta(carpetaArch"), 1)                  # «Así quedará» tras mapear


# ============================================================================ 2. interfaz
@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestInterfaz(Base):
    carpeta_forzada = False             # para ver en «Se guardará como» la carpeta del reporte / de la página

    def setUp(self):
        super().setUp()
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)
        self.defecto = os.path.abspath(os.path.join(RAIZ_BOT, "descargas"))     # (solo se enseña: no se escribe)

    def navegador(self):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self.addCleanup(self._p.stop)
        nav = self._p.chromium.launch(channel="chrome", headless=True)
        self.addCleanup(nav.close)
        pg = nav.new_page(viewport={"width": 1366, "height": 768})
        self.errores = []
        pg.on("console", lambda m: self.errores.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: self.errores.append(str(e)))
        return pg

    def esperar_texto(self, pg, selector, texto, timeout=10000):
        pg.wait_for_function("([s, t]) => { const e = document.querySelector(s); return !!e && e.textContent.includes(t); }",
                             arg=[selector, texto], timeout=timeout)

    def test_editor_una_descarga(self):
        rid = self.alm.guardar(Flujo(nombre=NOMBRE, url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"),
            Paso("descargar", selectores=["#d"], objetivo="Exportar", nombre=mod_flujo.NOMBRE_DESCARGA_DEFECTO)]))
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("editor/%d" % rid), wait_until="load")
        zona = "#contenido details[data-archivo-descargado='1']"
        campo = zona + " input[data-nombre-archivo='1']"
        pg.wait_for_selector(campo, timeout=15000)
        self.assertTrue(pg.locator(zona + " summary").is_visible())                    # a la vista (abierto)
        self.assertIn("Archivo descargado", pg.locator(zona + " summary").inner_text())
        self.assertEqual(pg.locator(zona + " label").first.inner_text(), "Nombre del archivo")
        self.assertEqual(pg.input_value(campo), "{reporte} {hoy:%Y-%m-%d}")            # sin la extensión
        vista = zona + " [data-vista-archivo]"
        self.esperar_texto(pg, vista, "Se guardará como: %s 2026-10-30.xlsx en %s" % (NOMBRE, self.defecto))
        # el nombre y la carpeta, con la vista previa al momento
        pg.fill(campo, "Ventas diarias {hoy:%d-%m-%Y}")
        self.esperar_texto(pg, vista, "Se guardará como: Ventas diarias 30-10-2026.xlsx")
        carpeta = os.path.join(self.tmp, "Reportes, S.A.S")
        pg.fill(zona + " input[aria-label='Carpeta']", carpeta)
        self.esperar_texto(pg, vista, " en " + carpeta)
        self.assertEqual(pg.locator(zona + " button[data-elegir='carpeta']").count(), 1)   # «📁 Elegir…»
        # es el mismo dato que «Guardar como» del paso
        pg.locator("#contenido tr[data-indice='1'] button:has-text('Editar')").click()
        pg.wait_for_selector(".modal input[data-nombre-descarga]")
        self.assertEqual(pg.input_value(".modal input[data-nombre-descarga]"), "Ventas diarias {hoy:%d-%m-%Y}{ext}")
        pg.fill(".modal input[data-nombre-descarga]", "Desde el paso {hoy:%Y}{ext}")
        pg.click(".modal .pie button:has-text('Aceptar')")
        pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
        pg.wait_for_function("s => document.querySelector(s).value === 'Desde el paso {hoy:%Y}'", arg=campo, timeout=10000)
        # atajos
        pg.click(zona + " button[data-nombre-rapido='reporte']")
        self.assertEqual(pg.input_value(campo), "{reporte} {hoy:%Y-%m-%d}")
        pg.fill(campo, "Ventas {hoy:%Y-%m-%d}")
        pg.click("#contenido .barra-herr button:has-text('Guardar')")
        pg.wait_for_function("() => /guardado/.test(document.querySelector('#subtitulo').textContent)", timeout=10000)
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual(fl.pasos[1].nombre, "Ventas {hoy:%Y-%m-%d}{ext}")
        self.assertEqual(fl.opcion("carpeta_descargas"), carpeta)
        self.assertEqual(self.errores, [])

    def test_editor_dos_descargas_y_sin_tocar_nada(self):
        fl = Flujo(nombre="ERP", url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"),
            Paso("descargar", selectores=["#a"], objetivo="Ventas", nombre="report_xls{ext}"),
            Paso("descargar", selectores=["#b"], objetivo="Cobros", nombre="", carpeta="Cobros"),
            Paso("guardar_pagina", formato="pdf", nombre="Resumen_{hoy:%Y-%m-%d}")])
        rid = self.alm.guardar(fl)
        antes = self.alm.cargar_flujo(rid).a_dict()
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("editor/%d" % rid), wait_until="load")
        zona = "#contenido details[data-archivo-descargado='1']"
        pg.wait_for_selector(zona + " input[data-nombre-archivo='3']", timeout=15000)
        # guardar SIN tocar nada deja el reporte igual
        pg.click("#contenido .barra-herr button:has-text('Guardar')")
        pg.wait_for_function("() => /guardado/.test(document.querySelector('#subtitulo').textContent)", timeout=10000)
        self.assertEqual(self.alm.cargar_flujo(rid).a_dict(), antes)
        etiquetas = pg.locator(zona + " [data-archivo-nombres] > label").all_inner_texts()
        self.assertEqual(etiquetas, ["Nombre del archivo del paso 2 («Ventas»)", "Nombre del archivo del paso 3 («Cobros»)",
                                     "Nombre del archivo del paso 4 (Guardar página)"])
        self.assertEqual([pg.input_value(zona + " input[data-nombre-archivo='%d']" % i) for i in (1, 2, 3)],
                         ["report_xls", "", "Resumen_{hoy:%Y-%m-%d}"])
        vistas = zona + " [data-vista-archivo]"
        pg.wait_for_function("s => [...document.querySelectorAll(s)].every((e) => e.textContent.startsWith('Se guardará'))",
                             arg=vistas, timeout=10000)
        textos = pg.locator(vistas).all_inner_texts()
        self.assertEqual(textos[0], "Se guardará como: report_xls.xlsx en " + self.defecto)
        self.assertEqual(textos[1], "Se guardará como: nombre_que_da_la_web.xlsx en " + os.path.join(self.defecto, "Cobros"))
        self.assertEqual(textos[2], "Se guardará como: Resumen_2026-10-30.pdf en " + self.defecto)
        # con varias descargas, «Nombre del reporte + fecha» añade el nombre de la web para que no se pisen
        pg.locator(zona + " button[data-nombre-rapido='reporte']").nth(1).click()
        self.assertEqual(pg.input_value(zona + " input[data-nombre-archivo='2']"), "{reporte} - {nombre} {hoy:%Y-%m-%d}")
        pg.click(zona + " button[data-nombre-rapido='web']")                       # el primero: «Nombre que da la web»
        self.assertEqual(pg.input_value(zona + " input[data-nombre-archivo='1']"), "{nombre}")
        self.assertEqual(self.errores, [])

    def test_editor_sin_descargas(self):
        rid = self.alm.guardar(Flujo(nombre="Solo mira", url="http://127.0.0.1/", pasos=[Paso("abrir_url", url="http://127.0.0.1/")]))
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("editor/%d" % rid), wait_until="load")
        pg.wait_for_selector("#contenido [data-archivo-descargado='1'] [data-sin-descargas]", timeout=15000)
        self.assertEqual(self.errores, [])

    def test_configurar_esta_pagina(self):
        pid, _ = paginas.guardar_nueva(self.alm, "Portal – Reportes", {
            "url": "http://127.0.0.1/", "llegada": [Paso("abrir_url", url="http://127.0.0.1/").a_dict()],
            "filtros": [{"id": "f1", "tipo": "lista", "nombre": "Corte", "selectores": ["#c"],
                         "defecto": {"estrategia": "fija", "valor": "45 - 2026"}}],
            "accion": {"tipo": "descargar", "generar": {"selectores": ["#e"], "objetivo": "Exportar"}}})
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("paginas/%d" % pid), wait_until="load")
        pg.wait_for_selector("#contenido details.config-pagina summary", timeout=15000)
        pg.click("#contenido details.config-pagina summary")
        zona = "#contenido [data-archivo-descargado='pagina']"
        pg.wait_for_selector(zona + " input[data-nombre-archivo='pagina']")
        self.assertEqual(pg.locator(zona + " > label").all_inner_texts(), ["Nombre del archivo", "Carpeta"])
        self.assertEqual(pg.input_value(zona + " input[data-nombre-archivo='pagina']"), "{pagina} - {variantes}")
        vista = zona + " [data-vista-archivo]"
        self.esperar_texto(pg, vista, "Se guardará como: Portal – Reportes - 45 - 2026.xlsx en " + self.defecto)
        # lo que no se ha guardado todavía también cuenta (otro nombre de filtro, sin marcar «en el nombre»)
        pg.fill(zona + " input[data-nombre-archivo='pagina']", "{pagina} {Corte} {hoy:%Y-%m-%d}")
        self.esperar_texto(pg, vista, "Se guardará como: Portal – Reportes 45 - 2026 2026-10-30.xlsx")
        carpeta = os.path.join(self.tmp, "Portal")
        pg.fill(zona + " input[aria-label='Carpeta de los archivos']", carpeta)
        self.esperar_texto(pg, vista, " en " + carpeta)
        pg.fill(zona + " input[data-nombre-archivo='pagina']", "{Nada}")
        self.esperar_texto(pg, vista, "⚠")
        pg.click(zona + " button[data-nombre-rapido='reporte']")                  # «Nombre de la página + lo elegido»
        self.assertEqual(pg.input_value(zona + " input[data-nombre-archivo='pagina']"), "{pagina} - {variantes}")
        pg.fill(zona + " input[data-nombre-archivo='pagina']", "{pagina} {hoy:%Y-%m-%d}")
        pg.click("#contenido button:has-text('Guardar configuración')")
        pg.wait_for_function("() => /Página guardada/.test(document.querySelector('#toasts').textContent)", timeout=10000)
        d = self.alm.obtener_pagina(pid)["data"]
        self.assertEqual((d["nombre_archivo"], d["opciones"]["carpeta_descargas"]), ("{pagina} {hoy:%Y-%m-%d}", carpeta))
        self.assertEqual(self.errores, [])

    # ---------------------------------------------------------------- al terminar de mapear (mapa simulado)
    def mapear(self, pg):
        def estado(route):
            r = route.fetch()
            d = r.json()
            d["mapeando"] = True                          # como si el navegador del mapeo estuviera abierto
            route.fulfill(response=r, json=d)
        pg.route("**/api/estado", estado)
        pg.route("**/api/mapa/mapear", lambda route: route.fulfill(json={
            "filtros": FILTROS_MAPA, "url": "http://127.0.0.1/reportes", "pestana": 0, "pestanas": [], "avisos": []}))
        pg.goto(self.srv.url_con_token("mapear"), wait_until="load")
        pg.click("#contenido button:has-text('Mapear toda la página')", timeout=15000)
        pg.wait_for_selector("#contenido [data-archivo-descargado='mapa']", timeout=15000)

    def test_mapear_y_crear_pasos(self):
        pg = self.navegador()
        self.mapear(pg)
        zona = "#contenido [data-archivo-descargado='mapa']"
        nombre = zona + " input[data-nombre-archivo='mapa']"
        self.assertEqual(pg.input_value(nombre), "{reporte} {hoy:%Y-%m-%d}")
        fila = "#contenido input[aria-label='Nombre del archivo']"                  # el del botón «Exportar»
        self.assertEqual(pg.input_value(fila), "{reporte} {hoy:%Y-%m-%d}{ext}")
        vista = zona + " [data-vista-archivo]"
        self.esperar_texto(pg, vista, "Se guardará como: Reporte mapeado 2026-10-30.xlsx en " + self.defecto)
        pg.fill(nombre, "Cortes {hoy:%Y}")
        self.assertEqual(pg.input_value(fila), "Cortes {hoy:%Y}{ext}")                # la fila sigue al nombre
        carpeta = os.path.join(self.tmp, "Cortes")
        pg.fill(zona + " input[aria-label='Carpeta del reporte']", carpeta)
        self.esperar_texto(pg, vista, "Se guardará como: Cortes 2026.xlsx en " + carpeta)
        pg.click("#contenido button[data-crear-pasos]")
        pg.wait_for_function("() => /#\\/editor\\/\\d+/.test(location.hash)", timeout=15000)
        rid = int(pg.evaluate("() => location.hash.split('/').pop()"))
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual([p.nombre for p in fl.pasos if p.tipo == "descargar"], ["Cortes {hoy:%Y}{ext}"])
        self.assertEqual(fl.opcion("carpeta_descargas"), carpeta)
        # y en el editor que se abre, en «Archivo descargado»
        campo = "#contenido [data-archivo-descargado='1'] input[data-nombre-archivo]"
        pg.wait_for_selector(campo, timeout=15000)
        self.assertEqual(pg.input_value(campo), "Cortes {hoy:%Y}")
        self.assertEqual(self.errores, [])


if __name__ == "__main__":
    unittest.main()
