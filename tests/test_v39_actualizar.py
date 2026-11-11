"""Pruebas de la v3.9: «Hay una nueva actualización» y el botón «Actualizar» (código nuevo de la rama New-tool).

1. GitHub (simulado): leer el último cambio de la rama; sin Internet o con límite de peticiones, se calla.
2. Comparar la versión instalada con la de GitHub (sha y fecha); sin saber la instalada, se toma la de GitHub como punto
   de partida (no avisa sin fin).
3. Actualizar: se niega si el bot trabaja, en una copia de desarrollo (con .git) y en una copia no instalada; si no,
   copia de seguridad de la base de datos, descarga a una carpeta nueva, descomprime sin salirse de ella y abre el
   instalador descargado en modo actualización.
4. El instalador descarga de la rama New-tool y tiene el modo actualización (esperar, sin preguntas, volver a abrir).
5. Las ejecuciones sin ventana (tareas de Windows) no miran GitHub.

Todo simulado: nunca se usa la red, nunca se instala nada de verdad, nunca se toca datos/bot.db, las credenciales, las
tareas de Windows ni las notificaciones.
"""

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import zipfile
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from webbot import actualizar, avisos, programador, secretos  # noqa: E402
from webbot import servidor_ui as su  # noqa: E402
from webbot.almacen import Almacen  # noqa: E402

SHA_A = "a" * 40
SHA_B = "b" * 40
INSTALADOR = os.path.join(RAIZ, "instalador", "Instalar Bot Web.cmd")


def respuesta_api(sha=SHA_B, mensaje="Arreglo del calendario\n\nDetalles largos", fecha="2026-11-10T15:00:00Z"):
    return json.dumps({"sha": sha, "commit": {"message": mensaje, "committer": {"date": fecha}}}).encode("utf-8")


def zip_del_bot(raiz="Mapez-New-tool/", extra=None, con_bot=True):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        if con_bot:
            z.writestr(raiz + "bot.py", "print('bot')\n")
            z.writestr(raiz + "webbot/__init__.py", "VERSION = '9.9'\n")
            z.writestr(raiz + "instalador/Instalar Bot Web.cmd", "@echo off\r\n")
        else:
            z.writestr(raiz + "LEEME.txt", "otra cosa")
        for nombre, datos in (extra or {}).items():
            z.writestr(nombre, datos)
    return b.getvalue()


class SinRed(unittest.TestCase):
    """Base: la red, los procesos y los avisos de verdad están prohibidos."""
    PROHIBIR_PROCESOS = True          # (la prueba de la interfaz necesita lanzar el navegador oculto de Playwright)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="botweb_v39_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        def prohibido(*a, **k):
            raise AssertionError("se intentó usar la red de verdad")
        for objetivo in ("urllib.request.urlopen", "socket.create_connection"):
            p = mock.patch(objetivo, prohibido)
            p.start()
            self.addCleanup(p.stop)
        if self.PROHIBIR_PROCESOS:
            p = mock.patch.object(actualizar.subprocess, "Popen", side_effect=AssertionError("proceso de verdad"))
            p.start()
            self.addCleanup(p.stop)
        secretos.usar_almacen(secretos.AlmacenMemoria())
        self.addCleanup(secretos.usar_almacen, None)
        avisos.usar_notificador(lambda t, x: None)
        self.addCleanup(avisos.usar_notificador, None)
        original = programador._ejecutar
        programador._ejecutar = lambda cmd: (_ for _ in ()).throw(AssertionError("schtasks de verdad: %s" % cmd))
        self.addCleanup(setattr, programador, "_ejecutar", original)

    def carpeta_instalada(self, nombre="BotWeb"):
        """Una instalación falsa: <tmp>/<nombre>/app con la marca del instalador y su base de datos en datos/."""
        app = os.path.join(self.tmp, nombre, "app")
        os.makedirs(os.path.join(app, "datos"))
        with open(os.path.join(app, actualizar.MARCA_INSTALADOR), "w", encoding="utf-8") as f:
            f.write("Instalado")
        db = os.path.join(app, "datos", "bot.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE prueba (x)")
        con.execute("INSERT INTO prueba VALUES ('mis datos')")
        con.commit()
        con.close()
        return app, db

    def carpeta_git(self, sha=SHA_A):
        raiz = os.path.join(self.tmp, "desarrollo")
        os.makedirs(os.path.join(raiz, ".git", "refs", "heads"))
        with open(os.path.join(raiz, ".git", "HEAD"), "w", encoding="utf-8") as f:
            f.write("ref: refs/heads/New-tool\n")
        with open(os.path.join(raiz, ".git", "refs", "heads", "New-tool"), "w", encoding="utf-8") as f:
            f.write(sha + "\n")
        return raiz


class _Abrir:
    """Imita `urlopen`: devuelve lo indicado por dirección y apunta las llamadas."""

    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.llamadas = []

    def __call__(self, url, timeout):
        self.llamadas.append(url)
        r = self.respuestas.get(url)
        if isinstance(r, BaseException):
            raise r
        if r is None:
            raise urllib.error.URLError("sin conexión")
        return io.BytesIO(r)


