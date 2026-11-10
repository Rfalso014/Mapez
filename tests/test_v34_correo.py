"""Pruebas de la versión 3.4 (parte 2): «Correo», sin navegador.

- `webbot/correo.py`: comparar sin mayúsculas/acentos/puntuación, fechas de Outlook/Gmail/IMAP, criterios («¿Qué
  correo?») en la lista y con el correo abierto, la clave de cada correo, copiar textos y tablas del cuerpo, nombres de
  archivo con plantillas, .zip, CSV/Excel/txt, las acciones y la revisión completa con un proveedor FALSO (todos los
  correos que coinciden, del más reciente al más antiguo, nunca dos veces, máximo por revisión, reintentos, sesión
  caducada, avisos e historial).
- `webbot/correo_imap.py` con un servidor IMAP FALSO (imaplib simulado: nunca se conecta a nada).
- `almacen`: tablas nuevas y conversión de una base de datos de la 3.4 (1/2); `servidor_ui`: la API «correo»;
  `programador`/`bot.py`: --correo-id / --correos.
Bases de datos temporales, contraseñas en memoria, ningún aviso de Windows, schtasks nunca se ejecuta, sin Internet.
"""

import datetime as dt
import email.message
import email.utils
import imaplib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import bot  # noqa: E402
from webbot import avisos, correo, correo_imap, horario, programador, secretos  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen, ErrorAlmacen  # noqa: E402

HOY = dt.datetime(2026, 10, 29, 10, 0)                 # jueves 29/10/2026 10:00
ASUNTO = "RESUMEN DE VENTAS EMPRESA EJEMPLO, S.A.S. AL %s"
ADJ = "SUPERVISION VENTAS EJEMPLO V1.4.xlsx"


def _sin_schtasks(*a, **k):
    raise AssertionError("¡Una prueba intentó ejecutar schtasks de verdad!")


def mensaje(id_, dias, hora, remitente="Reportes Ventas <reportes@ejemplo.com>", asunto=None, html=None,
            adjuntos=None):
    f = dt.datetime.combine((HOY - dt.timedelta(days=dias)).date(), dt.time(*hora))
    return {"id": id_, "asunto": asunto if asunto is not None else ASUNTO % f.strftime("%d/%m/%Y"), "remitente": remitente,
            "fecha": f, "html": html if html is not None else "<p>Total ventas: %d</p>" % (1000 + dias),
            "adjuntos": adjuntos if adjuntos is not None else {ADJ: ("xlsx %s" % id_).encode()}}


def buzon():
    return [mensaje("a1", 0, (9, 7), html="<p>Buenos días,</p><p>Total ventas: 1.234</p><table><tr><th>Producto</th>"
                                          "<th>Cantidad</th></tr><tr><td>Plan Básico</td><td>12</td></tr></table>"),
            mensaje("a2", 1, (15, 30)),
            mensaje("a3", 0, (8, 0), remitente="Boletín <noticias@ejemplo.org>", asunto="Novedades de la semana",
                    html="<p>Nada</p>", adjuntos={}),
            mensaje("a4", 10, (9, 0)),
            mensaje("a5", 2, (11, 15), html="<p>Sin el dato que se busca</p>")]


class AdaptadorFalso:
    """Un buzón en memoria con la interfaz de los proveedores."""

    def __init__(self, mensajes, sesion=True):
        self.mensajes = mensajes
        self.sesion = sesion
        self.entradas = 0
        self.abiertos = []
        self.descargados = []

    def __call__(self, cuenta):                # (también hace de «abrir_adaptador»)
        return self

    def __enter__(self):
        self.entradas += 1
        if not self.sesion:
            raise correo.ErrorSesion("La sesión de «prueba» caducó (el buzón pide iniciar sesión)")
        return self

    def __exit__(self, *exc):
        return False

    def buscar(self, c, hoy=None, limite=30):
        return [{"id": "falso:" + m["id"], "_id": m["id"], "asunto": m["asunto"], "remitente": m["remitente"],
                 "remitente_correo": correo.correo_de(m["remitente"]), "fecha": m["fecha"], "adjuntos": None,
                 "tiene_adjuntos": bool(m["adjuntos"]), "texto": ""} for m in self.mensajes][:limite]

    def abrir(self, m):
        self.abiertos.append(m["_id"])
        src = next(x for x in self.mensajes if x["id"] == m["_id"])
        return {"asunto": src["asunto"], "remitente": src["remitente"], "fecha": src["fecha"], "html": src["html"],
                "texto": "", "adjuntos": [{"nombre": n, "tamano": ""} for n in src["adjuntos"]]}

    def descargar(self, m, det, nombres, carpeta):
        src = next(x for x in self.mensajes if x["id"] == m["_id"])
        res = {}
        for n in nombres:
            ruta = os.path.join(carpeta, n)
            with open(ruta, "wb") as f:
                f.write(src["adjuntos"][n])
            res[n] = ruta
            self.descargados.append(n)
        return res


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_correo_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.avisos = []
        avisos.usar_notificador(lambda titulo, texto: self.avisos.append((titulo, texto)))
        self.addCleanup(avisos.usar_notificador, None)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        p = mock.patch.object(programador, "_ejecutar", _sin_schtasks)
        p.start()
        self.addCleanup(p.stop)
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.base = os.path.join(self.tmp, "descargas")
        os.makedirs(self.base)

    def cuenta(self, **k):
        return self.alm.guardar_cuenta_correo(dict({"nombre": "Empresa", "proveedor": "outlook_web",
                                                    "direccion": "reportes@ejemplo.com"}, **k))

    def busqueda(self, cid=None, **k):
        datos = {"nombre": "Ventas", "cuenta_id": cid or self.cuenta(),
                 "criterios": {"asunto": "RESUMEN DE VENTAS EMPRESA", "remitente": "reportes@ejemplo.com",
                               "fecha": "ultimos", "dias": 7},
                 "acciones": [{"tipo": "adjuntos", "coincide": "supervision ventas",
                               "nombre": "Ventas {fecha_correo:%Y-%m-%d}.xlsx", "carpeta": "migracion"},
                              {"tipo": "texto", "etiqueta": "Total ventas:"}]}
        datos.update(k)
        return self.alm.guardar_busqueda_correo(datos, hoy=HOY)


