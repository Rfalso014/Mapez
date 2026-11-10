"""Bot web (versiÃ³n 2): graba y reproduce pasos en el navegador con Playwright."""

import os

VERSION = "3.6"

# Carpeta del proyecto (la que contiene bot.py y la carpeta webbot).
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carpeta(nombre):
    """Devuelve (y crea si hace falta) una carpeta de trabajo dentro del proyecto."""
    ruta = os.path.join(RAIZ, nombre)
    os.makedirs(ruta, exist_ok=True)
    return ruta
