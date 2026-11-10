"""Pruebas de la versión 3.6 (rama New-tool): «pegar en Outlook» y «calendario de fechas».

1. Outlook: se busca con el texto COMPLETO (el asunto entero), pegándolo en el buscador (no tecleándolo), se comprueba
   que quedó entero y, si nada de lo que sale vale, se prueba una vez con uno más corto.  La página de prueba
   `correo_outlook.html` tiene ahora un buscador que PIERDE las letras tecleadas muy seguidas (como el combobox de
   Outlook): demuestra el fallo de antes y que pegar lo arregla (también con Ctrl+V cuando no acepta el texto insertado).
2. Fechas: plantillas nuevas (semanas, año), `analizar_fecha` / `plantilla_fecha` (ida y vuelta), lo mismo en la
   interfaz (`window.__botFechas`), y el campo de fecha con calendario (`campoFecha`) en el navegador: elegir un día,
   «Ayer» + formato, el teclado, y que lo elegido se guarda con el texto de siempre.

Base de datos temporal, contraseñas en memoria, sin avisos de Windows, sin tareas programadas, sin Internet.  El
portapapeles: con el navegador OCULTO Chrome usa uno propio (no el de Windows); la prueba lo comprueba con el número de
secuencia del portapapeles de Windows (solo lectura: no lee ni cambia su contenido).
"""

import datetime
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import HAY_PLAYWRIGHT  # noqa: E402
from webbot import correo, filtros, mapeador, plantillas  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

HOY = datetime.date(2026, 10, 29)          # jueves
ASUNTO = "RESUMEN DE VENTAS EMPRESA EJEMPLO, S.A.S."


def secuencia_portapapeles():
    """Número de secuencia del portapapeles de Windows (cambia cada vez que alguien lo cambia).  Solo lectura."""
    if os.name != "nt":
        return None
    import ctypes
    return ctypes.windll.user32.GetClipboardSequenceNumber()


# ============================================================================ plantillas de fecha
class TestPlantillasNuevas(unittest.TestCase):
    def r(self, texto, hoy=HOY):
        return plantillas.renderizar(texto, hoy=hoy)

    def test_semanas_y_anio(self):
        self.assertEqual(self.r("{lunes_semana}"), "26/10/2026")
        self.assertEqual(self.r("{lunes_semana_anterior}"), "19/10/2026")
        self.assertEqual(self.r("{domingo_semana_anterior:%Y-%m-%d}"), "2026-10-25")
        self.assertEqual(self.r("{inicio_anio}"), "01/01/2026")
        lunes, domingo = datetime.date(2026, 10, 26), datetime.date(2026, 11, 1)
        self.assertEqual(self.r("{lunes_semana}", lunes), "26/10/2026")            # el lunes es el primer día
        self.assertEqual(self.r("{domingo_semana_anterior}", lunes), "25/10/2026")
        self.assertEqual(self.r("{lunes_semana}", domingo), "26/10/2026")          # el domingo, el último
        self.assertEqual(self.r("{lunes_semana_anterior}", datetime.date(2027, 1, 3)), "21/12/2026")
        for n in ("lunes_semana", "lunes_semana_anterior", "domingo_semana_anterior", "inicio_anio"):
            self.assertIn(n, plantillas.RESERVADAS)
            self.assertIn("{%s}" % n, [x[0] for x in plantillas.AYUDA_PLANTILLAS])
        self.assertEqual(plantillas.variables_usadas("{lunes_semana} {cliente}"), ["cliente"])

    def test_pasos_con_esas_fechas_son_filtros_de_fecha(self):
        for v in ("{dias:-7}", "{lunes_semana:%d-%m-%Y}", "{inicio_anio}"):
            self.assertTrue(filtros.es_fecha(Paso("escribir", selectores=["#x"], objetivo="Campo", valor=v)), v)
        self.assertFalse(filtros.es_fecha(Paso("escribir", selectores=["#x"], objetivo="Cliente", valor="Acme")))


