"""Bot Web (versión 2): graba tus pasos en el navegador y los repite, visible u oculto.

Los reportes se guardan DENTRO de la aplicación (base de datos `datos/bot.db`).

Uso:
    python bot.py                                        abre la ventana
    python bot.py --reporte "Ventas" --sin-ventana       ejecuta ese reporte guardado y sale
    python bot.py --id 3 --id 5 --sin-ventana            varios reportes por número (lote)
    python bot.py --todos --sin-ventana                  todos los reportes guardados
    python bot.py --flujo archivo.json --sin-ventana     un archivo .json (compatibilidad)
    python bot.py --id 10 --sin-ventana --filtro "Elegir corte=43 - 2026 (02/10/2026 - 08/10/2026)"
                                                         con otra opción en un filtro (sin cambiar el reporte)
    python bot.py --pagina "Portal – Reportes" --favorito "Mayorista" [--filtro "Elegir corte=más reciente"]
                                                         (3.2) una Página guardada, sin ventana
    python bot.py --correo-id 2 [--oculto|--visible]     (3.4) revisa una búsqueda de correo («Correo»)
    python bot.py --correos                              (3.4) todas las búsquedas de correo activas
    python bot.py --id 3 --sin-ventana --aviso-antes 5 --avisar-inicio --avisar-fin --ventanita
                                                         (3.7) avisa 5 min antes, al empezar y al terminar, con la
                                                         ventanita de progreso (lo ponen las tareas de Windows)
Código de salida: 0 = todo bien, 1 = algo falló, 2 = no se pudo abrir el reporte.
Otras opciones: --url, --var clave=valor, --visible/--oculto, --lento, --navegador chrome|msedge,
--descargas CARPETA, --perfil CARPETA, --registros CARPETA, --db ARCHIVO, --carpeta-flujos CARPETA,
--ejecutar (en la ventana), --smoke.
"""

import argparse
import os
import queue
import shutil
import sqlite3
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from webbot import RAIZ, VERSION, carpeta, lote, plantillas, programador, secretos
from webbot import almacen as mod_almacen
from webbot.accesos import PeticionAcceso
from webbot.almacen import Almacen, ErrorAlmacen, nombre_perfil, ruta_por_defecto
from webbot.flujo import (BOTONES, ESTADOS, ESTRATEGIAS, FORMATOS_PAGINA, NOMBRES_ESTRATEGIA, NOMBRES_TIPO,
                          TIPOS_CON_CARGA, ErrorFlujo, Flujo, Paso, convertir_en_secreto, migrar_flujo,
                          nombre_secreto_sugerido, slug)

TITULO = "Bot Web - Descarga de reportes (v%s)" % VERSION
NAVEGADORES_GUI = {"Chrome": "chrome", "Edge": "msedge"}
CARGA_AUTO = "según el reporte"


# ============================================================ línea de comandos
def analizar_argumentos(argv=None):
    p = argparse.ArgumentParser(
        prog="bot.py", description="Bot Web: graba y repite tus pasos en el navegador para descargar reportes.")
    p.add_argument("--reporte", action="append", default=None, metavar="NOMBRE",
                   help="reporte guardado en la aplicación, por su nombre; se puede repetir")
    p.add_argument("--id", action="append", type=int, default=None, metavar="N",
                   help="reporte guardado en la aplicación, por su número; se puede repetir")
    p.add_argument("--todos", action="store_true", help="ejecutar todos los reportes guardados")
    p.add_argument("--flujo", action="append", default=None, metavar="ARCHIVO",
                   help="archivo de flujo (.json), por compatibilidad; se puede repetir")
    p.add_argument("--db", metavar="ARCHIVO", help="base de datos de los reportes (por defecto datos/bot.db)")
    p.add_argument("--carpeta-flujos", help="carpeta de flujos antiguos (.json) que se importan a la aplicación "
                                            "(por defecto, flujos/)")
    p.add_argument("--url", help="dirección de la página (sustituye la del flujo)")
    modo = p.add_mutually_exclusive_group()
    modo.add_argument("--oculto", action="store_true", help="navegador oculto (headless)")
    modo.add_argument("--visible", action="store_true", help="navegador visible")
    p.add_argument("--var", action="append", default=[], metavar="CLAVE=VALOR",
                   help="variable para las plantillas, p. ej. --var cliente=Acme (se puede repetir)")
    p.add_argument("--filtro", action="append", default=[], metavar="FILTRO=VALOR",
                   help="(3.1) elige otra opción en un filtro solo para esta ejecución, p. ej. "
                        "--filtro \"Elegir corte=43 - 2026 (02/10/2026 - 08/10/2026)\"; FILTRO = nombre del filtro "
                        "(como en «Usar filtros») o número de paso; VALOR = el texto de la opción o «más reciente». "
                        "Se puede repetir (el mismo filtro varias veces = una ejecución por valor)")
    p.add_argument("--pagina", metavar="NOMBRE",
                   help="(3.2) ejecuta una Página guardada (sin ventana) con sus valores por defecto, un --favorito y/o "
                        "--filtro \"Nombre=Valor\"; con --vigilar, revisa su filtro vigilado")
    p.add_argument("--pagina-id", type=int, metavar="N", help="(3.2) como --pagina, por su número (tareas programadas)")
    p.add_argument("--favorito", metavar="NOMBRE", help="(3.2) con --pagina: los valores de ese favorito")
    p.add_argument("--ejecutar", action="store_true", help="en la ventana: ejecutar el flujo nada más abrir")
    p.add_argument("--sin-ventana", action="store_true", help="ejecutar sin ventana y salir")
    p.add_argument("--lento", action="store_true", help="modo lento (pausa entre acciones)")
    p.add_argument("--navegador", choices=["chrome", "msedge"], help="navegador a usar")
    p.add_argument("--descargas", help="carpeta de descargas")
    p.add_argument("--perfil", help="carpeta del perfil del navegador")
    p.add_argument("--registros", help="carpeta de registros")
    p.add_argument("--smoke", action="store_true", help="comprueba que la ventana se construye y sale")
    p.add_argument("--clasica", action="store_true", help="abre la ventana clásica (tkinter) en vez de la nueva")
    p.add_argument("--vigilar", action="store_true",
                   help="revisa las vigilancias activas (de --id/--reporte o --pagina/--pagina-id, o todas) sin ventana, "
                        "avisa de lo nuevo y sale")
    p.add_argument("--vigilancia-id", type=int, metavar="N",
                   help="(3.3) revisa solo la vigilancia número N (implica --vigilar; la usan las tareas programadas)")
    p.add_argument("--correo-id", type=int, action="append", default=None, metavar="N",
                   help="(3.4) revisa la búsqueda de correo número N (descarga los adjuntos y copia los textos de los "
                        "correos nuevos) y sale; se puede repetir (la usan las tareas programadas)")
    p.add_argument("--correos", action="store_true", help="(3.4) revisa todas las búsquedas de correo activas y sale")
    # v3.7 «Avisos y vista» (los ponen las tareas de Windows según lo elegido en «Cuándo»)
    p.add_argument("--aviso-antes", type=int, default=0, metavar="MIN",
                   help="(3.7) avisa y espera MIN minutos antes de empezar (la tarea se lanza MIN minutos antes)")
    p.add_argument("--avisar-inicio", action="store_true", help="(3.7) notificación de Windows al empezar")
    p.add_argument("--avisar-fin", action="store_true", help="(3.7) notificación de Windows al terminar, con el resultado")
    p.add_argument("--ventanita", action="store_true", help="(3.7) ventanita con la barra de progreso y «Detener»")
    p.add_argument("--ventanita-de", type=int, metavar="N", help=argparse.SUPPRESS)      # (3.7) la ventanita en sí
    p.add_argument("--smoke-web", action="store_true",
                   help="arranca la interfaz nueva con una base de datos temporal, la carga oculta y sale")
    p.add_argument("--puerto", type=int, default=0, help="puerto de la interfaz nueva (por defecto, uno libre)")
    p.add_argument("--sin-navegador", action="store_true",
                   help="interfaz nueva: no abre la ventana (solo imprime la dirección)")
    return p.parse_args(argv)


def leer_variables(lista):
    res = {}
    for item in lista or []:
        if "=" not in item:
            raise SystemExit("La variable «%s» debe tener la forma clave=valor" % item)
        k, v = item.split("=", 1)
        res[k.strip()] = v
    return res


def buscar_archivo_flujo(ruta, carpeta_flujos=None):
    """Busca el archivo .json de un flujo: tal cual, en el proyecto, en flujos/ o con extensión .json.
    Devuelve la ruta absoluta o None."""
    candidatos = [ruta, os.path.join(RAIZ, ruta), os.path.join(RAIZ, "flujos", ruta)]
    if carpeta_flujos:
        candidatos.append(os.path.join(carpeta_flujos, ruta))
    for c in list(candidatos):
        if not c.lower().endswith(".json"):
            candidatos.append(c + ".json")
    for c in candidatos:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def resolver_ruta_flujo(ruta, carpeta_flujos=None):
    """Como buscar_archivo_flujo, pero lanza SystemExit si no existe."""
    encontrada = buscar_archivo_flujo(ruta, carpeta_flujos)
    if encontrada is None:
        raise SystemExit("No se encontró el flujo «%s»" % ruta)
    return encontrada


def carpeta_perfil_de(flujo, args=None, reporte_id=None):
    """Perfil del navegador: `--perfil` si se indicó; si no, `perfiles/reporte_<id>` para los reportes
    guardados (así renombrarlos no pierde la sesión) o `perfiles/<nombre>` para los que no están guardados."""
    if args is not None and getattr(args, "perfil", None):
        return os.path.abspath(args.perfil)
    if reporte_id is not None:
        return os.path.join(carpeta("perfiles"), nombre_perfil(reporte_id))
    return os.path.join(carpeta("perfiles"), slug(flujo.nombre))


def carpeta_perfiles_de(args):
    """Carpeta que contiene un perfil por reporte (en un lote, `--perfil` es esta carpeta)."""
    return os.path.abspath(args.perfil) if getattr(args, "perfil", None) else carpeta("perfiles")


def carpeta_flujos_de(args):
    if getattr(args, "carpeta_flujos", None):
        c = os.path.abspath(args.carpeta_flujos)
        os.makedirs(c, exist_ok=True)
        return c
    return carpeta("flujos")


def abrir_almacen(args):
    """La base de datos de reportes (`--db` o datos/bot.db)."""
    return Almacen(os.path.abspath(args.db) if getattr(args, "db", None) else None)


def migrar_flujos_antiguos(almacen, args):
    """Importa a la aplicación los flujos .json que queden en flujos/ (una sola vez: luego se mueven a
    flujos/_importados/).  Devuelve los mensajes para el usuario."""
    perfiles = None if getattr(args, "perfil", None) else carpeta("perfiles")
    cf = carpeta_flujos_de(args)
    res = almacen.migrar_carpeta(cf, perfiles)
    mensajes = []
    if res["importados"]:
        mensajes.append("Se importaron %d reporte%s de %s a la aplicación: %s. Los archivos originales quedan en %s."
                        % (len(res["importados"]), "" if len(res["importados"]) == 1 else "s", cf,
                           ", ".join("«%s»" % n for _, _, n in res["importados"]),
                           os.path.join(cf, "_importados")))
    for archivo, error in res["errores"]:
        mensajes.append("No se pudo importar %s: %s" % (archivo, error))
    return mensajes


def migrar_reportes(almacen):
    """Actualiza los reportes guardados con una versión anterior (con copia de seguridad de cada uno, que se
    puede restaurar en «Más ▾ → Versiones anteriores del reporte»).  Devuelve los mensajes para el usuario."""
    mensajes = []
    try:
        cambios = almacen.migrar_formato()
    except sqlite3.Error as e:
        return ["No se pudieron actualizar los reportes guardados: %s" % e]
    for _rid, nombre, cambios_rep, antes, despues in cambios:
        mensajes.append("Reporte «%s» actualizado a la v%s (%d → %d pasos): %s. Se guardó una copia de la versión "
                        "anterior (Más ▾ → Versiones anteriores del reporte)." % (
                            nombre, "2.3", antes, despues, "; ".join(cambios_rep)))
    try:                                            # v3.2: los reportes mapeados pasan a ser también Páginas (una vez)
        from webbot import paginas as mod_paginas
        mensajes += mod_paginas.convertir_mapas(almacen)
    except sqlite3.Error as e:
        mensajes.append("No se pudieron crear las páginas de los mapas guardados: %s" % e)
    mensajes += migrar_nombres_descarga(almacen)
    try:                                            # v3.6.1: los correos descartados por leer mal Outlook (una vez)
        n = almacen.olvidar_descartados_correo()
        if n:
            mensajes.append("Correo: se volverán a revisar %d correo(s) que el bot había descartado (ahora lee bien el "
                            "remitente en Outlook)." % n)
    except sqlite3.Error as e:
        mensajes.append("No se pudieron volver a revisar los correos descartados: %s" % e)
    return mensajes


def migrar_nombres_descarga(almacen):
    """v3.5 (una vez): las descargas que se guardaban con el nombre que da la web («report_xls (6).xlsx») pasan a
    llevar el nombre completo del reporte y la fecha.  Con copia de cada reporte en «Versiones anteriores»."""
    try:
        cambios = almacen.migrar_nombres_descarga()
    except sqlite3.Error as e:
        return ["No se pudo poner el nombre del reporte a las descargas: %s" % e]
    mensajes = []
    for _rid, nombre, pasos in cambios:
        detalle = "; ".join("paso %d: «%s» → «%s»" % (i + 1, antes, despues) for i, antes, despues in pasos)
        mensajes.append("Reporte «%s»: los archivos se guardarán con el nombre del reporte y la fecha (%s). Se guardó una "
                        "copia de la versión anterior (Más ▾ → Versiones anteriores del reporte)." % (nombre, detalle))
    if cambios:
        try:
            almacen.crear_notificacion(
                "nombres_descarga", "Las descargas llevan ahora el nombre del reporte",
                "%d reporte(s) guardaban sus archivos con el nombre que da la web (p. ej. «report_xls (6).xlsx»). Ahora se "
                "llaman como el reporte, con la fecha: «%s %s.xlsx». Si prefieres el de antes, edita el paso "
                "«Descargar» (botón «Nombre que da la web») o restaura la versión anterior del reporte."
                % (len(cambios), cambios[0][1], plantillas.renderizar("{hoy:%Y-%m-%d}")),
                {"reportes": [c[0] for c in cambios]})
        except sqlite3.Error:
            pass
    return mensajes


def objetivos_de(args, almacen=None, abrir=None):
    """Qué hay que ejecutar: ids de reportes guardados (int) y rutas de archivos .json (str), sin repetir.

    `abrir()` devuelve el almacén si hace falta (solo se abre la base de datos cuando se usa).
    Lanza SystemExit con el mensaje si algo no existe."""
    res = []

    def anadir(x):
        if isinstance(x, str):
            if x.lower() in [r.lower() for r in res if isinstance(r, str)]:
                return
        elif x in res:
            return
        res.append(x)

    def alm():
        nonlocal almacen
        if almacen is None:
            almacen = abrir()
        return almacen

    if getattr(args, "todos", False):
        for r in alm().listar():
            anadir(r["id"])
    for n in getattr(args, "id", None) or []:
        if alm().obtener(n) is None:
            raise SystemExit("No existe el reporte número %d" % n)
        anadir(n)
    for nombre in getattr(args, "reporte", None) or []:
        r = alm().obtener_por_nombre(nombre)
        if r is None:
            raise SystemExit("No existe el reporte «%s» (mira la lista de Reportes de la ventana)" % nombre)
        anadir(r["id"])
    cf = carpeta_flujos_de(args)
    for f in getattr(args, "flujo", None) or []:
        ruta = buscar_archivo_flujo(f, cf)
        if ruta is not None:
            anadir(ruta)
            continue
        # el archivo ya se importó a la aplicación (tareas programadas antiguas): se busca el reporte
        r = alm().obtener_por_origen(f) or alm().obtener_por_nombre(os.path.splitext(os.path.basename(f))[0])
        if r is None:
            raise SystemExit("No se encontró el flujo «%s»" % f)
        anadir(r["id"])
    return res


# v3.7 «Avisos y vista»: el seguimiento de la ejecución (avisos, espera previa, progreso en la tabla `en_curso`, ventanita)
def _seg(args):
    return getattr(args, "_seguimiento", None)


def _detener_de(args):
    """El Event que para la ejecución: el del seguimiento («Detener» de la ventanita o de la interfaz) o uno nuevo."""
    s = _seg(args)
    return s.detener if s is not None else threading.Event()


def _progreso_de(args, flujo, extra):
    """`progreso` para el ejecutor (el del seguimiento) o None; respeta uno que ya viniera en `extra`."""
    s = _seg(args)
    previo = extra.pop("progreso", None)
    if s is None:
        return previo
    hasta = extra.get("hasta")
    s.nuevo_flujo(min(int(hasta), len(flujo.pasos)) if hasta else len(flujo.pasos))

    def progreso(i, estado, texto=""):
        s.progreso(i, estado, texto)
        if previo is not None:
            previo(i, estado, texto)
    return progreso


