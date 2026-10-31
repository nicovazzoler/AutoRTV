"""Bucle del asistente: Claude propone tarjetas, el motor las prueba y, si algo falla, le pide que corrija.

Nunca aplica nada: devuelve una propuesta que la persona acepta o descarta.
"""
import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app import acciones, export
from app.agent import controles
from app.agent.cliente import Proveedor
from app.engine import model as m
from app.engine.comparar import diferencias, porcentaje_igual
from app.engine.pipeline import correr
from app.engine.tarjetas import criterios
from app.semana import columna_programa
from app.validate import grilla

MAX_VUELTAS = 3
FILAS_MUESTRA = 15
MAX_DIFERENCIAS = 30
MAX_HISTORIAL = 10  # mensajes previos de la conversación que se reenvían
MAX_LARGO_MENSAJE = 1500
LISTA_TARJETAS = TypeAdapter(list[m.Tarjeta])
FILAS_FOCO = 12  # filas para revisar que se le muestran, además de unas pocas de referencia


class CorreccionBase(BaseModel):
    """"En las pautas que cumplen `filtro`, poné `valor` en `columna`." La aplica el servidor."""
    model_config = ConfigDict(extra="forbid")
    filtro: dict[str, str]
    columna: str
    valor: str | None


LISTA_CORRECCIONES = TypeAdapter(list[CorreccionBase])


@dataclass
class Entorno:
    """Lo que el servidor sabe de la persona y de la semana, y el agente no puede averiguar solo."""
    foco: list[int] = field(default_factory=list)  # filas para revisar de la semana
    es_admin: bool = False
    reglas_catalogo: list[str] = field(default_factory=list)  # "Columna: regla"


@dataclass
class Ejemplo:
    nombre: str
    entrada: pd.DataFrame
    esperado: pd.DataFrame

    @cached_property
    def pares(self) -> list[tuple[int, int]] | None:
        return controles.pares_con_ejemplo(self.entrada, self.esperado)


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
    correcciones_base: list[dict] = field(default_factory=list)
    acciones_admin: list[dict] = field(default_factory=list)
    antes: Metricas | None = None
    despues: Metricas | None = None
    problemas: list[str] = field(default_factory=list)  # lo que quedó sin resolver en la última vuelta
    vueltas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    modelo: str = ""
    aviso: str = ""


@dataclass
class Charla:
    respuesta: str
    proponer_cambios: bool
    tokens_entrada: int = 0
    tokens_salida: int = 0
    modelo: str = ""


def sistema() -> str:
    texto = (Path(__file__).parent / "prompts" / "sistema.md").read_text(encoding="utf-8")
    return texto + json.dumps(TypeAdapter(m.Tarjeta).json_schema(), ensure_ascii=False)


def sistema_charla() -> str:
    return (Path(__file__).parent / "prompts" / "charla.md").read_text(encoding="utf-8")


def charlar(receta: m.Senal, tabla: pd.DataFrame | None, historial: list[dict], mensaje: str,
            proveedor: Proveedor) -> Charla:
    """Respuesta rápida. Si el mensaje pide cambiar reglas o columnas, avisa que hay que armar una propuesta."""
    partes = ["## Receta actual (tarjetas en orden)",
              json.dumps([t.model_dump(exclude_none=True) for t in receta.tarjetas], ensure_ascii=False)]
    if tabla is not None:
        salida, informes = correr(receta, tabla)
        errores = [f"tarjeta {i.id}: {i.error}" for i in informes if i.error]
        partes += [f"## Grilla de entrada: columnas {list(map(str, tabla.columns))}", _filas(tabla),
                   f"## Salida actual ({len(salida)} filas)", _filas(salida)]
        if errores:
            partes += ["## Tarjetas con error", "\n".join(errores)]
    else:
        partes.append("(No hay grilla subida.)")
    partes += _conversacion(historial) + ["## Mensaje nuevo", mensaje]
    r = proveedor.charlar(sistema_charla(), [{"role": "user", "content": "\n\n".join(partes)}])
    if r.rechazo:
        return Charla(f"No puedo responder eso ({r.rechazo}).", False, r.tokens_entrada, r.tokens_salida, r.modelo)
    datos = r.datos if isinstance(r.datos, dict) else {}
    return Charla(str(datos.get("respuesta", "")), bool(datos.get("proponer_cambios", not datos)),
                  r.tokens_entrada, r.tokens_salida, r.modelo)


def _conversacion(historial: list[dict]) -> list[str]:
    """Últimos mensajes de la conversación, como texto: el asistente no guarda nada entre pedidos."""
    if not historial:
        return []
    lineas = [f"{'Persona' if h.get('rol') == 'persona' else 'Asistente'}: {str(h.get('texto', ''))[:MAX_LARGO_MENSAJE]}"
              for h in historial[-MAX_HISTORIAL:]]
    return ["## Conversación hasta ahora", "\n".join(lineas)]