class TestAnalizarFecha(unittest.TestCase):
    # (texto guardado, lo que entiende la interfaz)
    CASOS = [
        ("{ayer:%d/%m/%Y}", {"modo": "relativa", "que": "ayer", "n": None, "formato": "%d/%m/%Y"}),
        ("{ayer}", {"modo": "relativa", "que": "ayer", "n": None, "formato": None}),
        ("{hoy:%Y-%m-%d}", {"modo": "relativa", "que": "hoy", "n": None, "formato": "%Y-%m-%d"}),
        ("{dias:-7}", {"modo": "relativa", "que": "dias", "n": -7, "formato": None}),
        ("{dias:3:%d.%m.%Y}", {"modo": "relativa", "que": "dias", "n": 3, "formato": "%d.%m.%Y"}),
        ("{fin_mes_anterior:%m/%d/%Y}", {"modo": "relativa", "que": "fin_mes_anterior", "n": None, "formato": "%m/%d/%Y"}),
        ("{fecha:%d/%m/%Y}", {"modo": "relativa", "que": "fecha", "n": None, "formato": "%d/%m/%Y"}),
        ("{lunes_semana}", {"modo": "relativa", "que": "lunes_semana", "n": None, "formato": None}),
        ("15/10/2026", {"modo": "fija", "fecha": "2026-10-15", "formato": "%d/%m/%Y"}),
        ("2026-10-15", {"modo": "fija", "fecha": "2026-10-15", "formato": "%Y-%m-%d"}),
        ("15-10-2026", {"modo": "fija", "fecha": "2026-10-15", "formato": "%d-%m-%Y"}),
        ("10/28/2026", {"modo": "fija", "fecha": "2026-10-28", "formato": "%m/%d/%Y"}),
        ("10/11/2026", {"modo": "fija", "fecha": "2026-11-10", "formato": "%d/%m/%Y"}),     # dd/mm primero
        ("15.10.2026", {"modo": "fija", "fecha": "2026-10-15", "formato": "%d.%m.%Y"}),
        ("15/10/26", {"modo": "fija", "fecha": "2026-10-15", "formato": "%d/%m/%y"}),
        ("28 Oct 2026", {"modo": "fija", "fecha": "2026-10-28", "formato": "%d %b %Y"}),
        ("", {"modo": "vacia"}),
        ("   ", {"modo": "vacia"}),
        ("Acme", {"modo": "mano", "texto": "Acme"}),
        ("{hoy:%d/%m/%Y} 00:00", {"modo": "mano", "texto": "{hoy:%d/%m/%Y} 00:00"}),
        ("1/2/2026", {"modo": "mano", "texto": "1/2/2026"}),                  # sin ceros: a mano
        ("31/02/2026", {"modo": "mano", "texto": "31/02/2026"}),              # no existe
        ("20261015", {"modo": "mano", "texto": "20261015"}),                  # 8 cifras: puede ser otra cosa
        ("{cliente}", {"modo": "mano", "texto": "{cliente}"}),
        ("{hoy:%Q}", {"modo": "mano", "texto": "{hoy:%Q}"}),                  # formato que no existe
    ]

    def test_analizar(self):
        for texto, esperado in self.CASOS:
            self.assertEqual(plantillas.analizar_fecha(texto), esperado, texto)

    def test_ida_y_vuelta(self):
        """Lo que se guarda y se vuelve a cargar no cambia (si no se toca nada, el texto queda igual)."""
        for texto, _ in self.CASOS:
            if texto.strip():
                self.assertEqual(plantillas.plantilla_fecha(plantillas.analizar_fecha(texto)), texto, texto)
        for texto in ("{ayer:%d/%m/%Y}", "{dias:-7:%Y-%m-%d}", "15/10/2026", "{inicio_anio:%d %b %Y}"):
            a = plantillas.analizar_fecha(texto)
            self.assertEqual(plantillas.renderizar(plantillas.plantilla_fecha(a), hoy=HOY),
                             plantillas.renderizar(texto, hoy=HOY))

    def test_componer_lo_elegido(self):
        p = plantillas.plantilla_fecha
        self.assertEqual(p({"modo": "relativa", "que": "ayer", "formato": "%d/%m/%Y"}), "{ayer:%d/%m/%Y}")
        self.assertEqual(p({"modo": "relativa", "que": "ayer", "formato": None}), "{ayer}")
        self.assertEqual(p({"modo": "relativa", "que": "dias", "n": -3, "formato": "%Y-%m-%d"}), "{dias:-3:%Y-%m-%d}")
        self.assertEqual(p({"modo": "fija", "fecha": "2026-10-15", "formato": "%d %b %Y"}), "15 Oct 2026")
        self.assertEqual(p({"modo": "fija", "fecha": "2026-10-05"}), "05/10/2026")
        self.assertEqual(p({"modo": "vacia"}), "")
        for malo in ({"modo": "fija", "fecha": "2026-02-31"}, {"modo": "relativa", "que": "pasado"},
                     {"modo": "relativa", "que": "dias", "n": "x"}, {"modo": "relativa", "que": "hoy", "formato": "%Q"}):
            with self.assertRaises(plantillas.ErrorPlantilla):
                p(malo)

    def test_describir_y_formato(self):
        d = plantillas.describir_fecha
        self.assertEqual(d("{ayer:%d/%m/%Y}", HOY), "ayer · 28/10/2026")
        self.assertEqual(d("{dias:-7}", HOY), "hace 7 días · 22/10/2026")
        self.assertEqual(d("{dias:-1}", HOY), "hace 1 día · 28/10/2026")
        self.assertEqual(d("{dias:2:%Y-%m-%d}", HOY), "dentro de 2 días · 2026-10-31")
        self.assertEqual(d("15/10/2026", HOY), "fecha fija · 15/10/2026")
        self.assertEqual(d("{inicio_mes_anterior}", HOY), "inicio del mes anterior · 01/09/2026")
        self.assertEqual(d("Acme", HOY), "Acme")
        self.assertEqual(plantillas.formato_de_fecha("{ayer:%Y-%m-%d}"), "%Y-%m-%d")
        self.assertEqual(plantillas.formato_de_fecha("{ayer}"), "%d/%m/%Y")
        self.assertEqual(plantillas.formato_de_fecha("15.10.2026"), "%d.%m.%Y")
        self.assertIsNone(plantillas.formato_de_fecha("Acme"))

    def test_formatos_y_botones(self):
        ejemplos = [datetime.date(2026, 10, 28).strftime(f) for f, _ in plantillas.FORMATOS_FECHA]
        self.assertEqual(len(set(ejemplos)), len(ejemplos))           # cada formato se ve distinto
        self.assertEqual(ejemplos[:4], ["28/10/2026", "2026-10-28", "28-10-2026", "10/28/2026"])
        self.assertEqual(plantillas.FORMATOS_FECHA[0][0], plantillas.FORMATO_FECHA)
        for que, _n in plantillas.RELATIVAS:
            self.assertTrue(que in plantillas.FECHAS or que in ("dias", "fecha"), que)

    def test_la_interfaz_tiene_las_mismas_listas(self):
        with open(os.path.join(RAIZ, "ui", "app.js"), encoding="utf-8") as f:
            js = f.read()
        bloque = js[js.index("const FORMATOS_FECHA = "):js.index("const FECHAS_NOMBRADAS")]
        self.assertEqual(re.findall(r"\['(%[^']+)'", bloque), [f for f, _ in plantillas.FORMATOS_FECHA])
        bloque = js[js.index("const RELATIVAS = "):js.index("const PALABRAS_FECHA")]
        self.assertEqual(re.findall(r"\['([a-z_]+)'", bloque), [q for q, _ in plantillas.RELATIVAS])
        bloque = js[js.index("const FECHAS_NOMBRADAS = "):js.index("// Botones de «Cambia sola»")]
        self.assertEqual(sorted(re.findall(r"'([a-z_]+)'", bloque)), sorted(plantillas.FECHAS))


