"""Pruebas de la v3.5 (parte 2): diseño «Centro de control» y rapidez de la interfaz.

- El Inicio trae en UNA llamada las series de 7 días (chispas), los reportes como filas, la novedad de vigilancia y lo
  último del correo; `/api/buscador` (Ctrl K) no toca nada lento.
- La lista de tareas de Windows (schtasks /Query, ~1 s) se guarda en caché y se vacía al crear/borrar una tarea.
- Los eventos «trabajo» llevan el reporte; cada petición HTTP cierra su conexión de SQLite.
- En la página (navegador oculto): al terminar un trabajo NO se reconstruye la página (un elemento marcado, la misma fila
  y el desplazamiento siguen ahí; solo cambia la fila afectada), las secciones se quedan vivas al cambiar de sección y la
  paleta Ctrl K busca sin acentos y ejecuta.

Base de datos temporal, contraseñas en memoria, avisos falsos; nunca se ejecuta schtasks (lista y ejecutor falsos), no
se abre ningún diálogo ni se ejecuta ningún reporte de verdad (los eventos se emiten a mano).
"""

import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from webbot import avisos, programador, secretos  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

SEMANAL = {"reglas": [{"tipo": "semanal", "dias": ["lun", "mar", "mie", "jue", "vie"], "horas": ["08:00"]}]}


def flujo(nombre, url="https://portal.ejemplo.com/portal/#/reportes/corte"):
    return Flujo(nombre=nombre, url=url, pasos=[Paso("abrir_url", url=url),
                                                Paso("descargar", selectores=["#generar"], nombre="{reporte}{ext}")])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v35d_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        avisos.usar_notificador(lambda t, x: None)
        self.addCleanup(avisos.usar_notificador, None)
        # por si algo intentara ejecutar schtasks de verdad: falla
        original = programador._ejecutar
        programador._ejecutar = lambda cmd: (_ for _ in ()).throw(AssertionError("schtasks de verdad: %s" % cmd))
        self.addCleanup(setattr, programador, "_ejecutar", original)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.tareas = []
        self.lecturas = 0
        self.llamadas = []

        def listar():
            self.lecturas += 1
            return list(self.tareas)

        def ejecutar(cmd):
            self.llamadas.append(list(cmd))
            if "/Create" in cmd:
                self.tareas.append({"nombre": cmd[cmd.index("/TN") + 1].split("\\", 1)[1], "proxima": "30/10/2026 8:00:00",
                                    "estado": "Listo"})
            elif "/Delete" in cmd:
                n = cmd[cmd.index("/TN") + 1].split("\\", 1)[1]
                self.tareas[:] = [t for t in self.tareas if t["nombre"] != n]
            return 0, "CORRECTO"
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                                 carpeta_descargas=os.path.join(self.tmp, "d"), listar_tareas=listar, oculto_forzado=True,
                                 ejecutar_tareas=ejecutar, abrir_dialogo=lambda *a: None)
        self.addCleanup(self.app.detener)

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})


