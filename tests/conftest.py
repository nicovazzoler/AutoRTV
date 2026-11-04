import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def tareas_en_el_mismo_proceso(monkeypatch):
    """Las tareas largas corren en un hilo y no en otro proceso: así ven el agente grabado de cada test."""
    from app import trabajos
    monkeypatch.setattr(trabajos, "EN_PROCESO", False)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """App con DATA_DIR temporal y un admin ya logueado."""
    from fastapi.testclient import TestClient

    from app import auth
    from app.main import app

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    auth.crear_usuario("admin", "clave-segura", admin=True)
    c = TestClient(app)
    assert c.post("/api/login", json={"usuario": "admin", "clave": "clave-segura"}).status_code == 200
    return c


@pytest.fixture(autouse=True)
def base_limpia():
    """Con DATABASE_URL (Postgres real) todos los tests comparten base: se vacía antes de cada uno."""
    import os
    if not os.environ.get("DATABASE_URL"):
        yield
        return
    from app import db, tablas
    with db.transaccion() as con:
        for tabla in reversed(db.metadata.sorted_tables):
            con.execute(tabla.delete())
    tablas.olvidar_cache()
    yield
