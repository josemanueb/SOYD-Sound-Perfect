# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SOYD - SOYD Sound Perfect
"""Entrada/salida de audio: leer cualquier formato habitual, escribir MP3/WAV/FLAC/Opus
y previsualizar por los altavoces sin dependencias externas (ffmpeg no hace falta).

* Lectura  : libsndfile (via `soundfile`) -> MP3, WAV, FLAC, OGG/Vorbis, Opus,
             AIFF, AU, CAF, W64...
* MP3      : codificador LAME (via `lameenc`) con bitrate seleccionable.
* Escucha  : `winsound` (API de Windows), reproduccion asincrona de WAV PCM.

AVISO IMPORTANTE SOBRE OGG/VORBIS: el codificador Vorbis de libsndfile 1.2.2 de
esta compilacion provoca un DESBORDAMIENTO DE PILA (no una excepcion: mata el
proceso) con archivos de mas de unos segundos. Por eso NUNCA se escribe Vorbis:
para .ogg/.oga/.opus se usa el codificador OPUS, que es estable y ademas da mas
calidad por bit. Opus exige 48 kHz, asi que se remuestrea cuando hace falta.
"""

from __future__ import annotations

import os
import tempfile
import time

import numpy as np
import soundfile as sf

# OJO: `resample` vive en dsp.py, que importa scipy (~6 s de carga en Windows).
# Se importa DENTRO de las funciones que lo usan, para que abrir la ventana no
# arrastre scipy. Si se importara aqui arriba, no serviria de nada el resto.

#: Formatos que podemos leer.
SUPPORTED_EXT = (".mp3", ".wav", ".flac", ".ogg", ".oga", ".opus",
                 ".aiff", ".aif", ".aifc", ".au", ".snd", ".caf", ".w64", ".rf64")

#: Bitrates MP3 ofrecidos en la interfaz.
MP3_BITRATES = (128, 160, 192, 224, 256, 320)

#: Esfuerzo del codificador LAME (0 = analiza muchisimo y tarda, 9 = rapidisimo).
#: 5 es el valor por defecto de LAME: a igual bitrate el archivo pesa EXACTAMENTE
#: lo mismo, solo cambia cuanto se esfuerza el analisis psicoacustico.
MP3_QUALITY_RAPIDA = 7
MP3_QUALITY_EQUILIBRADA = 5
MP3_QUALITY_MAXIMA = 2
DEFAULT_MP3_QUALITY = MP3_QUALITY_EQUILIBRADA

#: Etiquetas de la interfaz -> esfuerzo del codificador.
MP3_ESFUERZOS = {
    "Rápida": MP3_QUALITY_RAPIDA,
    "Equilibrada": MP3_QUALITY_EQUILIBRADA,
    "Máxima": MP3_QUALITY_MAXIMA,
}

#: Frecuencias de muestreo aceptadas por MPEG-1/2 Layer III.
MP3_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)

#: Carpeta preferida para las previsualizaciones. OJO: `tempfile.gettempdir()`
#: PUEDE lanzar una excepcion si no encuentra ningun sitio escribible (equipos
#: muy restringidos). Si eso pasara al importar el modulo, la aplicacion no
#: arrancaria, asi que se protege y se usa un plan B.
try:
    _TEMP_DIR = os.path.join(tempfile.gettempdir(), "SOYD Sound Perfect")
except Exception:  # noqa: BLE001
    _TEMP_DIR = os.path.join(os.path.expanduser("~"), "SOYD Sound Perfect temporal")


def filetypes_in() -> list[tuple[str, str]]:
    patrones = " ".join("*" + e for e in SUPPORTED_EXT)
    return [("Audio compatible", patrones), ("MP3", "*.mp3"), ("WAV", "*.wav"),
            ("FLAC", "*.flac"), ("OGG / Opus", "*.ogg *.oga *.opus"),
            ("Todos los archivos", "*.*")]


# --------------------------------------------------------------------------
# Lectura
# --------------------------------------------------------------------------


