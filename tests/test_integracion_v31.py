"""Pruebas de integración de la versión 3.1 (navegador oculto + página tipo Portal `portal.html`, cuyos campos llevan el
aria-label «Open» de Vuetify, con «Elegir corte» que depende de «Seleccione reporte»):

- Mapear la página da nombres de verdad («Filtro por sistema», «Seleccione reporte», «Elegir corte»), nunca «Open»,
  y los pasos generados guardan las opciones del mapa.
- Panel «Usar filtros» por la API: filtros con nombre, opciones de la más reciente a la más antigua, de dónde salen.
- «Descargar con estos filtros»: una vez con «43 …» (el reporte guardado no cambia), varias opciones = varias
  ejecuciones con nombres de archivo distintos, más de 10 = hay que confirmar.
- «Guardar como predeterminado» (con copia en Versiones), «Actualizar opciones» (corte nuevo, listas dependientes).
- La vigilancia actualiza las opciones del filtro y marca la novedad como «nueva».
- `--filtro` en la línea de comandos.
- La página: el panel se abre sin errores en la consola, con «La más reciente (hoy: 44 …)» y la Vigilancia muestra
  primero lo más reciente.
Base de datos temporal, contraseñas en memoria, sin notificaciones de Windows ni tareas programadas.
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from servidor_prueba import CORTE_NUEVO, ServidorPrueba, cortes_portal  # noqa: E402
from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from test_servidor_ui import BaseApi  # noqa: E402
from webbot import mapeador, plantillas, secretos  # noqa: E402
from webbot.ejecutor import Ejecutor  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

REPORTE = "Detalles Ventas Mayorista"
CORTES = cortes_portal(REPORTE)              # «33 - 2026 (…)» … «44 - 2026 (…)» (la página los da del más antiguo al más nuevo)
C44, C43, C42 = CORTES[-1], CORTES[-2], CORTES[-3]


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestUsarFiltros(BaseApi):
    @classmethod
    def setUpClass(cls):
        cls.web = ServidorPrueba().iniciar()
        cls.url = cls.web.url_base + "portal.html?ms=200"
        tmp = tempfile.mkdtemp(prefix="botweb_mapa31_")
        try:
            f = Flujo(nombre="Mapa", url=cls.url, pasos=[Paso("abrir_url", url=cls.url)])
            f.opciones.update(pausa_entre_pasos=0, timeout_paso=8)

            def al_final(ej, pg):
                filtros = mapeador.escanear(ej, pg)
                k = next(x["k"] for x in filtros if x["etiqueta"] == "Seleccione reporte")
                return mapeador.actualizar_opciones(ej, pg, filtros, k, REPORTE)
            res = Ejecutor(f, carpeta_perfil=os.path.join(tmp, "p"), carpeta_registros=tmp, oculto=True,
                           pausa_entre_pasos=0, al_final=al_final).ejecutar()
            cls.mapa = res.extra if res.ok else None
            cls.error_mapa = res.resumen()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def setUp(self):
        super().setUp()
        self.assertIsNotNone(self.mapa, self.error_mapa)
        self.web.estado.update(nuevo_corte=False)
        self.web.estado["descargas"].clear()
        self.addCleanup(self.web.estado.update, {"nuevo_corte": False})

    # ------------------------------------------------------------ utilidades
    def crear_reporte(self, nombre_archivo="Reporte{ext}"):
        por = {f["etiqueta"]: f for f in self.mapa}
        elecciones = [{"k": por["Seleccione reporte"]["k"], "estrategia": "fija", "valor": REPORTE},
                      {"k": por["Elegir corte"]["k"], "estrategia": "mas_reciente"},
                      {"k": por["Formato a Exportar"]["k"], "estrategia": "fija", "valor": "CSV"},
                      {"k": por["Generar"]["k"], "modo": "descargar", "nombre": nombre_archivo}]
        r = self.api("POST", "mapa/crear_pasos", {"filtros": self.mapa, "elecciones": elecciones, "destino": "nuevo",
                                                    "nombre": "Portal filtros", "url": self.url})
        rid = r["id"]
        self.api("POST", "mapa/guardar", {"reporte_id": rid, "url": self.url, "alcance": "todo", "filtros": self.mapa})
        fl = self.alm.cargar_flujo(rid)
        fl.opciones.update(pausa_entre_pasos=0, timeout_paso=10)
        self.alm.guardar(fl, rid)
        self.assertEqual([p.tipo for p in fl.pasos], ["abrir_url", "elegir_opcion", "elegir_opcion", "elegir_opcion",
                                                      "descargar"])
        return rid

    def panel(self, rid, elecciones=None):
        if elecciones is None:
            d = self.api("GET", "reportes/%d/filtros" % rid)
        else:
            d = self.api("POST", "reportes/%d/filtros" % rid, {"elecciones": elecciones})
        return {f["nombre"]: f for f in d["filtros"]}

    def lanzar(self, ruta, datos):
        """Lanza un trabajo y espera a que termine.  Devuelve (evento final, eventos de ESE trabajo)."""
        desde = self.app.eventos.ultimo
        t = self.api("POST", ruta, datos)
        fin, eventos = self.esperar_trabajo(t["id"], timeout=180)
        return fin, [e for e in eventos if e["seq"] > desde]

    def contenido(self, ruta):
        with open(ruta, encoding="utf-8") as fh:
            return fh.read()

    # ------------------------------------------------------------ pruebas
    def test_mapa_nombres_y_panel(self):
        etiquetas = [f["etiqueta"] for f in self.mapa]
        self.assertNotIn("Open", etiquetas)                    # los campos llevan aria-label="Open" (como Vuetify)
        for e in ("Filtro por sistema", "Seleccione reporte", "Elegir corte", "Formato a Exportar"):
            self.assertIn(e, etiquetas)
        rid = self.crear_reporte()
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual([p.filtro for p in fl.pasos[1:4]], ["Seleccione reporte", "Elegir corte", "Formato a Exportar"])
        por = self.panel(rid)
        self.assertEqual(sorted(por), ["Elegir corte", "Formato a Exportar", "Seleccione reporte"])
        corte = por["Elegir corte"]
        self.assertEqual([o["texto"] for o in corte["opciones"]], list(reversed(CORTES)))   # de la más reciente
        self.assertTrue(corte["opciones"][0]["mas_reciente"])
        self.assertEqual((corte["estrategia"], corte["actual"], corte["fuente"]), ("mas_reciente", C44, "mapa"))
        self.assertEqual(corte["opciones"][0]["detalle"], "año 2026 · del 09/10/2026 al 15/10/2026")
        self.assertEqual(corte["nota"], "")
        self.assertEqual([o["texto"] for o in por["Seleccione reporte"]["opciones"]], [REPORTE, "Resumen de Ventas"])
        self.assertEqual(por["Formato a Exportar"]["actual"], "CSV")
        self.assertEqual(self.alm.opciones_filtro(rid, 2)[0]["padres"], {1: REPORTE})

    def test_descargar_una_vez_varias_y_confirmar(self):
        rid = self.crear_reporte()
        guardado = self.alm.cargar_flujo(rid).a_dict()
        fin, eventos = self.lanzar("reportes/%d/filtros/descargar" % rid, {"elecciones": {"2": {"valores": [C43]}}})
        self.assertEqual(fin["estado"], "ok", fin)
        resultado = [e for e in eventos if e["tipo"] == "resultado"][-1]
        self.assertEqual(len(resultado["archivos"]), 1)
        self.assertEqual(os.path.basename(resultado["archivos"][0]), "Reporte.csv")      # una sola: sin sufijo
        self.assertIn(C43, self.contenido(resultado["archivos"][0]))
        self.assertEqual(self.web.estado["descargas"], [C43])
        self.assertEqual(self.alm.cargar_flujo(rid).a_dict(), guardado)               # el reporte no cambia
        log = self.contenido(resultado["registro"])
        self.assertIn("Filtros elegidos para esta ejecución (el reporte guardado no cambia): paso 3 «Elegir corte» "
                      "= «%s»" % C43, log)
        self.assertEqual(self.alm.historial(rid)[0]["resultado"], "ok")
        cache = self.alm.opciones_filtro(rid, 2)[0]                                   # la ejecución guardó la lista
        self.assertEqual((cache["fuente"], cache["opciones"], cache["padres"]), ("ejecucion", CORTES, {1: REPORTE}))
        # varias opciones: dos ejecuciones con nombres distintos
        fin, eventos = self.lanzar("reportes/%d/filtros/descargar" % rid, {"elecciones": {"2": {"valores": [C42, C43]}}})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertIn("2 de 2 bien", fin["resumen"])
        archivos = sorted(os.path.basename(a) for e in eventos if e["tipo"] == "resultado" for a in e["archivos"])
        self.assertEqual(archivos, ["Reporte - %s.csv" % C42.replace("/", "_"), "Reporte - %s.csv" % C43.replace("/", "_")])
        self.assertEqual(self.web.estado["descargas"], [C43, C42, C43])
        self.assertEqual([e["n"] for e in eventos if e["tipo"] == "lote"], [1, 2])
        # más de 10 ejecuciones: hay que confirmarlo (no se lanza nada)
        r = self.api("POST", "reportes/%d/filtros/descargar" % rid, {"elecciones": {"2": {"valores": CORTES[:11]}}})
        self.assertEqual((r["confirmar"], r["n"]), (True, 11))
        self.assertNotEqual((self.app.trabajo.estado if self.app.trabajo else ""), "en_curso")
        self.assertEqual(self.alm.cargar_flujo(rid).a_dict(), guardado)

    def test_predeterminado_actualizar_y_dependientes(self):
        rid = self.crear_reporte()
        antes = len(self.alm.versiones(rid))
        r = self.api("POST", "reportes/%d/filtros/predeterminado" % rid, {"elecciones": {"2": {"valores": [C43]}}})
        self.assertEqual(len(r["cambios"]), 1)
        self.assertEqual(len(self.alm.versiones(rid)), antes + 1)
        self.assertEqual(self.alm.versiones(rid)[0]["motivo"], "antes de «Guardar como predeterminado» en «Usar filtros»")
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual((fl.pasos[2].estrategia, fl.pasos[2].valor), ("fija", plantillas.escapar(C43)))
        self.assertEqual(self.panel(rid)["Elegir corte"]["actual"], C43)
        # renombrar un filtro
        self.api("POST", "reportes/%d/filtros/nombre" % rid, {"paso": 3, "nombre": "Formato"})
        self.assertEqual(self.alm.cargar_flujo(rid).pasos[3].filtro, "Formato")
        codigo, err = self.llamar("POST", "api/reportes/%d/filtros/nombre" % rid, {"paso": 3, "nombre": "Open"})
        self.assertEqual(codigo, 400, err)
        # «Actualizar opciones»: llegó el corte 45 → la lista guardada lo trae (y no se descarga nada)
        self.web.estado["nuevo_corte"] = True
        fin, _ev = self.lanzar("reportes/%d/filtros/actualizar" % rid, {"elecciones": {}})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual(self.web.estado["descargas"], [])
        cache = self.alm.opciones_filtro(rid, 2)[0]
        self.assertEqual((cache["fuente"], cache["opciones"][-1]), ("actualizar", CORTE_NUEVO))
        corte = self.panel(rid)["Elegir corte"]
        self.assertEqual((corte["opciones"][0]["texto"], corte["mas_reciente"]), (CORTE_NUEVO, CORTE_NUEVO))
        # lista dependiente: con otro «reporte» no hay lista guardada → la última conocida y una nota
        corte = self.panel(rid, {"1": {"valores": ["Resumen de Ventas"]}})["Elegir corte"]
        self.assertFalse(corte["exacta"])
        self.assertIn("otra combinación", corte["nota"])                   # solo se conoce una combinación
        self.assertIn("Actualizar opciones", corte["nota"])
        self.assertIn(CORTE_NUEVO, [o["texto"] for o in corte["opciones"]])
        fin, _ev = self.lanzar("reportes/%d/filtros/actualizar" % rid, {"elecciones": {"1": {"valores": ["Resumen de Ventas"]}}})
        self.assertEqual(fin["estado"], "ok", fin)                       # el «43 …» no está: se elige otro para leer
        corte = self.panel(rid, {"1": {"valores": ["Resumen de Ventas"]}})["Elegir corte"]
        self.assertEqual(corte["nota"], "")
        self.assertEqual([o["texto"] for o in corte["opciones"] if not o["guardada"]],
                         ["Octubre 2026", "Septiembre 2026", "Agosto 2026"])
        self.assertEqual(self.panel(rid)["Elegir corte"]["opciones"][0]["texto"], CORTE_NUEVO)   # la otra sigue
        # ya se conocen dos listas distintas: con un reporte sin lista guardada, el aviso fuerte
        self.alm.guardar_opciones_filtro(rid, 1, [REPORTE, "Resumen de Ventas", "Otro reporte"], {}, "", "actualizar")
        corte = self.panel(rid, {"1": {"valores": ["Otro reporte"]}})["Elegir corte"]
        self.assertIn("No hay opciones guardadas para esta combinación", corte["nota"])

    def test_vigilancia_actualiza_las_opciones_y_marca_nueva(self):
        rid = self.crear_reporte()
        self.api("PUT", "vigilancia/%d" % rid, {"paso": 2, "auto_descargar": False})
        fin, _ev = self.lanzar("vigilancia/%d/revisar" % rid, {})
        self.assertEqual(fin["estado"], "ok", fin)
        self.web.estado["nuevo_corte"] = True
        fin, eventos = self.lanzar("vigilancia/%d/revisar" % rid, {})
        self.assertEqual(fin["estado"], "ok", fin)
        self.assertEqual([e["nuevas"] for e in eventos if e["tipo"] == "vigilancia"], [[CORTE_NUEVO]])
        corte = self.panel(rid)["Elegir corte"]
        self.assertEqual(corte["fuente"], "vigilancia")
        self.assertTrue(corte["vigilado"])
        primera = corte["opciones"][0]
        self.assertEqual((primera["texto"], primera["nueva"], primera["mas_reciente"]), (CORTE_NUEVO, True, True))
        self.assertFalse(any(o["nueva"] for o in corte["opciones"][1:]))
        self.assertEqual(self.alm.notificaciones()[0]["titulo"], "Llegó un corte nuevo en «Portal filtros»: " + CORTE_NUEVO)

    def test_linea_de_comandos_filtro(self):
        import bot
        rid = self.crear_reporte()
        # (v3.5: base de datos ya convertida: «Reporte{ext}» es un nombre elegido y la conversión de una vez no lo toca)
        self.alm.poner_meta(self.alm.META_NOMBRES_V35, "1")
        guardado = self.alm.cargar_flujo(rid).a_dict()
        args = ["--db", self.alm.ruta, "--id", str(rid), "--sin-ventana", "--oculto",
                "--perfil", os.path.join(self.tmp, "perfil_cli"), "--registros", os.path.join(self.tmp, "registros"),
                "--descargas", os.path.join(self.tmp, "descargas_cli"), "--carpeta-flujos", os.path.join(self.tmp, "fl")]
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = bot.principal(args + ["--filtro", "Elegir corte=" + C42])
        self.assertEqual(codigo, 0, salida.getvalue())
        self.assertIn("Filtros elegidos para esta ejecución", salida.getvalue())
        self.assertEqual(self.web.estado["descargas"], [C42])
        self.assertEqual(os.listdir(os.path.join(self.tmp, "descargas_cli")), ["Reporte.csv"])
        self.assertEqual(self.alm.cargar_flujo(rid).a_dict(), guardado)
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = bot.principal(args + ["--filtro", "No existe=1"])
        self.assertEqual(codigo, 2)
        self.assertIn("No hay ningún filtro «No existe»", salida.getvalue())

    def test_pagina_panel_de_filtros_y_orden_de_vigilancia(self):
        from playwright.sync_api import sync_playwright
        rid = self.crear_reporte()
        self.alm.guardar_vigilancia(rid, 2)
        self.alm.registrar_opciones(rid, 2, CORTES)                    # orden de la página: del 33 al 44
        errores = []
        with sync_playwright() as p:
            nav = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = nav.new_page()
                pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errores.append(str(e)))
                pg.goto(self.srv.url_con_token("reportes"), wait_until="load")
                pg.wait_for_selector("#contenido [data-pagina='reportes']")
                pg.click("#contenido button:has-text('Usar filtros')")
                pg.wait_for_selector(".modal [data-filtros] .filtro")
                self.assertEqual(pg.locator(".modal .filtro").count(), 3)
                texto = pg.inner_text(".modal")
                self.assertNotIn("Open", texto)
                for n in ("Seleccione reporte", "Elegir corte", "Formato a Exportar"):
                    self.assertIn(n, texto)
                sel = pg.locator(".modal .filtro[data-paso='2'] select").first
                self.assertEqual(sel.locator("option").first.inner_text(), "La más reciente (hoy: %s)" % C44)
                self.assertEqual(sel.input_value(), "__mas_reciente")
                self.assertIn("más reciente", pg.inner_text(".modal .filtro[data-paso='2']"))
                # elegir otra opción y varias
                sel.select_option(C43)
                pg.click(".modal .filtro[data-paso='2'] label:has-text('Elegir varias')")
                pg.wait_for_selector(".modal .filtro[data-paso='2'] .opciones-multi:not(.oculto)")
                pg.click(".modal .pie button:has-text('Cerrar')")
                pg.wait_for_selector("#modal-fondo.oculto", state="attached")
                # Vigilancia: lo más reciente primero, con «más reciente»
                pg.evaluate("() => { location.hash = '#/vigilancia'; }")
                pg.wait_for_selector("#contenido [data-pagina='vigilancia'] ul.lista li")
                primera = pg.locator("#contenido ul.lista li").first.inner_text()
                self.assertIn(C44, primera)
                self.assertIn("más reciente", primera)
                self.assertIn(CORTES[0], pg.locator("#contenido ul.lista li").last.inner_text())
            finally:
                nav.close()
        self.assertEqual(errores, [])


if __name__ == "__main__":
    unittest.main()
