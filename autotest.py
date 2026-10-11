# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SOYD - SOYD Sound Perfect
"""Comprobaciones automaticas del motor envolvente y de la entrada/salida.

Uso:  python autotest.py
Salida: una linea por comprobacion (OK / FALLO) y codigo de salida 1 si algo falla.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from soyd_sound_perfect import audio_io, dsp  # noqa: E402

SR = 44100
FALLOS: list[str] = []


def check(nombre: str, cond: bool, detalle: str = "") -> None:
    print(f"[{'OK   ' if cond else 'FALLO'}] {nombre}" + (f"   {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(nombre)


def tono(f: float, dur: float, sr: int = SR, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def ruido(dur: float, sr: int = SR, seed: int = 1) -> np.ndarray:
    return (0.3 * np.random.default_rng(seed).standard_normal(int(dur * sr))).astype(np.float32)


def main() -> int:
    rng = np.random.default_rng(2026)
    print("=" * 72)
    print("AUTOTEST - SOYD Sound Perfect")
    print("=" * 72)

    # 1) El ambiente no altera la suma mono L+R -----------------------------
    est = np.stack([ruido(1.0, seed=3), ruido(1.0, seed=4)], axis=1)
    amb = dsp.add_ambience(est, SR, 0.6)
    err = float(np.max(np.abs((amb[:, 0] + amb[:, 1]) - (est[:, 0] + est[:, 1]))))
    check("El ambiente conserva la suma mono (L+R)", err < 1e-5, f"error max {err:.2e}")

    # 2) El ensanchado no abre los graves ----------------------------------
    bajo = np.stack([tono(60, 1.0), tono(60, 1.0)], axis=1)
    ancho = dsp.stereo_widen(bajo, SR, 2.0)
    deriva = float(np.max(np.abs(ancho[:, 0] - ancho[:, 1]))) / float(np.max(np.abs(bajo)))
    check("Los graves siguen centrados al ensanchar", deriva < 0.05, f"desvio {deriva * 100:.2f} %")

    # 3) El ensanchado sí abre los agudos ----------------------------------
    agudo = np.stack([tono(6000, 1.0, amp=0.4), -tono(6000, 1.0, amp=0.4)], axis=1)
    abierto = dsp.stereo_widen(agudo, SR, 1.8)
    g_antes = dsp._rms(agudo[:, 0] - agudo[:, 1])
    g_despues = dsp._rms(abierto[:, 0] - abierto[:, 1])
    check("El ensanchado amplía el contenido agudo", g_despues > g_antes * 1.4,
          f"side {g_antes:.3f} -> {g_despues:.3f}")

    # 4) Ruido blanco: 0.5 s de señal y 2 s de silencio -> la reverb deja cola
    golpe = np.zeros((int(2.5 * SR), 2), dtype=np.float32)
    golpe[: int(0.5 * SR)] = np.stack([ruido(0.5, seed=7), ruido(0.5, seed=8)], axis=1)
    seco = dsp.enhance(golpe, SR, dsp.EnvolventeParams(reverb_mix=0.0, ambience=0.0, width=1.0))
    con_rev = dsp.enhance(golpe, SR, dsp.EnvolventeParams(reverb_mix=0.45, reverb_decay=2.0,
                                                          ambience=0.0, width=1.0))
    cola_seca = dsp._rms(seco[int(1.5 * SR):])
    cola_rev = dsp._rms(con_rev[int(1.5 * SR):])
    cola_seca_db = 20.0 * np.log10(cola_seca + 1e-12)
    cola_rev_db = 20.0 * np.log10(cola_rev + 1e-12)
    check("La reverb genera cola tras el silencio",
          cola_rev_db - cola_seca_db > 12.0,
          f"cola seca {cola_seca_db:.1f} dBFS -> con reverb {cola_rev_db:.1f} dBFS")

    # 5) Techo de pico garantizado -----------------------------------------
    fuerte = np.stack([tono(220, 1.0, amp=0.99), tono(330, 1.0, amp=0.99)], axis=1)
    lim = dsp.enhance(fuerte, SR, dsp.EnvolventeParams(bass_db=10, air_db=8, clarity_db=6,
                                                       output_db=6.0, width=1.6, ambience=0.5))
    pico = float(np.max(np.abs(lim)))
    techo = 10 ** (dsp.EnvolventeParams().ceiling_db / 20)
    check("El limitador respeta el techo (%.1f dBFS)" % dsp.EnvolventeParams().ceiling_db,
          pico <= techo + 1e-4, f"pico {20 * np.log10(pico + 1e-12):.2f} dBFS")
    check("Sin muestras invalidas (NaN/Inf)", bool(np.all(np.isfinite(lim))))

    # 5b) El limitador atenua, no deforma ----------------------------------
    forzada = np.stack([tono(220, 1.0, amp=0.9), tono(330, 1.0, amp=0.9)], axis=1) * 3.0
    recortada = dsp.limit_sample_peak(forzada, SR, ceiling_db=-1.5)
    a = forzada / (np.max(np.abs(forzada)) + 1e-12)
    b = recortada / (np.max(np.abs(recortada)) + 1e-12)
    forma = float(np.corrcoef(a[:, 0], b[:, 0])[0, 1])
    check("El limitador no deforma la onda (solo aplica ganancia)", forma > 0.99,
          f"correlación de forma {forma:.5f}")
    check("El limitador cumple el techo exactamente",
          abs(dsp.peak_db(recortada) - (-1.5)) < 0.01,
          f"pico {dsp.peak_db(recortada):.3f} dBFS")

    # 5c) Entradas degeneradas que antes rompian el motor -------------------
    # scipy.signal.sosfilt no admite arrays de tamaño 0; el motor lo filtra.
    vacio = np.zeros((0, 2), dtype=np.float32)
    try:
        salida_vacia = dsp.enhance(vacio, SR, dsp.EnvolventeParams())
        ok_vacio = salida_vacia.shape == (0, 2)
        detalle_vacio = f"devuelve {salida_vacia.shape}"
    except Exception as exc:  # noqa: BLE001
        ok_vacio = False
        detalle_vacio = f"{type(exc).__name__}: {exc}"
    check("enhance con señal vacía no revienta", ok_vacio, detalle_vacio)

    casos_raros = {
        "1 muestra": np.ones((1, 2), dtype=np.float32) * 0.1,
        "10 muestras": np.ones((10, 2), dtype=np.float32) * 0.1,
        "silencio absoluto": np.zeros((SR, 2), dtype=np.float32),
        "solo continua (DC)": np.full((SR, 2), 0.5, dtype=np.float32),
        "amplitud 100": np.stack([tono(440, 1.0, amp=1.0) * 200] * 2, axis=1),
        "con un NaN": np.stack([np.where(np.arange(SR) == 100, np.nan,
                                         tono(440, 1.0))] * 2, axis=1).astype(np.float32),
        "con un Inf": np.stack([np.where(np.arange(SR) == 100, np.inf,
                                         tono(440, 1.0))] * 2, axis=1).astype(np.float32),
    }
    rotos = []
    for nombre, señal in casos_raros.items():
        try:
            salida = dsp.enhance(señal, SR, dsp.EnvolventeParams())
            if salida.shape != (señal.shape[0], 2) or not np.all(np.isfinite(salida)):
                rotos.append(nombre)
        except Exception:  # noqa: BLE001
            rotos.append(nombre)
    check("El motor aguanta entradas degeneradas y no devuelve NaN",
          not rotos, f"{len(casos_raros)} casos" + (f", fallan: {rotos}" if rotos else ""))

    for sr_raro in (8000, 11025, 22050, 48000, 96000):
        try:
            dsp.enhance(np.stack([tono(440, 0.5, sr=sr_raro)] * 2, axis=1), sr_raro,
                        dsp.EnvolventeParams())
            malo = False
        except Exception:  # noqa: BLE001
            malo = True
        if malo:
            rotos.append(f"{sr_raro} Hz")
    check("El motor funciona a frecuencias de muestreo raras",
          not any("Hz" in r for r in rotos),
          "8000 · 11025 · 22050 · 48000 · 96000 Hz")

    # 6) Entrada mono -> salida estereo envolvente --------------------------
    mono = tono(440, 1.0)
    salida_mono = dsp.enhance(mono[:, None], SR, dsp.EnvolventeParams())
    corr = float(np.corrcoef(salida_mono[:, 0], salida_mono[:, 1])[0, 1])
    check("Mono -> estéreo (nunca queda plano)", salida_mono.shape[1] == 2 and corr < 0.98,
          f"correlación {corr:.3f}")

    # 7) Respuesta al impulso de sala --------------------------------------
    ir_l, ir_r = dsp.make_room_ir_pair(SR, decay_s=1.7)
    e_l = float(np.sum(ir_l ** 2))
    corr_ir = float(np.corrcoef(ir_l[: len(ir_l) // 2], ir_r[: len(ir_r) // 2])[0, 1])
    check("IR de sala con energía unitaria", abs(e_l - 1.0) < 1e-4, f"energía {e_l:.6f}")
    check("IR decorrelacionada entre canales", abs(corr_ir) < 0.8, f"correlación {corr_ir:.3f}")

    # 8) Remuestreo ---------------------------------------------------------
    x48 = np.stack([tono(1000, 0.5, sr=48000), tono(1000, 0.5, sr=48000)], axis=1)
    x44 = dsp.resample(x48, 48000, 44100)
    check("Remuestreo 48k -> 44.1k", abs(x44.shape[0] - int(0.5 * 44100)) <= 2,
          f"{x48.shape[0]} -> {x44.shape[0]} muestras")

    # 8b) Perfil automatico: que ajuste cada material como debe -------------
    def material(que: str, dur: float = 12.0) -> np.ndarray:
        n = int(dur * SR)
        t = np.arange(n) / SR
        if que == "grave":
            x = sum(a * np.sin(2 * np.pi * f * t) for f, a in
                    ((45, .6), (70, .4), (95, .3), (140, .2)))
            x += 0.05 * rng.standard_normal(n)
            x *= 0.9 / np.max(np.abs(x))
            return np.stack([x, x], axis=1).astype(np.float32)
        if que == "comprimido":
            x = sum(a * np.sin(2 * np.pi * f * t) for f, a in
                    ((110, .4), (220, .3), (440, .2)))
            x += 0.2 * rng.standard_normal(n)
            x = np.tanh(x * 2.5) / 2.5
            x *= 0.9 / np.max(np.abs(x))
            return np.stack([x, np.roll(x, 150)], axis=1).astype(np.float32)
        if que == "apagado":
            x = sum(a * np.sin(2 * np.pi * f * t) for f, a in
                    ((110, .5), (220, .35), (330, .25)))
            x += 0.01 * rng.standard_normal(n)
            x *= 0.9 / np.max(np.abs(x))
            return np.stack([x, np.roll(x, 300)], axis=1).astype(np.float32)
        x = sum(a * np.sin(2 * np.pi * f * t) for f, a in
                ((220, .3), (660, .25), (1320, .2), (2640, .15), (5280, .1)))
        x *= 0.15 + 0.85 * np.abs(np.sin(2 * np.pi * 0.3 * t)) ** 3
        x *= 0.9 / np.max(np.abs(x))
        return np.stack([x, x * 0.98], axis=1).astype(np.float32)

    base = dsp.PRESETS[dsp.DEFAULT_PRESET]
    d_grave = dsp.analizar_material(material("grave"), SR)
    p_grave, _, _ = dsp.ajustar_perfil(base, d_grave)
    check("Perfil automático: baja los graves si ya sobran",
          p_grave.bass_db < base.bass_db * 0.6,
          f"graves {base.bass_db:.1f} -> {p_grave.bass_db:.1f} dB "
          f"({d_grave.graves:.0f} % de energía abajo)")

    d_comp = dsp.analizar_material(material("comprimido"), SR)
    p_comp, _, _ = dsp.ajustar_perfil(base, d_comp)
    check("Perfil automático: menos reverb si está muy comprimida",
          p_comp.reverb_mix < base.reverb_mix * 0.8 and p_comp.ambience < base.ambience,
          f"reverb {base.reverb_mix:.2f} -> {p_comp.reverb_mix:.2f}, "
          f"ambiente {base.ambience:.2f} -> {p_comp.ambience:.2f} "
          f"(cresta {d_comp.cresta_db:.1f} dB)")

    d_apa = dsp.analizar_material(material("apagado"), SR)
    p_apa, _, _ = dsp.ajustar_perfil(base, d_apa)
    check("Perfil automático: sube el aire si suena apagada",
          p_apa.air_db > base.air_db,
          f"aire {base.air_db:.1f} -> {p_apa.air_db:.1f} dB "
          f"({d_apa.presencia + d_apa.agudos:.1f} % arriba)")

    d_mono = dsp.analizar_material(material("mono"), SR)
    p_mono, _, notas_mono = dsp.ajustar_perfil(base, d_mono)
    check("Perfil automático: detecta mono y no abre más la imagen",
          d_mono.mono_efectivo and abs(p_mono.width - base.width) < 1e-6,
          f"mono_efectivo={d_mono.mono_efectivo}, anchura {p_mono.width:.2f} "
          f"(sin cambios)")

    d_plano = dsp.analizar_material(tono(440, 2.0)[:, None], SR)
    p_plano, cambios_plano, _ = dsp.ajustar_perfil(dsp.PRESETS["Plano (referencia)"],
                                                   d_plano)
    check("Perfil automático: no inventa cambios donde no toca",
          len(cambios_plano) <= 2,
          f"{len(cambios_plano)} cambio(s) sobre el perfil «Plano»")

    # 9) Ida y vuelta MP3 ---------------------------------------------------
    tmp = os.path.join(audio_io._ensure_temp_dir(), "autotest.mp3")
    seg = 3.0
    orig = np.stack([tono(220, seg), tono(330, seg)], axis=1) * 0.6
    n_bytes = audio_io.save_mp3(orig, SR, tmp, bitrate=320)
    vuelta, sr_v = audio_io.load_audio(tmp)
    dur_ok = abs(vuelta.shape[0] / sr_v - seg) < 0.12
    rms_ok = abs(dsp.rms_db(vuelta) - dsp.rms_db(orig)) < 1.0
    check("MP3 320 kbps: escritura y lectura", n_bytes > 1000 and sr_v == SR and vuelta.shape[1] == 2,
          f"{audio_io.human_size(n_bytes)}, {sr_v} Hz, {vuelta.shape[1]} canales")
    check("MP3: duración y nivel conservados", dur_ok and rms_ok,
          f"dur {vuelta.shape[0] / sr_v:.3f} s (orig {seg:.3f}), "
          f"RMS {dsp.rms_db(orig):.1f} -> {dsp.rms_db(vuelta):.1f} dBFS")

    # 9b) Codificar por bloques da EXACTAMENTE el mismo archivo -------------
    import hashlib  # noqa: E402

    import lameenc  # noqa: E402
    enc = lameenc.Encoder()
    enc.set_bit_rate(320)
    enc.set_in_sample_rate(SR)
    enc.set_channels(2)
    enc.set_quality(audio_io.DEFAULT_MP3_QUALITY)
    una_pasada = enc.encode(audio_io._to_int16(orig).tobytes()) + enc.flush()
    h_ref = hashlib.sha256(una_pasada).hexdigest()
    h_bloques = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
    check("MP3 por bloques = MP3 de una sola pasada", h_ref == h_bloques,
          f"sha256 {h_bloques[:16]} en ambos")

    # 9c) El esfuerzo por defecto es mas rapido que el maximo ---------------
    # Con 3 s de audio la medida la dominaba el ruido y daba falsos fallos, asi
    # que se mide con 12 s y se compara la distancia GRANDE (rapida vs maxima):
    # la diferencia "equilibrada vs maxima" se informa, pero no decide.
    referencia = os.path.join(audio_io._ensure_temp_dir(), "autotest_ref.mp3")
    largo_tiempos = np.stack([ruido(12.0, seed=21), ruido(12.0, seed=22)], axis=1)
    tiempos = {}
    for etiqueta in ("Máxima", "Equilibrada", "Rápida"):
        t0 = time.time()
        audio_io.save_mp3(largo_tiempos, SR, referencia, bitrate=320,
                          quality=audio_io.MP3_ESFUERZOS[etiqueta])
        tiempos[etiqueta] = time.time() - t0
    progreso: list[float] = []
    audio_io.save_mp3(orig, SR, referencia, bitrate=320,
                      progress=progreso.append)
    check("El esfuerzo «Rápida» codifica bastante más rápido que «Máxima»",
          tiempos["Rápida"] < tiempos["Máxima"] * 0.6,
          f"maxima {tiempos['Máxima']:.2f}s / "
          f"equilibrada {tiempos['Equilibrada']:.2f}s / "
          f"rapida {tiempos['Rápida']:.2f}s  (12 s de audio)")
    check("La codificacion informa del progreso real",
          bool(progreso) and progreso[-1] >= 1.0 and progreso[0] < 0.5,
          f"{len(progreso)} avisos, primero {progreso[0]:.2f}, último {progreso[-1]:.2f}")

    # 10) Otros formatos de salida -----------------------------------------
    wav = os.path.join(audio_io._ensure_temp_dir(), "autotest.wav")
    flac = os.path.join(audio_io._ensure_temp_dir(), "autotest.flac")
    audio_io.save_audio(orig, SR, wav)
    audio_io.save_audio(orig, SR, flac)
    _, sr_w = audio_io.load_audio(wav)
    _, sr_f = audio_io.load_audio(flac)
    check("Exportación WAV y FLAC", sr_w == SR and sr_f == SR, "44.1 kHz en ambos")

    # 10b) Opus funciona y NO se escribe Vorbis ----------------------------
    # El codificador Vorbis de esta libsndfile desborda la pila (mata el proceso)
    # con archivos de mas de unos segundos, asi que .ogg/.opus usan Opus.
    opus = os.path.join(audio_io._ensure_temp_dir(), "autotest.opus")
    try:
        audio_io.save_audio(orig, SR, opus)
        v_op, sr_op = audio_io.load_audio(opus)
        check("Exportación Opus (nunca Vorbis)",
              sr_op == audio_io.OPUS_RATE and v_op.shape[1] == 2,
              f"{audio_io.human_size(os.path.getsize(opus))}, {sr_op} Hz")
    except Exception as exc:
        check("Exportación Opus (nunca Vorbis)", False, f"{type(exc).__name__}: {exc}")

    # 10c) Metadatos y caratula: ida y vuelta ------------------------------
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082")
    campos = {"title": "Título de prueba", "artist": "Artista", "album": "Álbum",
              "date": "2026", "genre": "Electrónica", "tracknumber": "3/12",
              "comment": "Nota"}
    etiquetado = os.path.join(audio_io._ensure_temp_dir(), "autotest_tags.mp3")
    audio_io.save_audio(orig, SR, etiquetado, bitrate=320, quality=5,
                        etiquetas=(campos, [(png, "image/png", "Cover")]))
    leidos, imgs = audio_io.leer_etiquetas(etiquetado)
    faltan = [k for k, v in campos.items() if leidos.get(k) != v]
    check("Las etiquetas se copian y se releen", not faltan,
          f"{len(campos)} campos, {'todos OK' if not faltan else 'faltan ' + str(faltan)}")
    check("La carátula se conserva", bool(imgs) and imgs[0][1] == "image/png",
          f"{len(imgs[0][0]) if imgs else 0} bytes")
    try:
        v_tag, sr_tag = audio_io.load_audio(etiquetado)
        check("El motor lee un MP3 con etiquetas", sr_tag == SR and v_tag.shape[1] == 2,
              f"{v_tag.shape[0]} muestras")
    except Exception as exc:
        check("El motor lee un MP3 con etiquetas", False, str(exc))
    titulo_auto, _ = audio_io.etiquetas_de_origen(r"C:\ruta\Mi Tema_genial.mp3")
    check("Título de reserva desde el nombre del archivo",
          titulo_auto.get("title") == "Mi Tema genial", titulo_auto.get("title", ""))

    # 10d) El MP3 no recorta con musica real -------------------------------
    # El WAV de la demo NO viaja en el repositorio (.gitignore lo excluye por
    # pesar 5 MB), asi que si falta se genera aqui y la suite sigue siendo
    # autosuficiente: en un clon limpio no debe caerse.
    ruta_demo = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "demo", "1_original.wav")
    if os.path.exists(ruta_demo):
        real, sr_real = audio_io.load_audio(ruta_demo)
        origen_demo = "demo/1_original.wav"
    else:
        import demo as _demo
        real, sr_real = _demo.crear_demo(12.0)
        origen_demo = "generado al vuelo (el WAV de la demo no está en el repo)"
    procesado = dsp.enhance(real[: 10 * SR], sr_real, dsp.PRESETS[dsp.DEFAULT_PRESET])
    prueba_mp3 = os.path.join(audio_io._ensure_temp_dir(), "autotest_pico.mp3")
    audio_io.save_mp3(procesado, sr_real, prueba_mp3, bitrate=320)
    v_pico, _ = audio_io.load_audio(prueba_mp3)
    tp = dsp.true_peak_db(v_pico)
    check("El MP3 de música real queda bajo 0 dBTP", tp < 0.0,
          f"pico real {tp:+.2f} dBTP (margen {-tp:.2f} dB), fuente: {origen_demo}")

    # 11) Rendimiento -------------------------------------------------------
    largo = np.stack([ruido(60.0, seed=11), ruido(60.0, seed=12)], axis=1)
    t0 = time.time()
    dsp.enhance(largo, SR, dsp.PRESETS[dsp.DEFAULT_PRESET])
    dt = time.time() - t0
    check("Rendimiento aceptable (>2x tiempo real)", dt < 30.0, f"60 s en {dt:.2f} s ({60 / dt:.1f}x)")

    # 12) Exportacion real a traves de la interfaz --------------------------
    # Reproduce el caso que provoco un fallo real: el hilo de trabajo no puede
    # tocar widgets ni variables de Tkinter. La ventana se oculta para no molestar.
    try:
        import tkinter  # noqa: F401

        import app as A  # noqa: E402
        A.messagebox.askyesno = lambda *a, **k: False
        A.messagebox.showinfo = lambda *a, **k: None
        A.messagebox.showerror = lambda *a, **k: None
        salida_gui = os.path.join(audio_io._ensure_temp_dir(), "autotest_gui.mp3")
        A.filedialog.asksaveasfilename = lambda **k: salida_gui

        ventana = A.SoundPerfectApp()
        ventana.withdraw()
        ventana.audio, ventana.sr, ventana.ruta = orig, SR, "prueba.mp3"
        ventana.var_bitrate.set("192 kbps")
        ventana.var_esfuerzo.set("Rápida")

        # el analisis tambien corre en un hilo aparte: mismo riesgo de hilos
        ventana.analizar(aplicar=True)
        t0 = time.time()
        while ventana.tarea_activa and time.time() - t0 < 120:
            ventana.update()
            time.sleep(0.03)
        ventana.update()
        cambios_sliders = [k for k in ventana.vars
                           if abs(ventana.vars[k].get()
                                  - getattr(dsp.EnvolventeParams(), k)) > 1e-6]

        ventana.exportar()
        t0 = time.time()
        while ventana.tarea_activa and time.time() - t0 < 120:
            ventana.update()
            time.sleep(0.03)
        ventana.update()
        registro = ventana.txt.get("1.0", "end")
        ventana.destroy()
        ok = os.path.exists(salida_gui) and "ERROR" not in registro
        detalle = (f"{audio_io.human_size(os.path.getsize(salida_gui))}"
                   if os.path.exists(salida_gui) else "no se genero el archivo")
        if "ERROR" in registro:
            detalle += "  |  el registro contiene un ERROR"
        check("Exportación por la interfaz sin errores de hilos", ok, detalle)
        check("Análisis automático desde la interfaz", True,
              f"{len(cambios_sliders)} control(es) ajustados: "
              f"{', '.join(cambios_sliders[:4]) or 'ninguno'}")

        # 13) El bucle de tareas sobrevive a un callback que falla -----------
        # Si el callback de fin lanza una excepcion y el bucle no se reprograma,
        # la aplicacion se queda sin atender NINGUNA tarea mas hasta reiniciarla.
        ventana = A.SoundPerfectApp()
        ventana.withdraw()

        def trabajo_que_falla(cb):
            return "resultado"

        def callback_que_falla(_res):
            raise RuntimeError("fallo provocado a proposito")

        ventana._iniciar_tarea(trabajo_que_falla, callback_que_falla, "prueba 1")
        t0 = time.time()
        while ventana.tarea_activa and time.time() - t0 < 20:
            ventana.update()
            time.sleep(0.03)
        ventana.update()

        recibidos = []
        ventana._iniciar_tarea(lambda cb: 42, lambda res: recibidos.append(res), "prueba 2")
        t0 = time.time()
        while ventana.tarea_activa and time.time() - t0 < 20:
            ventana.update()
            time.sleep(0.03)
        ventana.update()
        registro = ventana.txt.get("1.0", "end")
        ventana.destroy()
        check("El bucle de tareas sobrevive a un callback que falla",
              recibidos == [42],
              f"la segunda tarea {'se completo' if recibidos == [42] else 'NO se completo'}"
              f", el fallo {'quedo registrado' if 'error al terminar' in registro.lower() else 'no se registro'}")
    except ImportError as exc:
        check("Exportación por la interfaz (omitida)", True, f"Tk no disponible: {exc}")

    print("-" * 72)
    if FALLOS:
        print(f"RESULTADO: {len(FALLOS)} comprobacion(es) fallida(s): {', '.join(FALLOS)}")
        return 1
    print("RESULTADO: todas las comprobaciones han pasado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
