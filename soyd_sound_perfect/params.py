# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SOYD - SOYD Sound Perfect
"""Parametros y perfiles de SOYD Sound Perfect.

Este modulo esta a proposito SEPARADO del motor (`dsp.py`) y no importa numpy ni
scipy. Asi la ventana puede abrirse en 2-3 segundos y el motor de calculo (que
tarda unos 6 s en cargar, casi todo por scipy) se carga solo cuando de verdad
hace falta: al analizar o procesar la primera cancion.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass
class EnvolventeParams:
    """Perfil de realce. Todos los valores son los que usa el motor."""

    width: float = 1.45          # 0.5 .. 2.0  (1.0 = sin cambios)
    ambience: float = 0.35       # 0.0 .. 1.0  envolvente / reflexiones
    reverb_mix: float = 0.22     # 0.0 .. 0.6  cantidad de reverb
    reverb_decay: float = 1.70   # 0.4 .. 3.5  segundos de cola
    bass_db: float = 4.5         # 0.0 .. 10   shelf de graves
    clarity_db: float = 2.0      # 0.0 .. 6    presencia (3 kHz)
    air_db: float = 2.5          # 0.0 .. 8    aire (9.5 kHz)
    output_db: float = 0.0       # -6 .. +6    ganancia de salida
    match_loudness: bool = True  # igualar volumen percibido con el original
    ceiling_db: float = -1.5     # techo de pico de muestra (dBFS), con margen MP3

    def copy(self) -> "EnvolventeParams":
        return replace(self)


PRESETS: dict[str, EnvolventeParams] = {
    "Suave": EnvolventeParams(
        width=1.20, ambience=0.18, reverb_mix=0.10, reverb_decay=1.10,
        bass_db=2.0, clarity_db=1.0, air_db=1.5,
    ),
    "Amplio (recomendado)": EnvolventeParams(
        width=1.45, ambience=0.35, reverb_mix=0.22, reverb_decay=1.70,
        bass_db=4.5, clarity_db=2.0, air_db=2.5,
    ),
    "Concierto": EnvolventeParams(
        width=1.70, ambience=0.50, reverb_mix=0.38, reverb_decay=2.80,
        bass_db=3.0, clarity_db=1.5, air_db=2.0,
    ),
    "Club": EnvolventeParams(
        width=1.30, ambience=0.30, reverb_mix=0.16, reverb_decay=1.30,
        bass_db=8.0, clarity_db=3.0, air_db=3.5,
    ),
    "Solo anchura (sin reverb)": EnvolventeParams(
        width=1.85, ambience=0.45, reverb_mix=0.0, reverb_decay=1.00,
        bass_db=0.0, clarity_db=0.0, air_db=1.0,
    ),
    "Plano (referencia)": EnvolventeParams(
        width=1.0, ambience=0.0, reverb_mix=0.0, reverb_decay=1.0,
        bass_db=0.0, clarity_db=0.0, air_db=0.0,
    ),
}

DEFAULT_PRESET = "Amplio (recomendado)"

#: (clave, etiqueta, minimo, maximo, paso, unidad, ayuda) para construir la GUI.
SLIDER_SPECS = (
    ("width", "Anchura estéreo", 0.5, 2.0, 0.01, "pct",
     "Abre la imagen entre altavoces. 100 % = igual que el original."),
    ("ambience", "Envolvente (ambiente)", 0.0, 1.0, 0.01, "pct",
     "Reflexiones laterales que te 'rodean'. No rompe la compatibilidad mono."),
    ("reverb_mix", "Profundidad (reverb)", 0.0, 0.6, 0.01, "pct",
     "Cantidad de cola de sala mezclada con la señal seca."),
    ("reverb_decay", "Tamaño de sala", 0.4, 3.5, 0.05, "sec",
     "Duración de la cola de reverberación, en segundos."),
    ("bass_db", "Graves", 0.0, 10.0, 0.1, "db",
     "Realce del bajo y el bombo, aplicado al centro para no perder pegada."),
    ("clarity_db", "Claridad (presencia)", 0.0, 6.0, 0.1, "db",
     "Realce alrededor de 3 kHz: voces e instrumentos más definidos."),
    ("air_db", "Aire (brillo)", 0.0, 8.0, 0.1, "db",
     "Realce de agudos altos: sensación de espacio y detalle."),
    ("output_db", "Volumen de salida", -6.0, 6.0, 0.1, "db",
     "Ajuste final de nivel después del realce."),
)

#: Campos que el ajuste automatico puede tocar, con su nombre legible y su unidad.
CAMPOS_AJUSTABLES = {
    "bass_db": ("Graves", "db"),
    "reverb_mix": ("Profundidad", "pct"),
    "ambience": ("Envolvente (ambiente)", "pct"),
    "width": ("Anchura estéreo", "pct"),
    "clarity_db": ("Claridad", "db"),
    "air_db": ("Aire", "db"),
}
