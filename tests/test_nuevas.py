"""Pruebas de la versión 2.1 que no necesitan navegador: pasos nuevos, esperas aprendidas,
contraseñas en claro, fechas propuestas, lista/historial/lote de reportes y programación por lotes."""

import datetime
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import bot  # noqa: E402
from webbot import flujo as fl  # noqa: E402
from webbot import lote, plantillas, programador, secretos  # noqa: E402
from webbot.ejecutor import ResultadoEjecucion  # noqa: E402
from webbot.flujo import ErrorFlujo, Flujo, Paso  # noqa: E402

HOY = datetime.date(2026, 3, 15)


class TestPasosNuevos(unittest.TestCase):
    def test_ida_y_vuelta_de_los_campos_nuevos(self):
        f = Flujo(nombre="N")
        f.pasos = [
            Paso("clic", selectores=["#a"], desactivado=True, espera_grabada=12.5),
            Paso("escribir", selectores=["#f"], valor="2026-03-01", fecha_directa=True),
            Paso("guardar_pagina", formato="csv", nombre="T_{hoy:%Y-%m-%d}", carpeta="x", pagina=1),
        ]
        g = Flujo.desde_json(f.a_json())
        self.assertEqual(g.a_dict(), f.a_dict())
        self.assertTrue(g.pasos[0].desactivado)
        self.assertEqual(g.pasos[0].espera_grabada, 12.5)
        self.assertTrue(g.pasos[1].fecha_directa)
        self.assertEqual((g.pasos[2].formato, g.pasos[2].pagina), ("csv", 1))
        # Solo se guarda lo que no es el valor por defecto
        self.assertEqual(Paso("clic", selectores=["#a"]).a_dict(), {"tipo": "clic", "selectores": ["#a"]})

    def test_flujo_antiguo_sin_campos_nuevos_se_carga(self):
        antiguo = {"version": 2, "nombre": "Viejo", "url": "http://x/", "opciones": {"timeout_paso": 30},
                   "pasos": [{"tipo": "abrir_url", "url": "http://x/"},
                             {"tipo": "clic", "selectores": ["#a"], "timeout": 5},
                             {"tipo": "descargar", "selectores": ["#d"], "nombre": "a{ext}"}]}
        f = Flujo.desde_json(json.dumps(antiguo))
        self.assertEqual(len(f.pasos), 3)
        self.assertFalse(any(p.desactivado or p.fecha_directa for p in f.pasos))
        self.assertIsNone(f.pasos[1].espera_grabada)
        self.assertEqual(f.opcion("timeout_paso"), 30)               # lo guardado se respeta
        self.assertEqual(f.opcion("pausa_entre_pasos"), 0.3)         # lo nuevo toma su valor por defecto
        self.assertEqual(f.opcion("timeout_descarga"), 600)
        self.assertEqual(f.problemas(), [])

    def test_valores_por_defecto(self):
        f = Flujo()
        self.assertEqual(f.opcion("timeout_paso"), 60)
        self.assertEqual(f.opcion("timeout_descarga"), 600)
        self.assertEqual(f.opcion("pausa_entre_pasos"), 0.3)

    def test_guardar_pagina_validacion_y_descripcion(self):
        p = Paso("guardar_pagina", formato="pdf", nombre="Inf_{hoy:%Y-%m-%d}")
        self.assertEqual(p.problemas(), [])
        self.assertIn("PDF", p.detalle())
        self.assertIn("Guardar la página", p.descripcion())
        self.assertTrue(Paso("guardar_pagina", formato="xls").problemas())
        self.assertTrue(Paso("guardar_pagina", formato="pdf", nombre="{mal").problemas())

    def test_desactivado_se_nota_en_la_descripcion(self):
        self.assertIn("desactivado", Paso("clic", selectores=["#a"], desactivado=True).descripcion())

    def test_selector_con_texto_acotado_se_describe_bien(self):
        self.assertEqual(fl.describir_selector('.mi-dp-anios span:text-is("2020")'), "«2020»")


