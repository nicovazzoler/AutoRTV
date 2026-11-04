"""Varios archivos de una misma semana, subidos juntos o en un .zip: cada uno se lee con su formato y van uno abajo
del otro, en orden de nombre."""
import datetime as dt
import io
import re
import zipfile
from pathlib import PurePosixPath

import pandas as pd

from app.engine import model as m

MAX_ARCHIVOS = 60
# Fecha completa en el nombre: 20261101, 2026-11-01 o 01-11-2026. Sin año ("(29-10)") no cuenta: en los archivos que
# llegan suele ser el día en que se recibieron, no el de la programación.
FECHA_ANIO_PRIMERO = re.compile(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)")
FECHA_DIA_PRIMERO = re.compile(r"(?<!\d)(\d{1,2})[-_.](\d{1,2})[-_.](20\d{2})(?!\d)")


def fecha_del_nombre(nombre: str) -> dt.date | None:
    """La fecha completa (con año) que trae el nombre de un archivo, o None."""
    raiz = PurePosixPath(nombre).stem
    for patron, anio, mes, dia in ((FECHA_ANIO_PRIMERO, 0, 1, 2), (FECHA_DIA_PRIMERO, 2, 1, 0)):
        for encontrada in patron.finditer(raiz):
            partes = [int(x) for x in encontrada.groups()]
            try:
                return dt.date(partes[anio], partes[mes], partes[dia])
            except ValueError:
                continue
    return None


def con_fecha(tabla: pd.DataFrame, fecha: dt.date) -> pd.DataFrame:
    """Le pone a cada fila la fecha del archivo; lo que viene después de la medianoche pasa al día siguiente."""
    from app.engine.tarjetas.estructura import a_hora

    columna = next((c for c in tabla.columns if sum(a_hora(v) is not None for v in tabla[c]) > len(tabla) / 2), None)
    dia, anterior, fechas = fecha, None, []
    for v in (tabla[columna] if columna is not None else [None] * len(tabla)):
        hora = a_hora(v)
        if hora and anterior and hora < anterior:
            dia += dt.timedelta(days=1)
        anterior = hora or anterior
        fechas.append(dt.datetime.combine(dia, dt.time()))
    tabla = tabla.copy()
    if "Fecha" in tabla.columns:
        tabla["Fecha"] = fechas
    else:
        tabla.insert(0, "Fecha", fechas)
    return tabla


def empaquetar(archivos: list[tuple[str, bytes]]) -> bytes:
    """Los archivos subidos juntos, en un zip: así la semana se guarda y se vuelve a leer como un solo contenido."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos:
            z.writestr(PurePosixPath(nombre).name or "archivo", contenido)
    return buf.getvalue()


def archivos(contenido: bytes) -> list[tuple[str, bytes]]:
    """Los archivos del zip, sin carpetas ni lo que agregan Mac y Windows; un zip adentro también se abre."""
    z = zipfile.ZipFile(io.BytesIO(contenido))
    lista = []
    for info in sorted(z.infolist(), key=lambda i: i.filename.lower()):
        nombre = PurePosixPath(info.filename)
        if info.is_dir() or "__MACOSX" in nombre.parts or nombre.name.startswith((".", "~$")) or nombre.name == "Thumbs.db":
            continue
        datos = z.read(info)
        lista += archivos(datos) if es_zip_suelto(datos) else [(nombre.name, datos)]
    if len(lista) > MAX_ARCHIVOS:
        raise ValueError(f"El zip trae {len(lista)} archivos: como mucho {MAX_ARCHIVOS} por semana")
    return lista


def es_zip_suelto(contenido: bytes) -> bool:
    """Un zip que no es un Excel ni un Word (que por dentro también son zip)."""
    if not contenido.startswith(b"PK"):
        return False
    try:
        nombres = zipfile.ZipFile(io.BytesIO(contenido)).namelist()
    except zipfile.BadZipFile:
        return False
    return not any(n.startswith(("xl/", "word/", "ppt/")) or n == "[Content_Types].xml" for n in nombres)


def leer(contenido: bytes, entrada: m.EntradaVarios) -> pd.DataFrame:
    from app import fechar, inputs

    tablas = []
    saltear = {n.strip().lower() for n in entrada.saltear}
    for nombre, datos in archivos(contenido):
        if nombre.strip().lower() in saltear:
            continue
        propia = entrada.cada_uno or inputs.detectar(datos)
        try:
            tabla = inputs.leer(datos, propia)
        except Exception as e:
            raise ValueError(f"{nombre}: {e}") from e
        # Un archivo por día sin la fecha adentro: la del nombre ("20261101-A3Cine.docx").
        if (fecha := fecha_del_nombre(nombre)) and not fechar.columnas_de_fecha(tabla):
            tabla = con_fecha(tabla, fecha)
        tablas.append(tabla)
    if not tablas:
        raise ValueError("El zip no trae archivos para leer")
    from app.pautas import tiene_horario
    grillas = [t for t in tablas if tiene_horario(t)] or tablas
    df = pd.concat(grillas, ignore_index=True).astype(object)
    for extra in (t for t in tablas if not any(t is g for g in grillas)):
        df = sumar_por_titulo(df, extra)
    return df


# Para cruzar un archivo sin horario (las sinopsis) con la grilla: cuántos de sus títulos tienen que estar en ella.
MIN_CRUCES = 3
MIN_PARTE_CRUZADA = 0.3


def _clave(v) -> str:
    from app.pautas import normalizar
    return normalizar(v) if isinstance(v, str) else ""


def sumar_por_titulo(grilla: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """Un archivo sin horario (sinopsis, fichas) se pega a la grilla por la columna de títulos que más coincide.

    Si no se encuentra cómo cruzarlo, va abajo como venía y lo resuelven las reglas o el agente.
    """
    mejor = (0, None, None)
    for cg in grilla.columns:
        titulos = {_clave(v) for v in grilla[cg]} - {""}
        if not titulos:
            continue
        for ce in extra.columns:
            cruces = sum(_clave(v) in titulos for v in extra[ce])
            if cruces > mejor[0]:
                mejor = (cruces, cg, ce)
    cruces, cg, ce = mejor
    if cruces < MIN_CRUCES or cruces < len(extra) * MIN_PARTE_CRUZADA:
        return pd.concat([grilla, extra], ignore_index=True).astype(object)
    por_titulo = {}
    for fila in extra.to_dict("records"):
        por_titulo.setdefault(_clave(fila[ce]), fila)
    grilla = grilla.copy()
    for col in [c for c in extra.columns if c != ce]:
        nombre = col if col not in grilla.columns else f"{col} ({ce})"
        grilla[nombre] = [por_titulo.get(_clave(v), {}).get(col) for v in grilla[cg]]
    return grilla.astype(object)
