import os
from pathlib import Path


def data_dir() -> Path:
    """Carpeta de la base SQLite cuando no hay DATABASE_URL, y origen de la migración del formato viejo."""
    d = Path(os.environ.get("DATA_DIR", "datos"))
    d.mkdir(parents=True, exist_ok=True)
    return d