# ============================================================================ 1. el Inicio en una sola llamada
class TestInicio(Base):
    def test_series_de_7_dias_y_filas(self):
        hoy = datetime.date.today()
        ahora = datetime.datetime.now().replace(microsecond=0)
        a = self.alm.guardar(flujo("Cartera General"))
        b = self.alm.guardar(flujo("Facturación ERP", "https://erp.ejemplo.com/Consultas.aspx"))
        self.alm.guardar(flujo("Nuevo sin ejecutar"))
        for dias, rid, res in ((9, a, "ok"), (6, a, "error"), (3, b, "ok"), (1, a, "ok"), (0, a, "ok"), (0, a, "ok"),
                               (0, b, "error")):                       # (hace 9 días: fuera de la serie)
            cuando = (ahora - datetime.timedelta(days=dias)).replace(hour=7, minute=30) if dias else ahora
            self.alm.registrar_ejecucion(rid, res, "El campo LICENCIA esta vacio" if res == "error" else "",
                                         archivos=["Cartera %d.xlsx" % dias] if res == "ok" else [], cuando=cuando,
                                         duracion=72)
        d = self.api("GET", "inicio")
        s = d["serie"]
        self.assertEqual(len(s["dias"]), 7)
        self.assertEqual(s["dias"][-1], hoy.strftime("%Y-%m-%d"))
        self.assertEqual(s["dias"][0], (hoy - datetime.timedelta(days=6)).strftime("%Y-%m-%d"))
        self.assertEqual(s["descargas"], [0, 0, 0, 1, 0, 1, 2])
        self.assertEqual(s["errores"], [1, 0, 0, 0, 0, 0, 1])
        self.assertEqual(s["total"], [1, 0, 0, 1, 0, 1, 3])
        self.assertEqual(len(s["novedades"]), 7)
        self.assertEqual((d["kpi"]["descargas_hoy"], d["kpi"]["descargas_ayer"]), (2, 1))
        filas = {r["nombre"]: r for r in d["reportes"]}
        self.assertEqual(filas["Cartera General"]["estado"], "ok")
        self.assertEqual(filas["Cartera General"]["archivos"], ["Cartera 0.xlsx"])
        self.assertEqual(filas["Cartera General"]["duracion"], 72)
        self.assertEqual(filas["Cartera General"]["sitio"], "portal.ejemplo.com")
        self.assertEqual(filas["Facturación ERP"]["estado"], "error")
        self.assertIn("LICENCIA", filas["Facturación ERP"]["mensaje"])
        self.assertEqual(filas["Nuevo sin ejecutar"]["estado"], "nuevo")
        self.assertIsNone(d["vigilancia_novedad"])
        self.assertIsNone(d["correo_ultimo"])
        self.assertEqual((d["tareas_activas"], d["en_curso"]), (0, None))
        # la novedad de las chispas = avisos de vigilancia y de correo de cada día
        self.alm.crear_notificacion("vigilancia", "Corte nuevo", "45 - 2026")
        self.assertEqual(self.api("GET", "inicio")["serie"]["novedades"][-1], 1)

    def test_programado_novedad_y_correo(self):
        rid = self.alm.guardar(flujo("Portabilidad semanal"))
        self.api("POST", "reportes/%d/programar" % rid, {"programacion": SEMANAL, "confirmar": True})
        fila = [r for r in self.api("GET", "inicio")["reportes"] if r["id"] == rid][0]
        self.assertEqual((fila["estado"], fila["programado"], fila["proxima"]), ("programado", True, "30/10/2026 8:00:00"))
        self.assertEqual(fila["cuando_texto"], "de lunes a viernes a las 08:00")
        # una opción nueva de una vigilancia
        rid2 = self.alm.guardar(Flujo(nombre="Mayorista", url="http://x/", pasos=[
            Paso("abrir_url", url="http://x/"), Paso("elegir_opcion", selectores=["#c"], objetivo="Corte", estrategia="mas_reciente")]))
        vid = self.alm.crear_vigilancia(reporte_id=rid2, paso=1)
        self.alm.registrar_opciones_vigilancia(vid, ["43 - 2026", "44 - 2026"])
        self.alm.registrar_opciones_vigilancia(vid, ["43 - 2026", "44 - 2026", "45 - 2026"], detalle=True)
        n = self.api("GET", "inicio")["vigilancia_novedad"]
        self.assertEqual((n["vigilancia_id"], n["texto"], n["reporte_id"]), (vid, "45 - 2026", rid2))

    def test_buscador_para_ctrl_k(self):
        rid = self.alm.guardar(flujo("Cartera General"))
        self.alm.crear_vigilancia(reporte_id=self.alm.guardar(Flujo(nombre="Mayorista", url="http://x/", pasos=[
            Paso("abrir_url", url="http://x/"), Paso("elegir_opcion", selectores=["#c"], objetivo="Corte")])), paso=1)
        d = self.api("GET", "buscador")
        self.assertIn({"id": rid, "nombre": "Cartera General", "sitio": "portal.ejemplo.com"}, d["reportes"])
        self.assertEqual([v["objetivo"] for v in d["vigilancias"]], ["Mayorista"])
        self.assertEqual((d["paginas"], d["busquedas"]), ([], []))
        self.assertEqual(self.lecturas, 0)                  # sin tareas de Windows (nada lento)


