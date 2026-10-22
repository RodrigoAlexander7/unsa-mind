"""Falso `tesseract`: `--list-langs` y `<imagen> stdout -l <idioma>` (verifica que la imagen exista)."""

import os
import sys
from pathlib import Path

argv = sys.argv[1:]
if argv == ["--list-langs"]:
    print("List of available languages in \"/usr/share/tessdata/\" (2):\neng\nspa")
    sys.exit(0)

path = Path(argv[0])
assert path.is_file() and path.read_bytes()[:4] == b"\x89PNG", "la imagen debe existir y ser PNG"
assert argv[1] == "stdout" and argv[2] == "-l"
assert os.environ.get("OMP_THREAD_LIMIT") == "1"

mode = os.environ.get("FAKE_TESS_MODE", "ok")
if mode == "fail":
    sys.stderr.write("Error: no se pudo leer la imagen\n")
    sys.exit(1)

uid = path.parent.name.removeprefix("unsa-ocr-")  # distinto por página
print(f"Hoja {uid}\nOficio {uid}\nTÍTULO I\nArtículo 1. Texto de Tesseract ({argv[3]}).\n"
      f"Cuerpo del artículo.\nFin {uid}\nFirma {uid}")