# ============================================================================ textos y fechas
class TestTextos(unittest.TestCase):
    def test_normalizar_como_octopus(self):
        for t in ("Servicios, S.A.S.", "SERVICIOS S. A. S.", "Servicios SAS", "servícios s-a-s"):
            self.assertEqual(correo.normalizar(t), "SERVICIOSSAS")
        self.assertTrue(correo.contiene("RESUMEN DE VENTAS MI EMPRESA Y SERVICIOS, S.A.S. AL 31 DE AGOSTO",
                                        "resumen de ventas mi empresa y servicios sas"))
        self.assertTrue(correo.contiene("lo que sea", ""))
        self.assertFalse(correo.contiene("Novedades", "ventas"))
        self.assertEqual(correo.correo_de("Reportes Ventas <Reportes@Ejemplo.com>"), "reportes@ejemplo.com")
        self.assertEqual(correo.nombre_de("Reportes Ventas <reportes@ejemplo.com>"), "Reportes Ventas")

    def test_fechas_de_cada_proveedor(self):
        casos = {
            "Thu 10/29/2026 9:07 AM": dt.datetime(2026, 10, 29, 9, 7),          # Outlook en inglés (M/D)
            "Fri 9/11/2026 8:07 PM": dt.datetime(2026, 9, 11, 20, 7),
            "jue 29/10/2026 9:07": dt.datetime(2026, 10, 29, 9, 7),             # Outlook en español (D/M)
            "mar 03/11/2026 14:05": dt.datetime(2026, 11, 3, 14, 5),            # 3 nov es martes (no 11 mar)
            "05/11/2026": dt.datetime(2026, 11, 5),                             # sin día de la semana: D/M
            "jue, 29 oct 2026, 9:07": dt.datetime(2026, 10, 29, 9, 7),           # Gmail en español
            "Oct 29, 2026, 9:07 PM": dt.datetime(2026, 10, 29, 21, 7),           # Gmail en inglés
            "29 de octubre de 2026 10:30": dt.datetime(2026, 10, 29, 10, 30),
            "2026-10-29 09:07": dt.datetime(2026, 10, 29, 9, 7),
        }
        for texto, esperado in casos.items():
            self.assertEqual(correo.leer_fecha(texto), esperado, texto)
        rfc = correo.leer_fecha(email.utils.format_datetime(dt.datetime(2026, 10, 29, 9, 7).astimezone()))
        self.assertEqual(rfc, dt.datetime(2026, 10, 29, 9, 7))
        self.assertIsNone(correo.leer_fecha("sin fecha"))
        self.assertIsNone(correo.leer_fecha(""))

    def test_extraer_textos(self):
        texto = correo.html_a_texto("<p>Buenos días</p><p>Total VENTAS : 1.234 DOP</p><table><tr><td>Clientes nuevos"
                                    "</td><td>15</td></tr></table><div>Saldo pendiente:</div><div>3.400,00</div>"
                                    "<p>Período: octubre</p><script>no()</script>")
        self.assertIn("Clientes nuevos\t15", texto)
        self.assertNotIn("no()", texto)
        self.assertEqual(correo.extraer_despues(texto, "Total ventas:"), "1.234 DOP")
        self.assertEqual(correo.extraer_despues(texto, "total ventas"), "1.234 DOP")
        self.assertEqual(correo.extraer_despues(texto, "Clientes nuevos"), "15")
        self.assertEqual(correo.extraer_despues(texto, "Saldo pendiente:"), "3.400,00")      # en la línea siguiente
        self.assertEqual(correo.extraer_despues(texto, "periodo:"), "octubre")               # sin acento
        self.assertIsNone(correo.extraer_despues(texto, "No está"))
        self.assertEqual(correo.extraer_entre(texto, "Total ventas:", "DOP"), "1.234")
        self.assertEqual(correo.extraer_entre(texto, "Total ventas:", ""), "1.234 DOP")
        self.assertEqual(correo.extraer_regex(texto, r"Total ventas\s*:\s*([\d.,]+)"), "1.234")
        self.assertEqual(correo.extraer_regex(texto, r"[\d.]+,\d\d"), "3.400,00")
        self.assertIsNone(correo.extraer_regex(texto, r"nada(\d)"))
        with self.assertRaises(correo.ErrorCorreo):
            correo.extraer_regex(texto, r"(")

    def test_tablas_del_cuerpo(self):
        html = ("<table><tr><td><table><tr><th>Producto</th><th>Importe</th></tr><tr><td>A</td><td>1,200.50</td></tr>"
                "<tr><td>B</td><td>007</td></tr></table></td></tr></table><table><tr><td>x</td></tr></table>")
        t = correo.tablas_html(html)
        self.assertEqual(len(t), 2)                     # la que solo envuelve a otra no cuenta
        self.assertEqual(t[0], [["Producto", "Importe"], ["A", 1200.5], ["B", "007"]])
        self.assertEqual(correo.valor_de_texto("42"), 42)
        self.assertEqual(correo.valor_de_texto("0042"), "0042")


# ============================================================================ criterios
class TestCriterios(unittest.TestCase):
    def c(self, **k):
        return correo.normalizar_criterios(dict({"asunto": "RESUMEN DE VENTAS EMPRESA"}, **k), HOY)

    def test_normalizar_y_errores(self):
        c = self.c(cuerpo="Total ventas\n\n  clientes  ", extension=".XLSX; csv", remitente="  a@b.com ")
        self.assertEqual(c["cuerpo"], ["Total ventas", "clientes"])
        self.assertEqual(c["extension"], "xlsx, csv")
        self.assertEqual(c["remitente"], "a@b.com")
        self.assertEqual(c["fecha"], "ultimos")
        with self.assertRaisesRegex(correo.ErrorCorreo, "al menos el asunto"):
            correo.normalizar_criterios({"fecha": "hoy"}, HOY)
        with self.assertRaisesRegex(correo.ErrorCorreo, "anterior"):
            self.c(fecha="rango", desde="{hoy}", hasta="{dias:-3}")
        with self.assertRaisesRegex(correo.ErrorCorreo, "No entiendo la fecha"):
            self.c(fecha="rango", desde="mañana")
        with self.assertRaises(correo.ErrorCorreo):
            self.c(fecha="semana")

    def test_rango_de_fechas(self):
        self.assertEqual(correo.rango_fechas(self.c(fecha="hoy"), HOY), (HOY.date(), HOY.date()))
        ayer = (HOY - dt.timedelta(days=1)).date()
        self.assertEqual(correo.rango_fechas(self.c(fecha="ayer"), HOY), (ayer, ayer))
        self.assertEqual(correo.rango_fechas(self.c(fecha="ultimos", dias=7), HOY), (dt.date(2026, 10, 22), HOY.date()))
        self.assertEqual(correo.rango_fechas(self.c(fecha="rango", desde="{dias:-7}", hasta="31/10/2026"), HOY),
                         (dt.date(2026, 10, 22), dt.date(2026, 10, 31)))
        self.assertEqual(correo.rango_fechas(self.c(fecha="rango", desde="{inicio_mes}"), HOY), (dt.date(2026, 10, 1), None))
        self.assertEqual(correo.rango_fechas(self.c(fecha="cualquiera"), HOY), (None, None))

    def test_coincide_en_la_lista_y_abierto(self):
        c = self.c(remitente="reportes@ejemplo.com", remitente_exacto=True, cuerpo=["Total ventas"], adjunto="supervision",
                   extension="xlsx")
        fila = {"asunto": "", "texto": "Reportes Ventas RESUMEN DE VENTAS EMPRESA EJEMPLO, S.A.S. AL 29/10/2026",
                "remitente": "Reportes Ventas", "remitente_correo": "", "fecha": HOY, "adjuntos": None,
                "tiene_adjuntos": None}
        self.assertEqual(correo.coincide(fila, c, HOY, fase="resumen"), (True, ""))   # lo que no se sabe no descarta
        self.assertFalse(correo.coincide(dict(fila, tiene_adjuntos=False), c, HOY, fase="resumen")[0])
        self.assertIn("antes del", correo.coincide(dict(fila, fecha=HOY - dt.timedelta(days=10)), c, HOY, "resumen")[1])
        abierto = dict(fila, asunto=ASUNTO % "29/10/2026", remitente="Reportes Ventas <reportes@ejemplo.com>",
                       remitente_correo="reportes@ejemplo.com", adjuntos=[{"nombre": ADJ}],
                       cuerpo_texto="Hola\nTotal ventas: 1.234")
        self.assertEqual(correo.coincide(abierto, c, HOY), (True, ""))
        self.assertIn("cuerpo no dice", correo.coincide(dict(abierto, cuerpo_texto="otro"), c, HOY)[1])
        self.assertIn("ningún adjunto", correo.coincide(dict(abierto, adjuntos=[{"nombre": "otro.pdf"}]), c, HOY)[1])
        self.assertIn("no lo envía", correo.coincide(dict(abierto, remitente_correo="otro@ejemplo.com"), c, HOY)[1])
        self.assertIn("no tiene adjuntos", correo.coincide(dict(abierto, adjuntos=[]), c, HOY)[1])
        self.assertIn("no se pudo leer la fecha", correo.coincide(dict(abierto, fecha=None), c, HOY)[1])
        # remitente por nombre exacto y «contiene»
        c2 = self.c(remitente="reportes ventas", remitente_exacto=True)
        self.assertTrue(correo.coincide(abierto, c2, HOY)[0])
        self.assertFalse(correo.coincide(dict(abierto, remitente="Reportes Ventas Sur <x@y.com>",
                                              remitente_correo="x@y.com"), c2, HOY)[0])
        self.assertTrue(correo.coincide(abierto, self.c(remitente="EJEMPLO.COM"), HOY)[0])
        self.assertFalse(correo.coincide(dict(abierto, asunto="Novedades"), self.c(), HOY)[0])

    def test_clave_y_orden(self):
        m = {"id": "outlook:abc", "fecha": HOY}
        self.assertEqual(correo.clave_mensaje(m), "outlook:abc|2026-10-29T10:00")       # conversación + fecha
        sin = {"asunto": "Hola", "remitente": "a@b.com", "fecha": HOY}
        self.assertEqual(correo.clave_mensaje(sin), correo.clave_mensaje(dict(sin, asunto="HOLA!")))
        self.assertNotEqual(correo.clave_mensaje(sin), correo.clave_mensaje(dict(sin, fecha=HOY - dt.timedelta(1))))
        lista = [{"n": 1, "fecha": HOY - dt.timedelta(days=2)}, {"n": 2, "fecha": None}, {"n": 3, "fecha": HOY}]
        self.assertEqual([x["n"] for x in correo.ordenar(lista)], [3, 1, 2])

    def test_consultas_de_cada_proveedor(self):
        c = self.c(remitente="reportes@ejemplo.com", fecha="ultimos", dias=7, adjunto="SUPERVISION VENTAS",
                   cuerpo=["Total ventas"])
        self.assertEqual(correo.consulta_gmail(c, HOY),
                         'subject:(RESUMEN DE VENTAS EMPRESA) from:reportes@ejemplo.com after:2026/10/22 '
                         'before:2026/10/30 has:attachment filename:(SUPERVISION VENTAS) "Total ventas"')
        self.assertEqual(correo.consulta_gmail(self.c(extension="xlsx, csv", fecha="cualquiera"), HOY),
                         "subject:(RESUMEN DE VENTAS EMPRESA) has:attachment {filename:xlsx filename:csv}")
        self.assertEqual(correo.criterios_imap(c, HOY), ["SINCE", "22-Oct-2026", "BEFORE", "30-Oct-2026", "FROM",
                                                         '"reportes@ejemplo.com"', "SUBJECT", '"RESUMEN DE VENTAS EMPRESA"'])
        # lo que no es ASCII no se manda al servidor IMAP (se comprueba aquí); el asunto se corta en la puntuación
        c2 = correo.normalizar_criterios({"asunto": "VENTAS, S.A.S. AL", "remitente": "Boletín", "fecha": "cualquiera"})
        self.assertEqual(correo.criterios_imap(c2), ["SUBJECT", '"VENTAS"'])
        self.assertEqual(correo.criterios_imap(correo.normalizar_criterios({"asunto": "Año", "fecha": "cualquiera"})),
                         ["ALL"])
        # v3.6: el asunto ENTERO (antes las 4 primeras palabras); la versión corta queda para un segundo intento
        self.assertEqual(correo.texto_a_teclear(self.c(asunto="RESUMEN DE VENTAS MI EMPRESA, S.A.S.")),
                         "RESUMEN DE VENTAS MI EMPRESA, S.A.S.")
        self.assertEqual(correo.texto_a_teclear(self.c(buscar="otra cosa")), "otra cosa")
        self.assertIn("de los últimos 7 días", correo.describir_criterios(c))


