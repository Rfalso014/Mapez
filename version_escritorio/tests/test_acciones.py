"""Pruebas de acciones.py (sin pynput): agrupación, descripciones, JSON y teclas."""

import ast
import enum
import os
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import acciones as ac  # noqa: E402


class Linea:
    """Ayudante para construir secuencias de eventos con tiempo creciente."""

    def __init__(self):
        self.t = 0.0
        self.ev = []

    def avanzar(self, dt):
        self.t += dt
        return self

    def mover(self, x, y, dt=0.02):
        self.t += dt
        self.ev.append(ac.ev_mover(round(self.t, 4), x, y))
        return self

    def clic(self, x, y, boton="left", dt=0.05, duracion=0.06):
        self.t += dt
        self.ev.append(ac.ev_clic(round(self.t, 4), x, y, boton, True))
        self.t += duracion
        self.ev.append(ac.ev_clic(round(self.t, 4), x, y, boton, False))
        return self

    def pulsar(self, x, y, boton="left", dt=0.05):
        self.t += dt
        self.ev.append(ac.ev_clic(round(self.t, 4), x, y, boton, True))
        return self

    def soltar(self, x, y, boton="left", dt=0.05):
        self.t += dt
        self.ev.append(ac.ev_clic(round(self.t, 4), x, y, boton, False))
        return self

    def rueda(self, dy, x=5, y=5, dt=0.03):
        self.t += dt
        self.ev.append(ac.ev_scroll(round(self.t, 4), x, y, 0, dy))
        return self

    def tecla(self, nombre, presionada, vk=None, dt=0.03):
        self.t += dt
        self.ev.append(ac.ev_tecla(round(self.t, 4), nombre, presionada, vk))
        return self

    def tocar(self, nombre, vk=None, dt=0.05, duracion=0.04):
        self.tecla(nombre, True, vk, dt)
        return self.tecla(nombre, False, vk, duracion)

    def escribir(self, texto):
        for c in texto:
            self.tocar(c)
        return self


def descripciones(eventos):
    return [p.descripcion for p in ac.agrupar(eventos)]


