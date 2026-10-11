# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SOYD - SOYD Sound Perfect
"""Motor DSP del realce "envolvente" para musica.

Cadena de proceso
-----------------
1. Preparacion : mono -> pseudoestereo (Haas), limpieza de subgraves y DC.
2. Graves      : shelf de graves aplicado SOLO al componente mono, para que el
                 centro (bombo, bajo) siga solido aunque se ensanche todo.
3. Anchura     : ensanchado mid/side dependiente de frecuencia; los graves se
                 mantienen practicamente centrados.
4. Ambiente    : inyeccion antifasica, retardada y filtrada de la diferencia
                 L-R. Anade sensacion envolvente y es 100 % compatible en mono
                 porque la suma L+R no cambia.
5. Profundidad : convolucion con una respuesta al impulso de sala sintetica,
                 distinta por canal (cola decorrelacionada = "envolvimiento").
6. Tono        : presencia (claridad) y aire (brillo).
7. Salida      : igualacion de volumen percibido, ganancia, limitador por GANANCIA
                 (sin recorte ni saturacion, no genera armonicos) y techo a
                 -1,5 dBFS, que es el margen medido que necesita el MP3 para que
                 su pico real entre muestras no llegue a 0 dBTP.

Todas las funciones trabajan con numpy float32 y arrays de forma (n, canales).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import gcd
from typing import Callable, Optional

import numpy as np
from scipy import signal as sps

# Los parametros y perfiles viven en params.py, que NO importa numpy ni scipy:
# asi la ventana puede abrirse sin esperar a que cargue este motor. Se importan
# aqui para que `dsp.EnvolventeParams`, `dsp.PRESETS`, etc. sigan funcionando.
from .params import (  # noqa: E402
    CAMPOS_AJUSTABLES,
    DEFAULT_PRESET,
    PRESETS,
    SLIDER_SPECS,
    EnvolventeParams,
)

EPS = 1e-12
Progress = Optional[Callable[[float, str], None]]


# --------------------------------------------------------------------------
# Utilidades basicas
# --------------------------------------------------------------------------


def _nyq(sr: float) -> float:
    return sr / 2.0


def _clamp_hz(f: float, sr: float) -> float:
    return float(np.clip(f, 10.0, _nyq(sr) * 0.92))


def as_stereo(x: np.ndarray) -> np.ndarray:
    """Devuelve float32 (n, canales>=1) sin copiar si ya lo es."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    return x


def downmix(x: np.ndarray) -> np.ndarray:
    """Mezcla cualquier numero de canales a estereo."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    n_ch = x.shape[1]
    if n_ch <= 2:
        return x
    left = x[:, 0].copy()
    right = x[:, 1].copy()
    for c in range(2, n_ch):
        g = 0.707 if c == 2 else 0.5      # central mas fuerte que los surrounds
        left += g * x[:, c]
        right += g * x[:, c]
    peak = max(float(np.max(np.abs(left))), float(np.max(np.abs(right))), EPS)
    if peak > 1.0:
        left /= peak
        right /= peak
    return np.stack([left, right], axis=1).astype(np.float32)


def peak_db(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    p = float(np.max(np.abs(x))) if x.size else 0.0
    return 20.0 * np.log10(p + EPS)


def rms_db(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    r = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    return 20.0 * np.log10(r + EPS)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(np.asarray(x, dtype=np.float64))))) if np.size(x) else 0.0


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Remuestreo polifasico de alta calidad (solo si hace falta)."""
    if int(sr_in) == int(sr_out) or x.size == 0:
        return np.asarray(x, dtype=np.float32)
    g = gcd(int(sr_in), int(sr_out))
    up, down = int(sr_out) // g, int(sr_in) // g
    y = sps.resample_poly(np.asarray(x, dtype=np.float64), up, down, axis=0)
    return y.astype(np.float32)


# --------------------------------------------------------------------------
# Filtros (biquads RBJ + Butterworth)
# --------------------------------------------------------------------------


def _sos_low_shelf(sr: float, f0: float, gain_db: float, q: float = 0.707) -> np.ndarray:
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * _clamp_hz(f0, sr) / sr
    alpha = np.sin(w0) / (2.0 * q)
    cw, sq = np.cos(w0), 2.0 * np.sqrt(A) * alpha
    b = np.array([A * ((A + 1) - (A - 1) * cw + sq),
                  2 * A * ((A - 1) - (A + 1) * cw),
                  A * ((A + 1) - (A - 1) * cw - sq)])
    a = np.array([(A + 1) + (A - 1) * cw + sq,
                  -2 * ((A - 1) + (A + 1) * cw),
                  (A + 1) + (A - 1) * cw - sq])
    return np.array([[b[0] / a[0], b[1] / a[0], b[2] / a[0], 1.0, a[1] / a[0], a[2] / a[0]]])


