"""Pruebas de integración de la versión 2.1 (navegador oculto + sitio local de prueba):

esperas largas, calendarios (fecha directa), contraseñas con «ojito», varias descargas,
lotes de reportes por línea de comandos y «guardar página» (PDF, HTML, CSV).
Nunca usan el ratón ni el teclado reales, ni crean tareas programadas.
"""

import contextlib
import csv
import io
import os
import sys
import threading
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from test_integracion import CLAVE, HOY, BaseIntegracion  # noqa: E402
from webbot import secretos  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402
from webbot.grabador_web import GrabadorWeb  # noqa: E402


class BaseGrabacion(BaseIntegracion):
    def grabar(self, url, conducir, nombre="Grabado", **kw):
        """Graba oculto: `conducir(grabador)` corre en el hilo de trabajo y maneja la página."""
        flujo = Flujo(nombre=nombre, url=url)
        eventos = []
        grab = GrabadorWeb(flujo, os.path.join(self.tmp, "perfil_grab"), oculto=True,
                           al_evento=lambda tipo, **datos: eventos.append((tipo, datos)), hoy=HOY,
                           carpeta_descargas_grabacion=os.path.join(self.tmp, "grabacion"), **kw)
        error = []

        def trabajo():
            try:
                grab.grabar(flujo.url)
            except BaseException as e:  # pragma: no cover
                error.append(e)

        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()
        self.assertTrue(grab.esperar_listo(60), "el navegador no arrancó")
        try:
            grab.solicitar(conducir).result(timeout=90)
            grab.detener()
        except BaseException:
            grab.detener()
            raise
        finally:
            hilo.join(30)
        self.assertFalse(hilo.is_alive(), "el hilo de grabación no terminó")
        self.assertEqual(error, [])
        return flujo, eventos

    def opciones_rapidas(self, flujo, **extra):
        flujo.opciones.update(pausa_entre_pasos=0, **extra)
        return flujo


class TestEsperasLargas(BaseIntegracion):
    """El reporte tarda 3 s en generarse y el timeout por paso es de solo 2 s."""

    def flujo(self, *pasos, timeout_paso=2, timeout_descarga=10):
        f = Flujo(nombre="Lento")
        # Estas pruebas miden los tiempos máximos de cada paso; desde la v2.3 el bot además espera solo a que
        # desaparezca el «Generando…» de la página (eso se prueba en test_integracion_v23), así que aquí se apaga.
        f.opciones.update(timeout_paso=timeout_paso, timeout_descarga=timeout_descarga, pausa_entre_pasos=0,
                          esperar_carga=False)
        f.pasos = [Paso("abrir_url", url=self.base + "lento.html?ms=3000"), Paso("clic", selectores=["#generar"])] + list(pasos)
        return f

    def test_espera_aprendida_cubre_la_generacion(self):
        f = self.flujo(Paso("esperar_elemento", selectores=["#resultado"], espera_grabada=2),
                       Paso("clic", selectores=["#descargar"]))
        avisos = []
        res = self.ejecutar(f, aviso_cada=1.0, progreso=lambda i, e, t="": avisos.append((i, e, t)))
        self.assertTrue(res.ok, res.resumen())
        log = self.leer_log(res)
        self.assertIn("esperando a que", log)                              # se avisa mientras espera
        self.assertTrue([a for a in avisos if a[1] == "espera"], avisos)    # y la ventana recibe el aviso

    def test_sin_espera_aprendida_se_agota_el_timeout_del_paso(self):
        f = self.flujo(Paso("esperar_elemento", selectores=["#resultado"]))
        res = self.ejecutar(f)
        self.assertFalse(res.ok)
        self.assertEqual(res.paso_fallido, 3)
        self.assertIn("No apareció", res.error)

    def test_clic_espera_a_que_el_boton_este_habilitado(self):
        # el botón «Descargar» está deshabilitado hasta que termina de generarse
        ok = self.ejecutar(self.flujo(Paso("clic", selectores=["#descargar"], espera_grabada=2)))
        self.assertTrue(ok.ok, ok.resumen())
        mal = self.ejecutar(self.flujo(Paso("clic", selectores=["#descargar"])), nombre_perfil="perfil_b")
        self.assertFalse(mal.ok)
        self.assertIn("deshabilitado", mal.error)

    def test_descargar_usa_la_espera_larga_aunque_el_boton_siga_deshabilitado(self):
        f = self.flujo(Paso("descargar", selectores=["#descargar"], nombre="Lento_{hoy:%Y-%m-%d}{ext}"))
        res = self.ejecutar(f, aviso_cada=1.0)
        self.assertTrue(res.ok, res.resumen())
        destino = os.path.join(self.descargas, "Lento_2026-03-15.csv")
        self.assertEqual(res.archivos, [destino])
        with open(destino, encoding="utf-8") as fh:
            self.assertIn("lento,42", fh.read())
        self.assertIn("esperando a que", self.leer_log(res))

    def test_descargar_con_timeout_propio_corto_falla(self):
        f = self.flujo(Paso("descargar", selectores=["#descargar"], timeout=1.5))
        res = self.ejecutar(f)
        self.assertFalse(res.ok)
        self.assertIn("deshabilitado", res.error)


