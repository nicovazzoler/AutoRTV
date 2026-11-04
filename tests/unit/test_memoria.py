import os
import subprocess
import sys
from pathlib import Path

from app import memoria

RAIZ = Path(__file__).resolve().parents[2]


def test_el_tope_del_servidor_deja_lugar_para_la_caja():
    assert memoria.tope_mb(8 * 2**30) == 4096  # la mitad de un contenedor de 8 GB
    assert memoria.tope_mb(None) == memoria.POR_DEFECTO_MB and memoria.tope_mb(8 * 2**30, "2000") == 2000


def test_el_servidor_se_pone_el_tope_y_un_exceso_es_un_error_y_no_la_muerte_del_proceso():
    codigo = ("from app import memoria; memoria.poner_tope()\n"
              "try:\n    x = bytearray(600 * 2**20)\nexcept MemoryError:\n    print('MemoryError')")
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True,
                       env={**os.environ, "MEMORIA_SERVIDOR_MB": "500"}, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "MemoryError", r.stderr


def test_la_vigia_ve_los_procesos_que_lanzo_el_servidor():
    hijo = subprocess.Popen(["sleep", "5"])
    try:
        assert hijo.pid in memoria.hijos(os.getpid())
        servidor, _, procesos = memoria.medir()
        assert servidor > 0 and procesos >= 1
    finally:
        hijo.kill()
        hijo.wait()