def medir(receta: m.Senal, tabla: pd.DataFrame, ejemplos: list[Ejemplo]) -> tuple[Metricas, dict]:
    """Métricas de la receta y el detalle que se le muestra al modelo si hay que corregir."""
    salida, informes = correr(receta, tabla)
    errores = [f"tarjeta {i.id}: {i.error}" for i in informes if i.error]
    validacion = grilla.validar(salida, receta.validaciones, receta.titulos_conocidos)
    porcentajes, difs = {}, {}
    for e in ejemplos:
        sal_e, _ = correr(receta, e.entrada)
        porcentajes[e.nombre] = round(porcentaje_igual(sal_e, e.esperado, e.pares), 2)
        difs[e.nombre] = diferencias(sal_e, e.esperado, e.pares)[:MAX_DIFERENCIAS]
    detalle = {"salida": salida, "errores": errores, "validacion": validacion, "diferencias": difs}
    return Metricas(len(errores), grilla.resumen(validacion), porcentajes), detalle


def pedir(receta: m.Senal, tabla: pd.DataFrame, pedido: str, proveedor: Proveedor,
          ejemplos: list[Ejemplo] = (), objetivo: str | None = None, orden_columnas: list[str] = (),
          historial: list[dict] = (), entorno: Entorno | None = None, fuerte: bool = False) -> Propuesta:
    """`objetivo` = nombre de un ejemplo que tiene que llegar al 100 % ("armar desde este ejemplo").

    `fuerte` usa el modelo más capaz (y más caro), para cuando el barato no lo logró.
    """
    entorno = entorno or Entorno()
    receta_original = receta
    antes, detalle = medir(receta, tabla, ejemplos)
    # Armar desde cero arranca de los criterios generales: el agente suma lo propio de la señal encima.
    sembrada = con_criterios(receta, tabla, ejemplos, objetivo) if objetivo and not receta.tarjetas else None
    if sembrada is not None:
        receta = sembrada
        _, detalle = medir(receta, tabla, ejemplos)
    contexto = _contexto(receta, tabla, detalle, antes, ejemplos, pedido, objetivo, orden_columnas, historial, entorno)
    mensajes = [{"role": "user", "content": contexto}]
    effort = "medium" if objetivo else "low"
    resultado = Propuesta(logrado=False, antes=antes)

    for vuelta in range(1, MAX_VUELTAS + 1):
        r = proveedor.pedir(sistema(), mensajes, effort, fuerte)
        resultado.vueltas = vuelta
        resultado.tokens_entrada += r.tokens_entrada
        resultado.tokens_salida += r.tokens_salida
        resultado.modelo = r.modelo
        resultado.aviso = r.aviso or resultado.aviso
        if r.rechazo:
            resultado.problemas = [f"El asistente no quiso responder este pedido ({r.rechazo})."]
            return resultado

        nueva, problemas = _leer_propuesta(r.datos, receta)
        (correcciones, admin), problemas_extras = _leer_extras(r.datos, entorno)
        if nueva is not None:
            despues, detalle_nuevo = medir(nueva, tabla, ejemplos)
            problemas = _problemas(antes, detalle["errores"], despues, detalle_nuevo, objetivo)
            resultado.correcciones_base, resultado.acciones_admin = correcciones, admin
            resultado.explicacion = r.datos.get("explicacion", "")
            resultado.receta = nueva.model_dump(exclude_none=True)
            resultado.cambios = cambios(receta, nueva)
            resultado.despues = despues
        problemas += problemas_extras
        resultado.problemas = problemas
        if not problemas:
            resultado.logrado = True
            return resultado
        mensajes += [
            {"role": "assistant", "content": r.texto or "(respuesta vacía)"},
            {"role": "user", "content": "Probé tu propuesta y pasó esto:\n- " + "\n- ".join(problemas)
                                        + "\n\nCorregí y devolvé la respuesta completa otra vez."},
        ]
    if sembrada is not None and resultado.receta is None:
        # Ninguna propuesta sirvió: quedan al menos los criterios generales, si mejoran el ejemplo.
        solo, _ = medir(sembrada, tabla, ejemplos)
        if solo.ejemplos.get(objetivo, 0) > antes.ejemplos.get(objetivo, 0):
            resultado.receta, resultado.despues = sembrada.model_dump(exclude_none=True), solo
            resultado.cambios = cambios(receta_original, sembrada)
    return resultado