class TestPasoDesactivado(BaseIntegracion):
    def test_los_pasos_desactivados_se_saltan(self):
        f = Flujo(nombre="Desactivado")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=2)
        f.pasos = [Paso("abrir_url", url=self.base + "index.html"),
                   Paso("clic", selectores=["#no-existe"], desactivado=True),        # fallaría si se ejecutara
                   Paso("escribir", selectores=["#usuario"], valor="demo")]
        estados = []
        res = self.ejecutar(f, progreso=lambda i, e, t="": estados.append((i, e)))
        self.assertTrue(res.ok, res.resumen())
        self.assertEqual((res.completados, res.desactivados), (2, 1))
        self.assertIn((1, "desactivado"), estados)
        log = self.leer_log(res)
        self.assertIn("desactivado", log)
        self.assertIn("1 desactivados", res.resumen())
        # el flag sobrevive al JSON
        self.assertTrue(Flujo.desde_json(f.a_json()).pasos[1].desactivado)

    def test_pausa_entre_pasos(self):
        import time
        f = Flujo(nombre="Pausa")
        f.opciones.update(timeout_paso=5)
        f.pasos = [Paso("esperar_segundos", segundos=0), Paso("esperar_segundos", segundos=0),
                   Paso("esperar_segundos", segundos=0)]
        marcas = []
        res = self.ejecutar(f, pausa_entre_pasos=0.6, progreso=lambda i, e, t="": marcas.append((i, e, time.monotonic())))
        self.assertTrue(res.ok, res.resumen())
        inicios = [t for i, e, t in marcas if e == "inicio"]
        self.assertEqual(len(inicios), 3)
        self.assertGreaterEqual(inicios[1] - inicios[0], 0.55)
        self.assertGreaterEqual(inicios[2] - inicios[1], 0.55)