class PruebasAgrupacion(unittest.TestCase):
    def test_clic_izquierdo(self):
        ev = Linea().clic(540, 320).ev
        pasos = ac.agrupar(ev)
        self.assertEqual(len(pasos), 1)
        self.assertEqual(pasos[0].descripcion, "Clic izquierdo en (540, 320)")
        self.assertEqual(pasos[0].tipo, "clic")
        self.assertEqual(pasos[0].indices, [0, 1])

    def test_clic_derecho_y_central(self):
        ev = Linea().clic(1, 2, "right").clic(3, 4, "middle", dt=1.5).ev
        self.assertEqual(descripciones(ev)[0], "Clic derecho en (1, 2)")
        self.assertIn("Clic central en (3, 4)", descripciones(ev))

    def test_clic_con_temblor_sigue_siendo_clic(self):
        ev = Linea().pulsar(100, 100).mover(102, 101).soltar(103, 100).ev
        pasos = ac.agrupar(ev)
        self.assertEqual([p.tipo for p in pasos], ["clic"])
        self.assertEqual(pasos[0].indices, [0, 1, 2])

    def test_doble_clic(self):
        ev = Linea().clic(50, 60).clic(50, 60, dt=0.1).ev
        pasos = ac.agrupar(ev)
        self.assertEqual(len(pasos), 1)
        self.assertEqual(pasos[0].descripcion, "Doble clic izquierdo en (50, 60)")
        self.assertEqual(pasos[0].tipo, "doble_clic")
        self.assertEqual(pasos[0].indices, [0, 1, 2, 3])

    def test_dos_clics_lentos_no_son_doble_clic(self):
        ev = Linea().clic(50, 60).clic(50, 60, dt=0.8).ev
        self.assertEqual(descripciones(ev), ["Clic izquierdo en (50, 60)"] * 2)

    def test_dos_clics_en_sitios_distintos_no_son_doble_clic(self):
        ev = Linea().clic(50, 60).clic(300, 60, dt=0.1).ev
        self.assertEqual([p.tipo for p in ac.agrupar(ev)], ["clic", "clic"])

    def test_arrastre(self):
        ev = Linea().pulsar(10, 10).mover(40, 40).mover(80, 80).soltar(120, 130).ev
        pasos = ac.agrupar(ev)
        self.assertEqual(len(pasos), 1)
        self.assertEqual(pasos[0].descripcion, "Arrastrar de (10, 10) a (120, 130)")
        self.assertEqual(pasos[0].tipo, "arrastre")
        self.assertEqual(pasos[0].indices, [0, 1, 2, 3])

    def test_arrastre_con_boton_derecho_lo_indica(self):
        ev = Linea().pulsar(0, 0, "right").soltar(90, 0, "right").ev
        self.assertEqual(descripciones(ev), ["Arrastrar con botón derecho de (0, 0) a (90, 0)"])

    def test_boton_sin_soltar(self):
        ev = Linea().pulsar(7, 8).tocar("a", dt=0.1).ev
        self.assertTrue(descripciones(ev)[0].startswith("Mantener botón izquierdo"))

    def test_movimientos_se_resumen(self):
        ev = Linea().mover(1, 1).mover(5, 5).mover(9, 9).ev
        pasos = ac.agrupar(ev)
        self.assertEqual(len(pasos), 1)
        self.assertEqual(pasos[0].tipo, "mover")
        self.assertEqual(pasos[0].descripcion, "Mover ratón de (1, 1) a (9, 9) (3 movimientos)")

    def test_un_solo_movimiento(self):
        self.assertEqual(descripciones(Linea().mover(3, 4).ev), ["Mover ratón a (3, 4)"])

    def test_mover_y_clic(self):
        ev = Linea().mover(1, 1).mover(200, 200).clic(200, 200).ev
        self.assertEqual([p.tipo for p in ac.agrupar(ev)], ["mover", "clic"])

    def test_rueda(self):
        ev = Linea().rueda(-1).rueda(-1).rueda(-1).ev
        pasos = ac.agrupar(ev)
        self.assertEqual(len(pasos), 1)
        self.assertEqual(pasos[0].descripcion, "Rueda del ratón: abajo 3 en (5, 5)")

    def test_texto(self):
        ev = Linea().escribir("hola").ev
        pasos = ac.agrupar(ev)
        self.assertEqual(len(pasos), 1)
        self.assertEqual(pasos[0].descripcion, "Escribir 'hola'")
        self.assertEqual(pasos[0].tipo, "texto")
        self.assertEqual(pasos[0].indices, list(range(8)))

    def test_texto_con_espacio_y_mayusculas(self):
        l = Linea()
        l.tecla("Key.shift", True, 160)
        l.tocar("H")
        l.tecla("Key.shift", False, 160)
        l.escribir("ola")
        l.tocar("Key.space")
        l.escribir("tú")
        self.assertEqual(descripciones(l.ev), ["Escribir 'Hola tú'"])

    def test_texto_con_altgr(self):
        l = Linea()
        l.tecla("Key.ctrl_l", True, 162)
        l.tecla("Key.alt_gr", True, 165)
        l.tocar("@")
        l.tecla("Key.alt_gr", False, 165)
        l.tecla("Key.ctrl_l", False, 162)
        self.assertEqual(descripciones(l.ev), ["Escribir '@'"])

    def test_texto_largo_se_recorta(self):
        pasos = ac.agrupar(Linea().escribir("a" * 120).ev)
        self.assertLess(len(pasos[0].descripcion), 70)
        self.assertTrue(pasos[0].descripcion.endswith("…'"))

    def test_texto_se_parte_con_pausa_larga(self):
        l = Linea().escribir("ab").avanzar(2.0).escribir("cd")
        self.assertEqual(descripciones(l.ev), ["Escribir 'ab'", "Esperar 2.0 s", "Escribir 'cd'"])

    def test_tecla_especial(self):
        self.assertEqual(descripciones(Linea().tocar("Key.enter").ev), ["Tecla Enter"])
        self.assertEqual(descripciones(Linea().tocar("Key.backspace").ev), ["Tecla Retroceso"])
        self.assertEqual(descripciones(Linea().tocar("Key.f5").ev), ["Tecla F5"])

    def test_texto_y_enter_son_pasos_distintos(self):
        l = Linea().escribir("ok").tocar("Key.enter")
        self.assertEqual(descripciones(l.ev), ["Escribir 'ok'", "Tecla Enter"])

    def test_tecla_repetida_se_fusiona(self):
        l = Linea().tocar("Key.enter", dt=0.1).tocar("Key.enter", dt=0.1).tocar("Key.enter", dt=0.1)
        self.assertEqual(descripciones(l.ev), ["Tecla Enter ×3"])

    def test_tecla_mantenida_con_autorepeticion(self):
        l = Linea()
        for _ in range(4):
            l.tecla("Key.down", True, 40)
        l.tecla("Key.down", False, 40)
        pasos = ac.agrupar(l.ev)
        self.assertEqual(len(pasos), 1)
        self.assertEqual(pasos[0].descripcion, "Tecla Flecha abajo ×4")
        self.assertEqual(pasos[0].indices, [0, 1, 2, 3, 4])

    def test_atajo_ctrl_c_con_caracter_de_control(self):
        l = Linea()
        l.tecla("Key.ctrl_l", True, 162)
        l.tecla("vk:67", True, 67)       # pynput da '\x03' -> se serializa como vk
        l.tecla("vk:67", False, 67)
        l.tecla("Key.ctrl_l", False, 162)
        pasos = ac.agrupar(l.ev)
        self.assertEqual(len(pasos), 1)
        self.assertEqual(pasos[0].descripcion, "Atajo Ctrl+C")
        self.assertEqual(pasos[0].tipo, "atajo")
        self.assertEqual(pasos[0].indices, [0, 1, 2, 3])

    def test_atajo_soltando_primero_el_modificador(self):
        l = Linea()
        l.tecla("Key.ctrl_l", True, 162)
        l.tecla("vk:86", True, 86)
        l.tecla("Key.ctrl_l", False, 162)
        l.tecla("v", False, 86)
        pasos = ac.agrupar(l.ev)
        self.assertEqual([p.descripcion for p in pasos], ["Atajo Ctrl+V"])
        self.assertEqual(pasos[0].indices, [0, 1, 2, 3])

    def test_atajo_con_letra_normal(self):
        l = Linea()
        l.tecla("Key.ctrl_l", True, 162)
        l.tocar("a", vk=65)
        l.tecla("Key.ctrl_l", False, 162)
        self.assertEqual(descripciones(l.ev), ["Atajo Ctrl+A"])

    def test_atajos_con_varios_modificadores(self):
        l = Linea()
        l.tecla("Key.ctrl_l", True, 162)
        l.tecla("Key.shift", True, 160)
        l.tocar("Key.esc")
        l.tecla("Key.shift", False, 160)
        l.tecla("Key.ctrl_l", False, 162)
        self.assertEqual(descripciones(l.ev), ["Atajo Ctrl+Mayús+Esc"])

    def test_alt_tab_y_shift_tab(self):
        l = Linea()
        l.tecla("Key.alt_l", True, 164)
        l.tocar("Key.tab")
        l.tecla("Key.alt_l", False, 164)
        l.tecla("Key.shift", True, 160, dt=0.5)
        l.tocar("Key.tab")
        l.tecla("Key.shift", False, 160)
        self.assertEqual(descripciones(l.ev), ["Atajo Alt+Tab", "Atajo Mayús+Tab"])

    def test_dos_atajos_con_ctrl_mantenido(self):
        l = Linea()
        l.tecla("Key.ctrl_l", True, 162)
        l.tocar("vk:67", vk=67)
        l.tocar("vk:86", vk=86)
        l.tecla("Key.ctrl_l", False, 162)
        self.assertEqual(descripciones(l.ev), ["Atajo Ctrl+C, Ctrl+V"])

    def test_modificador_solo(self):
        l = Linea()
        l.tecla("Key.cmd", True, 91)
        l.tecla("Key.cmd", False, 91)
        self.assertEqual(descripciones(l.ev), ["Tecla Win"])

    def test_ctrl_clic_deja_modificadores_visibles(self):
        l = Linea()
        l.tecla("Key.ctrl_l", True, 162)
        l.clic(10, 10, dt=0.1)
        l.tecla("Key.ctrl_l", False, 162, dt=0.1)
        self.assertEqual(descripciones(l.ev),
                         ["Presionar tecla Ctrl", "Clic izquierdo en (10, 10)", "Soltar tecla Ctrl"])

    def test_espera_automatica(self):
        l = Linea().clic(1, 1).avanzar(2.4).clic(2, 2, dt=0)
        pasos = ac.agrupar(l.ev)
        self.assertEqual([p.tipo for p in pasos], ["clic", "espera_auto", "clic"])
        self.assertEqual(pasos[1].descripcion, "Esperar 2.4 s")
        self.assertEqual(pasos[1].indices, [])
        self.assertEqual(pasos[1].antes_de, 2)
        self.assertAlmostEqual(pasos[1].hueco, 2.4, places=2)

    def test_pausa_corta_no_genera_espera(self):
        l = Linea().clic(1, 1).avanzar(0.8).clic(2, 2)
        self.assertEqual([p.tipo for p in ac.agrupar(l.ev)], ["clic", "clic"])

    def test_agrupar_no_modifica_los_eventos(self):
        ev = Linea().mover(1, 1).clic(2, 2).escribir("hi").tocar("Key.enter").ev
        copia = [dict(e) for e in ev]
        ac.agrupar(ev)
        self.assertEqual(ev, copia)

    def test_todos_los_eventos_quedan_cubiertos_una_vez(self):
        l = (Linea().mover(1, 1).mover(30, 30).clic(30, 30).clic(30, 30, dt=0.1)
             .escribir("abc").tocar("Key.enter").rueda(-1).avanzar(3)
             .pulsar(1, 1).mover(200, 200).soltar(200, 200))
        usados = []
        for p in ac.agrupar(l.ev):
            usados.extend(p.indices)
        self.assertEqual(sorted(usados), list(range(len(l.ev))))

    def test_lista_vacia(self):
        self.assertEqual(ac.agrupar([]), [])


