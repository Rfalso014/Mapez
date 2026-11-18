"""v3.9: la lista de TODO lo que baja una ejecución grande, para enseñarla en la interfaz mientras se ejecuta.

Una ejecución es «grande» si recorre una lista («para cada opción»: cada comercio, cada sucursal…) o se repite (por días,
meses o quincenas), o las dos cosas (cada comercio × cada mes).  Cada elemento de la lista es un pase (una opción de la
lista en un periodo) con su estado: pendiente → descargando → listo (con sus archivos: «PDF ✔ Excel ✔») o falló (con el
motivo).  Lo que quedó sin hacer (se detuvo o falló antes) queda «sin hacer».  No importa playwright: el ejecutor la va
actualizando y cada cambio se avisa con `avisar(datos)` (la aplicación lo manda a la interfaz como evento «descargas»).

Con «cada_una» las opciones no se saben hasta leer la lista: entonces el total se da en cuanto se leen.
"""

import os
import re

ESTADOS = ("pendiente", "descargando", "listo", "fallo", "sin_hacer")
TIPOS_ARCHIVO = {".pdf": "PDF", ".xlsx": "Excel", ".xls": "Excel", ".xlsm": "Excel", ".xlsb": "Excel", ".csv": "CSV",
                 ".htm": "HTML", ".html": "HTML", ".txt": "Texto", ".zip": "ZIP", ".doc": "Word", ".docx": "Word",
                 ".xml": "XML", ".json": "JSON"}
NOMBRES_PERIODO = {"meses": ("mes", "meses"), "quincenas": ("quincena", "quincenas")}
MAX_ITEMS = 2000


def tipo_archivo(ruta):
    """«PDF», «Excel», «CSV»… (lo que se enseña junto a cada elemento)."""
    ext = os.path.splitext(ruta or "")[1].lower()
    return TIPOS_ARCHIVO.get(ext, ext[1:].upper() or "Archivo")


def plural(nombre, n):
    """El nombre de la lista en singular o plural («Comercio» → «comercios»); si no es una palabra sencilla, «opciones»."""
    t = (nombre or "").strip().strip("«»\"' ").strip()
    if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,30}", t):
        return "opción" if n == 1 else "opciones"
    t = t.lower()
    if n == 1:
        return t
    if t.endswith("ón"):
        return t[:-2] + "ones"
    if t.endswith("z"):
        return t[:-1] + "ces"
    if t[-1] in "aeiouéá" or t.endswith("s"):
        return t if t.endswith("s") else t + "s"
    return t + "es"


def _contar(n, singular, plural_):
    return "%d %s" % (n, singular if n == 1 else plural_)