def load_audio(path: str) -> tuple[np.ndarray, int]:
    """Lee un archivo de audio -> (float32 (n, canales), sr)."""
    datos, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if datos.size == 0:
        raise ValueError("El archivo no contiene muestras de audio.")
    return np.ascontiguousarray(datos, dtype=np.float32), int(sr)


def audio_info(path: str) -> dict:
    """Informacion ligera sin cargar todo el audio."""
    info = sf.info(str(path))
    return {
        "sr": int(info.samplerate),
        "canales": int(info.channels),
        "duracion_s": float(info.duration),
        "formato": info.format,
        "subtipo": info.subtype,
        "mb": os.path.getsize(path) / 1e6,
    }


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------


def mp3_safe_rate(sr: int) -> int:
    """Devuelve la frecuencia MP3 valida mas cercana."""
    sr = int(sr)
    if sr in MP3_RATES:
        return sr
    return min(MP3_RATES, key=lambda r: abs(r - sr))


def _to_int16(x: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(x, dtype=np.float64) * 32767.0, -32768.0, 32767.0).astype("<i2")


def save_mp3(x: np.ndarray, sr: int, path: str, bitrate: int = 320,
             quality: int = DEFAULT_MP3_QUALITY, progress=None) -> int:
    """Codifica a MP3 con LAME. Devuelve el tamano en bytes.

    La codificacion se hace por bloques y se escribe segun se genera, de modo
    que `progress` recibe el avance real (0.0 -> 1.0). El resultado es byte a
    byte identico al de codificar todo de una sola vez.
    """
    import lameenc

    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    target = mp3_safe_rate(sr)
    if target != int(sr):
        from .dsp import resample          # solo aqui hace falta scipy
        x = resample(x, int(sr), target)
    enc = lameenc.Encoder()
    enc.set_bit_rate(int(bitrate))
    enc.set_in_sample_rate(int(target))
    enc.set_channels(int(x.shape[1]))
    enc.set_quality(int(quality))

    pcm = _to_int16(x)
    n = int(pcm.shape[0])
    paso = 1 << 16                     # ~1,5 s de audio por bloque
    escrito = 0
    try:
        with open(path, "wb") as fh:
            for i in range(0, n, paso):
                datos = enc.encode(pcm[i:i + paso].tobytes())
                if datos:
                    fh.write(datos)
                    escrito += len(datos)
                if progress and n:
                    progress(min(0.98, (i + paso) / float(n) * 0.98))
            cola = enc.flush()
            if cola:
                fh.write(cola)
                escrito += len(cola)
    except Exception:
        try:                           # no dejar un MP3 a medias
            os.remove(path)
        except OSError:
            pass
        raise
    if progress:
        progress(1.0)
    return escrito


def save_wav(x: np.ndarray, sr: int, path: str, bits: int = 16) -> int:
    sub = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[int(bits)]
    sf.write(str(path), np.asarray(x, dtype=np.float32), int(sr), subtype=sub)
    return os.path.getsize(path)


def save_flac(x: np.ndarray, sr: int, path: str) -> int:
    sf.write(str(path), np.asarray(x, dtype=np.float32), int(sr), subtype="PCM_24")
    return os.path.getsize(path)


#: Opus solo admite 48 kHz, asi que se remuestrea cuando haga falta.
OPUS_RATE = 48000