# ================================================================================================ GitHub
class TestConsultarGitHub(SinRed):
    def test_lee_el_ultimo_cambio(self):
        abrir = _Abrir({actualizar.URL_API: respuesta_api()})
        r = actualizar.consultar_remoto(abrir=abrir)
        self.assertEqual(r, {"sha": SHA_B, "mensaje": "Arreglo del calendario", "fecha": "2026-11-10T15:00:00Z"})
        self.assertEqual(abrir.llamadas, ["https://api.github.com/repos/Rfalso014/Mapez/commits?sha=New-tool&per_page=1"])

    def test_lee_la_lista_que_devuelve_github(self):
        # GitHub contesta con una lista (el último cambio, sin sus archivos): así no pasa de 1 MB con cambios grandes.
        lista = ("[" + respuesta_api().decode("utf-8") + "]").encode("utf-8")
        r = actualizar.consultar_remoto(abrir=_Abrir({actualizar.URL_API: lista}))
        self.assertEqual(r, {"sha": SHA_B, "mensaje": "Arreglo del calendario", "fecha": "2026-11-10T15:00:00Z"})

    def test_sin_conexion_o_limite_se_calla(self):
        limite = urllib.error.HTTPError(actualizar.URL_API, 403, "rate limit exceeded", {}, None)
        for fallo in (urllib.error.URLError("sin red"), limite, TimeoutError("tiempo"), OSError("red")):
            self.assertIsNone(actualizar.consultar_remoto(abrir=_Abrir({actualizar.URL_API: fallo})))
        self.assertIsNone(actualizar.consultar_remoto(abrir=_Abrir({actualizar.URL_API: b"<html>no es json"})))
        self.assertIsNone(actualizar.consultar_remoto(abrir=_Abrir({actualizar.URL_API: b'{"sha": "no-es-un-sha"}'})))

    def test_peticion_sin_datos_personales(self):
        visto = {}

        def urlopen(pedido, timeout):
            visto.update(url=pedido.full_url, agente=pedido.get_header("User-agent"), timeout=timeout)
            return io.BytesIO(respuesta_api())
        with mock.patch.object(actualizar.urllib.request, "urlopen", urlopen):
            self.assertEqual(actualizar.consultar_remoto()["sha"], SHA_B)
        self.assertEqual(visto, {"url": actualizar.URL_API, "agente": "BotWeb", "timeout": actualizar.TIEMPO_API})
        self.assertEqual(actualizar.URL_ZIP, "https://github.com/Rfalso014/Mapez/archive/refs/heads/New-tool.zip")


# ================================================================================================ comparar
class TestComparar(unittest.TestCase):
    def test_mismo_sha(self):
        self.assertTrue(actualizar.mismo_sha(SHA_A, SHA_A.upper()))
        self.assertTrue(actualizar.mismo_sha(SHA_A, SHA_A[:7]))
        self.assertFalse(actualizar.mismo_sha(SHA_A, SHA_B))
        self.assertFalse(actualizar.mismo_sha(SHA_A, "aaa"))          # demasiado corto: no se da por igual
        self.assertFalse(actualizar.mismo_sha("", ""))

    def test_hay_novedad(self):
        remoto = {"sha": SHA_B, "fecha": "2026-11-10T15:00:00Z"}
        self.assertFalse(actualizar.hay_novedad({"sha": SHA_B}, remoto))
        self.assertTrue(actualizar.hay_novedad({"sha": SHA_A, "fecha": "2026-11-01T10:00:00-05:00"}, remoto))
        # un paquete hecho con cambios aún sin subir (más nuevo que GitHub): no pide «actualizar» a una versión vieja
        self.assertFalse(actualizar.hay_novedad({"sha": SHA_A, "fecha": "2026-11-11T09:00:00-05:00"}, remoto))
        self.assertTrue(actualizar.hay_novedad({"sha": SHA_A}, remoto))             # sin fechas: basta con otro sha
        self.assertFalse(actualizar.hay_novedad(None, remoto))                      # sin saber la instalada: no
        self.assertFalse(actualizar.hay_novedad({"sha": SHA_A}, None))              # sin conexión: no
        self.assertTrue(actualizar.hay_novedad({"sha": SHA_A, "fecha": "no es fecha"}, remoto))

    def test_fecha_corta(self):
        self.assertRegex(actualizar.fecha_corta("2026-11-10T15:00:00Z"), r"^1[01]/11/2026$")
        self.assertEqual(actualizar.fecha_corta(""), "")


