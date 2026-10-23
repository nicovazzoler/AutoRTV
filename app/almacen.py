"""Guarda recetas (con historial) y ejemplos antes/después en DATA_DIR/senales."""
import datetime as dt
import json
import re
import shutil
from pathlib import Path

from app.config import data_dir
from app.engine import model as m

ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class NoExiste(Exception):
    pass


def _carpeta(senal_id: str) -> Path:
    # El id termina siendo parte de una ruta: así nadie puede escribir fuera de senales/.
    if not ID_VALIDO.match(senal_id):
        raise ValueError(f"Id inválido: {senal_id!r} (solo minúsculas, números, - y _)")
    return data_dir() / "senales" / senal_id


def listar() -> list[dict]:
    raiz = data_dir() / "senales"
    salida = []
    for archivo in sorted(raiz.glob("*/senal.json")) if raiz.exists() else []:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        salida.append({"id": datos["id"], "nombre": datos["nombre"]})
    return salida


def leer(senal_id: str) -> m.Senal:
    archivo = _carpeta(senal_id) / "senal.json"
    if not archivo.exists():
        raise NoExiste(senal_id)
    return m.Senal.model_validate_json(archivo.read_text(encoding="utf-8"))


def guardar(senal: m.Senal, usuario: str) -> None:
    carpeta = _carpeta(senal.id)
    (carpeta / "historial").mkdir(parents=True, exist_ok=True)
    texto = senal.model_dump_json(indent=2, exclude_none=True)
    (carpeta / "senal.json").write_text(texto, encoding="utf-8")
    sello = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    (carpeta / "historial" / f"{sello}_{_seguro(usuario)}.json").write_text(texto, encoding="utf-8")


def _seguro(texto: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", texto)[:32]


def _carpeta_ejemplo(senal_id: str, nombre: str) -> Path:
    if not ID_VALIDO.match(nombre):
        raise ValueError(f"Nombre de ejemplo inválido: {nombre!r} (solo minúsculas, números, - y _)")
    return _carpeta(senal_id) / "ejemplos" / nombre


def guardar_ejemplo(senal_id: str, nombre: str, entrada: bytes, esperado: bytes) -> None:
    carpeta = _carpeta_ejemplo(senal_id, nombre)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "entrada.xlsx").write_bytes(entrada)
    (carpeta / "esperado.xlsx").write_bytes(esperado)


def listar_ejemplos(senal_id: str) -> list[str]:
    raiz = _carpeta(senal_id) / "ejemplos"
    return sorted(p.name for p in raiz.iterdir() if (p / "esperado.xlsx").exists()) if raiz.exists() else []


def rutas_ejemplo(senal_id: str, nombre: str) -> tuple[Path, Path]:
    carpeta = _carpeta_ejemplo(senal_id, nombre)
    if not (carpeta / "esperado.xlsx").exists():
        raise NoExiste(nombre)
    return carpeta / "entrada.xlsx", carpeta / "esperado.xlsx"


def borrar_ejemplo(senal_id: str, nombre: str) -> None:
    shutil.rmtree(_carpeta_ejemplo(senal_id, nombre), ignore_errors=True)
