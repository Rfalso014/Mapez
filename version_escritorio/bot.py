"""Bot Copión: graba y reproduce acciones de ratón y teclado (Windows).

Atajos globales: F9 grabar/detener · F10 ejecutar · Esc abortar.
Uso: ``python bot.py``  (o doble clic en ``iniciar.bat``).
"""

import argparse
import os
import sys

import acciones as ac

# IMPORTANTE: la DPI awareness debe activarse ANTES de crear Tk o cualquier
# objeto de pynput; así las coordenadas grabadas y reproducidas coinciden.
DPI_ACTIVADA = ac.activar_dpi_awareness()

import queue  # noqa: E402
import shutil  # noqa: E402
import tkinter as tk  # noqa: E402
import traceback  # noqa: E402
import webbrowser  # noqa: E402
from tkinter import filedialog, messagebox, simpledialog, ttk  # noqa: E402

from pynput import keyboard  # noqa: E402

import grabador  # noqa: E402
import reproductor  # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))
CARPETA_GRABACIONES = os.path.join(RAIZ, "grabaciones")
ULTIMA = os.path.join(CARPETA_GRABACIONES, "ultima.json")
ANTERIOR = os.path.join(CARPETA_GRABACIONES, "anterior.json")

TITULO = "Bot Copión — grabador y reproductor de acciones"
VELOCIDADES = ["0.25×", "0.5×", "0.75×", "1×", "1.5×", "2×", "3×", "4×"]
TECLAS_BOT = {"Key.f9": "f9", "Key.f10": "f10", "Key.esc": "esc"}

REPOSO, INICIANDO, GRABANDO, EJECUTANDO = "reposo", "iniciando", "grabando", "ejecutando"
RETARDO_MINIMIZAR_MS = 700   # tiempo para que la ventana desaparezca antes de grabar
RETARDO_EJECUTAR_MS = 400


