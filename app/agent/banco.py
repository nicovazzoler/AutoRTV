"""Banco de pruebas de los agentes: para cada grilla + ejemplo, qué logra Haiku, qué logra Sonnet y qué recupera
Sonnet arrancando de lo de Haiku (escalera). Gasta API de verdad, con tope."""
import io
import time
import traceback
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from app import inputs
from app.agent import asistente, cliente, controles, diagnostico, lectura, uso
from app.engine import model as m
from app.engine.comparar import normalizar
from app.engine.pipeline import correr

HAIKU, SONNET = cliente.MODELO, cliente.MODELO_FUERTE
PASOS = ("diagnostico", "lectura", "reglas")
SIN_AGENTE = {"diagnostico"}  # pasos que no llaman al agente ni gastan
UMBRAL_REGLAS = 90.0
COLUMNAS_PEORES = 3
PEDIDO = "Ajustá las tarjetas para que la grilla de entrada de este ejemplo quede igual al EPG esperado."


@dataclass
class Par:
    nombre: str
    grilla: bytes
    esperado: bytes | None  # el EPG terminado en Excel; None = solo se prueba la lectura
    senal_id: str = ""
    entrada: dict | None = None  # cómo lee hoy la señal esta grilla


class TopeDeGasto(Exception):
    pass


class Caja:
    """Suma lo gastado, avisa cada pedido (para el registro de uso) y corta antes de pasar el tope."""

    def __init__(self, tope: float, al_cobrar: Callable[[str, str, int, int, int, bool], None] | None = None):
        self.tope, self.gastado, self.al_cobrar = tope, 0.0, al_cobrar

    def cobrar(self, senal: str, modelo: str, entrada: int, salida: int, vueltas: int, logrado: bool) -> float:
        precio = uso.costo(modelo, entrada, salida)
        costo = precio if precio is not None else uso.costo(SONNET, entrada, salida) or 0.0
        self.gastado += costo
        if self.al_cobrar:
            self.al_cobrar(senal, modelo, entrada, salida, vueltas, logrado)
        if self.gastado > self.tope:
            raise TopeDeGasto(f"Se pasó el tope de US$ {self.tope:g}: van US$ {self.gastado:.2f}")
        return round(costo, 4)


def por_columna(salida: pd.DataFrame, esperado: pd.DataFrame, pares: list[tuple[int, int]] | None) -> dict[str, float]:
    """% de celdas iguales al ejemplo en cada columna, en las filas emparejadas."""
    pares = pares if pares is not None else [(i, i) for i in range(min(len(salida), len(esperado)))]
    if not pares:
        return {c: 0.0 for c in esperado.columns}
    return {c: round(100 * sum(c in salida.columns and normalizar(esperado.iloc[i][c]) == normalizar(salida.iloc[j][c])
                               for i, j in pares) / len(pares), 1) for c in esperado.columns}


def _lectura(par, esperado, proveedor, modelo, caja, previa=None) -> dict:
    inicio = time.time()
    p = lectura.proponer(par.grilla, proveedor, modelo, esperado, previa)
    costo = caja.cobrar(par.nombre, p.modelo or modelo, p.tokens_entrada, p.tokens_salida, p.vueltas, p.logrado)
    return {"modelo": p.modelo or modelo, "logrado": p.logrado, "medida": p.medida, "entrada": p.entrada,
            "problemas": p.problemas, "vueltas": p.vueltas, "segundos": round(time.time() - inicio, 1),
            "costo": costo, "_propuesta": p}


def _reglas(par, receta, ejemplo, proveedor, fuerte, caja) -> dict:
    inicio = time.time()
    p = asistente.pedir(receta, ejemplo.entrada, PEDIDO, proveedor, [ejemplo], objetivo=ejemplo.nombre,
                        orden_columnas=list(ejemplo.esperado.columns), fuerte=fuerte)
    modelo = p.modelo or (SONNET if fuerte else HAIKU)
    costo = caja.cobrar(par.nombre, modelo, p.tokens_entrada, p.tokens_salida, p.vueltas, p.logrado)
    antes = p.antes.ejemplos.get(ejemplo.nombre, 0) if p.antes else 0
    despues = p.despues.ejemplos.get(ejemplo.nombre, antes) if p.despues else antes
    final = m.Senal(**p.receta) if p.receta else receta
    columnas = por_columna(correr(final, ejemplo.entrada)[0], ejemplo.esperado, ejemplo.pares)
    peores = sorted(columnas.items(), key=lambda x: x[1])[:COLUMNAS_PEORES]
    return {"modelo": modelo, "logrado": p.logrado, "antes": antes, "despues": despues,
            "tarjetas": len(final.tarjetas), "vueltas": p.vueltas, "peores": peores, "problemas": p.problemas[:3],
            "explicacion": p.explicacion,
            "segundos": round(time.time() - inicio, 1), "costo": costo, "_receta": p.receta}


