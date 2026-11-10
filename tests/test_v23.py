"""Pruebas unitarias de la versión 2.3: paso «Iniciar sesión», conversión de los reportes guardados (con copia
de seguridad que se puede restaurar), accesos por sitio y textos que cambian cada día.

No abren el navegador.  Las bases de datos son temporales y las contraseñas viven en memoria.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import VERSION, accesos, secretos  # noqa: E402
from webbot import flujo as mod_flujo  # noqa: E402
from webbot.almacen import Almacen, ErrorAlmacen  # noqa: E402
from webbot.flujo import Flujo, Paso, agrupar_inicio_sesion, migrar_flujo  # noqa: E402

# --- formas reales (registros/2026-10-24_113431.log y 2026-10-24_114805.log) -----------------------------

RUTA_PORTAL = ("#app > div:nth-of-type(1) > div:nth-of-type(1) > main:nth-of-type(1) > div:nth-of-type(1) > "
              "div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(3) > form:nth-of-type(1) > button:nth-of-type(1)")


def pasos_portal_metricas():
    return [
        {"tipo": "abrir_url", "url": "https://portal.ejemplo.com/portal/#/inicio-sesion"},
        {"tipo": "escribir", "selectores": ["#input-v-0", "input[placeholder=\"Usuario (código)\"]"],
         "valor": "100000001", "objetivo": "Usuario (código)", "espera_grabada": 19.9},
        {"tipo": "clic", "selectores": ["role=button[name=\"appended action\"]", "i[aria-label=\" appended action\"]",
                                        "i.mdi-eye.mdi"], "objetivo": "appended action", "espera_grabada": 4.8},
        {"tipo": "escribir", "selectores": ["#input-v-2", "input[placeholder=\"Contraseña\"]"],
         "valor": "{secreto:portal.ejemplo.com:input-v-2}", "objetivo": "Contraseña", "espera_grabada": 3.1},
        {"tipo": "clic", "selectores": ["role=button[name=\"Iniciar Sesion\"]", "button.v-btn.v-btn--block", RUTA_PORTAL],
         "objetivo": "Iniciar Sesion", "espera_grabada": 0.1},
        {"tipo": "clic", "selectores": ["role=link[name=\"Reportes\"]"], "objetivo": "Reportes", "espera_grabada": 3.5},
        {"tipo": "clic", "selectores": ["role=button[name=\"Generar\"]"], "objetivo": "Generar"},
    ]


def pasos_portal_recaudos():
    """Se grabó un primer intento con el usuario mal escrito; luego se corrigió y se volvió a pulsar «Iniciar Sesion»."""
    p = pasos_portal_metricas()
    usuario_mal = dict(p[1], valor="10000002")
    return [p[0], usuario_mal, p[3], p[4], dict(p[1]), p[2], p[4], p[5]]


def pasos_erp():
    return [
        {"tipo": "abrir_url", "url": "https://erp.ejemplo.com/app_1000_login.aspx"},
        {"tipo": "escribir", "selectores": ["#ctl00_formContent_txtLicencia_I", "input[name=\"ctl00$formContent$txtLicencia\"]"],
         "valor": "LIC0001", "objetivo": "ctl00$formContent$txtLicencia", "espera_grabada": 0.1},
        {"tipo": "escribir", "selectores": ["#ctl00_formContent_txtContrasenia_I_CLND"],
         "valor": "{secreto:erp.ejemplo.com:ctl00_formContent_txtContrasenia_I_CLND}",
         "objetivo": "ctl00_formContent_txtContrasenia_I_CLND", "espera_grabada": 16.0},
        {"tipo": "escribir", "selectores": ["#ctl00_formContent_txtUsuario_I", "input[name=\"ctl00$formContent$txtUsuario\"]"],
         "valor": "usuario.demo   ", "objetivo": "ctl00$formContent$txtUsuario", "espera_grabada": 0.0},
        {"tipo": "escribir", "selectores": ["#ctl00_formContent_txtContrasenia_I", "input[name=\"ctl00$formContent$txtContrasenia\"]"],
         "valor": "{secreto:erp.ejemplo.com:ctl00$formContent$txtContrasenia}",
         "objetivo": "ctl00$formContent$txtContrasenia", "espera_grabada": 9.4},
        {"tipo": "clic", "selectores": [".dxb span:text-is(\"Aceptar\")", "span.dx-vam:text-is(\"Aceptar\")",
                                        "#ctl00_formContent_btnAceptar_CD > span:nth-of-type(1)"], "objetivo": "Aceptar"},
        {"tipo": "pasar_raton", "selectores": ["#ctl00_formContent_mainMenu"], "objetivo": "Servicio al Cliente", "auto": True},
        {"tipo": "clic", "selectores": [".dxm-content span:text-is(\"Registro De Asistencia\")"],
         "objetivo": "Registro De Asistencia"},
    ]


def flujo_v2(nombre, pasos):
    return {"version": 2, "nombre": nombre, "url": pasos[0]["url"], "variables": {}, "opciones": {"timeout_paso": 60},
            "pasos": pasos}


class TestPasoIniciarSesion(unittest.TestCase):
    def paso(self):
        return Paso("iniciar_sesion", sitio="portal.example.com", enviar={"selectores": ["#entrar"], "objetivo": "Entrar"},
                    campos=[{"selectores": ["#u"], "etiqueta": "Usuario", "tipo": "texto", "clave": "u", "valor": "{cliente}"},
                            {"selectores": ["#p"], "etiqueta": "Contraseña", "tipo": "clave", "clave": "p",
                             "secreto": "portal.example.com:p"}])

    def test_descripcion_y_json(self):
        p = self.paso()
        self.assertEqual(p.descripcion(), "Iniciar sesión en «portal.example.com» (si hace falta)")
        self.assertIn("contraseña «portal.example.com:p»", p.detalle())
        self.assertIn("enviar con «Entrar»", p.detalle())
        self.assertEqual(p.problemas(), [])
        f = Flujo(nombre="X", pasos=[Paso("abrir_url", url="http://portal.example.com/"), p], variables={"cliente": "a"})
        f2 = Flujo.desde_json(f.a_json())
        self.assertEqual(f2.a_dict(), f.a_dict())
        self.assertEqual(f2.version, 3)
        self.assertEqual(f.variables_necesarias(), [])
        self.assertEqual(Flujo(pasos=[p]).variables_necesarias(), ["cliente"])
        # las contraseñas de los pasos «Iniciar sesión» no se exigen al empezar (se piden si faltan)
        self.assertEqual(f.secretos_necesarios(), ["portal.example.com:p"])
        self.assertEqual(f.secretos_necesarios(incluir_inicio_sesion=False), [])

    def test_problemas(self):
        self.assertTrue(Paso("iniciar_sesion").problemas())
        p = self.paso()
        p.campos[0]["tipo"] = "raro"
        self.assertTrue(any("no válido" in x for x in p.problemas()))

    def test_opcion_y_paso_esperar_carga(self):
        f = Flujo()
        self.assertIs(f.opcion("esperar_carga"), True)
        p = Paso.desde_dict({"tipo": "clic", "selectores": ["#a"], "esperar_carga": 0})
        self.assertIs(p.esperar_carga, False)
        self.assertNotIn("esperar_carga", Paso("clic", selectores=["#a"]).a_dict())


class TestTextosQueCambian(unittest.TestCase):
    def test_fragmentos(self):
        t = "ACME Detalles De Ventas Mayorista 24/10/2026 11:32 Canal X"
        self.assertTrue(mod_flujo.texto_volatil(t))
        self.assertEqual(mod_flujo.fragmentos_estables(t), ["ACME Detalles De Ventas Mayorista", "Canal X"])
        self.assertEqual(mod_flujo.etiqueta_estable(t), "ACME Detalles De Ventas Mayorista")
        self.assertFalse(mod_flujo.texto_volatil("Reporte listo"))
        self.assertEqual(mod_flujo.fragmentos_estables("Reporte listo"), ["Reporte listo"])
        self.assertTrue(mod_flujo.texto_volatil("Folio 1234567"))

    def test_coincide_otro_dia(self):
        grabado = "ACME Detalles De Ventas Mayorista 24/10/2026 11:32 Canal X"
        hoy = "Menú  ACME Detalles De Ventas Mayorista 25/10/2026 08:01 Canal X  Descargar"
        self.assertTrue(mod_flujo.coincide_texto_estable(hoy, grabado))
        self.assertFalse(mod_flujo.coincide_texto_estable("Canal X ... ACME Detalles De Ventas Mayorista", grabado))
        self.assertTrue(mod_flujo.coincide_texto_estable("a Reporte  listo b", "Reporte listo"))


class TestAgrupar(unittest.TestCase):
    def test_portal_metricas_con_ojito(self):
        f = Flujo.desde_dict(flujo_v2("Portal, metricas", pasos_portal_metricas()))
        msgs = migrar_flujo(f)
        self.assertEqual([p.tipo for p in f.pasos], ["abrir_url", "iniciar_sesion", "clic", "clic"])
        login = f.pasos[1]
        self.assertEqual(login.sitio, "portal.ejemplo.com")
        self.assertEqual([(c["etiqueta"], c["tipo"]) for c in login.campos],
                         [("Usuario (código)", "texto"), ("Contraseña", "clave")])
        self.assertEqual(login.campos[0]["valor"], "100000001")
        self.assertEqual(login.campos[1]["secreto"], "portal.ejemplo.com:input-v-2")
        self.assertNotIn("valor", login.campos[1])
        self.assertEqual(login.enviar["objetivo"], "Iniciar Sesion")
        self.assertEqual(login.espera_grabada, 19.9)
        self.assertEqual(len(msgs), 1)
        self.assertIn("pasos 2 a 5", msgs[0])
        self.assertEqual(f.version, 3)

    def test_portal_recaudos_reintento(self):
        f = Flujo.desde_dict(flujo_v2("Portal, Recaudos", pasos_portal_recaudos()))
        migrar_flujo(f)
        self.assertEqual([p.tipo for p in f.pasos], ["abrir_url", "iniciar_sesion", "clic"])
        self.assertEqual(f.pasos[1].campos[0]["valor"], "100000001")         # vale el último intento
        self.assertEqual(f.pasos[2].objetivo, "Reportes")

    def test_erp_con_clon_de_devexpress(self):
        f = Flujo.desde_dict(flujo_v2("ERP", pasos_erp()))
        migrar_flujo(f)
        self.assertEqual([p.tipo for p in f.pasos], ["abrir_url", "iniciar_sesion", "pasar_raton", "clic"])
        login = f.pasos[1]
        self.assertEqual([c["etiqueta"] for c in login.campos], ["Licencia", "Usuario", "Contrasenia"])
        self.assertEqual(login.campos[0]["valor"], "LIC0001")
        self.assertEqual(login.campos[1]["valor"], "usuario.demo   ")
        self.assertEqual(login.campos[2]["secreto"], "erp.ejemplo.com:ctl00$formContent$txtContrasenia")
        self.assertTrue(all("_CLND" not in c["selectores"][0] for c in login.campos))     # el clon sobra
        self.assertEqual(login.enviar["objetivo"], "Aceptar")
        self.assertEqual(login.problemas(), [])

    def test_no_se_toca_sin_contrasena_guardada_ni_fuera_del_principio(self):
        pasos = pasos_portal_metricas()
        pasos[3]["valor"] = "en-claro"                          # contraseña escrita en claro: no se convierte
        f = Flujo.desde_dict(flujo_v2("X", pasos))
        self.assertEqual(migrar_flujo(f), [])
        self.assertEqual(len(f.pasos), len(pasos))
        pasos = pasos_portal_metricas()
        pasos.insert(1, {"tipo": "clic", "selectores": ["#otra-cosa"], "objetivo": "Aceptar cookies"})
        f = Flujo.desde_dict(flujo_v2("Y", pasos))
        self.assertEqual(migrar_flujo(f), [])
        self.assertEqual(f.version, 3)

    def test_grabador_con_info_de_formulario(self):
        """Clic en el recuadro (td) antes del campo, ojito entre medias y Enter para entrar."""
        td = Paso("clic", selectores=["#td_usuario"], objetivo="td")
        u = Paso("escribir", selectores=["#usuario_I"], valor="demo", objetivo="Usuario")
        ojo = Paso("clic", selectores=["#ojo"], objetivo="ver")
        c = Paso("escribir", selectores=["#clave_I"], valor="{secreto:h:clave}", objetivo="Contraseña")
        enter = Paso("tecla", selectores=["#clave_I"], tecla="Enter")
        despues = Paso("clic", selectores=["#accion"], objetivo="Hacer acción")
        token = {"token": "L:h/login:clave", "host": "h"}
        info = {id(td): dict(token, rol="incidental"), id(u): dict(token, rol="campo"),
                id(ojo): dict(token, rol="incidental"), id(c): dict(token, rol="campo", clave=True),
                id(enter): dict(token, rol="campo")}
        pasos = [Paso("abrir_url", url="http://h/app.html"), td, u, ojo, c, enter, despues]
        nuevos, grupos = agrupar_inicio_sesion(pasos, info=info)
        self.assertEqual([p.tipo for p in nuevos], ["abrir_url", "iniciar_sesion", "clic"])
        self.assertEqual(nuevos[1].enviar, {"tecla": "Enter"})
        self.assertEqual(nuevos[1].sitio, "h")
        self.assertEqual(len(grupos), 1)
        # sin info del grabador (y sin estar al principio) no se agrupa nada
        self.assertEqual(len(agrupar_inicio_sesion(pasos)[0]), len(pasos))


class BaseDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v23_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ruta = os.path.join(self.tmp, "bot.db")
        self.alm = Almacen(self.ruta)
        self.addCleanup(self.alm.cerrar)

    def insertar_crudo(self, nombre, d):
        """Como los reportes que ya tiene el usuario: JSON de la versión 2 tal cual en la base de datos."""
        c = sqlite3.connect(self.ruta)
        try:
            cur = c.execute("INSERT INTO reportes(nombre, url, flujo, creado, modificado) VALUES (?, ?, ?, ?, ?)",
                            (nombre, d.get("url", ""), json.dumps(d, ensure_ascii=False), "2026-10-24 09:00:00",
                             "2026-10-24 09:00:00"))
            c.commit()
            return cur.lastrowid
        finally:
            c.close()


class TestMigracionEnBaseDeDatos(BaseDb):
    def test_convierte_con_copia_y_se_puede_restaurar(self):
        originales = {
            "Portal, metricas": flujo_v2("Portal, metricas", pasos_portal_metricas()),
            "Portal, Recaudos": flujo_v2("Portal, Recaudos", pasos_portal_recaudos()),
            "ERP": flujo_v2("ERP", pasos_erp()),
        }
        ids = {n: self.insertar_crudo(n, d) for n, d in originales.items()}
        sin_login = flujo_v2("Sin login", [{"tipo": "abrir_url", "url": "http://x/"}, {"tipo": "clic", "selectores": ["#a"]}])
        id_sin = self.insertar_crudo("Sin login", sin_login)
        ya_v3 = Flujo(nombre="Nuevo", url="http://y/", pasos=[Paso("abrir_url", url="http://y/")])
        id_v3 = self.alm.guardar(ya_v3)
        modificado_v3 = self.alm.obtener(id_v3)["modificado"]

        cambios = self.alm.migrar_formato()
        self.assertEqual(sorted(n for _, n, *_ in cambios), ["ERP", "Portal, Recaudos", "Portal, metricas"])
        for nombre, rid in ids.items():
            fl = self.alm.cargar_flujo(rid)
            self.assertEqual(fl.version, 3)
            self.assertEqual(fl.pasos[1].tipo, "iniciar_sesion", nombre)
            versiones = self.alm.versiones(rid)
            self.assertEqual(len(versiones), 1)
            self.assertIn("2.3", versiones[0]["motivo"])
            copia = self.alm.flujo_de_version(versiones[0]["id"])
            self.assertEqual(copia.version, 2)
            self.assertEqual(len(copia.pasos), len(originales[nombre]["pasos"]))
        # el que no tenía inicio de sesión: mismos pasos, versión nueva, y también con copia
        self.assertEqual([p.tipo for p in self.alm.cargar_flujo(id_sin).pasos], ["abrir_url", "clic"])
        self.assertEqual(len(self.alm.versiones(id_sin)), 1)
        # el que ya estaba en el formato nuevo no se toca
        self.assertEqual(self.alm.versiones(id_v3), [])
        self.assertEqual(self.alm.obtener(id_v3)["modificado"], modificado_v3)
        # una segunda vez no hace nada
        self.assertEqual(self.alm.migrar_formato(), [])
        self.assertEqual(len(self.alm.versiones(ids["ERP"])), 1)

        # restaurar: vuelve la versión 2 (y la convertida queda también como copia)
        rid = ids["Portal, metricas"]
        self.alm.renombrar(rid, "Portal métricas")
        self.alm.restaurar_version(self.alm.versiones(rid)[-1]["id"])
        fl = self.alm.cargar_flujo(rid)
        self.assertEqual(fl.version, 2)
        self.assertEqual([p.tipo for p in fl.pasos][:5], ["abrir_url", "escribir", "clic", "escribir", "clic"])
        self.assertEqual(fl.nombre, "Portal métricas")             # conserva el nombre actual
        self.assertEqual(len(self.alm.versiones(rid)), 2)
        with self.assertRaises(ErrorAlmacen):
            self.alm.restaurar_version(99999)

    def test_reporte_danado_no_se_toca(self):
        c = sqlite3.connect(self.ruta)
        c.execute("INSERT INTO reportes(nombre, url, flujo, creado, modificado) VALUES ('Roto', '', '{no es json', 'a', 'a')")
        c.commit()
        c.close()
        self.assertEqual(self.alm.migrar_formato(), [])
        self.assertEqual(self.alm.obtener_por_nombre("Roto")["flujo"], "{no es json")

    def test_importar_un_json_antiguo_lo_convierte(self):
        ruta = os.path.join(self.tmp, "erp.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(flujo_v2("ERP viejo", pasos_erp()), f)
        rid = self.alm.importar_archivo(ruta)
        self.assertEqual(self.alm.cargar_flujo(rid).pasos[1].tipo, "iniciar_sesion")


class TestAccesos(BaseDb):
    def test_guardar_listar_borrar(self):
        self.alm.guardar_acceso("Portal.Example.com", "usuario", "Usuario", "texto", valor="ana", selectores=["#u"])
        self.alm.guardar_acceso("portal.example.com", "clave", "Contraseña", "clave", valor="NO-SE-GUARDA",
                                secreto="portal.example.com:clave")
        self.alm.guardar_acceso("otro.com", "licencia", "Licencia", "texto", valor="L1")
        filas = self.alm.accesos_de("portal.example.com")
        self.assertEqual([(f["clave"], f["tipo"]) for f in filas], [("usuario", "texto"), ("clave", "clave")])
        self.assertEqual(filas[0]["selectores"], ["#u"])
        self.assertIsNone(filas[1]["valor"])                           # nunca el valor de una contraseña
        with sqlite3.connect(self.ruta) as c:
            todo = json.dumps(c.execute("SELECT * FROM accesos").fetchall())
        self.assertNotIn("NO-SE-GUARDA", todo)
        self.alm.guardar_acceso("portal.example.com", "usuario", "", "texto", valor="bea")
        filas = self.alm.accesos_de("portal.example.com")
        self.assertEqual((filas[0]["valor"], filas[0]["etiqueta"], filas[0]["selectores"]), ("bea", "Usuario", ["#u"]))
        self.assertEqual(len(self.alm.listar_accesos()), 3)
        self.alm.borrar_acceso("portal.example.com", "usuario")
        self.assertEqual(len(self.alm.accesos_de("portal.example.com")), 1)
        self.alm.borrar_acceso("portal.example.com")
        self.assertEqual(self.alm.accesos_de("portal.example.com"), [])
        with self.assertRaises(ErrorAlmacen):
            self.alm.guardar_acceso("", "x")

    def test_memoria_misma_interfaz(self):
        m = accesos.AccesosMemoria()
        m.guardar_acceso("H", "u", "Usuario", "texto", valor="x")
        m.guardar_acceso("h", "p", "Clave", "clave", valor="nunca", secreto="h:p")
        self.assertEqual([(a["clave"], a["valor"], a["secreto"]) for a in m.accesos_de("h")],
                         [("u", "x", None), ("p", None, "h:p")])
        m.borrar_acceso("h", "u")
        self.assertEqual(len(m.listar_accesos()), 1)

    def test_peticion(self):
        p = accesos.PeticionAcceso({"host": "h"})
        hilo = threading.Thread(target=lambda: p.responder({"valores": {"u": "1"}, "recordar": False}))
        hilo.start()
        self.assertTrue(p.evento.wait(5))
        hilo.join()
        self.assertEqual(p.respuesta["valores"], {"u": "1"})
        p.responder(None)                                   # una segunda respuesta no cambia nada
        self.assertIsNotNone(p.respuesta)
        q = accesos.PeticionAcceso({})
        q.cancelar()
        self.assertTrue(q.cancelada and q.evento.is_set() and q.respuesta is None)

    def test_mensajes(self):
        self.assertIn("Abre el bot y ejecútalo una vez con la ventana", accesos.MENSAJE_SIN_VENTANA % "h")
        self.assertIn("rechazada", accesos.MENSAJE_RECHAZADA)
        self.assertEqual(accesos.nombre_secreto("h", "c"), "h:c")
        self.assertEqual(VERSION, "3.6")          # v3.6 (rama New-tool)


class TestSecretosIntactos(unittest.TestCase):
    """La conversión no toca las contraseñas guardadas: los nombres siguen siendo los mismos."""

    def test_nombres(self):
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        f = Flujo.desde_dict(flujo_v2("ERP", pasos_erp()))
        antes = set(f.secretos_necesarios()) - {"erp.ejemplo.com:ctl00_formContent_txtContrasenia_I_CLND"}
        migrar_flujo(f)
        self.assertEqual(set(f.secretos_necesarios()), antes)


if __name__ == "__main__":
    unittest.main()