class TestCalendarios(BaseGrabacion):
    def conducir(self, g):
        pg = g.paginas[0]
        pg.wait_for_selector("#f_ini")

        def elegir(anio, mes, dia):
            pg.click("span.anio:text-is('%d') >> visible=true" % anio)
            pg.click("span.mes:text-is('%s') >> visible=true" % mes)
            pg.click("span.dia:text-is('%d') >> visible=true" % dia)

        pg.click("#g_ini i")                       # icono (su clase «fa-calendar» lo delata como calendario)
        elegir(2026, "Mar", 1)
        pg.wait_for_timeout(900)                   # el valor se detecta al quedarse quieto el calendario
        pg.click("#g_fin i")                       # icono sin pista en su clase («glyphicon-th»)
        elegir(2026, "Mar", 15)
        pg.click("#ver")                           # el siguiente clic fuera del calendario revisa los valores
        pg.wait_for_selector("#rango:has-text('Rango: 2026-03-01')")
        pg.wait_for_timeout(500)

    def test_grabacion_escribe_la_fecha_y_desactiva_los_clics_del_calendario(self):
        flujo, eventos = self.grabar(self.base + "fechas.html", self.conducir)
        tipos = [p.tipo for p in flujo.pasos]
        self.assertEqual(tipos, ["abrir_url"] + ["clic"] * 4 + ["escribir"] + ["clic"] * 4 + ["escribir", "clic"], tipos)
        abrir, *medio, ver = flujo.pasos
        escribir_ini, escribir_fin = flujo.pasos[5], flujo.pasos[10]
        # fechas directas con su valor final
        self.assertTrue(escribir_ini.fecha_directa and escribir_fin.fecha_directa)
        self.assertEqual((escribir_ini.selectores[0], escribir_ini.valor), ("#f_ini", "2026-03-01"))
        self.assertEqual((escribir_fin.selectores[0], escribir_fin.valor), ("#f_fin", "2026-03-15"))
        # todos los clics del calendario (y el del icono que lo abrió) quedan desactivados, no borrados
        for p in flujo.pasos[1:5] + flujo.pasos[6:10]:
            self.assertEqual(p.tipo, "clic")
            self.assertTrue(p.desactivado, p.descripcion())
        self.assertFalse(ver.desactivado)
        self.assertFalse(escribir_ini.desactivado or escribir_fin.desactivado)
        # selectores del año: acotados a su contenedor, no una ruta CSS desde <body>
        anio = flujo.pasos[2]
        self.assertEqual(anio.selectores[0], '.mi-dp-anios span:text-is("2026")')
        self.assertIn('span.anio:text-is("2026")', anio.selectores)
        self.assertNotIn("body", " ".join(anio.selectores[:-1]))
        # espera aprendida en cada paso (menos el primero)
        self.assertIsNone(abrir.espera_grabada)
        self.assertTrue(all(p.espera_grabada is not None for p in flujo.pasos[1:]))
        # sugerencias de fecha dinámica
        sugerencias = [d["plantilla"] for t, d in eventos if t == "sugerencia"]
        self.assertEqual(sugerencias, ["{inicio_mes:%Y-%m-%d}", "{hoy:%Y-%m-%d}"])

        # --- 1) re-ejecución con las fechas directas (los clics del calendario se saltan)
        escribir_ini.valor, escribir_fin.valor = sugerencias
        flujo.pasos.append(Paso("esperar_texto", texto="Rango: 2026-03-01 a 2026-03-15"))
        flujo2 = Flujo.desde_json(flujo.a_json())              # ida y vuelta por JSON
        self.opciones_rapidas(flujo2, timeout_paso=15)
        res = self.ejecutar(flujo2, nombre_perfil="perfil_a")
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        self.assertEqual(res.desactivados, 8)
        log = self.leer_log(res)
        self.assertIn("solo lectura", log)

        # --- 2) solo los clics (sin las fechas directas): los selectores nuevos encuentran el calendario correcto
        flujo3 = Flujo.desde_json(flujo2.a_json())
        for p in flujo3.pasos:
            if p.tipo == "clic":
                p.desactivado = False
        flujo3.pasos[5].desactivado = flujo3.pasos[10].desactivado = True
        res3 = self.ejecutar(flujo3, nombre_perfil="perfil_b")
        self.assertTrue(res3.ok, res3.resumen() + "\n" + self.leer_log(res3))
        self.assertEqual(res3.desactivados, 2)

    def test_escribir_en_campo_de_solo_lectura_falla_con_claridad_si_la_pagina_lo_borra(self):
        f = Flujo(nombre="Solo lectura")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=3)
        f.pasos = [Paso("abrir_url", url=self.base + "fechas.html"),
                   Paso("escribir", selectores=["#f_ini"], valor="2020-05-05"),
                   Paso("clic", selectores=["#ver"]),
                   Paso("esperar_texto", texto="Rango: 2020-05-05")]
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen())          # se escribe con JavaScript aunque el campo sea readonly


