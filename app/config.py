import os
from pathlib import Path


def data_dir() -> Path:
    """Carpeta de datos: usuarios, señales y ejemplos. En Railway es un volumen."""
    d = Path(os.environ.get("DATA_DIR", "datos"))
    d.mkdir(parents=True, exist_ok=True)
    return d