def _sos_high_shelf(sr: float, f0: float, gain_db: float, q: float = 0.707) -> np.ndarray:
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * _clamp_hz(f0, sr) / sr
    alpha = np.sin(w0) / (2.0 * q)
    cw, sq = np.cos(w0), 2.0 * np.sqrt(A) * alpha
    b = np.array([A * ((A + 1) + (A - 1) * cw + sq),
                  -2 * A * ((A - 1) + (A + 1) * cw),
                  A * ((A + 1) + (A - 1) * cw - sq)])
    a = np.array([(A + 1) - (A - 1) * cw + sq,
                  2 * ((A - 1) - (A + 1) * cw),
                  (A + 1) - (A - 1) * cw - sq])
    return np.array([[b[0] / a[0], b[1] / a[0], b[2] / a[0], 1.0, a[1] / a[0], a[2] / a[0]]])


def _sos_peaking(sr: float, f0: float, gain_db: float, q: float = 1.0) -> np.ndarray:
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * _clamp_hz(f0, sr) / sr
    alpha = np.sin(w0) / (2.0 * q)
    cw = np.cos(w0)
    b = np.array([1 + alpha * A, -2 * cw, 1 - alpha * A])
    a = np.array([1 + alpha / A, -2 * cw, 1 - alpha / A])
    return np.array([[b[0] / a[0], b[1] / a[0], b[2] / a[0], 1.0, a[1] / a[0], a[2] / a[0]]])


def _sos_hp(sr: float, f: float, order: int = 2) -> np.ndarray:
    return sps.butter(order, _clamp_hz(f, sr) / _nyq(sr), btype="highpass", output="sos")


def _sos_lp(sr: float, f: float, order: int = 2) -> np.ndarray:
    return sps.butter(order, _clamp_hz(f, sr) / _nyq(sr), btype="lowpass", output="sos")


def _sos_bp(sr: float, f1: float, f2: float, order: int = 2) -> np.ndarray:
    lo = _clamp_hz(min(f1, f2), sr)
    hi = max(_clamp_hz(max(f1, f2), sr), lo * 1.05)
    hi = min(hi, _nyq(sr) * 0.95)
    if hi <= lo:
        hi = min(lo * 1.5, _nyq(sr) * 0.95)
    return sps.butter(order, [lo / _nyq(sr), hi / _nyq(sr)], btype="bandpass", output="sos")


def _filt(x: np.ndarray, sos: np.ndarray, axis: int = 0) -> np.ndarray:
    """Aplica un filtro SOS. Con señal vacia devuelve la señal tal cual.

    scipy.signal.sosfilt revienta con arrays de tamaño 0 ("cannot reshape array
    of size 0"), asi que se filtra aqui, que es por donde pasan todos los filtros
    del motor.
    """
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return x
    return sps.sosfilt(sos, x, axis=axis).astype(np.float32, copy=False)


# --------------------------------------------------------------------------
# Bloques de la cadena
# --------------------------------------------------------------------------


def mono_to_stereo(x: np.ndarray, sr: int, delay_ms: float = 14.0,
                   amount: float = 0.45, lp_hz: float = 6500.0) -> np.ndarray:
    """Convierte mono en estereo envolvente manteniendo la suma L+R intacta."""
    m = np.asarray(x, dtype=np.float32)
    if m.ndim == 2:
        m = m[:, 0]
    d = max(1, int(sr * delay_ms / 1000.0))
    if d >= m.size:
        return np.stack([m, m], axis=1)
    dl = np.zeros_like(m)
    dl[d:] = m[:-d]
    dl = _filt(dl, _sos_lp(sr, lp_hz, 2))
    return np.stack([m + amount * dl, m - amount * dl], axis=1).astype(np.float32)


