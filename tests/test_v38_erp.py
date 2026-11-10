"""Pruebas de la versión 3.8 «ERP»: lo que el mapeo detectaba mal en el ERP real (DevExpress dentro de un iframe).

Diagnóstico del 28/10/2026 («Registro de asistencia»): 29 filtros en vez de ~9.
- La fila de filtros de la rejilla (`…_DXFREditorcolN`) salía como 18 filtros «DXFR Editorcol0…» (las fechas, marcadas
  solas): ahora son secundarios, con el nombre de su columna.
- El buscador general de la web (documento principal) salía como filtro: ahora es secundario.
- Empleado / Ubicación salían partidos en «Cod» (texto) y «Descrip» (lista que no se abría): ahora UN filtro de texto
  con búsqueda, con su nombre.
- La lista del formato se llamaba «Espere…» (el panel de carga): ahora «Formato».
- La casilla «Ver bajas» (ASPxCheckBox, un <span>) no se veía: ahora sí, y el paso la marca con un clic.
Página de prueba `erp_devexpress.html` (+ `erp_devexpress_consulta.html` en el iframe).  Navegador oculto, base de datos
temporal, sin notificaciones ni tareas programadas.
"""

import os
import sys
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion_v33 import BaseMapeo  # noqa: E402
from webbot import mapeador  # noqa: E402

PRINCIPALES = {"Fecha Desde": "fecha", "Hasta": "fecha", "Empleado": "texto", "Ubicación": "texto", "Vista": "lista",
               "Formato": "lista", "Exportar": "accion", "Consultar": "accion", "Ver bajas": "casilla"}
COLUMNAS = ["Codigo", "Apellido", "Nombre", "Ubicación", "Fecha", "Hora"]


class TestReglaFueraDelReporte(unittest.TestCase):
    def test_solo_con_varios_documentos(self):
        uno = [{"tipo": "texto", "marco": [], "etiqueta": "Buscar"}, {"tipo": "lista", "marco": []}]
        mapeador._marcar_fuera_del_reporte(uno)
        self.assertFalse(any(f.get("secundario") for f in uno))
        varios = [{"tipo": "texto", "marco": [], "etiqueta": "Buscar"}] + \
                 [{"tipo": t, "marco": ["#tab0_Frame"]} for t in ("fecha", "fecha", "lista", "accion")]
        mapeador._marcar_fuera_del_reporte(varios)
        self.assertEqual(varios[0].get("grupo"), mapeador.GRUPO_FUERA)
        self.assertFalse(any(f.get("secundario") for f in varios[1:]))
        # un marco con una lista no es «el buscador de la web»
        otro = [{"tipo": "lista", "marco": []}] + [{"tipo": "fecha", "marco": ["#f"]} for _ in range(3)]
        mapeador._marcar_fuera_del_reporte(otro)
        self.assertFalse(otro[0].get("secundario"))