# ============================================================================ nombres, carpetas, acciones
class TestNombres(unittest.TestCase):
    CTX = {"fecha_correo": dt.datetime(2026, 10, 29, 9, 7), "asunto": "VENTAS: 29/10 <hoy>", "remitente": "Reportes",
           "adjunto": "SUPERVISION VENTAS V1.4", "ext": ".xlsx", "n": 2}

    def test_plantillas_del_correo(self):
        self.assertEqual(correo.nombre_final("Ventas {fecha_correo:%Y-%m-%d}.xlsx", self.CTX, HOY), "Ventas 2026-10-29.xlsx")
        self.assertEqual(correo.nombre_final("Ventas {fecha_correo:%Y-%m-%d}", self.CTX, HOY), "Ventas 2026-10-29.xlsx")
        self.assertEqual(correo.nombre_final("{adjunto} ({n}){ext}", self.CTX, HOY), "SUPERVISION VENTAS V1.4 (2).xlsx")
        self.assertEqual(correo.nombre_final("{asunto}", self.CTX, HOY), "VENTAS_ 29_10 _hoy_.xlsx")     # sin / : < >
        self.assertEqual(correo.nombre_final("", self.CTX, HOY), "SUPERVISION VENTAS V1.4.xlsx")
        self.assertEqual(correo.nombre_final("Ventas {hoy:%Y%m%d} - {remitente}", self.CTX, HOY), "Ventas 20261029 - Reportes.xlsx")
        self.assertEqual(correo.nombre_final("{fecha_correo}.csv", self.CTX, HOY), "2026-10-29.csv")
        with self.assertRaisesRegex(correo.ErrorCorreo, "fecha_correo"):
            correo.nombre_final("{cliente}", self.CTX, HOY)

    def test_carpetas(self):
        base = os.path.abspath("x_base")
        self.assertEqual(correo.resolver_carpeta("", base), base)
        self.assertEqual(correo.resolver_carpeta("migracion", base), os.path.join(base, "migracion"))
        self.assertEqual(correo.resolver_carpeta("Correo\\{fecha_correo:%Y-%m}", base, self.CTX),
                         os.path.join(base, "Correo", "2026-10"))
        with mock.patch.dict(os.environ, {"BOTWEB_PRUEBA_CARPETA": os.path.abspath("otra")}):
            self.assertEqual(correo.resolver_carpeta("%BOTWEB_PRUEBA_CARPETA%\\migracion", base),
                             os.path.join(os.path.abspath("otra"), "migracion"))

    def test_acciones_validas_e_invalidas(self):
        a = correo.normalizar_accion({"tipo": "texto", "etiqueta": "Total ventas:"})
        self.assertEqual((a["campo"], a["modo"]), ("Total ventas", "despues"))
        a = correo.normalizar_accion({"tipo": "adjuntos", "extension": "*.XLSX"})
        self.assertEqual(a["extension"], "xlsx")
        malas = [({"tipo": "nada"}, "tipo desconocido"), ({"tipo": "texto"}, "texto que va justo antes"),
                 ({"tipo": "texto", "modo": "regex", "regex": "("}, "no es válida"),
                 ({"tipo": "texto", "etiqueta": "x", "archivo": "a.doc"}, ".xlsx, .csv o .txt"),
                 ({"tipo": "tabla"}, "escribe el archivo"), ({"tipo": "tabla", "archivo": "a.csv", "modo": "hoja_mes"}, "solo vale con Excel"),
                 ({"tipo": "adjuntos", "nombre": "{cliente}"}, "nombre del archivo"),
                 ({"tipo": "cuerpo", "formato": "pdf"}, "formato desconocido")]
        for datos, texto in malas:
            with self.assertRaisesRegex(correo.ErrorCorreo, texto):
                correo.normalizar_accion(datos)
        with self.assertRaisesRegex(correo.ErrorCorreo, "al menos una acción"):
            correo.normalizar_busqueda({"nombre": "x", "cuenta_id": 1, "criterios": {"asunto": "a"}, "acciones": []})
        with self.assertRaisesRegex(correo.ErrorCorreo, "nombre"):
            correo.normalizar_busqueda({"cuenta_id": 1})
        self.assertIn("Copiar «Total ventas»", correo.describir_accion(correo.normalizar_accion(
            {"tipo": "texto", "etiqueta": "Total ventas:"})))