class TestTimeoutEfectivo(unittest.TestCase):
    OP = {"timeout_paso": 60, "timeout_descarga": 600}

    def test_explicito_gana(self):
        self.assertEqual(Paso("clic", timeout=7, espera_grabada=100).timeout_efectivo(self.OP), 7)

    def test_sin_espera_aprendida_es_timeout_paso(self):
        self.assertEqual(Paso("clic").timeout_efectivo(self.OP), 60)

    def test_espera_aprendida_por_tres_mas_treinta(self):
        self.assertEqual(Paso("clic", espera_grabada=40).timeout_efectivo(self.OP), 150)
        self.assertEqual(Paso("clic", espera_grabada=2).timeout_efectivo(self.OP), 60)    # max con timeout_paso

    def test_tope_en_timeout_descarga(self):
        self.assertEqual(Paso("clic", espera_grabada=1000).timeout_efectivo(self.OP), 600)
        self.assertEqual(Paso("clic", espera_grabada=3).timeout_efectivo({"timeout_paso": 2, "timeout_descarga": 10}), 10)

    def test_opcional_espera_poco(self):
        self.assertEqual(Paso("clic", opcional=True, espera_grabada=500).timeout_efectivo(self.OP), fl.TIMEOUT_OPCIONAL)

    def test_descargas_usan_el_timeout_largo(self):
        self.assertEqual(Paso("descargar").timeout_descarga_efectivo(self.OP), 600)
        self.assertEqual(Paso("descargar", timeout=90).timeout_descarga_efectivo(self.OP), 90)

    def test_el_flujo_usa_sus_opciones(self):
        f = Flujo()
        f.opciones.update(timeout_paso=2, timeout_descarga=10)
        self.assertEqual(f.timeout_de(Paso("clic", espera_grabada=3)), 10)


class TestContrasenasEnClaro(unittest.TestCase):
    def setUp(self):
        self.almacen = secretos.AlmacenMemoria()
        secretos.usar_almacen(self.almacen)
        self.addCleanup(secretos.usar_almacen, None)

    def test_detecta_campos_de_contrasena(self):
        for p in (Paso("escribir", selectores=["#clave"], valor="x"), Paso("escribir", selectores=["input[name=\"pwd\"]"], valor="x"),
                  Paso("escribir", selectores=["#a"], objetivo="Contraseña", valor="x"),
                  Paso("escribir", selectores=["#password"], valor="x")):
            self.assertTrue(p.parece_contrasena(), p.selectores)
        self.assertFalse(Paso("escribir", selectores=["#usuario"], objetivo="Usuario", valor="x").parece_contrasena())
        self.assertFalse(Paso("clic", selectores=["#clave"]).parece_contrasena())

    def test_la_lista_no_muestra_la_contrasena_literal(self):
        p = Paso("escribir", selectores=["#clave"], valor="MiSecreta99")
        self.assertTrue(p.valor_literal_en_campo_contrasena())
        self.assertNotIn("MiSecreta99", p.detalle())
        self.assertNotIn("MiSecreta99", p.descripcion())
        self.assertFalse(Paso("escribir", selectores=["#clave"], valor="{secreto:a:b}").valor_literal_en_campo_contrasena())

    def test_convertir_en_secreto(self):
        p = Paso("escribir", selectores=["#clave"], valor="MiSecreta{{99}}")      # llaves escapadas como las guarda el grabador
        convertir = fl.convertir_en_secreto
        convertir(p, "portal:clave", secretos.guardar)
        self.assertEqual(p.valor, "{secreto:portal:clave}")
        self.assertEqual(secretos.obtener("portal:clave"), "MiSecreta{99}")
        self.assertNotIn("MiSecreta", json.dumps(p.a_dict()))
        with self.assertRaises(ErrorFlujo):
            convertir(p, "otra", secretos.guardar)                    # ya es un secreto
        with self.assertRaises(ErrorFlujo):
            convertir(Paso("clic", selectores=["#a"]), "x", secretos.guardar)
        with self.assertRaises(ErrorFlujo):
            convertir(Paso("escribir", selectores=["#a"], valor=""), "x", secretos.guardar)
        with self.assertRaises(ErrorFlujo):
            convertir(Paso("escribir", selectores=["#a"], valor="v"), "mal}nombre", secretos.guardar)

    def test_nombre_sugerido(self):
        p = Paso("escribir", selectores=["#txtPassword", "input:nth-of-type(2)"], valor="x")
        self.assertEqual(fl.nombre_secreto_sugerido(p, "https://portal.ejemplo.com/login"), "portal.ejemplo.com:txtPassword")
        p2 = Paso("escribir", selectores=["input:nth-of-type(2)"], objetivo="Contraseña", valor="x")
        self.assertEqual(fl.nombre_secreto_sugerido(p2, ""), "sitio:contraseña")


