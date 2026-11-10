"""Pruebas de integración de la versión 3.4 «Correo», con navegador OCULTO y buzones FALSOS del sitio de prueba.

- `correo_outlook.html` (imita Outlook en la web: buscador que reacciona al teclado, filas [data-convid] con el asunto
  recortado en pantalla y completo en el aria-label, fecha «Thu 10/29/2026 9:07 AM» en un title, panel de lectura,
  tarjetas de adjuntos con «Más acciones» → «Descargar» y «Descargar todo»).
- `correo_gmail.html` (imita Gmail: búsqueda por la dirección #search/<operadores>, filas tr.zA, correo abierto con
  h2.hP / span.gD / div.a3s y adjuntos span.aZo).
Por la API, como lo usa el usuario: crear la cuenta y la búsqueda, «Revisar ahora» (todos los correos que coinciden, una
sola vez; un correo que llega después), «Descargar todo» cuando el menú no tiene «Descargar», un .zip descomprimido,
«Probar búsqueda», la sesión caducada (aviso claro) y «Iniciar sesión en el correo» (el «usuario» entra solo en la
página de prueba con ?auto_login), y la página Correo en el navegador sin errores en la consola.

NO prueban el Outlook ni el Gmail reales (no hay acceso desde aquí): solo que el bot funciona con páginas con su misma
estructura.  Base de datos temporal, contraseñas en memoria, sin notificaciones de Windows ni tareas programadas.
"""

import datetime
import os
import sys
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from servidor_prueba import ServidorPrueba  # noqa: E402
from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from test_servidor_ui import BaseApi  # noqa: E402
from webbot import correo_web  # noqa: E402

ADJ = "SUPERVISION VENTAS EJEMPLO V1.4.xlsx"


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class BaseCorreo(BaseApi):
    @classmethod
    def setUpClass(cls):
        cls.web = ServidorPrueba().iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def setUp(self):
        super().setUp()
        self.web.estado.update(correo_login=False, correos_extra=[], correo_descargas=[], correo_busquedas=[])
        self.hoy = datetime.date.today()
        self.base = os.path.join(self.tmp, "descargas")
        for k, v in (("CONFIRMAR_LOGIN", 4), ("ESPERA_BANDEJA_S", 30)):     # (que la sesión caducada se vea antes)
            p = mock.patch.object(correo_web, k, v)
            p.start()
            self.addCleanup(p.stop)

    def cuenta(self, proveedor="outlook_web", pagina="correo_outlook.html", nombre="Empresa"):
        return self.api("POST", "correo/cuentas", {"nombre": nombre, "proveedor": proveedor,
                                                   "url": self.web.url_base + pagina})["cuenta"]

    def busqueda(self, cid, nombre="Ventas", **k):
        datos = {"nombre": nombre, "cuenta_id": cid,
                 "criterios": {"asunto": "RESUMEN DE VENTAS EMPRESA", "remitente": "reportes@ejemplo.com",
                               "fecha": "ultimos", "dias": 7, "adjunto": "supervision ventas"},
                 "acciones": [{"tipo": "adjuntos", "coincide": "supervision ventas",
                               "nombre": "Ventas {fecha_correo:%Y-%m-%d}.xlsx", "carpeta": "migracion"},
                              {"tipo": "texto", "etiqueta": "Total ventas:"}]}
        datos.update(k)
        return self.api("POST", "correo/busquedas", datos)["busqueda"]

    def lanzar(self, ruta, datos=None, timeout=180):
        desde = self.app.eventos.ultimo
        t = self.api("POST", ruta, datos or {})
        fin, eventos = self.esperar_trabajo(t["id"], timeout=timeout)
        return fin, [e for e in eventos if e["seq"] > desde]

    def archivo(self, *partes):
        return os.path.join(self.base, *partes)


