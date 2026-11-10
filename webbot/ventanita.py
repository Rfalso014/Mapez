"""v3.7: la ventanita de progreso de las ejecuciones programadas (tareas de Windows).

Se abre en SU PROPIO proceso (`python bot.py --db <base> --ventanita-de <fila>`, ver `seguimiento.abrir_ventanita_proceso`):
así, si tkinter falla o no hay escritorio, la ejecución sigue igual.  Lee la fila de la tabla `en_curso` cada medio segundo
y enseña: el nombre, «Paso 3 de 8: Clic en …», la barra de progreso, el tiempo que lleva y los botones:

- mientras espera para empezar («Avisarme antes»): «Ver en vivo» (si va en segundo plano), «Empezar ya» y «Cancelar
  esta ejecución»;
- mientras trabaja: «Detener» (el navegador ya está abierto como estaba: no se puede pasar a verlo en vivo a mitad);
- al terminar: el resultado y «Cerrar»; se cierra sola a los pocos segundos.

Siempre encima de las demás ventanas, abajo a la derecha.  `vista(fila)` (sin tkinter) decide qué se enseña.
"""

import datetime as _dt

FORMATO = "%Y-%m-%d %H:%M:%S"
CERRAR_TRAS = 8.0              # segundos que se ve el resultado antes de cerrarse sola
CADA_MS = 500
BOTONES = {"en_vivo": "Ver en vivo", "ya": "Empezar ya", "cancelar": "Cancelar esta ejecución", "detener": "Detener",
           "cerrar": "Cerrar"}


def _reloj(segundos):
    s = max(0, int(segundos))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def vista(fila, ahora=None):
    """Lo que enseña la ventanita para esa fila de `en_curso`: {titulo, texto, pct (None = sin saber cuánto falta),
    tiempo, botones [en_vivo|ya|cancelar|detener|cerrar], final, estado} o {cerrar: True} si ya no existe."""
    if not fila:
        return {"cerrar": True}
    ahora = ahora or _dt.datetime.now()
    estado = fila.get("estado") or "en_curso"
    titulo = fila.get("nombre") or "Bot Web"
    if estado == "esperando":
        try:
            ini = _dt.datetime.strptime(fila["inicio"], FORMATO)
            emp = _dt.datetime.strptime(fila["empieza"], FORMATO)
        except (KeyError, TypeError, ValueError):
            ini = emp = ahora
        total = max(1.0, (emp - ini).total_seconds())
        falta = max(0.0, (emp - ahora).total_seconds())
        botones = ([] if fila.get("visible") else ["en_vivo"]) + ["ya", "cancelar"]
        modo = "en vivo" if fila.get("visible") else "en segundo plano"
        return {"titulo": titulo, "estado": estado, "final": False, "botones": botones,
                "texto": "Se ejecutará a las %s (%s)" % (emp.strftime("%H:%M"), modo),
                "pct": min(100.0, 100.0 * (total - falta) / total), "tiempo": "Empieza dentro de %s" % _reloj(falta)}
    if estado == "en_curso":
        paso, total, texto = int(fila.get("paso") or 0), int(fila.get("total") or 0), fila.get("texto") or ""
        if total and paso:
            linea = "Paso %d de %d: %s" % (min(paso, total), total, texto or "…")
            pct = min(100.0, 100.0 * paso / total)
        else:
            linea, pct = texto or "Empezando…", None
        return {"titulo": titulo, "estado": estado, "final": False, "botones": ["detener"], "texto": linea, "pct": pct,
                "tiempo": "Lleva %s%s" % (_reloj(fila.get("segundos") or 0),
                                          " · en vivo" if fila.get("visible") else " · en segundo plano")}
    resumen = fila.get("resumen") or fila.get("texto") or ""
    pre = {"ok": "Terminó bien", "error": "Falló", "detenido": "Se detuvo", "cancelado": "Cancelada"}.get(estado, "Terminó")
    texto = resumen[0].upper() + resumen[1:] if resumen else pre
    return {"titulo": titulo, "estado": estado, "final": True, "botones": ["cerrar"], "texto": texto,
            "pct": 100.0 if estado == "ok" else None,
            "tiempo": ("Tardó %s" % _reloj(fila.get("segundos") or 0)) if estado != "cancelado" else ""}