class TestAplicarAcciones(Base):
    def aplicar(self, acciones, m=None, hechas=()):
        m = m or buzon()[0]
        det = {"asunto": m["asunto"], "remitente": m["remitente"], "fecha": m["fecha"], "html": m["html"], "texto": "",
               "adjuntos": [{"nombre": n} for n in m["adjuntos"]]}
        llamadas = []

        def descargar(nombres, carpeta):
            llamadas.append(list(nombres))
            res = {}
            for n in nombres:
                with open(os.path.join(carpeta, n), "wb") as f:
                    f.write(m["adjuntos"][n])
                res[n] = os.path.join(carpeta, n)
            return res
        r = correo.aplicar_acciones(correo.normalizar_acciones(acciones), m, det, descargar, self.base, HOY, hechas=hechas)
        return r, llamadas

    def test_adjuntos_nombre_carpeta_y_choques(self):
        m = mensaje("x", 0, (9, 7), adjuntos={ADJ: b"uno", "Otro.csv": b"dos", "foto.png": b"tres"})
        acc = [{"tipo": "adjuntos", "coincide": "supervision ventas", "nombre": "Ventas {fecha_correo:%Y-%m-%d}.xlsx",
                "carpeta": "migracion"}, {"tipo": "adjuntos", "extension": "csv, png"}]
        r, llamadas = self.aplicar(acc, m)
        self.assertEqual(r["errores"], [])
        self.assertEqual(r["archivos"], [os.path.join(self.base, "migracion", "Ventas 2026-10-29.xlsx"),
                                         os.path.join(self.base, "Otro.csv"), os.path.join(self.base, "foto.png")])
        with open(r["archivos"][0], "rb") as f:
            self.assertEqual(f.read(), b"uno")
        r2, _ = self.aplicar(acc[:1], m)                 # otra vez: no se pisa el anterior
        self.assertEqual(r2["archivos"], [os.path.join(self.base, "migracion", "Ventas 2026-10-29 (2).xlsx")])
        # un adjunto que no está: error de esa acción, las demás siguen
        r3, _ = self.aplicar([{"tipo": "adjuntos", "coincide": "no existe"}, {"tipo": "texto", "etiqueta": "Total ventas:"}], m)
        self.assertEqual(len(r3["errores"]), 1)
        self.assertIn("ningún adjunto que coincida", r3["errores"][0])
        self.assertEqual(r3["valores"], [("Total ventas", "1000")])
        self.assertEqual(r3["hechas"], [1])

    def test_zip_descomprimido(self):
        import io
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("carpeta/" + ADJ, b"del zip")
            z.writestr("__MACOSX/._x", b"basura")
            z.writestr("leeme.txt", b"hola")
        m = mensaje("z", 0, (9, 0), adjuntos={"paquete.zip": b.getvalue()})
        r, _ = self.aplicar([{"tipo": "adjuntos", "coincide": "supervision", "descomprimir": True,
                              "nombre": "{adjunto} {fecha_correo:%d-%m}"}], m)
        self.assertEqual(r["errores"], [])
        self.assertEqual([os.path.basename(x) for x in r["archivos"]], ["SUPERVISION VENTAS EJEMPLO V1.4 29-10.xlsx"])

    def test_extraer_zip_no_se_sale_de_la_carpeta(self):
        z = os.path.join(self.tmp, "malo.zip")
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("../../fuera.txt", b"x")
        dentro = os.path.join(self.tmp, "dentro")
        self.assertEqual(correo.extraer_zip(z, dentro), [os.path.join(dentro, "fuera.txt")])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "fuera.txt")))
        self.assertTrue(correo.es_zip_valido(z))
        self.assertTrue(correo.es_tmp_guid("3f2504e0-4f89-11d3-9a0c-0305e82c3301.tmp"))
        self.assertFalse(correo.es_tmp_guid("informe.tmp"))

    def test_texto_anotado_en_csv_excel_y_txt(self):
        for archivo in ("valores.csv", "valores.xlsx", "valores.txt"):
            acc = [{"tipo": "texto", "etiqueta": "Total ventas:", "archivo": archivo}]
            self.aplicar(acc)
            r, _ = self.aplicar(acc, buzon()[1])
            self.assertEqual(r["errores"], [])
        with open(os.path.join(self.base, "valores.csv"), encoding="utf-8-sig") as f:
            lineas = f.read().splitlines()
        self.assertEqual(lineas[0], "Fecha;Asunto;Campo;Valor")
        self.assertEqual(lineas[1].split(";")[2:], ["Total ventas", "1.234"])
        self.assertEqual(len(lineas), 3)
        from openpyxl import load_workbook
        hoja = load_workbook(os.path.join(self.base, "valores.xlsx")).worksheets[0]
        filas = [list(f) for f in hoja.iter_rows(values_only=True)]
        self.assertEqual(filas[0], correo.COLUMNAS_TEXTO)
        self.assertEqual([f[3] for f in filas[1:]], ["1.234", "1001"])
        with open(os.path.join(self.base, "valores.txt"), encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 2)

    def test_tabla_a_excel_y_csv(self):
        acc = [{"tipo": "tabla", "n": 1, "archivo": "tabla.xlsx", "modo": "agregar"},
               {"tipo": "tabla", "n": 1, "archivo": "tabla.csv", "modo": "agregar"},
               {"tipo": "tabla", "n": 1, "archivo": "meses.xlsx", "modo": "hoja_mes"}]
        self.aplicar(acc)
        r, _ = self.aplicar(acc)
        self.assertEqual(r["errores"], [])
        from openpyxl import load_workbook
        filas = [list(f) for f in load_workbook(os.path.join(self.base, "tabla.xlsx")).worksheets[0].iter_rows(values_only=True)]
        self.assertEqual(filas, [["Producto", "Cantidad"], ["Plan Básico", 12], ["Plan Básico", 12]])   # sin repetir títulos
        with open(os.path.join(self.base, "tabla.csv"), encoding="utf-8-sig") as f:
            self.assertEqual(f.read().splitlines(), ["Producto;Cantidad", "Plan Básico;12", "Plan Básico;12"])
        libro = load_workbook(os.path.join(self.base, "meses.xlsx"))
        self.assertEqual(libro.sheetnames, ["OCTUBRE 2026"])
        self.assertEqual(libro["OCTUBRE 2026"].max_row, 2)                              # hoja del mes reemplazada
        r, _ = self.aplicar([{"tipo": "tabla", "n": 3, "archivo": "x.csv"}])
        self.assertIn("trae 1 tabla", r["errores"][0])

    def test_cuerpo_y_acciones_ya_hechas(self):
        r, llamadas = self.aplicar([{"tipo": "cuerpo", "formato": "html", "carpeta": "cuerpos"},
                                    {"tipo": "cuerpo", "formato": "txt", "nombre": "cuerpo {fecha_correo:%Y%m%d}"},
                                    {"tipo": "adjuntos"}], hechas=[2])
        self.assertEqual(r["errores"], [])
        self.assertEqual(llamadas, [])                   # la acción 3 ya estaba hecha: no se descarga
        self.assertTrue(r["archivos"][0].endswith(".html") and os.path.dirname(r["archivos"][0]).endswith("cuerpos"))
        with open(r["archivos"][0], encoding="utf-8") as f:
            self.assertIn("<!doctype html>", f.read())
        with open(r["archivos"][1], encoding="utf-8") as f:
            self.assertIn("Total ventas: 1.234", f.read())
        self.assertEqual(os.path.basename(r["archivos"][1]), "cuerpo 20261029.txt")