class PruebasNotasYEdicion(unittest.TestCase):
    def grabacion(self):
        l = Linea().clic(10, 10).avanzar(2.0).escribir("hola").tocar("Key.enter", dt=0.2)
        return ac.Grabacion(l.ev)

    def test_nota_en_paso_y_en_espera(self):
        g = self.grabacion()
        pasos = g.pasos()
        g.poner_nota(pasos[0], "abrir menú")
        g.poner_nota(pasos[1], "esperar a que cargue")
        pasos = g.pasos()
        self.assertEqual([p.nota for p in pasos], ["abrir menú", "esperar a que cargue", "", ""])

    def test_nota_vacia_borra(self):
        g = self.grabacion()
        g.poner_nota(g.pasos()[0], "x")
        g.poner_nota(g.pasos()[0], "   ")
        self.assertEqual(g.pasos()[0].nota, "")
        self.assertNotIn("nota", g.eventos[0])

    def test_notas_estables_al_eliminar_otro_paso(self):
        g = self.grabacion()
        g.poner_nota(g.pasos()[2], "teclear saludo")
        g.poner_nota(g.pasos()[3], "confirmar")
        g.eliminar_pasos([g.pasos()[0]])   # quita el clic
        notas = {p.descripcion: p.nota for p in g.pasos()}
        self.assertEqual(notas["Escribir 'hola'"], "teclear saludo")
        self.assertEqual(notas["Tecla Enter"], "confirmar")

    def test_eliminar_paso_quita_sus_eventos_y_su_nota(self):
        g = self.grabacion()
        g.poner_nota(g.pasos()[0], "borrame")
        antes = len(g.eventos)
        quitados = g.eliminar_pasos([g.pasos()[0]])
        self.assertEqual(quitados, 2)
        self.assertEqual(len(g.eventos), antes - 2)
        self.assertNotIn("borrame", repr(g.eventos))

    def test_eliminar_espera_automatica_cierra_el_hueco(self):
        g = self.grabacion()
        espera = [p for p in g.pasos() if p.tipo == "espera_auto"][0]
        t_antes = g.eventos[-1]["t"]
        g.eliminar_pasos([espera])
        self.assertEqual([p.tipo for p in g.pasos()], ["clic", "texto", "tecla"])
        self.assertAlmostEqual(g.eventos[-1]["t"], t_antes - 2.0, delta=0.15)

    def test_eliminar_descuenta_el_tiempo_del_paso(self):
        l = Linea().clic(1, 1).avanzar(0.5).escribir("abc").avanzar(0.5).clic(9, 9)
        g = ac.Grabacion(l.ev)
        t_final = g.eventos[-1]["t"]
        texto = [p for p in g.pasos() if p.tipo == "texto"][0]
        dur = g.eventos[max(texto.indices)]["t"] - g.eventos[texto.indices[0]]["t"]
        g.eliminar_pasos([texto])
        self.assertAlmostEqual(g.eventos[-1]["t"], t_final - dur, places=4)
        tiempos = [e["t"] for e in g.eventos]
        self.assertEqual(tiempos, sorted(tiempos))

    def test_insertar_espera_despues_de_un_paso(self):
        g = self.grabacion()
        t_final = g.eventos[-1]["t"]
        g.insertar_espera_despues_de(g.pasos()[0], 3.0)
        pasos = g.pasos()
        self.assertEqual(pasos[1].descripcion, "Esperar 3.0 s")
        self.assertEqual(pasos[1].tipo, "esperar")
        self.assertEqual(g.eventos[2]["tipo"], "esperar")
        self.assertAlmostEqual(g.eventos[-1]["t"], t_final + 3.0, places=4)
        # la espera manual no debe duplicarse como pausa automática
        self.assertEqual(sum(1 for p in pasos if p.descripcion == "Esperar 3.0 s"), 1)

    def test_insertar_espera_al_principio_y_al_final(self):
        g = ac.Grabacion(Linea().clic(1, 1).ev)
        g.insertar_espera_despues_de(None, 2.0)
        self.assertEqual(g.eventos[-1]["tipo"], "esperar")
        g2 = ac.Grabacion()
        g2.insertar_espera(1.5)
        self.assertEqual([p.descripcion for p in g2.pasos()], ["Esperar 1.5 s"])

    def test_insertar_espera_tras_espera_automatica(self):
        g = self.grabacion()
        espera = [p for p in g.pasos() if p.tipo == "espera_auto"][0]
        g.insertar_espera_despues_de(espera, 1.0)
        tipos = [p.tipo for p in g.pasos()]
        self.assertEqual(tipos[:3], ["clic", "espera_auto", "esperar"])

    def test_insertar_espera_invalida(self):
        with self.assertRaises(ValueError):
            ac.Grabacion().insertar_espera(0)

    def test_espera_manual_se_puede_borrar(self):
        g = self.grabacion()
        g.insertar_espera_despues_de(g.pasos()[0], 3.0)
        t_final = g.eventos[-1]["t"]
        paso = [p for p in g.pasos() if p.tipo == "esperar"][0]
        g.eliminar_pasos([paso])
        self.assertFalse(any(e["tipo"] == "esperar" for e in g.eventos))
        self.assertAlmostEqual(g.eventos[-1]["t"], t_final - 3.0, places=4)