class TestMapeoErpDevExpress(BaseMapeo):
    def mapear(self):
        self.abrir("erp_devexpress.html")
        fin = time.monotonic() + 30
        m = {"filtros": []}
        while time.monotonic() < fin and "Ver bajas" not in self.por_etiqueta(m):
            time.sleep(0.5)
            m = self.api("POST", "mapa/mapear", {"alcance": "todo"})
        return m

    def test_mapa_como_el_erp_real(self):
        m = self.mapear()
        principales = [f for f in m["filtros"] if not f.get("secundario")]
        secundarios = [f for f in m["filtros"] if f.get("secundario")]
        self.assertEqual({f["etiqueta"]: f["tipo"] for f in principales}, PRINCIPALES,
                         [(f["etiqueta"], f["tipo"]) for f in m["filtros"]])
        self.assertTrue(all(f["marco"] == ["#tab0_Frame"] for f in principales))
        # Empleado: UN filtro de texto (el código) con su lupa; ni «Cod» ni «Descrip»
        por = {f["etiqueta"]: f for f in principales}
        self.assertEqual(por["Empleado"]["selectores"][0], "#wbeEmpleado_txtCod_I")
        self.assertTrue(por["Empleado"]["busqueda"]["selectores"])
        self.assertIn("txtDescrip_B0", " ".join(por["Empleado"]["busqueda"]["selectores"]))
        self.assertEqual(por["Formato"]["opciones"], ["XLSX", "PDF", "CSV"])
        self.assertFalse(por["Ver bajas"]["marcado"])
        # ids de ASP.NET antes que la ruta CSS
        self.assertTrue(por["Consultar"]["selectores"][0].startswith("#ctl00_formContent_wuc_1000_01_"), por["Consultar"]["selectores"])
        self.assertTrue(por["Formato"]["selectores"][0].startswith("#ctl00_formContent_wuc_1000_01_"), por["Formato"]["selectores"])
        # secundarios: las columnas de la rejilla (con su nombre) y el buscador de la web
        cols = [f for f in secundarios if f.get("grupo") == "Filtros de las columnas de la tabla"]
        self.assertEqual([f["etiqueta"] for f in sorted(cols, key=lambda f: f["x"])], COLUMNAS)
        fuera = [f for f in secundarios if f.get("grupo") == mapeador.GRUPO_FUERA]
        self.assertEqual([(f["etiqueta"], f["marco"]) for f in fuera], [("Buscar...", [])])
        self.assertEqual(len(secundarios), len(cols) + len(fuera))
        self.assertFalse(any("DXFR" in f["etiqueta"] or f["etiqueta"] in ("Cod", "Descrip", "Espere…") for f in m["filtros"]))
        # con secundarios se guarda el diagnóstico, con el HTML de cada filtro (sin valores de los campos)
        self.assertTrue(m.get("diagnostico") and os.path.isdir(m["diagnostico"]), m.get("diagnostico"))
        import json
        with open(os.path.join(m["diagnostico"], "diagnostico.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        html = {f["etiqueta"]: f.get("html", "") for f in d["filtros"]}
        self.assertIn("wbeEmpleado_txtCod_I", html["Empleado"])
        self.assertNotIn("value=", html["Fecha Desde"])
        self.assertNotIn("28/09/2026", html["Fecha Desde"])

    def test_los_pasos_escriben_el_codigo_y_marcan_la_casilla(self):
        m = self.mapear()
        por = {f["etiqueta"]: f for f in m["filtros"] if not f.get("secundario")}
        elecciones = [{"k": por["Fecha Desde"]["k"], "fecha": "plantilla", "valor": "01/10/2026"},
                      {"k": por["Hasta"]["k"], "fecha": "plantilla", "valor": "15/10/2026"},
                      {"k": por["Empleado"]["k"], "valor": "123"},
                      {"k": por["Ver bajas"]["k"], "marcado": True},
                      {"k": por["Consultar"]["k"], "modo": "clic"},
                      {"k": por["Exportar"]["k"], "modo": "descargar", "nombre": "Entradas{ext}"}]
        r = self.api("POST", "mapa/crear_pasos", {"filtros": m["filtros"], "elecciones": elecciones, "destino": "nuevo",
                                                    "nombre": "ERP entradas", "url": m["url"]})
        rid = r["id"]
        fl = self.alm.cargar_flujo(rid)
        fl.opciones.update(pausa_entre_pasos=0, timeout_paso=15)
        self.alm.guardar(fl, rid)
        tipos = {p.filtro or p.objetivo: p.tipo for p in fl.pasos}
        self.assertEqual(tipos["Empleado"], "escribir")              # NO «Elegir opción» (no es una lista)
        self.assertEqual(tipos["Ver bajas"], "marcar")
        self.terminar()
        t = self.api("POST", "ejecutar", {"ids": [rid]})
        lineas = []
        try:
            fin, _eventos = self.esperar_trabajo(t["id"], timeout=180,
                                                 al_evento=lambda ev: lineas.append(ev.get("texto") or ev.get("linea") or "") if ev["tipo"] == "log" else None)
        except AssertionError:
            self.fail("no terminó:\n" + "\n".join(str(x) for x in lineas[-40:]))
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(self.web.estado["descargas"][-1], "ERP 123||C 01/10/2026-15/10/2026")


class TestMapearUnaParteDentroDelMarco(unittest.TestCase):
    """«Mapear una parte…» en el ERP (07/11/2026): los filtros están dentro del iframe y el selector de la parte solo
    escuchaba el documento principal: no se resaltaba nada, el clic no hacía nada y el bot esperaba 5 minutos hasta
    que se cerraba el navegador.  Ahora escucha también en los iframes y el mapa de la parte mira solo ese marco."""

    @classmethod
    def setUpClass(cls):
        from servidor_prueba import ServidorPrueba
        from playwright.sync_api import sync_playwright
        cls.web = ServidorPrueba().iniciar()
        cls._p = sync_playwright().start()
        cls.nav = cls._p.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.nav.close()
        cls._p.stop()
        cls.web.parar()

    def setUp(self):
        self.pg = self.nav.new_page()
        self.addCleanup(self.pg.close)
        self.pg.goto(self.web.url_base + "erp_devexpress.html", wait_until="load")
        self.marco = self.pg.frame_locator("#tab0_Frame")
        self.marco.locator("#wbeEmpleado_txtCod_I").wait_for()
        self.doc = next(f for f in self.pg.frames if f.url.endswith("erp_devexpress_consulta.html"))

    def hacer_dentro_del_marco(self, js, ms=800):
        """Lo que hará el usuario dentro del iframe, un poco después (mientras `elegir_parte` espera)."""
        self.doc.evaluate("([js, ms]) => setTimeout(() => (new Function(js))(), ms)", [js, ms])

    def test_clic_dentro_del_iframe_elige_la_parte_y_se_mapea_solo_eso(self):
        self.hacer_dentro_del_marco("document.querySelector('table').dispatchEvent("
                                    "new MouseEvent('click', {bubbles: true, cancelable: true}))")
        t0 = time.monotonic()
        parte = mapeador.elegir_parte(self.pg, segundos=20)
        self.assertLess(time.monotonic() - t0, 10)                       # no espera al tiempo máximo
        self.assertIsNotNone(parte)
        self.assertEqual(parte["marco"], ["#tab0_Frame"])
        self.assertTrue(parte["selector"])
        # el resaltado y el letrero se quitaron en todos los documentos
        self.assertEqual(self.pg.evaluate("() => !!window.__botCancelarParte"), False)
        self.assertEqual(self.doc.evaluate("() => !!window.__botCancelarParte"), False)
        filtros = mapeador.escanear(None, self.pg, raiz=parte["selector"], leer_listas=False, marco_raiz=parte["marco"])
        etiquetas = {f["etiqueta"] for f in filtros}
        self.assertTrue({"Fecha Desde", "Hasta", "Empleado", "Ubicación"} <= etiquetas, etiquetas)
        self.assertNotIn("Buscar...", etiquetas)                         # el buscador de fuera del marco no entra
        self.assertTrue(all(f["marco"] == ["#tab0_Frame"] for f in filtros))

    def test_esc_dentro_del_iframe_cancela(self):
        self.hacer_dentro_del_marco("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        t0 = time.monotonic()
        self.assertIsNone(mapeador.elegir_parte(self.pg, segundos=20))
        self.assertLess(time.monotonic() - t0, 10)

    def test_sin_elegir_se_acaba_el_tiempo_y_se_limpia(self):
        self.assertIsNone(mapeador.elegir_parte(self.pg, segundos=1))
        self.assertEqual(self.doc.evaluate("() => !!window.__botCancelarParte"), False)
        # se puede volver a pedir y funciona
        self.hacer_dentro_del_marco("document.querySelector('table').dispatchEvent("
                                    "new MouseEvent('click', {bubbles: true, cancelable: true}))", ms=300)
        self.assertEqual((mapeador.elegir_parte(self.pg, segundos=10) or {}).get("marco"), ["#tab0_Frame"])


if __name__ == "__main__":
    unittest.main()
