"""Servidor real para los tests en navegador, con el agente respondiendo siempre lo mismo (no gasta API)."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def servidor(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    # El asistente charla siempre lo mismo y propone siempre lo mismo: pasar Titulo a mayúsculas.
    falso = tmp_path / "asistente.json"
    falso.write_text(json.dumps([{"respuesta": "¡Hola! Decime qué querés cambiar.", "proponer_cambios": False},
                                 {"explicacion": "Pasé los títulos a mayúsculas", "columnas_salida": None,
                                  "tarjetas_json": json.dumps([{"id": "a1", "tipo": "mayus_minus",
                                                                "columnas": ["Titulo"], "modo": "MAYUS"}])}]))
    entorno = {"DATA_DIR": str(tmp_path), "ADMIN_USUARIO": "admin", "ADMIN_CLAVE": "clave-segura", "PATH": "",
               "AGENTE_FALSO": str(falso)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(puerto)],
                            cwd=RAIZ, env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", puerto), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait()
