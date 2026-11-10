"""Pruebas del reproductor con controladores falsos (no mueven el ratón real)."""

import os
import sys
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import acciones as ac  # noqa: E402

try:
    import reproductor as rp  # noqa: E402
    from pynput import keyboard, mouse  # noqa: E402
    HAY_PYNPUT = True
except ImportError:  # pragma: no cover
    HAY_PYNPUT = False


class RatonFalso:
    def __init__(self):
        self.pos = (500, 500)
        self.registro = []

    @property
    def position(self):
        return self.pos

    @position.setter
    def position(self, valor):
        self.pos = tuple(valor)
        self.registro.append(("pos", time.perf_counter(), self.pos))

    def press(self, boton):
        self.registro.append(("press", time.perf_counter(), boton.name))

    def release(self, boton):
        self.registro.append(("release", time.perf_counter(), boton.name))

    def scroll(self, dx, dy):
        self.registro.append(("scroll", time.perf_counter(), (dx, dy)))


class TecladoFalso:
    def __init__(self):
        self.registro = []

    def press(self, tecla):
        self.registro.append(("press", time.perf_counter(), tecla))

    def release(self, tecla):
        self.registro.append(("release", time.perf_counter(), tecla))


def ejecutar(eventos, **kw):
    raton, teclado = RatonFalso(), TecladoFalso()
    resultado = {}
    pasos_vistos = []

    def al_fin(res, msg):
        resultado["res"], resultado["msg"] = res, msg

    def al_paso(i, rep, total):
        pasos_vistos.append((i, rep, total))
        if kw.get("en_paso"):
            kw["en_paso"](i, raton)

    r = rp.Reproductor(al_paso=al_paso, al_fin=al_fin, raton=raton, teclado=teclado)
    pasos = ac.agrupar(eventos)
    r.iniciar(eventos, pasos, velocidad=kw.get("velocidad", 1.0),
              repeticiones=kw.get("repeticiones", 1), cuenta=0)
    if kw.get("abortar_a"):
        time.sleep(kw["abortar_a"])
        r.abortar("prueba")
    r.esperar(10)
    return r, raton, teclado, resultado, pasos_vistos