def save_opus(x: np.ndarray, sr: int, path: str) -> int:
    """Escribe Ogg/Opus. NUNCA usa Vorbis (ver aviso de cabecera del modulo)."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if int(sr) != OPUS_RATE:
        from .dsp import resample          # solo aqui hace falta scipy
        x = resample(x, int(sr), OPUS_RATE)
    sf.write(str(path), x, OPUS_RATE, format="OGG", subtype="OPUS")
    return os.path.getsize(path)


def save_audio(x: np.ndarray, sr: int, path: str, bitrate: int = 320,
               wav_bits: int = 16, quality: int = DEFAULT_MP3_QUALITY,
               etiquetas: tuple[dict, list] | None = None,
               avisos: list | None = None,
               progress=None) -> int:
    """Guarda segun la extension del destino (.mp3 / .wav / .flac / .opus).

    `etiquetas` es la pareja (campos, imagenes) que devuelve `etiquetas_de_origen`.
    Si se pasa `avisos` (una lista), se le anaden los problemas no fatales, como
    no haber podido escribir las etiquetas: el audio se guarda igual, pero quien
    llama puede avisar al usuario en vez de decir que todo fue bien.
    `progress` (0.0 -> 1.0) solo se reporta de forma continua para MP3; en los
    formatos sin perdidas se avisa al terminar.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mp3":
        n = save_mp3(x, sr, path, bitrate=bitrate, quality=quality,
                     progress=progress)
    elif ext == ".wav":
        n = save_wav(x, sr, path, bits=wav_bits)
    elif ext == ".flac":
        n = save_flac(x, sr, path)
    elif ext in (".ogg", ".oga", ".opus"):
        # OJO: Opus, no Vorbis (el codificador Vorbis de esta libsndfile revienta)
        n = save_opus(x, sr, path)
    else:
        raise ValueError(f"Formato de salida no soportado: {ext or '(sin extensión)'}")

    if etiquetas:
        campos, imagenes = etiquetas
        if campos or imagenes:
            try:
                escribir_etiquetas(path, campos, imagenes)
                n = os.path.getsize(path)
            except Exception as exc:  # noqa: BLE001
                # Quedarse sin etiquetas es mucho menos grave que perder el audio
                # ya escrito, pero NO se oculta: se avisa a quien pidio el guardado
                # para que no diga que las copio cuando en realidad no pudo.
                if avisos is not None:
                    avisos.append(f"No se pudieron escribir las etiquetas: {exc}")
    if progress:
        progress(1.0)
    return n


# --------------------------------------------------------------------------
# Etiquetas (metadatos) y caratula
# --------------------------------------------------------------------------

#: Campos que sabemos copiar de un formato a otro.
CAMPOS_ETIQUETA = ("title", "artist", "album", "albumartist", "date",
                   "genre", "tracknumber", "composer", "comment")

#: Campo interno -> frame ID3v2.3 equivalente.
_ID3_DE_CAMPO = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2",
    "date": "TDRC", "genre": "TCON", "tracknumber": "TRCK", "composer": "TCOM",
}
_CAMPO_DE_ID3 = {v: k for k, v in _ID3_DE_CAMPO.items()}
_CAMPO_DE_ID3["TYER"] = "date"          # etiquetas antiguas (ID3v2.3)


def titulo_desde_nombre(path: str) -> str:
    """Titulo de reserva a partir del nombre del archivo."""
    base = os.path.splitext(os.path.basename(path))[0]
    limpio = base.replace("_", " ").replace("  ", " ").strip(" -")
    return limpio or "Sin título"


def _leer_id3(tags) -> tuple[dict, list]:
    campos: dict = {}
    imagenes: list = []
    for frame in tags.values():
        fid = frame.FrameID
        if fid == "APIC":
            imagenes.append((bytes(frame.data), frame.mime or "image/jpeg",
                             frame.desc or ""))
        elif fid == "COMM":
            try:
                campos.setdefault("comment", str(frame.text[0]))
            except Exception:
                pass
        elif fid in _CAMPO_DE_ID3:
            try:
                campos.setdefault(_CAMPO_DE_ID3[fid], str(frame.text[0]))
            except Exception:
                pass
    return campos, imagenes


