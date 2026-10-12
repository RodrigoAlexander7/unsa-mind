"""Falso `agy`: lee un evento NDJSON por stdin y responde en el formato real."""

import json
import os
import sys

line = sys.stdin.readline()
event = json.loads(line)
assert event["event"] == "user"
text = event["message"]["content"][0]["text"]

log = os.environ.get("FAKE_AGY_LOG")
if log:
    with open(log, "w", encoding="utf-8") as fh:
        json.dump({"argv": sys.argv[1:], "text": text}, fh)


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


mode = os.environ.get("FAKE_AGY_MODE", "ok")
if mode == "crash":
    sys.stderr.write("boom\n")
    sys.exit(3)
if mode == "503":
    emit({"event": "result", "result": {"status": "FAILED", "error": "503 UNAVAILABLE"}})
    sys.exit(0)

emit({"event": "init", "init": {"model": "x"}})
if mode == "nodeltas":
    pass
else:
    for part in ("hola ", "mundo"):
        emit(
            {
                "event": "step_update",
                "step_update": {
                    "step_type": "agent_response",
                    "state": "ACTIVE",
                    "text_delta": part,
                },
            }
        )
emit({"event": "result", "result": {"status": "SUCCESS", "response": "hola mundo\n", "usage": {}}})
