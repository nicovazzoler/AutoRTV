"""Código hostil que tiene que fallar en la caja: si alguno sale, el código de las señales queda apagado.

Corre en el build de la imagen y al arrancar el servidor, con las claves de verdad cargadas en el proceso.
"""
import datetime as dt
import json
import os
import secrets
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import caja

CANARIO = "AUTORTV_CANARIO"
# Va en el entorno del servidor, como las claves de verdad. Se pone al cargar el módulo, antes de que haya hilos:
# cambiar el entorno con el servidor andando puede tirar abajo el proceso si otro hilo lo está leyendo.
os.environ.setdefault(CANARIO, secrets.token_hex(12))
SENSIBLES = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CLAVE", "DATABASE_URL")

NORMAL = '''
import datetime as dt, re, unicodedata
def principal(d):
    filas = []
    for linea in d["lineas"]:
        hora, titulo = re.match(r"(\\d\\d:\\d\\d) (.*)", linea).groups()
        filas.append({"Hora": dt.datetime.strptime(hora, "%H:%M").strftime("%H:%M"),
                      "Titulo": unicodedata.normalize("NFC", titulo).upper()})
    return filas
'''
NORMAL_DATOS = {"lineas": ["06:00 Noticias", "07:30 Cine del día"]}
NORMAL_ESPERADO = [{"Hora": "06:00", "Titulo": "NOTICIAS"}, {"Hora": "07:30", "Titulo": "CINE DEL DÍA"}]


def _casos(archivo: Path, escrito: Path) -> dict[str, str]:
    leer = "import js\ndef principal(d):\n    return js.Deno.readTextFileSync({!r})"
    correr = "import js\ndef principal(d):\n    return str(js.Deno.Command.new({}).outputSync().stdout)"
    return {
        "Variables de entorno: os.environ": "import os\ndef principal(d):\n    return dict(os.environ)",
        "Variables de entorno: os.getenv": f"import os\ndef principal(d):\n    return os.getenv({CANARIO!r})",
        "Variables de entorno: posix.environ": "import posix\ndef principal(d):\n    return {str(k): str(v) for k, v in posix.environ.items()}",
        "Variables de entorno: Deno.env": "import js\ndef principal(d):\n    return js.Deno.env.toObject().to_py()",
        "Variables de entorno: process.env": f"import js\ndef principal(d):\n    return js.process.env.{CANARIO}",
        "Variables de entorno: /proc/self/environ": leer.format("/proc/self/environ"),
        "Variables del servidor: /proc del proceso padre": leer.format(f"/proc/{os.getpid()}/environ"),
        "Red: socket": "import socket\ndef principal(d):\n    socket.create_connection(('1.1.1.1', 443), 3)\n    return 'conectó'",
        "Red: urllib": ("import urllib.request\ndef principal(d):\n    abrir = urllib.request.build_opener("
                        "urllib.request.ProxyHandler({}))\n    return str(abrir.open('http://93.184.215.14/', timeout=3).read()[:50])"),
        "Red: fetch": "import js\nasync def principal(d):\n    r = await js.fetch('https://example.com')\n    return await r.text()",
        "Red: pyfetch": "from pyodide.http import pyfetch\nasync def principal(d):\n    r = await pyfetch('https://example.com')\n    return await r.string()",
        "Red: Deno.connect": ("import js\nasync def principal(d):\n    await js.Deno.connect(js.Object.fromEntries("
                              "[['hostname', '1.1.1.1'], ['port', 443]]))\n    return 'conectó'"),
        "Red: DNS": "import js\nasync def principal(d):\n    return str(await js.Deno.resolveDns('example.com', 'A'))",
        "Red: importar código de internet": "import js\nasync def principal(d):\n    await js.eval(\"import('https://esm.sh/lodash')\")\n    return 'importó'",
        "Archivos: /etc/passwd con open()": "def principal(d):\n    return open('/etc/passwd').read()",
        "Archivos: /etc/passwd con Deno": leer.format("/etc/passwd"),
        "Archivos: un secreto del servidor": leer.format(str(archivo)),
        "Archivos: el código del servidor": leer.format(str(caja.RAIZ / "app" / "caja" / "__init__.py")),
        "Archivos: montar el disco (NODEFS)": ("import js, pyodide_js\ndef principal(d):\n    fs = pyodide_js.FS\n"
                                               "    fs.mkdir('/host')\n    fs.mount(fs.filesystems.NODEFS, "
                                               "js.Object.fromEntries([['root', '/']]), '/host')\n"
                                               f"    return open('/host{archivo}').read()"),
        "Archivos: escribir": f"import js\ndef principal(d):\n    js.Deno.writeTextFileSync({str(escrito)!r}, 'x')\n    return 'escribió'",
        "Procesos: /usr/bin/id": correr.format("'/usr/bin/id'"),
        "Procesos: /bin/sh": ("import js\ndef principal(d):\n    c = js.Deno.Command.new('/bin/sh', js.Object.fromEntries("
                              "[['args', js.Array.of('-c', 'id')]]))\n    return str(c.outputSync().stdout)"),
        "Procesos: subprocess": "import subprocess\ndef principal(d):\n    return str(subprocess.run(['id'], capture_output=True).stdout)",
        "Bibliotecas del sistema (FFI)": "import js\ndef principal(d):\n    js.Deno.dlopen('libc.so.6', js.Object.new())\n    return 'abrió libc'",
        "Datos del sistema": "import js\ndef principal(d):\n    return js.Deno.hostname()",
        "Pedir permisos": ("import js\nasync def principal(d):\n    r = await js.Deno.permissions.request("
                           "js.Object.fromEntries([['name', 'env']]))\n    if r.state != 'granted':\n"
                           "        raise PermissionError(r.state)\n    return r.state"),
        "Tiempo: bucle infinito": "def principal(d):\n    while True:\n        pass",
        "Memoria: llenarla": "def principal(d):\n    return len([bytearray(100_000_000) for _ in range(40)])",
        "Salida: un resultado enorme": "def principal(d):\n    return ['y' * 1000] * 20000",
        "Salida: escribir de más por afuera": ("import js\ndef principal(d):\n    bloque = js.Uint8Array.new(1_000_000)\n"
                                               "    for _ in range(100):\n        js.Deno.stdout.writeSync(bloque)\n    return []"),
    }


