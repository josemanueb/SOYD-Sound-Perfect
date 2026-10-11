# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SOYD - SOYD Sound Perfect
"""Genera el icono de la aplicacion (icono.ico) a partir de codigo, sin recursos externos.

Uso:  python crear_icono.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))
LADO = 512


def _degradado(lado: int, c1=(21, 101, 192), c2=(123, 31, 162)) -> Image.Image:
    img = Image.new("RGB", (lado, lado))
    px = img.load()
    for y in range(lado):
        for x in range(lado):
            t = (x + y) / (2.0 * (lado - 1))
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return img


def _mascara_redondeada(lado: int, radio: int) -> Image.Image:
    m = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, lado - 1, lado - 1], radius=radio, fill=255)
    return m


def crear_icono() -> str:
    lado = LADO
    fondo = _degradado(lado, (18, 92, 176), (126, 34, 168))
    icono = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    icono.paste(fondo, (0, 0), _mascara_redondeada(lado, int(lado * 0.22)))
    d = ImageDraw.Draw(icono)

    blanco = (255, 255, 255, 255)
    cx, cy = lado * 0.42, lado * 0.5
    grosor = max(3, int(lado * 0.035))

    # ondas traseras (detras del altavoz, semitransparentes): sensacion envolvente
    for r in (0.135, 0.205, 0.275):
        caja2 = [cx - lado * r * 0.72, cy - lado * r * 0.72,
                 cx + lado * r * 0.72, cy + lado * r * 0.72]
        d.arc(caja2, start=122, end=238, fill=(255, 255, 255, 165), width=grosor)

    # altavoz
    caja_w, caja_h = lado * 0.075, lado * 0.20
    d.rounded_rectangle([cx - lado * 0.175, cy - caja_h / 2, cx - lado * 0.175 + caja_w,
                         cy + caja_h / 2], radius=lado * 0.02, fill=blanco)
    d.polygon([(cx - lado * 0.105, cy - lado * 0.085),
               (cx + lado * 0.02, cy - lado * 0.185),
               (cx + lado * 0.02, cy + lado * 0.185),
               (cx - lado * 0.105, cy + lado * 0.085)], fill=blanco)

    # ondas frontales
    for r in (0.135, 0.205, 0.275):
        caja = [cx - lado * r, cy - lado * r, cx + lado * r, cy + lado * r]
        d.arc(caja, start=-58, end=58, fill=blanco, width=grosor)

    destino = os.path.join(AQUI, "icono.ico")
    icono.save(destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                               (128, 128), (256, 256)])
    icono.resize((256, 256), Image.LANCZOS).save(
        os.path.join(AQUI, "icono_preview.png"))
    return destino


if __name__ == "__main__":
    print("Icono creado:", crear_icono())