class TestOutlook(BaseCorreo):
    def test_revisar_procesa_todos_una_sola_vez(self):
        c = self.cuenta()
        b = self.busqueda(c["id"])
        fin, evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        hoy, ayer = self.hoy, self.hoy - datetime.timedelta(days=1)
        for d, contenido in ((hoy, b"xlsx-de-hoy"), (ayer, b"xlsx-de-ayer")):
            with open(self.archivo("migracion", "Ventas %s.xlsx" % d.strftime("%Y-%m-%d")), "rb") as f:
                self.assertEqual(f.read(), contenido)
        ev = [e for e in evs if e["tipo"] == "correo"][0]
        self.assertEqual(ev["procesados"], 2)
        titulos = [n["titulo"] for n in self.alm.notificaciones()]
        self.assertTrue(any(t.startswith("Llegó «RESUMEN DE VENTAS EMPRESA EJEMPLO, S.A.S. AL %s»: 1 archivo guardado, "
                                         "Total ventas: 1.234" % hoy.strftime("%d/%m/%Y")) for t in titulos), titulos)
        self.assertEqual(self.web.estado["correo_busquedas"][-1], "RESUMEN DE VENTAS EMPRESA")   # lo que se tecleó
        self.assertEqual(sorted(self.web.estado["correo_descargas"]), [ADJ, ADJ])
        self.assertEqual(self.alm.cuenta_correo(c["id"])["estado_sesion"], "ok")
        h = self.api("GET", "correo/busquedas/%d" % b["id"])
        self.assertEqual(len(h["busqueda"]["procesados"]), 2)
        self.assertEqual(h["historial"][0]["resultado"], "ok")
        self.assertEqual(sorted(p["valores"][0][1] for p in h["busqueda"]["procesados"]), ["1.234", "987"])
        # otra vez, sin nada nuevo: «Revisar ahora» (v3.6.1) rehace el MÁS RECIENTE
        fin, evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual([e["procesados"] for e in evs if e["tipo"] == "correo"], [1], fin.get("resumen"))
        self.assertEqual(len(self.web.estado["correo_descargas"]), 3)
        with open(self.archivo("migracion", "Ventas %s (2).xlsx" % hoy.strftime("%Y-%m-%d")), "rb") as f:
            self.assertEqual(f.read(), b"xlsx-de-hoy")
        # llega uno nuevo: solo se procesa ese
        self.web.estado["correos_extra"].append({
            "id": "m6", "de_nombre": "Reportes Ventas", "de_correo": "reportes@ejemplo.com",
            "asunto": "RESUMEN DE VENTAS EMPRESA EJEMPLO, S.A.S. AL CIERRE",
            "fecha": datetime.datetime.combine(hoy, datetime.time(9, 45)),
            "html": "<p>Total ventas: 2.000</p>", "adjuntos": [(ADJ, b"nuevo")]})
        fin, evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        self.assertEqual([e["procesados"] for e in evs if e["tipo"] == "correo"], [1])
        with open(self.archivo("migracion", "Ventas %s (3).xlsx" % hoy.strftime("%Y-%m-%d")), "rb") as f:
            self.assertEqual(f.read(), b"nuevo")

    def test_descargar_todo_y_zip(self):
        c = self.api("POST", "correo/cuentas", {"nombre": "Sin menú", "url": self.web.url_base +
                                                "correo_outlook.html?sin_menu=1"})["cuenta"]
        b = self.busqueda(c["id"], criterios={"asunto": "RESUMEN DE VENTAS EMPRESA", "fecha": "hoy"},
                          acciones=[{"tipo": "adjuntos", "carpeta": "todo"},
                                    {"tipo": "tabla", "n": 1, "archivo": "tablas.csv"},
                                    {"tipo": "cuerpo", "formato": "txt", "carpeta": "cuerpos"}])
        fin, _ = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        self.assertEqual(sorted(os.listdir(self.archivo("todo"))), sorted([ADJ, "Otro reporte.csv"]))
        with open(self.archivo("tablas.csv"), encoding="utf-8-sig") as f:      # la tabla de dentro (no la que envuelve)
            self.assertEqual(f.read().splitlines(), ["Producto;Cantidad;Importe", "Plan Básico;12;1200.5", "Plan Plus;3;34"])
        cuerpos = os.listdir(self.archivo("cuerpos"))
        with open(self.archivo("cuerpos", cuerpos[0]), encoding="utf-8") as f:
            self.assertIn("Total ventas: 1.234", f.read())
        self.assertIn("(todo) m1", self.web.estado["correo_descargas"])
        # el .zip de hace 10 días, descomprimido (solo lo que coincide)
        c2 = self.cuenta(nombre="Normal")
        b2 = self.busqueda(c2["id"], nombre="Zip", criterios={"asunto": "RESUMEN", "fecha": "ultimos", "dias": 30,
                                                              "extension": "zip"},
                           acciones=[{"tipo": "adjuntos", "coincide": "supervision", "descomprimir": True,
                                      "carpeta": "zip", "nombre": "{adjunto} - {fecha_correo:%d-%m-%Y}"}])
        fin, _ = self.lanzar("correo/busquedas/%d/revisar" % b2["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        d = (self.hoy - datetime.timedelta(days=10)).strftime("%d-%m-%Y")
        self.assertEqual(os.listdir(self.archivo("zip")), ["SUPERVISION VENTAS EJEMPLO V1.4 - %s.xlsx" % d])

    def test_sesion_caducada_e_iniciar_sesion(self):
        self.web.estado["correo_login"] = True
        c = self.cuenta()
        b = self.busqueda(c["id"])
        fin, evs = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertEqual(fin["estado"], "error")
        ev = [e for e in evs if e["tipo"] == "correo"][0]
        self.assertTrue(ev["sesion_caducada"])
        self.assertIn("Iniciar sesión en el correo", ev["resumen"])
        self.assertEqual(self.alm.cuenta_correo(c["id"])["estado_sesion"], "caducada")
        avisos = [n for n in self.alm.notificaciones() if n["tipo"] == "correo_sesion"]
        self.assertEqual(len(avisos), 1)
        # «Iniciar sesión en el correo»: el usuario entra él (aquí la página de prueba «entra» sola a los 2,5 s)
        self.api("PUT", "correo/cuentas/%d" % c["id"], {"url": self.web.url_base + "correo_outlook.html?auto_login=2500"})
        fin, evs = self.lanzar("correo/cuentas/%d/sesion" % c["id"])
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        self.assertTrue([e for e in evs if e["tipo"] == "correo_sesion" and e["ok"]])
        self.assertEqual(self.alm.cuenta_correo(c["id"])["estado_sesion"], "ok")
        self.assertTrue(self.alm.notificacion(avisos[0]["id"])["leida"])
        fin, _ = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertIn("2 correo(s) procesado(s)", fin["resumen"])


class TestGmail(BaseCorreo):
    def test_probar_y_revisar(self):
        c = self.cuenta("gmail_web", "correo_gmail.html", "Gmail")
        b = self.busqueda(c["id"])
        fin, evs = self.lanzar("correo/probar", {"busqueda_id": b["id"]})
        self.assertEqual(fin["estado"], "ok", fin.get("resumen"))
        ev = [e for e in evs if e["tipo"] == "correo_prueba"][0]
        hoy = self.hoy.strftime("%d/%m/%Y")
        self.assertEqual([(m["asunto"][-10:], m["coincide"], m["procesado"]) for m in ev["mensajes"]],
                         [(hoy, True, ""), ((self.hoy - datetime.timedelta(days=1)).strftime("%d/%m/%Y"), True, "")])
        self.assertEqual(ev["mensajes"][0]["adjuntos"], [ADJ, "Otro reporte.csv"])
        self.assertEqual(self.web.estado["correo_descargas"], [])        # probar no descarga nada
        busq = self.web.estado["correo_busquedas"][-1]
        self.assertIn("subject:(RESUMEN DE VENTAS EMPRESA)", busq)
        self.assertIn("from:reportes@ejemplo.com", busq)
        fin, _ = self.lanzar("correo/busquedas/%d/revisar" % b["id"])
        self.assertIn("2 correo(s) procesado(s)", fin["resumen"])
        self.assertTrue(os.path.isfile(self.archivo("migracion", "Ventas %s.xlsx" % self.hoy.strftime("%Y-%m-%d"))))
        fin, evs = self.lanzar("correo/probar", {"busqueda_id": b["id"]})
        ev = [e for e in evs if e["tipo"] == "correo_prueba"][0]
        self.assertTrue(all(m["procesado"] for m in ev["mensajes"]))     # ahora dice «ya procesado el …»


class TestPaginaCorreo(BaseCorreo):
    def test_pagina_editor_y_probar_en_el_navegador(self):
        from playwright.sync_api import sync_playwright
        c = self.cuenta()
        self.busqueda(c["id"])
        errores = []
        with sync_playwright() as p:
            nav = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = nav.new_page()
                pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errores.append(str(e)))
                pg.goto(self.srv.url_con_token("correo"), wait_until="load")
                pg.wait_for_selector("#contenido [data-pagina='correo'] .correo-tarjeta", timeout=15000)
                self.assertEqual(pg.locator("#contenido .correo-cuenta").count(), 1)
                self.assertIn("falta iniciar sesión", pg.locator("#contenido .correo-cuenta").inner_text())
                pg.click("#contenido button[data-editar-correo]")
                pg.wait_for_selector(".modal [data-modal-correo] [data-correo-que]", timeout=10000)
                self.assertEqual(pg.locator(".modal .correo-accion").count(), 2)
                pg.click(".modal button[data-anadir-accion]")
                self.assertEqual(pg.locator(".modal .correo-accion").count(), 3)
                pg.wait_for_selector(".modal [data-cuando] [data-cuando-vista]", timeout=10000)
                pg.click(".modal button[data-probar-correo]")
                pg.wait_for_selector(".modal [data-prueba-correo] li[data-correo-encontrado]", timeout=90000)
                self.assertEqual(pg.locator(".modal [data-prueba-correo] li[data-correo-encontrado]").count(), 2)
                self.assertIn("2 correo(s) coinciden ahora", pg.locator(".modal [data-prueba-correo]").inner_text())
                # (que termine el trabajo «Probar» y la página se repinte antes de seguir)
                pg.wait_for_selector("#trabajo.oculto", state="attached", timeout=30000)
                pg.wait_for_timeout(800)
                pg.click(".modal .pie button:has-text('Cancelar')")
                pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
                pg.click("#contenido button[data-nueva-busqueda]")
                pg.wait_for_selector(".modal [data-modal-correo]", timeout=10000)
                pg.fill(".modal input[aria-label='Nombre de la búsqueda']", "Otra")
                pg.fill(".modal input[aria-label='El asunto contiene']", "Estado de cuenta")
                pg.click(".modal .pie button:has-text('Guardar')")
                try:
                    pg.wait_for_selector("#contenido .correo-tarjeta >> nth=1", timeout=20000)
                except Exception:
                    self.fail("no apareció la búsqueda nueva; avisos: %s; ventana: %s" % (
                        pg.locator("#toasts").inner_text(), pg.locator("#modal-fondo").inner_text()[:500]))
                self.assertEqual(len(self.api("GET", "correo")["busquedas"]), 2)
            finally:
                nav.close()
        self.assertEqual(errores, [])


if __name__ == "__main__":
    unittest.main()
