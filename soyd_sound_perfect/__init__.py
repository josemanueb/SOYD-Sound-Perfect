"""SOYD Sound Perfect - motor de realce envolvente y entrada/salida de audio.

IMPORTANTE: aqui NO se importan los submodulos a proposito.

`dsp` arrastra numpy y scipy, y scipy tarda unos 6 segundos en cargar en Windows.
Si este paquete los importara al entrar, la ventana tardaria esos 6 segundos en
aparecer. Se importan solo cuando hacen falta:

    from soyd_sound_perfect import audio_io      # ligero
    from soyd_sound_perfect import dsp           # pesado, solo al procesar
"""

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SOYD

__all__ = ["dsp", "audio_io", "params"]
__version__ = "1.0.0"
__author__ = "SOYD"
__license__ = "GPL-3.0-or-later"
__url__ = "https://github.com/"
