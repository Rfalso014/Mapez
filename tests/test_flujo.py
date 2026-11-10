"""Pruebas de flujo.py: modelo, JSON, descripciones en español y validación."""

import json
import os
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import flujo as fl  # noqa: E402
from webbot.flujo import ErrorFlujo, Flujo, Paso  # noqa: E402


def flujo_completo():
    f = Flujo(nombre="Ventas", url="https://ejemplo.com/", variables={"cliente": "Acme"})
    f.opciones["timeout_paso"] = 20
    f.pasos = [
        Paso("abrir_url", url="https://ejemplo.com/"),
        Paso("escribir", selectores=["#usuario"], valor="demo", objetivo="Usuario"),
        Paso("escribir", selectores=["#clave"], valor="{secreto:ejemplo.com:clave}"),
        Paso("clic", selectores=['role=button[name="Entrar"]', "button:nth-of-type(1)"]),
        Paso("tecla", selectores=["#q"], tecla="Enter"),
        Paso("seleccionar", selectores=["#cli"], valor="{cliente}", etiqueta="Acme S.A."),
        Paso("marcar", selectores=["#todos"], marcado=False),
        Paso("esperar_elemento", selectores=["#resultado"], estado="visible", timeout=120),
        Paso("esperar_texto", texto="Reporte listo"),
        Paso("esperar_segundos", segundos=2.5),
        Paso("clic", selectores=["#resultado"], boton="derecho", pagina=1, marco=["iframe#panel"]),
        Paso("clic", selectores=["#x"], doble=True, opcional=True, nota="aviso"),
        Paso("descargar", selectores=["#m-csv"], nombre="Ventas_{hoy:%Y-%m-%d}{ext}", carpeta="ventas"),
    ]
    return f


class TestJson(unittest.TestCase):
    def test_ida_y_vuelta(self):
        f = flujo_completo()
        g = Flujo.desde_json(f.a_json())
        self.assertEqual(g.a_dict(), f.a_dict())
        self.assertEqual(g.pasos[10].marco, ["iframe#panel"])
        self.assertEqual(g.pasos[10].pagina, 1)
        self.assertEqual(g.opciones["timeout_paso"], 20)
        self.assertEqual(g.variables, {"cliente": "Acme"})

    def test_json_solo_guarda_lo_que_no_es_por_defecto(self):
        d = Paso("clic", selectores=["#a"]).a_dict()
        self.assertEqual(d, {"tipo": "clic", "selectores": ["#a"]})

    def test_archivo(self):
        f = flujo_completo()
        with tempfile.TemporaryDirectory() as t:
            ruta = os.path.join(t, "sub", "v.json")
            f.guardar(ruta)
            self.assertEqual(Flujo.cargar(ruta).a_dict(), f.a_dict())
            with open(ruta, encoding="utf-8") as fh:
                json.load(fh)          # JSON válido
            self.assertFalse(os.path.exists(ruta + ".tmp"))

    def test_json_invalido_y_version_futura(self):
        with self.assertRaises(ErrorFlujo):
            Flujo.desde_json("{no es json")
        with self.assertRaises(ErrorFlujo):
            Flujo.desde_dict({"version": 99, "pasos": []})
        with self.assertRaises(ErrorFlujo):
            Flujo.desde_dict({"pasos": [{"tipo": "volar"}]})
        with self.assertRaises(ErrorFlujo):
            Flujo.desde_dict({"pasos": [{"selectores": ["#a"]}]})

    def test_campos_desconocidos_se_ignoran_y_selector_texto(self):
        p = Paso.desde_dict({"tipo": "clic", "selectores": "#a", "futuro": 1})
        self.assertEqual(p.selectores, ["#a"])

    def test_opciones_por_defecto(self):
        f = Flujo.desde_dict({"pasos": []})
        self.assertEqual(f.opcion("navegador"), "chrome")
        self.assertEqual(f.opcion("timeout_paso"), 60)      # v2.1: antes 30
        self.assertEqual(f.opcion("timeout_descarga"), 600)

    def test_copia_es_independiente(self):
        f = flujo_completo()
        g = f.copia()
        g.pasos[0].url = "otra"
        g.pasos[3].selectores.append("x")
        self.assertEqual(f.pasos[0].url, "https://ejemplo.com/")
        self.assertEqual(len(f.pasos[3].selectores), 2)

    def test_aplicar_url(self):
        f = flujo_completo()
        f.aplicar_url("http://nueva/")
        self.assertEqual((f.url, f.pasos[0].url), ("http://nueva/", "http://nueva/"))
        g = Flujo(pasos=[Paso("clic", selectores=["#a"])])
        g.aplicar_url("http://nueva/")
        self.assertEqual(g.pasos[0].tipo, "abrir_url")