# ============================================================================ almacén
class TestAlmacenCorreo(Base):
    def test_conversion_de_una_base_de_datos_anterior(self):
        from webbot.flujo import Flujo
        self.alm.registrar_ejecucion(self.alm.guardar(Flujo(nombre="R")), "ok")
        self.alm.cerrar()
        con = sqlite3.connect(os.path.join(self.tmp, "b.db"))
        for t in ("cuentas_correo", "busquedas_correo", "correos_procesados"):
            con.execute("DROP TABLE %s" % t)
        con.execute("DROP INDEX ejecuciones_por_correo")
        con.execute("ALTER TABLE ejecuciones DROP COLUMN correo_id")
        con.commit()
        con.close()
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.assertIn("correo_id", {f[1] for f in self.alm._con().execute("PRAGMA table_info(ejecuciones)")})
        self.assertEqual(len(self.alm.historial()), 1)                     # lo anterior sigue
        self.assertEqual(self.alm.listar_busquedas_correo(), [])

    def test_cuentas_busquedas_y_procesados(self):
        cid = self.cuenta()
        self.assertEqual(self.alm.cuenta_correo(cid)["proveedor"], "outlook_web")
        with self.assertRaisesRegex(ErrorAlmacen, "servidor IMAP"):
            self.alm.guardar_cuenta_correo({"proveedor": "imap", "nombre": "x"})
        iid = self.alm.guardar_cuenta_correo({"proveedor": "imap", "host": "imap.ejemplo.com", "direccion": "yo@ejemplo.com"})
        c = self.alm.cuenta_correo(iid)
        self.assertEqual((c["puerto"], c["usuario"], c["carpeta"], c["ssl"]), (993, "yo@ejemplo.com", "INBOX", True))
        bid = self.busqueda(cid)
        b = self.alm.busqueda_correo(bid)
        self.assertEqual((b["nombre"], b["cuenta"], b["activa"], b["max_por_vez"]), ("Ventas", "Empresa", True, 10))
        self.assertEqual(b["programacion"], horario.vacia())
        with self.assertRaisesRegex(ErrorAlmacen, "Ya hay una búsqueda"):
            self.busqueda(cid)
        with self.assertRaisesRegex(ErrorAlmacen, "la usan"):
            self.alm.borrar_cuenta_correo(cid)
        self.alm.marcar_correo_procesado(bid, "k1", "ok", asunto="A", archivos=["C:\\x\\a.xlsx"], valores=[("T", "1")])
        self.alm.marcar_correo_procesado(bid, "k2", "descartado", asunto="B")
        self.assertEqual([p["clave"] for p in self.alm.procesados_correo(bid)], ["k1"])
        self.assertEqual(self.alm.correo_procesado(bid, "k1")["valores"], [["T", "1"]])
        # cambiar los criterios olvida los descartados (se vuelven a mirar), no los procesados
        self.alm.guardar_busqueda_correo(dict(b, criterios=dict(b["criterios"], asunto="OTRO")), bid, hoy=HOY)
        self.assertIsNone(self.alm.correo_procesado(bid, "k2"))
        self.assertIsNotNone(self.alm.correo_procesado(bid, "k1"))
        self.assertTrue(self.alm.olvidar_correo_procesado(bid, "k1"))
        self.assertFalse(self.alm.olvidar_correo_procesado(bid, "k1"))
        # historial de una búsqueda (con las rutas completas de los archivos)
        self.alm.registrar_ejecucion(None, "ok", "1 correo", ["C:\\x\\Ventas.xlsx"], correo_id=bid)
        h = self.alm.historial()
        self.assertEqual((h[0]["nombre"], h[0]["correo_id"], h[0]["archivos"]), ("Ventas", bid, ["C:\\x\\Ventas.xlsx"]))
        self.assertEqual(len(self.alm.historial(correo_id=bid)), 1)
        self.alm.guardar_programacion("correo:%d" % bid, {"reglas": [{"tipo": "semanal", "dias": ["lun"], "horas": ["09:00"]}]})
        self.alm.borrar_busqueda_correo(bid)
        self.assertIsNone(self.alm.busqueda_correo(bid))
        self.assertIsNone(self.alm.programacion("correo:%d" % bid))
        self.assertEqual(self.alm.historial(), [])
        self.alm.borrar_cuenta_correo(cid)


# ============================================================================ la revisión completa (proveedor falso)
class TestRevisar(Base):
    def revisar(self, bid, falso, **k):
        return correo.revisar_busqueda(self.alm, bid, falso, self.base, HOY, carpeta_registros=os.path.join(self.tmp, "reg"),
                                       **k)

    def test_procesa_todos_los_nuevos_una_sola_vez(self):
        bid = self.busqueda()
        falso = AdaptadorFalso(buzon())
        r = self.revisar(bid, falso)
        self.assertTrue(r.ok, r.error)
        # a1 (hoy) y a2 (ayer) coinciden; a5 coincide en la lista pero su cuerpo no tiene «Total ventas» (la acción de
        # texto falla) ; a3 es de otro remitente; a4 es de hace 10 días
        self.assertEqual(falso.abiertos, ["a1", "a2", "a5"])                     # del más reciente al más antiguo
        self.assertEqual([p["asunto"] for p in r.procesados], [ASUNTO % "29/10/2026", ASUNTO % "28/10/2026",
                                                               ASUNTO % "27/10/2026"])
        self.assertEqual(r.procesados[0]["valores"], [("Total ventas", "1.234")])
        self.assertEqual(r.procesados[0]["archivos"], [os.path.join(self.base, "migracion", "Ventas 2026-10-29.xlsx")])
        self.assertEqual(len(r.con_error), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.base, "migracion", "Ventas 2026-10-28.xlsx")))
        # avisos: uno por correo («Llegó …»), y la ejecución en el historial con los archivos
        titulos = [n["titulo"] for n in self.alm.notificaciones()]
        self.assertIn("Llegó «%s»: 1 archivo guardado, Total ventas: 1.234" % (ASUNTO % "29/10/2026"), titulos)
        self.assertTrue(any("acción(es) con error" in t for t in titulos))
        self.assertEqual(len(self.avisos), 1)                    # (y una sola notificación de Windows para todo)
        h = self.alm.historial(correo_id=bid)
        self.assertEqual(h[0]["resultado"], "error")             # una acción falló
        self.assertIn(os.path.join(self.base, "migracion", "Ventas 2026-10-29.xlsx"), h[0]["archivos"])
        self.assertTrue(os.path.isfile(h[0]["registro"]))
        self.assertIn("3 correo(s) procesado(s)", self.alm.busqueda_correo(bid)["ultimo_resultado"])
        # segunda revisión: los «ok» no se repiten; el que tuvo error se reintenta (solo la acción que faltó)
        falso.abiertos.clear()
        falso.descargados.clear()
        r = self.revisar(bid, falso)
        self.assertEqual(falso.abiertos, ["a5"])
        self.assertEqual(falso.descargados, [])                  # su adjunto ya estaba guardado
        self.assertEqual(r.ya_procesados, 2)
        p = self.alm.correo_procesado(bid, correo.clave_mensaje({"id": "falso:a5", "fecha": buzon()[4]["fecha"]}))
        self.assertEqual((p["estado"], p["intentos"], p["hechas"]), ("error", 2, [0]))
        self.revisar(bid, falso)
        falso.abiertos.clear()
        r = self.revisar(bid, falso)                             # tras 3 intentos ya no se reintenta
        self.assertEqual(falso.abiertos, [])
        self.assertIn("no hay correos nuevos", r.resumen())
        # llega un correo nuevo
        falso.mensajes.append(mensaje("a6", 0, (9, 45)))
        r = self.revisar(bid, falso)
        self.assertEqual(falso.abiertos, ["a6"])
        self.assertEqual(len(r.procesados), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.base, "migracion", "Ventas 2026-10-29 (2).xlsx")))
        # «volver a procesar»
        clave = r.procesados[0]["clave"]
        self.alm.olvidar_correo_procesado(bid, clave)
        falso.abiertos.clear()
        self.revisar(bid, falso)
        self.assertEqual(falso.abiertos, ["a6"])

    def test_maximo_por_revision_y_descartados(self):
        cid = self.cuenta()
        bid = self.busqueda(cid, max_por_vez=1, criterios={"asunto": "RESUMEN", "cuerpo": ["Total ventas"],
                                                           "fecha": "cualquiera"},
                            acciones=[{"tipo": "texto", "etiqueta": "Total ventas:"}])
        falso = AdaptadorFalso(buzon())
        r = self.revisar(bid, falso)
        self.assertEqual(len(r.procesados), 1)
        self.assertEqual(r.pendientes, 3)
        self.assertIn("3 más para la próxima revisión", r.resumen())
        for _ in range(4):
            r = self.revisar(bid, falso)
        # a5 no dice «Total ventas»: al abrirlo se descarta (no se procesa ni se vuelve a abrir)
        self.assertEqual(r.descartados + sum(1 for p in self.alm.procesados_correo(bid, incluir_descartados=True)
                                             if p["estado"] == "descartado"), 1)
        falso.abiertos.clear()
        r = self.revisar(bid, falso)
        self.assertEqual(falso.abiertos, [])
        self.assertEqual(len(self.alm.procesados_correo(bid)), 3)
        # sin nada nuevo no se llena el historial
        self.assertEqual(len(self.alm.historial(correo_id=bid)), 3)

    def test_sesion_caducada(self):
        cid = self.cuenta()
        bid = self.busqueda(cid)
        r = self.revisar(bid, AdaptadorFalso(buzon(), sesion=False))
        self.assertFalse(r.ok)
        self.assertTrue(r.sesion_caducada)
        self.assertEqual(self.alm.cuenta_correo(cid)["estado_sesion"], "caducada")
        n = [x for x in self.alm.notificaciones() if x["tipo"] == "correo_sesion"]
        self.assertEqual(len(n), 1)
        self.assertIn("Iniciar sesión en el correo", n[0]["texto"])
        self.assertEqual(self.alm.historial(correo_id=bid)[0]["resultado"], "error")
        # vuelve a funcionar: la cuenta queda «ok» y el aviso se da por leído
        r = self.revisar(bid, AdaptadorFalso(buzon()))
        self.assertTrue(r.ok)
        self.assertEqual(self.alm.cuenta_correo(cid)["estado_sesion"], "ok")
        self.assertTrue(self.alm.notificacion(n[0]["id"])["leida"])

    def test_un_correo_que_no_se_abre_no_para_los_demas(self):
        bid = self.busqueda(criterios={"asunto": "RESUMEN DE VENTAS EMPRESA", "cuerpo": ["Total ventas"]},
                            acciones=[{"tipo": "texto", "etiqueta": "Total ventas:"}])
        falso = AdaptadorFalso(buzon())
        abrir = falso.abrir

        def abrir_que_falla(m):
            if m["_id"] == "a2":
                raise correo.ErrorProveedor("Outlook no mostró el cuerpo del correo")
            return abrir(m)
        falso.abrir = abrir_que_falla
        r = self.revisar(bid, falso)
        self.assertTrue(r.ok)
        self.assertEqual([p["valores"][0][1] for p in r.procesados], ["1.234"])     # (a5 no dice «Total ventas»)
        self.assertIn("1 correo(s) no se pudieron abrir", r.resumen())
        self.assertEqual(self.alm.historial(correo_id=bid)[0]["resultado"], "error")
        falso.abrir = abrir                                     # la próxima vez se abre (no se había apuntado)
        r = self.revisar(bid, falso)
        self.assertEqual([p["valores"] for p in r.procesados], [[("Total ventas", "1001")]])

    def test_varias_busquedas_de_la_misma_cuenta_un_solo_buzon(self):
        cid = self.cuenta()
        b1 = self.busqueda(cid)
        b2 = self.busqueda(cid, nombre="Cobros", criterios={"remitente": "noticias@ejemplo.org", "fecha": "hoy"},
                           acciones=[{"tipo": "cuerpo", "formato": "txt"}])
        falso = AdaptadorFalso(buzon())
        res = correo.revisar_varias(self.alm, [b1, b2], falso, self.base, HOY)
        self.assertEqual(falso.entradas, 1)
        self.assertEqual([len(r.procesados) for r in res], [3, 1])
        # con la sesión caducada, ninguna se revisa y las dos lo dicen
        res = correo.revisar_varias(self.alm, [b1, b2], AdaptadorFalso(buzon(), sesion=False), self.base, HOY)
        self.assertTrue(all(r.sesion_caducada for r in res))
        self.assertEqual(len(res), 2)

    def test_probar_no_procesa(self):
        bid = self.busqueda()
        falso = AdaptadorFalso(buzon())
        res = correo.probar_busqueda(falso, self.alm.busqueda_correo(bid)["criterios"], HOY, almacen=self.alm,
                                     busqueda_id=bid)
        self.assertEqual([(m["asunto"][-10:], m["coincide"]) for m in res],
                         [("29/10/2026", True), ("28/10/2026", True), ("27/10/2026", True)])
        self.assertEqual(res[0]["adjuntos"], [ADJ])
        self.assertEqual(self.alm.procesados_correo(bid, incluir_descartados=True), [])
        self.assertEqual(falso.descargados, [])