def leer_etiquetas(path: str) -> tuple[dict, list]:
    """Devuelve (campos, imagenes) del archivo, sin fallar si no hay etiquetas."""
    campos: dict = {}
    imagenes: list = []
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3
            try:
                campos, imagenes = _leer_id3(ID3(path))
            except Exception:
                pass
        elif ext == ".wav":
            # en WAV el ID3 va en un bloque RIFF, no al principio del archivo
            from mutagen.wave import WAVE
            try:
                fich = WAVE(path)
                if fich.tags is not None:
                    campos, imagenes = _leer_id3(fich.tags)
            except Exception:
                pass
        elif ext in (".aiff", ".aif", ".aifc"):
            from mutagen.aiff import AIFF
            try:
                fich = AIFF(path)
                if fich.tags is not None:
                    campos, imagenes = _leer_id3(fich.tags)
            except Exception:
                pass
        elif ext == ".flac":
            from mutagen.flac import FLAC
            f = FLAC(path)
            for clave, valor in (f.tags or {}).items():
                if clave.lower() in CAMPOS_ETIQUETA and valor:
                    campos.setdefault(clave.lower(), str(valor[0]))
            for pic in f.pictures:
                imagenes.append((bytes(pic.data), pic.mime or "image/jpeg",
                                 pic.desc or ""))
        elif ext in (".ogg", ".oga", ".opus"):
            import mutagen
            import base64
            fich = mutagen.File(path)
            for clave, valor in (fich.tags or {}).items():
                if clave.lower() in CAMPOS_ETIQUETA and valor:
                    campos.setdefault(clave.lower(), str(valor[0]))
                elif clave.lower() == "metadata_block_picture":   # caratula en Ogg
                    for dato in valor:
                        try:
                            imagenes.append(_imagen_desde_bloque_flac(
                                base64.b64decode(dato)))
                        except Exception:
                            pass
    except Exception:
        pass
    return campos, imagenes


def _imagen_desde_bloque_flac(datos: bytes) -> tuple[bytes, str, str]:
    """Extrae (imagen, mime, descripcion) de un bloque FLAC PICTURE."""
    import struct
    pos = 4
    mime_len = struct.unpack(">I", datos[pos:pos + 4])[0]
    pos += 4
    mime = datos[pos:pos + mime_len].decode("ascii", "ignore")
    pos += mime_len
    desc_len = struct.unpack(">I", datos[pos:pos + 4])[0]
    pos += 4
    desc = datos[pos:pos + desc_len].decode("utf-8", "ignore")
    pos += desc_len + 16          # ancho, alto, profundidad, colores
    img_len = struct.unpack(">I", datos[pos:pos + 4])[0]
    pos += 4
    return datos[pos:pos + img_len], mime, desc


def _rellenar_id3(tags, campos: dict, imagenes: list) -> None:
    from mutagen.id3 import APIC, COMM
    for campo, valor in campos.items():
        if not valor:
            continue
        if campo == "comment":
            tags.add(COMM(encoding=3, lang="spa", desc="", text=str(valor)))
        elif campo in _ID3_DE_CAMPO:
            import mutagen.id3 as id3mod
            clase = getattr(id3mod, _ID3_DE_CAMPO[campo])
            tags.add(clase(encoding=3, text=str(valor)))
    for datos, mime, desc in imagenes or []:
        if datos:
            tags.add(APIC(encoding=3, mime=mime or "image/jpeg", type=3,
                          desc=desc or "Cover", data=datos))


def escribir_etiquetas(path: str, campos: dict, imagenes: list | None = None) -> None:
    """Escribe etiquetas (y caratula) en el archivo ya generado.

    MP3/WAV/AIFF usan ID3v2.3 (la version que mejor leen Windows y los
    reproductores); FLAC y Ogg usan comentarios Vorbis.
    """
    ext = os.path.splitext(path)[1].lower()
    campos = {k: v for k, v in (campos or {}).items() if v}
    imagenes = list(imagenes or [])

    if ext == ".mp3":
        from mutagen.id3 import ID3
        try:
            tags = ID3(path)
        except Exception:
            tags = ID3()
        _rellenar_id3(tags, campos, imagenes)
        tags.save(path, v2_version=3)
        return

    if ext == ".wav":
        from mutagen.wave import WAVE
        f = WAVE(path)
        if f.tags is None:
            f.add_tags()
        _rellenar_id3(f.tags, campos, imagenes)
        f.save()
        return

    if ext in (".aiff", ".aif", ".aifc"):
        from mutagen.aiff import AIFF
        f = AIFF(path)
        if f.tags is None:
            f.add_tags()
        _rellenar_id3(f.tags, campos, imagenes)
        f.save()
        return

    if ext == ".flac":
        from mutagen.flac import FLAC, Picture
        f = FLAC(path)
        for campo, valor in campos.items():
            f[campo] = str(valor)
        for datos, mime, desc in imagenes:
            if not datos:
                continue
            pic = Picture()
            pic.type = 3
            pic.mime = mime or "image/jpeg"
            pic.desc = desc or "Cover"
            pic.data = datos
            f.add_picture(pic)
        f.save()
        return

    if ext in (".ogg", ".oga", ".opus"):
        import mutagen
        f = mutagen.File(path)
        if f is None:
            return
        if f.tags is None:
            f.add_tags()
        for campo, valor in campos.items():
            f[campo] = str(valor)
        f.save()
        return