def _log_de(args):
    s = _seg(args)

    def log(linea):
        print(linea, flush=True)
        if s is not None:
            s.anotar_log(linea)
    return log


def _anotar(args, res):
    s = _seg(args)
    if s is not None and res is not None:
        s.resultado(res)


def _con_seguimiento(args, funcion):
    """Ejecuta `funcion(args)` con el seguimiento: si se pidió, avisa y espera antes (`--aviso-antes`), avisa al empezar y
    al terminar (`--avisar-inicio` / `--avisar-fin`), apunta el progreso para la interfaz y abre la ventanita
    (`--ventanita`).  Solo para lo que está guardado en la base de datos (no para un --flujo suelto).  Si el seguimiento
    falla, la ejecución sigue como siempre."""
    usa_bd = bool(args.id or args.reporte or args.todos or args.pagina or args.pagina_id is not None or
                  args.vigilancia_id is not None or args.vigilar or args.correo_id or args.correos)
    if not usa_bd:
        return funcion(args)
    from webbot import seguimiento
    alm = None
    try:
        alm = abrir_almacen(args)
        seg = seguimiento.desde_args(args, alm)
    except Exception:              # noqa: BLE001  (sin seguimiento, como antes)
        if alm is not None:
            alm.cerrar()
        return funcion(args)
    args._seguimiento = seg
    codigo = 1
    try:
        if not seg.esperar_antes():
            print("Cancelada: esta vez no se ejecuta.", flush=True)
            return 0
        if seg.visible and not args.visible:              # «Ver en vivo» mientras esperaba
            args.visible, args.oculto = True, False
        seg.empezar()
        codigo = funcion(args)
        return codigo
    finally:
        try:
            seg.terminar(codigo)
        except Exception:          # noqa: BLE001
            pass
        args._seguimiento = None
        alm.cerrar()


def ejecutar_sin_ventana(args):
    from webbot.ejecutor import Ejecutor
    if not (args.flujo or args.todos or args.reporte or args.id):
        print("Con --sin-ventana hay que indicar qué ejecutar: --reporte \"Nombre\", --id N, --todos "
              "o --flujo archivo.json", file=sys.stderr)
        return 2
    almacen = None

    def abrir():
        nonlocal almacen
        try:
            almacen = abrir_almacen(args)
        except (sqlite3.Error, OSError) as e:
            raise SystemExit("No se pudo abrir la base de datos de reportes: %s" % e)
        for m in migrar_flujos_antiguos(almacen, args) + migrar_reportes(almacen):
            print(m, flush=True)
        return almacen

    try:
        try:
            objetivos = objetivos_de(args, abrir=abrir)
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            return 2
        if not objetivos:
            print("No hay ningún reporte guardado que ejecutar", file=sys.stderr)
            return 2
        variables = leer_variables(args.var)
        registros = os.path.abspath(args.registros) if args.registros else carpeta("registros")
        descargas = os.path.abspath(args.descargas) if args.descargas else None
        detener = _detener_de(args)

        if len(objetivos) > 1 or args.todos:
            if args.url:
                print("--url solo se puede usar con un único reporte", file=sys.stderr)
                return 2
            if args.filtro:
                print("--filtro solo se puede usar con un único reporte", file=sys.stderr)
                return 2
            try:
                res = lote.ejecutar_lote(
                    objetivos, carpeta_perfiles=carpeta_perfiles_de(args), carpeta_registros=registros,
                    carpeta_descargas=descargas, oculto=not args.visible, lento=args.lento, navegador=args.navegador,
                    variables=variables, log=_log_de(args), detener=detener, almacen=almacen)
            except KeyboardInterrupt:
                detener.set()
                print("Interrumpido.", file=sys.stderr)
                return 1
            _anotar(args, res)
            print(res.resumen())
            return 0 if res.ok else 1

        objetivo = objetivos[0]
        reporte_id = objetivo if isinstance(objetivo, int) else None
        try:
            flujo = almacen.cargar_flujo(reporte_id) if reporte_id is not None else Flujo.cargar(objetivo)
        except (ErrorFlujo, ErrorAlmacen, OSError) as e:
            print("No se pudo abrir el flujo: %s" % e, file=sys.stderr)
            return 2
        if args.url:
            flujo.aplicar_url(args.url)
        if args.navegador:
            flujo.opciones["navegador"] = args.navegador
        accesos = almacen          # un archivo .json suelto no abre la base de datos (accesos solo en memoria)
        # v3.1: --filtro → una ejecución por combinación (sin cambiar el reporte guardado)
        ejecuciones = [(flujo, None)]
        if args.filtro:
            from webbot import filtros as mod_filtros
            try:
                mapas = almacen.mapas(reporte_id, limite=5) if (almacen is not None and reporte_id is not None) else []
                nombres = {i: n for i, (n, _o) in mod_filtros.nombres(flujo, mapas).items()}
                combos = mod_filtros.combinaciones(flujo, mod_filtros.resolver_cli(flujo, args.filtro, mapas))
                if len(combos) > mod_filtros.MAX_EJECUCIONES:
                    raise mod_filtros.ErrorFiltros("Son %d ejecuciones: el máximo es %d" % (
                        len(combos), mod_filtros.MAX_EJECUCIONES))
                base = flujo.copia()
                for i, n in nombres.items():
                    if not base.pasos[i].filtro:
                        base.pasos[i].filtro = n
                ejecuciones = []
                for cambios, sufijo in combos:
                    mod_filtros.aplicar(base, cambios, sufijo)         # comprueba que se puede aplicar
                    ejecuciones.append((mod_filtros.aplicar(base, {}, sufijo)[0], cambios))
            except mod_filtros.ErrorFiltros as e:
                print(str(e), file=sys.stderr)
                return 2
            if len(ejecuciones) > mod_filtros.MAX_SIN_CONFIRMAR:
                print("Aviso: con esos filtros el reporte se ejecutará %d veces." % len(ejecuciones), flush=True)
        # Sin ventana no se puede preguntar: si falta una contraseña (o la rechazan) el reporte falla con un
        # mensaje claro y el código de salida es 1.
        todo_bien = True
        for n, (flujo_n, cambios) in enumerate(ejecuciones, 1):
            if len(ejecuciones) > 1:
                print("=== Ejecución %d de %d ===" % (n, len(ejecuciones)), flush=True)
            ej = Ejecutor(
                flujo_n, carpeta_perfil=carpeta_perfil_de(flujo, args, reporte_id), carpeta_registros=registros,
                carpeta_descargas=descargas, oculto=not args.visible, lento=args.lento, variables=variables,
                log=lambda linea: print(linea, flush=True), detener=detener, accesos=accesos, pedir_acceso=None,
                reporte_id=reporte_id, filtros=cambios, progreso=_progreso_de(args, flujo_n, {}))
            try:
                res = ej.ejecutar()
            except KeyboardInterrupt:
                detener.set()
                print("Interrumpido.", file=sys.stderr)
                return 1
            _anotar(args, res)
            if reporte_id is not None:
                try:
                    almacen.registrar_resultado(reporte_id, res)
                except sqlite3.Error:
                    pass
            if not res.ok and res.error:
                print(res.resumen(), file=sys.stderr, flush=True)
            print("Registro: %s" % res.ruta_log)
            todo_bien = todo_bien and res.ok
        return 0 if todo_bien else 1
    finally:
        if almacen is not None:
            almacen.cerrar()


def crear_ejecutor_cli(args, almacen, variables, registros, descargas, detener=None, log=None):
    """Fábrica de ejecutores para la vigilancia por línea de comandos (sin ventana: no se puede preguntar nada)."""
    from webbot.ejecutor import Ejecutor

    def crear(flujo, reporte_id=None, **extra):
        if args.navegador:
            flujo.opciones["navegador"] = args.navegador
        progreso = _progreso_de(args, flujo, extra)
        return Ejecutor(flujo, carpeta_perfil=carpeta_perfil_de(flujo, args, reporte_id), carpeta_registros=registros,
                        carpeta_descargas=descargas, oculto=not args.visible, lento=args.lento, variables=variables,
                        log=log, detener=detener, accesos=almacen, pedir_acceso=None, reporte_id=reporte_id,
                        progreso=progreso, **extra)
    return crear


def vigilar_sin_ventana(args, almacen=None):
    """--vigilar: revisa las vigilancias (3.3: puede haber varias por reporte y por Página).  Cuáles: --vigilancia-id N
    (esa, aunque esté pausada), las activas de los reportes indicados (--id/--reporte), las de una Página
    (--pagina/--pagina-id) o, sin nada, TODAS las activas (reportes y Páginas).
    Código 0 = revisiones correctas; 1 = alguna falló; 2 = no hay nada que vigilar (o no existe)."""
    from webbot import paginas as mod_paginas
    from webbot import vigilancia
    propio = almacen is None
    if propio:
        try:
            almacen = abrir_almacen(args)
        except (sqlite3.Error, OSError) as e:
            print("No se pudo abrir la base de datos de reportes: %s" % e, file=sys.stderr)
            return 2
    try:
        if propio:
            for m in migrar_reportes(almacen):
                print(m, flush=True)
        try:
            if getattr(args, "vigilancia_id", None) is not None:
                v = almacen.vigilancia_id(args.vigilancia_id)
                if v is None:
                    print("No existe la vigilancia número %s." % args.vigilancia_id, file=sys.stderr)
                    return 2
                vigs = [v]
            elif args.pagina or args.pagina_id is not None:
                vigs = almacen.lista_vigilancias(pagina_id=_pagina_de_args(args, almacen), solo_activas=True)
            else:
                ids = [x for x in objetivos_de(args, almacen=almacen) if isinstance(x, int)]
                if ids and not getattr(args, "todos", False):
                    vigs = [v for i in ids for v in almacen.lista_vigilancias(reporte_id=i, solo_activas=True)]
                else:
                    vigs = almacen.lista_vigilancias(solo_activas=True)
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            return 2
        except ErrorAlmacen as e:
            print(str(e), file=sys.stderr)
            return 2
        if not vigs:
            print("No hay ningún filtro vigilado (ninguna vigilancia activa).", file=sys.stderr)
            return 2
        registros = os.path.abspath(args.registros) if args.registros else carpeta("registros")
        descargas = os.path.abspath(args.descargas) if args.descargas else None
        variables = leer_variables(args.var)
        log = lambda linea: print(linea, flush=True)        # noqa: E731
        todo_bien = True
        for v in vigs:
            if v["tipo"] == "pagina":
                data = mod_paginas.normalizar(almacen.obtener_pagina(v["pagina_id"])["data"])
                crear = crear_ejecutor_pagina_cli(args, almacen, v["pagina_id"], data, variables, registros, descargas,
                                                  detener=_detener_de(args), log=log)
            else:
                crear = crear_ejecutor_cli(args, almacen, variables, registros, descargas, detener=_detener_de(args),
                                           log=log)
            try:
                r = vigilancia.revisar_vigilancia(almacen, v["id"], crear, log=log if v["tipo"] == "pagina" else None)
            except vigilancia.ErrorVigilancia as e:
                print(str(e), file=sys.stderr)
                todo_bien = False
                continue
            _anotar(args, r)
            print("[vigilancia %d] %s" % (v["id"], r.resumen()), flush=True)
            todo_bien = todo_bien and r.ok and all(res is not None and res.ok for _t, res in r.descargas)
        return 0 if todo_bien else 1
    finally:
        if propio:
            almacen.cerrar()


def _pagina_de_args(args, almacen):
    ref = args.pagina_id if args.pagina_id is not None else args.pagina
    return almacen.resolver_pagina(ref)


def crear_ejecutor_pagina_cli(args, almacen, pagina_id, data, variables, registros, descargas, detener=None, log=None):
    """Fábrica de ejecutores de una Página sin ventana (no se puede preguntar: si falta una contraseña, error claro)."""
    from webbot import paginas as mod_paginas
    from webbot.ejecutor import Ejecutor
    perfil = os.path.abspath(args.perfil) if args.perfil else mod_paginas.carpeta_perfil(carpeta("perfiles"), pagina_id,
                                                                                         data)

    def crear(flujo, reporte_id=None, **extra):
        if args.navegador:
            flujo.opciones["navegador"] = args.navegador
        progreso = _progreso_de(args, flujo, extra)
        return Ejecutor(flujo, carpeta_perfil=perfil, carpeta_registros=registros, carpeta_descargas=descargas,
                        oculto=not args.visible, lento=args.lento, variables=variables, log=log, detener=detener,
                        accesos=almacen, pedir_acceso=None, progreso=progreso, **extra)
    return crear


def ejecutar_pagina_sin_ventana(args):
    """--pagina / --pagina-id (3.2): ejecuta una Página guardada (una vez por combinación si --filtro repite un filtro).
    Código 0 = bien, 1 = alguna ejecución falló, 2 = no existe la página / el favorito / el filtro."""
    from webbot import paginas as mod_paginas
    try:
        almacen = abrir_almacen(args)
    except (sqlite3.Error, OSError) as e:
        print("No se pudo abrir la base de datos: %s" % e, file=sys.stderr)
        return 2
    try:
        for m in migrar_reportes(almacen):
            print(m, flush=True)
        try:
            pid = _pagina_de_args(args, almacen)
            fila = almacen.obtener_pagina(pid)
            data = mod_paginas.normalizar(fila["data"])
            sel = mod_paginas.seleccion_base(data, favorito=args.favorito,
                                             seleccion=mod_paginas.resolver_cli(data, args.filtro))
            combos = mod_paginas.preparar(data, sel)
        except (ErrorAlmacen, mod_paginas.ErrorPagina) as e:
            print(str(e), file=sys.stderr)
            return 2
        if len(combos) > mod_paginas.MAX_SIN_CONFIRMAR:
            print("Aviso: con esos filtros la página se ejecutará %d veces." % len(combos), flush=True)
        registros = os.path.abspath(args.registros) if args.registros else carpeta("registros")
        descargas = os.path.abspath(args.descargas) if args.descargas else None
        detener = _detener_de(args)
        crear = crear_ejecutor_pagina_cli(args, almacen, pid, data, leer_variables(args.var), registros, descargas,
                                          detener=detener, log=lambda linea: print(linea, flush=True))
        try:
            r = mod_paginas.ejecutar(almacen, pid, sel, crear, combos=combos, log=lambda linea: print(linea, flush=True),
                                     detener=detener)
        except KeyboardInterrupt:
            detener.set()
            print("Interrumpido.", file=sys.stderr)
            return 1
        _anotar(args, r)
        for _etiqueta, res in r.resultados:
            if not res.ok and res.error:
                print(res.resumen(), file=sys.stderr, flush=True)
            print("Registro: %s" % res.ruta_log)
        print(r.resumen(), flush=True)
        return 0 if r.ok else 1
    finally:
        almacen.cerrar()


def revisar_correo_sin_ventana(args, almacen=None, abrir_adaptador=None):
    """--correo-id N / --correos (3.4): revisa búsquedas de correo sin ventana (lo que ejecutan las tareas de Windows).
    Si la sesión del correo caducó, lo dice claro, crea el aviso en el bot y sale con 1 (no puede preguntar nada).
    Código 0 = bien (aunque no hubiera correos nuevos), 1 = alguna revisión falló, 2 = no existe la búsqueda."""
    from webbot import correo
    propio = almacen is None
    if propio:
        try:
            almacen = abrir_almacen(args)
        except (sqlite3.Error, OSError) as e:
            print("No se pudo abrir la base de datos: %s" % e, file=sys.stderr)
            return 2
    try:
        if args.correo_id:
            ids = []
            for n in args.correo_id:
                if almacen.busqueda_correo(n) is None:
                    print("No existe la búsqueda de correo número %s." % n, file=sys.stderr)
                    return 2
                ids.append(int(n))
        else:
            ids = [b["id"] for b in almacen.listar_busquedas_correo(solo_activas=True)]
            if not ids:
                print("No hay ninguna búsqueda de correo activa.", file=sys.stderr)
                return 2
        registros = os.path.abspath(args.registros) if args.registros else carpeta("registros")
        base = os.path.abspath(args.descargas) if args.descargas else (
            almacen.ajustes().get("carpeta_descargas") or os.path.join(RAIZ, "descargas"))
        perfiles = carpeta_perfiles_de(args)
        navegador = args.navegador or almacen.ajustes().get("navegador") or "chrome"
        log = _log_de(args)
        detener = _detener_de(args)
        if abrir_adaptador is None:
            def abrir_adaptador(cuenta):
                return correo.crear_adaptador(cuenta, perfiles, oculto=not args.visible, navegador=navegador, log=log,
                                              detener=detener)
        try:
            res = correo.revisar_varias(almacen, ids, abrir_adaptador, base, log=log, detener=detener,
                                        carpeta_registros=registros)
        except KeyboardInterrupt:
            detener.set()
            print("Interrumpido.", file=sys.stderr)
            return 1
        todo_bien = True
        for r in res:
            _anotar(args, r)
            print("[correo %d] %s" % (r.busqueda_id, r.resumen()), flush=True)
            if r.ruta_log:
                print("Registro: %s" % r.ruta_log)
            todo_bien = todo_bien and r.ok and not r.con_error
        return 0 if todo_bien else 1
    finally:
        if propio:
            almacen.cerrar()


