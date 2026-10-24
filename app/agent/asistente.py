"""Bucle del asistente: Claude propone tarjetas, el motor las prueba y, si algo falla, le pide que corrija.

Nunca aplica nada: devuelve una propuesta que la persona acepta o descarta.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pydantic import TypeAdapter, ValidationError

from app import export
from app.agent.cliente import Proveedor
from app.engine import model as m
from app.engine.comparar import diferencias, porcentaje_igual
from app.engine.pipeline import correr
from app.validate import grilla

MAX_VUELTAS = 3
FILAS_MUESTRA = 15
MAX_DIFERENCIAS = 30
LISTA_TARJETAS = TypeAdapter(list[m.Tarjeta])


@dataclass
class Ejemplo:
    nombre: str
    entrada: pd.DataFrame
    esperado: pd.DataFrame


@dataclass
class Metricas:
    errores_tarjetas: int
    validaciones: dict[str, int]
    ejemplos: dict[str, float]


@dataclass
class Propuesta:
    logrado: bool
    explicacion: str = ""
    receta: dict | None = None
    cambios: list[dict] = field(default_factory=list)
    antes: Metricas | None = None
    despues: Metricas | None = None
    problemas: list[str] = field(default_factory=list)  # lo que quedó sin resolver en la última vuelta
    vueltas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0


def sistema() -> str:
    texto = (Path(__file__).parent / "prompts" / "sistema.md").read_text(encoding="utf-8")
    return texto + json.dumps(TypeAdapter(m.Tarjeta).json_schema(), ensure_ascii=False)


def medir(receta: m.Senal, tabla: pd.DataFrame, ejemplos: list[Ejemplo]) -> tuple[Metricas, dict]:
    """Métricas de la receta y el detalle que se le muestra al modelo si hay que corregir."""
    salida, informes = correr(receta, tabla)
    errores = [f"tarjeta {i.id}: {i.error}" for i in informes if i.error]
    validacion = grilla.validar(salida, receta.validaciones, receta.titulos_conocidos)
    porcentajes, difs = {}, {}
    for e in ejemplos:
        sal_e, _ = correr(receta, e.entrada)
        porcentajes[e.nombre] = round(porcentaje_igual(sal_e, e.esperado), 2)
        difs[e.nombre] = diferencias(sal_e, e.esperado)[:MAX_DIFERENCIAS]
    detalle = {"salida": salida, "errores": errores, "validacion": validacion, "diferencias": difs}
    return Metricas(len(errores), grilla.resumen(validacion), porcentajes), detalle


def pedir(receta: m.Senal, tabla: pd.DataFrame, pedido: str, proveedor: Proveedor,
          ejemplos: list[Ejemplo] = (), objetivo: str | None = None, orden_columnas: list[str] = ()) -> Propuesta:
    """`objetivo` = nombre de un ejemplo que tiene que llegar al 100 % ("armar desde este ejemplo")."""
    antes, detalle = medir(receta, tabla, ejemplos)
    contexto = _contexto(receta, tabla, detalle, antes, ejemplos, pedido, objetivo, orden_columnas)
    mensajes = [{"role": "user", "content": contexto}]
    effort = "medium" if objetivo else "low"
    resultado = Propuesta(logrado=False, antes=antes)

    for vuelta in range(1, MAX_VUELTAS + 1):
        r = proveedor.pedir(sistema(), mensajes, effort)
        resultado.vueltas = vuelta
        resultado.tokens_entrada += r.tokens_entrada
        resultado.tokens_salida += r.tokens_salida
        if r.rechazo:
            resultado.problemas = [f"El asistente no quiso responder este pedido ({r.rechazo})."]
            return resultado

        nueva, problemas = _leer_propuesta(r.datos, receta)
        if nueva is not None:
            despues, detalle_nuevo = medir(nueva, tabla, ejemplos)
            problemas = _problemas(antes, detalle["errores"], despues, detalle_nuevo, objetivo)
            resultado.explicacion = r.datos.get("explicacion", "")
            resultado.receta = nueva.model_dump(exclude_none=True)
            resultado.cambios = cambios(receta, nueva)
            resultado.despues = despues
        resultado.problemas = problemas
        if not problemas:
            resultado.logrado = True
            return resultado
        mensajes += [
            {"role": "assistant", "content": r.texto or "(respuesta vacía)"},
            {"role": "user", "content": "Probé tu propuesta y pasó esto:\n- " + "\n- ".join(problemas)
                                        + "\n\nCorregí y devolvé la lista completa de tarjetas otra vez."},
        ]
    return resultado


def _leer_propuesta(datos: dict | None, receta: m.Senal) -> tuple[m.Senal | None, list[str]]:
    if not isinstance(datos, dict):
        return None, ["La respuesta no fue un JSON válido con explicacion, tarjetas_json y columnas_salida."]
    try:
        tarjetas = LISTA_TARJETAS.validate_json(datos.get("tarjetas_json") or "")
    except ValidationError as e:
        errores = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:10])
        return None, [f"tarjetas_json no cumple el schema: {errores}"]
    ids = [t.id for t in tarjetas]
    if len(ids) != len(set(ids)):
        return None, ["Hay tarjetas con el mismo id: cada tarjeta necesita un id distinto."]
    cambios_receta = {"tarjetas": tarjetas}
    if datos.get("columnas_salida") is not None:
        cambios_receta["salida"] = m.Salida(columnas=datos["columnas_salida"])
    return receta.model_copy(update=cambios_receta), []


def _problemas(antes: Metricas, errores_antes: list[str], despues: Metricas, detalle: dict,
               objetivo: str | None) -> list[str]:
    # Solo cuentan los errores que trajo la propuesta: los que ya estaban no son culpa de este pedido.
    problemas = [e for e in detalle["errores"] if e not in errores_antes]
    for nombre, pct in despues.ejemplos.items():
        exigido = 100.0 if nombre == objetivo else antes.ejemplos[nombre]
        if pct < exigido:
            difs = "; ".join(f"fila {d['fila'] + 1}, {d['columna']}: quedó {_txt(d['obtenido'])} "
                             f"y tenía que quedar {_txt(d['esperado'])}" for d in detalle["diferencias"][nombre][:15])
            motivo = "tiene que llegar al 100 %" if nombre == objetivo else f"antes daba {exigido} %"
            problemas.append(f"El ejemplo {nombre} da {pct} % ({motivo}). Diferencias: {difs}")
    if despues.validaciones["error"] > antes.validaciones["error"]:
        nuevos = [a.mensaje for a in detalle["validacion"] if a.nivel == "error"][:10]
        problemas.append(f"Las validaciones pasaron de {antes.validaciones['error']} a "
                         f"{despues.validaciones['error']} errores: {'; '.join(nuevos)}")
    return problemas


def cambios(antes: m.Senal, despues: m.Senal) -> list[dict]:
    """Qué tarjetas se agregan, modifican o borran, para mostrarlo sin leer JSON."""
    viejas = {t.id: t.model_dump(exclude_none=True) for t in antes.tarjetas}
    nuevas = {t.id: t.model_dump(exclude_none=True) for t in despues.tarjetas}
    lista = []
    for id_, t in nuevas.items():
        if id_ not in viejas:
            lista.append({"tipo": "agregada", "id": id_, "tarjeta": t})
        elif t != viejas[id_]:
            campos = sorted(k for k in set(t) | set(viejas[id_]) if t.get(k) != viejas[id_].get(k))
            lista.append({"tipo": "modificada", "id": id_, "tarjeta": t, "campos": campos})
    lista += [{"tipo": "borrada", "id": id_, "tarjeta": t} for id_, t in viejas.items() if id_ not in nuevas]
    if antes.salida.columnas != despues.salida.columnas:
        lista.append({"tipo": "salida", "id": "", "columnas": despues.salida.columnas})
    orden_viejo = [i for i in viejas if i in nuevas]
    if orden_viejo != [i for i in nuevas if i in viejas]:
        lista.append({"tipo": "orden", "id": ""})
    return lista


def _contexto(receta, tabla, detalle, antes: Metricas, ejemplos, pedido, objetivo, orden_columnas=()) -> str:
    partes = [
        "## Receta actual",
        json.dumps({"tarjetas": [t.model_dump(exclude_none=True) for t in receta.tarjetas],
                    "columnas_salida": receta.salida.columnas,
                    "cantidad_titulos_conocidos": len(receta.titulos_conocidos)}, ensure_ascii=False),
        f"## Grilla de entrada: columnas {list(map(str, tabla.columns))}",
        _filas(tabla),
        f"## Salida actual ({len(detalle['salida'])} filas)",
        _filas(detalle["salida"]),
    ]
    if detalle["errores"]:
        partes += ["## Tarjetas con error", "\n".join(detalle["errores"])]
    errores_validacion = [a.mensaje for a in detalle["validacion"] if a.nivel != "info"][:10]
    if errores_validacion:
        partes += ["## Validaciones con problemas", "\n".join(errores_validacion)]
    for e in ejemplos:
        difs = detalle["diferencias"][e.nombre]
        partes.append(f"## Ejemplo {e.nombre}: hoy coincide {antes.ejemplos[e.nombre]} %")
        if e.nombre == objetivo:
            partes += [f"Así tiene que quedar (columnas {list(map(str, e.esperado.columns))}):", _filas(e.esperado)]
        if difs:
            partes.append("Diferencias: " + "; ".join(
                f"fila {d['fila'] + 1}, {d['columna']}: quedó {_txt(d['obtenido'])} y tenía que quedar {_txt(d['esperado'])}"
                for d in difs))
    if orden_columnas:
        partes += ["## Orden general de columnas del EPG",
                   "Si agregás columnas o cambiás columnas_salida, respetá este orden: " + ", ".join(orden_columnas)]
    partes += ["## Pedido", pedido]
    return "\n\n".join(partes)


def _filas(df: pd.DataFrame) -> str:
    columnas = list(map(str, df.columns))
    return "\n".join(json.dumps(dict(zip(columnas, f)), ensure_ascii=False, default=str)
                     for f in export.a_filas(df, FILAS_MUESTRA))


def _txt(v) -> str:
    return "(vacío)" if v is None else json.dumps(export.celda_json(v), ensure_ascii=False, default=str)