class PruebasJSON(unittest.TestCase):
    def test_ida_y_vuelta_conserva_eventos_y_notas(self):
        l = (Linea().mover(1, 2).clic(10, 10).avanzar(2).escribir("añadir ñ")
             .tocar("Key.enter").rueda(2).avanzar(1.5))
        g = ac.Grabacion(l.ev)
        g.insertar_espera_despues_de(g.pasos()[1], 2.5)
        for i, p in enumerate(g.pasos()):
            g.poner_nota(p, "nota %d ñ" % i)
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "sub", "g.json")
            g.guardar(ruta)
            g2 = ac.Grabacion.cargar(ruta)
        self.assertEqual(g.eventos, g2.eventos)
        self.assertEqual([(p.descripcion, p.nota) for p in g.pasos()],
                         [(p.descripcion, p.nota) for p in g2.pasos()])
        self.assertTrue(all(p.nota for p in g2.pasos()))

    def test_json_incluye_version(self):
        self.assertEqual(ac.Grabacion().a_dict()["version"], ac.VERSION_FORMATO)

    def test_no_deja_archivos_temporales(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "a.json")
            ac.Grabacion(Linea().clic(1, 1).ev).guardar(ruta)
            self.assertEqual(os.listdir(tmp), ["a.json"])

    def test_rechaza_archivos_invalidos(self):
        with self.assertRaises(ValueError):
            ac.Grabacion.desde_dict([1, 2])
        with self.assertRaises(ValueError):
            ac.Grabacion.desde_dict({"version": 1, "eventos": [{"tipo": "raro", "t": 0}]})
        with self.assertRaises(ValueError):
            ac.Grabacion.desde_dict({"version": 99, "eventos": []})
        with self.assertRaises(ValueError):
            ac.Grabacion.desde_dict({"version": 1, "eventos": [{"tipo": "mover"}]})
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "malo.json")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("{no es json")
            with self.assertRaises(ValueError):
                ac.Grabacion.cargar(ruta)