def etiquetas_de_origen(path: str, titulo: str | None = None) -> tuple[dict, list]:
    """Etiquetas del archivo original, con titulo de reserva si no tiene."""
    campos, imagenes = leer_etiquetas(path)
    if not campos.get("title"):
        campos["title"] = titulo or titulo_desde_nombre(path)
    return campos, imagenes


def resumen_etiquetas(campos: dict, imagenes: list) -> str:
    """Texto corto para el registro de la aplicacion."""
    if not campos and not imagenes:
        return "sin etiquetas"
    partes = []
    if campos.get("title"):
        partes.append(f"«{campos['title']}»")
    if campos.get("artist"):
        partes.append(campos["artist"])
    if imagenes:
        partes.append(f"carátula {human_size(len(imagenes[0][0]))}")
    return " · ".join(partes) if partes else "etiquetas copiadas"



# --------------------------------------------------------------------------
# Reproduccion / previsualizacion (Windows)
# --------------------------------------------------------------------------


_TEMP_RESUELTO: str | None = None


def _ensure_temp_dir() -> str:
    """Devuelve una carpeta temporal ESCRIBIBLE, creandola si hace falta.

    No siempre se puede escribir en %TEMP%: equipos con politicas restrictivas,
    perfiles moviles, unidades de red o sesiones limitadas. Si se diera por hecho,
    la previsualizacion fallaria con un error confuso. Aqui se prueban varios
    sitios por orden y se recuerda el primero en el que se puede escribir de verdad.
    """
    global _TEMP_RESUELTO
    if _TEMP_RESUELTO:
        return _TEMP_RESUELTO

    candidatos = [
        _TEMP_DIR,
        os.path.join(os.path.expanduser("~"), "SOYD Sound Perfect temporal"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temporal"),
        os.getcwd(),
    ]
    for carpeta in candidatos:
        try:
            os.makedirs(carpeta, exist_ok=True)
            prueba = os.path.join(carpeta, f".prueba_{os.getpid()}")
            with open(prueba, "w", encoding="utf-8") as fh:
                fh.write("x")
            os.remove(prueba)
            _TEMP_RESUELTO = os.path.abspath(carpeta)
            return _TEMP_RESUELTO
        except Exception:  # noqa: BLE001  (se prueba el siguiente candidato)
            continue

    # Ultimo recurso: devolver la ruta estandar aunque no se haya podido probar.
    # Quien la use recibira un error claro en su propio try/except.
    _TEMP_RESUELTO = _TEMP_DIR
    return _TEMP_RESUELTO


def preview_wav_path(tag: str = "preview") -> str:
    """Ruta de un WAV temporal unico (limpia los antiguos de ese tipo)."""
    d = _ensure_temp_dir()
    for viejo in os.listdir(d):
        if viejo.startswith(tag) and viejo.endswith(".wav"):
            try:
                os.remove(os.path.join(d, viejo))
            except OSError:
                pass  # puede estar sonando todavia
    return os.path.join(d, f"{tag}_{int(time.time() * 1000) % 1000000:06d}.wav")


def write_preview(x: np.ndarray, sr: int, tag: str = "preview") -> str:
    """Escribe un WAV PCM16 temporal reproducible por winsound."""
    path = preview_wav_path(tag)
    sf.write(path, np.asarray(x, dtype=np.float32), int(sr), subtype="PCM_16")
    return path


def play_async(path: str) -> None:
    """Reproduce un WAV en segundo plano (no bloquea)."""
    import winsound
    winsound.PlaySound(str(path),
                       winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def stop_playback() -> None:
    import winsound
    try:
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass


def beep() -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def human_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