class TestComprobar(SinRed):
    def actualizador(self, raiz, remotos, **kw):
        self.consultas = []

        def consultar():
            self.consultas.append(1)
            return remotos.pop(0) if remotos else None
        self.lineas = []
        return actualizar.Actualizador(raiz=raiz, consultar=consultar, registrar=self.lineas.append, **kw)

    def test_sin_version_apuntada_toma_la_de_github_y_no_avisa_sin_fin(self):
        app, _db = self.carpeta_instalada()
        remoto = {"sha": SHA_A, "mensaje": "Primero", "fecha": "2026-11-01T10:00:00Z"}
        act = self.actualizador(app, [dict(remoto), dict(remoto)])
        est = act.comprobar()
        self.assertFalse(est["disponible"])
        self.assertEqual(actualizar.leer_instalado(app)["sha"], SHA_A)
        self.assertEqual(actualizar.leer_instalado(app)["origen"], "supuesto")
        self.assertEqual(len(self.lineas), 1)
        self.assertIn("punto de partida", self.lineas[0])
        self.assertFalse(act.comprobar()["disponible"])                 # la segunda vez, tampoco
        self.assertEqual(len(self.lineas), 1)

    def test_version_nueva_disponible(self):
        app, _db = self.carpeta_instalada()
        actualizar.guardar_instalado(app, {"sha": SHA_A, "fecha": "2026-11-01T10:00:00Z"})
        act = self.actualizador(app, [{"sha": SHA_B, "mensaje": "Arreglo del calendario", "fecha": "2026-11-10T15:00:00Z"}])
        est = act.comprobar()
        self.assertTrue(est["disponible"])
        self.assertEqual((est["sha"], est["novedades"], est["instalado"]), (SHA_B[:7], "Arreglo del calendario", SHA_A[:7]))
        self.assertFalse(est["copia_git"])
        self.assertFalse(est["pospuesta"])

    def test_sin_conexion_no_pasa_nada(self):
        app, _db = self.carpeta_instalada()
        act = self.actualizador(app, [])
        est = act.comprobar()
        self.assertEqual((est["disponible"], est["sin_conexion"]), (False, True))
        self.assertFalse(os.path.exists(os.path.join(app, actualizar.ARCHIVO)))       # nada apuntado a ciegas

    def test_sin_conexion_despues_conserva_el_aviso(self):
        app, _db = self.carpeta_instalada()
        actualizar.guardar_instalado(app, {"sha": SHA_A})
        act = self.actualizador(app, [{"sha": SHA_B, "fecha": ""}])
        self.assertTrue(act.comprobar()["disponible"])
        est = act.comprobar()                                            # ahora sin Internet
        self.assertTrue(est["disponible"])
        self.assertTrue(est["sin_conexion"])

    def test_manual_seguido_no_gasta_peticiones(self):
        app, _db = self.carpeta_instalada()
        actualizar.guardar_instalado(app, {"sha": SHA_A})
        act = self.actualizador(app, [{"sha": SHA_A}, {"sha": SHA_A}])
        act.comprobar(manual=True)
        act.comprobar(manual=True)
        self.assertEqual(len(self.consultas), 1)

    def test_mas_tarde_y_buscar_otra_vez(self):
        app, _db = self.carpeta_instalada()
        actualizar.guardar_instalado(app, {"sha": SHA_A})
        act = self.actualizador(app, [{"sha": SHA_B}])
        act.comprobar()
        self.assertTrue(act.posponer()["pospuesta"])
        self.assertTrue(act.estado()["pospuesta"])
        self.assertFalse(act.comprobar(manual=True)["pospuesta"])      # «Buscar actualizaciones» lo vuelve a enseñar

    def test_copia_de_desarrollo(self):
        raiz = self.carpeta_git(SHA_A)
        self.assertTrue(actualizar.es_copia_git(raiz))
        self.assertEqual(actualizar.sha_git(raiz), SHA_A)
        act = self.actualizador(raiz, [{"sha": SHA_B}], git_tiene=lambda r, s: False)
        est = act.comprobar()
        self.assertTrue(est["disponible"])
        self.assertTrue(est["copia_git"])
        self.assertFalse(os.path.exists(os.path.join(raiz, actualizar.ARCHIVO)))      # en la copia de git no se escribe
        act = self.actualizador(raiz, [{"sha": SHA_B}], git_tiene=lambda r, s: True)  # ya lo tiene (va por delante)
        self.assertFalse(act.comprobar()["disponible"])

    def test_sha_git_en_packed_refs(self):
        raiz = self.carpeta_git()
        os.remove(os.path.join(raiz, ".git", "refs", "heads", "New-tool"))
        with open(os.path.join(raiz, ".git", "packed-refs"), "w", encoding="utf-8") as f:
            f.write("# pack-refs with: peeled\n%s refs/heads/New-tool\n" % SHA_B)
        self.assertEqual(actualizar.sha_git(raiz), SHA_B)

    def test_hilo_periodico_avisa_una_vez(self):
        app, _db = self.carpeta_instalada()
        actualizar.guardar_instalado(app, {"sha": SHA_A})
        emitidos = []
        act = self.actualizador(app, [{"sha": SHA_B}], emitir=lambda tipo, **d: emitidos.append((tipo, d)),
                                temporal=self.tmp)
        with mock.patch.object(actualizar, "ESPERA_INICIAL", 0):
            act.iniciar_periodico()
            fin = time.monotonic() + 5
            while not emitidos and time.monotonic() < fin:
                time.sleep(0.05)
            act.parar()
        self.assertEqual(emitidos[0][0], "actualizacion")
        self.assertTrue(emitidos[0][1]["info"]["disponible"])
        self.assertEqual(len(self.consultas), 1)                       # la siguiente, dentro de 6 horas
        self.assertEqual(actualizar.INTERVALO, 6 * 3600)


