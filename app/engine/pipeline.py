"""Aplica las tarjetas en orden sobre una tabla y arma la salida."""
from dataclasses import dataclass, field

import pandas as pd

from app.engine import model as m
from app.engine.tarjetas import criterios, estructura, texto
from app.engine.util import ErrorTarjeta, mascara

DE_TEXTO = {
    "limpiar_espacios": texto.limpiar_espacios,
    "reemplazar": texto.reemplazar,
    "quitar": texto.quitar,
    "separar": texto.separar,
    "extraer": texto.extraer,
    "mayus_minus": texto.mayus_minus,
    "asignar": texto.asignar,
    "a_numero": texto.a_numero,
    "correcciones": texto.correcciones,
    "criterios": criterios.criterios,
}
DE_ESTRUCTURA = {
    "renombrar": estructura.renombrar,
    "numerar": estructura.numerar,
    "redondear_hora": estructura.redondear_hora,
    "dia_semana": estructura.dia_semana,
    "duracion": estructura.duracion,
    "clasificar_sinopsis": estructura.clasificar_sinopsis,
    "convertir_zona": estructura.convertir_zona,
}


@dataclass
class InformeTarjeta:
    id: str
    celdas_cambiadas: int = 0
    error: str | None = None
    avisos: list[str] = field(default_factory=list)
    columnas: list[str] = field(default_factory=list)  # las que quedan después de esta tarjeta


@dataclass
class Resultado:
    tabla: pd.DataFrame
    informes: list[InformeTarjeta] = field(default_factory=list)


def aplicar(tabla: pd.DataFrame, tarjetas: list[m.Tarjeta], titulos: list[str] = ()) -> Resultado:
    """Corre las tarjetas activas. Una tarjeta con error se saltea y las demás siguen.

    `titulos` son los títulos conocidos de la señal: se suman a los de cada tarjeta `separar` y `criterios`.
    """
    df = tabla.copy().astype(object)
    informes = []
    for t in tarjetas:
        if t.tipo in ("separar", "criterios") and titulos:
            t = t.model_copy(update={"titulos": [*t.titulos, *titulos]})
        informe = InformeTarjeta(t.id)
        informes.append(informe)
        informe.columnas = list(df.columns)
        if not t.activa:
            continue
        try:
            nuevo = _aplicar_una(df.copy(), t)
        except ErrorTarjeta as e:
            informe.error = str(e)
            continue
        except Exception as e:  # una tarjeta con un caso que no contempla no frena a las demás
            informe.error = f"Falló con estos datos ({type(e).__name__}: {e})"[:500]
            continue
        if isinstance(nuevo, tuple):  # algunas tarjetas devuelven (tabla, avisos)
            nuevo, informe.avisos = nuevo
        # Una columna nueva de números (duración) tiene que poder recibir texto de la tarjeta siguiente.
        nuevo = nuevo.astype(object)
        informe.celdas_cambiadas = _contar_cambios(df, nuevo)
        informe.columnas = list(nuevo.columns)
        df = nuevo
    return Resultado(df, informes)


def _aplicar_una(df: pd.DataFrame, t) -> pd.DataFrame:
    if t.tipo in DE_ESTRUCTURA:
        if t.si is not None:
            raise ErrorTarjeta("Esta tarjeta trabaja sobre toda la tabla y no admite condición")
        return DE_ESTRUCTURA[t.tipo](df, t)
    return DE_TEXTO[t.tipo](df, t, mascara(df, t.si))


def _contar_cambios(antes: pd.DataFrame, despues: pd.DataFrame) -> int:
    cambios = 0
    for col in despues.columns:
        if col not in antes.columns:
            cambios += int(despues[col].notna().sum())
            continue
        a, d = antes[col], despues[col]
        cambios += int((~((a == d) | (a.isna() & d.isna()))).sum())
    return cambios


def armar_salida(df: pd.DataFrame, salida: m.Salida) -> pd.DataFrame:
    """Deja solo las columnas de salida, en ese orden. Las que no existen salen vacías.

    Sin columnas de salida definidas (señal nueva) se ven todas.
    """
    if not salida.columnas:
        return df
    return pd.DataFrame({c: df[c] if c in df.columns else None for c in salida.columnas}, index=df.index)


def correr(senal: m.Senal, tabla: pd.DataFrame) -> tuple[pd.DataFrame, list[InformeTarjeta]]:
    r = aplicar(tabla, senal.tarjetas, senal.titulos_conocidos)
    return armar_salida(r.tabla, senal.salida), r.informes
