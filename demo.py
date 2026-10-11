# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SOYD - SOYD Sound Perfect
"""Genera una demo de musica sintetizada y la procesa con el motor envolvente.

Crea en la carpeta `demo/`:
    1_original.mp3            audio de partida (tomado del WAV sin perdidas)
    2_envolvente.mp3          mismo audio tras el realce
    1_original.wav            referencia sin perdidas
    informe_demo.txt          metricas objetivas antes/despues

Uso:  python demo.py [--preset "Concierto"] [--segundos 19.2] [--bitrate 320]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
from scipy import signal as sps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from soyd_sound_perfect import audio_io, dsp  # noqa: E402

SR = 44100
BPM = 100.0
BEAT = 60.0 / BPM
BAR = 4.0 * BEAT
A4 = 440.0
NOTAS = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
         "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}

#: Nivel de pico de cada elemento dentro de la mezcla.
NIVEL = {"kick": 0.48, "snare": 0.42, "hat": 0.22, "hat_ab": 0.16,
         "bajo": 0.26, "pad": 0.30, "lead": 0.34, "shaker": 0.13}


def nota(nombre: str, octava: int) -> float:
    return A4 * 2.0 ** ((NOTAS[nombre] + 12 * (octava - 4) - 9) / 12.0)


def _pk(sig: np.ndarray, objetivo: float) -> np.ndarray:
    p = float(np.max(np.abs(sig))) + 1e-9
    return (sig * (objetivo / p)).astype(np.float32)


def _env(n: int, ataque: float, caida: float, sr: int = SR) -> np.ndarray:
    t = np.arange(n) / sr
    return np.minimum(1.0, t / max(ataque, 1e-4)) * np.exp(-t * caida)


def kick(dur: float = 0.42) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 46.0 + 110.0 * np.exp(-t * 38.0)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.0)
    click = np.random.default_rng(11).standard_normal(n) * np.exp(-t * 320.0) * 0.25
    return _pk(y + click, NIVEL["kick"])


def snare(dur: float = 0.30) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(22)
    sos = sps.butter(2, [1400 / (SR / 2), 8500 / (SR / 2)], btype="bandpass", output="sos")
    ruido = sps.sosfilt(sos, rng.standard_normal(n)) * np.exp(-t * 20.0)
    tono = np.sin(2 * np.pi * 196.0 * t) * np.exp(-t * 32.0) * 0.55
    return _pk(ruido * 0.9 + tono, NIVEL["snare"])


def hat(dur: float = 0.12, abierto: bool = False) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(33)
    sos = sps.butter(2, 7200 / (SR / 2), btype="highpass", output="sos")
    y = sps.sosfilt(sos, rng.standard_normal(n))
    return _pk(y * np.exp(-t * (14.0 if abierto else 55.0)),
               NIVEL["hat_ab" if abierto else "hat"])


def shaker(dur: float = 0.09) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(44)
    sos = sps.butter(2, 5200 / (SR / 2), btype="highpass", output="sos")
    y = sps.sosfilt(sos, rng.standard_normal(n))
    y *= np.minimum(1.0, t / 0.004) * np.exp(-t * 45.0)
    return _pk(y, NIVEL["shaker"])


def nota_bajo(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * f * t) + 0.22 * np.sin(4 * np.pi * f * t)
    y += 0.10 * sps.sawtooth(2 * np.pi * f * t)
    return _pk(y * _env(n, 0.006, 3.2), NIVEL["bajo"])


def acorde_pad(freqs, dur: float, rng, detune: float = 0.0035) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    env = np.minimum(1.0, t / 0.45) * np.minimum(1.0, np.maximum(0.0, dur - t) / 0.6)
    out = np.zeros(n)
    for f in freqs:
        for d in (-detune, 0.0, detune):
            out += np.sin(2 * np.pi * f * (1.0 + d) * t + rng.uniform(0, 2 * np.pi))
    return _pk(out * env / (3.0 * len(freqs)), NIVEL["pad"])


def nota_lead(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = (np.sin(2 * np.pi * f * t) + 0.30 * np.sin(4 * np.pi * f * t)
         + 0.12 * np.sin(6 * np.pi * f * t))
    # pequeno vibrato para dar vida
    y = y * (1.0 + 0.06 * np.sin(2 * np.pi * 5.2 * t))
    return _pk(y * _env(n, 0.012, 4.5), NIVEL["lead"])


def crear_demo(segundos: float = 19.2, sr: int = SR):
    """Devuelve (audio estereo float32 (n,2), sr) con un loop musical sintetizado."""
    total = int(segundos * sr)
    buf_l = np.zeros(total + sr, dtype=np.float64)
    buf_r = np.zeros(total + sr, dtype=np.float64)

    acordes = {"Am": [nota("A", 3), nota("C", 4), nota("E", 4)],
               "F": [nota("F", 3), nota("A", 3), nota("C", 4)],
               "C": [nota("C", 4), nota("E", 4), nota("G", 4)],
               "G": [nota("G", 3), nota("B", 3), nota("D", 4)]}
    bajos = {"Am": nota("A", 2), "F": nota("F", 2), "C": nota("C", 3), "G": nota("G", 2)}
    melodia = [(0.0, "A", 4, 0.55), (0.6, "C", 5, 0.55), (1.2, "E", 5, 1.0),
               (2.6, "D", 5, 0.55), (3.2, "C", 5, 0.55), (3.8, "A", 4, 1.3),
               (5.0, "C", 5, 0.55), (5.6, "A", 4, 0.55), (6.2, "F", 4, 1.3),
               (7.4, "G", 4, 0.55), (8.0, "B", 4, 0.55), (8.6, "D", 5, 1.5)]
    progresion = ["Am", "F", "C", "G"]

    def add(sig: np.ndarray, pos: int, pan: float) -> None:
        """pan 0 = izquierda, 0.5 = centro, 1 = derecha (potencia constante)."""
        n = min(len(sig), len(buf_l) - pos)
        if n <= 0:
            return
        gl = float(np.cos(pan * np.pi / 2.0))
        gr = float(np.sin(pan * np.pi / 2.0))
        buf_l[pos:pos + n] += sig[:n] * gl
        buf_r[pos:pos + n] += sig[:n] * gr

    n_compases = int(np.ceil(segundos / BAR)) + 1
    for c in range(n_compases):
        p0 = int(c * BAR * sr)
        if p0 >= total:
            break
        nombre = progresion[c % 4]

        # pad estereo: dos capas ligeramente distintas y contrapaneadas
        pad_a = acorde_pad(acordes[nombre], BAR + 0.3, np.random.default_rng(100 + c), 0.0030)
        pad_b = acorde_pad(acordes[nombre], BAR + 0.3, np.random.default_rng(500 + c), 0.0055)
        add(pad_a, p0, 0.32)
        add(pad_b, p0 + int(0.008 * sr), 0.68)

        # bajo: una nota por tiempo (la ultima sube una octava de vez en cuando)
        for beat in range(4):
            f = bajos[nombre] * (2.0 if (beat == 3 and c % 2 == 1) else 1.0)
            add(nota_bajo(f, BEAT * 0.92), p0 + int(beat * BEAT * sr), 0.5)

        # bateria
        for beat in range(4):
            bp = p0 + int(beat * BEAT * sr)
            if beat in (0, 2) or (beat == 3 and c % 2 == 1):
                add(kick(), bp, 0.5)
            if beat in (1, 3):
                add(snare(), bp, 0.5)
            for k, medio in enumerate((0.0, 0.25, 0.5, 0.75)):
                pan = 0.66 if (beat * 2 + 2 * k) % 2 == 0 else 0.34
                add(hat(abierto=(medio == 0.5 and beat == 3)),
                    bp + int(medio * BEAT * sr), pan)
                if k in (1, 3):
                    add(shaker(), bp + int(medio * BEAT * sr), 0.72 if k == 1 else 0.28)

        # melodia: patron completo de 4 compases, una vez cada 4 compases
        if c % 4 == 0:
            for (off, nn, oc, dur) in melodia:
                add(nota_lead(nota(nn, oc), dur), p0 + int(off * sr), 0.56)

    audio = np.stack([buf_l[:total], buf_r[:total]], axis=1).astype(np.float32)
    if sr != SR:
        audio = dsp.resample(audio, SR, sr)
    audio = dsp._filt(audio, dsp._sos_hp(SR, 28.0, 2))
    pico = float(np.max(np.abs(audio))) + 1e-9
    audio *= (10.0 ** (-3.0 / 20.0)) / pico
    return audio.astype(np.float32), SR


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera la demo de SOYD Sound Perfect")
    ap.add_argument("--preset", default=dsp.DEFAULT_PRESET)
    ap.add_argument("--segundos", type=float, default=19.2)
    ap.add_argument("--bitrate", type=int, default=320)
    args = ap.parse_args()

    aqui = os.path.dirname(os.path.abspath(__file__))
    demo_dir = os.path.join(aqui, "demo")
    os.makedirs(demo_dir, exist_ok=True)

    print("1) Sintetizando musica de demo...")
    audio, sr = crear_demo(args.segundos)
    print(f"   {audio.shape[0] / sr:.1f} s, {sr} Hz, {audio.shape[1]} canales")

    wav_in = os.path.join(demo_dir, "1_original.wav")
    audio_io.save_wav(audio, sr, wav_in, bits=24)
    mp3_in = os.path.join(demo_dir, "1_original.mp3")
    audio_io.save_mp3(audio, sr, mp3_in, bitrate=args.bitrate)

    preset = dsp.PRESETS.get(args.preset, dsp.EnvolventeParams())
    print(f"2) Procesando con el perfil «{args.preset}»...")
    t0 = time.time()
    salida = dsp.enhance(audio, sr, preset)
    dt = max(time.time() - t0, 1e-6)
    mp3_out = os.path.join(demo_dir, "2_envolvente.mp3")
    audio_io.save_mp3(salida, sr, mp3_out, bitrate=args.bitrate)

    m_in = dsp.analyse(audio, sr)
    m_out = dsp.analyse(salida, sr)
    lineas = [
        "INFORME DE LA DEMO - SOYD Sound Perfect",
        "=" * 70,
        f"Perfil aplicado      : {args.preset}",
        f"Duracion             : {audio.shape[0] / sr:.1f} s",
        f"Tiempo de proceso    : {dt:.2f} s  ({audio.shape[0] / sr / dt:.1f}x tiempo real)",
        f"Bitrate de salida    : {args.bitrate} kbps",
        "",
        dsp.format_report("ANTES  ", m_in),
        dsp.format_report("DESPUES", m_out),
        "",
        "Energia por banda:",
    ]
    for k in m_in["bandas_pct"]:
        lineas.append(
            f"  {k:>9} Hz : {m_in['bandas_pct'][k]:5.1f} %  ->  {m_out['bandas_pct'][k]:5.1f} %")
    lineas += [
        "",
        f"Ancho estereo (side/mid): {m_in['ancho_side_sobre_mid']:.3f}  ->  "
        f"{m_out['ancho_side_sobre_mid']:.3f}",
        f"Tamano MP3 original : {audio_io.human_size(os.path.getsize(mp3_in))}",
        f"Tamano MP3 realzado : {audio_io.human_size(os.path.getsize(mp3_out))}",
        "",
        "Archivos generados en ./demo :",
        "  1_original.wav / 1_original.mp3   (entrada)",
        "  2_envolvente.mp3                  (salida realzada)",
    ]
    informe = "\n".join(lineas)
    print("\n" + informe)
    with open(os.path.join(demo_dir, "informe_demo.txt"), "w", encoding="utf-8") as fh:
        fh.write(informe + "\n")
    print(f"\nOK -> {demo_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