# ============================================================================ 2. caché de las tareas de Windows
class TestCacheTareas(Base):
    def test_una_lectura_para_varias_paginas_y_se_vacia_al_crear(self):
        rid = self.alm.guardar(flujo("Cartera General"))
        self.api("GET", "inicio")
        self.api("GET", "vigilancia")
        self.api("GET", "correo")
        self.api("GET", "inicio")
        self.assertEqual(self.lecturas, 1)                  # antes: una lectura (~1 s) por cada página
        # crear la tarea (con el ejecutor de prueba) vacía la caché: la siguiente consulta ya la ve
        self.api("POST", "reportes/%d/programar" % rid, {"programacion": SEMANAL, "confirmar": True})
        self.assertEqual(len(self.llamadas), 1)
        antes = self.lecturas
        self.assertEqual(self.api("GET", "inicio")["tareas_activas"], 1)
        self.assertEqual(self.lecturas, antes + 1)
        self.assertTrue(self.api("GET", "reportes/%d/programar" % rid)["existe"])
        # quitarla también vacía la caché
        self.api("POST", "reportes/%d/quitar_tarea" % rid, {"confirmar": True})
        self.assertEqual(self.api("GET", "inicio")["tareas_activas"], 0)

    def test_caduca_y_en_segundo_plano_no_hace_esperar(self):
        self.api("GET", "inicio")
        self.assertEqual(self.lecturas, 1)
        ttl = su.TTL_TAREAS
        self.addCleanup(setattr, su, "TTL_TAREAS", ttl)
        su.TTL_TAREAS = 0                                    # caducada: se vuelve a leer
        self.api("GET", "inicio")
        self.assertEqual(self.lecturas, 2)
        # con la interfaz abierta (abrir_aplicacion): se devuelve la lista anterior al instante y se relee en otro hilo
        self.app.tareas_en_segundo_plano = True
        self.tareas.append({"nombre": "Nueva", "proxima": "", "estado": "Listo"})
        lenta = self.app.listar_tareas
        self.app.listar_tareas = lambda: (time.sleep(0.5), lenta())[1]
        t0 = time.monotonic()
        self.assertEqual(self.app._tareas(), [])            # la anterior
        self.assertLess(time.monotonic() - t0, 0.3)
        fin = time.monotonic() + 5
        while self.lecturas < 3 and time.monotonic() < fin:
            time.sleep(0.05)
        su.TTL_TAREAS = ttl
        time.sleep(0.1)
        self.assertEqual([t["nombre"] for t in self.app._tareas()], ["Nueva"])

    def test_fallo_al_leer_es_lista_vacia(self):
        self.app.listar_tareas = lambda: (_ for _ in ()).throw(OSError("sin schtasks"))
        self.assertEqual(self.app._tareas(), [])


# ============================================================================ 3. eventos y servidor
class TestServidor(Base):
    def test_el_evento_trabajo_lleva_el_reporte(self):
        t = self.app.lanzar("ejecutar", "Ejecutar «X»", lambda t: (True, "listo"), reporte_id=7, pagina_id=None)
        t.hilo.join(5)
        evs = [e for e in self.app.eventos.desde(0)[0] if e["tipo"] == "trabajo"]
        self.assertEqual([(e["estado"], e.get("reporte_id")) for e in evs], [("en_curso", 7), ("ok", 7)])
        self.assertNotIn("pagina_id", evs[0])
        self.assertEqual(t.a_dict()["reporte_id"], 7)

    def test_cada_peticion_cierra_su_conexion(self):
        srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(srv.parar)
        for _ in range(12):
            req = urllib.request.Request(srv.url + "api/estado", headers={"X-Bot-Token": self.app.token})
            with urllib.request.urlopen(req, timeout=30) as r:
                json.loads(r.read().decode("utf-8"))
        time.sleep(0.2)
        self.assertLessEqual(len(self.alm._conexiones), 2)   # antes: una conexión abierta (y perdida) por petición

    def test_fuentes_propias_sin_cdn(self):
        with open(os.path.join(RAIZ, "ui", "tema.css"), encoding="utf-8") as f:
            css = f.read()
        with open(os.path.join(RAIZ, "ui", "index.html"), encoding="utf-8") as f:
            html = f.read()
        for t in (css, html):
            self.assertNotIn("googleapis", t)
            self.assertNotIn("gstatic", t)
        for nombre in ("ibm-plex-mono-400.woff2", "ibm-plex-mono-500.woff2"):
            self.assertIn("fuentes/" + nombre, css)
            with open(os.path.join(RAIZ, "ui", "fuentes", nombre), "rb") as f:
                self.assertEqual(f.read(4), b"wOF2")