def con_criterios(receta: m.Senal, tabla: pd.DataFrame, ejemplos: list[Ejemplo], objetivo: str) -> m.Senal | None:
    """La receta con la tarjeta de criterios generales al principio, configurada para esta grilla y este EPG."""
    ejemplo = next((e for e in ejemplos if e.nombre == objetivo), None)
    salida = receta.salida.columnas or (list(ejemplo.esperado.columns) if ejemplo is not None else [])
    programa = columna_programa(salida, receta.validaciones) if salida else None
    tarjeta = criterios.configurar(tabla, salida, programa)
    if tarjeta is None:
        return None
    return receta.model_copy(update={"tarjetas": [tarjeta, *receta.tarjetas]})


def _leer_propuesta(datos: dict | None, receta: m.Senal) -> tuple[m.Senal | None, list[str]]:
    if not isinstance(datos, dict):
        return None, ["La respuesta no fue un JSON válido con explicacion, tarjetas_json y columnas_salida."]
    if not (datos.get("tarjetas_json") or "").strip():  # no cambia las reglas
        return receta.model_copy(), []
    try:
        tarjetas = LISTA_TARJETAS.validate_json(datos["tarjetas_json"])
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


def _leer_extras(datos: dict | None, entorno: Entorno) -> tuple[tuple[list[dict], list[dict]], list[str]]:
    """Correcciones en la base y acciones de admin que vinieron junto con la propuesta."""
    if not isinstance(datos, dict):
        return ([], []), []
    problemas = []
    correcciones, admin = [], []
    try:
        correcciones = [c.model_dump() for c in LISTA_CORRECCIONES.validate_json(datos.get("correcciones_base_json") or "[]")]
    except ValidationError as e:
        problemas.append(f"correcciones_base_json no cumple el formato: {_errores(e)}")
    try:
        admin = [a.model_dump() for a in acciones.LISTA.validate_json(datos.get("acciones_admin_json") or "[]")]
    except ValidationError as e:
        problemas.append(f"acciones_admin_json no cumple el formato: {_errores(e)}")
    if admin and not entorno.es_admin:
        problemas.append("La persona no es admin: no propongas acciones_admin, explicale que las pide un admin.")
        admin = []
    return (correcciones, admin), problemas


def _errores(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:10])


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


def _contexto(receta, tabla, detalle, antes: Metricas, ejemplos, pedido, objetivo, orden_columnas=(),
              historial=(), entorno: Entorno | None = None) -> str:
    entorno = entorno or Entorno()
    indices = _filas_a_mostrar(len(tabla), entorno.foco)
    partes = [
        "## Receta actual",
        json.dumps({"tarjetas": [t.model_dump(exclude_none=True) for t in receta.tarjetas],
                    "columnas_salida": receta.salida.columnas,
                    "cantidad_titulos_conocidos": len(receta.titulos_conocidos)}, ensure_ascii=False),
        f"## Grilla de entrada: columnas {list(map(str, tabla.columns))}",
        _filas(tabla, indices),
        f"## Salida actual ({len(detalle['salida'])} filas)",
        _filas(detalle["salida"], indices),
    ]
    if entorno.foco:
        partes.append(f"De esas filas, las que hay que revisar esta semana son: "
                      f"{', '.join(str(i + 1) for i in entorno.foco[:FILAS_FOCO])}.")
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
    partes += ["## Quién pide", "Es admin: puede aplicar acciones_admin." if entorno.es_admin
               else "No es admin: no propongas acciones_admin."]
    if entorno.es_admin and entorno.reglas_catalogo:
        partes += ["## Catálogo de columnas (columna: regla)", "\n".join(entorno.reglas_catalogo)]
    partes += _conversacion(list(historial)) + ["## Pedido", pedido]
    return "\n\n".join(partes)


def _filas_a_mostrar(total: int, foco: list[int]) -> list[int]:
    """Las primeras filas para revisar y, si sobra lugar, las primeras de la grilla como referencia."""
    elegidas = [i for i in foco if 0 <= i < total][:FILAS_FOCO]
    resto = [i for i in range(total) if i not in elegidas][:FILAS_MUESTRA - len(elegidas)]
    return sorted(elegidas + resto)


def _filas(df: pd.DataFrame, indices: list[int] | None = None) -> str:
    columnas = list(map(str, df.columns))
    datos = df.head(FILAS_MUESTRA) if indices is None else df.iloc[[i for i in indices if i < len(df)]]
    numeros = list(range(len(datos))) if indices is None else [i for i in indices if i < len(df)]
    return "\n".join(f"fila {n + 1}: " + json.dumps(dict(zip(columnas, f)), ensure_ascii=False, default=str)
                     for n, f in zip(numeros, export.a_filas(datos)))


def _txt(v) -> str:
    return "(vacío)" if v is None else json.dumps(export.celda_json(v), ensure_ascii=False, default=str)
