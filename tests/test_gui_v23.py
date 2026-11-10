"""Pruebas de la ventana para la v2.3 (sin interacción humana): pregunta «la página pide iniciar sesión» entre el
hilo de trabajo y la ventana, cuadros Accesos / Iniciar sesión / Versiones, opción de esperas de carga y
actualización de los reportes guardados al abrir la ventana.  Base de datos temporal y contraseñas en memoria."""

import json
import os
import sqlite3
import sys
import threading
import tkinter as tk
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "tests")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import bot  # noqa: E402
from test_gui import BaseGui, _raiz_tk  # noqa: E402
from test_v23 import flujo_v2, pasos_erp, pasos_portal_metricas  # noqa: E402
from webbot import secretos  # noqa: E402
from webbot.accesos import PeticionAcceso  # noqa: E402
from webbot.flujo import Paso  # noqa: E402


class TestPreguntaDeAcceso(BaseGui):
    def test_hilo_de_trabajo_pregunta_y_la_ventana_contesta(self):
        solicitud = {"host": "portal", "mensaje": "pide", "campos": [{"clave": "p", "etiqueta": "Clave", "tipo": "clave"}]}
        vistas = []

        def falso_dialogo(sol):
            vistas.append((threading.current_thread() is threading.main_thread(), sol))
            return {"valores": {"p": "x"}, "recordar": False}

        resultado = []

        def esperar(evento):                     # lo que haría el ejecutor (sin navegador)
            if not evento.wait(30):
                raise RuntimeError("sin respuesta")

        def trabajo():
            resultado.append(self.app._pedir_acceso(solicitud, esperar))

        with mock.patch.object(self.app, "_abrir_dialogo_acceso", side_effect=falso_dialogo):
            hilo = threading.Thread(target=trabajo, daemon=True)
            hilo.start()
            self.assertTrue(self.esperar(lambda: resultado, 20), "la ventana no contestó")
            hilo.join(5)
        self.assertEqual(resultado, [{"valores": {"p": "x"}, "recordar": False}])
        self.assertEqual(len(vistas), 1)
        self.assertTrue(vistas[0][0], "el cuadro debe abrirse en el hilo principal")
        self.assertIs(vistas[0][1], solicitud)

    def test_detener_cancela_la_pregunta_pendiente(self):
        pet = PeticionAcceso({"host": "h"})
        dlg = tk.Toplevel(self.root)
        self.app._peticion_acceso = pet
        self.app._dialogo_acceso = dlg
        self.app._detener()
        self.assertTrue(pet.evento.is_set() and pet.cancelada)
        self.assertIsNone(pet.respuesta)
        self.assertFalse(dlg.winfo_exists())
        # una petición ya cancelada no abre ningún cuadro
        with mock.patch.object(self.app, "_abrir_dialogo_acceso") as abrir:
            self.app._atender_acceso(pet)
            abrir.assert_not_called()

    def test_cuadro_iniciar_sesion(self):
        sol = {"host": "erp.example.com", "rechazada": True, "mensaje": "La contraseña fue rechazada…",
               "error_pagina": "Usuario o contraseña incorrectos",
               "campos": [{"clave": "u", "etiqueta": "Usuario", "tipo": "texto", "valor": "ana"},
                          {"clave": "p", "etiqueta": "Contraseña", "tipo": "clave", "valor": ""},
                          {"clave": "l", "etiqueta": "Licencia", "tipo": "texto", "valor": ""}]}
        dlg = bot.DialogoAcceso(self.root, sol)
        dlg.update()
        entradas = [w for w in dlg.winfo_children()[0].winfo_children() if isinstance(w, tk.ttk.Entry)]
        self.assertEqual([e.cget("show") for e in entradas], ["", "*", ""])
        self.assertTrue(dlg.v_recordar.get())                 # «Recordar» viene marcado
        dlg.vars["p"].set("nueva")
        dlg.vars["l"].set("L-1")
        dlg._aceptar()
        self.assertEqual(dlg.respuesta, {"valores": {"u": "ana", "p": "nueva", "l": "L-1"}, "recordar": True})
        dlg2 = bot.DialogoAcceso(self.root, sol)
        dlg2._cancelar()
        self.assertIsNone(dlg2.respuesta)

    def test_ejecutar_pasa_la_pregunta_y_los_accesos(self):
        capturado = {}

        class FalsoEjecutor:
            def __init__(self, flujo, **kw):
                capturado.update(kw)

            def ejecutar(self):
                from webbot.ejecutor import ResultadoEjecucion
                r = ResultadoEjecucion()
                r.ok = True
                return r

        self.app.flujo.pasos = [Paso("abrir_url", url="http://127.0.0.1/")]
        import webbot.ejecutor as mod_ej
        with mock.patch.object(mod_ej, "Ejecutor", FalsoEjecutor):
            self.app._ejecutar()
            self.assertTrue(self.esperar(lambda: not self.app.trabajando, 20))
        self.assertEqual(capturado["pedir_acceso"], self.app._pedir_acceso)
        self.assertIs(capturado["accesos"], self.app.almacen)


