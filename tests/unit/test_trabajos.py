import os

import pytest

from app import trabajos


def llenar_la_memoria():
    return [bytearray(100 * 2**20) for _ in range(100)]


def escribir(ruta: str):
    with open(ruta, "w") as f:
        f.write(str(os.getpid()))


@pytest.fixture
def en_proceso(monkeypatch):
    monkeypatch.setattr(trabajos, "EN_PROCESO", True)
    monkeypatch.setattr(trabajos, "MEMORIA_MB", 500)


def test_una_tarea_corre_en_otro_proceso_y_avisa_cuando_termina(en_proceso, tmp_path):
    codigos = []
    trabajos.lanzar("prueba", escribir, (str(tmp_path / "pid"),), codigos.append, en_hilo=False)
    assert codigos == [0] and int((tmp_path / "pid").read_text()) != os.getpid()


def test_una_tarea_que_se_come_la_memoria_muere_sola_y_el_servidor_sigue(en_proceso):
    codigos = []
    trabajos.lanzar("glotona", llenar_la_memoria, (), codigos.append, en_hilo=False)
    assert codigos and codigos[0] != 0  # el proceso de la tarea se cortó; este, que es el servidor, sigue acá
    assert trabajos.vivos() == {}
