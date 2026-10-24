import re

import pandas as pd

from app.engine import model as m

PLANTILLA = re.compile(r"\{([^}]+)\}")


class ErrorTarjeta(Exception):
    """Error de configuración que se le muestra al usuario en la tarjeta."""


def columnas_de(df: pd.DataFrame, columnas) -> list[str]:
    if columnas == "*":
        return list(df.columns)
    faltan = [c for c in columnas if c not in df.columns]
    if faltan:
        raise ErrorTarjeta(f"No existe la columna: {', '.join(faltan)}")
    return list(columnas)


def celdas_texto(serie: pd.Series) -> pd.Series:
    return serie.map(lambda v: isinstance(v, str))


def texto(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


def rellenar_plantilla(plantilla: str, fila: pd.Series) -> str:
    def valor(r):
        if r.group(1) not in fila.index:
            raise ErrorTarjeta(f"No existe la columna: {r.group(1)}")
        return texto(fila[r.group(1)])
    return PLANTILLA.sub(valor, plantilla)


def mascara(df: pd.DataFrame, si: m.Condicion | None) -> pd.Series:
    if si is None:
        return pd.Series(True, index=df.index)
    (col,) = columnas_de(df, [si.columna])

    def cumple(fila) -> bool:
        v = texto(fila[col])
        ref = rellenar_plantilla(si.valor, fila)
        return {
            "igual": lambda: v == ref,
            "distinto": lambda: v != ref,
            "contiene": lambda: ref in v,
            "empieza": lambda: v.startswith(ref),
            "termina": lambda: v.endswith(ref),
            "vacio": lambda: v.strip() == "",
            "no_vacio": lambda: v.strip() != "",
            "regex": lambda: re.search(ref, v) is not None,
        }[si.op]()

    if df.empty:
        return pd.Series(False, index=df.index)
    return df.apply(cumple, axis=1).astype(bool)