# ============================================================================ IMAP (servidor falso)
def correo_mime(uid, asunto, remitente, fecha, texto, adjuntos=(), html=None):
    m = email.message.EmailMessage()
    m["Subject"], m["From"], m["To"] = asunto, remitente, "yo@ejemplo.com"
    m["Date"] = email.utils.format_datetime(fecha.astimezone())
    m["Message-ID"] = "<%s@ejemplo.com>" % uid
    m.set_content(texto)
    if html:
        m.add_alternative(html, subtype="html")
    for n, datos in adjuntos:
        m.add_attachment(datos, maintype="application", subtype="octet-stream", filename=n)
    return m.as_bytes()


class ImapFalso:
    """Lo que usa el bot de imaplib.IMAP4_SSL, en memoria."""
    correos = {}
    clave = "clave-de-aplicacion"
    instancias = []

    def __init__(self, host, puerto, ssl_context=None, timeout=None):
        self.host, self.puerto = host, puerto
        self.seleccion = None
        self.busquedas = []
        self.marcados = []
        ImapFalso.instancias.append(self)

    def login(self, usuario, clave):
        if clave != self.clave:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def select(self, carpeta, readonly=False):
        self.seleccion = (carpeta, readonly)
        return ("OK", [b"5"]) if carpeta == "INBOX" else ("NO", [b"no existe"])

    def response(self, que):
        return que, [b"77"]

    def uid(self, orden, *args):
        if orden == "SEARCH":
            crit = list(args[1:])
            self.busquedas.append(crit)
            res = []
            for uid, crudo in sorted(self.correos.items()):
                m = email.message_from_bytes(crudo)
                ok = True
                if "FROM" in crit:
                    ok = ok and crit[crit.index("FROM") + 1].strip('"').lower() in str(m["From"]).lower()
                if "SUBJECT" in crit:
                    ok = ok and crit[crit.index("SUBJECT") + 1].strip('"').lower() in str(m["Subject"]).lower()
                if "SINCE" in crit:
                    desde = dt.datetime.strptime(crit[crit.index("SINCE") + 1], "%d-%b-%Y").date()
                    ok = ok and email.utils.parsedate_to_datetime(m["Date"]).date() >= desde
                if ok:
                    res.append(str(uid))
            return "OK", [" ".join(res).encode()]
        if orden == "FETCH":
            uid, que = args
            crudo = self.correos[int(uid)]
            if "HEADER.FIELDS" in que:
                cab = crudo.split(b"\n\n", 1)[0] if b"\n\n" in crudo else crudo.split(b"\r\n\r\n", 1)[0]
                return "OK", [(b"1 (UID %s BODY[HEADER] {%d}" % (uid.encode(), len(cab)), cab), b")"]
            if "BODY.PEEK[]" not in que:
                raise AssertionError("el bot debe leer con BODY.PEEK (sin marcar como leído)")
            return "OK", [(b"1 (UID %s BODY[] {%d}" % (uid.encode(), len(crudo)), crudo), b")"]
        if orden == "STORE":
            self.marcados.append(args)
        raise AssertionError("orden IMAP inesperada: %s" % orden)

    def close(self):
        return "OK", []

    def logout(self):
        return "BYE", []