def add_ambience(x: np.ndarray, sr: int, amount: float = 0.35,
                 delays_ms=(11.0, 19.0, 27.0), gains=(0.55, 0.32, 0.20),
                 hp_hz: float = 260.0, lp_hz: float = 7000.0) -> np.ndarray:
    """Inyecta antifasicamente la diferencia L-R retardada.

    L' = L + a*E   y   R' = R - a*E   =>  L'+R' = L+R  (mono intacto).
    """
    x = as_stereo(x)
    if x.shape[1] < 2 or amount <= 0.0:
        return x
    diff = x[:, 0] - x[:, 1]
    diff = _filt(diff, _sos_hp(sr, hp_hz, 2))
    diff = _filt(diff, _sos_lp(sr, lp_hz, 2))
    env = np.zeros_like(diff)
    for dms, g in zip(delays_ms, gains):
        d = int(sr * dms / 1000.0)
        if 0 < d < diff.size:
            tmp = np.zeros_like(diff)
            tmp[d:] = diff[:-d]
            env += g * tmp
    g = 0.5 * amount
    return np.stack([x[:, 0] + g * env, x[:, 1] - g * env], axis=1).astype(np.float32)


def stereo_widen(x: np.ndarray, sr: int, width: float, bass_keep_hz: float = 190.0) -> np.ndarray:
    """Ensanchado mid/side; los graves se quedan centrados."""
    x = as_stereo(x)
    if x.shape[1] < 2 or abs(width - 1.0) < 1e-3:
        return x
    mid = 0.5 * (x[:, 0] + x[:, 1])
    side = 0.5 * (x[:, 0] - x[:, 1])
    side_low = _filt(side, _sos_lp(sr, bass_keep_hz, 2))
    side_high = side - side_low
    target_low = width if width < 1.0 else 1.0 + (width - 1.0) * 0.25
    side_new = side_low * target_low + side_high * width
    return np.stack([mid + side_new, mid - side_new], axis=1).astype(np.float32)


def make_room_ir_pair(sr: int, decay_s: float = 1.7, predelay_ms: float = 16.0,
                      damp_hz: float = 6000.0, hp_hz: float = 150.0,
                      seed: int = 7, common: float = 0.55) -> tuple[np.ndarray, np.ndarray]:
    """Respuesta al impulso estereo de sala: cola exponencial decorrelacionada."""
    n_tail = max(8, int(sr * float(decay_s)))
    pre = max(1, int(sr * float(predelay_ms) / 1000.0))
    t = np.arange(n_tail) / sr
    build = 1.0 - np.exp(-t / 0.0035)          # el campo difuso tarda en formarse
    e_slow = np.exp(-6.9 * t / float(decay_s))  # -60 dB al final de la cola
    e_fast = np.exp(-6.9 * t / (float(decay_s) * 0.45))  # los agudos decaen antes

    def layer(offset: int, fast_scale: float = 0.85) -> np.ndarray:
        rng = np.random.default_rng(int(seed) + offset)
        noise = rng.standard_normal(n_tail)
        low = _filt(noise, _sos_lp(sr, damp_hz, 2))
        high = noise - low
        return (low * e_slow + high * fast_scale * e_fast) * build

    shared = layer(0)
    u_l, u_r = layer(101), layer(202)
    uniq = float(np.sqrt(max(0.0, 1.0 - float(common) ** 2)))

    def finish(ir: np.ndarray) -> np.ndarray:
        ir = _filt(ir, _sos_hp(sr, hp_hz, 2))
        # reflexiones tempranas discretas y suaves
        rng = np.random.default_rng(int(seed) + 909)
        for t_ms, amp in ((0.009, 0.55), (0.017, 0.42), (0.029, 0.30), (0.043, 0.20)):
            idx = pre + int(sr * t_ms)
            if idx < ir.size:
                ir[idx] += float(rng.choice([-1.0, 1.0])) * amp * 0.06
        ir = np.concatenate([np.zeros(pre, dtype=np.float64), ir])
        e = float(np.sqrt(np.sum(ir ** 2)))
        if e > EPS:
            ir = ir / e                     # energia unitaria => conserva el nivel
        return ir.astype(np.float32)

    return finish(shared * float(common) + uniq * u_l), finish(shared * float(common) + uniq * u_r)


