"""Pruebas unitarias de la versión 3.1 (sin navegador):

- Regla de novedad de la vigilancia con la forma real de Portal (reporte 10, «Elegir corte», 156 cortes en el orden
  de la página, del «44 - 2026» al «45 - 2023»): un corte antiguo que aparece por primera vez («45 - 2023», «45 - 2025»)
  no es una novedad (ni aviso ni descarga); «45 - 2026 (16/10/2026 - 22/10/2026)» sí, y se descarga UNA vez.  Opciones
  sin fecha ni número: se avisan pero no se descargan solas.
- La API de Vigilancia devuelve las opciones de la más reciente a la más antigua (y la página no las invierte).
- «Usar filtros»: nombres de los filtros (nunca «Open»), enlace con el mapa por selectores o por valor, opciones
  ordenadas, listas dependientes, combinaciones y nombres de archivo, «Guardar como predeterminado», --filtro.
"""

import datetime
import os
import shutil
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import avisos, filtros, mapeador, plantillas, secretos, vigilancia  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402
from webbot.flujo import Flujo, Paso  # noqa: E402

# Selectores reales (posicionales) de los pasos generados para el reporte 10 «Reporte mapeado»
SEL_FORM = ("#app > div:nth-of-type(1) > div:nth-of-type(1) > main:nth-of-type(1) > div:nth-of-type(1) > "
            "div:nth-of-type(1) > div:nth-of-type(3) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > "
            "form:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(%d) > div:nth-of-type(1) > div:nth-of-type(1) > "
            "div:nth-of-type(1)")
SEL_CABECERA = ['div:text-is("Corte44 - 2026 (09/10/2026 - 15/10/2026)Corte")', "#app > header"]
SEL_FORMATO = ['div:text-is("Formato a Exportar📊 ExcelFormato a Exportar")', SEL_FORM % 5]
C44 = "44 - 2026 (09/10/2026 - 15/10/2026)"
C43 = "43 - 2026 (02/10/2026 - 08/10/2026)"
C45_2023 = "45 - 2023 (20/10/2023 - 26/10/2023)"
C45_2025 = "45 - 2025 (17/10/2025 - 23/10/2025)"
C45_2026 = "45 - 2026 (16/10/2026 - 22/10/2026)"


def cortes_reales(sin=()):
    """Los 156 cortes de Portal en el orden de la página (del 44 - 2026 hacia atrás hasta el 45 - 2023)."""
    res = []
    ini = datetime.date(2026, 10, 9)
    semana, anio = 44, 2026
    while len(res) < 156:
        res.append("%02d - %d (%s - %s)" % (semana, anio, ini.strftime("%d/%m/%Y"),
                                             (ini + datetime.timedelta(days=6)).strftime("%d/%m/%Y")))
        ini -= datetime.timedelta(days=7)
        semana -= 1
        if semana == 0:
            anio -= 1
            semana = 52
    return [t for t in res if t not in sin]


def flujo_reporte_10():
    """Forma del reporte 10 «Reporte mapeado» (pasos generados por «Mapear página» con «Open» como objetivo)."""
    url = "https://portal.ejemplo.com/portal/#/reportes/corte"
    return Flujo(nombre="Reporte mapeado", url=url, pasos=[
        Paso("abrir_url", url=url),
        Paso("clic", selectores=['role=tab[name="Corte"]'], objetivo="Corte"),
        Paso("elegir_opcion", selectores=list(SEL_CABECERA), objetivo="Corte", estrategia="mas_reciente"),
        Paso("elegir_opcion", selectores=[SEL_FORM % 1], objetivo="Open", estrategia="fija", valor="Portal"),
        Paso("elegir_opcion", selectores=[SEL_FORM % 2], objetivo="Open", estrategia="fija", valor="Cartera General"),
        Paso("elegir_opcion", selectores=[SEL_FORM % 3], objetivo="Open", estrategia="fija", valor=C44),
        Paso("elegir_opcion", selectores=list(SEL_FORMATO), objetivo="Formato a Exportar", estrategia="fija",
             valor="📊 Excel"),
        Paso("descargar", selectores=['role=button[name="Generar"]'], objetivo="Generar", nombre="{nombre}{ext}")])


