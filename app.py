# SOYD Sound Perfect - realce envolvente para musica
# Copyright (C) 2026 SOYD
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""SOYD Sound Perfect - aplicacion de escritorio.

Realza musica para que suene envolvente (imagen estereo amplia, profundidad de
sala y graves solidos) y la exporta a MP3 con el bitrate que elijas.

Ejecutar:   python app.py       (o hacer doble clic en INICIAR.bat)
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from soyd_sound_perfect import audio_io, params  # noqa: E402

#: El motor de calculo (dsp) importa numpy y scipy, y scipy tarda unos 6 s en
#: cargar. Por eso NO se importa al arrancar: la ventana aparece en 2-3 s y el
#: motor se carga la primera vez que de verdad hace falta (analizar o procesar).
dsp = None


def cargar_motor():
    """Carga el motor de calculo una sola vez. Devuelve el modulo."""
    global dsp
    if dsp is None:
        from soyd_sound_perfect import dsp as modulo
        dsp = modulo
    return dsp


APP_TITULO = "SOYD Sound Perfect · realce envolvente para tu música"
PREVIEW_S = 35.0            # segundos de previsualización para escuchar
ANALISIS_S = 60.0           # segundos usados para el informe objetivo

COLOR_FONDO = "#12151c"
COLOR_PANEL = "#1b2029"
COLOR_TEXTO = "#e8ecf4"
COLOR_SUAVE = "#9aa7bd"
COLOR_ACENTO = "#4fc3f7"


class SoundPerfectApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.pedir_dpi()     # inofensivo si main() ya lo pidio antes
        self.title(APP_TITULO)
        self.geometry("1060x862")
        self.minsize(980, 760)
        self.configure(bg=COLOR_FONDO)
        self._icono()

        self.audio = None            # float32 (n, canales) cargado
        self.sr = 0
        self.ruta = ""
        self.cola: queue.Queue = queue.Queue()
        self.tarea_activa = False
        self._t0 = 0.0
        self._poll_id = None
        self.diagnostico = None
        self.diagnostico_ruta = ""
        self.vars: dict[str, tk.DoubleVar] = {}
        self.labels: dict[str, ttk.Label] = {}
        self.escalas: dict[str, ttk.Scale] = {}

        self._estilo()
        self._construir()
        self._aplicar_preset(params.DEFAULT_PRESET, registrar=False)
        self._log("Listo. Elige un archivo de música y pulsa «Escuchar mejorado» "
                  "para comparar con el original.")
        self.bind("<Control-o>", lambda _e: self.elegir_archivo())
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self._poll_id = self.after(80, self._poll)

    # ------------------------------------------------------------------ DPI
    @staticmethod
    def pedir_dpi() -> None:
        """Pide la conciencia de DPI. Debe llamarse ANTES de crear la ventana."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    # --------------------------------------------------------------- icono
    def _icono(self) -> None:
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icono.ico")
        try:
            if os.path.exists(ruta):
                self.iconbitmap(ruta)
        except Exception:
            pass

    # --------------------------------------------------------------- estilo
    def _estilo(self) -> None:
        st = ttk.Style(self)
        self.tema = "vista" if "vista" in st.theme_names() else (
            "clam" if "clam" in st.theme_names() else "default")
        st.theme_use(self.tema)
        if self.tema == "vista":
            self.paleta = {"panel": "#f2f4f7", "texto": "#1b2129", "suave": "#5b6675",
                           "acento": "#0b5fa5", "log_bg": "#ffffff", "log_fg": "#1b2129",
                           "borde": "#c9d1dc"}
        else:
            self.paleta = {"panel": "#1b2029", "texto": "#e8ecf4", "suave": "#9aa7bd",
                           "acento": "#4fc3f7", "log_bg": "#0d1016", "log_fg": "#e8ecf4",
                           "borde": "#2c3442"}
        pal = self.paleta
        self.configure(bg=pal["panel"])

        st.configure(".", font=("Segoe UI", 10))
        if self.tema != "vista":
            st.configure(".", background=pal["panel"], foreground=pal["texto"])
            st.configure("TFrame", background=pal["panel"])
            st.configure("TLabel", background=pal["panel"], foreground=pal["texto"])
            st.configure("TLabelframe", background=pal["panel"],
                         bordercolor=pal["borde"], relief="solid", borderwidth=1)
            st.configure("TCheckbutton", background=pal["panel"], foreground=pal["texto"])
        st.configure("TLabelframe.Label", foreground=pal["acento"],
                     font=("Segoe UI Semibold", 10))
        st.configure("TButton", padding=(10, 5))
        st.configure("Acento.TButton", font=("Segoe UI Semibold", 10))
        st.configure("Titulo.TLabel", font=("Segoe UI Semibold", 16),
                     foreground=pal["acento"])
        st.configure("Sub.TLabel", foreground=pal["suave"], font=("Segoe UI", 9))
        st.configure("Ayuda.TLabel", foreground=pal["suave"],
                     font=("Segoe UI", 9, "italic"))
        st.configure("Valor.TLabel", font=("Consolas", 10))

    # ----------------------------------------------------------- interfaz
    def _construir(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(5, weight=1)

        cab = ttk.Frame(self)
        cab.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        ttk.Label(cab, text="SOYD Sound Perfect", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(cab, style="Sub.TLabel",
                  text="Convierte cualquier canción en una versión más amplia, profunda y "
                       "envolvente, y guárdala en MP3 de alta calidad.").pack(anchor="w")

        # ---- 1. Archivo
        f_ar = ttk.LabelFrame(self, text=" 1 · Archivo de música ")
        f_ar.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 8))
        f_ar.columnconfigure(0, weight=1)
        self.var_ruta = tk.StringVar(value="(todavía no has elegido ningún archivo)")
        ttk.Entry(f_ar, textvariable=self.var_ruta, state="readonly").grid(
            row=0, column=0, sticky="ew", padx=(10, 6), pady=(10, 2))
        ttk.Button(f_ar, text="Elegir archivo…  (Ctrl+O)",
                   command=self.elegir_archivo).grid(row=0, column=1, padx=4, pady=(10, 2))
        ttk.Button(f_ar, text="Quitar", command=self.quitar_archivo).grid(
            row=0, column=2, padx=(4, 10), pady=(10, 2))
        self.lbl_archivo = ttk.Label(
            f_ar, style="Sub.TLabel",
            text="Compatible: MP3 · WAV · FLAC · OGG/Opus · AIFF · AU · CAF  (no hace falta ffmpeg)")
        self.lbl_archivo.grid(row=1, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 10))

        # ---- zona central
        medio = ttk.Frame(self)
        medio.grid(row=2, column=0, sticky="nsew", padx=14)
        medio.columnconfigure(0, weight=11)
        medio.columnconfigure(1, weight=9)
        medio.rowconfigure(0, weight=1)

        # perfil
        f_perf = ttk.LabelFrame(medio, text=" 2 · Perfil envolvente ")
        f_perf.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        f_perf.columnconfigure(1, weight=1)

        fila = ttk.Frame(f_perf)
        fila.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 4))
        ttk.Label(fila, text="Ajuste rápido:").pack(side="left", padx=(0, 6))
        self.var_preset = tk.StringVar(value=params.DEFAULT_PRESET)
        combo = ttk.Combobox(fila, textvariable=self.var_preset, state="readonly",
                             values=list(params.PRESETS), width=24)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>",
                   lambda _e: self._aplicar_preset(self.var_preset.get()))
        ttk.Button(fila, text="Restaurar", width=10,
                   command=lambda: self._aplicar_preset(params.DEFAULT_PRESET)).pack(
            side="left", padx=(6, 4))
        ttk.Button(fila, text="A cero", width=8,
                   command=lambda: self._aplicar_preset("Plano (referencia)")).pack(side="left")

        for i, spec in enumerate(params.SLIDER_SPECS, start=1):
            self._crear_slider(f_perf, i, spec)

        self.btn_analizar = ttk.Button(
            f_perf, text="🔍  Analizar la canción y ajustar el perfil",
            style="Acento.TButton", command=lambda: self.analizar(aplicar=True))
        self.btn_analizar.grid(row=len(params.SLIDER_SPECS) + 1, column=0, columnspan=3,
                               sticky="ew", padx=12, pady=(8, 2))

        f_nota = ttk.Frame(f_perf)
        f_nota.grid(row=len(params.SLIDER_SPECS) + 2, column=0, columnspan=3, sticky="ew",
                    padx=10, pady=(6, 10))
        self.var_ayuda = tk.StringVar(value="Pasa el ratón por un control para ver qué hace.")
        ttk.Label(f_nota, textvariable=self.var_ayuda, style="Ayuda.TLabel",
                  wraplength=520, justify="left").pack(anchor="w")

        # columna derecha
        der = ttk.Frame(medio)
        der.grid(row=0, column=1, sticky="nsew")
        der.columnconfigure(0, weight=1)
        der.rowconfigure(1, weight=1)

        f_esc = ttk.LabelFrame(der, text=" 3 · Escuchar y comparar ")
        f_esc.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        f_esc.columnconfigure(0, weight=1)
        ttk.Label(f_esc, style="Sub.TLabel",
                  text=f"Se procesan {PREVIEW_S:.0f} s desde la posición elegida.").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        fila_pos = ttk.Frame(f_esc)
        fila_pos.grid(row=1, column=0, sticky="ew", padx=10)
        fila_pos.columnconfigure(1, weight=1)
        ttk.Label(fila_pos, text="Posición").grid(row=0, column=0, sticky="w")
        self.var_pos = tk.DoubleVar(value=0.33)
        ttk.Scale(fila_pos, from_=0, to=100, variable=self.var_pos, orient="horizontal",
                  command=lambda _v: self._refrescar_pos()).grid(
            row=0, column=1, sticky="ew", padx=6)
        self.lbl_pos = ttk.Label(fila_pos, text="33 %", width=6, anchor="e",
                                 style="Valor.TLabel")
        self.lbl_pos.grid(row=0, column=2, sticky="e")

        botones = ttk.Frame(f_esc)
        botones.grid(row=2, column=0, sticky="ew", padx=10, pady=8)
        botones.columnconfigure(0, weight=1)
        botones.columnconfigure(1, weight=1)
        self.btn_original = ttk.Button(botones, text="▶  Escuchar original",
                                       command=lambda: self.escuchar(False))
        self.btn_original.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_mejorado = ttk.Button(botones, text="★  Escuchar mejorado",
                                       style="Acento.TButton",
                                       command=lambda: self.escuchar(True))
        self.btn_mejorado.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ttk.Button(botones, text="■  Detener", command=self.detener).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=(6, 0))
        ttk.Button(botones, text="▧  Medir original", command=self.medir).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=(6, 0))

        f_exp = ttk.LabelFrame(der, text=" 4 · Exportar ")
        f_exp.grid(row=1, column=0, sticky="nsew")
        f_exp.columnconfigure(1, weight=1)

        ttk.Label(f_exp, text="Calidad MP3").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        self.var_bitrate = tk.StringVar(value="320 kbps")
        ttk.Combobox(f_exp, textvariable=self.var_bitrate, state="readonly", width=14,
                     values=[f"{b} kbps" for b in audio_io.MP3_BITRATES]).grid(
            row=0, column=1, sticky="w", padx=6, pady=(10, 2))

        ttk.Label(f_exp, text="Frecuencia").grid(row=1, column=0, sticky="w",
                                                 padx=(10, 2), pady=2)
        self.var_sr = tk.StringVar(value="Original")
        ttk.Combobox(f_exp, textvariable=self.var_sr, state="readonly", width=11,
                     values=["Original", "44100 Hz", "48000 Hz"]).grid(
            row=1, column=1, sticky="w", padx=(2, 8), pady=2)

        ttk.Label(f_exp, text="Esfuerzo").grid(row=1, column=2, sticky="w",
                                               padx=(2, 2), pady=2)
        self.var_esfuerzo = tk.StringVar(value="Equilibrada")
        combo_esf = ttk.Combobox(f_exp, textvariable=self.var_esfuerzo, state="readonly",
                                 width=12, values=list(audio_io.MP3_ESFUERZOS))
        combo_esf.grid(row=1, column=3, sticky="w", padx=(2, 10), pady=2)
        combo_esf.bind("<Enter>", lambda _e: self.var_ayuda.set(
            "Esfuerzo del codificador MP3. «Equilibrada» es la recomendada: a igual "
            "bitrate el archivo pesa exactamente lo mismo y tarda la mitad que «Máxima»."))
        combo_esf.bind("<Leave>", lambda _e: self.var_ayuda.set(
            "Pasa el ratón por un control para ver qué hace."))

        self.var_igualar = tk.BooleanVar(value=True)
        ttk.Checkbutton(f_exp, text="Igualar volumen con el original (A/B justo)",
                        variable=self.var_igualar).grid(
            row=2, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 2))

        self.var_etiquetas = tk.BooleanVar(value=True)
        chk_etq = ttk.Checkbutton(f_exp, text="Conservar etiquetas y carátula",
                                  variable=self.var_etiquetas)
        chk_etq.grid(row=3, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 4))
        chk_etq.bind("<Enter>", lambda _e: self.var_ayuda.set(
            "Copia del archivo original el título, artista, álbum, año, género, "
            "número de pista y la carátula. Si no tiene título, se usa el nombre "
            "del archivo. En Opus no se copia la carátula."))
        chk_etq.bind("<Leave>", lambda _e: self.var_ayuda.set(
            "Pasa el ratón por un control para ver qué hace."))

        self.btn_exportar = ttk.Button(f_exp, text="⬇  PROCESAR Y EXPORTAR",
                                       style="Acento.TButton", command=self.exportar)
        self.btn_exportar.grid(row=4, column=0, columnspan=4, sticky="ew", padx=10, pady=(6, 4))
        ttk.Button(f_exp, text="Abrir carpeta del último archivo",
                   command=self.abrir_carpeta).grid(row=5, column=0, columnspan=4,
                                                    sticky="ew", padx=10, pady=(0, 12))
        self.ultima_salida = ""

        # ---- estado
        f_est = ttk.Frame(self)
        f_est.grid(row=3, column=0, sticky="ew", padx=14, pady=(10, 4))
        f_est.columnconfigure(0, weight=1)
        self.prg = ttk.Progressbar(f_est, mode="determinate", maximum=100)
        self.prg.grid(row=0, column=0, sticky="ew")
        self.var_estado = tk.StringVar(value="En espera.")
        ttk.Label(f_est, textvariable=self.var_estado, style="Sub.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 0))

        # ---- registro
        f_log = ttk.LabelFrame(self, text=" 5 · Actividad e informe ")
        f_log.grid(row=5, column=0, sticky="nsew", padx=14, pady=(4, 14))
        f_log.columnconfigure(0, weight=1)
        f_log.rowconfigure(0, weight=1)
        self.txt = tk.Text(f_log, height=8, wrap="word", bg=self.paleta["log_bg"],
                           fg=self.paleta["log_fg"], insertbackground=self.paleta["log_fg"],
                           relief="flat", font=("Consolas", 9), padx=8, pady=6)
        self.txt.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        barra = ttk.Scrollbar(f_log, orient="vertical", command=self.txt.yview)
        barra.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.txt.configure(yscrollcommand=barra.set, state="disabled")

    def _crear_slider(self, padre, fila: int, spec) -> None:
        clave, etiqueta, lo, hi, paso, unidad, ayuda = spec
        ttk.Label(padre, text=etiqueta).grid(row=fila, column=0, sticky="w",
                                             padx=(12, 4), pady=3)
        var = tk.DoubleVar(value=getattr(params.EnvolventeParams(), clave))
        escala = ttk.Scale(padre, from_=lo, to=hi, variable=var, orient="horizontal",
                           command=lambda _v, k=clave: self._refrescar_valor(k))
        escala.grid(row=fila, column=1, sticky="ew", padx=4, pady=3)
        et = ttk.Label(padre, text=self._formato(clave, var.get()), width=9,
                       anchor="e", style="Valor.TLabel")
        et.grid(row=fila, column=2, sticky="e", padx=(4, 12), pady=3)
        escala.bind("<Enter>", lambda _e, a=ayuda: self.var_ayuda.set(a))
        escala.bind("<Leave>", lambda _e: self.var_ayuda.set(
            "Pasa el ratón por un control para ver qué hace."))
        self.vars[clave] = var
        self.labels[clave] = et
        self.escalas[clave] = escala

    # ------------------------------------------------------------- formato
    @staticmethod
    def _paso(clave: str) -> float:
        for spec in params.SLIDER_SPECS:
            if spec[0] == clave:
                return spec[4]
        return 0.01

    def _formato(self, clave: str, valor: float) -> str:
        for spec in params.SLIDER_SPECS:
            if spec[0] == clave:
                unidad = spec[5]
                break
        else:
            unidad = ""
        if unidad == "pct":
            return f"{valor * 100:.0f} %"
        if unidad == "sec":
            return f"{valor:.2f} s"
        if unidad == "db":
            return f"{valor:+.1f} dB"
        return f"{valor:.2f}"

    def _refrescar_valor(self, clave: str) -> None:
        self.labels[clave].configure(text=self._formato(clave, self.vars[clave].get()))

    def _refrescar_pos(self) -> None:
        self.lbl_pos.configure(text=f"{self.var_pos.get():.0f} %")

    def _params(self) -> params.EnvolventeParams:
        p = params.EnvolventeParams()
        for spec in params.SLIDER_SPECS:
            clave, _et, lo, hi, paso, _u, _a = spec
            v = float(self.vars[clave].get())
            v = round(v / paso) * paso
            setattr(p, clave, float(min(max(v, lo), hi)))
        p.match_loudness = bool(self.var_igualar.get())
        return p

    def _aplicar_preset(self, nombre: str, registrar: bool = True) -> None:
        preset = params.PRESETS.get(nombre)
        if preset is None:
            return
        self.var_preset.set(nombre)
        for spec in params.SLIDER_SPECS:
            clave = spec[0]
            self.vars[clave].set(getattr(preset, clave))
            self._refrescar_valor(clave)
        self.var_igualar.set(preset.match_loudness)
        if registrar:
            self._log(f"Perfil aplicado: «{nombre}».")

    # ---------------------------------------------------------------- log
    def _log(self, texto: str) -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", f"{time.strftime('%H:%M:%S')}  {texto}\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    # -------------------------------------------------------------- tareas
    def _iniciar_tarea(self, trabajo, al_terminar, etiqueta: str) -> None:
        if self.tarea_activa:
            self._log("Hay un proceso en marcha; espera a que termine.")
            return
        self.tarea_activa = True
        self._t0 = time.time()
        self.prg.configure(value=0)
        self.var_estado.set(etiqueta)
        self._log(etiqueta)

        def runner() -> None:
            try:
                res = trabajo(lambda v, m: self.cola.put(("prog", v, m)))
                self.cola.put(("fin", res, al_terminar))
            except Exception as exc:  # noqa: BLE001
                self.cola.put(("error", exc, None))

        threading.Thread(target=runner, daemon=True).start()

    def _poll(self) -> None:
        """Recoge lo que mandan los hilos de trabajo.

        OJO: el `finally` NO es decorativo. Si un callback de finalizacion lanza
        una excepcion (por ejemplo, al analizar el resultado), sin el `finally`
        no se volveria a programar este bucle y la aplicacion se quedaria sin
        atender ninguna tarea mas hasta reiniciarla.
        """
        try:
            while True:
                msg = self.cola.get_nowait()
                tipo = msg[0]
                if tipo == "prog":
                    _t, v, m = msg
                    self.prg.configure(value=float(v) * 100.0)
                    self.var_estado.set(f"{m}  ({v * 100:.0f} %)")
                elif tipo == "fin":
                    _t, res, cb = msg
                    self.tarea_activa = False
                    self.prg.configure(value=100)
                    if cb:
                        try:
                            cb(res)
                        except Exception as exc:  # noqa: BLE001
                            self.var_estado.set("Error al terminar la tarea.")
                            self._log(f"ERROR al terminar la tarea: {exc}")
                            messagebox.showerror(
                                "SOYD Sound Perfect",
                                f"La tarea terminó, pero algo falló al mostrar el "
                                f"resultado:\n\n{exc}")
                elif tipo == "error":
                    _t, exc, _ = msg
                    self.tarea_activa = False
                    self.prg.configure(value=0)
                    self.var_estado.set("Error.")
                    self._log(f"ERROR: {exc}")
                    messagebox.showerror("SOYD Sound Perfect", f"No se pudo completar:\n\n{exc}")
        except queue.Empty:
            pass
        finally:
            # Se guarda el id para poder cancelarlo al cerrar: si no, un `after`
            # pendiente se dispara despues de destruir la ventana y Tk imprime
            # "invalid command name ..._poll" (y el proceso puede salir con error).
            self._poll_id = self.after(80, self._poll)

    # ------------------------------------------------------------- archivo
    def elegir_archivo(self) -> None:
        ruta = filedialog.askopenfilename(title="Elige un archivo de música",
                                          filetypes=audio_io.filetypes_in())
        if not ruta:
            return
        try:
            audio, sr = audio_io.load_audio(ruta)
            info = audio_io.audio_info(ruta)
        except Exception as exc:  # noqa: BLE001
            self._log(f"No se pudo leer el archivo: {exc}")
            messagebox.showerror(
                "Formato no compatible",
                "No se ha podido leer ese archivo.\n\n"
                f"Detalle: {exc}\n\n"
                "Formatos admitidos: MP3, WAV, FLAC, OGG/Opus, AIFF, AU, CAF.\n"
                "Los formatos con protección DRM o AAC/M4A no están soportados.")
            return
        self.audio, self.sr, self.ruta = audio, sr, ruta
        self.var_ruta.set(ruta)
        self.lbl_archivo.configure(
            text=f"{os.path.basename(ruta)}  ·  {info['formato']}/{info['subtipo']}  ·  "
                 f"{audio_io.human_time(info['duracion_s'])}  ·  {info['sr']} Hz  ·  "
                 f"{audio.shape[1]} canal(es)  ·  {audio_io.human_size(info['mb'])}")
        self._log(f"Cargado: {os.path.basename(ruta)} "
                  f"({audio_io.human_time(info['duracion_s'])}, {info['sr']} Hz, "
                  f"{audio.shape[1]} canal(es))")
        if audio.shape[1] == 1:
            self._log("Es mono: se convertirá en estéreo envolvente de forma automática.")
        self.diagnostico = None
        self.diagnostico_ruta = ""
        # se analiza en segundo plano para no bloquear la ventana
        self.analizar(aplicar=False)

    def quitar_archivo(self) -> None:
        self.audio = None
        self.sr = 0
        self.ruta = ""
        self.var_ruta.set("(todavía no has elegido ningún archivo)")
        self.lbl_archivo.configure(
            text="Compatible: MP3 · WAV · FLAC · OGG/Opus · AIFF · AU · CAF  "
                 "(no hace falta ffmpeg)")
        self.detener()

    def _fragmento(self, segundos: float):
        if self.audio is None:
            return None
        total = self.audio.shape[0]
        n = min(int(segundos * self.sr), total)
        if total <= n:
            ini = 0
        else:
            ini = int(np_clip(self.var_pos.get() / 100.0, 0.0, 1.0) * (total - n))
        return self.audio[ini:ini + n]

    # ------------------------------------------------------------ escuchar
    def escuchar(self, mejorado: bool) -> None:
        if self.audio is None:
            messagebox.showinfo("SOYD Sound Perfect", "Primero elige un archivo de música.")
            return
        trozo = self._fragmento(PREVIEW_S)
        if trozo is None or trozo.size == 0:
            return
        audio_io.stop_playback()
        if not mejorado:
            try:
                ruta = audio_io.write_preview(trozo, self.sr, "original")
                audio_io.play_async(ruta)
            except Exception as exc:  # noqa: BLE001
                self._log(f"No se pudo reproducir: {exc}")
                return
            self._log(f"Reproduciendo ORIGINAL ({trozo.shape[0] / self.sr:.0f} s)...")
            self.var_estado.set("Reproduciendo el original.")
            return

        p = self._params()
        seg = trozo.shape[0] / self.sr

        def trabajo(cb):
            cb(0.0, "Cargando el motor de audio...")
            cargar_motor()
            cb(0.05, f"Procesando {seg:.0f} s para la escucha...")
            y = dsp.enhance(trozo, self.sr, p, cb)
            ruta = audio_io.write_preview(y, self.sr, "mejorado")
            audio_io.play_async(ruta)
            return y

        self._iniciar_tarea(trabajo, self._fin_preview, "Preparando la escucha mejorada...")

    def _fin_preview(self, y) -> None:
        dt = time.time() - self._t0
        seg = y.shape[0] / self.sr if self.sr else 0.0
        self.var_estado.set("Reproduciendo la versión mejorada.")
        self._log(f"Reproduciendo MEJORADO · procesado en {dt:.1f} s "
                  f"({seg / dt:.1f}x tiempo real). Perfil: "
                  + ", ".join(f"{k}={v:.2f}" for k, v in
                              (("ancho", self.vars['width'].get()),
                               ("ambiente", self.vars['ambience'].get()),
                               ("reverb", self.vars['reverb_mix'].get()),
                               ("graves", self.vars['bass_db'].get()))))

    def detener(self) -> None:
        audio_io.stop_playback()
        self.var_estado.set("Reproducción detenida.")

    def medir(self, silencioso: bool = False) -> None:
        if self.audio is None:
            if not silencioso:
                messagebox.showinfo("SOYD Sound Perfect", "Primero elige un archivo de música.")
            return
        trozo = self._fragmento(ANALISIS_S)
        if trozo is None:
            return
        sr = self.sr

        def trabajo(cb):
            cb(0.1, "Cargando el motor de audio...")
            cargar_motor()
            cb(0.4, "Midiendo el original...")
            m = dsp.analyse(trozo, sr)
            cb(1.0, "Medición terminada")
            return m

        self._iniciar_tarea(
            trabajo,
            lambda m: self._log(dsp.format_report("Original", m)),
            "Midiendo el original...")

    # ------------------------------------------------- perfil automatico
    def analizar(self, aplicar: bool = False) -> None:
        """Mide la canción y, si se pide, adapta el perfil a lo que ha medido."""
        if self.audio is None:
            if aplicar:
                messagebox.showinfo("SOYD Sound Perfect", "Primero elige un archivo de música.")
            return
        audio, sr = self.audio, self.sr

        def trabajo(cb):
            cb(0.05, "Cargando el motor de audio...")
            cargar_motor()
            cb(0.25, "Analizando la canción (cresta, balance, imagen)...")
            d = dsp.analizar_material(audio, sr)
            cb(1.0, "Análisis terminado")
            return d

        etiqueta = ("Analizando y ajustando..." if aplicar else "Analizando la canción...")
        self._iniciar_tarea(trabajo, lambda d: self._fin_analisis(d, aplicar), etiqueta)

    def _fin_analisis(self, d, aplicar: bool) -> None:
        self.diagnostico = d
        self.diagnostico_ruta = self.ruta
        cargar_motor()          # ya esta cargado: no cuesta nada
        self._log(f"Análisis de la canción: {d.resumen()}")
        self.var_estado.set("Análisis terminado.")
        if not aplicar:
            return

        base_nombre = self.var_preset.get()
        p, cambios, notas = dsp.ajustar_perfil(self._params(), d)
        for campo, antes, despues, motivo in cambios:
            self._log(f"   {dsp.formato_cambio(campo, antes, despues)}"
                      f"   ·   porque {motivo}")
        for nota in notas:
            self._log(f"   Nota: {nota}")

        if not cambios:
            self._log("   El perfil elegido ya le va bien a esta canción: "
                      "no he cambiado ningún valor.")
            return

        for spec in params.SLIDER_SPECS:
            clave = spec[0]
            self.vars[clave].set(getattr(p, clave))
            self._refrescar_valor(clave)
        self._log(f"   Perfil ajustado a esta canción partiendo de «{base_nombre}». "
                  "Puedes seguir moviendo los controles a mano.")
        self.var_estado.set(f"{len(cambios)} ajuste(s) aplicados al perfil.")
        audio_io.beep()

    # ------------------------------------------------------------ exportar
    def exportar(self) -> None:
        if self.audio is None:
            messagebox.showinfo("SOYD Sound Perfect", "Primero elige un archivo de música.")
            return
        base = os.path.splitext(os.path.basename(self.ruta))[0] or "cancion"
        destino = filedialog.asksaveasfilename(
            title="Guardar la versión envolvente",
            initialdir=os.path.dirname(self.ruta) or os.getcwd(),
            initialfile=f"{base}_envolvente.mp3",
            defaultextension=".mp3",
            filetypes=[("MP3 (recomendado)", "*.mp3"), ("WAV sin pérdidas", "*.wav"),
                       ("FLAC sin pérdidas", "*.flac"), ("OGG/Opus", "*.opus")])
        if not destino:
            return

        p = self._params()
        bitrate = int(self.var_bitrate.get().split()[0])
        # OJO: todo lo que toque widgets o variables de Tkinter debe leerse AQUI,
        # en el hilo principal. El hilo de trabajo solo puede usar variables
        # normales de Python (Tkinter no admite llamadas desde otros hilos).
        esfuerzo_txt = self.var_esfuerzo.get()
        calidad = audio_io.MP3_ESFUERZOS.get(esfuerzo_txt, audio_io.DEFAULT_MP3_QUALITY)
        conservar_etiquetas = bool(self.var_etiquetas.get())
        ruta_origen = self.ruta
        sr_txt = self.var_sr.get()
        sr_out = self.sr if sr_txt == "Original" else int(sr_txt.split()[0])
        entrada = self.audio
        sr_in = self.sr
        dur = entrada.shape[0] / sr_in
        formato = os.path.splitext(destino)[1].lstrip(".").upper() or "MP3"
        detalle = (f"{formato} · {bitrate} kbps · esfuerzo {esfuerzo_txt} · "
                   f"{sr_out} Hz")

        def trabajo(cb):
            t0 = time.time()
            cb(0.0, "Cargando el motor de audio...")
            cargar_motor()
            cb(0.02, f"Realzando {audio_io.human_time(dur)} de audio...")
            # el realce ocupa el 0-86 % de la barra; la codificacion, el resto
            y = dsp.enhance(entrada, sr_in, p,
                            lambda v, m: cb(0.86 * float(v), m))
            if sr_out != sr_in:
                cb(0.86, f"Remuestreando a {sr_out} Hz...")
                y = dsp.resample(y, sr_in, sr_out)

            etiquetas = None
            avisos: list = []
            if conservar_etiquetas and ruta_origen:
                try:
                    etiquetas = audio_io.etiquetas_de_origen(ruta_origen,
                                                             titulo=base)
                except Exception as exc:  # noqa: BLE001
                    avisos.append(f"No se pudieron leer las etiquetas del "
                                  f"original: {exc}")

            cb(0.87, f"Codificando {formato}...")
            n = audio_io.save_audio(
                y, sr_out, destino, bitrate=bitrate, quality=calidad,
                etiquetas=etiquetas, avisos=avisos,
                progress=lambda f: cb(0.87 + 0.12 * float(f),
                                      f"Codificando {formato}... {f * 100:.0f} %"))
            cb(1.0, "Terminado")
            resumen = (audio_io.resumen_etiquetas(*etiquetas)
                       if etiquetas and not avisos else
                       ("sin etiquetas" if not etiquetas else "no se pudieron copiar"))
            return {"ruta": destino, "bytes": n, "audio": y, "sr": sr_out,
                    "dt": time.time() - t0, "dur": dur, "detalle": detalle,
                    "etiquetas": resumen, "avisos": avisos}

        nombre = os.path.basename(destino)
        self._iniciar_tarea(trabajo, self._fin_export, f"Procesando «{nombre}»...")

    def _fin_export(self, res) -> None:
        self.ultima_salida = res["ruta"]
        cargar_motor()          # ya esta cargado: no cuesta nada
        # el informe se calcula sobre un fragmento: analizar 4 minutos enteros
        # retrasaria varios segundos el aviso de "terminado" sin aportar nada
        y = res["audio"]
        n = min(int(ANALISIS_S * res["sr"]), y.shape[0])
        ini = max(0, (y.shape[0] - n) // 2)
        m = dsp.analyse(y[ini:ini + n], res["sr"])
        self._log(f"Listo: {res['ruta']}")
        self._log(f"   {audio_io.human_size(res['bytes'])} en "
                  f"{res['dt']:.1f} s ({res['dur'] / max(res['dt'], 1e-6):.1f}x tiempo real)  ·  "
                  f"{res['detalle']}")
        self._log(f"   Etiquetas: {res['etiquetas']}")
        for aviso in res.get("avisos", ()):
            self._log(f"   AVISO: {aviso}")
        self._log("   " + dsp.format_report("Resultado", m))
        self.var_estado.set(f"Guardado: {os.path.basename(res['ruta'])}")
        audio_io.beep()
        respuesta = messagebox.askyesno(
            "SOYD Sound Perfect",
            f"Archivo guardado:\n\n{res['ruta']}\n\n"
            f"{audio_io.human_size(res['bytes'])}\n\n"
            "¿Quieres abrir la carpeta que lo contiene?")
        if respuesta:
            self.abrir_carpeta()

    def abrir_carpeta(self) -> None:
        if not self.ultima_salida or not os.path.exists(self.ultima_salida):
            messagebox.showinfo("SOYD Sound Perfect", "Todavía no has exportado ningún archivo.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(os.path.dirname(self.ultima_salida))  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", os.path.dirname(self.ultima_salida)])
        except Exception as exc:  # noqa: BLE001
            self._log(f"No se pudo abrir la carpeta: {exc}")

    def _cerrar(self) -> None:
        # Si hay una tarea en marcha, cerrar la mata a mitad (el hilo es daemon) y
        # deja el archivo de salida truncado con el nombre final. Se avisa.
        if self.tarea_activa:
            if not messagebox.askyesno(
                    "SOYD Sound Perfect",
                    "Todavía hay un proceso en marcha.\n\n"
                    "Si cierras ahora, el archivo que se estaba guardando quedará "
                    "incompleto y habrá que borrarlo.\n\n¿Cerrar de todas formas?"):
                return
        try:
            audio_io.stop_playback()
        except Exception:
            pass
        try:                      # que no quede un temporizador vivo tras destruir
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
        except Exception:
            pass
        self.destroy()


def np_clip(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def main() -> int:
    # La conciencia de DPI hay que pedirla ANTES de crear ninguna ventana: si se
    # hace despues, la raiz ya se creo como "DPI-unaware" y en pantallas al
    # 125/150 % el tamaño y las fuentes quedan incoherentes.
    SoundPerfectApp.pedir_dpi()
    app = SoundPerfectApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