# ================================================================================================ actualizar
class TestActualizar(SinRed):
    def preparar(self, zip_bytes=None, remoto=None, nombre="BotWeb"):
        self.app, self.db = self.carpeta_instalada(nombre)
        actualizar.guardar_instalado(self.app, {"sha": SHA_A})
        self.temporal = os.path.join(self.tmp, "temp")
        os.makedirs(self.temporal, exist_ok=True)
        self.abrir = _Abrir({actualizar.URL_ZIP: zip_del_bot() if zip_bytes is None else zip_bytes})
        self.lanzados = []
        self.lineas = []
        return actualizar.Actualizador(
            raiz=self.app, consultar=lambda: remoto or {"sha": SHA_B, "mensaje": "Nueva", "fecha": "2026-11-10T15:00:00Z"},
            abrir=self.abrir, popen=lambda *a, **k: self.lanzados.append((a, k)), registrar=self.lineas.append,
            pid=4321, temporal=self.temporal)

    def test_copia_de_seguridad_descarga_y_lanza_el_instalador(self):
        act = self.preparar()
        res = act.actualizar(self.db)
        self.assertTrue(res["ok"])
        # copia de seguridad (con la fecha) junto a la base de datos, con los datos dentro
        self.assertRegex(os.path.basename(res["copia"]), r"^bot_antes_de_actualizar_\d{8}_\d{6}\.db$")
        self.assertEqual(os.path.dirname(res["copia"]), os.path.dirname(self.db))
        con = sqlite3.connect(res["copia"])
        self.assertEqual(con.execute("SELECT x FROM prueba").fetchone(), ("mis datos",))
        con.close()
        # descargado de la rama New-tool a una carpeta temporal NUEVA, descomprimido en su propia carpeta
        self.assertEqual(self.abrir.llamadas, [actualizar.URL_ZIP])
        carpeta = res["carpeta"]
        self.assertEqual(os.path.realpath(os.path.dirname(carpeta)), os.path.realpath(self.temporal))
        self.assertTrue(os.path.basename(carpeta).startswith(actualizar.PREFIJO_TEMPORAL))
        codigo = os.path.join(os.path.realpath(carpeta), "codigo", "Mapez-New-tool")
        self.assertEqual(actualizar.leer_instalado(codigo)["sha"], SHA_B)       # el instalador lo copiará a la app
        # el instalador descargado, en modo actualización, para esta instalación
        self.assertEqual(len(self.lanzados), 1)
        (comando,), k = self.lanzados[0]
        self.assertEqual(comando, 'cmd.exe /d /s /c ""%s""' % os.path.join(codigo, "instalador", "Instalar Bot Web.cmd"))
        env = k["env"]
        self.assertEqual((env["BOTWEB_ACTUALIZAR"], env["BOTWEB_FUENTE"], env["BOTWEB_ESPERAR_PID"]), ("1", "local", "4321"))
        self.assertEqual(env["BOTWEB_DESTINO"], os.path.dirname(self.app))
        self.assertNotIn("BOTWEB_NO_PREGUNTAR", env)
        self.assertEqual(k["cwd"], os.path.join(codigo, "instalador"))
        # el programa instalado no se ha tocado (lo cambia el instalador cuando este se cierre)
        self.assertEqual(sorted(os.listdir(self.app)), sorted([actualizar.MARCA_INSTALADOR, actualizar.ARCHIVO, "datos"]))

    def test_no_hereda_variables_de_prueba(self):
        act = self.preparar()
        with mock.patch.dict(os.environ, {"BOTWEB_SIN_ACCESOS": "1", "BOTWEB_URL_CODIGO": "http://127.0.0.1/x.zip"}):
            act.actualizar(self.db)
        env = self.lanzados[0][1]["env"]
        self.assertNotIn("BOTWEB_SIN_ACCESOS", env)
        self.assertNotIn("BOTWEB_URL_CODIGO", env)

    def test_copia_de_desarrollo_nunca_se_sobrescribe(self):
        raiz = self.carpeta_git()
        abrir = _Abrir({})
        lanzados = []
        act = actualizar.Actualizador(raiz=raiz, consultar=lambda: {"sha": SHA_B}, abrir=abrir,
                                      popen=lambda *a, **k: lanzados.append(a))
        with self.assertRaises(actualizar.ErrorActualizar) as e:
            act.actualizar(os.path.join(self.tmp, "no-existe.db"))
        self.assertIn("git", str(e.exception))
        self.assertEqual((abrir.llamadas, lanzados), ([], []))
        self.assertEqual(sorted(os.listdir(raiz)), [".git"])

    def test_copia_no_instalada(self):
        raiz = os.path.join(self.tmp, "suelta")
        os.makedirs(raiz)
        act = actualizar.Actualizador(raiz=raiz, consultar=lambda: {"sha": SHA_B}, abrir=_Abrir({}),
                                      popen=lambda *a, **k: self.fail("no debe lanzar nada"))
        with self.assertRaises(actualizar.ErrorActualizar) as e:
            act.actualizar(None)
        self.assertIn("Instalar Bot Web", str(e.exception))

    def test_sin_conexion(self):
        act = self.preparar()
        act._consultar = lambda: None
        with self.assertRaises(actualizar.ErrorActualizar) as e:
            act.actualizar(self.db)
        self.assertIn("conexión", str(e.exception))
        self.assertEqual((self.abrir.llamadas, self.lanzados), ([], []))
        self.assertEqual(os.listdir(os.path.dirname(self.db)), ["bot.db"])       # ni siquiera la copia

    def test_descarga_fallida(self):
        act = self.preparar()
        self.abrir.respuestas[actualizar.URL_ZIP] = urllib.error.URLError("se cortó")
        with self.assertRaises(actualizar.ErrorActualizar) as e:
            act.actualizar(self.db)
        self.assertIn("No se pudo descargar", str(e.exception))
        self.assertEqual(self.lanzados, [])
        self.assertEqual(os.listdir(self.temporal), [])                          # la carpeta temporal se borra

    def test_zip_que_no_es_el_bot(self):
        act = self.preparar(zip_bytes=zip_del_bot(con_bot=False))
        with self.assertRaises(actualizar.ErrorActualizar) as e:
            act.actualizar(self.db)
        self.assertIn("no es el bot", str(e.exception))
        self.assertEqual(self.lanzados, [])
        act = self.preparar(zip_bytes=b"esto no es un zip", nombre="Otra")
        with self.assertRaises(actualizar.ErrorActualizar):
            act.actualizar(self.db)
        self.assertEqual(self.lanzados, [])

    def test_zip_no_se_sale_de_su_carpeta(self):
        act = self.preparar(zip_bytes=zip_del_bot(extra={"../fuera.txt": "x", "Mapez-New-tool/../../fuera2.txt": "x"}))
        with self.assertRaises(actualizar.ErrorActualizar):
            act.actualizar(self.db)
        self.assertEqual(self.lanzados, [])
        for raiz, _dirs, archivos in os.walk(self.tmp):
            self.assertNotIn("fuera.txt", archivos, raiz)
            self.assertNotIn("fuera2.txt", archivos, raiz)

    def test_extraer_en_carpeta_nueva(self):
        destino = os.path.join(self.tmp, "ya_existe")
        os.makedirs(destino)
        ruta = os.path.join(self.tmp, "c.zip")
        with open(ruta, "wb") as f:
            f.write(zip_del_bot())
        with self.assertRaises(OSError):
            actualizar.extraer_zip(ruta, destino)

    def test_respaldo_sin_base_de_datos(self):
        self.assertIsNone(actualizar.respaldar_bd(os.path.join(self.tmp, "no-existe.db")))
        self.assertIsNone(actualizar.respaldar_bd(None))

    def test_limpiar_temporales_viejos(self):
        viejo = os.path.join(self.tmp, actualizar.PREFIJO_TEMPORAL + "viejo")
        nuevo = os.path.join(self.tmp, actualizar.PREFIJO_TEMPORAL + "nuevo")
        otro = os.path.join(self.tmp, "OtraCosa")
        for d in (viejo, nuevo, otro):
            os.makedirs(d)
        hace = time.time() - 3 * 86400
        os.utime(viejo, (hace, hace))
        os.utime(otro, (hace, hace))
        actualizar.limpiar_temporales(self.tmp)
        self.assertEqual((os.path.exists(viejo), os.path.exists(nuevo), os.path.exists(otro)), (False, True, True))