class TestFechasPropuestas(unittest.TestCase):
    def test_inicio_y_fin_de_mes_y_mes_anterior(self):
        pr = plantillas.proponer_fecha_dinamica
        self.assertEqual(pr("2026-03-01", HOY), "{inicio_mes:%Y-%m-%d}")
        self.assertEqual(pr("31/03/2026", HOY), "{fin_mes}")
        self.assertEqual(pr("2026-02-01", HOY), "{inicio_mes_anterior:%Y-%m-%d}")
        self.assertEqual(pr("28/02/2026", HOY), "{fin_mes_anterior}")
        self.assertEqual(pr("2026-03-15", HOY), "{hoy:%Y-%m-%d}")
        self.assertEqual(pr("14/03/2026", HOY), "{ayer}")
        self.assertIsNone(pr("2026-03-02", HOY))

    def test_ida_y_vuelta(self):
        for texto in ("2026-03-01", "31/03/2026", "2026-02-01", "28/02/2026", "20260315"):
            plantilla = plantillas.proponer_fecha_dinamica(texto, HOY)
            self.assertIsNotNone(plantilla, texto)
            self.assertEqual(plantillas.renderizar(plantilla, hoy=HOY), texto)

    def test_hoy_gana_si_coincide_con_inicio_de_mes(self):
        primero = datetime.date(2026, 3, 1)
        self.assertEqual(plantillas.proponer_fecha_dinamica("2026-03-01", primero), "{hoy:%Y-%m-%d}")