class TestMapeoYFiltros(unittest.TestCase):
    F = {"tipo": "fecha", "etiqueta": "Desde", "valor": "29/10/2026", "tipo_campo": "text"}

    def test_mapear_con_lo_que_sale_del_calendario(self):
        paso = mapeador._paso_de_filtro(self.F, {"fecha": "plantilla", "valor": "{ayer:%Y-%m-%d}"}, "fecha", ["#d"], "Desde")
        self.assertEqual((paso.tipo, paso.valor, paso.fecha_directa), ("escribir", "{ayer:%Y-%m-%d}", True))
        paso = mapeador._paso_de_filtro(self.F, {"fecha": "plantilla", "valor": "15/10/2026"}, "fecha", ["#d"], "Desde")
        self.assertEqual(paso.valor, "15/10/2026")
        with self.assertRaises(mapeador.ErrorMapeo):
            mapeador._paso_de_filtro(self.F, {"fecha": "plantilla", "valor": "{ayer"}, "fecha", ["#d"], "Desde")
        # lo de antes sigue valiendo
        self.assertEqual(mapeador._paso_de_filtro(self.F, {"fecha": "ayer", "formato": "%d/%m/%Y"}, "fecha", ["#d"],
                                                  "Desde").valor, "{ayer:%d/%m/%Y}")
        self.assertEqual(mapeador._paso_de_filtro(self.F, {"fecha": "fija", "valor": "{x}"}, "fecha", ["#d"],
                                                  "Desde").valor, "{{x}}")

    def test_formato_en_usar_filtros_y_paginas(self):
        fl = Flujo(nombre="R", url="http://x/", pasos=[
            Paso("abrir_url", url="http://x/"),
            Paso("escribir", selectores=["#d"], objetivo="Fecha desde", valor="{ayer:%Y-%m-%d}", fecha_directa=True),
            Paso("escribir", selectores=["#h"], objetivo="Fecha hasta", valor="15.10.2026")])
        d = filtros.datos_panel(fl)
        self.assertEqual([x["formato"] for x in d], ["%Y-%m-%d", "%d.%m.%Y"])
        from webbot import paginas
        data = paginas.normalizar({"url": "http://x/", "filtros": [
            {"id": "f1", "tipo": "fecha", "nombre": "Desde", "selectores": ["#d"], "formato": "%Y-%m-%d",
             "defecto": {"valor": "{ayer:%Y-%m-%d}"}}], "accion": {"tipo": "descargar"}})
        self.assertEqual(paginas.formulario(data, [])[0]["formato"], "%Y-%m-%d")


