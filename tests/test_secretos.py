"""Pruebas de secretos.py con un almacén en memoria (nunca toca el Administrador de credenciales real)."""

import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import secretos  # noqa: E402


class TestSecretos(unittest.TestCase):
    def setUp(self):
        self.mem = secretos.AlmacenMemoria()
        secretos.usar_almacen(self.mem)
        self.addCleanup(secretos.usar_almacen, None)

    def test_guardar_y_obtener(self):
        secretos.guardar("portal:clave", "s3creto!")
        self.assertEqual(secretos.obtener("portal:clave"), "s3creto!")
        self.assertTrue(secretos.existe("portal:clave"))
        self.assertIsNone(secretos.obtener("no-existe"))

    def test_obtener_requerida(self):
        with self.assertRaises(secretos.ErrorSecreto) as cm:
            secretos.obtener_requerida("falta")
        self.assertIn("falta", str(cm.exception))
        self.assertNotIn("s3creto", str(cm.exception))
        secretos.guardar("falta", "x")
        self.assertEqual(secretos.obtener_requerida("falta"), "x")

    def test_cambiar_valor(self):
        secretos.guardar("a", "1")
        secretos.guardar("a", "2")
        self.assertEqual(secretos.obtener("a"), "2")
        self.assertEqual(secretos.listar(), ["a"])

    def test_listar_solo_nombres_y_ordenados(self):
        secretos.guardar("b", "uno")
        secretos.guardar("a", "dos")
        self.assertEqual(secretos.listar(), ["a", "b"])
        self.assertNotIn("uno", str(secretos.listar()))

    def test_borrar(self):
        secretos.guardar("a", "1")
        secretos.borrar("a")
        self.assertIsNone(secretos.obtener("a"))
        self.assertEqual(secretos.listar(), [])
        secretos.borrar("a")      # borrar algo que no existe no falla

    def test_validaciones(self):
        for malo in ("", "   ", None):
            with self.assertRaises(secretos.ErrorSecreto):
                secretos.guardar(malo, "x")
        with self.assertRaises(secretos.ErrorSecreto):
            secretos.guardar("a", "")
        with self.assertRaises(secretos.ErrorSecreto):
            secretos.guardar("__indice__", "x")

    def test_el_indice_no_contiene_valores(self):
        secretos.guardar("a", "valor-secreto")
        indice = self.mem.datos[(secretos.SERVICIO, "__indice__")]
        self.assertNotIn("valor-secreto", indice)

    def test_errores_del_almacen_no_filtran_el_valor(self):
        class Roto:
            def set_password(self, *a):
                raise RuntimeError("fallo con valor-secreto")

            def get_password(self, *a):
                return None

        secretos.usar_almacen(Roto())
        with self.assertRaises(secretos.ErrorSecreto) as cm:
            secretos.guardar("a", "valor-secreto")
        self.assertNotIn("valor-secreto", str(cm.exception))

    def test_el_almacen_es_inyectable_y_se_restaura(self):
        otro = secretos.AlmacenMemoria()
        secretos.usar_almacen(otro)
        secretos.guardar("z", "1")
        self.assertEqual(len(self.mem.datos), 0)
        self.assertGreater(len(otro.datos), 0)


if __name__ == "__main__":
    unittest.main()