def probar_par(par: Par, proveedor, caja: Caja, pasos=PASOS, avisar: Callable[[str], None] = lambda _: None) -> dict:
    esperado = pd.read_excel(io.BytesIO(par.esperado), dtype=object) if par.esperado else None
    detectada = inputs.detectar(par.grilla)
    medida = controles.lectura(inputs.leer(par.grilla, detectada), esperado)
    resultado = {"nombre": par.nombre, "senal_id": par.senal_id,
                 "codigo": {"medida": medida, "problemas": controles.problemas_de_lectura(medida)}}
    if "diagnostico" in pasos:
        avisar(f"{par.nombre} · diagnóstico")
        resultado["diagnostico"] = diagnostico.diagnosticar(par.grilla, esperado, par.entrada)
    lecturas = []
    if "lectura" in pasos:
        avisar(f"{par.nombre} · lectura con Haiku")
        haiku = _lectura(par, esperado, proveedor, HAIKU, caja)
        avisar(f"{par.nombre} · lectura con Sonnet")
        sonnet = _lectura(par, esperado, proveedor, SONNET, caja)
        escalera = None
        if not haiku["logrado"]:
            avisar(f"{par.nombre} · lectura con Sonnet desde lo de Haiku")
            escalera = _lectura(par, esperado, proveedor, SONNET, caja, haiku["_propuesta"])
        resultado["lectura"] = {"haiku": haiku, "sonnet": sonnet, "escalera": escalera}
        lecturas = [haiku, sonnet, escalera]

    if "reglas" not in pasos or esperado is None:
        return resultado
    # Las reglas se arman sobre una lectura que pasó los controles: la del código, o la primera del agente que pasó.
    buena = detectada if not resultado["codigo"]["problemas"] else next(
        (lectura.ENTRADA.validate_python(x["entrada"]) for x in lecturas if x and x["logrado"]), None)
    if buena is None:
        resultado["reglas"] = {"error": "Ninguna lectura pasó los controles: " + "; ".join(resultado["codigo"]["problemas"])}
        return resultado
    receta = m.Senal(id="banco", nombre=par.nombre, entrada=buena, tarjetas=[], salida=m.Salida(columnas=[]))
    ejemplo = asistente.Ejemplo(par.nombre, inputs.leer(par.grilla, buena), esperado)
    avisar(f"{par.nombre} · reglas con Haiku")
    haiku = _reglas(par, receta, ejemplo, proveedor, False, caja)
    avisar(f"{par.nombre} · reglas con Sonnet")
    sonnet = _reglas(par, receta, ejemplo, proveedor, True, caja)
    escalera = None
    if haiku["despues"] < UMBRAL_REGLAS and haiku["_receta"]:
        avisar(f"{par.nombre} · reglas con Sonnet desde lo de Haiku")
        escalera = _reglas(par, m.Senal(**haiku["_receta"]), ejemplo, proveedor, True, caja)
    resultado["reglas"] = {"haiku": haiku, "sonnet": sonnet, "escalera": escalera}
    return resultado


def limpio(x):
    """El resultado sin lo interno (propuestas y recetas enteras), para guardarlo o mostrarlo."""
    if isinstance(x, dict):
        return {k: limpio(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, (list, tuple)):
        return [limpio(v) for v in x]
    return x


def resumen(resultados: list[dict]) -> dict:
    """Cuántas veces alcanzó Haiku, cuántas Sonnet y cuántas recuperó la escalera, por paso."""
    cuenta = {}
    for paso, logro in (("lectura", lambda x: x["logrado"]), ("reglas", lambda x: x["despues"] >= UMBRAL_REGLAS)):
        filas = [r[paso] for r in resultados if isinstance(r.get(paso), dict) and "haiku" in r[paso]]
        cuenta[paso] = {"senales": len(filas), "haiku": sum(logro(f["haiku"]) for f in filas),
                        "sonnet": sum(logro(f["sonnet"]) for f in filas),
                        "escalera": sum(bool(f["escalera"]) and logro(f["escalera"]) for f in filas)}
    cuenta["diagnostico"] = diagnostico.resumen([r["diagnostico"] for r in resultados if r.get("diagnostico")])
    return cuenta


def _donde(e: Exception) -> str:
    """El archivo y la línea de la app donde saltó el error, para encontrarlo sin los logs."""
    marcos = [f for f in traceback.extract_tb(e.__traceback__) if "/app/" in f.filename.replace("\\", "/")]
    return f" (en {Path(marcos[-1].filename).name}:{marcos[-1].lineno})" if marcos else ""


def correr_banco(pares: list[Par], proveedor, caja: Caja, pasos=PASOS,
                 avisar: Callable[[str, list[dict]], None] = lambda *_: None) -> tuple[list[dict], str | None]:
    """(resultados, motivo del corte o None). Cada señal que termina se avisa con los resultados hasta ahí."""
    resultados: list[dict] = []
    for n, par in enumerate(pares, 1):
        try:
            resultados.append(limpio(probar_par(par, proveedor, caja, pasos,
                                                lambda texto: avisar(f"Señal {n} de {len(pares)} · {texto}", resultados))))
        except TopeDeGasto as e:
            return resultados, str(e)
        except cliente.ErrorAgente as e:
            resultados.append({"nombre": par.nombre, "senal_id": par.senal_id, "error": str(e)})
        except Exception as e:  # una grilla rota no tira abajo el resto del banco
            resultados.append({"nombre": par.nombre, "senal_id": par.senal_id, "error": f"{type(e).__name__}: {e}{_donde(e)}"})
        avisar(f"Señal {n} de {len(pares)} lista", resultados)
    return resultados, None