class ListaDescargas:
    def __init__(self, reporte, avisar, periodos=None, modo_periodo=None, lista=None, opciones=None, por_pase=1):
        """
        - reporte: nombre del reporte; avisar(datos): se llama en cada cambio.
        - periodos: textos de los pases de «Repetir…» («octubre 2026», «01/11/2026»…); vacío/None = no se repite.
        - modo_periodo: «meses», «quincenas» o «dias» (para las palabras).
        - lista: nombre de la lista de «para cada opción» (None = sin repetir por opciones).
        - opciones: las opciones que se recorren si ya se saben («las que marque»); None = se sabrán al leer la lista.
        - por_pase: cuántos archivos guarda cada pase (los pasos «Descargar» / «Guardar la página» que se repiten).
        """
        self.reporte = reporte or ""
        self._avisar = avisar
        self.periodos = list(periodos or [])
        self.modo_periodo = modo_periodo or "dias"
        self.lista = lista
        self.opciones = list(opciones) if opciones is not None else None
        self.por_pase = max(1, int(por_pase or 1))
        self.terminado = False
        self.items = []
        self._actual = None
        self.otros_archivos = 0
        for pi in range(max(1, len(self.periodos))):
            self.items.extend(self._nuevos(pi, self.opciones))
        self.avisar()

    # ------------------------------------------------------------ elementos
    def _nuevos(self, pi, opciones):
        per = self.periodos[pi] if self.periodos else ""
        if self.lista is None:
            return [self._item(pi, per, None)] if self.periodos else []
        return [self._item(pi, per, o) for o in (opciones or [])]

    @staticmethod
    def _item(pi, periodo, opcion):
        return {"id": "%d|%s" % (pi, opcion if opcion is not None else ""), "periodo": pi, "periodo_texto": periodo,
                "opcion": opcion, "texto": opcion if opcion is not None else periodo, "estado": "pendiente",
                "archivos": [], "motivo": ""}

    def _buscar(self, pi, opcion):
        for it in self.items:
            if it["periodo"] == pi and it["opcion"] == opcion:
                return it
        return None

    # ------------------------------------------------------------ lo que hace el ejecutor
    def opciones_leidas(self, pi, opciones):
        """Las opciones que se van a recorrer en el pase `pi` (al leer la lista con «cada_una», o las marcadas)."""
        opciones = list(opciones)
        if self.lista is None:
            return
        if self.opciones is None:              # primera vez que se saben: se supone la misma lista en todos los pases
            self.opciones = opciones
            for k in range(max(1, len(self.periodos))):
                if not any(it["periodo"] == k for it in self.items):
                    self.items.extend(self._nuevos(k, opciones))
            self._ordenar()
        else:
            viejos = {it["opcion"]: it for it in self.items if it["periodo"] == pi}
            if list(viejos) != opciones:       # en este pase la lista trae otras opciones
                otros = [it for it in self.items if it["periodo"] != pi]
                nuevos = [viejos.get(o) or self._item(pi, self.periodos[pi] if self.periodos else "", o) for o in opciones]
                for it in viejos.values():
                    if it["opcion"] not in opciones and it["estado"] in ("listo", "fallo"):
                        nuevos.append(it)
                self.items = otros + nuevos
                self._ordenar()
        del self.items[MAX_ITEMS:]
        self.avisar()

    def _ordenar(self):
        self.items.sort(key=lambda it: it["periodo"])          # (estable: dentro de cada pase, el orden de la lista)

    def empezar(self, pi, opcion=None):
        it = self._buscar(pi, opcion)
        if it is None:
            it = self._item(pi, self.periodos[pi] if self.periodos else "", opcion)
            self.items.append(it)
            self._ordenar()
        it.update(estado="descargando", motivo="")
        self._actual = it
        self.avisar()

    def terminar(self, ok, motivo=""):
        it = self._actual
        if it is None:
            return
        it["estado"] = "listo" if ok else "fallo"
        it["motivo"] = "" if ok else (motivo or "falló")
        self._actual = None
        self.avisar()

    def fallo_pase(self, pi, motivo):
        """El pase `pi` falló antes de recorrer la lista (no se pudo leer, no tenía opciones…)."""
        cambio = False
        for it in self.items:
            if it["periodo"] == pi and it["estado"] in ("pendiente", "descargando"):
                it.update(estado="fallo", motivo=motivo or "falló")
                cambio = True
        if not cambio and self.lista is not None and self.opciones is None:
            it = self._item(pi, self.periodos[pi] if self.periodos else "", None)
            it.update(texto="Lista %s" % self.lista if self.lista else "Lista", estado="fallo", motivo=motivo or "falló")
            self.items.append(it)
            self._ordenar()
        self._actual = None
        self.avisar()

    def archivo(self, ruta):
        it = self._actual
        if it is None:
            self.otros_archivos += 1
        else:
            it["archivos"].append({"nombre": os.path.basename(ruta), "tipo": tipo_archivo(ruta), "impreso": None})
        self.avisar()

    def impreso(self, ruta, ok):
        nombre = os.path.basename(ruta)
        for it in reversed(self.items):
            for a in it["archivos"]:
                if a["nombre"] == nombre and a["impreso"] is None:
                    a["impreso"] = bool(ok)
                    self.avisar()
                    return

    def cerrar(self, detenido=False, error=""):
        """Al terminar la ejecución: lo que se estaba bajando falló (o se detuvo) y lo pendiente queda «sin hacer»."""
        for it in self.items:
            if it["estado"] == "descargando":
                it.update(estado="fallo", motivo="Detenido por ti" if detenido else (error or "falló"))
            elif it["estado"] == "pendiente":
                it.update(estado="sin_hacer", motivo="Se detuvo antes" if detenido else "No se llegó a bajar")
        self._actual = None
        self.terminado = True
        self.avisar()

    # ------------------------------------------------------------ lo que se enseña
    def _nombre_pases(self, n):
        s, p = NOMBRES_PERIODO.get(self.modo_periodo, ("día", "días"))
        return _contar(n, s, p)

    def resumen(self):
        """«Se van a bajar 17 comercios × 1 mes = 34 archivos»."""
        partes = []
        if self.lista is not None:
            if self.opciones is None:
                partes.append("las opciones de «%s» (se sabrá cuántas al leer la lista)" % self.lista)
            else:
                partes.append("%d %s" % (len(self.opciones), plural(self.lista, len(self.opciones))))
        if self.periodos:
            partes.append(self._nombre_pases(len(self.periodos)))
        texto = "Se van a bajar " + " × ".join(partes)
        if self.lista is None or self.opciones is not None:
            pases = (len(self.opciones) if self.lista is not None else 1) * max(1, len(self.periodos))
            texto += " = " + _contar(pases * self.por_pase, "archivo", "archivos")
        return texto

    def titulo(self):
        """«Pagos — 6 de 17 comercios»: el que se está bajando (o los ya hechos) de cuántos."""
        total = len(self.items)
        hechos = sum(1 for it in self.items if it["estado"] in ("listo", "fallo"))
        n = hechos + (1 if any(it["estado"] == "descargando" for it in self.items) else 0)
        if self.lista is not None and len(self.periodos) <= 1:
            que = plural(self.lista, total)
        elif self.lista is None:
            s, p = NOMBRES_PERIODO.get(self.modo_periodo, ("día", "días"))
            que = s if total == 1 else p
        else:
            que = "descarga" if total == 1 else "descargas"
        if self.terminado:
            n = hechos
        return "%s — %d de %d %s" % (self.reporte, min(n, total), total, que)

    def datos(self):
        cuenta = {e: sum(1 for it in self.items if it["estado"] == e) for e in ESTADOS}
        return {"reporte": self.reporte, "titulo": self.titulo(), "resumen": self.resumen(), "total": len(self.items),
                "listos": cuenta["listo"], "fallos": cuenta["fallo"], "pendientes": cuenta["pendiente"],
                "sin_hacer": cuenta["sin_hacer"], "terminado": self.terminado, "por_leer": self.lista is not None and
                self.opciones is None, "lista": self.lista or "", "con_periodos": len(self.periodos) > 1,
                "archivos": sum(len(it["archivos"]) for it in self.items) + self.otros_archivos,
                "items": [dict(it, archivos=[dict(a) for a in it["archivos"]]) for it in self.items]}

    def avisar(self):
        if self._avisar is None:
            return
        try:
            self._avisar(self.datos())
        except Exception:          # noqa: BLE001 (la interfaz no debe parar una descarga)
            pass