class TestListaHistorialYLote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "flujos")
        os.makedirs(self.dir)

    def guardar(self, nombre, url="http://ejemplo/"):
        f = Flujo(nombre=nombre, url=url)
        f.pasos = [Paso("abrir_url", url=url)]
        ruta = os.path.join(self.dir, fl.slug(nombre) + ".json")
        f.guardar(ruta)
        return ruta

    def test_listar_ignora_historial_papelera_y_marca_los_rotos(self):
        a = self.guardar("Ventas")
        self.guardar("Clientes", "http://otra/")
        with open(os.path.join(self.dir, "roto.json"), "w") as fh:
            fh.write("{no es json")
        os.makedirs(os.path.join(self.dir, "_papelera"))
        lote.Historial(self.dir).registrar(a, "ok")
        lista = lote.listar_flujos(self.dir)
        self.assertEqual([i["archivo"] for i in lista], ["Clientes.json", "roto.json", "Ventas.json"])
        self.assertEqual(lista[0]["url"], "http://otra/")
        self.assertTrue(lista[1]["error"])
        self.assertEqual(lista[2]["nombre"], "Ventas")

    def test_historial(self):
        a = self.guardar("Ventas")
        h = lote.Historial(self.dir)
        self.assertIsNone(h.obtener(a))
        h.registrar(a, "error", "Error en el paso 3", archivos=[r"C:\x\a.csv"], cuando=datetime.datetime(2026, 3, 15, 8, 30, 5))
        e = lote.Historial(self.dir).obtener(a)                  # se persiste en disco
        self.assertEqual((e["ultima"], e["resultado"], e["archivos"]), ("2026-03-15 08:30:05", "error", ["a.csv"]))
        self.assertEqual(lote.texto_resultado(e), "Falló")
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "_historial.json")))
        h.olvidar(a)
        self.assertIsNone(h.obtener(a))

    def test_historial_ignora_flujos_de_otras_carpetas(self):
        fuera = os.path.join(self.tmp.name, "otro.json")
        h = lote.Historial(self.dir)
        res = ResultadoEjecucion()
        res.ok = True
        h.registrar_resultado(fuera, res)
        self.assertFalse(os.path.exists(h.ruta))

    def test_duplicar_y_papelera(self):
        a = self.guardar("Ventas")
        b = lote.duplicar_flujo(a)
        c = lote.duplicar_flujo(a)
        self.assertEqual([os.path.basename(x) for x in (b, c)], ["Ventas (copia).json", "Ventas (copia 2).json"])
        self.assertEqual(Flujo.cargar(b).nombre, "Ventas (copia)")
        destino = lote.mover_a_papelera(b)
        self.assertFalse(os.path.exists(b))
        self.assertTrue(os.path.isfile(destino))
        self.assertNotIn("Ventas (copia).json", [i["archivo"] for i in lote.listar_flujos(self.dir)])

    def test_lote_sigue_tras_un_fallo_y_resume(self):
        a, b, c = self.guardar("Uno"), self.guardar("Dos"), self.guardar("Tres")
        h = lote.Historial(self.dir)
        llamados = []

        class FalsoEjecutor:
            def __init__(self, flujo, **kw):
                self.flujo = flujo
                llamados.append(flujo.nombre)

            def ejecutar(self):
                r = ResultadoEjecucion()
                if self.flujo.nombre == "Dos":
                    r.ok, r.paso_fallido, r.error = False, 2, "no apareció"
                else:
                    r.ok = True
                    r.archivos = [r"C:\d\%s.csv" % self.flujo.nombre]
                return r

        avisos = []
        res = lote.ejecutar_lote([a, b, c], carpeta_perfiles=self.tmp.name, carpeta_registros=self.tmp.name,
                                 historial=h, fabrica_ejecutor=FalsoEjecutor,
                                 aviso_lote=lambda n, t, item, fase: avisos.append((n, t, fase)))
        self.assertEqual(llamados, ["Uno", "Dos", "Tres"])
        self.assertFalse(res.ok)
        self.assertEqual([i.estado for i in res.items], ["ok", "error", "ok"])
        self.assertEqual(len(res.correctos), 2)
        self.assertEqual(len(res.archivos), 2)
        texto = res.resumen()
        self.assertIn("2 de 3", texto)
        self.assertIn("FALLÓ   Dos", texto)
        self.assertIn("no apareció", texto)
        self.assertEqual(avisos[0], (1, 3, "inicio"))
        self.assertEqual(h.obtener(b)["resultado"], "error")
        self.assertEqual(h.obtener(a)["resultado"], "ok")

    def test_lote_con_flujo_ilegible_y_detener(self):
        a = self.guardar("Uno")
        roto = os.path.join(self.dir, "roto.json")
        with open(roto, "w") as fh:
            fh.write("[]")
        parar = threading.Event()

        class FalsoEjecutor:
            def __init__(self, flujo, **kw):
                pass

            def ejecutar(self):
                parar.set()                     # el usuario pulsa «Detener» durante el primero
                r = ResultadoEjecucion()
                r.detenido = True
                return r

        res = lote.ejecutar_lote([a, roto, a], carpeta_perfiles=self.tmp.name, carpeta_registros=self.tmp.name,
                                 fabrica_ejecutor=FalsoEjecutor, detener=parar)
        self.assertEqual([i.estado for i in res.items], ["detenido", "no_ejecutado", "no_ejecutado"])
        self.assertTrue(res.detenido)
        self.assertIn("SIN EJECUTAR", res.resumen())
        # y un flujo ilegible falla sin tumbar el lote
        res2 = lote.ejecutar_lote([roto], carpeta_perfiles=self.tmp.name, carpeta_registros=self.tmp.name,
                                  fabrica_ejecutor=FalsoEjecutor)
        self.assertEqual(res2.items[0].estado, "error")
        self.assertIn("No se pudo abrir", res2.items[0].mensaje)


