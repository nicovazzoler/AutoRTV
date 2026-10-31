"""El banco de agentes desde la terminal, con los pares de muestras/banco.json. Gasta API de verdad.

Uso: python herramientas/banco_agentes.py [--tope 5] [--solo AGAPE,OWN] [--pasos lectura,reglas]
Lo mismo corre en la web, en Administrar › Banco de agentes, con los ejemplos guardados de cada señal.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.agent import banco, cliente  # noqa: E402

MUESTRAS = RAIZ / "muestras"


def _lectura(x: dict | None) -> str:
    if not x:
        return "—"
    med = x["medida"] or {}
    empareja = f"{med['empareja']:.0%}" if med.get("empareja") is not None else "s/ej"
    return f"{'✔' if x['logrado'] else '✗'} {empareja} · US$ {x['costo']:.3f}"


def _reglas(x: dict | None) -> str:
    if not x:
        return "—"
    peores = ", ".join(f"{c} {p:.0f}%" for c, p in x["peores"])
    return f"{x['antes']:.0f} → {x['despues']:.0f} % · {x['vueltas']} vueltas · peores: {peores} · US$ {x['costo']:.3f}"


def informe(resultados: list[dict], gastado: float) -> str:
    lineas = [f"# Banco de agentes · {dt.datetime.now():%Y-%m-%d %H:%M}", "",
              f"Haiku = {banco.HAIKU} · Sonnet = {banco.SONNET} · gastado US$ {gastado:.2f}", "",
              f"Resumen: {json.dumps(banco.resumen(resultados), ensure_ascii=False)}", "",
              "| Señal | Paso | Haiku | Sonnet | Escalera |", "|---|---|---|---|---|"]
    for r in resultados:
        if "error" in r:
            lineas.append(f"| {r['nombre']} | — | {r['error']} | | |")
            continue
        if lec := r.get("lectura"):
            lineas.append(f"| {r['nombre']} | lectura | {_lectura(lec['haiku'])} | {_lectura(lec['sonnet'])} | "
                          f"{_lectura(lec['escalera'])} |")
        if reg := r.get("reglas"):
            if "error" in reg:
                lineas.append(f"| {r['nombre']} | reglas | {reg['error']} | | |")
            else:
                lineas.append(f"| {r['nombre']} | reglas | {_reglas(reg['haiku'])} | {_reglas(reg['sonnet'])} | "
                              f"{_reglas(reg['escalera'])} |")
    return "\n".join(lineas) + "\n"


def main():
    argumentos = argparse.ArgumentParser()
    argumentos.add_argument("--tope", type=float, default=5.0, help="US$ máximos a gastar")
    argumentos.add_argument("--solo", default="", help="nombres de señal separados por coma")
    argumentos.add_argument("--pasos", default=",".join(banco.PASOS))
    a = argumentos.parse_args()
    proveedor = cliente.proveedor_configurado()
    if not isinstance(proveedor, cliente.Claude):
        sys.exit("Falta ANTHROPIC_API_KEY en el entorno: el banco gasta API de verdad.")
    pares = json.loads((MUESTRAS / "banco.json").read_text(encoding="utf-8"))
    if a.solo:
        pares = [p for p in pares if p["nombre"] in a.solo.split(",")]
    pares = [banco.Par(p["nombre"], (MUESTRAS / p["grilla"]).read_bytes(),
                       (MUESTRAS / p["ejemplo"]).read_bytes() if p.get("ejemplo") else None) for p in pares]
    caja = banco.Caja(a.tope)
    resultados, corte = banco.correr_banco(pares, proveedor, caja, a.pasos.split(","),
                                           lambda texto, _: print(f"→ {texto}", flush=True))
    if corte:
        print(corte)
    salida = MUESTRAS / "banco"
    salida.mkdir(exist_ok=True)
    sello = f"{dt.datetime.now():%Y%m%d-%H%M}"
    (salida / f"resultado-{sello}.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=1, default=str))
    texto = informe(resultados, caja.gastado)
    (salida / f"resultado-{sello}.md").write_text(texto, encoding="utf-8")
    print(texto)


if __name__ == "__main__":
    main()
