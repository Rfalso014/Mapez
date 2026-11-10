"""Pruebas de integración de la versión 3.0 (navegador oculto + sitio local de prueba `portal.html`, tipo Vuetify):

- §1 Esperas de carga: el menú abierto de una lista (v-overlay--active + v-menu, que se queda en el DOM) no es una
  rueda de carga; la rueda de verdad (v-progress-circular) sí se espera.
- §2 Accesos: lo escrito al grabar se guarda solo en Accesos; contraseña rechazada sin nadie delante → marcada (no se
  vuelve a enviar en la siguiente ejecución), aviso en la aplicación y notificación de Windows (falsa); con la ventana
  → cuadro «La contraseña falló» y, con la nueva, se guarda y se sigue.
- §3 Paso «Elegir opción» (fija, más reciente en una lista virtual, lista nativa) y «Repetir por días»; vigilancia:
  la primera revisión es la referencia, un corte nuevo (estado del servidor) se avisa y se descarga UNA vez.
- §4 Mapear la página: pestañas, listas propias (con opciones dependientes «reporte → corte»), lista nativa, botón
  «Generar»; los pasos generados se ejecutan y descargan el corte más reciente.
Nunca usan el ratón ni el teclado reales, ni el Administrador de credenciales ni la base de datos reales.
"""

import datetime
import json
import os
import re
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from servidor_prueba import cortes_portal  # noqa: E402
from test_integracion import CLAVE, BaseIntegracion  # noqa: E402
from test_integracion_v21 import BaseGrabacion  # noqa: E402
from test_integracion_v23 import SECRETO, PedirFalso, paso_login  # noqa: E402
from webbot import accesos as mod_accesos  # noqa: E402
from webbot import avisos, mapeador, secretos, vigilancia  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.ejecutor import Ejecutor  # noqa: E402
from servidor_prueba import CORTE_NUEVO  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

CAMPO = '.v-input[data-campo="%s"] .v-field'


def duraciones(log):
    """[(número de paso, descripción, segundos)] a partir del registro."""
    res = []
    actual = None
    for linea in log.splitlines():
        m = re.search(r"Paso (\d+)/\d+: (.*)$", linea)
        if m:
            actual = (int(m.group(1)), m.group(2))
            continue
        m = re.search(r"    OK \(([\d.]+) s\)", linea)
        if m and actual:
            res.append((actual[0], actual[1], float(m.group(1))))
    return res


class TestMenusNoSonCargas(BaseIntegracion):
    def test_listas_de_vuetify_rapidas_y_rueda_esperada(self):
        url = self.base + "portal.html?ms=2000"
        f = Flujo(nombre="Portal menús", url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=8)
        f.pasos = [Paso("abrir_url", url=url),
                   Paso("clic", selectores=[CAMPO % "reporte"], objetivo="div"),
                   Paso("clic", selectores=['role=option[name="Detalles Ventas Mayorista"]']),
                   Paso("clic", selectores=[CAMPO % "corte"], objetivo="div"),
                   Paso("clic", selectores=['role=option[name="%s"]' % cortes_portal("Detalles Ventas Mayorista")[1]]),
                   Paso("clic", selectores=["#generar"]),
                   # solo existe tras la rueda (2 s): con 1 s de tiempo, pasa solo si el bot esperó a la rueda
                   Paso("esperar_texto", texto="Reporte generado", timeout=1)]
        res = self.ejecutar(f)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        tiempos = {n: s for n, _d, s in duraciones(log)}
        for n in (2, 3, 4, 5):
            self.assertLess(tiempos[n], 3.0, "el paso %d tardó %.1f s\n%s" % (n, tiempos[n], log))
        self.assertNotIn("v-menu", log)
        generar = log.split("Paso 6/7")[1].split("Paso 7/7")[0]
        self.assertRegex(generar, r"tardó [\d.]+ s en terminar de cargar: indicador .*v-overlay")
        self.assertGreaterEqual(tiempos[6], 1.5, log)
        self.assertEqual(len(res.archivos), 0)       # sin paso «Descargar», la descarga automática no se guarda