# ============================================================================ 4. la página (navegador oculto)
@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestPagina(Base):
    def setUp(self):
        super().setUp()
        self.ids = [self.alm.guardar(flujo("Reporte %02d" % i)) for i in range(1, 16)]
        self.ids.append(self.alm.guardar(flujo("Cartera General")))
        self.ids.append(self.alm.guardar(flujo("Ventas por canal, S.A.S.", "https://informes.ejemplo.com/x")))
        for rid in self.ids:
            self.alm.registrar_ejecucion(rid, "ok", archivos=["a.xlsx"], duracion=30)
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)

    def abrir(self, p, errores):
        nav = p.chromium.launch(channel="chrome", headless=True)
        pg = nav.new_page(viewport={"width": 1366, "height": 768})
        pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errores.append(str(e)))
        pg.goto(self.srv.url_con_token(), wait_until="load")
        pg.wait_for_selector("#contenido [data-pagina='inicio'] .fila-rep[data-reporte-id]")
        return nav, pg

    def test_no_se_reconstruye_al_terminar_un_trabajo(self):
        from playwright.sync_api import sync_playwright
        rid, otro = self.ids[-2], self.ids[0]
        fila = "#contenido .fila-rep[data-reporte-id='%d']" % rid
        errores = []
        with sync_playwright() as p:
            nav, pg = self.abrir(p, errores)
            try:
                pg.evaluate("""([rid, otro]) => {
                    const v = document.querySelector('#contenido [data-pagina="inicio"]');
                    window.__vista = v;
                    window.__otra = document.querySelector('.fila-rep[data-reporte-id="' + otro + '"]');
                    v.appendChild(Object.assign(document.createElement('div'), { id: 'marca-prueba' }));
                    document.querySelector('.feed').setAttribute('data-marca', '1');
                    window.scrollTo(0, 250);
                }""", [rid, otro])
                # empieza un trabajo de ese reporte: su fila pasa a «en curso» (sin recargar)
                self.app.eventos.emitir("trabajo", trabajo="t1", estado="en_curso", tipo_trabajo="ejecutar",
                                        descripcion="Ejecutar «Cartera General»", reporte_id=rid)
                pg.wait_for_selector(fila + "[data-estado='curso'] .barra")
                self.app.eventos.emitir("progreso", trabajo="t1", i=1, estado="inicio", texto="Descargar", total=2)
                pg.wait_for_function("s => /Paso 2 de 2/.test(document.querySelector(s + ' .det').textContent)", arg=fila)
                # termina (con la ejecución ya guardada, como hace el bot)
                self.alm.registrar_ejecucion(rid, "error", "El campo LICENCIA esta vacio (es un dato obligatorio)")
                self.app.eventos.emitir("trabajo", trabajo="t1", estado="error", tipo_trabajo="ejecutar",
                                        descripcion="Ejecutar «Cartera General»", reporte_id=rid,
                                        resumen="Cartera General: el campo LICENCIA está vacío")
                pg.wait_for_selector(fila + "[data-estado='error']")
                pg.wait_for_function("s => /LICENCIA esta vacio/.test(document.querySelector(s + ' .det').textContent)", arg=fila)
                pg.wait_for_selector(fila + " button:has-text('Completar Licencia')")
                pg.wait_for_function("() => /LICENCIA/.test(document.querySelector('.feed').textContent)")
                pg.wait_for_timeout(1200)                     # (por si algo recargara la página después)
                r = pg.evaluate("""otro => ({
                    misma: window.__vista === document.querySelector('#contenido [data-pagina="inicio"]'),
                    marca: !!document.getElementById('marca-prueba'),
                    feed: !!document.querySelector('.feed[data-marca]'),
                    otra: window.__otra === document.querySelector('.fila-rep[data-reporte-id="' + otro + '"]'),
                    scroll: window.scrollY })""", otro)
                self.assertEqual(r, {"misma": True, "marca": True, "feed": True, "otra": True, "scroll": 250})
                self.assertEqual(pg.locator("#contenido .kpi[data-kpi='error'] .num").inner_text().split()[0], "1")
                # al cambiar de sección y volver, la vista sigue viva (mismo nodo, mismo desplazamiento)
                pg.evaluate("() => { location.hash = '#/reportes'; }")
                pg.wait_for_selector("#contenido [data-pagina='reportes'] .fila-rep")
                pg.evaluate("() => { window.__rep = document.querySelector('#contenido [data-pagina=\"reportes\"]'); }")
                self.app.eventos.emitir("trabajo", trabajo="t2", estado="ok", tipo_trabajo="lote", descripcion="Lote",
                                        resumen="2 reportes bien")
                pg.wait_for_timeout(900)
                self.assertTrue(pg.evaluate("() => window.__rep === document.querySelector('#contenido [data-pagina=\"reportes\"]')"))
                pg.evaluate("() => { location.hash = '#/inicio'; }")
                pg.wait_for_function("() => window.__vista === document.querySelector('#contenido [data-pagina=\"inicio\"]')")
                self.assertEqual(pg.evaluate("() => [!!document.getElementById('marca-prueba'), window.scrollY]"), [True, 250])
            finally:
                nav.close()
        self.assertEqual(errores, [])

    def test_paleta_ctrl_k(self):
        from playwright.sync_api import sync_playwright
        errores = []
        with sync_playwright() as p:
            nav, pg = self.abrir(p, errores)
            try:
                pg.keyboard.press("Control+k")
                pg.wait_for_selector("#paleta-q")
                pg.wait_for_function("() => /Cartera/.test(document.querySelector('#paleta-lista').textContent)")
                pg.keyboard.type("carte")
                primero = pg.locator("#paleta-lista li").first
                self.assertEqual(primero.locator(".t").inner_text(), "Ejecutar «Cartera General»")
                self.assertEqual(primero.get_attribute("aria-selected"), "true")
                # sin acentos ni mayúsculas, y con letras salteadas
                pg.fill("#paleta-q", "MAPEAR PAGINA")
                self.assertEqual(pg.locator("#paleta-lista li").first.locator(".t").inner_text(), "Mapear una página")
                pg.fill("#paleta-q", "sas ventas")
                self.assertIn("Ventas por canal, S.A.S.", pg.locator("#paleta-lista li").first.inner_text())
                pg.fill("#paleta-q", "hstrl")
                self.assertEqual(pg.locator("#paleta-lista li").first.locator(".t").inner_text(), "Ir a Historial")
                pg.fill("#paleta-q", "zzzz qqq")
                pg.wait_for_selector("#paleta .vacio:not(.oculto)")
                # ↓ ↑ Enter: va a la sección
                pg.fill("#paleta-q", "ir a")
                pg.keyboard.press("ArrowDown")
                self.assertEqual(pg.locator("#paleta-lista li[aria-selected='true']").locator(".t").inner_text(), "Ir a Reportes")
                pg.keyboard.press("ArrowUp")
                pg.fill("#paleta-q", "historial")
                pg.keyboard.press("Enter")
                pg.wait_for_selector("#contenido [data-pagina='historial']")
                self.assertTrue(pg.locator("#paleta").evaluate("e => e.classList.contains('oculto')"))
                # Esc cierra; el botón «Buscar o ejecutar…» la abre
                pg.click("#btn-paleta")
                pg.wait_for_selector("#paleta-q")
                pg.keyboard.press("Escape")
                pg.wait_for_selector("#paleta.oculto", state="attached")
                # la búsqueda (función de la página) es la misma que usa la paleta
                orden = pg.evaluate("() => window.__botPaleta.buscar(window.__botPaleta.opciones(), 'vigilancia').map(o => o.texto)")
                self.assertIn("Ir a Vigilancia", orden[:3])
            finally:
                nav.close()
        self.assertEqual(errores, [])


if __name__ == "__main__":
    unittest.main()