class TestProgramadorLotes(unittest.TestCase):
    BOT = r"C:\Bots\bot.py"
    PY = r"C:\Python\pythonw.exe"

    def test_todos(self):
        cmd = programador.construir_comando_crear("Todos", self.BOT, None, "06:00", python=self.PY, todos=True)
        tr = cmd[cmd.index("/TR") + 1]
        self.assertEqual(tr, '"C:\\Python\\pythonw.exe" "C:\\Bots\\bot.py" --todos --sin-ventana --oculto')
        self.assertEqual(cmd[cmd.index("/TN") + 1], "BotWeb\\Todos")

    def test_varios_flujos_seleccionados(self):
        cmd = programador.construir_comando_crear("Lote", self.BOT, [r"D:\x\a.json", r"D:\x\b.json"], "06:00", python=self.PY,
                                                  variables={"c": "1"})
        tr = cmd[cmd.index("/TR") + 1]
        self.assertEqual(tr.count("--flujo"), 2)
        self.assertIn(r'--flujo "D:\x\a.json" --flujo "D:\x\b.json"', tr)
        self.assertTrue(tr.endswith('--sin-ventana --oculto --var "c=1"'))

    def test_flujos_de_la_carpeta_del_proyecto_van_con_nombre_corto(self):
        from webbot import RAIZ as raiz_proyecto
        a = os.path.join(raiz_proyecto, "flujos", "Ventas diarias.json")
        b = os.path.join(raiz_proyecto, "flujos", "Clientes.json")
        tr = programador.comando_bot(self.BOT, [a, b], python=self.PY)
        self.assertIn('--flujo "Ventas diarias" --flujo "Clientes"', tr)

    def test_un_solo_flujo_no_cambia(self):
        tr = programador.comando_bot(self.BOT, r"C:\Bots\flujos\ventas.json", python=self.PY)
        self.assertEqual(tr, '"C:\\Python\\pythonw.exe" "C:\\Bots\\bot.py" --flujo "C:\\Bots\\flujos\\ventas.json" --sin-ventana --oculto')

    def test_sin_flujos_es_un_error(self):
        with self.assertRaises(programador.ErrorProgramador):
            programador.construir_comando_crear("X", self.BOT, [], "06:00", python=self.PY)
        with self.assertRaises(programador.ErrorProgramador):
            programador.construir_comando_crear("X", self.BOT, None, "06:00", python=self.PY)

    def test_nunca_se_llama_a_schtasks_sin_confirmar(self):
        llamadas = []
        cmd = programador.construir_comando_crear("Todos", self.BOT, None, "06:00", python=self.PY, todos=True)
        with self.assertRaises(programador.ErrorProgramador):
            programador.crear(cmd, confirmado=False, ejecutor=lambda c: llamadas.append(c) or (0, ""))
        self.assertEqual(llamadas, [])


class TestLineaDeComandosYVentana(unittest.TestCase):
    def test_flujo_repetible_y_todos(self):
        a = bot.analizar_argumentos(["--flujo", "a", "--flujo", "b", "--todos", "--carpeta-flujos", "x"])
        self.assertEqual(a.flujo, ["a", "b"])
        self.assertTrue(a.todos)
        self.assertEqual(a.carpeta_flujos, "x")
        self.assertIsNone(bot.analizar_argumentos([]).flujo)

    def test_sin_flujos_codigo_2(self):
        self.assertEqual(bot.principal(["--sin-ventana"]), 2)

    def test_smoke_construye_la_ventana_con_el_panel_de_reportes(self):
        r = subprocess.run([sys.executable, os.path.join(RAIZ, "bot.py"), "--smoke"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90, cwd=RAIZ)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)
        self.assertIn("panel Reportes", r.stdout)


if __name__ == "__main__":
    unittest.main()
