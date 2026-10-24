import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