class TestAccesos(BaseIntegracion):
    def setUp(self):
        super().setUp()
        self.toasts = []
        avisos.usar_notificador(lambda titulo, texto: self.toasts.append((titulo, texto)))
        self.addCleanup(avisos.usar_notificador, None)
        self.db = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.db.cerrar)

    def flujo(self):
        f = Flujo(nombre="Login", url=self.base + "app.html")
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=10)
        f.pasos = [Paso("abrir_url", url=self.base + "app.html"), paso_login(), Paso("clic", selectores=["#accion"]),
                   Paso("esperar_texto", texto="hecha")]
        return f

    def test_rechazada_sin_ventana_avisa_y_no_reintenta_la_misma(self):
        secretos.guardar(SECRETO, "vieja")
        res = self.ejecutar(self.flujo(), accesos=self.db, nombre_perfil="p1")
        self.assertFalse(res.ok)
        self.assertIn("rechazó la contraseña guardada", res.error)
        self.assertIsNotNone(secretos.rechazada(SECRETO))
        self.assertIsNotNone(self.db.estado_clave(SECRETO)["rechazada"])
        notis = self.db.notificaciones()
        self.assertEqual([n["titulo"] for n in notis], [mod_accesos.TITULO_CLAVE_CAMBIO % "127.0.0.1"])
        self.assertEqual(notis[0]["datos"]["host"], "127.0.0.1")
        self.assertEqual(len(self.toasts), 1)
        self.assertIn("cambió", self.toasts[0][0])
        # siguiente ejecución desatendida: la misma contraseña NO se vuelve a enviar
        res2 = self.ejecutar(self.flujo(), accesos=self.db, nombre_perfil="p2")
        log2 = self.leer_log(res2)
        self.assertFalse(res2.ok)
        self.assertIn("ya fue rechazada", res2.error)
        self.assertNotIn("iniciando sesión", log2)
        self.assertEqual(len(self.db.notificaciones()), 1)                 # el aviso no se repite
        # el usuario cambia la contraseña: vuelve a funcionar y el aviso se da por leído
        secretos.guardar(SECRETO, CLAVE)
        res3 = self.ejecutar(self.flujo(), accesos=self.db, nombre_perfil="p3")
        self.assertTrue(res3.ok, res3.resumen() + "\n" + self.leer_log(res3))
        self.assertIsNone(secretos.rechazada(SECRETO))
        self.assertIsNone(self.db.estado_clave(SECRETO)["rechazada"])
        self.assertEqual(self.db.no_leidas(), 0)
        texto = self.leer_log(res) + log2 + json.dumps(self.db.notificaciones()) + repr(self.toasts)
        self.assertNotIn("vieja", texto)
        self.assertNotIn(CLAVE, texto)

    def test_con_ventana_cuadro_contrasena_fallida(self):
        secretos.guardar(SECRETO, "vieja")
        secretos.marcar_rechazada(SECRETO)                 # ya se rechazó en una ejecución anterior
        pedir = PedirFalso({"valores": {"clave": CLAVE}, "recordar": True})
        avisos_ui = []
        res = self.ejecutar(self.flujo(), accesos=self.db, pedir_acceso=pedir,
                            notificar=lambda tipo, datos: avisos_ui.append(tipo))
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        sol = pedir.solicitudes[0]
        self.assertEqual(sol["tipo"], "clave_fallida")
        self.assertEqual(sol["usuario"], "demo")
        self.assertEqual({c["clave"]: c["valor"] for c in sol["campos"]}["clave"], "")
        self.assertNotIn("intento 2", self.leer_log(res))           # la vieja no se envió: un solo intento
        self.assertEqual(secretos.obtener(SECRETO), CLAVE)
        self.assertIsNone(secretos.rechazada(SECRETO))
        self.assertIn("accesos_guardados", avisos_ui)
        self.assertEqual(self.toasts, [])