def _secretos(canario: str, del_archivo: str) -> list[str]:
    reales = [v for k, v in os.environ.items() if any(s in k.upper() for s in SENSIBLES) and len(v) >= 8]
    return [canario, del_archivo, *reales]


def _ultima_linea(texto: str) -> str:
    return next((x.strip() for x in reversed(texto.strip().splitlines()) if x.strip()), "")[:200]


def probar(segundos: int = caja.SEGUNDOS) -> dict:
    """Corre el código normal y el hostil. ok = el normal anda y ningún hostil salió con algo de afuera."""
    inicio = time.monotonic()
    fecha = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if not caja.instalada():
        return {"ok": False, "anda": False, "fecha": fecha, "casos": [],
                "motivo": "La caja no está instalada en este servidor: el código de las señales queda apagado."}
    canario = os.environ[CANARIO]
    carpeta = Path(tempfile.mkdtemp(prefix="autortv-caja-"))
    archivo, escrito = carpeta / "secreto.txt", carpeta / "escrito.txt"
    del_archivo = secrets.token_hex(12)
    archivo.write_text(del_archivo)
    try:
        normal = caja.correr(NORMAL, NORMAL_DATOS, segundos=segundos)
        anda = normal["ok"] and normal.get("resultado") == NORMAL_ESPERADO
        secretos = _secretos(canario, del_archivo)

        def uno(par: tuple[str, str]) -> dict:
            nombre, codigo = par
            r = caja.correr(codigo, {}, segundos=segundos)
            texto = json.dumps(r, ensure_ascii=False)
            fuga = any(s in texto for s in secretos) or "root:x:0" in texto
            return {"nombre": nombre, "bloqueado": not r["ok"] and not fuga and not escrito.exists(),
                    "motivo": "salió con datos de afuera" if fuga else _ultima_linea(r.get("error") or "")
                    or ("terminó bien" if r["ok"] else "")}

        with ThreadPoolExecutor(caja.SIMULTANEOS) as hilos:
            casos = list(hilos.map(uno, _casos(archivo, escrito).items()))
    finally:
        for f in (archivo, escrito):
            f.unlink(missing_ok=True)
        carpeta.rmdir()
    escapados = [c["nombre"] for c in casos if not c["bloqueado"]]
    if not anda:
        motivo = (f"La caja no corre código en este servidor ({_ultima_linea(normal.get('error') or '')}): el código "
                  "de las señales queda apagado.")
    elif escapados:
        motivo = f"Se {'escapó' if len(escapados) == 1 else 'escaparon'} {len(escapados)}: el código de las señales queda apagado."
    else:
        motivo = f"Bloqueó los {len(casos)} intentos y corre código normal."
    return {"ok": anda and not escapados, "anda": anda, "fecha": fecha, "casos": casos, "motivo": motivo,
            "segundos": round(time.monotonic() - inicio, 1), "usuario": normal.get("usuario"),
            "limites": {"segundos": segundos, "memoria_mb": caja.MEMORIA_MB}}


_estado: dict = {"ok": False, "anda": False, "probando": False, "casos": [],
                 "motivo": "Todavía no se probó en este servidor: el código de las señales está apagado."}
_cerrojo = threading.Lock()


def estado() -> dict:
    with _cerrojo:
        return dict(_estado)


def disponible() -> bool:
    """El código de las señales puede correr: la última autoprueba de este servidor salió bien."""
    return bool(estado()["ok"])


def en_segundo_plano() -> None:
    """Lanza la autoprueba sin esperarla. Si ya hay una corriendo, no hace nada."""
    with _cerrojo:
        if _estado["probando"]:
            return
        _estado["probando"] = True
    threading.Thread(target=_probar_y_guardar, daemon=True).start()


def _probar_y_guardar() -> None:
    try:
        resultado = probar()
    except Exception as e:  # una falla de la prueba deja el código apagado, nunca prendido
        resultado = {"ok": False, "anda": False, "casos": [], "motivo": f"La autoprueba falló: {type(e).__name__}: {e}"}
    with _cerrojo:
        _estado.clear()
        _estado.update(resultado, probando=False)