def vigilar_pagina_sin_ventana(args, almacen=None):
    """--vigilar --pagina (3.2): revisa las vigilancias de una Página (3.3: todas las activas de esa Página)."""
    return vigilar_sin_ventana(args, almacen)


# ================================================================== diálogos
def _centrar(ventana, padre):
    ventana.update_idletasks()
    x = padre.winfo_rootx() + max(0, (padre.winfo_width() - ventana.winfo_width()) // 2)
    y = padre.winfo_rooty() + max(0, (padre.winfo_height() - ventana.winfo_height()) // 3)
    ventana.geometry("+%d+%d" % (x, y))


class DialogoPaso(tk.Toplevel):
    """Edita un paso: selectores, valor (con ayuda de plantillas), nota, opcional, timeout…"""

    def __init__(self, padre, paso, variables=None, opciones=None):
        super().__init__(padre)
        self.title("Editar paso: %s" % NOMBRES_TIPO.get(paso.tipo, paso.tipo))
        self.transient(padre)
        self.paso = paso
        self.variables = variables or {}
        self.opciones = opciones or {}
        self.aceptado = False
        self.vars = {}
        self.widgets = {}
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        self._fila = 0
        t = paso.tipo

        if t == "abrir_url":
            self._entrada(f, "url", "Dirección (URL):", paso.url, plantilla=True)
        if t in ("clic", "escribir", "tecla", "seleccionar", "marcar", "esperar_elemento", "descargar", "pasar_raton",
                 "elegir_opcion"):
            self._selectores(f)
            self._entrada(f, "objetivo", "Nombre del elemento (informativo):", paso.objetivo)
        if t == "pasar_raton":
            ttk.Label(f, foreground="#555555", wraplength=520, justify="left",
                      text="El bot pone el ratón encima de este elemento (sin hacer clic) para que se abra su menú; "
                           "el paso siguiente puede usar las opciones que aparecen."
                           + ("\nEste paso lo añadió el grabador automáticamente: el menú necesitaba el ratón encima."
                              if paso.auto else "")).grid(row=self._fila, column=0, columnspan=3, sticky="w")
            self._fila += 1
        if t in ("clic", "descargar"):
            self._combo(f, "boton", "Botón del ratón:", BOTONES, paso.boton)
            self._check(f, "doble", "Doble clic", paso.doble)
        if t == "escribir":
            self._entrada(f, "valor", "Texto a escribir:", paso.valor, plantilla=True)
        if t == "seleccionar":
            self._entrada(f, "valor", "Valor de la opción:", paso.valor, plantilla=True)
            self._entrada(f, "etiqueta", "Texto de la opción (por si cambia el valor):", paso.etiqueta)
        if t == "elegir_opcion":
            self._combo(f, "estrategia", "Qué opción elegir:", ESTRATEGIAS, paso.estrategia or "fija")
            self._entrada(f, "valor", "Texto (fija / contiene):", paso.valor, plantilla=True)
            ttk.Label(f, foreground="#555555", wraplength=520, justify="left",
                      text="fija = %s; mas_reciente = %s; primera / ultima; contiene = %s." % (
                          NOMBRES_ESTRATEGIA["fija"], NOMBRES_ESTRATEGIA["mas_reciente"], NOMBRES_ESTRATEGIA["contiene"])
                      ).grid(row=self._fila, column=0, columnspan=3, sticky="w")
            self._fila += 1
        if t == "tecla":
            self._entrada(f, "tecla", "Tecla (Enter, Escape, Tab…):", paso.tecla)
        if t == "marcar":
            self._check(f, "marcado", "Casilla marcada", paso.marcado)
        if t == "esperar_elemento":
            self._combo(f, "estado", "Esperar hasta que esté:", ESTADOS, paso.estado)
        if t == "esperar_texto":
            self._entrada(f, "texto", "Texto que debe aparecer:", paso.texto, plantilla=True)
        if t == "esperar_segundos":
            self._entrada(f, "segundos", "Segundos:", "%g" % paso.segundos)
        if t == "guardar_pagina":
            self._combo(f, "formato", "Formato:", FORMATOS_PAGINA, paso.formato or "html")
            ttk.Label(f, foreground="#555555", wraplength=520, justify="left",
                      text="PDF: la página tal como se imprime.  HTML: copia de la página.  "
                           "CSV: la tabla más grande de la página.").grid(row=self._fila, column=0, columnspan=3, sticky="w")
            self._fila += 1
        if t in ("descargar", "guardar_pagina"):
            self._entrada(f, "nombre", "Guardar como (nombre):", paso.nombre, plantilla=True, extra=True)
            self._entrada(f, "carpeta", "Carpeta (vacío = la de descargas):", paso.carpeta, plantilla=True)
        if t == "iniciar_sesion":
            self._editor_inicio_sesion(f)
        if t in TIPOS_CON_CARGA:
            actual = {None: CARGA_AUTO, True: "sí", False: "no"}.get(paso.esperar_carga, CARGA_AUTO)
            self._combo(f, "esperar_carga", "Esperar a que la página cargue después:", (CARGA_AUTO, "sí", "no"), actual)
        ttk.Separator(f).grid(row=self._fila, column=0, columnspan=3, sticky="ew", pady=6)
        self._fila += 1
        self._entrada(f, "nota", "Nota:", paso.nota)
        self._check(f, "opcional", "Opcional (si no aparece, sigue con el siguiente paso)", paso.opcional)
        self._check(f, "desactivado", "Desactivado (se conserva en la lista, pero no se ejecuta)", paso.desactivado)
        self._entrada(f, "timeout", "Tiempo máximo en segundos (vacío = automático):",
                      "" if paso.timeout is None else "%g" % paso.timeout)
        self.lbl_espera = ttk.Label(f, foreground="#555555", wraplength=520, justify="left")
        self.lbl_espera.grid(row=self._fila, column=0, columnspan=3, sticky="w")
        self._fila += 1
        self._texto_espera()
        self.vars["timeout"].trace_add("write", lambda *a: self._texto_espera())
        self._entrada(f, "pagina", "Pestaña (1 = la principal):", str(paso.pagina + 1))
        self.lbl_error = ttk.Label(f, foreground="#b91c1c", wraplength=520)
        self.lbl_error.grid(row=self._fila, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._fila += 1
        botones = ttk.Frame(f)
        botones.grid(row=self._fila, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(botones, text="Aceptar", command=self._aceptar).pack(side="left", padx=4)
        ttk.Button(botones, text="Cancelar", command=self.destroy).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._aceptar() if not isinstance(e.widget, tk.Text) else None)
        _centrar(self, padre)

    def _texto_espera(self):
        """Muestra la espera aprendida al grabar y el tiempo máximo que se usará al ejecutar."""
        try:
            tmo = self.vars["timeout"].get().strip().replace(",", ".")
            prueba = Paso.desde_dict(dict(self.paso.a_dict(), timeout=float(tmo) if tmo else None))
        except (ValueError, ErrorFlujo):
            return
        if prueba.tipo in ("descargar", "guardar_pagina"):
            efectivo = prueba.timeout_descarga_efectivo(self.opciones)
            motivo = "espera de descargas"
        else:
            efectivo = prueba.timeout_efectivo(self.opciones)
            motivo = "automático"
        aprendida = ("Espera aprendida al grabar: %g s.  " % prueba.espera_grabada) if prueba.espera_grabada is not None else ""
        propio = "propio" if prueba.timeout else motivo
        self.lbl_espera.configure(text="%sTiempo máximo que se usará al ejecutar: %g s (%s)." % (aprendida, efectivo, propio))

    # --- construcción de campos
    def _nueva_fila(self, f, etiqueta):
        ttk.Label(f, text=etiqueta).grid(row=self._fila, column=0, sticky="w", pady=3, padx=(0, 8))
        return self._fila

    def _entrada(self, f, clave, etiqueta, valor, plantilla=False, extra=False):
        fila = self._nueva_fila(f, etiqueta)
        v = tk.StringVar(value=valor)
        self.vars[clave] = v
        e = ttk.Entry(f, textvariable=v, width=52)
        e.grid(row=fila, column=1, sticky="ew", pady=3)
        if plantilla:
            mb = ttk.Menubutton(f, text="Plantilla…")
            menu = tk.Menu(mb, tearoff=0)
            for codigo, ayuda in plantillas.AYUDA_PLANTILLAS + ([("{ext}", "Extensión del archivo (.csv)"),
                                                                ("{nombre}", "Nombre original del archivo")]
                                                               if extra else []):
                menu.add_command(label="%s    (%s)" % (codigo, ayuda),
                                 command=lambda c=codigo, ent=e: ent.insert(tk.INSERT, c))
            mb["menu"] = menu
            mb.grid(row=fila, column=2, padx=(6, 0))
            self._fila += 1
            lbl = ttk.Label(f, foreground="#555555")
            lbl.grid(row=self._fila, column=1, sticky="w")
            v.trace_add("write", lambda *a, c=clave, l=lbl: self._previsualizar(c, l))
            self._previsualizar(clave, lbl)
        self._fila += 1
        self.widgets[clave] = e

    def _previsualizar(self, clave, lbl):
        texto = self.vars[clave].get()
        try:
            vista = plantillas.renderizar(texto, variables=self.variables, enmascarar_secretos=True,
                                          ext=".ext", nombre="original")
            lbl.configure(text="Vista previa: %s" % vista if plantillas.es_plantilla(texto) else "", foreground="#555555")
        except plantillas.ErrorPlantilla as e:
            lbl.configure(text="Plantilla no válida: %s" % e, foreground="#b91c1c")

    def _combo(self, f, clave, etiqueta, valores, actual):
        fila = self._nueva_fila(f, etiqueta)
        v = tk.StringVar(value=actual)
        self.vars[clave] = v
        ttk.Combobox(f, textvariable=v, values=list(valores), state="readonly", width=20).grid(
            row=fila, column=1, sticky="w", pady=3)
        self._fila += 1

    def _check(self, f, clave, texto, actual):
        v = tk.BooleanVar(value=actual)
        self.vars[clave] = v
        ttk.Checkbutton(f, text=texto, variable=v).grid(row=self._fila, column=0, columnspan=3, sticky="w", pady=2)
        self._fila += 1

    def _editor_inicio_sesion(self, f):
        """Paso «Iniciar sesión»: página, valor de cada campo (las contraseñas solo por su nombre) y botón de entrar."""
        self._entrada(f, "sitio", "Página (host):", self.paso.sitio)
        ttk.Label(f, foreground="#555555", wraplength=520, justify="left",
                  text="Si al llegar aquí la página ya tiene la sesión abierta, el paso se omite.  Si falta una "
                       "contraseña o la página la rechaza, el bot la pide (con la ventana abierta).  Los datos que "
                       "se escriben en ese momento se guardan en «Accesos».").grid(
            row=self._fila, column=0, columnspan=3, sticky="w")
        self._fila += 1
        for k, c in enumerate(self.paso.campos):
            nombre = c.get("etiqueta") or c.get("clave") or "Campo %d" % (k + 1)
            if c.get("tipo") == "clave":
                self._entrada(f, "campo_%d" % k, "%s — nombre de la contraseña guardada:" % nombre, c.get("secreto") or "")
            else:
                self._entrada(f, "campo_%d" % k, "%s:" % nombre, c.get("valor") or "", plantilla=True)
        fila = self._nueva_fila(f, "Botón para entrar (selectores,\nuno por línea; vacío = Enter):")
        t = tk.Text(f, width=52, height=3, wrap="none")
        t.insert("1.0", "\n".join((self.paso.enviar or {}).get("selectores") or []))
        t.grid(row=fila, column=1, columnspan=2, sticky="ew", pady=3)
        self.txt_enviar = t
        self._fila += 1

    def _datos_inicio_sesion(self, d):
        d["sitio"] = self.vars["sitio"].get().strip()
        campos = []
        for k, c in enumerate(self.paso.campos):
            c = dict(c)
            v = self.vars["campo_%d" % k].get()
            if c.get("tipo") == "clave":
                c.pop("valor", None)
                if v.strip():
                    c["secreto"] = v.strip()
                else:
                    c.pop("secreto", None)
            else:
                c["valor"] = v
            campos.append(c)
        d["campos"] = campos
        sels = [l.strip() for l in self.txt_enviar.get("1.0", "end").splitlines() if l.strip()]
        enviar = dict(self.paso.enviar or {})
        if sels:
            enviar["selectores"] = sels
            enviar.pop("tecla", None)
        else:
            enviar = {"tecla": "Enter"}
        d["enviar"] = enviar

    def _selectores(self, f):
        fila = self._nueva_fila(f, "Selectores (uno por línea,\nel primero que funcione):")
        t = tk.Text(f, width=52, height=4, wrap="none")
        t.insert("1.0", "\n".join(self.paso.selectores))
        t.grid(row=fila, column=1, columnspan=2, sticky="ew", pady=3)
        self.txt_selectores = t
        self._fila += 1

    # --- aceptar
    def _aceptar(self):
        d = self.paso.a_dict()
        v = self.vars
        try:
            for clave in ("url", "valor", "etiqueta", "tecla", "texto", "nombre", "carpeta", "objetivo", "nota",
                          "boton", "estado", "formato", "estrategia"):
                if clave in v:
                    d[clave] = v[clave].get()
            for clave in ("doble", "marcado", "opcional", "desactivado"):
                if clave in v:
                    d[clave] = bool(v[clave].get())
            if "esperar_carga" in v:
                d["esperar_carga"] = {CARGA_AUTO: None, "sí": True, "no": False}.get(v["esperar_carga"].get())
            if self.paso.tipo == "iniciar_sesion":
                self._datos_inicio_sesion(d)
            if "segundos" in v:
                d["segundos"] = float(v["segundos"].get().replace(",", "."))
            tmo = v["timeout"].get().strip().replace(",", ".")
            d["timeout"] = float(tmo) if tmo else None
            pag = int(v["pagina"].get().strip() or "1")
            if pag < 1:
                raise ValueError
            d["pagina"] = pag - 1
        except ValueError:
            self.lbl_error.configure(text="Revisa los números: segundos, tiempo máximo y pestaña deben ser válidos.")
            return
        if hasattr(self, "txt_selectores"):
            d["selectores"] = [l.strip() for l in self.txt_selectores.get("1.0", "end").splitlines() if l.strip()]
        try:
            nuevo = Paso.desde_dict(d)
        except ErrorFlujo as e:
            self.lbl_error.configure(text=str(e))
            return
        problemas = nuevo.problemas()
        if problemas:
            self.lbl_error.configure(text="; ".join(problemas))
            return
        for campo, valor in nuevo.a_dict().items():
            setattr(self.paso, campo, valor)
        for campo in list(vars(self.paso)):                 # campos que volvieron a su valor por defecto
            if campo not in nuevo.a_dict():
                setattr(self.paso, campo, getattr(Paso(self.paso.tipo), campo))
        self.aceptado = True
        self.destroy()


class DialogoContrasenas(tk.Toplevel):
    """Lista, guarda y borra contraseñas (nunca muestra los valores)."""

    def __init__(self, padre):
        super().__init__(padre)
        self.title("Contraseñas guardadas")
        self.transient(padre)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Se guardan en el Administrador de credenciales de Windows.\n"
                          "Los pasos solo recuerdan el nombre, p. ej. {secreto:portal:clave}.",
                  justify="left").pack(anchor="w")
        self.lista = tk.Listbox(f, height=10, width=50, exportselection=False)
        self.lista.pack(fill="both", expand=True, pady=8)
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="Añadir / cambiar…", command=self._anadir).pack(side="left", padx=(0, 6))
        ttk.Button(b, text="Borrar", command=self._borrar).pack(side="left")
        ttk.Button(b, text="Cerrar", command=self.destroy).pack(side="right")
        self._refrescar()
        _centrar(self, padre)

    def _refrescar(self):
        self.lista.delete(0, "end")
        try:
            for n in secretos.listar():
                self.lista.insert("end", n)
        except secretos.ErrorSecreto as e:
            messagebox.showerror("Contraseñas", str(e), parent=self)

    def _anadir(self):
        nombre = simpledialog.askstring("Nombre", "Nombre de la contraseña (p. ej. portal:clave):", parent=self)
        if not nombre:
            return
        valor = simpledialog.askstring("Contraseña", "Escribe la contraseña para «%s»:" % nombre.strip(),
                                       show="*", parent=self)
        if not valor:
            return
        try:
            secretos.guardar(nombre, valor)
        except secretos.ErrorSecreto as e:
            messagebox.showerror("Contraseñas", str(e), parent=self)
        self._refrescar()

    def _borrar(self):
        sel = self.lista.curselection()
        if not sel:
            return
        nombre = self.lista.get(sel[0])
        if messagebox.askyesno("Borrar", "¿Borrar la contraseña «%s»?" % nombre, parent=self):
            try:
                secretos.borrar(nombre)
            except secretos.ErrorSecreto as e:
                messagebox.showerror("Contraseñas", str(e), parent=self)
            self._refrescar()


class DialogoAcceso(tk.Toplevel):
    """«La página «host» pide iniciar sesión»: muestra los campos que detectó el bot (contraseñas ocultas con *),
    con los valores conocidos, y la casilla «Recordar».  `respuesta` = {"valores": {...}, "recordar": bool} o None."""

    def __init__(self, padre, solicitud):
        super().__init__(padre)
        self.solicitud = solicitud
        self.respuesta = None
        host = solicitud.get("host") or "la página"
        fallida = solicitud.get("tipo") == "clave_fallida"
        self.title(("La contraseña de %s falló" if fallida else "Iniciar sesión en %s") % host)
        self.transient(padre)
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text=("La contraseña de «%s» falló" if fallida else "La página «%s» pide iniciar sesión") % host,
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        texto = solicitud.get("mensaje") or ""
        if solicitud.get("error_pagina"):
            texto += "\nLa página dice: «%s»" % solicitud["error_pagina"][:200]
        ttk.Label(f, text=texto, wraplength=440, justify="left",
                  foreground="#b91c1c" if solicitud.get("rechazada") else "#374151").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 10))
        self.vars = {}
        fila = 2
        primero = None
        for c in solicitud.get("campos") or []:
            etiqueta = c.get("etiqueta") or c.get("clave") or "Campo"
            ttk.Label(f, text=etiqueta + ("" if c.get("requerido", True) else " (opcional)") + ":").grid(
                row=fila, column=0, sticky="w", padx=(0, 8), pady=3)
            v = tk.StringVar(value=c.get("valor") or "")
            e = ttk.Entry(f, textvariable=v, width=36, show="*" if c.get("tipo") == "clave" else "")
            e.grid(row=fila, column=1, sticky="ew", pady=3)
            if c.get("tipo") == "clave":
                ver = tk.BooleanVar(value=False)
                ttk.Checkbutton(f, text="Mostrar", variable=ver,
                                command=lambda e=e, ver=ver: e.configure(show="" if ver.get() else "*")).grid(
                    row=fila, column=2, sticky="w", padx=(6, 0))
            if primero is None and not v.get():
                primero = e
            self.vars[c.get("clave")] = v
            fila += 1
        self.v_recordar = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Recordar (las contraseñas van al Administrador de credenciales de Windows)",
                        variable=self.v_recordar).grid(row=fila, column=0, columnspan=2, sticky="w", pady=(8, 0))
        fila += 1
        b = ttk.Frame(f)
        b.grid(row=fila, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Guardar y reintentar" if fallida else "Aceptar", command=self._aceptar).pack(side="left", padx=4)
        ttk.Button(b, text="Cancelar", command=self._cancelar).pack(side="left")
        self.bind("<Return>", lambda e: self._aceptar())
        self.bind("<Escape>", lambda e: self._cancelar())
        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        _centrar(self, padre)
        if primero is not None:
            primero.focus_set()

    def valores(self):
        return {k: v.get() for k, v in self.vars.items()}

    def _aceptar(self):
        self.respuesta = {"valores": self.valores(), "recordar": bool(self.v_recordar.get())}
        self.destroy()

    def _cancelar(self):
        self.respuesta = None
        self.destroy()


class DialogoAccesos(tk.Toplevel):
    """🔑 Accesos: datos de acceso guardados por sitio (usuario, licencia… y el nombre de la contraseña).
    Permite cambiar valores y contraseñas y borrar.  Las contraseñas nunca se muestran."""

    def __init__(self, padre, almacen):
        super().__init__(padre)
        self.almacen = almacen
        self.title("Accesos guardados")
        self.transient(padre)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Datos con los que el bot inicia sesión en cada página.  Las contraseñas se guardan en el\n"
                          "Administrador de credenciales de Windows (aquí solo se ve su nombre).",
                  justify="left").pack(anchor="w")
        cols = ("sitio", "campo", "tipo", "valor")
        self.arbol = ttk.Treeview(f, columns=cols, show="headings", height=10, selectmode="browse")
        for c, t, w in (("sitio", "Página", 190), ("campo", "Campo", 150), ("tipo", "Tipo", 80), ("valor", "Valor", 230)):
            self.arbol.heading(c, text=t)
            self.arbol.column(c, width=w, anchor="w")
        self.arbol.pack(fill="both", expand=True, pady=8)
        self.arbol.bind("<Double-1>", lambda e: self._editar())
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="Cambiar valor…", command=self._editar).pack(side="left", padx=(0, 6))
        ttk.Button(b, text="Cambiar contraseña…", command=self._cambiar_clave).pack(side="left", padx=(0, 6))
        ttk.Button(b, text="Borrar", command=self._borrar).pack(side="left", padx=(0, 6))
        ttk.Button(b, text="Borrar la página entera", command=self._borrar_sitio).pack(side="left", padx=(0, 6))
        ttk.Button(b, text="Contraseñas sueltas…", command=self._contrasenas).pack(side="left")
        ttk.Button(b, text="Cerrar", command=self.destroy).pack(side="right")
        self.filas = {}
        self._refrescar()
        _centrar(self, padre)

    def _refrescar(self):
        self.arbol.delete(*self.arbol.get_children())
        self.filas = {}
        try:
            accesos = self.almacen.listar_accesos()
        except sqlite3.Error as e:
            messagebox.showerror("Accesos", str(e), parent=self)
            return
        for n, a in enumerate(accesos):
            iid = str(n)
            self.filas[iid] = a
            if a["tipo"] == "clave":
                valor = "•••••• (%s)" % (a.get("secreto") or "?")
            else:
                valor = a.get("valor") or ""
            self.arbol.insert("", "end", iid=iid, values=(a["host"], a.get("etiqueta") or a["clave"],
                                                          "contraseña" if a["tipo"] == "clave" else "texto", valor))

    def _sel(self):
        s = self.arbol.selection()
        return self.filas.get(s[0]) if s else None

    def _editar(self):
        a = self._sel()
        if a is None:
            return
        if a["tipo"] == "clave":
            return self._cambiar_clave()
        nuevo = simpledialog.askstring("Cambiar valor", "«%s» en %s:" % (a.get("etiqueta") or a["clave"], a["host"]),
                                       initialvalue=a.get("valor") or "", parent=self)
        if nuevo is None:
            return
        self.almacen.guardar_acceso(a["host"], a["clave"], a.get("etiqueta"), "texto", valor=nuevo,
                                    selectores=a.get("selectores"))
        self._refrescar()

    def _cambiar_clave(self):
        a = self._sel()
        if a is None or a["tipo"] != "clave":
            messagebox.showinfo("Cambiar contraseña", "Elige una fila de tipo «contraseña».", parent=self)
            return
        valor = simpledialog.askstring("Cambiar contraseña", "Nueva contraseña de «%s» en %s:" % (
            a.get("etiqueta") or a["clave"], a["host"]), show="*", parent=self)
        if not valor:
            return
        nombre = a.get("secreto") or "%s:%s" % (a["host"], a["clave"])
        try:
            secretos.guardar(nombre, valor)
            self.almacen.guardar_acceso(a["host"], a["clave"], a.get("etiqueta"), "clave", secreto=nombre,
                                        selectores=a.get("selectores"))
        except (secretos.ErrorSecreto, ErrorAlmacen) as e:
            messagebox.showerror("Cambiar contraseña", str(e), parent=self)
        self._refrescar()

    def _borrar(self):
        a = self._sel()
        if a is None:
            return
        extra = "\n(También se borrará la contraseña guardada «%s».)" % a["secreto"] if a.get("secreto") else ""
        if not messagebox.askyesno("Borrar", "¿Borrar «%s» de %s?%s" % (a.get("etiqueta") or a["clave"], a["host"], extra),
                                   parent=self):
            return
        if a.get("secreto"):
            try:
                secretos.borrar(a["secreto"])
            except secretos.ErrorSecreto as e:
                messagebox.showerror("Borrar", str(e), parent=self)
        self.almacen.borrar_acceso(a["host"], a["clave"])
        self._refrescar()

    def _borrar_sitio(self):
        a = self._sel()
        if a is None:
            return
        if not messagebox.askyesno("Borrar", "¿Borrar todos los datos de acceso de %s (y sus contraseñas guardadas)?"
                                   % a["host"], parent=self):
            return
        for x in self.almacen.accesos_de(a["host"]):
            if x.get("secreto"):
                try:
                    secretos.borrar(x["secreto"])
                except secretos.ErrorSecreto:
                    pass
        self.almacen.borrar_acceso(a["host"])
        self._refrescar()

    def _contrasenas(self):
        dlg = DialogoContrasenas(self)
        dlg.grab_set()
        self.wait_window(dlg)


