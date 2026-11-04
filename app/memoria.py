"""La memoria del servidor: un tope propio por debajo del de Railway y un aviso en el log cuando sube.

Con el tope, si algo se come la memoria falla esa tarea (MemoryError, con el lugar en el log) y el servidor sigue.
Sin él, Railway mata el proceso entero.
"""
import logging
import os
import resource
import threading
import time
from collections.abc import Callable
from pathlib import Path

CGROUP = (Path("/sys/fs/cgroup/memory.max"), Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))
PARTE = 0.5  # del tope del contenedor: el resto queda para la caja (dos de hasta 1,5 GB) y el sistema
POR_DEFECTO_MB = 4000  # si no se ve el del contenedor (el plan Hobby de Railway llega a 8 GB)
AVISO_MB = 1000
CADA = 15  # segundos entre mediciones


def tope_del_contenedor() -> int | None:
    """Los bytes que el contenedor puede usar, o None si no tiene tope (o no se ve)."""
    for ruta in CGROUP:
        try:
            texto = ruta.read_text().strip()
        except OSError:
            continue
        if texto.isdigit() and int(texto) < 2**40:  # "max" o un número enorme: sin tope
            return int(texto)
    return None


def tope_mb(contenedor: int | None, pedido: str | None = None) -> int:
    if pedido:
        return int(pedido)
    return int(contenedor * PARTE / 2**20) if contenedor else POR_DEFECTO_MB


def poner_tope() -> int:
    """Baja el tope de memoria del proceso (RLIMIT_DATA) y devuelve cuántos MB quedaron."""
    mb = tope_mb(tope_del_contenedor(), os.environ.get("MEMORIA_SERVIDOR_MB"))
    _, duro = resource.getrlimit(resource.RLIMIT_DATA)
    blando = mb * 2**20 if duro == resource.RLIM_INFINITY else min(mb * 2**20, duro)
    resource.setrlimit(resource.RLIMIT_DATA, (blando, duro))
    return mb


def rss_mb(pid: int) -> float:
    try:
        linea = next(x for x in Path(f"/proc/{pid}/status").read_text().splitlines() if x.startswith("VmRSS:"))
        return int(linea.split()[1]) / 1024
    except (OSError, StopIteration, ValueError, IndexError):
        return 0.0


def hijos(pid: int) -> list[int]:
    """Los procesos que lanzó `pid` (los de la caja)."""
    encontrados = []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            # El nombre del proceso va entre paréntesis y puede tener espacios: lo de después es fijo.
            campos = stat.read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if campos and int(campos[1]) == pid:
            encontrados.append(int(stat.parent.name))
    return encontrados


def descendientes(pid: int) -> list[int]:
    """Los procesos que lanzó `pid` y los que lanzaron esos: las tareas y sus cajas."""
    todos, pendientes = [], hijos(pid)
    while pendientes:
        todos.append(actual := pendientes.pop())
        pendientes += hijos(actual)
    return todos


def medir() -> tuple[float, float, int]:
    """(MB del servidor, MB de los procesos que lanzó, cuántos son)."""
    propios = descendientes(os.getpid())
    return rss_mb(os.getpid()), sum(rss_mb(h) for h in propios), len(propios)


def vigilar(que_corre: Callable[[], str]) -> None:
    """Cada CADA segundos, si la memoria pasa de AVISO_MB, deja en el log cuánto y qué estaba corriendo."""
    def bucle():
        while True:
            time.sleep(CADA)
            servidor, caja, procesos = medir()
            if servidor + caja > AVISO_MB:
                logging.getLogger("autortv").warning("Memoria alta: servidor %.0f MB, tareas y caja %.0f MB en %d procesos · %s",
                                                     servidor, caja, procesos, que_corre())
    threading.Thread(target=bucle, daemon=True, name="vigia-memoria").start()