class TestGrabarGuardaAccesos(BaseGrabacion):
    def test_lo_escrito_al_grabar_queda_en_accesos(self):
        acc = mod_accesos.AccesosMemoria()

        def conducir(g):
            pg = g.paginas[0]
            pg.wait_for_selector("#usuario")
            pg.fill("#usuario", "demo")
            pg.fill("#clave", CLAVE)
            pg.click("#entrar")
            pg.wait_for_selector("#accion")
            pg.wait_for_timeout(300)

        flujo, eventos = self.grabar(self.base + "app.html", conducir, accesos=acc)
        self.assertIn("iniciar_sesion", [p.tipo for p in flujo.pasos])
        guardados = {a["clave"]: a for a in acc.accesos_de("127.0.0.1")}
        self.assertEqual(guardados["usuario"]["valor"], "demo")
        self.assertEqual(guardados["clave"]["secreto"], "127.0.0.1:clave")
        self.assertIsNone(guardados["clave"]["valor"])
        self.assertIn(("accesos", {"host": "127.0.0.1", "texto": "Se guardaron los datos de acceso de «127.0.0.1»"}),
                      eventos)
        self.assertNotIn(CLAVE, repr(acc.listar_accesos()) + repr(eventos))


class TestElegirOpcion(BaseIntegracion):
    def flujo(self, *pasos, ms=300):
        url = self.base + "portal.html?ms=%d" % ms
        f = Flujo(nombre="Portal", url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=8)
        f.pasos = [Paso("abrir_url", url=url)] + list(pasos)
        return f

    def test_fija_mas_reciente_en_lista_virtual_y_nativa(self):
        f = self.flujo(
            Paso("elegir_opcion", selectores=[CAMPO % "reporte"], objetivo="Seleccione reporte", valor="Detalles Ventas Mayorista"),
            Paso("elegir_opcion", selectores=[CAMPO % "corte"], objetivo="Elegir corte", estrategia="mas_reciente"),
            Paso("elegir_opcion", selectores=["#formato"], objetivo="Formato a Exportar", valor="CSV"),
            Paso("descargar", selectores=["#generar"], nombre="Corte_{nombre}{ext}"))
        res = self.ejecutar(f)
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        ultimo = cortes_portal("Detalles Ventas Mayorista")[-1]          # «44 - 2026 …», al final de una lista virtual
        self.assertIn("→ «%s» (mas_reciente; 12 opciones)" % ultimo, log)
        self.assertEqual([os.path.basename(a) for a in res.archivos], ["Corte_Portal_44.csv"])
        with open(res.archivos[0], encoding="utf-8") as fh:
            self.assertIn(ultimo, fh.read())
        tiempos = {n: s for n, _d, s in duraciones(log)}
        self.assertLess(max(tiempos[2], tiempos[3], tiempos[4]), 6.0, log)

    def test_opcion_que_no_existe_falla_con_la_lista(self):
        f = self.flujo(Paso("elegir_opcion", selectores=[CAMPO % "reporte"], valor="No existe"))
        res = self.ejecutar(f)
        self.assertFalse(res.ok)
        self.assertIn("No hay ninguna opción «No existe»", res.error)
        self.assertIn("Detalles Ventas Mayorista", res.error)

    def test_repetir_por_dias(self):
        f = self.flujo(Paso("clic", selectores=['role=tab[name="Crédito y Cobros"]']),
                       Paso("escribir", selectores=["#fecha_credito"], valor="{fecha:%Y-%m-%d}"),
                       Paso("clic", selectores=["#consultar"]),
                       Paso("esperar_texto", texto="Consulta del {fecha:%Y-%m-%d}"),
                       Paso("guardar_pagina", formato="html", nombre="Credito_{fecha:%Y%m%d}"))
        f.opciones["repetir_dias"] = {"modo": "ultimos", "n": 2}
        res = self.ejecutar(f)              # hoy (inyectado) = 15/03/2026 → 13 y 14 de marzo
        log = self.leer_log(res)
        self.assertTrue(res.ok, res.resumen() + "\n" + log)
        self.assertEqual(res.dias, [datetime.date(2026, 3, 13), datetime.date(2026, 3, 14)])
        self.assertEqual(sorted(os.path.basename(a) for a in res.archivos),
                         ["Credito_20260313.html", "Credito_20260314.html"])
        self.assertIn("=== Día 13/03/2026 (1 de 2) ===", log)
        self.assertIn("Terminado: 2 días", res.resumen())


