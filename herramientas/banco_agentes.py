"""Banco de pruebas de los agentes: ¿alcanza Haiku, o hace falta Sonnet? Gasta API de verdad.

Uso: python herramientas/banco_agentes.py [--tope 5] [--solo AGAPE,OWN]
Lee los pares grilla + ejemplo de muestras/banco.json y deja el resultado en muestras/banco/.
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app import inputs  # noqa: E402
from app.agent import asistente, cliente, controles, lectura  # noqa: E402
from app.engine import model as m  # noqa: E402

MUESTRAS = RAIZ / "muestras"
HAIKU, SONNET = cliente.MODELO, cliente.MODELO_FUERTE
# US$ por millón de tokens (entrada, salida). Lo cacheado se cuenta como entrada común: el costo da un poco de más.
PRECIOS = {"haiku": (0.10, 0.50), "sonnet": (2.00, 10.00), "opus": (4.00, 20.00)}
CORRIDAS_HAIKU = 2
UMBRAL_REGLAS = 90.0
PEDIDO = "Ajustá las tarjetas para que la grilla de entrada de este ejemplo quede igual al EPG esperado."


class TopeDeGasto(Exception):
    pass


class Caja:
    """Suma lo gastado y corta antes de pasar el tope."""

    def __init__(self, tope: float):
        self.tope, self.gastado = tope, 0.0

    def cobrar(self, modelo: str, entrada: int, salida: int) -> float:
        precio = next((p for nombre, p in PRECIOS.items() if nombre in modelo), PRECIOS["sonnet"])
        costo = (entrada * precio[0] + salida * precio[1]) / 1_000_000
        self.gastado += costo
        if self.gastado > self.tope:
            raise TopeDeGasto(f"Se pasó el tope de US$ {self.tope}: van US$ {self.gastado:.2f}")
        return round(costo, 4)


def _lectura(contenido, proveedor, modelo, esperado, caja, previa=None) -> dict:
    inicio = time.time()
    p = lectura.proponer(contenido, proveedor, modelo, esperado, previa)
    return {"modelo": modelo, "logrado": p.logrado, "medida": p.medida, "entrada": p.entrada,
            "problemas": p.problemas, "vueltas": p.vueltas, "segundos": round(time.time() - inicio, 1),
            "costo": caja.cobrar(p.modelo or modelo, p.tokens_entrada, p.tokens_salida), "_propuesta": p}


def _reglas(receta, tabla, ejemplo, proveedor, fuerte, caja) -> dict:
    inicio = time.time()
    p = asistente.pedir(receta, tabla, PEDIDO, proveedor, [ejemplo], objetivo=ejemplo.nombre,
                        orden_columnas=list(ejemplo.esperado.columns), fuerte=fuerte)
    antes = p.antes.ejemplos.get(ejemplo.nombre, 0) if p.antes else 0
    despues = p.despues.ejemplos.get(ejemplo.nombre, antes) if p.despues else antes
    return {"modelo": p.modelo, "logrado": p.logrado, "antes": antes, "despues": despues,
            "tarjetas": len((p.receta or {}).get("tarjetas", [])), "problemas": p.problemas[:5],
            "vueltas": p.vueltas, "segundos": round(time.time() - inicio, 1),
            "costo": caja.cobrar(p.modelo or (SONNET if fuerte else HAIKU), p.tokens_entrada, p.tokens_salida),
            "_receta": p.receta}


def probar_par(par: dict, proveedor, caja) -> dict:
    contenido = (MUESTRAS / par["grilla"]).read_bytes()
    esperado = pd.read_excel(MUESTRAS / par["ejemplo"], dtype=object) if par.get("ejemplo") else None
    detectada = inputs.detectar(contenido)
    codigo = controles.lectura(inputs.leer(contenido, detectada), esperado)
    resultado = {"nombre": par["nombre"], "codigo": {"entrada": detectada.model_dump(exclude_defaults=True),
                                                     "medida": codigo, "problemas": controles.problemas_de_lectura(codigo)}}

    # Paso 1: lectura a ciegas (el agente no ve lo que detectó el código).
    haikus = [_lectura(contenido, proveedor, HAIKU, esperado, caja) for _ in range(CORRIDAS_HAIKU)]
    sonnet = _lectura(contenido, proveedor, SONNET, esperado, caja)
    fallida = next((h for h in haikus if not h["logrado"]), None)
    escalera = _lectura(contenido, proveedor, SONNET, esperado, caja, fallida["_propuesta"]) if fallida else None
    resultado["lectura"] = {"haiku": haikus, "sonnet": sonnet, "escalera": escalera}

    # Paso 4: reglas desde el ejemplo, sobre una lectura que pasó los controles.
    if esperado is None:
        return resultado
    if not resultado["codigo"]["problemas"]:
        buena = detectada
    else:
        aprobada = next((x for x in [*haikus, sonnet, escalera] if x and x["logrado"]), None)
        buena = lectura.ENTRADA.validate_python(aprobada["entrada"]) if aprobada else None
    if buena is None:
        resultado["reglas"] = {"error": "ninguna lectura pasó los controles"}
        return resultado
    tabla = inputs.leer(contenido, buena)
    receta = m.Senal(id="banco", nombre=par["nombre"], entrada=buena, tarjetas=[], salida=m.Salida(columnas=[]))
    ejemplo = asistente.Ejemplo(par["nombre"], tabla, esperado)
    haiku_r = _reglas(receta, tabla, ejemplo, proveedor, False, caja)
    sonnet_r = _reglas(receta, tabla, ejemplo, proveedor, True, caja)
    escalera_r = None
    if haiku_r["despues"] < UMBRAL_REGLAS and haiku_r["_receta"]:
        receta_haiku = m.Senal(**haiku_r["_receta"])
        escalera_r = _reglas(receta_haiku, tabla, ejemplo, proveedor, True, caja)
    resultado["reglas"] = {"haiku": haiku_r, "sonnet": sonnet_r, "escalera": escalera_r}
    return resultado


def _fila_lectura(x: dict | None) -> str:
    if not x:
        return "—"
    med = x["medida"] or {}
    estado = "✔" if x["logrado"] else "✗"
    empareja = f"{med['empareja']:.0%}" if med.get("empareja") is not None else "s/ej"
    return f"{estado} {med.get('con_horario', 0):.0%} / {empareja} · US$ {x['costo']:.3f} · {x['segundos']}s"


def _fila_reglas(x: dict | None) -> str:
    if not x:
        return "—"
    return f"{x['antes']:.0f} → {x['despues']:.0f} % · {x['tarjetas']} tarjetas · US$ {x['costo']:.3f} · {x['segundos']}s"


def informe(resultados: list[dict], caja: Caja) -> str:
    lineas = [f"# Banco de agentes · {dt.datetime.now():%Y-%m-%d %H:%M}", "",
              f"Haiku = {HAIKU} · Sonnet = {SONNET} · gastado US$ {caja.gastado:.2f}", "",
              "## Paso 1 · lectura (✔/✗ · % filas con fecha y hora / % del ejemplo que empareja)", "",
              "| Señal | Código | Haiku 1 | Haiku 2 | Sonnet | Escalera |", "|---|---|---|---|---|---|"]
    for r in resultados:
        cod = r["codigo"]
        c = f"{'✔' if not cod['problemas'] else '✗'} {cod['medida']['con_horario']:.0%}"
        lec = r.get("lectura", {})
        hs = lec.get("haiku", [])
        lineas.append(f"| {r['nombre']} | {c} | {_fila_lectura(hs[0] if hs else None)} | "
                      f"{_fila_lectura(hs[1] if len(hs) > 1 else None)} | {_fila_lectura(lec.get('sonnet'))} | "
                      f"{_fila_lectura(lec.get('escalera'))} |")
    lineas += ["", "## Paso 4 · reglas desde el ejemplo (% del ejemplo igual, solo con reglas)", "",
               "| Señal | Haiku | Sonnet | Escalera (Sonnet arranca de Haiku) |", "|---|---|---|---|"]
    for r in resultados:
        reg = r.get("reglas")
        if not reg:
            continue
        if "error" in reg:
            lineas.append(f"| {r['nombre']} | {reg['error']} | | |")
            continue
        lineas.append(f"| {r['nombre']} | {_fila_reglas(reg['haiku'])} | {_fila_reglas(reg['sonnet'])} | "
                      f"{_fila_reglas(reg['escalera'])} |")
    return "\n".join(lineas) + "\n"


def _limpio(x):
    if isinstance(x, dict):
        return {k: _limpio(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, list):
        return [_limpio(v) for v in x]
    return x


def main():
    argumentos = argparse.ArgumentParser()
    argumentos.add_argument("--tope", type=float, default=5.0, help="US$ máximos a gastar")
    argumentos.add_argument("--solo", default="", help="nombres de señal separados por coma")
    a = argumentos.parse_args()
    proveedor = cliente.proveedor_configurado()
    if not isinstance(proveedor, cliente.Claude):
        sys.exit("Falta ANTHROPIC_API_KEY en el entorno: el banco gasta API de verdad.")
    pares = json.loads((MUESTRAS / "banco.json").read_text(encoding="utf-8"))
    if a.solo:
        pares = [p for p in pares if p["nombre"] in a.solo.split(",")]
    caja, resultados = Caja(a.tope), []
    for par in pares:
        print(f"→ {par['nombre']}", flush=True)
        try:
            resultados.append(probar_par(par, proveedor, caja))
        except TopeDeGasto as e:
            print(e)
            break
        except cliente.ErrorAgente as e:
            resultados.append({"nombre": par["nombre"], "codigo": {"medida": {"con_horario": 0}, "problemas": [str(e)]}})
    salida = MUESTRAS / "banco"
    salida.mkdir(exist_ok=True)
    sello = f"{dt.datetime.now():%Y%m%d-%H%M}"
    (salida / f"resultado-{sello}.json").write_text(json.dumps(_limpio(resultados), ensure_ascii=False, indent=1, default=str))
    texto = informe(resultados, caja)
    (salida / f"resultado-{sello}.md").write_text(texto, encoding="utf-8")
    print(texto)


if __name__ == "__main__":
    main()
