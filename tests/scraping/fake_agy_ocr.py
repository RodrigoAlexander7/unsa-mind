"""Falso `agy --output-format json -p ...` para el OCR: verifica la imagen y responde en JSON."""

import json
import os
import re
import sys
from pathlib import Path

argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1]
path = Path(re.search(r"archivo (\S+) es", prompt).group(1))
assert path.is_file() and path.read_bytes()[:4] == b"\x89PNG", "la imagen debe existir y ser PNG"

log = os.environ.get("FAKE_AGY_LOG")
if log:
    Path(log).write_text(json.dumps({"argv": argv}), encoding="utf-8")

mode = os.environ.get("FAKE_AGY_MODE", "ok")
if mode == "503":
    print(json.dumps({"status": "FAILED", "error": "503 UNAVAILABLE"}))
elif mode == "garbage":
    print("no es json")
else:
    uid = path.parent.name.removeprefix("unsa-ocr-")  # distinto por llamada (por página)
    body = (  # bordes únicos por página, para que no se tomen como encabezados repetidos
        f"Hoja {uid}\nOficio {uid}\nTÍTULO I\nArtículo 1. Texto escaneado.\n"
        f"Cuerpo del artículo.\nFin {uid}\nFirma {uid}\n"
    )
    print(json.dumps({"status": "SUCCESS", "response": body}))