# ============================================================================ Outlook: texto completo y pegado
class TestTextoBusqueda(unittest.TestCase):
    def c(self, **k):
        return correo.normalizar_criterios(dict({"fecha": "cualquiera"}, **k), exigir=False)

    def test_texto_completo_y_corto(self):
        self.assertEqual(correo.texto_a_teclear(self.c(asunto=ASUNTO)), ASUNTO)
        self.assertEqual(correo.texto_a_teclear(self.c(asunto="  VENTAS   DIARIAS  ")), "VENTAS DIARIAS")
        self.assertEqual(correo.texto_a_teclear(self.c(asunto=ASUNTO, buscar="ventas sas")), "ventas sas")
        self.assertEqual(correo.textos_a_buscar(self.c(asunto=ASUNTO)),
                         [(ASUNTO, "completo"), ("RESUMEN DE VENTAS EMPRESA EJEMPLO", "más corto")])
        # sin coma: las 4 primeras palabras sin signos (lo de Octopus)
        self.assertEqual(correo.textos_a_buscar(self.c(asunto="Reporte: ventas diarias (Zona Capital) 2026")),
                         [("Reporte: ventas diarias (Zona Capital) 2026", "completo"),
                          ("Reporte ventas diarias Zona", "más corto")])
        # ya es corto: un solo intento
        self.assertEqual(correo.textos_a_buscar(self.c(asunto="Estado de cuenta")), [("Estado de cuenta", "completo")])
        self.assertEqual(correo.textos_a_buscar(self.c(remitente="reportes@ejemplo.com")),
                         [("reportes@ejemplo.com", "completo")])
        self.assertEqual(correo.textos_a_buscar(self.c(cuerpo=["Total ventas"])), [("Total ventas", "completo")])
        self.assertEqual(correo.textos_a_buscar(self.c()), [])
        self.assertEqual(correo.texto_corto("A, B"), "A B")             # una palabra antes de la coma: 4 palabras
        self.assertEqual(correo.texto_corto("uno"), "")


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestOutlookPegar(unittest.TestCase):
    """El adaptador de Outlook contra la página de prueba (buscador que pierde letras tecleadas)."""

    @classmethod
    def setUpClass(cls):
        from servidor_prueba import ServidorPrueba
        cls.web = ServidorPrueba().iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.web.parar()

    def setUp(self):
        self.web.estado.update(correo_login=False, correos_extra=[], correo_descargas=[], correo_busquedas=[])
        self.tmp = tempfile.mkdtemp(prefix="botweb_v36_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = []

    def buscar(self, pagina, **criterios):
        cuenta = {"id": 1, "nombre": "Prueba", "proveedor": "outlook_web", "url": self.web.url_base + pagina}
        c = correo.normalizar_criterios(dict({"fecha": "cualquiera"}, **criterios), exigir=False)
        with correo.crear_adaptador(cuenta, os.path.join(self.tmp, "perfiles"), oculto=True, log=self.log.append) as a:
            lista = a.buscar(c, datetime.date.today())
        return [m for m in lista if correo.coincide(m, c, fase="resumen")[0]]

    def test_teclear_pierde_letras_en_la_pagina_de_prueba(self):
        """El fallo de antes: tecleado pulsación a pulsación (40 ms), el combobox se come letras."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            nav = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = nav.new_page()
                pg.goto(self.web.url_base + "correo_outlook.html", wait_until="load")
                pg.wait_for_selector("[data-convid]")
                pg.click("#buscar")
                pg.type("#buscar", ASUNTO, delay=40)
                self.assertNotEqual(pg.input_value("#buscar"), ASUNTO)
                self.assertGreater(pg.evaluate("window.letrasPerdidas"), 0)
                pg.fill("#buscar", "")
                pg.keyboard.insert_text(ASUNTO)                             # pegado: llega entero
                self.assertEqual(pg.input_value("#buscar"), ASUNTO)
            finally:
                nav.close()

    def test_pega_el_asunto_completo(self):
        antes = secuencia_portapapeles()
        encontrados = self.buscar("correo_outlook.html", asunto=ASUNTO)
        self.assertEqual(len(encontrados), 3)                                # m1, m2 y el de hace 10 días
        self.assertEqual(self.web.estado["correo_busquedas"][-1], ASUNTO)    # buscado con el texto ENTERO
        self.assertIn("Buscando en Outlook: «%s» (completo)" % ASUNTO, self.log)
        self.assertIn("  buscador: «%s» (pegado y comprobado)" % ASUNTO, self.log)
        self.assertFalse([x for x in self.log if "se prueba con" in x])     # no hizo falta el segundo intento
        self.assertEqual(secuencia_portapapeles(), antes)                    # el portapapeles de Windows, sin tocar

    def test_buscador_como_el_real_pierde_el_placeholder_al_pegar(self):
        """v3.6.1: en el Outlook real el placeholder «Search» desaparece al tener texto; el bot lo buscaba por el
        placeholder, lo perdía justo después de pegar y nunca pulsaba Enter."""
        t0 = time.monotonic()
        encontrados = self.buscar("correo_outlook.html?como_real=1", asunto=ASUNTO)
        self.assertEqual(len(encontrados), 3)
        self.assertEqual(self.web.estado["correo_busquedas"][-1], ASUNTO)
        self.assertIn("  buscador: «%s» (pegado y comprobado)" % ASUNTO, self.log)
        self.assertLess(time.monotonic() - t0, 25, self.log)                 # sin esperas de 30 s por el buscador

    def test_con_ctrl_v_si_no_acepta_el_texto_insertado(self):
        antes = secuencia_portapapeles()
        encontrados = self.buscar("correo_outlook.html?sin_insertar=1", asunto=ASUNTO)
        self.assertEqual(len(encontrados), 3)
        self.assertEqual(self.web.estado["correo_busquedas"][-1], ASUNTO)
        self.assertTrue([x for x in self.log if x.startswith("  el buscador quedó con «»")], self.log)
        self.assertIn("  buscador: «%s» (pegado con Ctrl+V y comprobado)" % ASUNTO, self.log)
        self.assertEqual(secuencia_portapapeles(), antes)                    # (Chrome oculto: portapapeles propio)

    def test_si_el_texto_completo_no_encuentra_nada_prueba_uno_mas_corto(self):
        encontrados = self.buscar("correo_outlook.html?coma_falla=1", asunto=ASUNTO)
        self.assertEqual(len(encontrados), 3)
        self.assertEqual(self.web.estado["correo_busquedas"][-2:],
                         ["__sin_resultados__ " + ASUNTO, "RESUMEN DE VENTAS EMPRESA EJEMPLO"])
        self.assertIn("Outlook: sin resultados que cumplan la búsqueda con «%s»; se prueba con «RESUMEN DE VENTAS "
                      "EMPRESA EJEMPLO» (más corto)" % ASUNTO, self.log)
        self.assertIn("Buscando en Outlook: «RESUMEN DE VENTAS EMPRESA EJEMPLO» (más corto)", self.log)

    def test_sin_resultados_que_valgan_no_reintenta_si_no_hay_texto_corto(self):
        encontrados = self.buscar("correo_outlook.html", asunto="Estado de cuenta", remitente="nadie@ejemplo.com")
        self.assertEqual(encontrados, [])
        self.assertEqual([x for x in self.web.estado["correo_busquedas"] if x], ["Estado de cuenta"])


# ============================================================================ el calendario en la interfaz
@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestCampoFecha(unittest.TestCase):
    """Con navegador oculto: el campo de fecha en el formulario de una Página, en el editor de pasos y en «Programar»."""

    @classmethod
    def setUpClass(cls):
        from test_servidor_ui import BaseApi  # noqa: F401  (mismas piezas que las demás pruebas de la interfaz)

    def setUp(self):
        from webbot import avisos, secretos
        from webbot import paginas as mod_paginas
        from webbot import servidor_ui as su
        from webbot.almacen import Almacen
        self.tmp = tempfile.mkdtemp(prefix="botweb_v36ui_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        avisos.usar_notificador(lambda t, x: None)
        self.addCleanup(avisos.usar_notificador, None)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.rid = self.alm.guardar(Flujo(nombre="Ventas", url="http://127.0.0.1/", pasos=[
            Paso("abrir_url", url="http://127.0.0.1/"),
            Paso("escribir", selectores=["#desde"], objetivo="Fecha desde", valor="{ayer:%d/%m/%Y}", fecha_directa=True),
            Paso("escribir", selectores=["#cliente"], objetivo="Cliente", valor="Acme")]))
        self.pid, _ = mod_paginas.guardar_nueva(self.alm, "Página de prueba", {
            "url": "http://127.0.0.1/", "llegada": [Paso("abrir_url", url="http://127.0.0.1/").a_dict()],
            "filtros": [{"id": "f1", "tipo": "fecha", "nombre": "Desde", "selectores": ["#desde"], "formato": "%d/%m/%Y",
                         "defecto": {"valor": "{ayer}"}}],
            "accion": {"tipo": "boton_descarga", "generar": {"selectores": ["#generar"], "objetivo": "Generar"}}}, [])
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "perfiles"),
                                 carpeta_registros=os.path.join(self.tmp, "registros"),
                                 carpeta_descargas=os.path.join(self.tmp, "descargas"), listar_tareas=lambda: [],
                                 oculto_forzado=True, ejecutar_tareas=lambda cmd: (1, "(prueba: sin tareas)"))
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)
        self.addCleanup(self.app.detener)

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

    def test_analisis_igual_en_la_interfaz_y_en_python(self):
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("inicio"), wait_until="load")
        pg.wait_for_function("() => !!window.__botFechas")
        textos = [t for t, _ in TestAnalizarFecha.CASOS] + ["{dias: -3 }", "{inicio_anio:%Y}", "{fecha}"]
        js = pg.evaluate("ts => ts.map((t) => { const a = window.__botFechas.analizar(t); "
                         "return [a, window.__botFechas.componer(a)]; })", textos)
        for t, (a, compuesto) in zip(textos, js):
            self.assertEqual(a, plantillas.analizar_fecha(t), t)
            if t.strip():
                self.assertEqual(compuesto, plantillas.plantilla_fecha(plantillas.analizar_fecha(t)), t)
        hoy = pg.evaluate("() => { const d = new Date(); return [d.getFullYear(), d.getMonth() + 1, d.getDate()]; }")
        hoy = datetime.date(*hoy)
        for t in ("{ayer:%d/%m/%Y}", "{dias:-7}", "{lunes_semana_anterior:%Y-%m-%d}", "{fin_mes_anterior}", "15/10/2026",
                  "{inicio_anio:%d %b %Y}", "{domingo_semana_anterior:%d.%m.%y}"):
            self.assertEqual(pg.evaluate("t => window.__botFechas.describir(t)", t), plantillas.describir_fecha(t, hoy), t)
        self.assertEqual(self.errores, [])

    def test_pagina_elegir_dia_y_ayer_con_formato(self):
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("paginas/%d" % self.pid), wait_until="load")
        boton = "#contenido [data-filtro='f1'] button[data-campo-fecha]"
        pg.wait_for_selector(boton, timeout=15000)
        campo = "#contenido [data-filtro='f1'] input.fecha-texto"
        self.assertFalse(pg.locator(campo).is_visible())                    # el texto de la plantilla, escondido
        self.assertIn("Ayer", pg.locator(boton).inner_text())
        # 1) fecha fija: el día 15 del mes que se ve
        pg.click(boton)
        pg.wait_for_selector("[data-fecha-pop] [data-fecha-modo='relativa'][aria-pressed='true']")
        pg.click("[data-fecha-pop] [data-fecha-modo='fija']")
        dia = pg.locator("[data-fecha-pop] .cal-dia").nth(14)
        iso = dia.get_attribute("data-dia")
        dia.click()
        a, m, d = iso.split("-")
        self.assertEqual(pg.input_value(campo), "%s/%s/%s" % (d, m, a))
        self.assertEqual(pg.locator("[data-fecha-pop] .cal-dia.elegido").get_attribute("data-dia"), iso)
        self.assertIn("Se escribirá: %s/%s/%s" % (d, m, a), pg.locator("[data-fecha-pop] [data-fecha-se-escribira]").inner_text())
        # teclado: → y Enter = el día siguiente; Esc cierra
        pg.locator("[data-fecha-pop] .cal-dia.elegido").focus()
        pg.keyboard.press("ArrowRight")
        pg.keyboard.press("Enter")
        siguiente = (datetime.date(int(a), int(m), int(d)) + datetime.timedelta(days=1)).strftime("%d/%m/%Y")
        self.assertEqual(pg.input_value(campo), siguiente)
        pg.keyboard.press("Escape")
        pg.wait_for_selector("[data-fecha-pop]", state="detached")
        self.assertEqual(pg.evaluate("() => document.activeElement.dataset.campoFecha"), "1")   # el foco vuelve
        self.assertIn("Fecha fija", pg.locator(boton).inner_text())
        # 2) «Cambia sola»: Ayer con el formato aaaa-mm-dd
        pg.click(boton)
        pg.click("[data-fecha-pop] [data-fecha-modo='relativa']")
        pg.click("[data-fecha-pop] [data-fecha-rel='ayer']")
        self.assertEqual(pg.input_value(campo), "{ayer:%d/%m/%Y}")        # (el formato de la fecha que había)
        opciones = pg.locator("[data-fecha-pop] select[data-fecha-formato] option").all_inner_texts()
        self.assertTrue(any(re.fullmatch(r"\d{4}-\d\d-\d\d  \(como los campos de fecha\)", o) for o in opciones), opciones)
        pg.select_option("[data-fecha-pop] select[data-fecha-formato]", "%Y-%m-%d")
        self.assertEqual(pg.input_value(campo), "{ayer:%Y-%m-%d}")
        # 3) hace N días
        pg.fill("[data-fecha-pop] input[data-fecha-n]", "3")
        self.assertEqual(pg.input_value(campo), "{dias:-3:%Y-%m-%d}")
        pg.click("[data-fecha-pop] [data-fecha-rel='ayer']")
        pg.click("[data-fecha-pop] button[data-fecha-listo]")
        pg.wait_for_selector("[data-fecha-pop]", state="detached")
        # se guarda con el texto de siempre
        pg.click("#contenido button:has-text('Guardar como valores por defecto')")
        pg.click(".modal .pie button:has-text('Guardar')")
        pg.wait_for_function("() => /Valores por defecto guardados/.test(document.querySelector('#toasts').textContent)",
                             timeout=10000)
        self.assertIn("{ayer:%Y-%m-%d}", repr(self.alm.obtener_pagina(self.pid)))
        # «Escribir a mano»: enseña el texto
        pg.click("#contenido [data-filtro='f1'] button[data-fecha-mano]")
        self.assertTrue(pg.locator(campo).is_visible())
        self.assertEqual(self.errores, [])

    def test_editor_de_pasos_y_programar(self):
        pg = self.navegador()
        pg.goto(self.srv.url_con_token("editor/%d" % self.rid), wait_until="load")
        pg.wait_for_selector("#contenido tr[data-indice='1'] button:has-text('Editar')", timeout=15000)
        # el paso que escribe {ayer:%d/%m/%Y} (grabado desde un calendario): con el campo de fecha
        pg.locator("#contenido tr[data-indice='1'] button:has-text('Editar')").click()
        pg.wait_for_selector(".modal button[data-campo-fecha]")
        self.assertIn("Ayer", pg.locator(".modal button[data-campo-fecha]").inner_text())
        pg.click(".modal button[data-campo-fecha]")
        pg.wait_for_selector("[data-fecha-pop] [data-fecha-rel='ayer'].activo")
        self.assertEqual(pg.locator("[data-fecha-pop] select[data-fecha-formato]").input_value(), "%d/%m/%Y")
        pg.click("[data-fecha-pop] [data-fecha-rel='lunes_semana']")
        pg.keyboard.press("Escape")                                         # cierra el calendario, NO la ventana
        pg.wait_for_selector("[data-fecha-pop]", state="detached")
        self.assertTrue(pg.locator(".modal").is_visible())
        pg.click(".modal .pie button:has-text('Aceptar')")
        pg.wait_for_selector("#modal-fondo.oculto", state="attached", timeout=5000)
        # un paso de texto normal: sin calendario (con el botón para usarlo si es una fecha)
        pg.locator("#contenido tr[data-indice='2'] button:has-text('Editar')").click()
        pg.wait_for_selector(".modal button[data-usar-calendario]")
        self.assertEqual(pg.locator(".modal button[data-campo-fecha]").count(), 0)
        pg.click(".modal .pie button:has-text('Cancelar')")
        pg.click("#contenido .barra-herr button:has-text('Guardar')")
        pg.wait_for_function("() => /guardado/.test(document.querySelector('#subtitulo').textContent)", timeout=10000)
        self.assertEqual(self.alm.cargar_flujo(self.rid).pasos[1].valor, "{lunes_semana:%d/%m/%Y}")
        # «Programar…»: la fecha de inicio con el calendario (AAAA-MM-DD, como antes)
        pg.click("#contenido button:has-text('Programar…')")
        pg.wait_for_selector(".modal .cuando-fechas", timeout=15000)
        pg.evaluate("() => { document.querySelector('.modal .cuando-fechas').open = true; }")
        pg.locator(".modal .cuando-fechas button[data-campo-fecha]").first.click()
        pg.wait_for_selector("[data-fecha-pop] .cal-dia")
        self.assertEqual(pg.locator("[data-fecha-pop] [data-fecha-modo]").count(), 0)    # solo fecha fija
        pg.click("[data-fecha-pop] [data-cal-siguiente]")
        dia = pg.locator("[data-fecha-pop] .cal-dia").first
        iso = dia.get_attribute("data-dia")
        dia.click()
        pg.wait_for_selector("[data-fecha-pop]", state="detached")
        self.assertEqual(pg.locator(".modal input[aria-label='Fecha de inicio']").input_value(), iso)
        d = datetime.date.fromisoformat(iso)
        pg.wait_for_function("t => document.querySelector('.modal [data-cuando-vista]').textContent.includes(t)",
                             arg="desde el", timeout=10000)
        self.assertIn(str(d.day), pg.locator(".modal .cuando-fechas button[data-campo-fecha]").first.inner_text())
        self.assertEqual(self.errores, [])


# ============================================================================ v3.6.1: fechas en casillas con máscara
from test_integracion import BaseIntegracion  # noqa: E402


class TestFechaConMascara(BaseIntegracion):
    """La casilla de fecha de Informes desordenaba lo escrito con `fill` («3020/2/026»)."""

    def test_fecha_en_casilla_con_mascara(self):
        f = Flujo(nombre="Máscara", url=self.base + "fecha_mascara.html")
        f.pasos = [Paso("abrir_url", url=self.base + "fecha_mascara.html"),
                   Paso("escribir", selectores=["#fecha"], valor="{hoy:%d/%m/%Y}", objetivo="Fecha Inicial",
                        fecha_directa=True),
                   Paso("esperar_elemento", selectores=['p:text-is("Fecha correcta: 15/03/2026")'])]
        f.opciones["timeout_paso"] = 8
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertIn("se teclea despacio", log)

    def test_fecha_en_el_formato_de_la_casilla(self):
        """Informes real: el reporte escribe dd/mm/aaaa y la casilla es AAAA-MM-DD («30/10/2026» → «3010-20-26»)."""
        f = Flujo(nombre="Máscara ISO", url=self.base + "fecha_mascara.html?iso=1")
        f.opciones["timeout_paso"] = 8
        f.pasos = [Paso("abrir_url", url=self.base + "fecha_mascara.html?iso=1"),
                   Paso("escribir", selectores=["#fecha"], valor="{hoy:%d/%m/%Y}", objetivo="Fecha Inicial",
                        fecha_directa=True),
                   Paso("esperar_elemento", selectores=['p:text-is("Fecha correcta: 2026-03-15")'])]
        r = self.ejecutar(f)
        log = self.leer_log(r)
        self.assertTrue(r.ok, log)
        self.assertIn("la casilla usa fechas como «2026-01-01» y dejó «1503-20-26»: se escribe «2026-03-15»", log)

    def test_formato_de_forma(self):
        from webbot.ejecutor import formato_de_forma, leer_fecha
        self.assertEqual(formato_de_forma("3010-20-26"), "%Y-%m-%d")
        self.assertEqual(formato_de_forma("dd/mm/aaaa"), "%d/%m/%Y")
        self.assertIsNone(formato_de_forma("Buscar..."))
        self.assertEqual(leer_fecha("30/10/2026"), (datetime.date(2026, 10, 30), "%d/%m/%Y"))
        self.assertEqual(leer_fecha("31/02/2026"), (None, None))
        self.assertEqual(leer_fecha("2026 P10"), (None, None))


if __name__ == "__main__":
    unittest.main()
