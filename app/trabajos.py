"""Las tareas largas (el agente de la señal, el Banco) corren en un proceso aparte, con su propio tope de memoria.

En Python un proceso hace una cosa a la vez: así no le sacan CPU a la web, y si una se dispara se corta esa y la web
sigue para todos. El proceso arranca limpio (spawn), con su propia conexión a la base y su propio agente.
"""
import logging
import multiprocessing
import threading
from collections.abc import Callable

MEMORIA_MB = 2000  # lo que puede crecer cada tarea por encima de lo que su proceso reservó al arrancar
SIMULTANEOS = 2  # procesos de tareas a la vez; el resto espera su turno
# Los tests lo apagan: la tarea corre en un hilo del mismo proceso, con el agente grabado del test.
EN_PROCESO = True
_turnos = threading.BoundedSemaphore(SIMULTANEOS)
_vivos: dict[int, str] = {}  # pid → nombre de la tarea, para el aviso de memoria
_cerrojo = threading.Lock()


def lanzar(nombre: str, funcion: Callable, args: tuple, al_terminar: Callable[[int | None], None],
           en_hilo: bool = True) -> None:
    """Corre funcion(*args) aparte y después al_terminar(código de salida) en este proceso: 0 = terminó bien.

    Sin `en_hilo` (tests), corre acá mismo y vuelve cuando terminó.
    """
    def esperar():
        with _turnos:
            codigo = _en_proceso(nombre, funcion, args) if EN_PROCESO else _aca(funcion, args)
        al_terminar(codigo)

    if en_hilo:
        threading.Thread(target=esperar, daemon=True, name=f"espera-{nombre}").start()
    else:
        esperar()


def vivos() -> dict[int, str]:
    with _cerrojo:
        return dict(_vivos)


def _aca(funcion: Callable, args: tuple) -> int:
    try:
        funcion(*args)
        return 0
    except Exception:
        logging.getLogger("autortv").exception("La tarea %s falló", getattr(funcion, "__name__", funcion))
        return 1


def _en_proceso(nombre: str, funcion: Callable, args: tuple) -> int | None:
    from app.caja import autoprueba

    proceso = multiprocessing.get_context("spawn").Process(
        target=_adentro, args=(funcion, args, autoprueba.estado(), MEMORIA_MB), name=nombre, daemon=True)
    proceso.start()
    with _cerrojo:
        _vivos[proceso.pid] = nombre
    proceso.join()
    with _cerrojo:
        _vivos.pop(proceso.pid, None)
    return proceso.exitcode


def _adentro(funcion: Callable, args: tuple, caja: dict, memoria_mb: int) -> None:
    from app import memoria
    from app.caja import autoprueba

    memoria.topar(memoria_mb)
    # La caja ya se probó en este servidor al arrancar: el proceso nuevo no vuelve a probarla.
    autoprueba._estado.update(caja, probando=False)
    funcion(*args)