# ================================================================================================ la API
class _ActualizadorFalso:
    def __init__(self, error=None):
        self.error = error
        self.llamadas = []

    def estado(self):
        return {"activo": True, "disponible": True, "sha": "bbbbbbb", "novedades": "Nueva", "pospuesta": False}

    def comprobar(self, manual=False):
        self.llamadas.append(("comprobar", manual))
        return self.estado()

    def posponer(self):
        self.llamadas.append(("posponer",))
        return dict(self.estado(), pospuesta=True)

    def actualizar(self, ruta_db):
        self.llamadas.append(("actualizar", ruta_db))
        if self.error:
            raise actualizar.ErrorActualizar(self.error)
        return {"ok": True, "copia": ruta_db + ".copia", "carpeta": "x", "sha": "bbbbbbb"}


class BaseApp(SinRed):
    def setUp(self):
        super().setUp()
        self.alm = Almacen(os.path.join(self.tmp, "b.db"))
        self.addCleanup(self.alm.cerrar)
        self.app = su.Aplicacion(self.alm, carpeta_perfiles=os.path.join(self.tmp, "p"), carpeta_registros=self.tmp,
                                 carpeta_descargas=os.path.join(self.tmp, "d"), listar_tareas=lambda: [],
                                 oculto_forzado=True, ejecutar_tareas=lambda cmd: (0, "CORRECTO"),
                                 abrir_dialogo=lambda *a: None)
        self.addCleanup(self.app.detener)

    def api(self, metodo, ruta, datos=None):
        return self.app.api(metodo, "/api/" + ruta, datos or {}, {})