class FalsaKey(enum.Enum):
    enter = 1
    ctrl_l = 2


class FalsaTecla:
    def __init__(self, char=None, vk=None):
        self.char = char
        self.vk = vk


class PruebasTeclas(unittest.TestCase):
    def test_serializar(self):
        self.assertEqual(ac.serializar_tecla(FalsaKey.enter), "Key.enter")
        self.assertEqual(ac.serializar_tecla(FalsaKey.ctrl_l), "Key.ctrl_l")
        self.assertEqual(ac.serializar_tecla(FalsaTecla(char="a", vk=65)), "a")
        self.assertEqual(ac.serializar_tecla(FalsaTecla(char="ñ")), "ñ")
        self.assertEqual(ac.serializar_tecla(FalsaTecla(vk=123)), "vk:123")

    def test_serializar_caracter_de_control_usa_vk(self):
        self.assertEqual(ac.serializar_tecla(FalsaTecla(char="\x03", vk=67)), "vk:67")
        self.assertEqual(ac.serializar_tecla(FalsaTecla(char="\x16", vk=86)), "vk:86")

    def test_analizar_vk(self):
        self.assertEqual(ac.analizar_vk("vk:67"), 67)
        self.assertIsNone(ac.analizar_vk("a"))
        self.assertIsNone(ac.analizar_vk("vk:xx"))
        self.assertIsNone(ac.analizar_vk("Key.enter"))

    def test_nombres(self):
        self.assertEqual(ac.nombre_tecla("Key.enter"), "Enter")
        self.assertEqual(ac.nombre_tecla("Key.page_down"), "Av Pág")
        self.assertEqual(ac.nombre_tecla("Key.f12"), "F12")
        self.assertEqual(ac.nombre_tecla("Key.ctrl_r"), "Ctrl")
        self.assertEqual(ac.nombre_tecla("a"), "A")
        self.assertEqual(ac.nombre_tecla("vk:67"), "C")
        self.assertEqual(ac.nombre_tecla("vk:112"), "F1")
        self.assertEqual(ac.nombre_tecla("\x03", 67), "C")   # carácter de control + vk
        self.assertEqual(ac.nombre_tecla("Key.algo_raro"), "Algo raro")

    def test_familias_de_modificadores(self):
        self.assertEqual(ac.familia_modificador("Key.shift_r"), "shift")
        self.assertEqual(ac.familia_modificador("Key.alt_gr"), "altgr")
        self.assertEqual(ac.familia_modificador("Key.cmd"), "cmd")
        self.assertIsNone(ac.familia_modificador("Key.enter"))
        self.assertIsNone(ac.familia_modificador("a"))