class TestImap(Base):
    def setUp(self):
        super().setUp()
        ImapFalso.instancias = []
        ImapFalso.correos = {
            1: correo_mime("u1", ASUNTO % "19/10/2026", "Reportes Ventas <reportes@ejemplo.com>", HOY - dt.timedelta(days=10),
                           "Total ventas: 555", [(ADJ, b"viejo")]),
            2: correo_mime("u2", ASUNTO % "28/10/2026", "Reportes Ventas <reportes@ejemplo.com>", HOY - dt.timedelta(days=1),
                           "Total ventas: 987", [(ADJ, b"de ayer")]),
            3: correo_mime("u3", "Novedades", "Boletín <noticias@ejemplo.org>", HOY - dt.timedelta(hours=1), "Nada"),
            4: correo_mime("u4", ASUNTO % "29/10/2026", "Reportes Ventas <reportes@ejemplo.com>", HOY - dt.timedelta(hours=2),
                           "Total ventas: 1.234", [(ADJ, b"de hoy"), ("Otro.csv", b"a;b")],
                           html="<p>Total ventas: <b>1.234</b></p>"),
        }
        p = mock.patch.object(correo_imap.imaplib, "IMAP4_SSL", ImapFalso)
        p.start()
        self.addCleanup(p.stop)
        self.cid = self.alm.guardar_cuenta_correo({"proveedor": "imap", "nombre": "Gmail IMAP", "host": "imap.ejemplo.com",
                                                   "direccion": "yo@ejemplo.com"})

    def abrir(self, cuenta):
        return correo.crear_adaptador(cuenta, os.path.join(self.tmp, "p"))

    def test_revisar_por_imap(self):
        bid = self.busqueda(self.cid)
        r = correo.revisar_busqueda(self.alm, bid, self.abrir, self.base, HOY)
        self.assertTrue(r.sesion_caducada)                       # sin contraseña guardada: se dice claro
        self.assertIn("Falta la contraseña IMAP", r.error)
        secretos.guardar(correo.secreto_de_cuenta(self.cid), "otra")
        r = correo.revisar_busqueda(self.alm, bid, self.abrir, self.base, HOY)
        self.assertTrue(r.sesion_caducada)
        self.assertIn("contraseña de aplicación", r.error)
        secretos.guardar(correo.secreto_de_cuenta(self.cid), ImapFalso.clave)
        r = correo.revisar_busqueda(self.alm, bid, self.abrir, self.base, HOY)
        self.assertTrue(r.ok, r.error)
        srv = ImapFalso.instancias[-1]
        self.assertEqual(srv.seleccion, ("INBOX", True))                          # solo lectura
        self.assertEqual(srv.busquedas[-1], ["SINCE", "22-Oct-2026", "BEFORE", "30-Oct-2026", "FROM",
                                             '"reportes@ejemplo.com"', "SUBJECT", '"RESUMEN DE VENTAS EMPRESA"'])
        self.assertEqual([(p["valores"], [os.path.basename(a) for a in p["archivos"]]) for p in r.procesados],
                         [([("Total ventas", "1.234")], ["Ventas 2026-10-29.xlsx"]),
                          ([("Total ventas", "987")], ["Ventas 2026-10-28.xlsx"])])
        with open(os.path.join(self.base, "migracion", "Ventas 2026-10-29.xlsx"), "rb") as f:
            self.assertEqual(f.read(), b"de hoy")
        self.assertTrue(r.procesados[0]["clave"].startswith("imap:<u4@ejemplo.com>"))
        r = correo.revisar_busqueda(self.alm, bid, self.abrir, self.base, HOY)
        self.assertEqual((len(r.procesados), r.ya_procesados), (0, 2))
        # la contraseña nunca va a la base de datos
        with open(self.alm.ruta, "rb") as f:
            self.assertNotIn(ImapFalso.clave.encode(), f.read())

    def test_probar_conexion_y_carpeta(self):
        secretos.guardar(correo.secreto_de_cuenta(self.cid), ImapFalso.clave)
        self.assertIn("tiene 4 correo(s)", correo_imap.probar_conexion(self.alm.cuenta_correo(self.cid)))
        self.alm.guardar_cuenta_correo(dict(self.alm.cuenta_correo(self.cid), carpeta="Reportes"), self.cid)
        with self.assertRaisesRegex(correo.ErrorProveedor, "No existe la carpeta"):
            correo_imap.probar_conexion(self.alm.cuenta_correo(self.cid))