class TestMapearYVigilar(BaseIntegracion):
    def setUp(self):
        super().setUp()
        self.toasts = []
        avisos.usar_notificador(lambda titulo, texto: self.toasts.append((titulo, texto)))
        self.addCleanup(avisos.usar_notificador, None)
        self.servidor.estado["nuevo_corte"] = False
        self.servidor.estado["descargas"].clear()
        self.addCleanup(self.servidor.estado.update, {"nuevo_corte": False})

    def test_mapear_generar_pasos_y_ejecutarlos(self):
        url = self.base + "portal.html?ms=300"
        f = Flujo(nombre="Mapa", url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=8)
        f.pasos = [Paso("abrir_url", url=url)]
        antes = {}

        def al_final(ej, pg):
            filtros = mapeador.escanear(ej, pg)
            antes["corte"] = next(dict(x) for x in filtros if x["etiqueta"] == "Elegir corte")
            k = next(x["k"] for x in filtros if x["etiqueta"] == "Seleccione reporte")
            return mapeador.actualizar_opciones(ej, pg, filtros, k, "Detalles Ventas Mayorista")

        res = self.ejecutar(f, al_final=al_final)
        self.assertTrue(res.ok, res.resumen() + "\n" + self.leer_log(res))
        por = {x["etiqueta"]: x for x in res.extra}
        self.assertEqual([x["tipo"] for x in res.extra if x["tipo"] == "pestana"], ["pestana", "pestana"])
        self.assertTrue(por["Corte"]["activo"])
        self.assertIn("Crédito y Cobros", por)
        self.assertEqual((por["Filtro por sistema"]["tipo"], por["Filtro por sistema"]["valor"]), ("lista", "Portal"))
        self.assertEqual(por["Filtro por sistema"]["opciones"], ["Portal", "Otro sistema"])
        self.assertEqual(por["Seleccione reporte"]["opciones"], ["Detalles Ventas Mayorista", "Resumen de Ventas"])
        self.assertEqual(antes["corte"]["opciones"], [])                         # depende del reporte
        self.assertEqual(por["Elegir corte"]["opciones"], cortes_portal("Detalles Ventas Mayorista"))  # virtual: 12
        self.assertEqual((por["Formato a Exportar"]["tipo"], por["Formato a Exportar"]["opciones"]),
                         ("lista_nativa", ["Excel", "PDF", "CSV"]))
        self.assertEqual(por["Generar"]["tipo"], "accion")
        self.assertNotIn("Consultar", por)                                       # la otra pestaña no se ve
        self.assertTrue(all(x["selectores"] for x in res.extra))
        elecciones = [{"k": por["Seleccione reporte"]["k"], "estrategia": "fija", "valor": "Detalles Ventas Mayorista"},
                      {"k": por["Elegir corte"]["k"], "estrategia": "mas_reciente"},
                      {"k": por["Formato a Exportar"]["k"], "estrategia": "fija", "valor": "CSV"},
                      {"k": por["Generar"]["k"], "modo": "descargar", "nombre": "Mapa_{opcion}{ext}"}]
        pasos = mapeador.generar_pasos(res.extra, elecciones)
        self.assertEqual([p.tipo for p in pasos], ["elegir_opcion", "elegir_opcion", "elegir_opcion", "descargar"])
        nuevo = Flujo(nombre="Desde el mapa", url=url, pasos=[Paso("abrir_url", url=url)] + pasos)
        nuevo.opciones.update(pausa_entre_pasos=0, timeout_paso=8)
        res2 = self.ejecutar(Flujo.desde_json(nuevo.a_json()), nombre_perfil="p2")
        self.assertTrue(res2.ok, res2.resumen() + "\n" + self.leer_log(res2))
        self.assertEqual([os.path.basename(a) for a in res2.archivos], ["Mapa_CSV.csv"])
        self.assertEqual(self.servidor.estado["descargas"], [cortes_portal("Detalles Ventas Mayorista")[-1]])
        # volver a mapear más tarde muestra lo que cambió
        nuevo_mapa = [dict(x) for x in res.extra]
        corte = next(x for x in nuevo_mapa if x["etiqueta"] == "Elegir corte")
        corte["opciones"] = corte["opciones"] + [CORTE_NUEVO]
        dif = mapeador.comparar(res.extra, nuevo_mapa)
        self.assertEqual(dif["opciones"], [{"etiqueta": "Elegir corte", "nuevas": [CORTE_NUEVO], "quitadas": []}])
        self.assertEqual(mapeador.punto_de_mapeo(nuevo), 1)

    def test_vigilancia_avisa_y_descarga_una_vez(self):
        url = self.base + "portal.html?ms=300"
        f = Flujo(nombre="Portal, metricas", url=url)
        f.opciones.update(pausa_entre_pasos=0, timeout_paso=8)
        f.pasos = [Paso("abrir_url", url=url),
                   Paso("elegir_opcion", selectores=[CAMPO % "reporte"], objetivo="Seleccione reporte",
                        valor="Detalles Ventas Mayorista"),
                   Paso("elegir_opcion", selectores=[CAMPO % "corte"], objetivo="Elegir corte", estrategia="mas_reciente"),
                   Paso("descargar", selectores=["#generar"], nombre="{opcion}{ext}")]
        db = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(db.cerrar)
        rid = db.guardar(f)
        db.guardar_vigilancia(rid, 2, auto_descargar=True)

        def crear(flujo, reporte_id=None, **extra):
            return Ejecutor(flujo, carpeta_perfil=os.path.join(self.tmp, "perfil_vig"), carpeta_registros=self.registros,
                            carpeta_descargas=self.descargas, oculto=True, pausa_entre_pasos=0, accesos=db,
                            reporte_id=reporte_id, **extra)

        r1 = vigilancia.revisar(db, rid, crear)
        self.assertTrue(r1.ok, r1.error)
        self.assertTrue(r1.primera)
        self.assertEqual(r1.opciones, cortes_portal("Detalles Ventas Mayorista"))
        self.assertEqual((r1.nuevas, r1.descargas, db.notificaciones(), self.toasts), ([], [], [], []))
        self.servidor.estado["nuevo_corte"] = True                      # llega el corte de la semana siguiente
        r2 = vigilancia.revisar(db, rid, crear)
        self.assertTrue(r2.ok, r2.error)
        self.assertEqual(r2.nuevas, [CORTE_NUEVO])
        self.assertEqual(len(r2.descargas), 1)
        self.assertTrue(r2.descargas[0][1].ok, r2.descargas[0][1].resumen())
        self.assertEqual([os.path.basename(a) for a in r2.descargas[0][1].archivos], [CORTE_NUEVO.replace("/", "_") + ".xlsx"])
        notis = db.notificaciones()
        self.assertEqual(notis[0]["titulo"], "Llegó un corte nuevo en «Portal, metricas»: " + CORTE_NUEVO)
        self.assertEqual(notis[0]["datos"]["opcion"], CORTE_NUEVO)
        self.assertTrue(notis[0]["leida"])                               # ya se descargó
        self.assertEqual(len(self.toasts), 1)
        vistas = {o["texto"]: o for o in db.opciones_vistas(rid, 2)}
        self.assertIsNotNone(vistas[CORTE_NUEVO]["descargada"])
        r3 = vigilancia.revisar(db, rid, crear)                         # nada nuevo: no se descarga otra vez
        self.assertEqual((r3.nuevas, r3.descargas), ([], []))
        self.assertEqual(self.servidor.estado["descargas"].count(CORTE_NUEVO), 1)
        self.assertIn("nada nuevo", db.vigilancia(rid)["ultimo_resultado"])


if __name__ == "__main__":
    unittest.main()
