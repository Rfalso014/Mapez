"""Crea el paquete para compartir Bot Web: «paquete/Bot Web para compartir.zip».

Solo lleva lo GUARDADO en git (`git archive HEAD`): nunca los datos de este equipo (datos/, perfiles/, registros/,
descargas/ no están en git) ni las pruebas.  Dentro del .zip:

    Bot Web/
        Instalar Bot Web.cmd      ← doble clic en la otra PC
        Desinstalar Bot Web.cmd
        LEEME.txt
        programa/                 ← el código del bot

Uso: doble clic en «Crear paquete para compartir.cmd» (o `python instalador/crear_paquete.py`).
"""

import io
import os
import subprocess
import sys
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "paquete", "Bot Web para compartir.zip")
SUELTOS = ("Instalar Bot Web.cmd", "Desinstalar Bot Web.cmd", "LEEME.txt")
NO_LLEVAR = ("tests/", "datos/", "perfiles/", "registros/", "descargas/", "paquete/")


def archivos_de_git():
    """{ruta: bytes} de lo guardado en git (HEAD), sin pruebas ni datos."""
    zip_git = subprocess.run(["git", "archive", "--format=zip", "HEAD"], cwd=RAIZ, capture_output=True, check=True).stdout
    res = {}
    with zipfile.ZipFile(io.BytesIO(zip_git)) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename.startswith(NO_LLEVAR) or "__pycache__/" in info.filename:
                continue
            if info.filename.startswith("flujos/") and info.filename.endswith(".json"):
                continue
            res[info.filename] = z.read(info)
    return res


def crear():
    sucio = subprocess.run(["git", "status", "--porcelain"], cwd=RAIZ, capture_output=True, text=True).stdout.strip()
    if sucio:
        print("Aviso: hay cambios sin guardar en git; el paquete lleva lo último GUARDADO (git), no esos cambios.")
    archivos = archivos_de_git()
    for n in SUELTOS:
        if "instalador/" + n not in archivos:
            sys.exit("Falta «instalador/%s» en git: guarda los cambios (commit) y vuelve a crear el paquete." % n)
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with zipfile.ZipFile(SALIDA, "w", zipfile.ZIP_DEFLATED) as z:
        for n in SUELTOS:
            z.writestr("Bot Web/" + n, archivos["instalador/" + n])
        for ruta, datos in sorted(archivos.items()):
            z.writestr("Bot Web/programa/" + ruta, datos)
    mb = os.path.getsize(SALIDA) / 1024 / 1024
    print("Paquete creado: %s (%.1f MB, %d archivos del programa)." % (SALIDA, mb, len(archivos)))
    print("Compártelo; en la otra PC: descomprimir y doble clic en «Instalar Bot Web.cmd».")
    return SALIDA


if __name__ == "__main__":
    crear()
