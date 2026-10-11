# Licencias de terceros

SOYD Sound Perfect se distribuye bajo **GPL-3.0-or-later** (ver [LICENSE](LICENSE)).

Además, **la versión portátil** (el ZIP publicado en *Releases*) incluye dentro de
la carpeta `runtime/` un intérprete de Python y varias librerías de terceros.
Sus licencias y avisos de copyright son estos:

## Componentes incluidos en la versión portátil

| Componente | Versión | Licencia | Para qué se usa |
|---|---|---|---|
| [Python](https://www.python.org/) | 3.12.14 | PSF-2.0 | Intérprete |
| [Tcl/Tk](https://www.tcl.tk/) | 8.6.12 | BSD-style | Interfaz gráfica |
| [NumPy](https://numpy.org/) | 2.3.5 | BSD-3-Clause | Cálculo con arrays |
| [SciPy](https://scipy.org/) | 1.18.1 | BSD-3-Clause | Filtros, convolución, remuestreo |
| [soundfile](https://python-soundfile.readthedocs.io/) | 0.14.0 | BSD-3-Clause | Lectura/escritura de audio |
| [libsndfile](https://libsndfile.github.io/libsndfile/) | 1.2.2 | LGPL-2.1-or-later | Motor de audio (dentro de soundfile) |
| [lameenc](https://github.com/chrisstaite/lameenc) | 1.8.4 | LGPL-3.0-or-later | Codificador MP3 |
| [LAME](https://lame.sourceforge.io/) | 3.100 | LGPL-3.0-or-later | Codificador MP3 (dentro de lameenc) |
| [mutagen](https://mutagen.readthedocs.io/) | 1.48.1 | GPL-2.0-or-later | Etiquetas ID3 y carátulas |
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU | Generar el icono (`crear_icono.py`) |
| [cffi](https://cffi.readthedocs.io/) | 2.1.1 | MIT-0 | Dependencia de soundfile |
| [pycparser](https://github.com/eliben/pycparser) | 3.11 | BSD-3-Clause | Dependencia de cffi |
| [typing_extensions](https://github.com/python/typing_extensions) | 4.16.0 | PSF-2.0 | Dependencia de Pillow |
| [pip](https://pip.pypa.io/) | 26.2.1 | MIT | Reparar el motor si hace falta |

## Dónde están los textos completos

En la versión portátil, **cada componente incluye su propio archivo de licencia**
dentro de `runtime/` (hay 56 archivos `LICENSE`/`COPYING`). Por ejemplo:

- `runtime/LICENSE.txt` — Python
- `runtime/Lib/site-packages/scipy/LICENSE.txt` — SciPy
- `runtime/Lib/site-packages/numpy/LICENSE.txt` — NumPy
- `runtime/Lib/site-packages/lameenc-1.8.4.dist-info/LICENSE` — lameenc
- `runtime/Lib/site-packages/_soundfile_data/COPYING` — libsndfile
- `runtime/Lib/site-packages/mutagen-1.48.1.dist-info/licenses/` — mutagen

Si redistribuyes la versión portátil, **conserva esos archivos**.

## Nota sobre el copyleft

Dos consecuencias prácticas de las licencias de arriba:

1. **mutagen es GPL** (versión 2 o posterior). Como la versión portátil lo
   incluye, el conjunto se distribuye bajo **GPL-3.0-or-later**, que es
   compatible con todas las demás licencias de la lista.
2. **lameenc/LAME y libsndfile son LGPL**: se pueden redistribuir junto a una
   aplicación siempre que se mantengan sus avisos y el usuario pueda sustituir
   esas librerías. Aquí van como módulos independientes (`.pyd`/`.dll`), así que
   esa condición se cumple.

Nada de esto afecta al **uso personal** de la aplicación: puedes usarla, copiarla
a tus equipos y procesar tu música sin ninguna obligación.