# ============================================================================ API de la interfaz
class TestApiCorreo(Base):
    def setUp(self):
        super().setUp()
        self.tareas = []
        self.llamadas = []

        def ejecutar(cmd):
            self.llamadas.append(list(cmd))
            if "/XML" in cmd:
                with open(cmd[cmd.index("/XML") + 1], "rb") as f:
                    self.llamadas[-1].append(f.read().decode("utf-16"))
                self.tareas.append({"nombre": cmd[cmd.index("/TN") + 1].split("\\", 1)[1], "proxima": "30/10/2026 9:00:00",
                                    "estado": "Listo"})
            elif "/Delete" in cmd:
                n = cmd[cmd.index("/TN") + 1].split("\\", 1)[1]
                self.tareas[:] = [t for t in self.tareas if t["nombre"] != n]
            return 0, "CORRECTO"
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                                 carpeta_descargas=self.base, listar_tareas=lambda: list(self.tareas),
                                 oculto_forzado=True, ejecutar_tareas=ejecutar, hoy=HOY)

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})

    def error(self, metodo, ruta, datos=None):
        with self.assertRaises(su.ErrorApi) as e:
            self.api(metodo, ruta, datos)
        return str(e.exception)

    def test_cuentas(self):
        d = self.api("GET", "correo")
        self.assertEqual((d["cuentas"], d["busquedas"]), ([], []))
        self.assertIn("outlook_web", d["proveedores"])
        self.assertTrue(d["hay_excel"])
        c = self.api("POST", "correo/cuentas", {"proveedor": "imap", "nombre": "Gmail", "host": "imap.gmail.com",
                                                "direccion": "yo@ejemplo.com", "contrasena": "abcd efgh ijkl mnop"})["cuenta"]
        self.assertTrue(c["tiene_clave"])
        self.assertEqual(secretos.obtener(correo.secreto_de_cuenta(c["id"])), "abcd efgh ijkl mnop")
        with open(self.alm.ruta, "rb") as f:
            self.assertNotIn(b"abcd efgh", f.read())
        c = self.api("PUT", "correo/cuentas/%d" % c["id"], {"puerto": 1993})["cuenta"]
        self.assertEqual((c["puerto"], c["host"]), (1993, "imap.gmail.com"))
        self.assertIn("servidor IMAP", self.error("POST", "correo/cuentas", {"proveedor": "imap"}))
        o = self.api("POST", "correo/cuentas", {"nombre": "Empresa", "direccion": "reportes@ejemplo.com"})["cuenta"]
        self.assertEqual((o["proveedor"], o["estado_sesion"], o["perfil_guardado"]), ("outlook_web", "", False))
        self.assertEqual(o["url_efectiva"], correo.URL_OUTLOOK)
        self.api("DELETE", "correo/cuentas/%d" % c["id"])
        self.assertIsNone(secretos.obtener(correo.secreto_de_cuenta(c["id"])))

    def test_busquedas_programar_y_inicio(self):
        cid = self.api("POST", "correo/cuentas", {"nombre": "Empresa"})["cuenta"]["id"]
        datos = {"nombre": "Ventas diarias", "cuenta_id": cid,
                 "criterios": {"asunto": "RESUMEN DE VENTAS MI EMPRESA", "fecha": "ultimos", "dias": 7},
                 "acciones": [{"tipo": "adjuntos", "coincide": "SUPERVISION VENTAS",
                               "nombre": "Ventas {fecha_correo:%Y-%m-%d}.xlsx",
                               "carpeta": os.path.join(self.tmp, "migracion")},
                              {"tipo": "texto", "etiqueta": "Total ventas:"}],
                 "programacion": {"reglas": [{"tipo": "semanal", "dias": ["lun", "mar", "mie", "jue", "vie"],
                                              "horas": ["09:00", "15:00"]}]}}
        b = self.api("POST", "correo/busquedas", datos)["busqueda"]
        self.assertEqual(b["cuando"], "de lunes a viernes a las 09:00 y 15:00")
        self.assertEqual(b["tarea"], {"existe": False, "nombres": [], "proxima": ""})
        self.assertEqual(b["acciones_texto"][1], "Copiar «Total ventas» (después de «Total ventas:»)")
        self.assertIn("asunto con «RESUMEN DE VENTAS MI EMPRESA»", b["que_texto"])
        self.assertIn("Añade al menos una acción", self.error("POST", "correo/busquedas", dict(datos, nombre="x",
                                                                                                acciones=[])))
        self.assertIn("Ya hay una búsqueda", self.error("POST", "correo/busquedas", datos))
        # «Próximas» del inicio: con horario y SIN tarea de Windows
        prox = [p for p in self.api("GET", "inicio")["proximas"] if p.get("correo_id") == b["id"]]
        self.assertEqual(len(prox), 1)
        self.assertTrue(prox[0]["sin_tarea"])
        # programar: primero se enseña (nada se crea), después se crea con confirmar
        pr = self.api("POST", "correo/busquedas/%d/programar" % b["id"], {})
        self.assertFalse(pr["creada"])
        self.assertEqual(self.llamadas, [])
        self.assertIn("--correo-id %d --oculto" % b["id"], pr["programa"])
        self.assertIn("schtasks /Create /XML", pr["comando"])
        self.assertEqual(pr["tarea"], "BotWeb\\Correo Ventas diarias #%d" % b["id"])
        pr = self.api("POST", "correo/busquedas/%d/programar" % b["id"], {"confirmar": True})
        self.assertTrue(pr["creada"])
        self.assertEqual(self.alm.programacion("correo:%d" % b["id"])["tarea"], "BotWeb\\Correo Ventas diarias #%d" % b["id"])
        b = self.api("GET", "correo/busquedas/%d" % b["id"])["busqueda"]
        self.assertTrue(b["tarea"]["existe"])
        prox = [p for p in self.api("GET", "inicio")["proximas"] if p.get("correo_id") == b["id"]]
        self.assertFalse(prox[0]["sin_tarea"])
        self.assertFalse(any(t.get("nombre", "").startswith("Correo ") for t in self.api("GET", "inicio")["proximas"]
                             if not t.get("correo_id")))
        # cambiar el horario lo dice (para ofrecer actualizar la tarea)
        r = self.api("PUT", "correo/busquedas/%d" % b["id"], {"programacion": {"reglas": []}})
        self.assertTrue(r["cambio_horario"])
        self.assertIn("no tiene horario", self.error("POST", "correo/busquedas/%d/programar" % b["id"], {}))
        q = self.api("POST", "correo/busquedas/%d/quitar_tarea" % b["id"], {})
        self.assertFalse(q["borrada"])
        self.api("POST", "correo/busquedas/%d/quitar_tarea" % b["id"], {"confirmar": True})
        self.assertEqual(self.tareas, [])
        # pausar, procesados, volver a procesar
        self.assertFalse(self.api("POST", "correo/busquedas/%d/activar" % b["id"], {"activa": False})["busqueda"]["activa"])
        self.alm.marcar_correo_procesado(b["id"], "k", "ok", asunto="A")
        self.assertEqual(len(self.api("GET", "correo/busquedas/%d/procesados" % b["id"])["procesados"]), 1)
        self.api("POST", "correo/busquedas/%d/reprocesar" % b["id"], {"clave": "k"})
        self.assertIn("no estaba apuntado", self.error("POST", "correo/busquedas/%d/reprocesar" % b["id"], {"clave": "k"}))
        # «Abrir archivo» vale en la carpeta absoluta de la acción
        self.assertIn(os.path.abspath(os.path.join(self.tmp, "migracion")), self.app._raices_permitidas())
        self.api("DELETE", "correo/busquedas/%d" % b["id"])
        self.assertEqual(self.api("GET", "correo")["busquedas"], [])

    def test_revisar_y_probar_lanzan_un_trabajo(self):
        cid = self.api("POST", "correo/cuentas", {"nombre": "Empresa"})["cuenta"]["id"]
        bid = self.busqueda(cid)
        falso = AdaptadorFalso(buzon())
        self.app._fabrica_correo = lambda t, ver=False, esperar_login=0: falso
        t = self.api("POST", "correo/busquedas/%d/revisar" % bid, {})
        self.app.trabajo.hilo.join(30)
        self.assertEqual(self.app.trabajo.estado, "error")              # (a5: su acción de texto falla)
        evs = [e for e in self.app.eventos.desde(0)[0] if e["tipo"] == "correo"]
        self.assertEqual((evs[0]["busqueda_id"], evs[0]["procesados"]), (bid, 3))
        self.assertEqual(t["tipo"], "correo")
        t = self.api("POST", "correo/probar", {"cuenta_id": cid, "criterios": {"asunto": "Novedades", "fecha": "hoy"}})
        self.app.trabajo.hilo.join(30)
        ev = [e for e in self.app.eventos.desde(0)[0] if e["tipo"] == "correo_prueba"][-1]
        self.assertEqual((ev["trabajo"], ev["ok"]), (t["id"], True))
        self.assertEqual([m["asunto"] for m in ev["mensajes"]], ["Novedades de la semana"])
        self.assertIn("Elige la cuenta", self.error("POST", "correo/probar", {"criterios": {"asunto": "x"}}))


# ============================================================================ línea de comandos y tareas
class TestCli(Base):
    def test_comando_de_la_tarea(self):
        linea = programador.comando_bot(os.path.join(RAIZ, "bot.py"), correo_id=4, python="py.exe")
        self.assertTrue(linea.endswith("--correo-id 4 --oculto"))
        self.assertTrue(programador.comando_bot("bot.py", correos=True, python="py.exe").endswith("--correos --oculto"))
        args = bot.analizar_argumentos(["--correo-id", "3", "--correo-id", "5", "--visible"])
        self.assertEqual((args.correo_id, args.visible), ([3, 5], True))

    def test_revisar_sin_ventana(self):
        cid = self.cuenta()
        bid = self.busqueda(cid, acciones=[{"tipo": "texto", "modo": "regex", "regex": r"ventas:\s*(\S+)"}])
        args = bot.analizar_argumentos(["--correo-id", str(bid), "--registros", os.path.join(self.tmp, "reg"),
                                        "--descargas", self.base, "--perfil", os.path.join(self.tmp, "p")])
        falso = AdaptadorFalso(buzon())
        import io
        import contextlib
        salida = io.StringIO()
        # (el día de los correos de prueba es HOY: sin fijarlo, «últimos 7 días» dejaba fuera los correos a partir del 05/11/2026)
        original = correo.revisar_varias
        p = mock.patch.object(correo, "revisar_varias", lambda *a, **k: original(*a, **dict(k, hoy=HOY)))
        p.start()
        self.addCleanup(p.stop)
        with contextlib.redirect_stdout(salida):
            self.assertEqual(bot.revisar_correo_sin_ventana(args, self.alm, abrir_adaptador=falso), 1)   # a5 falla
            self.assertEqual(bot.revisar_correo_sin_ventana(args, self.alm, abrir_adaptador=falso), 1)   # reintento
        self.assertIn("[correo %d]" % bid, salida.getvalue())
        args2 = bot.analizar_argumentos(["--correo-id", "999"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bot.revisar_correo_sin_ventana(args2, self.alm, abrir_adaptador=falso), 2)
        # sesión caducada → 1 y el aviso en el bot
        args3 = bot.analizar_argumentos(["--correos", "--registros", os.path.join(self.tmp, "reg"), "--descargas", self.base,
                                         "--perfil", os.path.join(self.tmp, "p")])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bot.revisar_correo_sin_ventana(args3, self.alm,
                                                            abrir_adaptador=AdaptadorFalso(buzon(), sesion=False)), 1)
        self.assertTrue(any(n["tipo"] == "correo_sesion" for n in self.alm.notificaciones()))
        self.alm.activar_busqueda_correo(bid, False)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bot.revisar_correo_sin_ventana(args3, self.alm, abrir_adaptador=falso), 2)


if __name__ == "__main__":
    unittest.main()