class App:
    def __init__(self, root, smoke=False, url=""):
        self.root = root
        self.smoke = smoke
        self._url_inicial = ac.normalizar_url(url)
        self._url_grabacion = None      # URL abierta al empezar la grabación actual
        self._espera_grabacion = 0.0
        self._token_inicio = 0
        self.estado = REPOSO
        self.grabacion = ac.Grabacion()
        self.pasos = []
        self.grabador = None
        self.reproductor = None
        self.run_id = 0
        self._cola = queue.Queue()
        self._vivo = True
        self._item_actual = None
        self._overlay = None
        self._teclas_abajo = set()
        self._minimizada_por_nosotros = False

        self._construir_ui()
        os.makedirs(CARPETA_GRABACIONES, exist_ok=True)
        self._cargar_ultima()
        self.refrescar_lista()
        self._actualizar_controles()

        # atajos globales (listener propio, solo encola mensajes)
        self._atajos = keyboard.Listener(on_press=self._al_presionar_global,
                                         on_release=self._al_soltar_global)
        self._atajos.start()

        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.root.after(30, self._bombear)
        self.root.after(250, self._tick)

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    def _construir_ui(self):
        root = self.root
        root.title(TITULO)
        escala = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.escala = escala
        root.geometry("%dx%d" % (int(940 * escala), int(600 * escala)))
        root.minsize(int(760 * escala), int(460 * escala))

        estilo = ttk.Style(root)
        estilo.configure("Treeview", rowheight=int(24 * escala))
        estilo.configure("Grande.TButton", padding=(10, 5))

        # --- barra principal ---
        barra = ttk.Frame(root, padding=(8, 8, 8, 4))
        barra.pack(fill="x")
        self.b_grabar = ttk.Button(barra, text="⏺ Grabar (F9)", style="Grande.TButton", command=self.iniciar_grabacion)
        self.b_detener = ttk.Button(barra, text="⏹ Detener", style="Grande.TButton", command=self.detener)
        self.b_ejecutar = ttk.Button(barra, text="▶ Ejecutar (F10)", style="Grande.TButton", command=self.ejecutar)
        self.b_guardar = ttk.Button(barra, text="💾 Guardar", style="Grande.TButton", command=self.guardar_como)
        self.b_cargar = ttk.Button(barra, text="📂 Cargar", style="Grande.TButton", command=self.cargar_archivo)
        self.b_limpiar = ttk.Button(barra, text="🗑 Limpiar", style="Grande.TButton", command=self.limpiar)
        for b in (self.b_grabar, self.b_detener, self.b_ejecutar):
            b.pack(side="left", padx=(0, 4))
        ttk.Separator(barra, orient="vertical").pack(side="left", fill="y", padx=8)
        for b in (self.b_guardar, self.b_cargar, self.b_limpiar):
            b.pack(side="left", padx=(0, 4))

        # --- URL ---
        marco_url = ttk.Frame(root, padding=(8, 0, 8, 2))
        marco_url.pack(fill="x")
        ttk.Label(marco_url, text="URL:").pack(side="left")
        self.var_url = tk.StringVar(value=self._url_inicial)
        self.e_url = ttk.Entry(marco_url, textvariable=self.var_url)
        self.e_url.pack(side="left", fill="x", expand=True, padx=(4, 8))
        ttk.Label(marco_url, text="(opcional) se abre al grabar y al ejecutar", foreground="#555555").pack(side="left")

        # --- opciones ---
        opciones = ttk.LabelFrame(root, text="Opciones de grabación y reproducción", padding=(8, 4))
        opciones.pack(fill="x", padx=8, pady=4)
        ttk.Label(opciones, text="Velocidad:").grid(row=0, column=0, sticky="w")
        self.var_velocidad = tk.StringVar(value="1×")
        self.c_velocidad = ttk.Combobox(opciones, textvariable=self.var_velocidad, values=VELOCIDADES, width=7)
        self.c_velocidad.grid(row=0, column=1, padx=(4, 16))
        ttk.Label(opciones, text="Repeticiones:").grid(row=0, column=2, sticky="w")
        self.var_reps = tk.StringVar(value="1")
        self.s_reps = tk.Spinbox(opciones, from_=1, to=9999, width=6, textvariable=self.var_reps)
        self.s_reps.grid(row=0, column=3, padx=(4, 16))
        ttk.Label(opciones, text="Cuenta regresiva (s):").grid(row=0, column=4, sticky="w")
        self.var_cuenta = tk.StringVar(value="3")
        self.s_cuenta = tk.Spinbox(opciones, from_=0, to=60, width=4, textvariable=self.var_cuenta)
        self.s_cuenta.grid(row=0, column=5, padx=(4, 16))
        ttk.Label(opciones, text="Espera de carga (s):").grid(row=0, column=6, sticky="w")
        self.var_carga = tk.StringVar(value="5")
        self.s_carga = tk.Spinbox(opciones, from_=0, to=120, width=4, textvariable=self.var_carga)
        self.s_carga.grid(row=0, column=7, padx=(4, 0))
        self.var_mover = tk.BooleanVar(value=True)
        ttk.Checkbutton(opciones, text="Grabar movimientos del ratón", variable=self.var_mover).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.var_minimizar = tk.BooleanVar(value=True)
        ttk.Checkbutton(opciones, text="Minimizar esta ventana al ejecutar", variable=self.var_minimizar).grid(
            row=1, column=3, columnspan=3, sticky="w", pady=(4, 0))

        # --- edición ---
        edicion = ttk.Frame(root, padding=(8, 4, 8, 0))
        edicion.pack(fill="x")
        ttk.Label(edicion, text="Pasos grabados", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.b_borrar = ttk.Button(edicion, text="✖ Eliminar paso(s)", command=self.eliminar_seleccion)
        self.b_espera = ttk.Button(edicion, text="⏱ Insertar espera…", command=self.insertar_espera)
        self.b_nota = ttk.Button(edicion, text="✏ Editar nota", command=self.editar_nota_seleccion)
        self.b_url = ttk.Button(edicion, text="🌐 Insertar Abrir URL…", command=self.insertar_url)
        for b in (self.b_borrar, self.b_espera, self.b_url, self.b_nota):
            b.pack(side="right", padx=(4, 0))

        # --- lista ---
        marco = ttk.Frame(root, padding=(8, 4))
        marco.pack(fill="both", expand=True)
        columnas = ("n", "accion", "tiempo", "nota")
        self.tree = ttk.Treeview(marco, columns=columnas, show="headings", selectmode="extended")
        self.tree.heading("n", text="Nº")
        self.tree.heading("accion", text="Acción")
        self.tree.heading("tiempo", text="Tiempo")
        self.tree.heading("nota", text="Nota (doble clic para editar)")
        self.tree.column("n", width=int(50 * escala), anchor="e", stretch=False)
        self.tree.column("accion", width=int(430 * escala), anchor="w")
        self.tree.column("tiempo", width=int(80 * escala), anchor="e", stretch=False)
        self.tree.column("nota", width=int(300 * escala), anchor="w")
        scroll = ttk.Scrollbar(marco, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("espera", foreground="#6b6b6b")
        self.tree.tag_configure("actual", background="#ffe08a", foreground="#000000")
        self.tree.bind("<Double-1>", self._doble_clic_lista)
        self.tree.bind("<Return>", lambda e: self.editar_nota_seleccion())
        self.tree.bind("<Delete>", lambda e: self.eliminar_seleccion())

        # --- barra de estado ---
        pie = ttk.Frame(root, padding=(8, 2, 8, 6))
        pie.pack(fill="x")
        self.var_estado = tk.StringVar(value="Listo.")
        ttk.Label(pie, textvariable=self.var_estado).pack(side="left")
        ttk.Label(pie, text="F9 grabar/detener · F10 ejecutar · Esc abortar", foreground="#555555").pack(side="right")

    def estado_texto(self, texto):
        self.var_estado.set(texto)

    def _actualizar_controles(self):
        reposo = self.estado == REPOSO
        hay = len(self.grabacion) > 0

        def poner(boton, activo):
            boton.configure(state="normal" if activo else "disabled")

        poner(self.b_grabar, reposo)
        poner(self.b_detener, self.estado in (INICIANDO, GRABANDO, EJECUTANDO))
        poner(self.b_ejecutar, reposo and hay)
        poner(self.b_guardar, reposo and hay)
        poner(self.b_cargar, reposo)
        poner(self.b_limpiar, reposo and hay)
        poner(self.b_borrar, reposo and hay)
        poner(self.b_espera, reposo)
        poner(self.b_nota, reposo and hay)
        poner(self.b_url, reposo)
        self.e_url.configure(state="normal" if reposo else "disabled")

    # ------------------------------------------------------------------
    # Lista de pasos
    # ------------------------------------------------------------------
    def refrescar_lista(self, seleccionar=None):
        """Reconstruye la tabla desde los eventos crudos."""
        anterior = self.tree.yview()
        self.pasos = self.grabacion.pasos()
        self.tree.delete(*self.tree.get_children())
        self._item_actual = None
        for i, p in enumerate(self.pasos):
            etiquetas = ("espera",) if p.tipo in ("esperar", "espera_auto") else ()
            self.tree.insert("", "end", iid=str(i), tags=etiquetas,
                             values=(i + 1, p.descripcion, "%.2f s" % p.t, p.nota))
        if seleccionar:
            validos = [str(i) for i in seleccionar if 0 <= i < len(self.pasos)]
            if validos:
                self.tree.selection_set(validos)
                self.tree.see(validos[0])
        elif anterior and anterior[0] > 0:
            self.tree.yview_moveto(anterior[0])
        self._actualizar_controles()

    def _indices_seleccionados(self):
        return sorted(int(i) for i in self.tree.selection())

    def _doble_clic_lista(self, evento):
        if self.estado != REPOSO:
            return
        fila = self.tree.identify_row(evento.y)
        if fila:
            self.editar_nota(int(fila))

    def editar_nota_seleccion(self):
        sel = self._indices_seleccionados()
        if sel:
            self.editar_nota(sel[0])
        else:
            self.estado_texto("Selecciona un paso para editar su nota.")

    def editar_nota(self, indice):
        if self.estado != REPOSO or not (0 <= indice < len(self.pasos)):
            return
        paso = self.pasos[indice]
        texto = simpledialog.askstring(
            "Nota del paso %d" % (indice + 1),
            "%s\n\nEscribe una nota o indicación para este paso:" % paso.descripcion,
            initialvalue=paso.nota, parent=self.root)
        if texto is None:
            return
        self.aplicar_nota(indice, texto)

    def aplicar_nota(self, indice, texto):
        self.grabacion.poner_nota(self.pasos[indice], texto)
        self.tree.set(str(indice), "nota", self.pasos[indice].nota)
        self.autoguardar()

    def eliminar_seleccion(self):
        if self.estado != REPOSO:
            return
        sel = self._indices_seleccionados()
        if not sel:
            self.estado_texto("Selecciona uno o más pasos para eliminar.")
            return
        if not messagebox.askyesno("Eliminar pasos", "¿Eliminar %d paso(s) y sus eventos grabados?" % len(sel),
                                   parent=self.root):
            return
        self.grabacion.eliminar_pasos([self.pasos[i] for i in sel])
        self.refrescar_lista(seleccionar=[min(sel)])
        self.autoguardar()
        self.estado_texto("Se eliminaron %d paso(s)." % len(sel))

    def insertar_espera(self):
        if self.estado != REPOSO:
            return
        segundos = simpledialog.askfloat("Insertar espera", "Segundos a esperar:", initialvalue=1.0,
                                         minvalue=0.1, maxvalue=3600, parent=self.root)
        if segundos is None:
            return
        sel = self._indices_seleccionados()
        paso = self.pasos[sel[-1]] if sel else (self.pasos[-1] if self.pasos else None)
        pos = self.grabacion.insertar_espera_despues_de(paso, segundos)
        self._refrescar_y_seleccionar_evento(pos)
        self.autoguardar()
        self.estado_texto("Espera de %.1f s insertada." % segundos)

    def _refrescar_y_seleccionar_evento(self, pos):
        self.refrescar_lista()
        nuevo = [i for i, p in enumerate(self.pasos) if pos in p.indices]
        if nuevo:
            self.tree.selection_set(str(nuevo[0]))
            self.tree.see(str(nuevo[0]))

    def insertar_url(self):
        """Inserta a mano un paso "Abrir URL" tras el paso seleccionado (o al final)."""
        if self.estado != REPOSO:
            return
        texto = simpledialog.askstring("Insertar Abrir URL", "Dirección que se abrirá en el navegador:",
                                       initialvalue=self.var_url.get(), parent=self.root)
        url = ac.normalizar_url(texto)
        if not url:
            return
        try:
            espera = self._leer_espera_carga()
        except ValueError:
            espera = 5.0
        sel = self._indices_seleccionados()
        paso = self.pasos[sel[-1]] if sel else (self.pasos[-1] if self.pasos else None)
        pos = self.grabacion.insertar_abrir_url_despues_de(paso, url, espera)
        self._refrescar_y_seleccionar_evento(pos)
        self.autoguardar()
        self.estado_texto("Paso «Abrir URL» insertado (con %.1f s de espera de carga)." % espera)

    # ------------------------------------------------------------------
    # Archivos
    # ------------------------------------------------------------------
    def autoguardar(self):
        if self.smoke:
            return
        try:
            self.grabacion.guardar(ULTIMA)
        except OSError as e:
            self.estado_texto("No se pudo autoguardar: %s" % e)

    def _respaldar_ultima(self):
        """Copia ultima.json a anterior.json antes de reemplazar la grabación."""
        if self.smoke or not os.path.exists(ULTIMA) or len(self.grabacion) == 0:
            return
        try:
            shutil.copyfile(ULTIMA, ANTERIOR)
        except OSError:
            pass

    def _cargar_ultima(self):
        if self.smoke or not os.path.exists(ULTIMA):
            return
        try:
            self.grabacion = ac.Grabacion.cargar(ULTIMA)
            self.estado_texto("Se cargó la última grabación (%d eventos)." % len(self.grabacion))
        except (ValueError, OSError) as e:
            self.estado_texto("No se pudo cargar la última grabación: %s" % e)

    def guardar_como(self):
        if self.estado != REPOSO or len(self.grabacion) == 0:
            return
        ruta = filedialog.asksaveasfilename(
            parent=self.root, title="Guardar grabación", initialdir=CARPETA_GRABACIONES,
            defaultextension=".json", filetypes=[("Grabaciones JSON", "*.json"), ("Todos", "*.*")])
        if not ruta:
            return
        try:
            self.grabacion.guardar(ruta)
            self.estado_texto("Guardado en %s" % ruta)
        except OSError as e:
            messagebox.showerror("Guardar", "No se pudo guardar:\n%s" % e, parent=self.root)

    def cargar_archivo(self):
        if self.estado != REPOSO:
            return
        ruta = filedialog.askopenfilename(
            parent=self.root, title="Cargar grabación", initialdir=CARPETA_GRABACIONES,
            filetypes=[("Grabaciones JSON", "*.json"), ("Todos", "*.*")])
        if not ruta:
            return
        try:
            nueva = ac.Grabacion.cargar(ruta)
        except (ValueError, OSError) as e:
            messagebox.showerror("Cargar", "No se pudo cargar la grabación:\n%s" % e, parent=self.root)
            return
        self._respaldar_ultima()
        self.grabacion = nueva
        self.refrescar_lista()
        self.autoguardar()
        self.estado_texto("Cargado %s (%d eventos, %d pasos)." % (os.path.basename(ruta), len(nueva), len(self.pasos)))

    def limpiar(self):
        if self.estado != REPOSO or len(self.grabacion) == 0:
            return
        if not messagebox.askyesno("Limpiar", "¿Borrar todos los pasos grabados?\n"
                                   "(Se conserva una copia en grabaciones/anterior.json)", parent=self.root):
            return
        self._respaldar_ultima()
        self.grabacion = ac.Grabacion()
        self.refrescar_lista()
        self.autoguardar()
        self.estado_texto("Lista vacía.")

    # ------------------------------------------------------------------
    # Atajos globales (hilo de pynput -> cola)
    # ------------------------------------------------------------------
    def _al_presionar_global(self, tecla, inyectada=False):
        nombre = TECLAS_BOT.get(ac.serializar_tecla(tecla))
        if nombre and nombre not in self._teclas_abajo:   # evita la autorepetición
            self._teclas_abajo.add(nombre)
            self._cola.put(("tecla", nombre))

    def _al_soltar_global(self, tecla, inyectada=False):
        nombre = TECLAS_BOT.get(ac.serializar_tecla(tecla))
        if nombre:
            self._teclas_abajo.discard(nombre)

    def _bombear(self):
        """Procesa en el hilo de Tk los mensajes de los demás hilos."""
        try:
            while True:
                self._manejar(self._cola.get_nowait())
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
        if self._vivo:
            self.root.after(30, self._bombear)

    def _manejar(self, msg):
        tipo = msg[0]
        if tipo == "tecla":
            self._atajo(msg[1])
        elif msg[1] != self.run_id:
            return   # mensaje de una ejecución anterior
        elif tipo == "paso":
            _, _, indice, rep, total = msg
            self._resaltar(indice)
            texto = "Ejecutando paso %d/%d" % (indice + 1, len(self.pasos))
            if total > 1:
                texto += " (repetición %d/%d)" % (rep, total)
            self.estado_texto(texto)
        elif tipo == "cuenta":
            self._mostrar_cuenta(msg[2])
        elif tipo == "fin":
            self._terminar_ejecucion(msg[2], msg[3])

    def _atajo(self, nombre):
        if nombre == "f9":
            if self.estado == REPOSO:
                self.iniciar_grabacion()
            elif self.estado in (INICIANDO, GRABANDO):
                self.detener_grabacion()
        elif nombre == "f10":
            if self.estado == REPOSO:
                self.ejecutar()
        elif nombre == "esc":
            if self.estado == EJECUTANDO:
                self.reproductor.abortar("Detenido con Esc")
                self.estado_texto("Abortando…")

    def _tick(self):
        if self.estado == GRABANDO and self.grabador is not None:
            self.estado_texto("⏺ Grabando… %d eventos (F9 para detener)" % self.grabador.num_eventos)
        if self._vivo:
            self.root.after(250, self._tick)

    # ------------------------------------------------------------------
    # Grabación
    # ------------------------------------------------------------------
    def _leer_espera_carga(self):
        try:
            valor = float(self.var_carga.get().replace(",", "."))
            if not 0 <= valor <= 120:
                raise ValueError
        except ValueError:
            raise ValueError("La espera de carga debe ser un número de 0 a 120 segundos.")
        return valor

    def iniciar_grabacion(self):
        if self.estado != REPOSO:
            return
        url = ac.normalizar_url(self.var_url.get())
        try:
            espera = self._leer_espera_carga() if url else 0.0
        except ValueError as e:
            messagebox.showwarning("Opciones no válidas", str(e), parent=self.root)
            return
        self._respaldar_ultima()
        self._url_grabacion = url or None
        self._espera_grabacion = espera
        self.grabador = grabador.Grabador(grabar_movimientos=self.var_mover.get())
        self.estado = INICIANDO
        self._token_inicio += 1
        token = self._token_inicio
        self._actualizar_controles()
        if url:
            self.estado_texto("Abriendo %s y esperando %.1f s de carga… (F9 cancela)" % (url, espera))
        else:
            self.estado_texto("Grabando en un instante… (F9 para detener)")
        self._minimizada_por_nosotros = True
        self.root.iconify()
        # los listeners arrancan tras un breve retardo para no grabar el clic en "Grabar"
        if url:
            self.root.after(RETARDO_MINIMIZAR_MS, lambda: self._abrir_url_para_grabar(token))
        else:
            self.root.after(RETARDO_MINIMIZAR_MS, lambda: self._arrancar_grabacion(token))

    def _abrir_url_para_grabar(self, token):
        if self.estado != INICIANDO or token != self._token_inicio:
            return
        try:
            webbrowser.open(self._url_grabacion)
        except Exception as e:
            self.estado_texto("No se pudo abrir la URL: %s" % e)
        self.root.after(int(self._espera_grabacion * 1000), lambda: self._arrancar_grabacion(token))

    def _arrancar_grabacion(self, token):
        if self.estado != INICIANDO or token != self._token_inicio:
            return
        self.grabador.iniciar()
        self.estado = GRABANDO
        self.estado_texto("⏺ Grabando… (F9 para detener)")

    def detener_grabacion(self):
        if self.estado == INICIANDO:   # cancelada antes de empezar
            self.estado = REPOSO
            self._token_inicio += 1
            self.grabador = None
            self._url_grabacion = None
            self._restaurar_ventana()
            self._actualizar_controles()
            self.estado_texto("Grabación cancelada.")
            return
        if self.estado != GRABANDO:
            return
        if self._url_grabacion:
            # la espera de carga y la URL pasan a ser el primer evento de la grabación
            eventos = self.grabador.detener(normalizar=False)
            eventos = ac.anteponer_abrir_url(eventos, self._url_grabacion, self._espera_grabacion)
        else:
            eventos = self.grabador.detener()
        self._url_grabacion = None
        self.grabador = None
        self.estado = REPOSO
        self.grabacion = ac.Grabacion(eventos)
        self._restaurar_ventana()
        self.refrescar_lista()
        self.autoguardar()
        self.estado_texto("Grabación detenida: %d eventos en %d pasos. Doble clic en un paso para añadir una nota."
                          % (len(eventos), len(self.pasos)))

    def detener(self):
        """Botón ⏹: detiene la grabación o aborta la ejecución."""
        if self.estado in (INICIANDO, GRABANDO):
            self.detener_grabacion()
        elif self.estado == EJECUTANDO:
            self.reproductor.abortar("Detenido con el botón")
            self.estado_texto("Abortando…")

    def _restaurar_ventana(self):
        if self._minimizada_por_nosotros:
            self._minimizada_por_nosotros = False
            self.root.deiconify()
            self.root.lift()
            try:
                self.root.focus_force()
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------
    def _leer_opciones(self):
        try:
            velocidad = float(self.var_velocidad.get().replace("×", "").replace("x", "").replace(",", ".").strip())
            if not 0.1 <= velocidad <= 10:
                raise ValueError
        except ValueError:
            raise ValueError("La velocidad debe ser un número entre 0.1 y 10 (por ejemplo 1×, 2×).")
        try:
            repeticiones = int(self.var_reps.get())
            if not 1 <= repeticiones <= 9999:
                raise ValueError
        except ValueError:
            raise ValueError("Las repeticiones deben ser un número entero de 1 a 9999.")
        try:
            cuenta = int(self.var_cuenta.get())
            if not 0 <= cuenta <= 60:
                raise ValueError
        except ValueError:
            raise ValueError("La cuenta regresiva debe ser un número entero de 0 a 60 segundos.")
        espera_carga = self._leer_espera_carga()
        return velocidad, repeticiones, cuenta, espera_carga

    def ejecutar(self):
        if self.estado != REPOSO:
            return
        if len(self.grabacion) == 0:
            self.estado_texto("No hay nada que ejecutar: graba algo primero (F9).")
            return
        try:
            velocidad, repeticiones, cuenta, espera_carga = self._leer_opciones()
        except ValueError as e:
            messagebox.showwarning("Opciones no válidas", str(e), parent=self.root)
            return
        self.estado = EJECUTANDO
        self.run_id += 1
        rid = self.run_id
        self._actualizar_controles()
        cola = self._cola
        self.reproductor = reproductor.Reproductor(
            al_paso=lambda i, rep, total: cola.put(("paso", rid, i, rep, total)),
            al_cuenta=lambda n: cola.put(("cuenta", rid, n)),
            al_fin=lambda res, msg: cola.put(("fin", rid, res, msg)))
        eventos = [dict(e) for e in self.grabacion.eventos]
        pasos = list(self.pasos)
        minimizar = self.var_minimizar.get()
        if minimizar:
            self._minimizada_por_nosotros = True
            self.root.iconify()
        self.estado_texto("Preparando la ejecución… (Esc para abortar)")
        if cuenta > 0:
            self._mostrar_cuenta(cuenta)
        retardo = RETARDO_EJECUTAR_MS if (minimizar or cuenta == 0) else 50
        url = ac.normalizar_url(self.var_url.get())
        self.root.after(retardo, lambda: self.reproductor.iniciar(
            eventos, pasos, velocidad, repeticiones, cuenta, url=url, espera_carga=espera_carga))

    def _mostrar_cuenta(self, restante):
        if restante <= 0:
            self._cerrar_cuenta()
            return
        if self._overlay is None:
            ov = tk.Toplevel(self.root)
            ov.overrideredirect(True)
            ov.attributes("-topmost", True)
            etiqueta = tk.Label(ov, font=("Segoe UI", int(22), "bold"), bg="#1f1f1f", fg="#ffffff",
                                padx=24, pady=10)
            etiqueta.pack()
            self._overlay = (ov, etiqueta)
        ov, etiqueta = self._overlay
        etiqueta.configure(text="Empieza en %d…   (Esc cancela)" % restante)
        self.estado_texto("Empieza en %d… (Esc para cancelar)" % restante)
        ov.update_idletasks()
        x = (ov.winfo_screenwidth() - ov.winfo_reqwidth()) // 2
        ov.geometry("+%d+%d" % (x, int(60 * self.escala)))

    def _cerrar_cuenta(self):
        if self._overlay is not None:
            try:
                self._overlay[0].destroy()
            except tk.TclError:
                pass
            self._overlay = None

    def _resaltar(self, indice):
        if self._item_actual is not None and self.tree.exists(self._item_actual):
            etiquetas = [t for t in self.tree.item(self._item_actual, "tags") if t != "actual"]
            self.tree.item(self._item_actual, tags=etiquetas)
        iid = str(indice)
        if self.tree.exists(iid):
            etiquetas = list(self.tree.item(iid, "tags")) + ["actual"]
            self.tree.item(iid, tags=etiquetas)
            self.tree.see(iid)
            self._item_actual = iid

    def _terminar_ejecucion(self, resultado, mensaje):
        self._cerrar_cuenta()
        self.estado = REPOSO
        self._restaurar_ventana()
        if self._item_actual is not None and self.tree.exists(self._item_actual):
            etiquetas = [t for t in self.tree.item(self._item_actual, "tags") if t != "actual"]
            self.tree.item(self._item_actual, tags=etiquetas)
        self._item_actual = None
        self._actualizar_controles()
        if resultado == "completado":
            self.estado_texto("Ejecución completada.")
        elif resultado == "abortado":
            self.estado_texto("Ejecución abortada" + (": %s." % mensaje if mensaje else "."))
        elif resultado == "vacio":
            self.estado_texto(mensaje)
        else:
            self.estado_texto("Error en la ejecución: %s" % mensaje)
            messagebox.showerror("Error", "La ejecución falló:\n%s" % mensaje, parent=self.root)

    def ejecutar_automatico(self):
        """Usado por --ejecutar: lanza la ejecución normal (con cuenta regresiva)."""
        if self.estado != REPOSO:
            return
        if len(self.grabacion) == 0:
            self.estado_texto("--ejecutar: no hay ninguna grabación cargada (graba algo primero).")
            return
        self.ejecutar()

    # ------------------------------------------------------------------
    def cerrar(self):
        self._vivo = False
        try:
            if self.estado == GRABANDO and self.grabador is not None:
                eventos = self.grabador.detener()
                self.grabacion = ac.Grabacion(eventos)
            if self.estado == EJECUTANDO and self.reproductor is not None:
                self.reproductor.abortar("Ventana cerrada")
                self.reproductor.esperar(2)
            self.autoguardar()
            self._atajos.stop()
        finally:
            self._cerrar_cuenta()
            self.root.destroy()


def _modo_smoke(app, ms=1500):
    """Prueba rápida sin tocar el ratón, el teclado ni el navegador: construye, edita y cierra."""
    ev = []
    t = 0.0
    for x, y in ((100, 100), (120, 130)):
        t += 0.05
        ev.append(ac.ev_mover(t, x, y))
    ev.append(ac.ev_clic(t + 0.1, 120, 130, "left", True))
    ev.append(ac.ev_clic(t + 0.2, 120, 130, "left", False))
    for c in "hola":
        ev.append(ac.ev_tecla(t + 3.0, c, True, ord(c.upper())))
        ev.append(ac.ev_tecla(t + 3.05, c, False, ord(c.upper())))
        t += 0.1
    app.grabacion = ac.Grabacion(ac.anteponer_abrir_url(ev, "example.com", 5))
    app.refrescar_lista()
    n = len(app.tree.get_children())
    app.aplicar_nota(0, "nota de prueba")
    assert app.tree.set("0", "nota") == "nota de prueba"
    assert app.tree.set("0", "accion") == "Abrir URL https://example.com", app.tree.set("0", "accion")
    assert n == len(app.pasos) >= 4, (n, app.pasos)
    print("SMOKE: DPI awareness=%s, pasos=%d, escala=%.2f, url=%r"
          % (DPI_ACTIVADA, n, app.escala, app.var_url.get()))
    app.root.after(ms, app.cerrar)


def principal(argv=None):
    analizador = argparse.ArgumentParser(description="Bot Copión: graba y reproduce acciones de ratón y teclado.")
    analizador.add_argument("--url", default="",
                            help="URL que se abrirá al grabar y al ejecutar (rellena el campo URL)")
    analizador.add_argument("--ejecutar", action="store_true",
                            help="ejecuta la grabación automáticamente al abrir (con la cuenta regresiva normal)")
    analizador.add_argument("--smoke", action="store_true", help="prueba de arranque: abre la ventana y se cierra sola")
    analizador.add_argument("--smoke-ms", type=int, default=1500, help=argparse.SUPPRESS)
    args = analizador.parse_args(sys.argv[1:] if argv is None else argv)
    root = tk.Tk()
    app = App(root, smoke=args.smoke, url=args.url)
    if args.smoke:
        _modo_smoke(app, args.smoke_ms)
        if args.url:
            assert app.var_url.get() == ac.normalizar_url(args.url)
    elif args.ejecutar:
        root.after(800, app.ejecutar_automatico)
    root.mainloop()
    if args.smoke:
        print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