class Ventanita:
    """La ventana (tkinter).  `leer()` → la fila (o None); `pedir(p)` → guarda lo que pide el usuario."""

    COLORES = {"ok": "#1f8a5a", "error": "#c0392b", "detenido": "#b7791f", "cancelado": "#666666"}

    def __init__(self, root, leer, pedir, cerrar_tras=CERRAR_TRAS, cada_ms=CADA_MS):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.leer, self.pedir = root, leer, pedir
        self.cerrar_tras, self.cada_ms = cerrar_tras, cada_ms
        self.final_desde = None
        self.botones_vistos = None
        self.sin_fila = 0
        self.indeterminada = False
        root.title("Bot Web — progreso")
        root.resizable(False, False)
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        marco = ttk.Frame(root, padding=12)
        marco.pack(fill="both", expand=True)
        self.lbl_titulo = ttk.Label(marco, text="", font=("Segoe UI", 11, "bold"), wraplength=330)
        self.lbl_titulo.pack(anchor="w")
        self.lbl_texto = ttk.Label(marco, text="", wraplength=330, justify="left")
        self.lbl_texto.pack(anchor="w", pady=(4, 6))
        self.barra = ttk.Progressbar(marco, length=330, mode="determinate", maximum=100)
        self.barra.pack(fill="x")
        self.lbl_tiempo = ttk.Label(marco, text="", foreground="#666666")
        self.lbl_tiempo.pack(anchor="w", pady=(4, 8))
        self.zona_botones = ttk.Frame(marco)
        self.zona_botones.pack(anchor="e")
        root.protocol("WM_DELETE_WINDOW", self.cerrar)

    def colocar(self):
        """Abajo a la derecha (encima de la barra de tareas)."""
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = max(0, self.root.winfo_screenwidth() - w - 24)
        y = max(0, self.root.winfo_screenheight() - h - 80)
        self.root.geometry("+%d+%d" % (x, y))

    def cerrar(self):
        try:
            self.root.destroy()
        except Exception:          # noqa: BLE001
            pass

    def _pulsar(self, que):
        if que == "cerrar":
            self.cerrar()
            return
        try:
            self.pedir(que)
        except Exception:          # noqa: BLE001
            pass
        if que in ("detener", "cancelar"):
            self.lbl_texto.configure(text="Deteniendo…" if que == "detener" else "Cancelando…")

    def pintar(self, v):
        from tkinter import ttk
        self.lbl_titulo.configure(text=v["titulo"])
        self.lbl_texto.configure(text=v["texto"], foreground=self.COLORES.get(v["estado"], ""))
        self.lbl_tiempo.configure(text=v["tiempo"])
        if v["pct"] is None and not v["final"]:
            if not self.indeterminada:
                self.barra.configure(mode="indeterminate")
                self.barra.start(15)
                self.indeterminada = True
        else:
            if self.indeterminada:
                self.barra.stop()
                self.barra.configure(mode="determinate")
                self.indeterminada = False
            self.barra["value"] = v["pct"] or 0
        if v["botones"] != self.botones_vistos:
            self.botones_vistos = list(v["botones"])
            for b in self.zona_botones.winfo_children():
                b.destroy()
            for que in v["botones"]:
                ttk.Button(self.zona_botones, text=BOTONES[que], command=lambda q=que: self._pulsar(q)).pack(
                    side="left", padx=(6, 0))

    def actualizar(self):
        """Una vuelta: lee la fila y la pinta.  Devuelve False si la ventanita se cierra."""
        try:
            fila = self.leer()
        except Exception:          # noqa: BLE001
            fila = None
        v = vista(fila)
        if v.get("cerrar"):
            self.sin_fila += 1
            if self.sin_fila >= 4:
                self.cerrar()
                return False
            return True
        self.sin_fila = 0
        self.pintar(v)
        if v["final"]:
            if self.final_desde is None:
                self.final_desde = _dt.datetime.now()
            elif (_dt.datetime.now() - self.final_desde).total_seconds() >= self.cerrar_tras:
                self.cerrar()
                return False
        return True

    def bucle(self):
        if self.actualizar():
            self.root.after(self.cada_ms, self.bucle)


def principal(db, fila_id):
    """`bot.py --ventanita-de N`: abre la ventanita y vuelve cuando se cierra.  Si algo falla, no pasa nada."""
    try:
        import tkinter as tk

        from .almacen import Almacen
        alm = Almacen(db)
    except Exception:              # noqa: BLE001
        return 0
    try:
        root = tk.Tk()
    except Exception:              # noqa: BLE001  (sin escritorio)
        alm.cerrar()
        return 0
    try:
        v = Ventanita(root, lambda: alm.en_curso_id(fila_id), lambda p: alm.pedir_en_curso(fila_id, p))
        v.actualizar()
        v.colocar()
        root.after(CADA_MS, v.bucle)
        root.mainloop()
    except Exception:              # noqa: BLE001
        pass
    finally:
        alm.cerrar()
    return 0