class DialogoVersiones(tk.Toplevel):
    """Copias anteriores de un reporte (p. ej. la de antes de actualizar a la v2.3): permite restaurarlas."""

    def __init__(self, padre, almacen, reporte_id, nombre, al_restaurar=None):
        super().__init__(padre)
        self.almacen = almacen
        self.reporte_id = reporte_id
        self.al_restaurar = al_restaurar
        self.title("Versiones anteriores de «%s»" % nombre)
        self.transient(padre)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Copias que guardó la aplicación antes de cambiar el reporte por su cuenta.").pack(anchor="w")
        self.arbol = ttk.Treeview(f, columns=("cuando", "motivo"), show="headings", height=8, selectmode="browse")
        self.arbol.heading("cuando", text="Fecha")
        self.arbol.heading("motivo", text="Motivo")
        self.arbol.column("cuando", width=140)
        self.arbol.column("motivo", width=380)
        self.arbol.pack(fill="both", expand=True, pady=8)
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="Restaurar esta copia", command=self._restaurar).pack(side="left")
        ttk.Button(b, text="Cerrar", command=self.destroy).pack(side="right")
        for v in almacen.versiones(reporte_id):
            self.arbol.insert("", "end", iid=str(v["id"]), values=(v["cuando"], v["motivo"]))
        _centrar(self, padre)

    def _restaurar(self):
        s = self.arbol.selection()
        if not s:
            return
        if not messagebox.askyesno("Restaurar", "¿Volver el reporte a esta copia? (la versión actual se guarda también "
                                                "como copia, por si acaso)", parent=self):
            return
        try:
            self.almacen.restaurar_version(int(s[0]))
        except ErrorAlmacen as e:
            messagebox.showerror("Restaurar", str(e), parent=self)
            return
        if self.al_restaurar:
            self.al_restaurar(self.reporte_id)
        self.destroy()