class PruebasURL(unittest.TestCase):
    def test_normalizar_url(self):
        self.assertEqual(ac.normalizar_url("example.com"), "https://example.com")
        self.assertEqual(ac.normalizar_url("  www.ejemplo.es/ruta?a=1  "), "https://www.ejemplo.es/ruta?a=1")
        self.assertEqual(ac.normalizar_url("http://localhost:8080/x"), "http://localhost:8080/x")
        self.assertEqual(ac.normalizar_url("HTTPS://Example.com"), "HTTPS://Example.com")
        self.assertEqual(ac.normalizar_url("localhost:8000"), "https://localhost:8000")
        self.assertEqual(ac.normalizar_url("file:///C:/a.html"), "file:///C:/a.html")
        self.assertEqual(ac.normalizar_url(""), "")
        self.assertEqual(ac.normalizar_url("   "), "")
        self.assertEqual(ac.normalizar_url(None), "")

    def test_anteponer_abrir_url_refleja_la_espera(self):
        ev = Linea().clic(10, 10).ev
        nuevos = ac.anteponer_abrir_url(ev, "example.com", 5)
        self.assertEqual(nuevos[0], {"tipo": "abrir_url", "t": 0.0, "url": "https://example.com"})
        self.assertAlmostEqual(nuevos[1]["t"], ev[0]["t"] + 5, places=4)
        self.assertEqual(ev[0]["t"], 0.05)   # no modifica la entrada
        with self.assertRaises(ValueError):
            ac.anteponer_abrir_url(ev, "  ", 5)

    def test_descripcion_y_espera_automatica(self):
        pasos = ac.agrupar(ac.anteponer_abrir_url(Linea().clic(10, 10, dt=0).ev, "example.com", 5))
        self.assertEqual([p.tipo for p in pasos], ["abrir_url", "espera_auto", "clic"])
        self.assertEqual(pasos[0].descripcion, "Abrir URL https://example.com")
        self.assertEqual(pasos[0].indices, [0])
        self.assertEqual(pasos[1].descripcion, "Esperar 5.0 s")

    def test_nota_en_paso_abrir_url(self):
        g = ac.Grabacion(ac.anteponer_abrir_url(Linea().clic(1, 1).ev, "example.com", 0.5))
        g.poner_nota(g.pasos()[0], "página de inicio")
        self.assertEqual(g.pasos()[0].nota, "página de inicio")
        self.assertEqual(g.eventos[0]["nota"], "página de inicio")

    def test_insertar_abrir_url_manual(self):
        g = ac.Grabacion(Linea().clic(1, 1).avanzar(1.5).clic(2, 2).ev)
        t_final = g.eventos[-1]["t"]
        primero = g.pasos()[0]
        pos = g.insertar_abrir_url_despues_de(primero, "ejemplo.org", 4.0)
        self.assertEqual(g.eventos[pos]["url"], "https://ejemplo.org")
        self.assertEqual([p.tipo for p in g.pasos()][:3], ["clic", "abrir_url", "espera_auto"])
        self.assertAlmostEqual(g.eventos[-1]["t"], t_final + 4.0, places=4)
        self.assertEqual(g.indice_primera_url(), pos)
        with self.assertRaises(ValueError):
            g.insertar_abrir_url_despues_de(None, "", 1)

    def test_insertar_abrir_url_al_final_y_en_vacio(self):
        g = ac.Grabacion()
        g.insertar_abrir_url_despues_de(None, "example.com")
        self.assertEqual([p.descripcion for p in g.pasos()], ["Abrir URL https://example.com"])
        self.assertIsNone(ac.Grabacion(Linea().clic(1, 1).ev).indice_primera_url())

    def test_eliminar_paso_abrir_url(self):
        g = ac.Grabacion(ac.anteponer_abrir_url(Linea().clic(1, 1).ev, "example.com", 5))
        g.eliminar_pasos([g.pasos()[0]])
        self.assertFalse(any(e["tipo"] == "abrir_url" for e in g.eventos))

    def test_json_ida_y_vuelta_con_url(self):
        g = ac.Grabacion(ac.anteponer_abrir_url(Linea().clic(1, 1).escribir("ok").ev, "example.com/ñ", 3))
        g.poner_nota(g.pasos()[0], "abrir la web")
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "u.json")
            g.guardar(ruta)
            g2 = ac.Grabacion.cargar(ruta)
        self.assertEqual(g.eventos, g2.eventos)
        self.assertEqual(g2.pasos()[0].descripcion, "Abrir URL https://example.com/ñ")
        self.assertEqual(g2.pasos()[0].nota, "abrir la web")

    def test_json_rechaza_abrir_url_sin_url(self):
        with self.assertRaises(ValueError):
            ac.Grabacion.desde_dict({"version": 1, "eventos": [{"tipo": "abrir_url", "t": 0}]})

    def test_acciones_no_importa_webbrowser(self):
        with open(os.path.join(RAIZ, "acciones.py"), encoding="utf-8") as f:
            self.assertNotIn("webbrowser", f.read())


class PruebasPureza(unittest.TestCase):
    def test_acciones_no_importa_pynput(self):
        with open(os.path.join(RAIZ, "acciones.py"), encoding="utf-8") as f:
            arbol = ast.parse(f.read())
        modulos = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                modulos.update(a.name.split(".")[0] for a in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                modulos.add(nodo.module.split(".")[0])
        self.assertNotIn("pynput", modulos)


if __name__ == "__main__":
    unittest.main()