def mapa_reporte_10(etiquetas=("Open", "Open", "Open")):
    """El mapa guardado del reporte 10 (las tres listas del formulario salieron como «Open»)."""
    cortes = cortes_reales(sin=(C45_2023,)) + [C45_2023]
    return [{"tipo": "lista", "etiqueta": "Corte", "valor": C44, "opciones": cortes, "k": 2, "orden": 0,
             "selectores": list(SEL_CABECERA)},
            {"tipo": "lista", "etiqueta": etiquetas[0], "valor": "Portal", "opciones": ["Portal"], "k": 3, "orden": 3,
             "selectores": [SEL_FORM % 1]},
            {"tipo": "lista", "etiqueta": etiquetas[1], "valor": "", "k": 4, "orden": 4, "selectores": [SEL_FORM % 2],
             "opciones": ["Cartera General", "Contratos Pendientes y Vencidos", "Creditos y Descuentos"]},
            {"tipo": "lista", "etiqueta": etiquetas[2], "valor": "", "opciones": cortes, "k": 5, "orden": 5,
             "selectores": [SEL_FORM % 3]},
            {"tipo": "lista", "etiqueta": "Formato a Exportar", "valor": "📊 Excel", "opciones": ["📄 CSV", "📊 Excel"],
             "k": 6, "orden": 6, "selectores": list(SEL_FORMATO)},
            {"tipo": "accion", "etiqueta": "Generar", "k": 7, "orden": 7, "selectores": ['role=button[name="Generar"]']}]


class ResFalso:
    """ResultadoEjecucion mínimo para la vigilancia con un ejecutor falso."""

    def __init__(self, ok=True, extra=None, archivos=None):
        self.ok, self.extra, self.archivos = ok, extra, list(archivos or [])
        self.detenido, self.error, self.ruta_log, self.ruta_captura = False, "", "", ""
        self.opciones_leidas = {}

    def resumen(self):
        return "Terminado" if self.ok else "Error"


class PaginaFalsa:
    """Ejecutor falso: «lee» las opciones que tenga la página en ese momento y «descarga» la opción elegida."""

    def __init__(self, opciones):
        self.opciones = list(opciones)
        self.descargas = []
        self.lecturas = 0

    def crear(self, flujo, reporte_id=None, hasta=None, al_final=None, **extra):
        pagina = self

        class Ej:
            def ejecutar(self):
                if al_final is not None:
                    pagina.lecturas += 1
                    res = ResFalso(extra=list(pagina.opciones))
                    res.opciones_leidas[hasta] = {"opciones": list(pagina.opciones),
                                                  "padres": {3: "Portal", 4: "Cartera General"}, "firma": SEL_FORM % 3}
                    return res
                paso = flujo.pasos[5]
                elegido = filtros.desescapar(paso.valor)
                pagina.descargas.append((paso.estrategia, elegido))
                return ResFalso(archivos=["C:/descargas/Portal_%s.xlsx" % elegido.split(" ")[0]])
        return Ej()


class BaseAlmacen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v31_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.toasts = []
        avisos.usar_notificador(lambda titulo, texto: self.toasts.append((titulo, texto)))
        self.addCleanup(avisos.usar_notificador, None)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)