class TestContrasenas(BaseGrabacion):
    def test_clave_con_ojito_nunca_se_guarda_en_claro(self):
        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#pw")
            pg.click("#ojo")                     # el campo pasa a type=text ANTES de escribir
            self.assertEqual(pg.get_attribute("#pw", "type"), "text")
            pg.fill("#pw", CLAVE)
            pg.fill("#otra", CLAVE + "-2")       # nunca fue type=password, pero su placeholder dice «contraseña»
            pg.click("#entrar")
            pg.wait_for_timeout(500)

        flujo, eventos = self.grabar(self.base + "clave.html", conducir)
        escribir = [p for p in flujo.pasos if p.tipo == "escribir"]
        self.assertEqual([p.valor for p in escribir], ["{secreto:127.0.0.1:pw}", "{secreto:127.0.0.1:otra}"])
        self.assertEqual(secretos.obtener("127.0.0.1:pw"), CLAVE)
        self.assertEqual(secretos.obtener("127.0.0.1:otra"), CLAVE + "-2")
        blob = flujo.a_json() + repr(eventos) + "".join(p.descripcion() + p.detalle() for p in flujo.pasos)
        self.assertNotIn(CLAVE, blob)

        # se re-ejecuta (otro almacén de contraseñas) y la contraseña tampoco llega al registro
        secretos.usar_almacen(secretos.AlmacenMemoria())
        secretos.guardar("127.0.0.1:pw", CLAVE)
        secretos.guardar("127.0.0.1:otra", CLAVE + "-2")
        self.opciones_rapidas(flujo, timeout_paso=10)
        flujo.pasos.append(Paso("esperar_texto", texto="Bienvenido"))
        mensajes = []
        res = self.ejecutar(flujo, nombre_perfil="perfil_pw", log=mensajes.append)
        self.assertTrue(res.ok, res.resumen())
        self.assertNotIn(CLAVE, self.leer_log(res))
        self.assertNotIn(CLAVE, "\n".join(mensajes))

    def test_contrasena_literal_se_enmascara_en_el_registro(self):
        f = Flujo(nombre="Literal")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=10)
        f.pasos = [Paso("abrir_url", url=self.base + "index.html"),
                   Paso("escribir", selectores=["#usuario"], valor="demo"),
                   Paso("escribir", selectores=["#clave"], valor=CLAVE),             # en claro (flujo antiguo)
                   Paso("clic", selectores=['role=button[name="Entrar"]']),
                   Paso("esperar_elemento", selectores=["#generar"])]
        mensajes = []
        res = self.ejecutar(f, log=mensajes.append)
        self.assertTrue(res.ok, res.resumen())          # el valor sigue usándose para entrar…
        log = self.leer_log(res)
        self.assertNotIn(CLAVE, log)                    # …pero no queda en el registro
        self.assertNotIn(CLAVE, "\n".join(mensajes))
        self.assertIn("********", log)
        self.assertIn("demo", log)                      # el usuario sí se ve


class TestVariasDescargas(BaseGrabacion):
    def test_dos_descargas_en_una_grabacion(self):
        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#d1")
            pg.click("#d1")
            pg.wait_for_timeout(1200)
            pg.click("#d2")
            pg.wait_for_timeout(1200)

        flujo, _ = self.grabar(self.base + "multiples.html", conducir)
        self.assertEqual([p.tipo for p in flujo.pasos], ["abrir_url", "descargar", "descargar"])
        d1, d2 = flujo.pasos[1:]
        # v3.5: varias descargas = nombre del reporte + el de la web ({nombre}) + la fecha (no se pisan)
        self.assertEqual((d1.selectores[0], d1.nombre), ("#d1", "{reporte} - {nombre} {hoy:%Y-%m-%d}{ext}"))
        self.assertEqual((d2.selectores[0], d2.nombre), ("#d2", "{reporte} - {nombre} {hoy:%Y-%m-%d}{ext}"))
        # durante la grabación las descargas se completan y quedan en la carpeta de la grabación
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, "grabacion"))), ["clientes.csv", "ventas.csv"])
        # se renombran y se re-ejecutan las dos
        d1.nombre = "Ventas_{hoy:%Y-%m-%d}{ext}"
        d2.nombre = "Clientes_{hoy:%Y-%m-%d}{ext}"
        self.opciones_rapidas(flujo, timeout_paso=15)
        res = self.ejecutar(flujo, nombre_perfil="perfil_dos")
        self.assertTrue(res.ok, res.resumen())
        self.assertEqual([os.path.basename(a) for a in res.archivos], ["Ventas_2026-03-15.csv", "Clientes_2026-03-15.csv"])
        self.assertEqual(sorted(os.listdir(self.descargas)), ["Clientes_2026-03-15.csv", "Ventas_2026-03-15.csv"])
        with open(os.path.join(self.descargas, "Ventas_2026-03-15.csv"), encoding="utf-8") as fh:
            self.assertIn("ventas,100", fh.read())
        with open(os.path.join(self.descargas, "Clientes_2026-03-15.csv"), encoding="utf-8") as fh:
            self.assertIn("clientes,7", fh.read())