@unittest.skipUnless(HAY_PYNPUT, "pynput no está instalado")
class PruebasReproductor(unittest.TestCase):
    def test_deserializar_teclas(self):
        self.assertIs(rp.deserializar_tecla("Key.enter"), keyboard.Key.enter)
        self.assertIsNone(rp.deserializar_tecla("Key.no_existe"))
        self.assertEqual(rp.deserializar_tecla("vk:67").vk, 67)
        self.assertEqual(rp.deserializar_tecla("a").char, "a")
        # con vk grabado se prefiere el vk (Ctrl+letra)
        self.assertEqual(rp.deserializar_tecla("a", 65).vk, 65)
        self.assertEqual(rp.deserializar_tecla("vk:67", 67).vk, 67)
        self.assertIsNone(rp.deserializar_tecla("??"))

    def test_orden_y_tiempos(self):
        ev = [ac.ev_mover(0.0, 10, 10),
              ac.ev_clic(0.10, 10, 10, "left", True),
              ac.ev_clic(0.20, 10, 10, "left", False),
              ac.ev_tecla(0.30, "a", True, 65),
              ac.ev_tecla(0.35, "a", False, 65)]
        t0 = time.perf_counter()
        r, raton, teclado, res, pasos = ejecutar(ev)
        self.assertEqual(res["res"], "completado")
        acciones_raton = [(k, v) for k, _, v in raton.registro]
        self.assertEqual(acciones_raton, [("pos", (10, 10)), ("pos", (10, 10)), ("press", "left"),
                                          ("pos", (10, 10)), ("release", "left")])
        # tiempos de la pulsación y la suelta (relativos al inicio)
        inicio = raton.registro[0][1]
        presionar = [t for k, t, _ in raton.registro if k == "press"][0] - inicio
        soltar = [t for k, t, _ in raton.registro if k == "release"][0] - inicio
        self.assertAlmostEqual(presionar, 0.10, delta=0.03)
        self.assertAlmostEqual(soltar, 0.20, delta=0.03)
        self.assertEqual([(k, t.vk) for k, _, t in teclado.registro], [("press", 65), ("release", 65)])
        self.assertLess(time.perf_counter() - t0, 1.5)

    def test_velocidad(self):
        ev = [ac.ev_mover(0.0, 1, 1), ac.ev_mover(0.8, 2, 2)]
        t0 = time.perf_counter()
        ejecutar(ev, velocidad=4.0)
        self.assertLess(time.perf_counter() - t0, 0.6)  # 0.8 s / 4 = 0.2 s
        t0 = time.perf_counter()
        ejecutar(ev, velocidad=1.0)
        self.assertGreater(time.perf_counter() - t0, 0.75)

    def test_repeticiones_y_resaltado_de_pasos(self):
        ev = [ac.ev_clic(0.0, 5, 5, "left", True), ac.ev_clic(0.02, 5, 5, "left", False),
              ac.ev_tecla(0.05, "Key.enter", True, 13), ac.ev_tecla(0.06, "Key.enter", False, 13)]
        r, raton, teclado, res, pasos = ejecutar(ev, repeticiones=3, velocidad=4)
        self.assertEqual(res["res"], "completado")
        self.assertEqual(pasos, [(0, 1, 3), (1, 1, 3), (0, 2, 3), (1, 2, 3), (0, 3, 3), (1, 3, 3)])
        self.assertEqual(sum(1 for k, _, _ in raton.registro if k == "press"), 3)

    def test_pausa_larga_resalta_el_paso_de_espera(self):
        ev = [ac.ev_mover(0.0, 1, 1), ac.ev_mover(1.5, 2, 2)]
        r, raton, teclado, res, pasos = ejecutar(ev, velocidad=4)
        self.assertEqual([p[0] for p in pasos], [0, 1, 2])  # mover, espera_auto, mover

    def test_abortar_suelta_todo_lo_pulsado(self):
        ev = [ac.ev_tecla(0.0, "Key.ctrl_l", True, 162),
              ac.ev_tecla(0.0, "vk:67", True, 67),
              ac.ev_clic(0.0, 9, 9, "left", True),
              ac.ev_mover(5.0, 1, 1)]   # largo: se aborta durante la espera
        r, raton, teclado, res, _ = ejecutar(ev, abortar_a=0.3)
        self.assertEqual(res["res"], "abortado")
        pulsadas = [t for k, _, t in teclado.registro if k == "press"]
        soltadas = [t for k, _, t in teclado.registro if k == "release"]
        self.assertEqual(len(pulsadas), 2)
        self.assertEqual(len(soltadas), 2)
        self.assertEqual(sum(1 for k, _, _ in raton.registro if k == "release"), 1)

    def test_failsafe_esquina_superior_izquierda(self):
        ev = [ac.ev_mover(0.0, 300, 300), ac.ev_mover(3.0, 400, 400)]

        def usuario_mueve_a_la_esquina(i, raton):
            raton.pos = (0, 0)

        r, raton, teclado, res, _ = ejecutar(ev, en_paso=usuario_mueve_a_la_esquina)
        self.assertEqual(res["res"], "abortado")
        self.assertIn("esquina", res["msg"])

    def test_la_grabacion_puede_llevar_el_raton_a_la_esquina(self):
        ev = [ac.ev_mover(0.0, 0, 0), ac.ev_mover(0.05, 100, 100)]
        r, raton, teclado, res, _ = ejecutar(ev)
        self.assertEqual(res["res"], "completado")

    def test_sin_eventos(self):
        r, raton, teclado, res, _ = ejecutar([])
        self.assertEqual(res["res"], "vacio")

    def test_scroll_y_esperar(self):
        ev = [ac.ev_scroll(0.0, 3, 3, 0, -2), ac.ev_esperar(0.0, 0.2),
              ac.ev_scroll(0.2, 3, 3, 0, 1)]
        r, raton, teclado, res, _ = ejecutar(ev)
        self.assertEqual([v for k, _, v in raton.registro if k == "scroll"], [(0, -2), (0, 1)])

    def test_tecla_desconocida_se_ignora(self):
        ev = [ac.ev_tecla(0.0, "Key.no_existe", True), ac.ev_tecla(0.01, "Key.no_existe", False)]
        r, raton, teclado, res, _ = ejecutar(ev)
        self.assertEqual(res["res"], "completado")
        self.assertEqual(teclado.registro, [])


