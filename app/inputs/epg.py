"""EPG crudo: la tabla de una página web pasada a columnas fijas, antes de las reglas y la base."""
import datetime as dt
import re

import pandas as pd

COLUMNAS = ["Fecha", "Hora", "Duración", "Título", "Episodio", "Temporada", "Número", "Sinopsis", "Año", "Extras"]
# Lo que no entra en una columna fija va acá, para no perderlo. No cuenta para el hash: suele traer ids y links.
EXTRAS = "Extras"

# Palabras del nombre de la columna de la página que delatan cada columna fija, de la más a la menos segura.
PISTAS = {
    "Título": ["show", "program", "programa", "titulo", "title column", "title", "name", "nombre"],
    "Episodio": ["episode title", "episode", "episodio", "subtitle", "capitulo"],
    "Temporada": ["season", "temporada"],
    "Número": ["episode number", "number", "numero", "nro"],
    "Sinopsis": ["synopsis", "sinopsis", "description", "descripcion", "summary"],
    "Año": ["year", "anio", "ano"],
    "Duración": ["duration", "duracion", "dur", "end"],
}
# Columnas que nunca son texto del programa, aunque su nombre lo parezca ("program-id", "image-url").
NO_SON_TEXTO = {"id", "url", "image", "img", "video", "link", "src", "href", "thumbnail"}
# Para el comienzo: la hora de la costa este manda; la que arma el navegador queda última porque depende de dónde se abrió.
PISTAS_INICIO = ["eastern", "utc", "start", "inicio", "timestamp", "date", "fecha", "time", "hora"]


def _palabras(nombre: str) -> str:
    return " ".join(re.findall(r"[a-z]+", nombre.lower().replace("data-", "")))


def _vacia(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def _momento(v) -> dt.datetime | None:
    """Fecha y hora juntas ("2026-10-23 00:00:00", "2026-10-20T01:00:00")."""
    if not isinstance(v, str) or not re.match(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}", v):
        return None
    m = pd.to_datetime(v.strip(), errors="coerce")
    return None if pd.isna(m) else m.to_pydatetime().replace(tzinfo=None)


def _fecha(v) -> dt.datetime | None:
    if isinstance(v, str) and re.match(r"^\s*\d{4}-\d{2}-\d{2}", v):
        f = pd.to_datetime(v.strip()[:10], errors="coerce")
        return None if pd.isna(f) else f.to_pydatetime()
    return None


def _hora(v) -> dt.time | None:
    if not isinstance(v, str):
        return None
    texto = v.strip().upper().replace(".", "")
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p", "%I%p"):
        try:
            return dt.datetime.strptime(texto, fmt).time()
        except ValueError:
            pass
    return None


def _mayoria(serie: pd.Series, convertir) -> bool:
    valores = [v for v in serie if not _vacia(v)]
    return bool(valores) and sum(convertir(v) is not None for v in valores) > len(valores) / 2


def _por_pistas(libres: list[str], pistas: list[str]) -> str | None:
    for pista in pistas:
        for c in libres:
            if pista in _palabras(c):
                return c
    return None


def proponer(tabla: pd.DataFrame) -> dict[str, str]:
    """De qué columna de la página sale cada columna fija, mirando nombres y contenido."""
    mapa: dict[str, str] = {}
    con_datos = [c for c in tabla.columns if not all(_vacia(v) for v in tabla[c])]
    momentos = [c for c in con_datos if _mayoria(tabla[c], _momento)]
    inicio = _por_pistas([c for c in momentos if "end" not in _palabras(c)], PISTAS_INICIO)
    if inicio:
        mapa["Fecha"] = mapa["Hora"] = inicio
    else:
        fecha = _por_pistas([c for c in con_datos if _mayoria(tabla[c], _fecha)], PISTAS_INICIO)
        hora = _por_pistas([c for c in con_datos if _mayoria(tabla[c], _hora)], PISTAS_INICIO)
        mapa |= {k: v for k, v in (("Fecha", fecha), ("Hora", hora)) if v}
    usadas = set(mapa.values()) | {c for c in con_datos if _mayoria(tabla[c], _hora) or _mayoria(tabla[c], _momento)}
    for fija, pistas in PISTAS.items():
        libres = [c for c in con_datos if c not in usadas or (fija == "Duración" and c in momentos and c != inicio)]
        if fija != "Duración":
            libres = [c for c in libres if not NO_SON_TEXTO & set(_palabras(c).split())]
        if fija == "Título":  # "episode title" también dice title: el del programa no puede ser el del capítulo
            libres = [c for c in libres if not any(p in _palabras(c) for p in ("episode", "episodio", "capitulo"))]
        elegida = _por_pistas(libres, pistas)
        if elegida:
            mapa[fija] = elegida
            usadas.add(elegida)
    return mapa


def _duracion(v, inicio: dt.datetime | None):
    """Minutos: un número tal cual, o la diferencia si la página da la hora de fin."""
    fin = _momento(v)
    if fin and inicio:
        return round((fin - inicio).total_seconds() / 60)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None if _vacia(v) else v


def armar(tabla: pd.DataFrame, mapa: dict[str, str], exigir: bool = True) -> pd.DataFrame:
    """La tabla de la página con las columnas fijas. Con `exigir`, una columna del mapa que falta es un error."""
    faltan = sorted({c for c in mapa.values() if c not in tabla.columns})
    if exigir and faltan:
        raise ValueError(f"La página ya no trae {', '.join(faltan)}: cambió su HTML y hay que revisar el EPG crudo")
    sobrantes = [c for c in tabla.columns if c not in set(mapa.values())]
    filas = []
    for fila in tabla.to_dict("records"):
        def de(fija):
            return fila.get(mapa[fija]) if fija in mapa else None

        inicio = _momento(de("Fecha"))
        nueva = {
            "Fecha": inicio.replace(hour=0, minute=0, second=0) if inicio else _fecha(de("Fecha")),
            "Hora": (_momento(de("Hora")) or inicio).time() if _momento(de("Hora")) or inicio else _hora(de("Hora")),
            "Duración": _duracion(de("Duración"), _momento(de("Hora")) or inicio),
        }
        for fija in ("Título", "Episodio", "Temporada", "Número", "Sinopsis", "Año"):
            v = de(fija)
            nueva[fija] = None if _vacia(v) else " ".join(str(v).split())
        extras = [f"{c}: {' '.join(str(fila[c]).split())}" for c in sobrantes if not _vacia(fila.get(c))]
        nueva[EXTRAS] = "; ".join(extras) or None
        filas.append(nueva)
    return pd.DataFrame(filas, columns=COLUMNAS).astype(object).where(lambda d: d.notna(), None)