class TestDescripciones(unittest.TestCase):
    def setUp(self):
        self.d = [p.descripcion() for p in flujo_completo().pasos]

    def test_abrir(self):
        self.assertEqual(self.d[0], "Abrir la página https://ejemplo.com/")

    def test_escribir_usa_nombre_del_elemento(self):
        self.assertEqual(self.d[1], "Escribir «demo» en «Usuario»")

    def test_contrasena_nunca_se_muestra_como_valor(self):
        self.assertIn("la contraseña «ejemplo.com:clave»", self.d[2])
        self.assertEqual(self.d[2], "Escribir la contraseña «ejemplo.com:clave» en elemento #clave")

    def test_clic_con_rol_y_nombre(self):
        self.assertEqual(self.d[3], "Clic en botón «Entrar»")

    def test_resto_de_tipos(self):
        self.assertEqual(self.d[4], "Pulsar tecla Enter en elemento #q")
        self.assertEqual(self.d[5], "Seleccionar «Acme S.A.» en elemento #cli")
        self.assertEqual(self.d[6], "Desmarcar casilla elemento #todos")
        self.assertEqual(self.d[7], "Esperar hasta que aparezca elemento #resultado")
        self.assertEqual(self.d[8], "Esperar hasta que aparezca «Reporte listo»")
        self.assertEqual(self.d[9], "Esperar 2.5 segundos")
        self.assertEqual(self.d[12], "Descargar: elemento #m-csv → guardar como «Ventas_{hoy:%Y-%m-%d}{ext}» en ventas")

    def test_clic_derecho_doble_y_pestana(self):
        self.assertEqual(self.d[10], "Clic derecho en elemento #resultado (pestaña 2)")
        self.assertEqual(self.d[11], "Doble clic en elemento #x")

    def test_esperar_un_segundo_en_singular(self):
        self.assertEqual(Paso("esperar_segundos", segundos=1).descripcion(), "Esperar 1 segundo")

    def test_describir_selector(self):
        ds = fl.describir_selector
        self.assertEqual(ds('li:text-is("Exportar CSV")'), "«Exportar CSV»")
        self.assertEqual(ds('input[name="usuario"]'), "campo «usuario»")
        self.assertEqual(ds('[data-testid="enviar"]'), "«enviar»")
        self.assertEqual(ds('role=link[name="Ayuda"]'), "enlace «Ayuda»")
        self.assertEqual(ds(""), "(sin selector)")

    def test_acciones_para_la_lista(self):
        self.assertEqual(Paso("clic", boton="medio").accion(), "Clic central")
        self.assertEqual(Paso("marcar").accion(), "Marcar casilla")


class TestValidacion(unittest.TestCase):
    def test_flujo_correcto(self):
        self.assertEqual(flujo_completo().problemas(), [])

    def test_problemas(self):
        self.assertTrue(Paso("clic").problemas())
        self.assertTrue(Paso("abrir_url").problemas())
        self.assertTrue(Paso("esperar_texto").problemas())
        self.assertTrue(Paso("escribir", selectores=["#a"], valor="{hoy").problemas())
        self.assertTrue(Paso("clic", selectores=["#a"], boton="rueda").problemas())

    def test_variables_y_secretos_necesarios(self):
        f = flujo_completo()
        self.assertEqual(f.secretos_necesarios(), ["ejemplo.com:clave"])
        self.assertEqual(f.variables_necesarias(), [])
        f.pasos.append(Paso("escribir", selectores=["#m"], valor="{mes}"))
        self.assertEqual(f.variables_necesarias(), ["mes"])

    def test_slug(self):
        self.assertEqual(fl.slug("Ventas / Octubre: ¿ok?"), "Ventas _ Octubre_ _ok_")
        self.assertEqual(fl.slug("  "), "flujo")


if __name__ == "__main__":
    unittest.main()