def ejecutar_con_url(eventos, url=None, espera_carga=0.3, **kw):
    """Como ejecutar(), pero con abridor falso y parámetros de URL."""
    raton, teclado = RatonFalso(), TecladoFalso()
    abiertas = []
    resultado = {}
    r = rp.Reproductor(al_fin=lambda res, msg: resultado.update(res=res, msg=msg),
                       raton=raton, teclado=teclado,
                       abridor=lambda u: abiertas.append((time.perf_counter(), u)))
    r.iniciar(eventos, ac.agrupar(eventos), velocidad=kw.get("velocidad", 1.0),
              repeticiones=kw.get("repeticiones", 1), cuenta=0, url=url, espera_carga=espera_carga)
    r.esperar(10)
    return raton, abiertas, resultado


@unittest.skipUnless(HAY_PYNPUT, "pynput no está instalado")
class PruebasReproductorURL(unittest.TestCase):
    def grabacion(self, url="https://grabada.com"):
        base = [ac.ev_clic(0.0, 7, 7, "left", True), ac.ev_clic(0.05, 7, 7, "left", False)]
        return ac.anteponer_abrir_url(base, url, 0.4)

    def test_abre_la_url_grabada_y_espera_la_carga(self):
        ev = self.grabacion()
        t0 = time.perf_counter()
        raton, abiertas, res = ejecutar_con_url(ev)
        self.assertEqual(res["res"], "completado")
        self.assertEqual([u for _, u in abiertas], ["https://grabada.com"])
        press = [t for k, t, _ in raton.registro if k == "press"][0]
        self.assertAlmostEqual(press - abiertas[0][0], 0.4, delta=0.05)  # la línea de tiempo ya lleva la espera
        self.assertLess(abiertas[0][0] - t0, 0.2)

    def test_el_campo_url_reemplaza_solo_la_primera(self):
        ev = self.grabacion()
        ev = ev + [ac.ev_abrir_url(ev[-1]["t"] + 0.1, "https://segunda.com")]
        raton, abiertas, res = ejecutar_con_url(ev, url="otra.com")
        self.assertEqual([u for _, u in abiertas], ["https://otra.com", "https://segunda.com"])

    def test_misma_url_en_el_campo_no_cambia_nada(self):
        raton, abiertas, res = ejecutar_con_url(self.grabacion(), url="grabada.com")
        self.assertEqual([u for _, u in abiertas], ["https://grabada.com"])

    def test_no_modifica_los_eventos_originales(self):
        ev = self.grabacion()
        copia = [dict(e) for e in ev]
        ejecutar_con_url(ev, url="otra.com")
        self.assertEqual(ev, copia)

    def test_sin_abrir_url_pero_con_campo_abre_primero_y_espera(self):
        ev = [ac.ev_clic(0.0, 7, 7, "left", True), ac.ev_clic(0.02, 7, 7, "left", False)]
        raton, abiertas, res = ejecutar_con_url(ev, url="example.com", espera_carga=0.4)
        self.assertEqual(res["res"], "completado")
        self.assertEqual([u for _, u in abiertas], ["https://example.com"])
        press = [t for k, t, _ in raton.registro if k == "press"][0]
        self.assertAlmostEqual(press - abiertas[0][0], 0.4, delta=0.06)

    def test_sin_abrir_url_y_sin_campo_no_abre_nada(self):
        ev = [ac.ev_mover(0.0, 1, 1)]
        raton, abiertas, res = ejecutar_con_url(ev)
        self.assertEqual(abiertas, [])

    def test_con_repeticiones_se_abre_en_cada_pasada(self):
        raton, abiertas, res = ejecutar_con_url(self.grabacion(), repeticiones=2, velocidad=4)
        self.assertEqual(len(abiertas), 2)
        ev = [ac.ev_mover(0.0, 1, 1)]
        raton, abiertas, res = ejecutar_con_url(ev, url="x.com", espera_carga=0.05, repeticiones=2)
        self.assertEqual(len(abiertas), 2)

    def test_abrir_url_se_resalta_como_paso(self):
        ev = self.grabacion()
        vistos = []
        r = rp.Reproductor(al_paso=lambda i, rep, tot: vistos.append(i), raton=RatonFalso(),
                           teclado=TecladoFalso(), abridor=lambda u: None)
        r.iniciar(ev, ac.agrupar(ev), cuenta=0)
        r.esperar(10)
        self.assertEqual(vistos[0], 0)


if __name__ == "__main__":
    unittest.main()