class TestReglaNovedad(BaseAlmacen):
    def test_cortes_antiguos_no_son_novedad_y_el_nuevo_se_descarga_una_vez(self):
        rid = self.alm.guardar(flujo_reporte_10())
        self.alm.guardar_vigilancia(rid, 5, auto_descargar=True)
        primera = cortes_reales(sin=(C45_2023, C45_2025))           # la primera lectura no llegó hasta el final
        self.assertEqual(primera[0], C44)
        pagina = PaginaFalsa(primera)
        r1 = vigilancia.revisar(self.alm, rid, pagina.crear)
        self.assertTrue(r1.ok and r1.primera)
        self.assertEqual(r1.mas_reciente(), C44)
        # segunda revisión: la lista se lee entera y aparecen «45 - 2023» y «45 - 2025» por primera vez
        pagina.opciones = cortes_reales()
        self.assertIn(C45_2023, pagina.opciones)
        r2 = vigilancia.revisar(self.alm, rid, pagina.crear)
        self.assertTrue(r2.ok)
        self.assertEqual((r2.nuevas, r2.recientes, r2.descargas), ([], [], []))
        self.assertEqual(sorted(r2.historicas), sorted([C45_2023, C45_2025]))
        self.assertIn("nada nuevo", r2.resumen())
        self.assertIn("2 opción(es) antigua(s)", r2.resumen())
        self.assertEqual((self.alm.notificaciones(), self.toasts, pagina.descargas), ([], [], []))
        self.assertEqual(self.alm.pendientes_de_descargar(rid, 5), [])
        vistas = {o["texto"]: o for o in self.alm.opciones_vistas(rid, 5)}
        self.assertFalse(vistas[C45_2023]["nueva"])
        self.assertIsNone(vistas[C45_2023]["novedad"])
        # tercera: llega el corte de la semana siguiente (arriba del todo, como en la web)
        pagina.opciones = [C45_2026] + cortes_reales()
        r3 = vigilancia.revisar(self.alm, rid, pagina.crear)
        self.assertEqual(r3.nuevas, [C45_2026])
        self.assertEqual(pagina.descargas, [("fija", C45_2026)])
        notis = self.alm.notificaciones()
        self.assertEqual(len(notis), 1)
        self.assertIn(C45_2026, notis[0]["titulo"])
        self.assertTrue(notis[0]["titulo"].startswith("Llegó un corte nuevo en «Reporte mapeado»"), notis[0]["titulo"])
        self.assertEqual(len(self.toasts), 1)
        # la cuarta revisión no descarga otra vez
        r4 = vigilancia.revisar(self.alm, rid, pagina.crear)
        self.assertEqual((r4.nuevas, r4.descargas), ([], []))
        self.assertEqual(len(pagina.descargas), 1)
        # la vigilancia deja la lista en las opciones del filtro, con la marca «nueva»
        cache = self.alm.opciones_filtro(rid, 5)
        self.assertEqual(cache[0]["fuente"], "vigilancia")
        self.assertEqual(cache[0]["opciones"][0], C45_2026)
        self.assertEqual(self.alm.novedades(rid, 5), [C45_2026])

    def test_opciones_sin_fecha_avisan_pero_no_se_descargan_solas(self):
        f = flujo_reporte_10()
        rid = self.alm.guardar(f)
        self.alm.guardar_vigilancia(rid, 5, auto_descargar=True)
        pagina = PaginaFalsa(["Cartera General", "Creditos y Descuentos"])
        vigilancia.revisar(self.alm, rid, pagina.crear)
        pagina.opciones = ["Cartera General", "Creditos y Descuentos", "Ventas Nuevas"]
        r = vigilancia.revisar(self.alm, rid, pagina.crear)
        self.assertEqual((r.nuevas, r.sin_orden, r.recientes), (["Ventas Nuevas"], ["Ventas Nuevas"], []))
        self.assertEqual(pagina.descargas, [])                         # sin la marca, no se descarga sola
        titulo = self.alm.notificaciones()[0]["titulo"]
        self.assertNotIn("Llegó", titulo)
        self.assertIn("sin fecha", titulo)
        self.assertEqual(self.alm.pendientes_de_descargar(rid, 5), [])
        self.assertEqual(self.alm.pendientes_de_descargar(rid, 5, incluir_sin_orden=True), ["Ventas Nuevas"])
        self.alm.guardar_vigilancia(rid, 5, auto_descargar=True, descargar_sin_fecha=True)
        vigilancia.revisar(self.alm, rid, pagina.crear)
        self.assertEqual(pagina.descargas, [("fija", "Ventas Nuevas")])

    def test_registrar_opciones_detalle(self):
        rid = self.alm.guardar(flujo_reporte_10())
        self.assertEqual(self.alm.registrar_opciones(rid, 5, [C44, C43]), ([], True))
        d = self.alm.registrar_opciones(rid, 5, [C44, C43, C45_2023, C45_2026], detalle=True)
        self.assertEqual((d["nuevas"], d["recientes"], d["historicas"], d["sin_orden"]),
                         ([C45_2026], [C45_2026], [C45_2023], []))