class TestCuadrosV23(BaseGui):
    def test_accesos_lista_cambia_y_borra(self):
        alm = self.almacen
        alm.guardar_acceso("portal.example.com", "usuario", "Usuario", "texto", valor="ana")
        alm.guardar_acceso("portal.example.com", "clave", "Contraseña", "clave", secreto="portal.example.com:clave")
        secretos.guardar("portal.example.com:clave", "vieja")
        dlg = bot.DialogoAccesos(self.root, alm)
        filas = [dlg.arbol.item(i, "values") for i in dlg.arbol.get_children()]
        self.assertEqual(len(filas), 2)
        self.assertNotIn("vieja", json.dumps(filas))
        # cambiar el usuario (askstring de la prueba devuelve self.nombres)
        dlg.arbol.selection_set("0")
        self.nombres = ["bea"]
        dlg._editar()
        self.assertEqual(alm.accesos_de("portal.example.com")[0]["valor"], "bea")
        # cambiar la contraseña
        iid = [i for i in dlg.arbol.get_children() if dlg.filas[i]["tipo"] == "clave"][0]
        dlg.arbol.selection_set(iid)
        self.nombres = ["nueva"]
        dlg._cambiar_clave()
        self.assertEqual(secretos.obtener("portal.example.com:clave"), "nueva")
        # borrar (askyesno de la prueba dice que sí): también la contraseña guardada
        iid = [i for i in dlg.arbol.get_children() if dlg.filas[i]["tipo"] == "clave"][0]
        dlg.arbol.selection_set(iid)
        dlg._borrar()
        self.assertIsNone(secretos.obtener("portal.example.com:clave"))
        self.assertEqual(len(alm.accesos_de("portal.example.com")), 1)
        dlg.destroy()

    def test_opcion_esperar_carga_y_paso(self):
        app = self.app
        app.v_carga.set(False)
        app._formulario_a_flujo()
        self.assertIs(app.flujo.opciones["esperar_carga"], False)
        app.flujo.opciones["esperar_carga"] = True
        app._flujo_a_formulario()
        self.assertTrue(app.v_carga.get())
        paso = Paso("clic", selectores=["#a"])
        dlg = bot.DialogoPaso(self.root, paso, {}, app.flujo.opciones)
        dlg.vars["esperar_carga"].set("no")
        dlg._aceptar()
        self.assertIs(paso.esperar_carga, False)
        dlg = bot.DialogoPaso(self.root, paso, {}, app.flujo.opciones)
        dlg.vars["esperar_carga"].set(bot.CARGA_AUTO)
        dlg._aceptar()
        self.assertIsNone(paso.esperar_carga)

    def test_editar_paso_iniciar_sesion(self):
        paso = Paso("iniciar_sesion", sitio="h", enviar={"selectores": ["#entrar"]},
                    campos=[{"selectores": ["#u"], "etiqueta": "Usuario", "tipo": "texto", "clave": "u", "valor": "ana"},
                            {"selectores": ["#p"], "etiqueta": "Contraseña", "tipo": "clave", "clave": "p", "secreto": "h:p"}])
        dlg = bot.DialogoPaso(self.root, paso, {}, {})
        dlg.vars["campo_0"].set("bea")
        dlg.vars["campo_1"].set("h:otra")
        dlg.txt_enviar.delete("1.0", "end")
        dlg._aceptar()
        self.assertTrue(dlg.aceptado)
        self.assertEqual(paso.campos[0]["valor"], "bea")
        self.assertEqual(paso.campos[1]["secreto"], "h:otra")
        self.assertEqual(paso.enviar, {"tecla": "Enter"})

    def test_versiones_restaurar(self):
        rid = self.guardar("Con copia", [Paso("abrir_url", url="http://a/")])
        self.almacen.guardar_version(rid, "prueba")
        f = self.almacen.cargar_flujo(rid)
        f.pasos.append(Paso("clic", selectores=["#b"]))
        self.almacen.guardar(f, rid)
        restaurados = []
        dlg = bot.DialogoVersiones(self.root, self.almacen, rid, "Con copia", al_restaurar=restaurados.append)
        dlg.arbol.selection_set(dlg.arbol.get_children()[0])
        dlg._restaurar()
        self.assertEqual(restaurados, [rid])
        self.assertEqual(len(self.almacen.cargar_flujo(rid).pasos), 1)


class TestActualizacionAlAbrir(BaseGui):
    def test_los_reportes_de_la_v22_se_actualizan_con_copia(self):
        ruta_db = self.almacen.ruta
        c = sqlite3.connect(ruta_db)
        for nombre, pasos in (("Portal, metricas", pasos_portal_metricas()), ("ERP", pasos_erp())):
            d = flujo_v2(nombre, pasos)
            c.execute("INSERT INTO reportes(nombre, url, flujo, creado, modificado) VALUES (?, ?, ?, ?, ?)",
                      (nombre, d["url"], json.dumps(d, ensure_ascii=False), "2026-10-24 09:00:00", "2026-10-24 09:00:00"))
        c.commit()
        c.close()
        otra = tk.Toplevel(_raiz_tk())
        otra.withdraw()
        app2 = bot.App(otra, self.args)
        try:
            log = app2.txt_log.get("1.0", "end")
            self.assertIn("«Portal, metricas» actualizado a la v2.3", log)
            self.assertIn("«ERP» actualizado", log)
            self.assertIn("Versiones anteriores", app2.v_estado.get() + log)
            for r in app2.reportes:
                fl = app2.almacen.cargar_flujo(r["id"])
                self.assertEqual(fl.pasos[1].tipo, "iniciar_sesion")
                self.assertEqual(len(app2.almacen.versiones(r["id"])), 1)
            # abrirlo en el editor y ver la lista de pasos
            rid = app2.almacen.obtener_por_nombre("ERP")["id"]
            app2._cargar_reporte(rid)
            fila = app2.arbol.item("1", "values")
            self.assertEqual(fila[1], "Iniciar sesión")
            self.assertIn("erp.ejemplo.com", fila[2])
        finally:
            app2.almacen.cerrar()
            otra.destroy()


if __name__ == "__main__":
    unittest.main()