class TestApi(BaseApp):
    def test_sin_actualizador_no_se_mira_github(self):
        self.assertIsNone(self.app.actualizador)                       # (solo la aplicación de verdad lo pone)
        self.assertIsNone(self.api("GET", "estado")["actualizacion"])
        self.assertEqual(self.api("GET", "actualizacion"), {"activo": False, "disponible": False})
        with self.assertRaises(su.ErrorApi) as e:
            self.api("POST", "actualizacion/comprobar")
        self.assertIn("no está activa", str(e.exception))

    def test_estado_comprobar_y_mas_tarde(self):
        self.app.actualizador = falso = _ActualizadorFalso()
        self.assertTrue(self.api("GET", "estado")["actualizacion"]["disponible"])
        self.assertTrue(self.api("POST", "actualizacion/comprobar")["disponible"])
        self.assertTrue(self.api("POST", "actualizacion/mas-tarde")["pospuesta"])
        self.assertEqual(falso.llamadas, [("comprobar", True), ("posponer",)])
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "actualizacion/otra-cosa")

    def test_se_niega_mientras_trabaja(self):
        self.app.actualizador = falso = _ActualizadorFalso()
        t = su.Trabajo("ejecutar", "Ventas")
        self.app.trabajo = t
        with self.assertRaises(su.ErrorApi) as e:
            self.api("POST", "actualizacion/instalar")
        self.assertEqual(e.exception.codigo, 409)
        self.assertIn("está trabajando", str(e.exception))
        self.assertIn("Ventas", str(e.exception))
        t.estado = "ok"
        with mock.patch.object(self.app, "revisar_en_curso", lambda forzar=False: [{"terminado": False, "nombre": "Cobros"}]):
            with self.assertRaises(su.ErrorApi) as e:
                self.api("POST", "actualizacion/instalar")
        self.assertIn("tarea programada", str(e.exception))
        self.app.grabador = mock.Mock()
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "actualizacion/instalar")
        self.assertEqual(falso.llamadas, [])
        self.assertFalse(self.app.actualizando)

    def test_actualizar_cierra_el_programa(self):
        self.app.actualizador = falso = _ActualizadorFalso()
        r = self.api("POST", "actualizacion/instalar")
        self.assertTrue(r["ok"])
        self.assertEqual(falso.llamadas, [("actualizar", self.alm.ruta)])      # la copia, de la base de datos en uso
        self.assertTrue(self.app.actualizando)
        self.assertTrue(self.app.salir.wait(6))                                # el programa se cierra solo
        with self.assertRaises(su.ErrorApi) as e:                              # y ya no empieza nada más
            self.app.lanzar("ejecutar", "Otro", lambda t: (True, ""))
        self.assertIn("actualizando", str(e.exception))
        with self.assertRaises(su.ErrorApi):
            self.api("POST", "actualizacion/instalar")

    def test_error_explicado_y_se_puede_seguir(self):
        self.app.actualizador = _ActualizadorFalso(error="Esta copia del bot es la de desarrollo (git)")
        with self.assertRaises(su.ErrorApi) as e:
            self.api("POST", "actualizacion/instalar")
        self.assertIn("git", str(e.exception))
        self.assertFalse(self.app.actualizando)
        self.assertFalse(self.app.salir.wait(0.1))


class _ActualizadorUI(_ActualizadorFalso):
    """Para la interfaz: `disponible` se puede cambiar."""

    def __init__(self, disponible=True, **kw):
        super().__init__(**kw)
        self.disponible = disponible
        self.pospuesta = False

    def estado(self):
        return {"activo": True, "comprobado": True, "disponible": self.disponible, "sha": "bbbbbbb", "instalado": "aaaaaaa",
                "novedades": "Arreglo del calendario", "fecha": "10/11/2026", "copia_git": False, "sin_conexion": False,
                "pospuesta": self.pospuesta}

    def posponer(self):
        self.llamadas.append(("posponer",))
        self.pospuesta = True
        return self.estado()


try:
    sys.path.insert(0, os.path.join(RAIZ, "tests"))
    from test_integracion import HAY_PLAYWRIGHT       # noqa: E402
except ImportError:                                  # pragma: no cover
    HAY_PLAYWRIGHT = False