def convolve_chunked(x: np.ndarray, ir: np.ndarray, block: int = 1 << 20,
                     progress: Optional[Callable[[float], None]] = None) -> np.ndarray:
    """Convolucion por bloques con memoria acotada.

    Devuelve siempre la MISMA longitud que `x` (la cola que sobrepasa el final
    del audio se descarta, como es habitual al procesar un tema completo).
    """
    x = np.asarray(x, dtype=np.float32)
    ir = np.asarray(ir, dtype=np.float32)
    n = int(x.shape[0])
    out = np.zeros(n, dtype=np.float32)
    if n == 0 or ir.size == 0:
        return out
    step = max(1024, int(block))
    total = max(1, (n + step - 1) // step)
    for i, start in enumerate(range(0, n, step)):
        c = sps.fftconvolve(x[start:start + step], ir, mode="full")
        end = min(n, start + c.shape[0])
        out[start:end] += c[: end - start].astype(np.float32, copy=False)
        if progress:
            progress((i + 1) / total)
    return out


def reverb_wet(x: np.ndarray, sr: int, decay_s: float = 1.7, predelay_ms: float = 16.0,
               damp_hz: float = 6000.0, hp_hz: float = 150.0, seed: int = 7,
               progress: Optional[Callable[[float], None]] = None) -> np.ndarray:
    """Devuelve la senal 100 % humeda (nivel comparable al original)."""
    x = as_stereo(x)
    ir_l, ir_r = make_room_ir_pair(sr, decay_s=decay_s, predelay_ms=predelay_ms,
                                   damp_hz=damp_hz, hp_hz=hp_hz, seed=seed)
    if x.shape[1] < 2:
        x = np.repeat(x, 2, axis=1)
    wl = convolve_chunked(x[:, 0], ir_l, progress=(lambda f: progress(0.5 * f)) if progress else None)
    wr = convolve_chunked(x[:, 1], ir_r, progress=(lambda f: progress(0.5 + 0.5 * f)) if progress else None)
    return np.stack([wl, wr], axis=1).astype(np.float32)


#: Margen por debajo de 0 dBFS con el que se limita el pico de MUESTRA.
#: No es arbitrario: al codificar a MP3 el pico REAL (entre muestras) SUBE.
#: Medido en el peor caso de prueba: +1,18 dB. Con 1,5 dB de margen el MP3
#: decodificado se queda por debajo de 0 dBTP sin necesidad de analizar el pico
#: real del tema completo, que costaba +20 s por cancion (mas que todo el realce
#: junto) y obligaba a un interpolador de 20 taps por fase para ser preciso.
MARGEN_MP3_DB = 1.5


def limit_sample_peak(x: np.ndarray, sr: int, ceiling_db: float = -1.5,
                      ventana_ms: float = 3.0, suavizado_ms: float = 1.5) -> np.ndarray:
    """Limitador de picos: solo aplica GANANCIA, nunca deforma la onda.

    A diferencia de un recorte o de un saturador `tanh`, aqui no se generan
    armonicos: la señal se atenua solo en las zonas que se pasan del techo. La
    envolvente se ensancha con una ventana MAYOR que el suavizado posterior, de
    modo que en el pico la ganancia jamas supera la necesaria.
    """
    from scipy import ndimage as ndi

    x = as_stereo(x)
    if x.shape[0] == 0:
        return x.astype(np.float32)
    techo = 10.0 ** (float(ceiling_db) / 20.0)

    pico = np.max(np.abs(x), axis=1)     # exacto y practicamente gratis
    v = max(3, int(round(float(ventana_ms) * sr / 1000.0)) | 1)
    env = ndi.maximum_filter1d(pico, size=v, axis=0, mode="nearest")
    gan = np.minimum(1.0, techo / np.maximum(env.astype(np.float64), 1e-12))

    s = max(3, int(round(float(suavizado_ms) * sr / 1000.0)) | 1)
    s = min(s, v)                        # el suavizado nunca supera la ventana
    if s > 1:
        gan = ndi.uniform_filter1d(gan, size=s, axis=0, mode="nearest")

    y = (x * gan[:, None]).astype(np.float32)
    p = float(np.max(np.abs(y))) if y.size else 0.0
    if p > techo:                        # red de seguridad
        y = (y * (techo / p)).astype(np.float32)
    return y


def true_peak_db(x: np.ndarray, sobremuestreo: int = 4) -> float:
    """Pico REAL (entre muestras) en dBTP, interpolando 4 veces.

    Es preciso, pero caro (~5 s por minuto de audio estéreo), asi que se usa para
    COMPROBAR resultados y para informar sobre fragmentos cortos, nunca dentro de
    la cadena de proceso.
    """
    x = as_stereo(x)
    if x.shape[0] == 0:
        return float("-inf")
    up = sps.resample_poly(np.asarray(x, dtype=np.float64), sobremuestreo, 1, axis=0)
    return 20.0 * np.log10(float(np.max(np.abs(up))) + EPS)


# --------------------------------------------------------------------------
# Analisis
# --------------------------------------------------------------------------

BANDS = ((20, 120), (120, 500), (500, 2000), (2000, 6000), (6000, 16000))


def analyse(x: np.ndarray, sr: int) -> dict:
    """Metricas objetivas utiles para comparar antes/despues."""
    x = as_stereo(x).astype(np.float64)
    if x.shape[1] > 2:
        x = downmix(x).astype(np.float64)
    res: dict = {
        "canales": int(x.shape[1]),
        "duracion_s": float(x.shape[0] / sr) if sr else 0.0,
        "pico_dbfs": peak_db(x),
        "rms_dbfs": rms_db(x),
        "cresta_db": peak_db(x) - rms_db(x),
    }
    if x.shape[1] >= 2:
        l, r = x[:, 0], x[:, 1]
        if np.std(l) > EPS and np.std(r) > EPS:
            res["correlacion"] = float(np.corrcoef(l, r)[0, 1])
        else:
            res["correlacion"] = 1.0
        mid = 0.5 * (l + r)
        side = 0.5 * (l - r)
        res["ancho_side_sobre_mid"] = float(_rms(side) / (_rms(mid) + EPS))
    n = x.shape[0]
    if n > 16:
        spec = np.abs(np.fft.rfft(x, axis=0)) ** 2
        power = spec.sum(axis=1) / n
        freqs = np.fft.rfftfreq(n, 1.0 / sr)
        # El total se calcula SOLO sobre el rango que cubren las bandas: si se
        # dividiera por toda la energia hasta Nyquist, los porcentajes nunca
        # sumarian 100 % y quedarian infravalorados (ruido blanco: sumaban 72 %),
        # lo que falsearia los umbrales del perfil automatico.
        rango = (freqs >= BANDS[0][0]) & (freqs < BANDS[-1][1])
        total = float(power[rango].sum()) + EPS
        res["bandas_pct"] = {}
        for lo, hi in BANDS:
            m = (freqs >= lo) & (freqs < hi)
            res["bandas_pct"][f"{lo}-{hi}"] = float(100.0 * power[m].sum() / total)
    return res


def format_report(tag: str, m: dict) -> str:
    parts = [f"{tag}: pico {m['pico_dbfs']:.1f} dBFS",
             f"RMS {m['rms_dbfs']:.1f} dBFS"]
    if "correlacion" in m:
        corr = m["correlacion"]
        estado = "mono OK" if corr > 0.2 else "¡ojo en mono!"
        parts.append(f"correlación estéreo {corr:.2f} ({estado})")
    if "bandas_pct" in m:
        b = m["bandas_pct"]
        parts.append("balance {:.0f}/{:.0f}/{:.0f}/{:.0f} % "
                     "(subgraves/graves-medios/medios/agudos)".format(
                         b.get("20-120", 0), b.get("120-500", 0),
                         b.get("500-2000", 0),
                         b.get("2000-6000", 0) + b.get("6000-16000", 0)))
    return "  |  ".join(parts)


# --------------------------------------------------------------------------
# Analisis del material y perfil automatico
# --------------------------------------------------------------------------



@dataclass
class Diagnostico:
    """Lo que la app 've' en la cancion antes de procesarla."""

    duracion_s: float = 0.0
    cresta_db: float = 0.0
    rms_dbfs: float = -60.0
    correlacion: float = 1.0
    ancho: float = 0.0                 # energia lateral / energia central
    graves: float = 0.0                # % de energia 20-120 Hz
    medios_bajos: float = 0.0          # % 120-500 Hz
    medios: float = 0.0                # % 500-2000 Hz
    presencia: float = 0.0             # % 2000-6000 Hz
    agudos: float = 0.0                # % 6000-16000 Hz
    es_mono: bool = False
    etiquetas: tuple = ()

    @property
    def mono_efectivo(self) -> bool:
        """Mono de verdad o estereo con los dos canales practicamente iguales."""
        return self.es_mono or self.ancho < 0.02

    @property
    def tiene_cuerpo(self) -> bool:
        """Hay contenido en 120-500 Hz, asi que tiene sentido realzar los graves."""
        return self.medios_bajos >= 25.0

    def resumen(self) -> str:
        """Linea corta para el registro de la aplicacion."""
        base = (f"cresta {self.cresta_db:.1f} dB · RMS {self.rms_dbfs:.1f} dBFS · "
                f"ancho {self.ancho:.2f} · balance "
                f"{self.graves:.0f}/{self.medios_bajos:.0f}/"
                f"{self.medios:.0f}/{self.presencia + self.agudos:.0f} %")
        if self.etiquetas:
            base += "  ·  " + ", ".join(self.etiquetas)
        return base


def extracto_analisis(x: np.ndarray, sr: int, max_s: float = 90.0) -> np.ndarray:
    """Trozo representativo: principio, mitad y final, o todo si es corto."""
    x = as_stereo(x)
    n = int(x.shape[0])
    objetivo = int(max_s * sr)
    if n <= objetivo or objetivo <= 0:
        return x
    trozo = max(1, objetivo // 3)
    partes = []
    for pos in (0.02, 0.5, 0.98):
        ini = max(0, min(int(pos * n) - trozo // 2, n - trozo))
        partes.append(x[ini:ini + trozo])
    return np.concatenate(partes, axis=0)


def analizar_material(x: np.ndarray, sr: int, max_s: float = 90.0) -> Diagnostico:
    """Mide como es la cancion para poder adaptar el realce a ella.

    Todo se mide sobre un extracto representativo (principio, mitad y final), asi
    que tarda lo mismo con una cancion de 3 minutos que con una de dos horas.
    """
    x = as_stereo(x)
    d = Diagnostico(duracion_s=float(x.shape[0]) / sr if sr else 0.0)
    if x.size == 0 or sr <= 0:
        return d

    seg = extracto_analisis(x, sr, max_s)
    d.es_mono = x.shape[1] < 2
    if seg.shape[1] > 2:
        # `enhance` mezcla TODOS los canales a estereo antes de procesar; si el
        # diagnostico mirara solo los dos primeros, en un 5.1 decidiria el perfil
        # a partir de una señal distinta de la que luego va a procesar.
        seg = downmix(seg)
    d.rms_dbfs = rms_db(seg)
    d.cresta_db = peak_db(seg) - d.rms_dbfs

    if seg.shape[1] >= 2:
        izq, der = seg[:, 0].astype(np.float64), seg[:, 1].astype(np.float64)
        if np.std(izq) > EPS and np.std(der) > EPS:
            d.correlacion = float(np.corrcoef(izq, der)[0, 1])
        centro = 0.5 * (izq + der)
        lado = 0.5 * (izq - der)
        d.ancho = float(_rms(lado) / (_rms(centro) + EPS))

    # Espectro promediado por segmentos (mas estable que una FFT unica)
    freqs, psd = sps.welch(np.asarray(seg, dtype=np.float64), fs=sr,
                           nperseg=min(8192, max(256, seg.shape[0])), axis=0)
    pot = psd.sum(axis=1) if psd.ndim > 1 else psd
    # Igual que en `analyse`: el total solo cubre el rango de las bandas usadas,
    # para que los porcentajes sumen 100 % y los umbrales signifiquen algo.
    total = float(pot[(freqs >= 20.0) & (freqs < 16000.0)].sum()) + EPS

    def banda(lo: float, hi: float) -> float:
        m = (freqs >= lo) & (freqs < hi)
        return float(100.0 * pot[m].sum() / total)

    d.graves = banda(20, 120)
    d.medios_bajos = banda(120, 500)
    d.medios = banda(500, 2000)
    d.presencia = banda(2000, 6000)
    d.agudos = banda(6000, 16000)

    etiquetas = []
    if d.es_mono:
        etiquetas.append("mono")
    elif d.mono_efectivo:
        etiquetas.append("casi mono")
    elif d.ancho > 0.5:
        etiquetas.append("ya muy ancha")
    if d.cresta_db < 6.0:
        etiquetas.append("muy comprimida")
    elif d.cresta_db > 14.0:
        etiquetas.append("dinámica")
    if d.graves > 45.0:
        etiquetas.append("muy cargada de graves")
    elif d.graves < 12.0 and not d.tiene_cuerpo:
        etiquetas.append("sin contenido por abajo")
    elif d.graves < 12.0:
        etiquetas.append("con poco peso abajo")
    if d.agudos + d.presencia < 4.0:
        etiquetas.append("apagada arriba")
    elif d.presencia > 25.0:
        etiquetas.append("con mucha presencia")
    d.etiquetas = tuple(etiquetas)
    return d


def ajustar_perfil(base: EnvolventeParams, d: Diagnostico
                   ) -> tuple[EnvolventeParams, list[tuple[str, float, float, str]],
                              list[str]]:
    """Adapta un perfil al material medido.

    Los ajustes son MULTIPLICATIVOS sobre el perfil elegido, para no traicionar su
    caracter: si has puesto *Concierto*, sigue sonando a concierto, solo que con
    los graves y la reverb que admite esa cancion en concreto.

    Devuelve (perfil nuevo, cambios, notas): cada cambio es
    (campo, valor antes, valor despues, motivo) y cada nota explica algo que se ha
    decidido NO tocar.
    """
    p = replace(base)
    cambios: list[tuple[str, float, float, str]] = []
    notas: list[str] = []

    def aplicar(campo: str, factor: float, motivo: str, minimo: float,
                maximo: float) -> None:
        antes = float(getattr(p, campo))
        despues = float(min(max(antes * factor, minimo), maximo))
        if abs(despues - antes) < 0.005:
            return
        setattr(p, campo, despues)
        cambios.append((campo, antes, despues, motivo))

    # --- Graves: no reforzar lo que ya viene cargado de abajo ---------------
    if d.graves > 45.0:
        aplicar("bass_db", 0.35,
                f"la canción ya trae el {d.graves:.0f} % de su energía en graves",
                0.0, 10.0)
    elif d.graves > 32.0:
        aplicar("bass_db", 0.7,
                f"ya hay bastante grave ({d.graves:.0f} % de la energía)",
                0.0, 10.0)
    elif d.graves < 12.0 and d.tiene_cuerpo:
        aplicar("bass_db", 1.35,
                f"tiene cuerpo pero poco peso abajo ({d.graves:.0f} %)", 0.0, 10.0)
    elif d.graves < 12.0:
        notas.append(
            f"No he tocado los graves: la grabación apenas tiene contenido por "
            f"debajo de 120 Hz ({d.graves:.0f} % de la energía), así que subirlos "
            "solo añadiría barro.")

    # --- Reverb: el material comprimido no admite tanta cola ---------------
    if d.cresta_db < 5.0:
        aplicar("reverb_mix", 0.55,
                f"está muy comprimida (cresta {d.cresta_db:.1f} dB): "
                "menos cola para no embarrar",
                0.0, 0.6)
    elif d.cresta_db < 8.0:
        aplicar("reverb_mix", 0.8,
                f"bastante comprimida (cresta {d.cresta_db:.1f} dB)",
                0.0, 0.6)
    elif d.cresta_db > 14.0:
        aplicar("reverb_mix", 1.15,
                f"es dinámica (cresta {d.cresta_db:.1f} dB): admite más sala",
                0.0, 0.6)

    # --- Ambiente: si ya es ancha, envolver más desestabiliza --------------
    if d.ancho > 0.5:
        aplicar("ambience", 0.6,
                f"ya es muy ancha (ancho {d.ancho:.2f}): envolver más la desdibujaría",
                0.0, 1.0)
    elif d.mono_efectivo:
        aplicar("ambience", 1.2,
                "es prácticamente mono: hay margen para envolverla",
                0.0, 1.0)
    if d.cresta_db < 5.0:
        aplicar("ambience", 0.8, "muy comprimida: conviene no añadir más densidad",
                0.0, 1.0)

    # --- Anchura: no abrir lo que ya está abierto --------------------------
    if d.ancho > 0.6:
        aplicar("width", 0.75,
                f"la imagen ya es muy amplia (ancho {d.ancho:.2f})", 0.5, 2.0)
    elif d.ancho > 0.35:
        aplicar("width", 0.88, f"ya tiene una imagen amplia ({d.ancho:.2f})", 0.5, 2.0)
    elif d.mono_efectivo:
        notas.append(
            "La anchura se queda como está: al ser mono (o casi), la app ya genera "
            "el estéreo por sí misma y abrirlo más lo volvería inestable.")
    elif d.ancho < 0.12:
        aplicar("width", 1.12, "la imagen es casi mono: se puede abrir más", 0.5, 2.0)

    # --- Tono: ni agudos de más ni grabación apagada -----------------------
    if d.presencia > 25.0:
        aplicar("clarity_db", 0.7,
                f"ya tiene mucha presencia ({d.presencia:.0f} %)", 0.0, 6.0)
    if d.presencia + d.agudos < 4.0:
        aplicar("air_db", 1.4,
                f"suena apagada arriba ({d.presencia + d.agudos:.1f} % de energía)",
                0.0, 8.0)
    elif d.presencia + d.agudos > 18.0:
        aplicar("air_db", 0.7,
                f"ya es brillante ({d.presencia + d.agudos:.0f} % de energía)",
                0.0, 8.0)

    return p, cambios, notas


def formato_cambio(campo: str, antes: float, despues: float) -> str:
    """Texto legible de un cambio del perfil automatico."""
    etiqueta = CAMPOS_AJUSTABLES.get(campo, (campo, "num"))[0]
    unidad = CAMPOS_AJUSTABLES.get(campo, (campo, "num"))[1]
    if unidad == "pct":
        return f"{etiqueta}: {antes * 100:.0f} % → {despues * 100:.0f} %"
    if unidad == "db":
        return f"{etiqueta}: {antes:+.1f} → {despues:+.1f} dB"
    return f"{etiqueta}: {antes:.2f} → {despues:.2f}"


# --------------------------------------------------------------------------
# Cadena completa
# --------------------------------------------------------------------------


def enhance(x: np.ndarray, sr: int, p: EnvolventeParams,
            progress: Progress = None) -> np.ndarray:
    """Aplica el realce envolvente completo. Devuelve float32 (n, 2)."""

    def rep(v: float, msg: str) -> None:
        if progress:
            progress(float(np.clip(v, 0.0, 1.0)), msg)

    x = as_stereo(x)
    if x.shape[1] > 2:
        x = downmix(x)
    mono_input = x.shape[1] == 1

    if x.shape[0] == 0:            # señal vacia: no hay nada que realzar
        rep(1.0, "Nada que procesar")
        return x.astype(np.float32)

    rep(0.01, "Preparando audio...")
    if mono_input:
        x = mono_to_stereo(x, sr, amount=0.45)
    else:
        x = np.array(x, dtype=np.float32, copy=True)

    ref_rms = _rms(x)

    rep(0.05, "Limpiando subgraves y continua...")
    x = _filt(x, _sos_hp(sr, 26.0, 2))
    x -= x.mean(axis=0, keepdims=True)          # elimina continua

    if p.bass_db > 0.05:
        rep(0.12, f"Reforzando graves (+{p.bass_db:.1f} dB, centrado)...")
        mid = x.mean(axis=1)
        mid_boost = _filt(mid, _sos_low_shelf(sr, 95.0, p.bass_db, 0.8))
        delta = np.clip(mid_boost - mid, -1.5, 1.5)
        x = x + delta[:, None]

    if abs(p.width - 1.0) > 0.01:
        rep(0.22, f"Ensanchando imagen estéreo ({p.width * 100:.0f} %)")
        x = stereo_widen(x, sr, p.width)

    if p.ambience > 0.005:
        rep(0.30, f"Añadiendo envolvente/ambiente ({p.ambience * 100:.0f} %)")
        x = add_ambience(x, sr, p.ambience)

    if p.reverb_mix > 0.005:
        rep(0.36, f"Generando profundidad de sala ({p.reverb_decay:.1f} s)...")
        wet = reverb_wet(
            x, sr, decay_s=p.reverb_decay, predelay_ms=16.0, damp_hz=6000.0,
            hp_hz=150.0, seed=7,
            progress=lambda f: rep(0.36 + 0.40 * f, "Convolución de reverb..."),
        )
        mix = float(np.clip(p.reverb_mix, 0.0, 0.8))
        x = x * (1.0 - 0.15 * (mix / 0.6)) + wet * mix
    else:
        wet = None

    if p.clarity_db > 0.05:
        rep(0.82, f"Añadiendo claridad (+{p.clarity_db:.1f} dB)")
        x = _filt(x, _sos_peaking(sr, 3000.0, p.clarity_db, 0.9))

    if p.air_db > 0.05:
        rep(0.87, f"Añadiendo aire (+{p.air_db:.1f} dB)")
        x = _filt(x, _sos_high_shelf(sr, 9500.0, p.air_db, 0.7))

    rep(0.92, "Ajustando volumen y controlando picos...")
    if p.match_loudness and ref_rms > EPS:
        cur = _rms(x)
        if cur > EPS:
            gain = float(np.clip(ref_rms / cur, 10.0 ** (-6 / 20), 10.0 ** (6 / 20)))
            x = x * gain
    x = x * (10.0 ** (float(p.output_db) / 20.0))

    x = limit_sample_peak(x, sr, ceiling_db=p.ceiling_db)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    rep(0.99, f"Control de picos (techo {p.ceiling_db:.1f} dBFS)")
    rep(1.0, "Procesado terminado")
    return x