class DialogoProgramar(tk.Toplevel):
    """Crea o elimina una tarea del Programador de tareas de Windows (con confirmación).

    Puede programar un reporte, los reportes marcados en la lista (lote) o todos (`--todos`).  Los
    reportes van por su número (`--id N`), así que la tarea sigue funcionando aunque se renombren."""

    def __init__(self, padre, reporte_id, nombre_reporte, variables, seleccionados=None, n_todos=0, modo=None, db=None):
        super().__init__(padre)
        self.title("Programar ejecución")
        self.transient(padre)
        self.reporte_id = reporte_id
        self.variables = variables
        self.seleccionados = list(seleccionados or [])        # ids
        self.nombre_reporte = nombre_reporte
        self.db = db
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        modo = modo or ("este" if reporte_id is not None else ("seleccion" if self.seleccionados else "todos"))
        self.v_modo = tk.StringVar(value=modo)
        self.v_nombre = tk.StringVar(value=self._nombre_por_modo(modo))
        self.v_frec = tk.StringVar(value="Diaria")
        self.v_hora = tk.StringVar(value="07:00")
        self.v_dias = {d: tk.BooleanVar(value=(d in ("MON", "TUE", "WED", "THU", "FRI"))) for d in programador.DIAS}
        marco = ttk.LabelFrame(f, text="Qué se programa", padding=6)
        marco.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        r1 = ttk.Radiobutton(marco, text="Solo este reporte: %s" % nombre_reporte, variable=self.v_modo, value="este",
                             command=self._cambio_modo)
        r2 = ttk.Radiobutton(marco, text="Los %d reportes marcados en la lista" % len(self.seleccionados),
                             variable=self.v_modo, value="seleccion", command=self._cambio_modo)
        r3 = ttk.Radiobutton(marco, text="Todos los reportes guardados (%d)" % n_todos,
                             variable=self.v_modo, value="todos", command=self._cambio_modo)
        if reporte_id is None:
            r1.state(["disabled"])
        if not self.seleccionados:
            r2.state(["disabled"])
        for r in (r1, r2, r3):
            r.pack(anchor="w")
        ttk.Label(f, text="Nombre de la tarea:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_nombre, width=34).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(f, text="Frecuencia:").grid(row=2, column=0, sticky="w", pady=3)
        c = ttk.Combobox(f, textvariable=self.v_frec, values=["Diaria", "Semanal"], state="readonly", width=12)
        c.grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Hora (HH:MM, 24 h):").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_hora, width=8).grid(row=3, column=1, sticky="w", pady=3)
        dias = ttk.Frame(f)
        dias.grid(row=4, column=0, columnspan=2, sticky="w", pady=3)
        for d in programador.DIAS:
            ttk.Checkbutton(dias, text=programador.DIAS_ES[d][:3].capitalize(), variable=self.v_dias[d]).pack(side="left")
        ttk.Label(f, text="(los días solo se usan en la frecuencia semanal)", foreground="#555555").grid(
            row=5, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Se ejecuta oculto, con tu usuario y solo si tienes la sesión de Windows iniciada. "
                          "Los reportes van por su número: puedes renombrarlos sin volver a programar.",
                  wraplength=420, foreground="#555555").grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.lbl_cmd = tk.Text(f, width=62, height=5, wrap="word", state="disabled", background="#f3f4f6")
        self.lbl_cmd.grid(row=7, column=0, columnspan=2, sticky="ew", pady=6)
        b = ttk.Frame(f)
        b.grid(row=8, column=0, columnspan=2, sticky="e")
        ttk.Button(b, text="Crear tarea…", command=self._crear).pack(side="left", padx=4)
        ttk.Button(b, text="Eliminar tarea…", command=self._borrar).pack(side="left", padx=4)
        ttk.Button(b, text="Cerrar", command=self.destroy).pack(side="left")
        for v in (self.v_nombre, self.v_frec, self.v_hora, self.v_modo, *self.v_dias.values()):
            v.trace_add("write", lambda *a: self._mostrar())
        self._mostrar()
        _centrar(self, padre)

    def _nombre_por_modo(self, modo):
        if modo == "este":
            return slug(self.nombre_reporte)
        return "Reportes seleccionados" if modo == "seleccion" else "Todos los reportes"

    def _cambio_modo(self):
        self.v_nombre.set(self._nombre_por_modo(self.v_modo.get()))

    def _comando(self):
        dias = [d for d, v in self.v_dias.items() if v.get()]
        modo = self.v_modo.get()
        db = self.db if self.db and os.path.abspath(self.db).lower() != ruta_por_defecto().lower() else None
        comun = dict(frecuencia=self.v_frec.get(), dias=dias, oculto=True, variables=self.variables, db=db)
        ruta_bot = os.path.join(RAIZ, "bot.py")
        if modo == "todos":
            return programador.construir_comando_crear(self.v_nombre.get(), ruta_bot, None, self.v_hora.get(),
                                                       todos=True, **comun)
        ids = self.seleccionados if modo == "seleccion" else ([self.reporte_id] if self.reporte_id is not None else [])
        return programador.construir_comando_crear(self.v_nombre.get(), ruta_bot, None, self.v_hora.get(),
                                                   ids=ids, **comun)

    def _mostrar(self):
        try:
            texto = programador.como_texto(self._comando())
        except programador.ErrorProgramador as e:
            texto = "(%s)" % e
        self.lbl_cmd.configure(state="normal")
        self.lbl_cmd.delete("1.0", "end")
        self.lbl_cmd.insert("1.0", texto)
        self.lbl_cmd.configure(state="disabled")

    def _crear(self):
        try:
            cmd = self._comando()
        except programador.ErrorProgramador as e:
            messagebox.showerror("Programar", str(e), parent=self)
            return
        if not messagebox.askyesno("Confirmar", "Se creará esta tarea en el Programador de tareas de Windows:\n\n%s\n\n¿Continuar?"
                                   % programador.como_texto(cmd), parent=self):
            return
        try:
            programador.crear(cmd, confirmado=True)
        except programador.ErrorProgramador as e:
            messagebox.showerror("Programar", str(e), parent=self)
            return
        messagebox.showinfo("Programar", "Tarea creada: %s" % programador.nombre_tarea(self.v_nombre.get()), parent=self)

    def _borrar(self):
        try:
            nombre = programador.nombre_tarea(self.v_nombre.get())
        except programador.ErrorProgramador as e:
            messagebox.showerror("Programar", str(e), parent=self)
            return
        if not messagebox.askyesno("Confirmar", "¿Eliminar la tarea «%s» del Programador de tareas?" % nombre, parent=self):
            return
        try:
            programador.borrar(self.v_nombre.get(), confirmado=True)
        except programador.ErrorProgramador as e:
            messagebox.showerror("Programar", str(e), parent=self)
            return
        messagebox.showinfo("Programar", "Tarea eliminada.", parent=self)


class DialogoPapelera(tk.Toplevel):
    """Reportes eliminados: se pueden recuperar (o borrar para siempre, con confirmación)."""

    def __init__(self, padre, almacen, al_cambiar=None):
        super().__init__(padre)
        self.title("Papelera de reportes")
        self.transient(padre)
        self.almacen = almacen
        self.al_cambiar = al_cambiar or (lambda: None)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Reportes eliminados. «Recuperar» los devuelve a la lista de Reportes.",
                  justify="left").pack(anchor="w")
        self.arbol = ttk.Treeview(f, columns=("nombre", "eliminado"), show="headings", selectmode="browse", height=10)
        self.arbol.heading("nombre", text="Reporte")
        self.arbol.heading("eliminado", text="Eliminado el")
        self.arbol.column("nombre", width=260)
        self.arbol.column("eliminado", width=140)
        self.arbol.pack(fill="both", expand=True, pady=8)
        self.arbol.bind("<Double-1>", lambda e: self.after(10, self._recuperar))
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="Recuperar", command=self._recuperar).pack(side="left", padx=(0, 6))
        ttk.Button(b, text="Borrar definitivamente…", command=self._borrar).pack(side="left")
        ttk.Button(b, text="Cerrar", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self._refrescar()
        _centrar(self, padre)

    def _refrescar(self):
        self.arbol.delete(*self.arbol.get_children())
        for r in self.almacen.papelera():
            self.arbol.insert("", "end", iid=str(r["id"]), values=(r["nombre"], (r["eliminado"] or "")[:16]))

    def _seleccionado(self):
        sel = self.arbol.selection()
        return int(sel[0]) if sel else None

    def _recuperar(self):
        rid = self._seleccionado()
        if rid is None:
            return
        try:
            nombre = self.almacen.restaurar(rid)
        except ErrorAlmacen as e:
            messagebox.showerror("Papelera", str(e), parent=self)
            return
        self._refrescar()
        self.al_cambiar()
        messagebox.showinfo("Papelera", "Recuperado: «%s»." % nombre, parent=self)

    def _borrar(self):
        rid = self._seleccionado()
        if rid is None:
            return
        nombre = self.arbol.item(str(rid), "values")[0]
        if not messagebox.askyesno("Borrar definitivamente",
                                   "¿Borrar para siempre el reporte «%s» y su historial?\nNo se podrá recuperar." % nombre,
                                   parent=self):
            return
        try:
            self.almacen.borrar_definitivo(rid)
        except ErrorAlmacen as e:
            messagebox.showerror("Papelera", str(e), parent=self)
            return
        self._refrescar()
        self.al_cambiar()


class DialogoResumen(tk.Toplevel):
    """Muestra el resumen de un lote de reportes."""

    def __init__(self, padre, titulo, texto):
        super().__init__(padre)
        self.title(titulo)
        self.transient(padre)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        t = tk.Text(f, width=90, height=min(24, max(8, texto.count("\n") + 2)), wrap="word", background="#f9fafb")
        t.insert("1.0", texto)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)
        ttk.Button(f, text="Cerrar", command=self.destroy).pack(anchor="e", pady=(8, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        _centrar(self, padre)


# ============================================================= ventana principal
class App:
    def __init__(self, root, args=None):
        self.root = root
        self.args = args or analizar_argumentos([])
        self.flujo = Flujo()
        self.reporte_id = None          # id (en la base de datos) del reporte abierto en el editor; None = sin guardar
        self._guardado = None           # copia (a_dict) de lo último guardado/abierto, para saber si hay cambios
        self._perfil_sin_guardar = None  # perfil del navegador usado por el reporte nuevo (se le pasa al guardarlo)
        self.cola = queue.Queue()
        self.hilo = None
        self.detener_evt = threading.Event()
        self.grabador = None
        self.trabajando = False
        self.carpeta_flujos = carpeta_flujos_de(self.args)
        self.almacen = abrir_almacen(self.args)
        self.marcados = set()           # ids de los reportes marcados en la lista
        self.reportes = []              # lista de reportes guardados (dicts de almacen.listar)
        self.lote_actual = None         # (n, total, nombre) mientras se ejecuta un lote
        self._peticion_acceso = None    # PeticionAcceso en curso (la página pide iniciar sesión)
        self._dialogo_acceso = None
        self._ticks = 0
        self._construir()
        self._nuevo_flujo(confirmar=False)
        self.root.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.root.after(100, self._bombear_cola)
        for m in migrar_flujos_antiguos(self.almacen, self.args) + migrar_reportes(self.almacen):
            self._log(m)
            self._estado(m[:200])
        self._refrescar_reportes()
        try:
            objetivos = objetivos_de(self.args, self.almacen)
        except SystemExit as e:
            objetivos = []
            self._log(str(e))
        ids = [o for o in objetivos if isinstance(o, int)]
        archivos = [o for o in objetivos if isinstance(o, str)]
        if ids and not self.args.todos:
            self._cargar_reporte(ids[0])
        elif archivos:
            try:
                self._cargar_archivo(archivos[0])
            except (ErrorFlujo, OSError) as e:
                self._log("No se pudo abrir %s: %s" % (archivos[0], e))
        if len(ids) > 1 or self.args.todos:
            self.marcados = set(ids)
            self._refrescar_reportes()
        if self.args.url:
            self.v_url.set(self.args.url)
        if self.args.oculto:
            self.v_ver.set(False)
        if self.args.visible:
            self.v_ver.set(True)
        if self.args.lento:
            self.v_lento.set(True)
        if self.args.navegador:
            self.v_nav.set({v: k for k, v in NAVEGADORES_GUI.items()}[self.args.navegador])
        if self.args.var:
            self.v_vars.set("; ".join(self.args.var))
        if self.args.ejecutar and (len(self.marcados) > 1 or self.args.todos):
            self.root.after(600, lambda: self._ejecutar_reportes(solo_marcados=True))
        elif self.args.ejecutar and objetivos:
            self.root.after(600, self._ejecutar)
        self._actualizar_titulo()

    # ------------------------------------------------------------ construcción
    def _construir(self):
        r = self.root
        r.title(TITULO)
        r.geometry("1320x740")
        r.minsize(1000, 600)
        estilo = ttk.Style()
        try:
            estilo.theme_use("vista")
        except tk.TclError:
            pass
        self.v_url = tk.StringVar()
        self.v_nombre = tk.StringVar(value="Nuevo reporte")
        self.v_ver = tk.BooleanVar(value=True)
        self.v_lento = tk.BooleanVar(value=False)
        self.v_recup = tk.BooleanVar(value=True)
        self.v_carga = tk.BooleanVar(value=True)
        self.v_nav = tk.StringVar(value="Chrome")
        self.v_desc = tk.StringVar()
        self.v_timeout = tk.StringVar(value="60")
        self.v_timeout_desc = tk.StringVar(value="600")
        self.v_pausa = tk.StringVar(value="0.3")
        self.v_vars = tk.StringVar()
        self.v_estado = tk.StringVar(value="Listo.")

        ttk.Label(r, textvariable=self.v_estado, relief="sunken", anchor="w", padding=(8, 2)).pack(fill="x", side="bottom")
        paned = ttk.PanedWindow(r, orient="horizontal")
        paned.pack(fill="both", expand=True)
        izq = ttk.Frame(paned)
        der = ttk.Frame(paned)
        paned.add(izq, weight=0)
        paned.add(der, weight=1)
        self._construir_reportes(izq)

        sup = ttk.Frame(der, padding=(10, 10, 10, 4))
        sup.pack(fill="x")
        sup.columnconfigure(1, weight=1)
        ttk.Label(sup, text="Dirección (URL):").grid(row=0, column=0, sticky="w")
        ttk.Entry(sup, textvariable=self.v_url).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(sup, text="Nombre del reporte:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Entry(sup, textvariable=self.v_nombre, width=26).grid(row=0, column=3, padx=6)

        bt = ttk.Frame(der, padding=(10, 2))
        bt.pack(fill="x")
        self.b_grabar = ttk.Button(bt, text="● Grabar", command=self._grabar)
        self.b_detener = ttk.Button(bt, text="■ Detener", command=self._detener, state="disabled")
        self.b_ejecutar = ttk.Button(bt, text="▶ Ejecutar", command=self._ejecutar)
        self.b_guardar = ttk.Button(bt, text="Guardar", command=self._guardar)
        self.b_guardar_como = ttk.Button(bt, text="Guardar como…", command=lambda: self._guardar(como_nuevo=True))
        self.b_nuevo = ttk.Button(bt, text="Nuevo", command=lambda: self._nuevo_flujo(confirmar=True))
        self.b_claves = ttk.Button(bt, text="🔑 Accesos", command=self._accesos)
        self.b_prog = ttk.Button(bt, text="Programar", command=self._programar)
        self.b_mas = ttk.Menubutton(bt, text="Más ▾")
        menu_mas = tk.Menu(self.b_mas, tearoff=0)
        menu_mas.add_command(label="Exportar a un archivo (.json)…", command=self._exportar)
        menu_mas.add_command(label="Importar desde un archivo (.json)…", command=self._importar)
        menu_mas.add_separator()
        menu_mas.add_command(label="Versiones anteriores del reporte…", command=self._versiones)
        menu_mas.add_command(label="Contraseñas sueltas…", command=self._contrasenas)
        menu_mas.add_command(label="Papelera de reportes…", command=self._rep_papelera)
        menu_mas.add_separator()
        menu_mas.add_command(label="Convertir listas en «Elegir opción»…", command=self._convertir_listas)
        self.b_mas["menu"] = menu_mas
        for b in (self.b_grabar, self.b_detener, self.b_ejecutar, self.b_guardar, self.b_guardar_como, self.b_nuevo):
            b.pack(side="left", padx=2)
        ttk.Separator(bt, orient="vertical").pack(side="left", fill="y", padx=8)
        for b in (self.b_claves, self.b_prog, self.b_mas):
            b.pack(side="left", padx=2)

        op = ttk.LabelFrame(der, text="Opciones", padding=8)
        op.pack(fill="x", padx=10, pady=6)
        op.columnconfigure(5, weight=1)
        ttk.Checkbutton(op, text="Ver mientras trabaja", variable=self.v_ver).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(op, text="Modo lento", variable=self.v_lento).grid(row=0, column=1, sticky="w", padx=10)
        ttk.Label(op, text="Navegador:").grid(row=0, column=2, sticky="e")
        ttk.Combobox(op, textvariable=self.v_nav, values=list(NAVEGADORES_GUI), state="readonly", width=8).grid(
            row=0, column=3, padx=6)
        ttk.Label(op, text="Tiempo máximo de espera (s):").grid(row=0, column=4, sticky="e", padx=(10, 0))
        ttk.Spinbox(op, textvariable=self.v_timeout, from_=1, to=3600, width=6).grid(row=0, column=5, sticky="w", padx=6)
        ttk.Label(op, text="Carpeta de descargas:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(op, textvariable=self.v_desc).grid(row=1, column=1, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Button(op, text="Examinar…", command=self._examinar).grid(row=1, column=5, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(op, text="Espera máxima de descargas/reportes (s):").grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Spinbox(op, textvariable=self.v_timeout_desc, from_=10, to=7200, width=6).grid(
            row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Label(op, text="Pausa entre pasos (s):").grid(row=2, column=3, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Spinbox(op, textvariable=self.v_pausa, from_=0, to=30, increment=0.1, width=6).grid(
            row=2, column=5, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(op, text="Variables (clave=valor; clave=valor):").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Entry(op, textvariable=self.v_vars).grid(row=3, column=2, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Checkbutton(op, text="Recuperación automática (si un elemento de un menú no se ve, pasar el ratón por el "
                                 "menú o volver a abrir la lista)", variable=self.v_recup).grid(
            row=4, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Checkbutton(op, text="Esperar a que la página termine de cargar (ruedas o barras de «cargando…», peticiones "
                                 "pendientes) después de cada paso", variable=self.v_carga).grid(
            row=5, column=0, columnspan=6, sticky="w", pady=(2, 0))

        cuerpo = ttk.Frame(der, padding=(10, 0))
        cuerpo.pack(fill="both", expand=True)
        cuerpo.columnconfigure(0, weight=1)
        cuerpo.rowconfigure(0, weight=3)
        cuerpo.rowconfigure(2, weight=1)
        cols = ("n", "accion", "detalle", "opc", "nota")
        self.arbol = ttk.Treeview(cuerpo, columns=cols, show="headings", selectmode="browse")
        for c, t, w, st in (("n", "Nº", 40, False), ("accion", "Acción", 170, False), ("detalle", "Detalle", 400, True),
                            ("opc", "Opc.", 40, False), ("nota", "Nota", 200, True)):
            self.arbol.heading(c, text=t)
            self.arbol.column(c, width=w, stretch=st, anchor="w")
        sb = ttk.Scrollbar(cuerpo, orient="vertical", command=self.arbol.yview)
        self.arbol.configure(yscrollcommand=sb.set)
        self.arbol.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.arbol.bind("<Double-1>", lambda e: self._editar())
        self.arbol.bind("<Delete>", lambda e: self._borrar_paso())
        self.arbol.tag_configure("actual", background="#fde68a")
        self.arbol.tag_configure("ok", background="#dcfce7")
        self.arbol.tag_configure("omitido", background="#e5e7eb")
        self.arbol.tag_configure("error", background="#fecaca")
        self.arbol.tag_configure("desactivado", background="#f3f4f6", foreground="#9ca3af")
        self.arbol.tag_configure("auto", foreground="#1d4ed8")

        lado = ttk.Frame(cuerpo)
        lado.grid(row=0, column=2, sticky="n", padx=(8, 0))
        self.botones_lista = []
        for texto, cmd in (("Subir", lambda: self._mover(-1)), ("Bajar", lambda: self._mover(1)),
                           ("Editar…", self._editar), ("Duplicar", self._duplicar),
                           ("Activar/Desactivar", self._alternar_desactivado),
                           ("Convertir en contraseña", self._convertir_contrasena), ("Borrar", self._borrar_paso)):
            b = ttk.Button(lado, text=texto, command=cmd, width=22)
            b.pack(pady=2)
            self.botones_lista.append(b)
        mb = ttk.Menubutton(lado, text="Insertar paso ▾", width=21)
        menu = tk.Menu(mb, tearoff=0)
        menu.add_command(label="Esperar a que aparezca un elemento…", command=lambda: self._insertar("esperar_elemento"))
        menu.add_command(label="Esperar a que aparezca un texto…", command=lambda: self._insertar("esperar_texto"))
        menu.add_command(label="Esperar unos segundos…", command=lambda: self._insertar("esperar_segundos"))
        menu.add_separator()
        menu.add_command(label="Pasar el ratón por encima de un elemento (abrir un menú)…",
                         command=lambda: self._insertar("pasar_raton"))
        menu.add_command(label="Guardar página (PDF, HTML o CSV)…", command=lambda: self._insertar("guardar_pagina"))
        menu.add_command(label="Elegir una opción de una lista…", command=lambda: self._insertar("elegir_opcion"))
        mb["menu"] = menu
        mb.pack(pady=(10, 2))
        self.menu_espera = mb

        ttk.Label(cuerpo, text="Registro:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.txt_log = tk.Text(cuerpo, height=7, state="disabled", wrap="word", background="#f9fafb")
        self.txt_log.grid(row=2, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(cuerpo, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb2.set)
        sb2.grid(row=2, column=1, sticky="ns")

    def _construir_reportes(self, padre):
        """Panel «Reportes»: los reportes guardados en la aplicación, con casilla, última ejecución y resultado."""
        marco = ttk.LabelFrame(padre, text="Reportes", padding=6)
        marco.pack(fill="both", expand=True, padx=(8, 0), pady=(8, 6))
        barra = ttk.Frame(marco)
        barra.pack(fill="x")
        self.botones_rep = []
        for texto, cmd in (("Nuevo", self._rep_nuevo), ("Abrir", self._rep_abrir), ("Renombrar", self._rep_renombrar),
                           ("Duplicar", self._rep_duplicar), ("Eliminar", self._rep_eliminar)):
            b = ttk.Button(barra, text=texto, command=cmd, width=9)
            b.pack(side="left", padx=1, pady=(0, 4))
            self.botones_rep.append(b)
        cols = ("sel", "nombre", "url", "ultima", "resultado")
        cont = ttk.Frame(marco)
        cont.pack(side="top", fill="both", expand=True)
        cont.columnconfigure(0, weight=1)
        cont.rowconfigure(0, weight=1)
        self.arbol_rep = ttk.Treeview(cont, columns=cols, show="headings", selectmode="browse", height=14)
        for c, t, w, st in (("sel", "", 26, False), ("nombre", "Reporte", 130, True), ("url", "Página", 120, True),
                            ("ultima", "Última vez", 105, False), ("resultado", "Resultado", 62, False)):
            self.arbol_rep.heading(c, text=t)
            self.arbol_rep.column(c, width=w, stretch=st, anchor="w")
        sbr = ttk.Scrollbar(cont, orient="vertical", command=self.arbol_rep.yview)
        self.arbol_rep.configure(yscrollcommand=sbr.set)
        self.arbol_rep.grid(row=0, column=0, sticky="nsew")
        sbr.grid(row=0, column=1, sticky="ns")
        self.arbol_rep.tag_configure("ok", foreground="#166534")
        self.arbol_rep.tag_configure("error", foreground="#b91c1c")
        self.arbol_rep.tag_configure("abierto", font=("Segoe UI", 9, "bold"))
        self.arbol_rep.bind("<Button-1>", self._clic_reportes)
        self.arbol_rep.bind("<Double-1>", lambda e: self.root.after(10, self._rep_abrir))
        self.v_rep_info = tk.StringVar(value="")
        ttk.Label(marco, textvariable=self.v_rep_info, foreground="#555555", wraplength=380, justify="left").pack(
            fill="x", pady=(4, 2))
        abajo = ttk.Frame(marco)
        abajo.pack(fill="x")
        self.b_rep_sel = ttk.Button(abajo, text="Ejecutar seleccionados", command=lambda: self._ejecutar_reportes(True))
        self.b_rep_todos = ttk.Button(abajo, text="Ejecutar todos", command=lambda: self._ejecutar_reportes(False))
        self.b_rep_prog = ttk.Button(abajo, text="Programar…", command=lambda: self._programar(desde_panel=True))
        for b in (self.b_rep_sel, self.b_rep_todos, self.b_rep_prog):
            b.pack(side="left", padx=1)
            self.botones_rep.append(b)
        abajo2 = ttk.Frame(marco)
        abajo2.pack(fill="x", pady=(4, 0))
        self.b_rep_papelera = ttk.Button(abajo2, text="Papelera…", command=self._rep_papelera)
        self.b_rep_papelera.pack(side="left", padx=1)
        self.botones_rep.append(self.b_rep_papelera)
        ttk.Label(marco, text="Doble clic en un reporte para abrirlo.  Marca la casilla ☐ de cada reporte para "
                              "ejecutarlos juntos; cada uno usa sus propias opciones guardadas.", foreground="#555555",
                  wraplength=380, justify="left").pack(fill="x", pady=(4, 0))

    # ------------------------------------------------------------ utilidades
    def _log(self, texto):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", texto + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _estado(self, texto):
        self.v_estado.set(texto)

    @staticmethod
    def _normalizar_url(txt):
        txt = (txt or "").strip()
        if not txt:
            return ""
        if "://" not in txt:
            local = txt.startswith(("localhost", "127.0.0.1", "[::1]"))
            txt = ("http://" if local else "https://") + txt
        return txt

    def _variables_form(self):
        res = {}
        for trozo in self.v_vars.get().split(";"):
            if "=" in trozo:
                k, v = trozo.split("=", 1)
                if k.strip():
                    res[k.strip()] = v.strip()
        return res

    def _formulario_a_flujo(self):
        f = self.flujo
        f.nombre = self.v_nombre.get().strip() or "Reporte"
        f.url = self._normalizar_url(self.v_url.get())
        f.opciones["navegador"] = NAVEGADORES_GUI.get(self.v_nav.get(), "chrome")
        f.opciones["carpeta_descargas"] = self.v_desc.get().strip()
        f.opciones["recuperacion_automatica"] = bool(self.v_recup.get())
        f.opciones["esperar_carga"] = bool(self.v_carga.get())
        for clave, var, defecto, minimo in (("timeout_paso", self.v_timeout, 60, 1),
                                            ("timeout_descarga", self.v_timeout_desc, 600, 1),
                                            ("pausa_entre_pasos", self.v_pausa, 0.3, 0)):
            try:
                f.opciones[clave] = max(minimo, float(var.get().replace(",", ".")))
            except ValueError:
                f.opciones[clave] = defecto
        f.variables = self._variables_form()

    def _flujo_a_formulario(self):
        f = self.flujo
        self.v_nombre.set(f.nombre)
        self.v_url.set(f.url)
        self.v_nav.set({v: k for k, v in NAVEGADORES_GUI.items()}.get(f.opcion("navegador"), "Chrome"))
        self.v_desc.set(f.opcion("carpeta_descargas") or "")
        self.v_timeout.set("%g" % f.opcion("timeout_paso"))
        self.v_timeout_desc.set("%g" % f.opcion("timeout_descarga"))
        self.v_pausa.set("%g" % f.opcion("pausa_entre_pasos"))
        self.v_recup.set(f.opcion("recuperacion_automatica") is not False)
        self.v_carga.set(f.opcion("esperar_carga") is not False)
        self.v_vars.set("; ".join("%s=%s" % kv for kv in f.variables.items()))
        self._refrescar_lista()

    def _fila(self, i, p):
        accion = p.accion() + (" (desactivado)" if p.desactivado else "")
        return (i + 1, accion, p.detalle(), "sí" if p.opcional else "", p.nota)

    def _tags_paso(self, i):
        if not (0 <= i < len(self.flujo.pasos)):
            return ()
        p = self.flujo.pasos[i]
        if p.desactivado:
            return ("desactivado",)
        return ("auto",) if p.tipo == "pasar_raton" and p.auto else ()

    def _refrescar_lista(self, seleccion=None):
        self.arbol.delete(*self.arbol.get_children())
        for i, p in enumerate(self.flujo.pasos):
            self.arbol.insert("", "end", iid=str(i), values=self._fila(i, p), tags=self._tags_paso(i))
        if seleccion is not None and 0 <= seleccion < len(self.flujo.pasos):
            self.arbol.selection_set(str(seleccion))
            self.arbol.see(str(seleccion))

    def _indice_seleccionado(self):
        sel = self.arbol.selection()
        return int(sel[0]) if sel else None

    def _poner_ocupado(self, ocupado, grabando=False):
        self.trabajando = ocupado
        estado = "disabled" if ocupado else "normal"
        for b in (self.b_grabar, self.b_ejecutar, self.b_guardar, self.b_guardar_como, self.b_nuevo, self.b_prog,
                  self.b_mas, *self.botones_lista, *self.botones_rep):
            b.configure(state=estado)
        self.menu_espera.configure(state=estado)
        self.b_detener.configure(state="normal" if ocupado else "disabled")

    # ------------------------------------------------------------ cambios sin guardar
    def _marcar_guardado(self):
        """Lo que hay ahora en el editor es lo guardado (se compara después para saber si hay cambios)."""
        self._formulario_a_flujo()
        self._guardado = self.flujo.a_dict() if self.reporte_id is not None else None
        self._actualizar_titulo()

    def _hay_cambios_sin_guardar(self):
        self._formulario_a_flujo()
        if self._guardado is None:
            return bool(self.flujo.pasos)
        return self.flujo.a_dict() != self._guardado

    def _actualizar_titulo(self):
        if self.trabajando:
            return
        try:
            sucio = self._hay_cambios_sin_guardar()
        except tk.TclError:
            return
        nombre = self.v_nombre.get().strip() or "Reporte"
        if self.reporte_id is None and not sucio:
            self.root.title(TITULO)
        else:
            self.root.title("%s%s — %s" % (nombre, "*" if sucio else "", TITULO))

    def _confirmar_descartar(self, accion="continuar"):
        """Si hay cambios sin guardar, pregunta si guardarlos.  True = se puede seguir."""
        if self.trabajando or not self._hay_cambios_sin_guardar():
            return True
        r = messagebox.askyesnocancel(
            "Cambios sin guardar", "El reporte «%s» tiene cambios sin guardar.\n\n¿Guardarlos antes de %s?\n"
                                   "(Sí = guardar, No = descartar los cambios, Cancelar = volver)"
            % (self.flujo.nombre, accion), parent=self.root)
        if r is None:
            return False
        if r:
            return self._guardar()
        return True

    # ------------------------------------------------------------ panel «Reportes»
    def _refrescar_reportes(self):
        self.reportes = self.almacen.listar()
        existentes = {r["id"] for r in self.reportes}
        self.marcados &= existentes
        sel_previa = self.arbol_rep.selection()
        self.arbol_rep.delete(*self.arbol_rep.get_children())
        for r in self.reportes:
            ultima = (r.get("ultima") or "—")[:16]
            etiqueta = lote.texto_resultado({"resultado": r["resultado"]} if r.get("resultado") else None)
            tags = []
            tag = {"ok": "ok", "error": "error", "detenido": "error"}.get(r.get("resultado"), "")
            if tag:
                tags.append(tag)
            if r["id"] == self.reporte_id:
                tags.append("abierto")
            self.arbol_rep.insert("", "end", iid=str(r["id"]), tags=tuple(tags), values=(
                "☑" if r["id"] in self.marcados else "☐", r["nombre"], r["url"] or "", ultima, etiqueta))
        for iid in sel_previa:
            if self.arbol_rep.exists(iid):
                self.arbol_rep.selection_set(iid)
        self._info_reportes()

    def _info_reportes(self):
        n = len(self.reportes)
        m = len(self.marcados)
        self.v_rep_info.set("%d reporte%s guardado%s, %d marcado%s." % (
            n, "" if n == 1 else "s", "" if n == 1 else "s", m, "" if m == 1 else "s"))

    def _clic_reportes(self, evento):
        if self.arbol_rep.identify_region(evento.x, evento.y) != "cell":
            return
        if self.arbol_rep.identify_column(evento.x) != "#1":
            return
        iid = self.arbol_rep.identify_row(evento.y)
        if not iid:
            return
        rid = int(iid)
        if rid in self.marcados:
            self.marcados.discard(rid)
        else:
            self.marcados.add(rid)
        self.arbol_rep.set(iid, "sel", "☑" if rid in self.marcados else "☐")
        self._info_reportes()

    def _reporte_seleccionado(self):
        sel = self.arbol_rep.selection()
        return int(sel[0]) if sel else None

    def _nombre_de(self, rid):
        return next((r["nombre"] for r in self.reportes if r["id"] == rid), str(rid))

    def _rep_nuevo(self):
        if self.trabajando:
            return
        self._nuevo_flujo(confirmar=True)

    def _rep_abrir(self):
        rid = self._reporte_seleccionado()
        if rid is None or self.trabajando:
            if rid is None:
                messagebox.showinfo("Reportes", "Elige un reporte de la lista.", parent=self.root)
            return
        if rid != self.reporte_id and not self._confirmar_descartar("abrir «%s»" % self._nombre_de(rid)):
            return
        try:
            self._cargar_reporte(rid)
        except ErrorAlmacen as e:
            messagebox.showerror("Abrir", "No se pudo abrir el reporte:\n%s" % e, parent=self.root)

    def _rep_renombrar(self):
        rid = self._reporte_seleccionado()
        if rid is None or self.trabajando:
            return
        actual = self._nombre_de(rid)
        nombre = self._pedir_nombre("Renombrar", "Nuevo nombre para «%s»:" % actual, actual, excluir_id=rid)
        if nombre is None or nombre == actual:
            return
        try:
            self.almacen.renombrar(rid, nombre)
        except ErrorAlmacen as e:
            messagebox.showerror("Renombrar", str(e), parent=self.root)
            return
        if rid == self.reporte_id:            # el abierto en el editor: cambia el nombre sin marcarlo como modificado
            self.v_nombre.set(nombre)
            self.flujo.nombre = nombre
            if self._guardado is not None:
                self._guardado["nombre"] = nombre
        self._refrescar_reportes()
        self._actualizar_titulo()
        self._estado("Renombrado: «%s» → «%s» (conserva su historial y su sesión del navegador)." % (actual, nombre))

    def _rep_duplicar(self):
        rid = self._reporte_seleccionado()
        if rid is None or self.trabajando:
            return
        try:
            nuevo = self.almacen.duplicar(rid)
        except ErrorAlmacen as e:
            messagebox.showerror("Duplicar", "No se pudo duplicar:\n%s" % e, parent=self.root)
            return
        self._refrescar_reportes()
        if self.arbol_rep.exists(str(nuevo)):
            self.arbol_rep.selection_set(str(nuevo))
        self._estado("Duplicado: «%s» (la copia empieza sin la sesión iniciada del original)." % self._nombre_de(nuevo))

    def _rep_eliminar(self):
        rid = self._reporte_seleccionado()
        if rid is None or self.trabajando:
            return
        nombre = self._nombre_de(rid)
        if not messagebox.askyesno(
                "Eliminar", "¿Eliminar el reporte «%s»?\n\nVa a la papelera: puedes recuperarlo con «Papelera…»." % nombre,
                parent=self.root):
            return
        try:
            self.almacen.eliminar(rid)
        except ErrorAlmacen as e:
            messagebox.showerror("Eliminar", "No se pudo eliminar:\n%s" % e, parent=self.root)
            return
        if rid == self.reporte_id:
            self.reporte_id = None      # el editor conserva su copia, pero ya no está guardada
            self._guardado = None
        self.marcados.discard(rid)
        self._refrescar_reportes()
        self._actualizar_titulo()
        self._estado("Eliminado: «%s» (está en la papelera)." % nombre)

    def _rep_papelera(self):
        if self.trabajando:
            return
        dlg = DialogoPapelera(self.root, self.almacen, al_cambiar=self._refrescar_reportes)
        dlg.grab_set()
        self.root.wait_window(dlg)

    def _ejecutar_reportes(self, solo_marcados):
        if self.trabajando:
            return
        if solo_marcados:
            ids = [r["id"] for r in self.reportes if r["id"] in self.marcados]
            if not ids:
                messagebox.showinfo("Ejecutar seleccionados", "Marca con ☐ al menos un reporte de la lista.", parent=self.root)
                return
        else:
            ids = [r["id"] for r in self.reportes]
            if not ids:
                messagebox.showinfo("Ejecutar todos", "No hay reportes guardados.", parent=self.root)
                return
        self._ejecutar_lote(ids)

    # ------------------------------------------------------------ gestión de reportes
    def _nuevo_flujo(self, confirmar=True):
        if confirmar and not self._confirmar_descartar("empezar uno nuevo"):
            return
        self.flujo = Flujo(nombre="Nuevo reporte")
        self.reporte_id = None
        self._guardado = None
        self._perfil_sin_guardar = None
        self._flujo_a_formulario()
        self._refrescar_marca_abierto()
        self._actualizar_titulo()
        self._estado("Reporte nuevo. Escribe la dirección y pulsa Grabar.")

    def _cargar_reporte(self, rid):
        self.flujo = self.almacen.cargar_flujo(rid)
        self.reporte_id = rid
        self._perfil_sin_guardar = None
        self._flujo_a_formulario()
        self._marcar_guardado()
        self._refrescar_marca_abierto()
        if self.arbol_rep.exists(str(rid)):
            self.arbol_rep.selection_set(str(rid))
            self.arbol_rep.see(str(rid))
        self._estado("Abierto: «%s»" % self.flujo.nombre)

    def _cargar_archivo(self, ruta):
        """Abre un archivo .json en el editor como reporte nuevo (sin guardar todavía en la aplicación)."""
        self.flujo = Flujo.cargar(ruta)
        for m in migrar_flujo(self.flujo):          # formato antiguo: se actualiza en memoria (el archivo no cambia)
            self._log("Archivo %s: %s" % (os.path.basename(ruta), m))
        self.reporte_id = None
        self._guardado = None
        self._perfil_sin_guardar = None
        self._flujo_a_formulario()
        self._refrescar_marca_abierto()
        self._actualizar_titulo()
        self._estado("Abierto el archivo %s (pulsa Guardar para guardarlo en la aplicación)." % ruta)

    def _refrescar_marca_abierto(self):
        for iid in self.arbol_rep.get_children():
            tags = [t for t in self.arbol_rep.item(iid, "tags") if t != "abierto"]
            if self.reporte_id is not None and iid == str(self.reporte_id):
                tags.append("abierto")
            self.arbol_rep.item(iid, tags=tuple(tags))

    def _pedir_nombre(self, titulo, mensaje, inicial, excluir_id=None):
        """Pide un nombre de reporte válido y libre.  None si se cancela."""
        nombre = inicial
        while True:
            nombre = simpledialog.askstring(titulo, mensaje, initialvalue=nombre, parent=self.root)
            if nombre is None:
                return None
            try:
                nombre = mod_almacen.validar_nombre(nombre)
            except ErrorAlmacen as e:
                messagebox.showerror(titulo, str(e), parent=self.root)
                continue
            if self.almacen.existe_nombre(nombre, excluir_id=excluir_id):
                messagebox.showerror(titulo, "Ya existe un reporte llamado «%s». Elige otro nombre." % nombre,
                                     parent=self.root)
                continue
            return nombre

    def _guardar(self, como_nuevo=False, nombre=None):
        """Guarda el reporte del editor en la aplicación.  «Guardar» actualiza el reporte abierto (si es nuevo,
        pide el nombre); «Guardar como…» siempre pide un nombre y crea otro reporte.  True si se guardó."""
        if self.trabajando:
            return False
        self._formulario_a_flujo()
        destino = None if como_nuevo else self.reporte_id
        if nombre is None and destino is None:
            inicial = self.flujo.nombre
            if como_nuevo and self.reporte_id is not None:
                inicial = self.almacen.nombre_libre(self.flujo.nombre)
            nombre = self._pedir_nombre("Guardar como" if como_nuevo else "Guardar reporte",
                                        "Nombre del reporte (se guarda en la aplicación):", inicial)
            if nombre is None:
                return False
        if nombre is not None:
            self.flujo.nombre = nombre
            self.v_nombre.set(nombre)
        try:
            rid = self.almacen.guardar(self.flujo, destino)
        except (ErrorAlmacen, sqlite3.Error) as e:
            messagebox.showerror("Guardar", "No se pudo guardar:\n%s" % e, parent=self.root)
            return False
        if destino is None:
            self._pasar_perfil(rid)
        self.reporte_id = rid
        self.v_nombre.set(self.flujo.nombre)
        self._marcar_guardado()
        self._refrescar_reportes()
        if self.arbol_rep.exists(str(rid)):
            self.arbol_rep.selection_set(str(rid))
            self.arbol_rep.see(str(rid))
        self._estado("Guardado en la aplicación: «%s»." % self.flujo.nombre)
        return True

    def _pasar_perfil(self, rid):
        """El perfil del navegador usado al grabar/probar el reporte nuevo pasa a ser el suyo (perfiles/reporte_<id>),
        para no perder la sesión iniciada."""
        origen = self._perfil_sin_guardar
        self._perfil_sin_guardar = None
        if not origen or self.args.perfil or not os.path.isdir(origen):
            return
        destino = carpeta_perfil_de(self.flujo, None, rid)
        if os.path.exists(destino):
            return
        try:
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            os.rename(origen, destino)
        except OSError:
            pass

    def _exportar(self):
        if self.trabajando:
            return
        self._formulario_a_flujo()
        if not self.flujo.pasos:
            messagebox.showinfo("Exportar", "No hay pasos que exportar. Abre o graba un reporte.", parent=self.root)
            return
        ruta = filedialog.asksaveasfilename(
            parent=self.root, title="Exportar reporte a un archivo", initialfile=slug(self.flujo.nombre) + ".json",
            defaultextension=".json", filetypes=[("Reporte (JSON)", "*.json")])
        if not ruta:
            return
        try:
            self.flujo.guardar(ruta)
        except OSError as e:
            messagebox.showerror("Exportar", "No se pudo exportar:\n%s" % e, parent=self.root)
            return
        self._estado("Exportado a %s (copia de seguridad; el reporte sigue guardado en la aplicación)." % ruta)

    def _importar(self, ruta=None):
        if self.trabajando:
            return
        if ruta is None:
            ruta = filedialog.askopenfilename(parent=self.root, title="Importar un reporte desde un archivo",
                                              filetypes=[("Reporte (JSON)", "*.json"), ("Todos", "*.*")])
        if not ruta:
            return
        if not self._confirmar_descartar("abrir el reporte importado"):
            return
        try:
            rid = self.almacen.importar_archivo(ruta)
        except ErrorAlmacen as e:
            messagebox.showerror("Importar", str(e), parent=self.root)
            return
        self._refrescar_reportes()
        self._cargar_reporte(rid)
        self._estado("Importado como «%s»." % self.flujo.nombre)

    def _examinar(self):
        c = filedialog.askdirectory(parent=self.root, title="Carpeta de descargas")
        if c:
            self.v_desc.set(os.path.normpath(c))

    # ------------------------------------------------------------ edición de pasos
    def _mover(self, delta):
        i = self._indice_seleccionado()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(self.flujo.pasos):
            p = self.flujo.pasos
            p[i], p[j] = p[j], p[i]
            self._refrescar_lista(j)

    def _editar(self):
        i = self._indice_seleccionado()
        if i is None or self.trabajando:
            return
        self._formulario_a_flujo()
        dlg = DialogoPaso(self.root, self.flujo.pasos[i], self.flujo.variables, self.flujo.opciones)
        dlg.grab_set()
        self.root.wait_window(dlg)
        self._refrescar_lista(i)

    def _duplicar(self):
        i = self._indice_seleccionado()
        if i is not None:
            self.flujo.pasos.insert(i + 1, self.flujo.pasos[i].copia())
            self._refrescar_lista(i + 1)

    def _alternar_desactivado(self):
        i = self._indice_seleccionado()
        if i is None or self.trabajando:
            return
        paso = self.flujo.pasos[i]
        paso.desactivado = not paso.desactivado
        self._refrescar_lista(i)
        self._estado("Paso %d %s." % (i + 1, "desactivado: no se ejecutará" if paso.desactivado else "activado"))

    def _convertir_contrasena(self):
        """Mueve el texto escrito en claro de un paso «Escribir» al almacén de contraseñas."""
        i = self._indice_seleccionado()
        if i is None or self.trabajando:
            return
        paso = self.flujo.pasos[i]
        if paso.tipo != "escribir":
            messagebox.showinfo("Convertir en contraseña", "Elige un paso «Escribir».", parent=self.root)
            return
        if paso.es_secreto():
            messagebox.showinfo("Convertir en contraseña", "Este paso ya usa una contraseña guardada.", parent=self.root)
            return
        self._formulario_a_flujo()
        nombre = simpledialog.askstring(
            "Convertir en contraseña",
            "El texto de este paso se guardará en el Administrador de credenciales de Windows y el paso quedará\n"
            "como {secreto:nombre}.  Nombre de la contraseña:", initialvalue=nombre_secreto_sugerido(paso, self.flujo.url),
            parent=self.root)
        if not nombre:
            return
        try:
            convertir_en_secreto(paso, nombre, secretos.guardar)
        except (ErrorFlujo, secretos.ErrorSecreto) as e:
            messagebox.showerror("Convertir en contraseña", str(e), parent=self.root)
            return
        self._refrescar_lista(i)
        self._estado("Paso %d convertido: ahora usa {secreto:%s}. Pulsa Guardar para quitar la contraseña del reporte." % (
            i + 1, nombre.strip()))
        messagebox.showinfo(
            "Convertir en contraseña",
            "Listo. Pulsa «Guardar» para que el reporte guardado ya no contenga la contraseña.\n\n"
            "Si lo habías exportado a un archivo o ejecutado con la contraseña en claro, ese archivo y los "
            "registros de la carpeta «registros» pueden conservarla: bórralos si lo necesitas, y cambia la "
            "contraseña en la web si estuvo expuesta.", parent=self.root)

    def _borrar_paso(self):
        i = self._indice_seleccionado()
        if i is None or self.trabajando:
            return
        if messagebox.askyesno("Borrar", "¿Borrar el paso %d (%s)?" % (i + 1, self.flujo.pasos[i].accion()),
                               parent=self.root):
            del self.flujo.pasos[i]
            self._refrescar_lista(min(i, len(self.flujo.pasos) - 1))

    def _insertar(self, tipo):
        i = self._indice_seleccionado()
        posicion = len(self.flujo.pasos) if i is None else i + 1
        paso = Paso(tipo)
        if tipo == "esperar_segundos":
            paso.segundos = 5
        if tipo == "guardar_pagina":
            paso.formato = "pdf"
            paso.nombre = "Pagina_{hoy:%Y-%m-%d}"
        if tipo in ("guardar_pagina", "pasar_raton") and self.flujo.pasos and i is not None:
            paso.pagina = self.flujo.pasos[i].pagina       # la misma pestaña que el paso elegido
        self._formulario_a_flujo()
        dlg = DialogoPaso(self.root, paso, self.flujo.variables, self.flujo.opciones)
        dlg.grab_set()
        self.root.wait_window(dlg)
        if dlg.aceptado:
            self.flujo.pasos.insert(posicion, paso)
            self._refrescar_lista(posicion)

    def _convertir_listas(self):
        """Convierte (si el usuario lo confirma) los pares «abrir lista + clic en opción» en pasos «Elegir opción»."""
        from webbot.flujo import convertir_listas, pares_lista_opcion
        if self.trabajando:
            return
        self._formulario_a_flujo()
        pares = pares_lista_opcion(self.flujo.pasos)
        if not pares:
            messagebox.showinfo("Elegir opción", "No hay pares «abrir la lista + clic en una opción» que convertir.",
                                parent=self.root)
            return
        texto = "\n".join("• pasos %d y %d: «%s»" % (i + 1, j + 1, t[:60]) for i, j, t in pares)
        if not messagebox.askyesno("Elegir opción", "Se convertirán en pasos «Elegir opción» (con la opción fija; luego "
                                   "puedes cambiarla a «la más reciente» editando el paso):\n\n%s\n\n¿Continuar?" % texto,
                                   parent=self.root):
            return
        mensajes = convertir_listas(self.flujo)
        self._refrescar_lista()
        self._log("Listas convertidas: " + "; ".join(mensajes))
        self._estado("%d listas convertidas en «Elegir opción». Pulsa Guardar para conservar el cambio." % len(mensajes))

    # ------------------------------------------------------------ diálogos auxiliares
    def _contrasenas(self):
        dlg = DialogoContrasenas(self.root)
        dlg.grab_set()
        self.root.wait_window(dlg)

    def _accesos(self):
        dlg = DialogoAccesos(self.root, self.almacen)
        dlg.grab_set()
        self.root.wait_window(dlg)

    def _versiones(self):
        """Copias anteriores del reporte abierto (o del elegido en el panel), p. ej. la de antes de la v2.3."""
        if self.trabajando:
            return
        rid = self.reporte_id if self.reporte_id is not None else self._reporte_seleccionado()
        if rid is None:
            messagebox.showinfo("Versiones anteriores", "Abre o elige un reporte guardado.", parent=self.root)
            return
        if not self.almacen.versiones(rid):
            messagebox.showinfo("Versiones anteriores", "Este reporte no tiene copias anteriores.", parent=self.root)
            return

        def restaurado(r):
            self._refrescar_reportes()
            if r == self.reporte_id:
                self._cargar_reporte(r)
            self._estado("Reporte restaurado a la copia elegida (la versión anterior también se guardó como copia).")

        dlg = DialogoVersiones(self.root, self.almacen, rid, self._nombre_de(rid), al_restaurar=restaurado)
        dlg.grab_set()
        self.root.wait_window(dlg)

    # ------------------------------------------------------------ «la página pide iniciar sesión»
    def _pedir_acceso(self, solicitud, esperar):
        """Lo llama el hilo de trabajo: pasa la pregunta a la ventana (cola) y espera la respuesta sin tocar Tk."""
        peticion = PeticionAcceso(solicitud)
        self.cola.put(("acceso", peticion))
        try:
            esperar(peticion.evento)
        except BaseException:
            peticion.cancelar()
            raise
        return peticion.respuesta

    def _abrir_dialogo_acceso(self, solicitud):
        """Muestra el cuadro «La página pide iniciar sesión» y devuelve la respuesta (None = Cancelar)."""
        dlg = DialogoAcceso(self.root, solicitud)
        self._dialogo_acceso = dlg
        try:                    # sin grab_set: el botón «Detener» de la ventana sigue funcionando
            dlg.lift()
            dlg.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.wait_window(dlg)
        self._dialogo_acceso = None
        return dlg.respuesta

    def _atender_acceso(self, peticion):
        """Hilo principal: contesta una PeticionAcceso del hilo de trabajo."""
        if peticion.cancelada or peticion.evento.is_set():
            return
        self._peticion_acceso = peticion
        host = peticion.solicitud.get("host") or "la página"
        self._estado("La página «%s» pide iniciar sesión: escribe los datos." % host)
        try:
            respuesta = self._abrir_dialogo_acceso(peticion.solicitud)
        finally:
            self._peticion_acceso = None
        peticion.responder(respuesta)
        self._estado("Datos de acceso enviados; sigue la ejecución…" if respuesta else "Inicio de sesión cancelado.")

    def _programar(self, desde_panel=False):
        marcados = [r["id"] for r in self.reportes if r["id"] in self.marcados]
        if desde_panel:
            if not self.reportes:
                messagebox.showinfo("Programar", "No hay reportes guardados.", parent=self.root)
                return
            rid = self._reporte_seleccionado()
            if rid is None:
                rid = self.reporte_id
            dlg = DialogoProgramar(self.root, rid, self._nombre_de(rid) if rid is not None else "", self._variables_form(),
                                   seleccionados=marcados, n_todos=len(self.reportes),
                                   modo=None if rid is not None else ("seleccion" if marcados else "todos"),
                                   db=self.almacen.ruta)
            if marcados and self._reporte_seleccionado() is None:
                dlg.v_modo.set("seleccion")
            dlg.grab_set()
            self.root.wait_window(dlg)
            return
        self._formulario_a_flujo()
        if not self.flujo.pasos:
            messagebox.showinfo("Programar", "Primero graba o abre un reporte.", parent=self.root)
            return
        if self.reporte_id is None or self._hay_cambios_sin_guardar():
            if not messagebox.askyesno("Programar", "Para programar, el reporte se guarda primero. ¿Guardarlo ahora?",
                                       parent=self.root):
                return
            if not self._guardar():
                return
        dlg = DialogoProgramar(self.root, self.reporte_id, self.flujo.nombre, self._variables_form(),
                               seleccionados=marcados, n_todos=len(self.reportes), modo="este", db=self.almacen.ruta)
        dlg.grab_set()
        self.root.wait_window(dlg)

    def _perfil_para(self, flujo):
        """Perfil del navegador del reporte del editor (por id si está guardado)."""
        perfil = carpeta_perfil_de(flujo, self.args, self.reporte_id)
        if self.reporte_id is None and not self.args.perfil:
            self._perfil_sin_guardar = perfil
        return perfil

    # ------------------------------------------------------------ grabar
    def _grabar(self):
        self._formulario_a_flujo()
        if not self.flujo.url:
            messagebox.showinfo("Grabar", "Escribe primero la dirección (URL) de la página.", parent=self.root)
            return
        if self.flujo.pasos and not messagebox.askyesno(
                "Grabar", "Al grabar se reemplazan los pasos actuales. ¿Continuar?", parent=self.root):
            return
        self.v_url.set(self.flujo.url)
        self.flujo.pasos = []
        self._refrescar_lista()
        self.detener_evt.clear()
        from webbot.grabador_web import GrabadorWeb
        flujo = self.flujo
        grabador = GrabadorWeb(
            flujo, self._perfil_para(flujo), navegador=flujo.opcion("navegador"), oculto=False,
            al_evento=lambda tipo, **datos: self.cola.put(("grab", tipo, datos)), accesos=self.almacen)
        self.grabador = grabador

        def trabajo():
            try:
                grabador.grabar(flujo.url)
            except Exception as e:
                self.cola.put(("error", "No se pudo grabar: %s" % (str(e).splitlines()[0] if str(e) else type(e).__name__)))
                self.cola.put(("grab", "fin", {"pasos": len(flujo.pasos)}))

        self._poner_ocupado(True, grabando=True)
        self._estado("Grabando… se abrirá el navegador.")
        self._log("--- Grabación iniciada (%s) ---" % flujo.url)
        self.hilo = threading.Thread(target=trabajo, name="grabador", daemon=True)
        self.hilo.start()

    def _evento_grabacion(self, tipo, datos):
        if tipo == "paso":
            i = datos["indice"]
            self.arbol.insert("", "end", iid=str(i), values=self._fila(i, datos["paso"]), tags=self._tags_paso(i))
            self.arbol.see(str(i))
        elif tipo == "paso_actualizado":
            i = datos["indice"]
            if self.arbol.exists(str(i)):
                self.arbol.item(str(i), values=self._fila(i, datos["paso"]), tags=self._tags_paso(i))
        elif tipo == "sugerencia":
            paso = datos["paso"]
            if messagebox.askyesno(
                    "Fecha dinámica",
                    "Escribiste la fecha «%s», que coincide con una fecha relativa (hoy, ayer, inicio o fin de mes…).\n\n"
                    "¿Quieres que el bot calcule siempre esa fecha el día en que se ejecute?\n"
                    "Se guardará como %s." % (datos["original"], datos["plantilla"]), parent=self.root):
                paso.valor = datos["plantilla"]
                i = datos["indice"]
                if self.arbol.exists(str(i)):
                    self.arbol.item(str(i), values=self._fila(i, paso))
        elif tipo == "estado":
            self._estado(datos.get("texto", ""))
            self._log(datos.get("texto", ""))
        elif tipo == "fin":
            self._poner_ocupado(False)
            self.grabador = None
            self._refrescar_lista()
            n = len(self.flujo.pasos)
            self._estado("Grabación terminada: %d pasos." % n)
            self._log("--- Grabación terminada (%d pasos) ---" % n)
            if n > 1:
                self.root.after(50, self._ofrecer_guardar_grabacion)

    def _ofrecer_guardar_grabacion(self):
        """Al terminar de grabar se pide el nombre para guardar el reporte en la aplicación."""
        if self.trabajando:
            return
        self._formulario_a_flujo()
        n = len(self.flujo.pasos)
        nombre = self._pedir_nombre(
            "Guardar la grabación",
            "Grabación terminada (%d pasos). ¿Con qué nombre la guardas en la aplicación?\n"
            "(Cancelar = no guardar ahora; puedes pulsar «Guardar» más tarde.)" % n,
            self.flujo.nombre, excluir_id=self.reporte_id)
        if nombre is None:
            self._estado("Grabación terminada: %d pasos sin guardar. Revísalos y pulsa Guardar." % n)
            self._actualizar_titulo()
            return
        actual = self.almacen.obtener(self.reporte_id) if self.reporte_id is not None else None
        if actual is not None and actual["nombre"].lower() == nombre.lower():
            self._guardar(nombre=nombre)                     # se regrabó el reporte abierto
        else:
            self._guardar(como_nuevo=True, nombre=nombre)

    # ------------------------------------------------------------ ejecutar
    def _ejecutar(self):
        if self.trabajando:
            return
        self._formulario_a_flujo()
        if not self.flujo.pasos:
            messagebox.showinfo("Ejecutar", "No hay pasos. Graba o abre un reporte.", parent=self.root)
            return
        problemas = self.flujo.problemas()
        if problemas:
            messagebox.showerror("Ejecutar", "El flujo tiene errores:\n\n" + "\n".join(problemas[:8]), parent=self.root)
            return
        flujo = self.flujo.copia()
        variables = self._variables_form()
        faltan = [v for v in flujo.variables_necesarias() if v not in variables]
        if faltan:
            messagebox.showerror("Ejecutar", "Faltan variables: %s\nEscríbelas en «Variables» (clave=valor)." % ", ".join(faltan),
                                 parent=self.root)
            return
        from webbot.ejecutor import Ejecutor
        self.detener_evt.clear()
        for iid in self.arbol.get_children():
            self.arbol.item(iid, tags=self._tags_paso(int(iid)))
        ejecutor = Ejecutor(
            flujo, carpeta_perfil=self._perfil_para(flujo),
            carpeta_registros=os.path.abspath(self.args.registros) if self.args.registros else carpeta("registros"),
            carpeta_descargas=os.path.abspath(self.args.descargas) if self.args.descargas else None,
            oculto=not self.v_ver.get(), lento=self.v_lento.get(), variables=variables,
            progreso=lambda i, estado, texto="": self.cola.put(("ejec", "progreso", (i, estado, texto))),
            log=lambda linea: self.cola.put(("log", linea)), detener=self.detener_evt,
            pedir_acceso=self._pedir_acceso, accesos=self.almacen, reporte_id=self.reporte_id)
        rid = self.reporte_id
        almacen = self.almacen

        def trabajo():
            try:
                res = ejecutor.ejecutar()
            except Exception as e:
                self.cola.put(("error", "Error inesperado: %s" % type(e).__name__))
                res = None
            finally:
                try:
                    almacen.liberar_hilo()      # la conexión de la base de datos de este hilo
                except Exception:
                    pass
            self.cola.put(("ejec", "fin", (res, rid)))

        self._poner_ocupado(True)
        self._estado("Ejecutando… (%s)" % ("a la vista" if self.v_ver.get() else "oculto"))
        self.hilo = threading.Thread(target=trabajo, name="ejecutor", daemon=True)
        self.hilo.start()

    def _evento_ejecucion(self, tipo, datos):
        if tipo == "progreso":
            i, estado, texto = datos
            if estado == "espera":
                self._estado("Paso %d de %d: %s" % (i + 1, len(self.flujo.pasos), texto))
                return
            for iid in self.arbol.get_children():
                tags = [t for t in self.arbol.item(iid, "tags") if t != "actual"]
                self.arbol.item(iid, tags=tags)
            iid = str(i)
            if self.arbol.exists(iid):
                if estado == "inicio":
                    self.arbol.item(iid, tags=("actual",))
                    self.arbol.see(iid)
                    self._estado("Paso %d de %d…" % (i + 1, len(self.flujo.pasos)))
                else:
                    self.arbol.item(iid, tags=(estado,))
        elif tipo == "fin":
            self._poner_ocupado(False)
            res, rid = datos
            if res is None:
                return
            if rid is not None:
                try:
                    self.almacen.registrar_resultado(rid, res)
                    self._refrescar_reportes()
                except sqlite3.Error:
                    pass
            self._estado(res.resumen())
            if res.ok:
                messagebox.showinfo("Ejecución terminada", res.resumen() + "\n\nRegistro: " + res.ruta_log, parent=self.root)
            elif res.detenido:
                messagebox.showinfo("Detenido", res.resumen(), parent=self.root)
            else:
                extra = ("\n\nCaptura: " + res.ruta_captura) if res.ruta_captura else ""
                messagebox.showerror("La ejecución falló", res.resumen() + extra + "\n\nRegistro: " + res.ruta_log,
                                     parent=self.root)

    # ------------------------------------------------------------ ejecutar varios reportes (lote)
    def _ejecutar_lote(self, ids):
        if self.trabajando or not ids:
            return
        if self.reporte_id in ids and self._hay_cambios_sin_guardar():
            if not messagebox.askyesno(
                    "Ejecutar reportes", "El reporte que estás editando tiene cambios sin guardar y el lote usa lo que "
                                         "está guardado. ¿Continuar igualmente?", parent=self.root):
                return
        variables = self._variables_form()
        self.detener_evt.clear()
        registros = os.path.abspath(self.args.registros) if self.args.registros else carpeta("registros")
        descargas = os.path.abspath(self.args.descargas) if self.args.descargas else None
        perfiles = carpeta_perfiles_de(self.args)
        oculto = not self.v_ver.get()
        lento = self.v_lento.get()
        navegador = self.args.navegador or None
        self.lote_actual = (0, len(ids), "")
        almacen = self.almacen

        def trabajo():
            res = None
            try:
                res = lote.ejecutar_lote(
                    list(ids), carpeta_perfiles=perfiles, carpeta_registros=registros, carpeta_descargas=descargas,
                    oculto=oculto, lento=lento, navegador=navegador, variables=variables,
                    progreso=lambda i, estado, texto="": self.cola.put(("lote", "paso", (i, estado, texto))),
                    log=lambda linea: self.cola.put(("log", linea)), detener=self.detener_evt, almacen=almacen,
                    pedir_acceso=self._pedir_acceso,
                    aviso_lote=lambda n, total, item, fase: self.cola.put(("lote", "flujo", (n, total, item.nombre, fase))))
            except Exception as e:
                self.cola.put(("error", "Error inesperado en el lote: %s" % type(e).__name__))
            self.cola.put(("lote", "fin", res))

        self._poner_ocupado(True)
        self._log("--- Lote de %d reporte%s (%s) ---" % (len(ids), "" if len(ids) == 1 else "s",
                                                         "a la vista" if not oculto else "oculto"))
        self._estado("Ejecutando %d reportes…" % len(ids))
        self.hilo = threading.Thread(target=trabajo, name="lote", daemon=True)
        self.hilo.start()

    def _evento_lote(self, tipo, datos):
        if tipo == "flujo":
            n, total, nombre, fase = datos
            if fase == "inicio":
                self.lote_actual = (n, total, nombre)
                self._estado("Reporte %d de %d: «%s»…" % (n, total, nombre))
            else:
                self._refrescar_reportes()
        elif tipo == "paso":
            i, estado, texto = datos
            n, total, nombre = self.lote_actual or (0, 0, "")
            if estado == "espera":
                self._estado("Reporte %d de %d «%s» — paso %d: %s" % (n, total, nombre, i + 1, texto))
            elif estado == "inicio":
                self._estado("Reporte %d de %d «%s» — paso %d: %s" % (n, total, nombre, i + 1, texto[:70]))
        elif tipo == "fin":
            self._poner_ocupado(False)
            self.lote_actual = None
            self._refrescar_reportes()
            if datos is None:
                return
            texto = datos.resumen()
            self._log(texto)
            self._estado("Lote terminado: %d bien, %d fallaron." % (len(datos.correctos), len(datos.fallidos)))
            dlg = DialogoResumen(self.root, "Resumen del lote", texto)
            dlg.grab_set()

    def _detener(self):
        self.detener_evt.set()
        if self.grabador is not None:
            self.grabador.detener()
        if self._peticion_acceso is not None:          # se cierra la pregunta de inicio de sesión pendiente
            self._peticion_acceso.cancelar()
            if self._dialogo_acceso is not None:
                try:
                    self._dialogo_acceso.destroy()
                except tk.TclError:
                    pass
        self._estado("Deteniendo…")

    # ------------------------------------------------------------ cola de mensajes
    def _bombear_cola(self):
        try:
            for _ in range(200):
                try:
                    msg = self.cola.get_nowait()
                except queue.Empty:
                    break
                clase = msg[0]
                if clase == "grab":
                    self._evento_grabacion(msg[1], msg[2])
                elif clase == "ejec":
                    self._evento_ejecucion(msg[1], msg[2])
                elif clase == "lote":
                    self._evento_lote(msg[1], msg[2])
                elif clase == "acceso":
                    self._atender_acceso(msg[1])
                elif clase == "log":
                    self._log(msg[1])
                elif clase == "error":
                    self._log(msg[1])
                    self._estado(msg[1])
                    messagebox.showerror("Error", msg[1], parent=self.root)
            self._ticks += 1
            if self._ticks % 5 == 0:            # cada ~0,5 s: «*» en el título si hay cambios sin guardar
                self._actualizar_titulo()
        finally:
            self.root.after(100, self._bombear_cola)

    def _cerrar(self):
        if self.trabajando:
            if not messagebox.askyesno("Salir", "Hay una grabación o ejecución en curso. ¿Detenerla y salir?",
                                       parent=self.root):
                return
            self._detener()
            if self.hilo is not None:
                self.hilo.join(timeout=8)
        elif not self._confirmar_descartar("salir"):
            return
        self.almacen.cerrar()
        self.root.destroy()


# ================================================================= arranque
def probar_ventana(args):
    """--smoke: construye la ventana y los cuadros de diálogo con una base de datos TEMPORAL (no toca
    datos/bot.db ni importa los flujos de flujos/), comprueba el panel Reportes y sale."""
    tmp = tempfile.mkdtemp(prefix="botweb_smoke_")
    try:
        ruta_db = os.path.join(tmp, "bot.db")
        prueba = Almacen(ruta_db)
        for nombre in ("Ventas (prueba)", "Clientes (prueba)"):
            prueba.guardar(Flujo(nombre=nombre, url="http://127.0.0.1/", pasos=[Paso("abrir_url", url="http://127.0.0.1/")]))
        prueba.cerrar()
        os.makedirs(os.path.join(tmp, "flujos"))
        args.db = ruta_db
        args.carpeta_flujos = os.path.join(tmp, "flujos")
        args.perfil = os.path.join(tmp, "perfiles")
        root = tk.Tk()
        try:
            app = App(root, args)
            root.update()
            app.flujo.pasos = [Paso("abrir_url", url="http://127.0.0.1/"), Paso("clic", selectores=["#a"]),
                               Paso("escribir", selectores=["#b"], valor="{hoy}"), Paso("tecla", tecla="Enter"),
                               Paso("seleccionar", selectores=["#c"], valor="x"), Paso("marcar", selectores=["#d"]),
                               Paso("esperar_elemento", selectores=["#e"]), Paso("esperar_texto", texto="listo"),
                               Paso("esperar_segundos", segundos=2), Paso("descargar", selectores=["#f"], nombre="a{ext}"),
                               Paso("guardar_pagina", formato="pdf", nombre="p_{hoy:%Y-%m-%d}"),
                               Paso("pasar_raton", selectores=["#menu"], auto=True),
                               Paso("elegir_opcion", selectores=["#lista"], estrategia="mas_reciente"),
                               Paso("clic", selectores=["#g"], desactivado=True, espera_grabada=12.5),
                               Paso("iniciar_sesion", sitio="127.0.0.1", enviar={"selectores": ["#entrar"]},
                                    campos=[{"selectores": ["#u"], "etiqueta": "Usuario", "tipo": "texto", "clave": "u",
                                             "valor": "demo"},
                                            {"selectores": ["#p"], "etiqueta": "Contraseña", "tipo": "clave", "clave": "p",
                                             "secreto": "127.0.0.1:p"}])]
            app._refrescar_lista(0)
            for paso in app.flujo.pasos:
                dlg = DialogoPaso(root, paso, {}, app.flujo.opciones)
                dlg.update()
                dlg.destroy()
            if not hasattr(app, "arbol_rep"):
                raise RuntimeError("falta el panel de reportes")
            app._refrescar_reportes()
            root.update()
            filas = len(app.arbol_rep.get_children())
            if filas != 2:
                raise RuntimeError("el panel Reportes debería mostrar 2 reportes de la base de datos y muestra %d" % filas)
            secretos.usar_almacen(secretos.AlmacenMemoria())      # el smoke no toca las credenciales reales
            ids = [r["id"] for r in app.reportes]
            app.almacen.guardar_acceso("127.0.0.1", "usuario", "Usuario", "texto", valor="demo")
            app.almacen.guardar_acceso("127.0.0.1", "clave", "Contraseña", "clave", secreto="127.0.0.1:clave")
            app.almacen.guardar_version(ids[0], "prueba")
            solicitud = {"host": "127.0.0.1", "mensaje": "La página pide iniciar sesión.", "rechazada": True,
                         "error_pagina": "Usuario o contraseña incorrectos",
                         "campos": [{"clave": "u", "etiqueta": "Usuario", "tipo": "texto", "valor": "demo"},
                                    {"clave": "p", "etiqueta": "Contraseña", "tipo": "clave", "valor": ""},
                                    {"clave": "l", "etiqueta": "Licencia", "tipo": "texto", "valor": ""}]}
            accesos = DialogoAccesos(root, app.almacen)
            if len(accesos.arbol.get_children()) != 2:
                raise RuntimeError("el cuadro Accesos debería mostrar 2 campos")
            for dlg in (DialogoContrasenas(root), DialogoProgramar(root, ids[0], "x", {}, db=ruta_db),
                        DialogoProgramar(root, None, "", {}, seleccionados=ids, n_todos=2),
                        DialogoPapelera(root, app.almacen), DialogoResumen(root, "Resumen", "Resumen del lote: 1 de 1"),
                        accesos, DialogoAcceso(root, solicitud),
                        DialogoVersiones(root, app.almacen, ids[0], "Ventas (prueba)")):
                dlg.update()
                dlg.destroy()
            root.update()
            app.flujo.pasos = []                  # sin cambios pendientes: no pregunta nada al salir
            app.almacen.cerrar()
            print("OK: la ventana se construyó correctamente (con el panel Reportes: %d reportes)." % filas)
            return 0
        finally:
            root.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def principal(argv=None):
    for flujo_salida in (sys.stdout, sys.stderr):
        try:
            flujo_salida.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = analizar_argumentos(argv)
    if args.smoke:
        return probar_ventana(args)
    if args.smoke_web:
        from webbot import servidor_ui
        return servidor_ui.probar_web(args)
    if args.ventanita_de is not None:                          # v3.7: la ventanita de progreso (su propio proceso)
        from webbot import ventanita
        return ventanita.principal(os.path.abspath(args.db) if args.db else mod_almacen.ruta_por_defecto(),
                                   args.ventanita_de)
    if args.correo_id or args.correos:                         # v3.4: búsquedas de correo
        return _con_seguimiento(args, revisar_correo_sin_ventana)
    if args.vigilancia_id is not None:                        # v3.3: una vigilancia por su número
        return _con_seguimiento(args, vigilar_sin_ventana)
    if args.pagina or args.pagina_id is not None:              # v3.2: Páginas
        return _con_seguimiento(args, vigilar_pagina_sin_ventana if args.vigilar else ejecutar_pagina_sin_ventana)
    if args.vigilar:
        return _con_seguimiento(args, vigilar_sin_ventana)
    if args.sin_ventana:
        return _con_seguimiento(args, ejecutar_sin_ventana)
    if not args.clasica:
        from webbot import servidor_ui
        return servidor_ui.abrir_aplicacion(args)
    root = tk.Tk()
    App(root, args)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