class TestLotePorLineaDeComandos(BaseIntegracion):
    def setUp(self):
        super().setUp()
        self.carpeta = os.path.join(self.tmp, "flujos")
        os.makedirs(self.carpeta)

    def guardar(self, nombre, pasos):
        f = Flujo(nombre=nombre, url=self.base + "index.html")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=3)
        f.pasos = pasos
        ruta = os.path.join(self.carpeta, nombre + ".json")
        f.guardar(ruta)
        return ruta

    def correr(self, *argumentos):
        import bot
        salida = io.StringIO()
        base = ["--sin-ventana", "--oculto", "--registros", self.registros, "--descargas", self.descargas,
                "--perfil", os.path.join(self.tmp, "perfiles"), "--carpeta-flujos", self.carpeta,
                "--db", os.path.join(self.tmp, "bot.db")]
        with contextlib.redirect_stdout(salida):
            codigo = bot.principal(list(argumentos) + base)
        return codigo, salida.getvalue()

    def test_todos_continua_tras_un_fallo_y_devuelve_1(self):
        # v2.2: los .json de la carpeta antigua se importan a la base de datos y --todos ejecuta los guardados
        from webbot.almacen import Almacen
        self.guardar("Bien", [Paso("abrir_url", url=self.base + "index.html"),
                              Paso("escribir", selectores=["#usuario"], valor="demo")])
        self.guardar("Mal", [Paso("abrir_url", url=self.base + "index.html"),
                             Paso("clic", selectores=["#no-existe"], timeout=1)])
        self.guardar("Zeta", [Paso("abrir_url", url=self.base + "index.html"),
                              Paso("escribir", selectores=["#usuario"], valor="otro")])
        codigo, salida = self.correr("--todos")
        self.assertEqual(codigo, 1, salida)
        self.assertIn("Se importaron 3 reportes", salida)
        self.assertIn("Resumen del lote: 2 de 3 reportes bien, 1 fallaron", salida)
        self.assertIn("BIEN    Bien", salida)
        self.assertIn("FALLÓ   Mal", salida)
        self.assertIn("BIEN    Zeta", salida)              # siguió con el siguiente tras el fallo
        # el historial de la base de datos recuerda el último resultado de cada uno
        alm = Almacen(os.path.join(self.tmp, "bot.db"))
        try:
            ultimos = {r["nombre"]: r["resultado"] for r in alm.listar()}
        finally:
            alm.cerrar()
        self.assertEqual(ultimos, {"Bien": "ok", "Mal": "error", "Zeta": "ok"})
        self.assertFalse([n for n in os.listdir(self.carpeta) if n.endswith(".json")])     # se movieron a _importados
        self.assertEqual(sorted(os.listdir(os.path.join(self.carpeta, "_importados"))), ["Bien.json", "Mal.json", "Zeta.json"])
        self.assertEqual(len([n for n in os.listdir(self.registros) if n.endswith(".png")]), 1)

    def test_varios_flujo_todos_bien_devuelve_0(self):
        self.guardar("Uno", [Paso("abrir_url", url=self.base + "index.html")])
        self.guardar("Dos", [Paso("abrir_url", url=self.base + "index.html")])
        codigo, salida = self.correr("--flujo", "Uno", "--flujo", "Dos.json")
        self.assertEqual(codigo, 0, salida)
        self.assertIn("2 de 2 reportes bien", salida)

    def test_flujo_inexistente_devuelve_2(self):
        codigo, salida = self.correr("--flujo", "NoExiste")
        self.assertEqual(codigo, 2)