@unittest.skipUnless(HAY_PLAYWRIGHT, "Playwright no está instalado")
class TestInterfaz(BaseApp):
    """El aviso en la ventana (navegador oculto contra un servidor local con una base de datos temporal)."""
    PROHIBIR_PROCESOS = False

    def setUp(self):
        super().setUp()
        self.srv = su.ServidorUI(self.app).iniciar()
        self.addCleanup(self.srv.parar)

    def navegador(self, ancho=1280, alto=800):
        if getattr(self, "_nav", None) is None:
            from playwright.sync_api import sync_playwright
            self._p = sync_playwright().start()
            self.addCleanup(self._p.stop)
            self._nav = self._p.chromium.launch(channel="chrome", headless=True)
            self.addCleanup(self._nav.close)
        pg = self._nav.new_page(viewport={"width": ancho, "height": alto})
        self.errores = getattr(self, "errores", [])
        pg.on("pageerror", lambda e: self.errores.append(str(e)))
        return pg

    def abrir(self, pg):
        pg.goto(self.srv.url_con_token(), wait_until="load")
        pg.wait_for_selector("#contenido [data-pagina='inicio']", timeout=15000)

    def test_aviso_novedades_y_mas_tarde(self):
        self.app.actualizador = falso = _ActualizadorUI()
        for ancho in (375, 1280):
            falso.pospuesta = False
            pg = self.navegador(ancho)
            self.abrir(pg)
            pg.wait_for_selector("#actualizacion:not(.oculto) [data-actualizar]", timeout=5000)
            texto = pg.inner_text("#actualizacion")
            self.assertIn("Hay una nueva actualización", texto)
            self.assertIn("Novedades: Arreglo del calendario · 10/11/2026", texto)
            self.assertTrue(pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth"), ancho)
            pg.click("#actualizacion [data-mas-tarde]")
            pg.wait_for_selector("#actualizacion.oculto", state="attached", timeout=5000)
            pg.reload(wait_until="load")                                    # hasta que se vuelva a abrir el bot
            pg.wait_for_selector("#contenido [data-pagina='inicio']", timeout=15000)
            pg.wait_for_timeout(300)
            self.assertEqual(pg.locator("#actualizacion.oculto").count(), 1)
        self.assertIn(("posponer",), falso.llamadas)
        self.assertEqual(self.errores, [])

    def test_nunca_hay_desplazamiento_horizontal(self):
        """v3.9: a ningún ancho la página se desplaza en horizontal (ni con algo demasiado ancho dentro), y lo vertical
        y la barra de arriba (fija) siguen igual."""
        for ancho in (360, 400, 800, 1280):
            pg = self.navegador(ancho, 700)
            self.abrir(pg)
            for ruta in ("inicio", "reportes", "historial", "ajustes"):
                pg.evaluate("p => { location.hash = '#/' + p; }", ruta)
                pg.wait_for_selector("#contenido [data-pagina='%s']" % ruta, timeout=15000)
                self.assertTrue(pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth"), (ancho, ruta))
            r = pg.evaluate("""() => {
                const c = document.querySelector('#contenido');
                c.appendChild(Object.assign(document.createElement('div'), { style: 'width: 3000px; height: 3000px; background: #eee' }));
                c.appendChild(Object.assign(document.createElement('div'), { textContent: 'x'.repeat(400) }));
                window.scrollTo(600, 900);
                const barra = document.querySelector('.barra-sup').getBoundingClientRect();
                return { ancho: document.documentElement.scrollWidth, W: innerWidth, x: window.scrollX, y: window.scrollY,
                         barra: Math.round(barra.top), sticky: getComputedStyle(document.querySelector('.barra-sup')).position };
            }""")
            self.assertLessEqual(r["ancho"], r["W"], ancho)
            self.assertEqual(r["x"], 0, ancho)
            self.assertEqual(r["y"], 900, ancho)                                     # lo vertical sigue igual
            if r["sticky"] == "sticky":
                self.assertEqual(r["barra"], 0, ancho)                               # la barra sigue arriba
            pg.close()
        self.assertEqual(self.errores, [])

    def test_buscar_actualizaciones_al_dia(self):
        self.app.actualizador = _ActualizadorUI(disponible=False)
        pg = self.navegador()
        self.abrir(pg)
        self.assertEqual(pg.locator("#actualizacion.oculto").count(), 1)
        pg.evaluate("() => { location.hash = '#/ajustes'; }")
        pg.click("#contenido [data-buscar-actualizaciones]", timeout=15000)
        pg.wait_for_selector(".toast:has-text('Ya tienes la última versión')", timeout=5000)
        self.assertEqual(self.errores, [])

    def test_actualizar_y_negarse_mientras_trabaja(self):
        self.app.actualizador = falso = _ActualizadorUI()
        t = su.Trabajo("ejecutar", "Ventas")
        self.app.trabajo = t
        pg = self.navegador()
        self.abrir(pg)
        pg.click("#actualizacion [data-actualizar]", timeout=5000)
        pg.click(".modal .pie button:has-text('Actualizar ahora')")
        pg.wait_for_selector(".modal h2:has-text('No se puede actualizar ahora')", timeout=5000)
        self.assertIn("está trabajando", pg.inner_text(".modal"))
        self.assertEqual(falso.llamadas, [])
        pg.click(".modal .pie button:has-text('Entendido')")
        t.estado = "ok"
        pg.click("#actualizacion [data-actualizar]")
        pg.click(".modal .pie button:has-text('Actualizar ahora')")
        pg.wait_for_selector(".modal h2:has-text('Actualizando Bot Web')", timeout=5000)
        self.assertEqual(falso.llamadas, [("actualizar", self.alm.ruta)])
        self.assertTrue(self.app.salir.wait(6))
        self.assertEqual(self.errores, [])


# ================================================================================================ sin ventana
class TestSinVentana(SinRed):
    def test_las_tareas_de_windows_no_miran_github(self):
        import bot
        with mock.patch.object(actualizar, "Actualizador", side_effect=AssertionError("no debe crearse")), \
                mock.patch.object(actualizar, "consultar_remoto", side_effect=AssertionError("no debe mirar GitHub")):
            self.assertEqual(bot.principal(["--sin-ventana"]), 2)
            self.assertEqual(bot.principal(["--sin-ventana", "--todos", "--db", os.path.join(self.tmp, "v.db"),
                                            "--registros", self.tmp, "--perfil", os.path.join(self.tmp, "p"),
                                            "--carpeta-flujos", os.path.join(self.tmp, "f")]), 2)


# ================================================================================================ instalador y paquete
class TestInstalador(unittest.TestCase):
    def texto(self):
        with open(INSTALADOR, encoding="utf-8") as f:
            return f.read()

    def test_descarga_de_la_rama_new_tool(self):
        t = self.texto()
        self.assertIn("$UrlCodigo = 'https://github.com/Rfalso014/Mapez/archive/refs/heads/New-tool.zip'", t)
        self.assertNotIn("heads/main", t)
        self.assertNotIn("rama main", t)
        self.assertIn("la rama New-tool no existe", t)

    def test_modo_actualizacion(self):
        t = self.texto()
        for trozo in ("$Actualizando = ($env:BOTWEB_ACTUALIZAR -eq '1')", "-or $Actualizando", "Esperar-BotCerrado",
                      "BOTWEB_ESPERAR_PID", "Escribir-Version $nuevo $commit", "Abrir-Bot"):
            self.assertIn(trozo, t)
        self.assertLess(t.index("if ($Actualizando) { Esperar-BotCerrado }"), t.index("        Cerrar-BotAbierto"))

    def powershell(self, codigo, env=None, timeout=60):
        ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                          "powershell.exe")
        if not os.path.isfile(ps):
            self.skipTest("Sin PowerShell")
        guion = ("$env:BOTWEB_SOLO_FUNCIONES = '1'; $env:BOTWEB_SCRIPT = '%s'; "
                 ". ([scriptblock]::Create([IO.File]::ReadAllText($env:BOTWEB_SCRIPT, [Text.Encoding]::UTF8))); %s"
                 % (INSTALADOR.replace("'", "''"), codigo))
        entorno = {k: v for k, v in os.environ.items() if not k.upper().startswith("BOTWEB_")}
        entorno.update(env or {})
        r = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", guion], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout, env=entorno)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout.strip()

    def test_funciones_del_instalador(self):
        tmp = tempfile.mkdtemp(prefix="botweb_v39ps_")
        self.addCleanup(shutil.rmtree, tmp, True)
        destino = os.path.join(tmp, "BotWeb")
        salida = self.powershell(
            "Write-Output (Url-Api $UrlCodigo); Write-Output ('[' + (Url-Api 'http://127.0.0.1:8000/bot.zip') + ']'); "
            "Escribir-Version '%s' @{ sha = '%s'; fecha = '2026-11-10T15:00:00Z'; mensaje = 'Nueva versión' }; "
            "Write-Output $Actualizando; Write-Output $NoPreguntar" % (tmp.replace("'", "''"), SHA_B),
            env={"BOTWEB_DESTINO": destino, "BOTWEB_ACTUALIZAR": "1"})
        lineas = salida.splitlines()
        self.assertEqual(lineas[:4], ["https://api.github.com/repos/Rfalso014/Mapez/commits?sha=New-tool&per_page=1", "[]", "True", "True"])
        datos = actualizar.leer_instalado(tmp)
        self.assertEqual((datos["sha"], datos["fecha"], datos["mensaje"], datos["rama"]),
                         (SHA_B, "2026-11-10T15:00:00Z", "Nueva versión", "New-tool"))
        with open(os.path.join(tmp, actualizar.ARCHIVO), "rb") as f:
            self.assertFalse(f.read().startswith(b"\xef\xbb\xbf"))

    def test_espera_a_que_se_cierre_el_bot(self):
        tmp = tempfile.mkdtemp(prefix="botweb_v39ps_")
        self.addCleanup(shutil.rmtree, tmp, True)
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
        self.addCleanup(p.kill)
        inicio = time.monotonic()
        self.powershell("Esperar-BotCerrado 30 5", env={"BOTWEB_DESTINO": os.path.join(tmp, "BotWeb"),
                                                        "BOTWEB_ESPERAR_PID": str(p.pid)})
        self.assertIsNotNone(p.poll(), "el instalador no esperó a que se cerrara el bot")
        self.assertLess(time.monotonic() - inicio, 30)

    def test_paquete_lleva_la_version(self):
        sys.path.insert(0, os.path.join(RAIZ, "instalador"))
        self.addCleanup(sys.path.remove, os.path.join(RAIZ, "instalador"))
        import crear_paquete
        if not os.path.isdir(os.path.join(RAIZ, ".git")):
            self.skipTest("Sin git")
        datos = json.loads(crear_paquete.version_de_git().decode("utf-8"))
        self.assertRegex(datos["sha"], r"^[0-9a-f]{40}$")
        self.assertEqual((datos["rama"], datos["origen"]), ("New-tool", "paquete"))
        self.assertIsNotNone(actualizar._fecha(datos["fecha"]))

    def test_version_instalada_fuera_de_git(self):
        with open(os.path.join(RAIZ, ".gitignore"), encoding="utf-8") as f:
            self.assertIn("/actualizacion.json", f.read().split())


if __name__ == "__main__":
    unittest.main()
