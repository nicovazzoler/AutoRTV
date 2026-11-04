"""La caja: corre el código que el agente escribe para una señal, aislado del servidor.

Python en Pyodide (WebAssembly) dentro de Deno sin permisos: sin variables de entorno, sin red, sin archivos fuera de
la caja, sin lanzar procesos, y con tiempo y memoria limitados. `autoprueba` lo demuestra con código hostil.
"""
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DIR = Path(os.environ.get("CAJA_DIR") or RAIZ / "caja")
SEGUNDOS = 20
MEMORIA_MB = 768
MAX_SALIDA = 8_000_000  # caracteres del resultado
# Más que esto por la salida del proceso es alguien escribiendo por fuera del resultado: se corta.
MAX_LEIDO = MAX_SALIDA + 100_000
MAX_ERRORES = 100_000
SIMULTANEOS = 2  # cada corrida ocupa unos 200 MB
NADIE = 65534
# Por encima del vigilante: la memoria que el sistema operativo le deja reservar al proceso. WebAssembly reserva de más
# al crecer, por eso el margen.
MARGEN_MB = 768
PRLIMIT = shutil.which("prlimit")
_turnos = threading.BoundedSemaphore(SIMULTANEOS)


def _deno() -> Path:
    return DIR / "node_modules" / "deno" / "deno"


def instalada() -> bool:
    return _deno().is_file() and (DIR / "runner.mjs").is_file() and (DIR / "node_modules" / "pyodide").is_dir()


def _comando(memoria_mb: int, segundos: int) -> list[str]:
    deno = [str(_deno()), "run", "--quiet", "--no-prompt", "--no-lock", "--no-remote", f"--allow-read={DIR}",
            "--deny-net", "--deny-env", "--deny-run", "--deny-ffi", "--deny-sys", "--deny-write", "--deny-import",
            f"--v8-flags=--max-old-space-size={memoria_mb // 2}", str(DIR / "runner.mjs")]
    if PRLIMIT is None:
        return deno
    # Los topes se los pone el proceso a sí mismo antes de ser Deno: desde afuera no se puede una vez que cambió de
    # usuario. Así no dependen de que el vigilante llegue a tiempo. La CPU suma todos los hilos (V8 compila en
    # paralelo al arrancar): el tope de tiempo de verdad es el del reloj, este es por si el vigilante no llega.
    cpu = segundos * 4 + 30
    return [PRLIMIT, f"--data={(memoria_mb + MARGEN_MB) * 2**20}", f"--cpu={cpu}:{cpu + 1}", "--core=0", "--", *deno]


def _lanzar(memoria_mb: int, segundos: int) -> subprocess.Popen:
    comun = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "env": {}, "cwd": "/",
             "start_new_session": True}
    if os.geteuid() == 0:
        # Como root se puede bajar a un usuario sin permisos: una barrera más, por si algún día fallan las de Deno.
        try:
            return subprocess.Popen(_comando(memoria_mb, segundos), user=NADIE, group=NADIE, extra_groups=[], **comun)
        except OSError:
            pass
    return subprocess.Popen(_comando(memoria_mb, segundos), **comun)


def _matar(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _medir(pid: int) -> tuple[float, int | None]:
    """(MB de memoria en uso, usuario) del proceso."""
    rss, uid = 0.0, None
    try:
        for linea in Path(f"/proc/{pid}/status").read_text().splitlines():
            if linea.startswith("VmRSS:"):
                rss = int(linea.split()[1]) / 1024
            elif linea.startswith("Uid:"):
                uid = int(linea.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return rss, uid


def correr(codigo: str, datos, funcion: str = "principal", segundos: int = SEGUNDOS,
           memoria_mb: int = MEMORIA_MB) -> dict:
    """Corre `funcion(datos)` del código en la caja.

    Devuelve {"ok", "resultado" o "error", "salida" (lo que imprimió), "segundos", "pico_mb", "usuario"}.
    """
    if not instalada():
        return {"ok": False, "error": "La caja no está instalada en este servidor.", "segundos": 0.0}
    pedido = json.dumps({"codigo": codigo, "funcion": funcion, "datos": datos, "max_salida": MAX_SALIDA},
                        ensure_ascii=False, default=str).encode()
    with _turnos:
        return _correr(pedido, segundos, memoria_mb)


def _correr(pedido: bytes, segundos: int, memoria_mb: int) -> dict:
    inicio = time.monotonic()
    proc = _lanzar(memoria_mb, segundos)
    leido = {"salida": bytearray(), "errores": bytearray()}
    corte: dict = {"motivo": None}

    def escribir():
        try:
            proc.stdin.write(pedido)
            proc.stdin.close()
        except OSError:
            pass

    def leer(nombre: str, flujo, tope: int):
        while bloque := flujo.read1(65536):
            if len(leido[nombre]) + len(bloque) <= tope:
                leido[nombre] += bloque
            elif nombre == "salida" and not corte["motivo"]:
                corte["motivo"] = "salida"
                _matar(proc)

    hilos = [threading.Thread(target=escribir, daemon=True),
             threading.Thread(target=leer, args=("salida", proc.stdout, MAX_LEIDO), daemon=True),
             threading.Thread(target=leer, args=("errores", proc.stderr, MAX_ERRORES), daemon=True)]
    for hilo in hilos:
        hilo.start()
    pico, usuario = 0.0, None
    while proc.poll() is None:
        rss, uid = _medir(proc.pid)
        pico, usuario = max(pico, rss), usuario if usuario is not None else uid
        if time.monotonic() - inicio > segundos:
            corte["motivo"] = corte["motivo"] or "tiempo"
        elif rss > memoria_mb:
            corte["motivo"] = corte["motivo"] or "memoria"
        if corte["motivo"]:
            _matar(proc)
            break
        time.sleep(0.05)
    proc.wait()
    for hilo in hilos:
        hilo.join(timeout=5)
    return _resultado(proc.returncode, leido, corte["motivo"], segundos, memoria_mb,
                      {"segundos": round(time.monotonic() - inicio, 2), "pico_mb": round(pico), "usuario": usuario})


def _resultado(codigo_salida: int, leido: dict, motivo: str | None, segundos: int, memoria_mb: int,
               medidas: dict) -> dict:
    errores = leido["errores"].decode(errors="replace")
    if motivo is None and codigo_salida in (-signal.SIGXCPU, -signal.SIGKILL):
        motivo = "tiempo"  # el tope de CPU del sistema operativo
    if motivo is None and ("heap out of memory" in errores or "MemoryError" in leido["salida"].decode(errors="replace")):
        motivo = "memoria"
    if motivo:
        textos = {"tiempo": f"Se cortó: tardó más de {segundos} s.", "memoria": f"Se cortó: usó más de {memoria_mb} MB.",
                  "salida": "Se cortó: escribió de más por fuera del resultado."}
        return {"ok": False, "error": textos[motivo], **medidas}
    try:
        recibido = json.loads(leido["salida"].decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        recibido = {"error": "La caja no devolvió un resultado: " + leido["salida"][:300].decode(errors="replace")}
    if not isinstance(recibido, dict):
        recibido = {"error": "La caja no devolvió un resultado."}
    # Solo lo que puede decir el código; las medidas son del servidor.
    salida = {"ok": recibido.get("ok") is True, "salida": str(recibido.get("salida") or "")[:4000]}
    if salida["ok"]:
        salida["resultado"] = recibido.get("resultado")
    else:
        salida["error"] = str(recibido.get("error") or f"La caja terminó con el código {codigo_salida}.")[-3000:]
        if errores.strip():
            salida["errores"] = errores[-1500:]
    return {**salida, **medidas}
