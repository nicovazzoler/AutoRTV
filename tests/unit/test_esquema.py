import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.engine import model as m

RAIZ = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("archivo", sorted((RAIZ / "ejemplos").glob("*.json")), ids=lambda p: p.name)
def test_ejemplos_validan(archivo):
    m.Senal.model_validate(json.loads(archivo.read_text(encoding="utf-8")))


def test_tipo_desconocido_falla():
    with pytest.raises(ValidationError):
        m.Senal.model_validate({"id": "x", "nombre": "x", "entrada": {"tipo": "excel"},
                                "tarjetas": [{"id": "t", "tipo": "inventada"}], "salida": {"columnas": []}})


def test_no_hay_json_de_senales_fuera_de_ejemplos():
    """Las recetas del laburo van en el repo privado, nunca acá."""
    sueltos = [p for p in RAIZ.rglob("*.json")
               if not {".venv", "privado", "muestras", "ejemplos", "node_modules", "front", "caja"} & set(p.relative_to(RAIZ).parts)]
    assert sueltos == []
