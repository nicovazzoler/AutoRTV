// Corre el código de una señal dentro de Pyodide. Por stdin llega {"codigo", "funcion", "datos", "max_salida"} y por
// stdout sale {"ok": true, "resultado": ..., "salida": "..."} o {"ok": false, "error": "...", "salida": "..."}.
// La seguridad no depende de este archivo: la dan los permisos con que se lanza Deno (ninguno salvo leer esta
// carpeta) y el proceso sin variables de entorno. Esto arma el intérprete y llama a la función pedida.
import { loadPyodide } from "pyodide";

const MAX_PRINTS = 4000;
let impreso = "";
const anotar = (t) => {
  if (impreso.length < MAX_PRINTS) impreso = (impreso + t + "\n").slice(0, MAX_PRINTS);
};
const escribir = async (texto) => {
  const datos = new TextEncoder().encode(texto);
  for (let hecho = 0; hecho < datos.length;) hecho += await Deno.stdout.write(datos.subarray(hecho));
};

const py = await loadPyodide({ env: {}, stdout: anotar, stderr: anotar });
const pedido = JSON.parse(await new Response(Deno.stdin.readable).text());
py.globals.set("CODIGO", pedido.codigo);
py.globals.set("FUNCION", pedido.funcion);
py.globals.set("DATOS_JSON", JSON.stringify(pedido.datos ?? null));
py.globals.set("MAX_SALIDA", pedido.max_salida);
try {
  // El resultado sale de Python ya en JSON y medido: así uno enorme no llega a ocupar la memoria de JavaScript.
  const resultado = await py.runPythonAsync(`
import inspect, json, os, posix

class _SinEntorno(dict):
    def _no(self, *a, **k):
        raise PermissionError("El código de la señal no tiene variables de entorno.")
    __getitem__ = __iter__ = __len__ = __contains__ = get = keys = items = values = copy = _no

posix.environ.clear()
posix.environ = os.environ = _SinEntorno()
os.getenv = lambda *a, **k: os.environ.get(*a)

espacio = {"__name__": "senal"}
exec(compile(CODIGO, "senal.py", "exec"), espacio)
if not callable(espacio.get(FUNCION)):
    raise NameError(f"El código no define la función {FUNCION}(datos).")
resultado = espacio[FUNCION](json.loads(DATOS_JSON))
if inspect.isawaitable(resultado):
    resultado = await resultado
texto = json.dumps(resultado, ensure_ascii=False, default=str)
if len(texto) > MAX_SALIDA:
    raise ValueError(f"El resultado pasa de {MAX_SALIDA} caracteres.")
texto
`);
  await escribir(`{"ok": true, "resultado": ${resultado}, "salida": ${JSON.stringify(impreso)}}`);
} catch (e) {
  await escribir(JSON.stringify({ ok: false, error: String(e).slice(-3000), salida: impreso }));
}