class TestOrdenEnVigilancia(BaseAlmacen):
    def test_api_ordena_de_la_mas_reciente_y_la_pagina_no_invierte(self):
        rid = self.alm.guardar(flujo_reporte_10())
        self.alm.guardar_vigilancia(rid, 5)
        self.alm.registrar_opciones(rid, 5, cortes_reales())          # orden de la página: 44-2026 … 45-2023
        app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                            listar_tareas=lambda: [], oculto_forzado=True,
                            ejecutar_tareas=lambda cmd: (1, "(prueba: nunca se crean tareas)"))
        x = next(r for r in app.api("GET", "/api/vigilancia", {}, {})["reportes"] if r["id"] == rid)
        textos = [o["texto"] for o in x["opciones"]]
        self.assertEqual(textos[0], C44)
        self.assertTrue(x["opciones"][0]["mas_reciente"])
        self.assertFalse(any(o["mas_reciente"] for o in x["opciones"][1:]))
        self.assertEqual(textos[:3], [C44, C43, "42 - 2026 (25/09/2026 - 01/10/2026)"])
        self.assertNotIn(C45_2023, textos)                             # el más antiguo, nunca arriba
        self.assertEqual(x["opciones"][0]["periodo"], "año 2026 · del 09/10/2026 al 15/10/2026")
        todas = app.api("GET", "/api/vigilancia/%d/opciones" % rid, {}, {})["opciones"]
        self.assertEqual(todas[-1]["texto"], C45_2023)
        with open(os.path.join(RAIZ, "ui", "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertNotIn("x.opciones || []).slice().reverse()", js)
        self.assertIn("chip('más reciente'", js)


class TestNombresDeFiltros(unittest.TestCase):
    def test_reporte_10_sin_open(self):
        fl = flujo_reporte_10()
        mapas = [{"cuando": "2026-10-26 11:15:04", "filtros": mapa_reporte_10()}]
        noms = filtros.nombres(fl, mapas)
        self.assertEqual(sorted(noms), [2, 3, 4, 5, 6])
        for _i, (n, _o) in noms.items():
            self.assertNotIn("open", n.lower())
        self.assertEqual(noms[2], ("Corte", "mapa"))
        self.assertEqual(noms[5][0], "Corte (paso 6)")                 # deducido de sus opciones; el 3 ya es «Corte»
        self.assertEqual(noms[6], ("Formato a Exportar", "mapa"))
        self.assertEqual(noms[3], ("Lista del paso 4", "numero"))
        # con un mapa nuevo (etiquetas buenas) se usan las del mapa, enlazadas por selectores
        mapas = [{"cuando": "x", "filtros": mapa_reporte_10(("Filtro por sistema", "Filtro por reporte",
                                                             "Elegir corte"))}]
        noms = filtros.nombres(fl, mapas)
        self.assertEqual([noms[i][0] for i in (3, 4, 5)], ["Filtro por sistema", "Filtro por reporte", "Elegir corte"])
        # enlace por el valor (sin selectores comunes)
        otro = flujo_reporte_10()
        otro.pasos[4].selectores = ["#otro"]
        f, _m = filtros.filtro_del_mapa(otro.pasos[4], mapas)
        self.assertEqual(f["etiqueta"], "Filtro por reporte")
        self.assertEqual(filtros.etiqueta_de_selector(fl.pasos[6]), "Formato a Exportar")
        self.assertEqual(filtros.etiqueta_de_selector(fl.pasos[2]), "Corte")
        for generica in ("Open", "Close", "Abrir", "mdi-menu-down", "arrow_drop_down", "div", "▾"):
            self.assertTrue(mod_flujo.etiqueta_generica(generica), generica)
        for buena in ("Elegir corte", "Filtro por sistema", "Factura", "Formato a Exportar"):
            self.assertFalse(mod_flujo.etiqueta_generica(buena), buena)
        with self.assertRaises(filtros.ErrorFiltros):
            filtros.validar_nombre("Open")
        # la descripción del paso usa el nombre del filtro si el objetivo es «Open»
        p = fl.pasos[5].copia()
        p.filtro = "Elegir corte"
        self.assertIn("«Elegir corte»", p.descripcion())

    def test_mapeador_no_genera_open(self):
        f = {"tipo": "lista", "etiqueta": "Open", "valor": C44, "k": 1, "orden": 1, "selectores": ["#c"],
             "opciones": [C44, C43]}
        p = mapeador.paso_de_filtro(f, {"estrategia": "mas_reciente"})
        self.assertEqual((p.objetivo, p.filtro), ("", ""))
        f["etiqueta"] = "Elegir corte"
        p = mapeador.paso_de_filtro(f, {"estrategia": "mas_reciente"})
        self.assertEqual((p.objetivo, p.filtro), ("Elegir corte", "Elegir corte"))
        with open(os.path.join(RAIZ, "webbot", "mapeador.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("RX_GENERICA", js)
        self.assertIn(".v-messages__message", js)


class TestPanelYCambios(unittest.TestCase):
    def test_panel_ordena_y_preselecciona(self):
        fl = flujo_reporte_10()
        fl.pasos[5].estrategia, fl.pasos[5].valor = "mas_reciente", ""
        firma = filtros.firma_paso(fl.pasos[5])
        filas = [{"paso": 5, "padres": {2: C44, 3: "Portal", 4: "Cartera General"}, "firma": firma,
                  "opciones": cortes_reales(), "actualizado": "2026-10-26 11:20:10", "fuente": "vigilancia"}]
        d = {x["paso"]: x for x in filtros.datos_panel(fl, filas, [{"cuando": "x", "filtros": mapa_reporte_10()}],
                                                         {5: [C44]}, 5)}
        corte = d[5]
        self.assertTrue(corte["cronologica"])
        self.assertEqual(corte["opciones"][0]["texto"], C44)
        self.assertTrue(corte["opciones"][0]["mas_reciente"])
        self.assertTrue(corte["opciones"][0]["nueva"])
        self.assertEqual(corte["opciones"][-1]["texto"], C45_2023)
        self.assertEqual((corte["estrategia"], corte["actual"], corte["fuente"]), ("mas_reciente", C44, "vigilancia"))
        self.assertTrue(corte["vigilado"])
        self.assertTrue(corte["exacta"])
        self.assertEqual(corte["nota"], "")
        formato = d[6]
        self.assertFalse(formato["cronologica"])
        self.assertEqual([o["texto"] for o in formato["opciones"]], ["📄 CSV", "📊 Excel"])     # orden de la página
        self.assertEqual((formato["actual"], formato["fuente"]), ("📊 Excel", "mapa"))
        # el usuario cambia el «reporte» (padre): no hay lista para esa combinación → la última conocida + nota
        filas.append({"paso": 5, "padres": {2: C44, 3: "Portal", 4: "Resumen de Ventas"}, "firma": firma,
                      "opciones": ["Agosto 2026", "Septiembre 2026"], "actualizado": "2026-10-25 10:00:00",
                      "fuente": "ejecucion"})
        d = {x["paso"]: x for x in filtros.datos_panel(fl, filas, [], {}, None,
                                                         {4: {"valores": ["Contratos Pendientes y Vencidos"]}})}
        self.assertFalse(d[5]["exacta"])
        self.assertIn("No hay opciones guardadas para esta combinación", d[5]["nota"])
        d = {x["paso"]: x for x in filtros.datos_panel(fl, filas, [], {}, None, {"4": {"valores": ["Resumen de Ventas"]}})}
        self.assertTrue(d[5]["exacta"])
        self.assertEqual([o["texto"] for o in d[5]["opciones"]], ["Septiembre 2026", "Agosto 2026"])

    def test_combinaciones_nombres_y_predeterminado(self):
        fl = flujo_reporte_10()
        combos = filtros.combinaciones(fl, {5: {"valores": [C43, "42 - 2026 (25/09/2026 - 01/10/2026)"]},
                                            6: {"estrategia": "fija", "valor": "📄 CSV"}})
        self.assertEqual(len(combos), 2)
        cambios, sufijo = combos[0]
        self.assertEqual(sufijo, [C43])
        nuevo, lineas = filtros.aplicar(fl, cambios, sufijo)
        self.assertEqual(nuevo.pasos[5].valor, plantillas.escapar(C43))
        self.assertEqual(nuevo.pasos[7].nombre, "{nombre} - 43 - 2026 (02_10_2026 - 08_10_2026){ext}")
        self.assertEqual(len(lineas), 2)
        self.assertEqual(fl.pasos[5].valor, C44)                       # el original no cambia
        self.assertEqual(len(filtros.combinaciones(fl, {5: {"valores": cortes_reales()[:4]},
                                                        6: {"valores": ["📄 CSV", "📊 Excel"]},
                                                        4: {"valores": ["a", "b"]}})), 16)
        # sin cambios reales: nada que anotar
        self.assertEqual(filtros.aplicar(fl, {5: {"estrategia": "fija", "valor": C44}})[1], [])
        # guardar como predeterminado (una opción por filtro) con nombres
        msgs = filtros.guardar_predeterminado(fl, {5: {"estrategia": "mas_reciente"}},
                                              {5: "Elegir corte", 3: "Open"})
        self.assertEqual((fl.pasos[5].estrategia, fl.pasos[5].valor, fl.pasos[5].filtro), ("mas_reciente", "", "Elegir corte"))
        self.assertEqual(fl.pasos[3].filtro, "")                        # «Open» nunca se guarda como nombre
        self.assertEqual(len(msgs), 1)
        with self.assertRaises(filtros.ErrorFiltros):
            filtros.guardar_predeterminado(fl, {5: {"valores": [C43, C44]}})

    def test_resolver_cli(self):
        fl = flujo_reporte_10()
        fl.pasos[5].filtro = "Elegir corte"
        el = filtros.resolver_cli(fl, ["Elegir corte=" + C43, "Formato a Exportar=📄 CSV"])
        self.assertEqual(el, {5: {"valores": [C43]}, 6: {"valores": ["📄 CSV"]}})
        self.assertEqual(filtros.resolver_cli(fl, ["6=" + C43, "elegir CORTE=" + C44]), {5: {"valores": [C43, C44]}})
        self.assertEqual(filtros.resolver_cli(fl, ["paso 3=más reciente"]), {2: {"estrategia": "mas_reciente", "valor": ""}})
        for malo in (["Corte de otro=1"], ["8=x"], ["sin igual"], ["Elegir corte="]):
            with self.assertRaises(filtros.ErrorFiltros):
                filtros.resolver_cli(fl, malo)

    def test_seleccionar_nativo_es_filtro(self):
        fl = Flujo(nombre="N", pasos=[Paso("abrir_url", url="http://a/"),
                                      Paso("seleccionar", selectores=["#cliente"], valor="acme", etiqueta="Acme S.A.")])
        d = filtros.datos_panel(fl, [{"paso": 1, "padres": {}, "firma": "#cliente", "opciones": ["Acme S.A.", "Beta"],
                                      "actualizado": "x", "fuente": "ejecucion"}])
        self.assertEqual((d[0]["clase"], d[0]["actual"]), ("lista", "Acme S.A."))
        nuevo, lineas = filtros.aplicar(fl, {1: {"estrategia": "fija", "valor": "Beta"}})
        self.assertEqual((nuevo.pasos[1].tipo, nuevo.pasos[1].valor, nuevo.pasos[1].estrategia), ("elegir_opcion", "Beta", "fija"))
        self.assertEqual(fl.pasos[1].tipo, "seleccionar")
        self.assertEqual(filtros.aplicar(fl, {1: {"estrategia": "fija", "valor": "Acme S.A."}})[1], [])

    def test_fecha_es_filtro(self):
        fl = Flujo(nombre="F", pasos=[Paso("abrir_url", url="http://a/"),
                                      Paso("escribir", selectores=["#f"], valor="{ayer:%d/%m/%Y}"),
                                      Paso("escribir", selectores=["#u"], valor="demo", objetivo="Usuario"),
                                      Paso("escribir", selectores=["#clave"], valor="{secreto:x}")])
        self.assertEqual([i for i, _p in filtros.pasos_filtro(fl)], [1])
        d = filtros.datos_panel(fl)
        self.assertEqual((d[0]["clase"], d[0]["valor"], d[0]["nombre"]), ("fecha", "{ayer:%d/%m/%Y}", "Fecha"))
        self.assertIn("{hoy:%d/%m/%Y}", [s["valor"] for s in d[0]["sugerencias"]])
        nuevo, lineas = filtros.aplicar(fl, {1: {"valor": "{hoy:%d/%m/%Y}"}})
        self.assertEqual(nuevo.pasos[1].valor, "{hoy:%d/%m/%Y}")


class TestCacheDeOpciones(BaseAlmacen):
    def test_guardar_buscar_y_mapa(self):
        fl = flujo_reporte_10()
        rid = self.alm.guardar(fl)
        self.alm.guardar_opciones_filtro(rid, 5, [C44, C43], {3: "Portal", 4: "Cartera General"}, "f", "ejecucion")
        self.alm.guardar_opciones_filtro(rid, 5, [C45_2026, C44, C43], {3: "Portal", 4: "Cartera General"}, "f",
                                         "actualizar")
        filas = self.alm.opciones_filtro(rid, 5)
        self.assertEqual(len(filas), 1)                                 # misma combinación: se sustituye
        self.assertEqual((filas[0]["fuente"], filas[0]["opciones"][0]), ("actualizar", C45_2026))
        self.assertEqual(filas[0]["padres"], {3: "Portal", 4: "Cartera General"})
        res = ResFalso()
        res.opciones_leidas = {6: {"opciones": ["📄 CSV", "📊 Excel"], "padres": {}, "firma": ""}}
        self.alm.registrar_resultado(rid, res)                          # cada ejecución guarda lo que leyó
        self.assertEqual(self.alm.opciones_filtro(rid, 6)[0]["fuente"], "ejecucion")
        # opciones del mapa para los pasos generados
        filtros_mapa = mapa_reporte_10(("Filtro por sistema", "Filtro por reporte", "Elegir corte"))
        filtros_mapa[2]["valor"] = "Cartera General"
        elec = [{"k": 3, "estrategia": "fija", "valor": "Portal"}, {"k": 4, "estrategia": "fija",
                                                                    "valor": "Cartera General"},
                {"k": 5, "estrategia": "mas_reciente"}]
        pasos, usados = mapeador.generar_pasos(filtros_mapa, elec, con_filtros=True)
        self.assertEqual([p.filtro for p in pasos], ["Filtro por sistema", "Filtro por reporte", "Elegir corte"])
        cache = mapeador.opciones_para_cache(pasos, usados, 2)
        self.assertEqual([(i, padres) for i, _o, padres in cache],
                         [(2, {}), (3, {2: "Portal"}), (4, {2: "Portal", 3: "Cartera General"})])


if __name__ == "__main__":
    unittest.main()