class TestGuardarPagina(BaseGrabacion):
    def flujo(self, *pasos):
        f = Flujo(nombre="Pagina")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=10)
        f.pasos = [Paso("abrir_url", url=self.base + "abrir_reporte.html"), Paso("clic", selectores=["#abrir"])] + list(pasos)
        return f

    def test_csv_html_y_pdf_de_un_informe_en_otra_pestana(self):
        f = self.flujo(
            Paso("guardar_pagina", formato="csv", nombre="Comisiones_{hoy:%Y-%m-%d}", pagina=1),
            Paso("guardar_pagina", formato="html", nombre="Informe_{hoy:%Y-%m-%d}", pagina=1),
            Paso("guardar_pagina", formato="pdf", nombre="Informe_{hoy:%Y-%m-%d}", pagina=1, carpeta="pdfs"))
        res = self.ejecutar(f)
        self.assertTrue(res.ok, res.resumen())
        csv_ruta = os.path.join(self.descargas, "Comisiones_2026-03-15.csv")
        self.assertIn(csv_ruta, res.archivos)
        with open(csv_ruta, encoding="utf-8-sig", newline="") as fh:
            filas = list(csv.reader(fh))
        self.assertEqual(filas[0], ["Agente", "Producto", "Importe"])             # la tabla más grande, no la de «Total»
        self.assertEqual(len(filas), 4)
        self.assertEqual(filas[1], ["María", "Plan Ñandú", "1500.50"])
        self.assertEqual(filas[2][1], "Plan, básico")
        self.assertEqual(filas[3][1], 'Plan "premium"')
        with open(os.path.join(self.descargas, "Informe_2026-03-15.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("Reporte de comisiones", html)
        self.assertIn("<base href=", html)
        with open(os.path.join(self.descargas, "pdfs", "Informe_2026-03-15.pdf"), "rb") as fh:
            self.assertEqual(fh.read(5), b"%PDF-")

    def test_pdf_con_navegador_auxiliar_como_en_modo_visible(self):
        f = self.flujo(Paso("guardar_pagina", formato="pdf", nombre="Aux", pagina=1))
        res = self.ejecutar(f, forzar_pdf_auxiliar=True)
        self.assertTrue(res.ok, res.resumen())
        with open(os.path.join(self.descargas, "Aux.pdf"), "rb") as fh:
            self.assertEqual(fh.read(5), b"%PDF-")
        self.assertIn("auxiliar", self.leer_log(res))

    def test_csv_sin_tablas_falla_con_claridad(self):
        f = Flujo(nombre="Sin tabla")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=2, timeout_descarga=2)
        f.pasos = [Paso("abrir_url", url=self.base + "index.html"), Paso("guardar_pagina", formato="csv", nombre="x")]
        res = self.ejecutar(f)
        self.assertFalse(res.ok)
        self.assertIn("ninguna tabla", res.error)

    def test_boton_de_la_barra_graba_el_paso(self):
        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#abrir")
            with g.contexto.expect_page() as nueva:
                pg.click("#abrir")
            informe = nueva.value
            informe.wait_for_selector("#detalle")
            informe.get_by_role("button", name="Guardar esta página").click()
            informe.locator("#__bot_host__ select").select_option("csv")
            informe.get_by_role("button", name="Añadir paso").click()
            informe.wait_for_timeout(500)

        flujo, _ = self.grabar(self.base + "abrir_reporte.html", conducir)
        ultimo = flujo.pasos[-1]
        self.assertEqual((ultimo.tipo, ultimo.formato, ultimo.pagina), ("guardar_pagina", "csv", 1))
        self.assertEqual(ultimo.nombre, "Reporte_de_comisiones_{hoy:%Y-%m-%d}")
        self.assertEqual([p.tipo for p in flujo.pasos[:-1]], ["abrir_url", "clic"])      # la barra no genera pasos propios
        self.opciones_rapidas(flujo, timeout_paso=10)
        res = self.ejecutar(flujo, nombre_perfil="perfil_bp")
        self.assertTrue(res.ok, res.resumen())
        self.assertTrue(os.path.isfile(os.path.join(self.descargas, "Reporte_de_comisiones_2026-03-15.csv")))


if __name__ == "__main__":
    unittest.main()
