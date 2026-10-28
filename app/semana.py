"""La semana subida, fila por fila: de la base, nueva lista para entrar sola, o para revisar."""
import pandas as pd

from app.catalogo import clave
from app.engine import model as m
from app.engine import titulos
from app.pautas import normalizar

PROGRAMA_CATALOGO = ("tit orig", "tit princ", "tit ing")
NIVELES_QUE_FRENAN = {"error", "aviso"}
# Lo que identifica a un capítulo, en el orden en que se muestra en Revisar.
CLAVES_TITULO = ("tit orig", "tit princ", "tit ing", "tit port")
CLAVES_CAPITULO = ("nro temp", "nro cap", "tit cap orig", "tit cap princ", "tit cap", "tit cap ing", "tit cap port")
# Para señales sin las columnas del catálogo (Programa, Capitulo...).
CLAVES_SUELTAS = ("temporada", "capitulo", "episodio", "numero")
# Más corta que esto, una sinopsis repetida ("Concierto", "Música") no dice nada.
MIN_SINOPSIS = 20


def columna_programa(columnas: list[str], v: m.Validaciones) -> str | None:
    if v.programa and v.programa in columnas:
        return v.programa
    por_clave = {clave(c): c for c in columnas}
    return next((por_clave[k] for k in PROGRAMA_CATALOGO if k in por_clave), None) or titulos.detectar_columna(columnas)


def programas_de_la_base(base: dict[str, dict], columna: str | None) -> list[str]:
    if not columna:
        return []
    vistos = {}
    for pauta in base.values():
        valor = pauta["salida"].get(columna)
        if isinstance(valor, str) and valor.strip():
            vistos.setdefault(normalizar(valor), " ".join(valor.split()))
    return sorted(vistos.values())


def campos_clave(columnas: list[str], programa: str | None) -> list[str]:
    """Las columnas que identifican a un capítulo: las únicas que Revisar muestra de entrada."""
    por_clave = {clave(c): c for c in columnas}
    titulos = [por_clave[k] for k in CLAVES_TITULO if k in por_clave]
    capitulo = [por_clave[k] for k in CLAVES_CAPITULO if k in por_clave]
    if titulos:
        return titulos + capitulo
    sueltas = [por_clave[k] for k in CLAVES_SUELTAS if k in por_clave]
    return [c for c in [programa, *capitulo, *sueltas] if c]


def completar_titulos(df: pd.DataFrame, crear: bool) -> pd.DataFrame:
    """Tit orig y Tit princ van siempre juntos: si una fila trae uno solo, el otro es el mismo.

    Con `crear`, si la salida tiene solo una de las dos columnas, se agrega la otra.
    """
    por_clave = {clave(c): c for c in df.columns}
    orig, princ = por_clave.get("tit orig"), por_clave.get("tit princ")
    if not orig and not princ or (not crear and not (orig and princ)):
        return df
    df = df.copy()
    orig, princ = orig or "Tit orig", princ or "Tit princ"
    for col in (orig, princ):
        if col not in df.columns:
            df[col] = None
    vacia = lambda v: v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())
    for i in df.index:
        a, b = df.at[i, orig], df.at[i, princ]
        if vacia(a) and not vacia(b):
            df.at[i, orig] = b
        elif vacia(b) and not vacia(a):
            df.at[i, princ] = a
    return df


def _nombre_capitulo(fila: dict, capitulo: list[str]) -> str:
    """El título del capítulo si hay; si no, su número."""
    for c in capitulo:
        if any(p in clave(c) for p in ("cap", "episodio")) and "nro" not in clave(c) and fila.get(c) not in (None, ""):
            return str(fila[c])
    numero = next((fila[c] for c in capitulo if "nro cap" in clave(c) or clave(c) == "numero"), None)
    return f"capítulo {numero}" if numero not in (None, "") else "otro capítulo"


def sinopsis_repetidas(salida: pd.DataFrame, base: list[dict], programa: str | None, capitulo: list[str]
                       ) -> dict[int, str]:
    """Filas cuya sinopsis de capítulo es la misma que la de otro capítulo del mismo programa.

    Se compara contra la semana y contra la base. Si dos capítulos distintos comparten sinopsis,
    en realidad es el argumento del programa.
    """
    sinopsis = [c for c in salida.columns if clave(c).startswith("sin")]
    if not programa or programa not in salida.columns or not capitulo or not sinopsis:
        return {}
    filas = salida.to_dict("records")
    vistos: dict[tuple, dict[tuple, str]] = {}
    for fila in [*base, *filas]:
        prog = normalizar(fila.get(programa))
        cap = tuple(normalizar(fila.get(c)) for c in capitulo)
        if not prog or not any(cap):
            continue
        for col in sinopsis:
            texto = normalizar(fila.get(col))
            if len(texto) >= MIN_SINOPSIS:
                vistos.setdefault((prog, col, texto), {}).setdefault(cap, _nombre_capitulo(fila, capitulo))
    motivos = {}
    for i, fila in enumerate(filas):
        prog = normalizar(fila.get(programa))
        propio = tuple(normalizar(fila.get(c)) for c in capitulo)
        for col in sinopsis:
            otros = [n for cap, n in vistos.get((prog, col, normalizar(fila.get(col))), {}).items() if cap != propio]
            if otros:
                motivos[i] = (f"{col}: misma sinopsis que {' y '.join(f'«{n}»' for n in otros[:2])}; "
                              "si es del programa, va como argumento de programa")
                break
    return motivos


def clasificar(salida: pd.DataFrame, estados: list[str], avisos: list, informes: list,
               programas: list[str], columna: str | None, extras: dict[int, str] | None = None) -> list[dict]:
    """Grupo de cada fila (`base` | `nueva_lista` | `revisar`) y por qué hay que revisarla."""
    conocidos = {normalizar(p) for p in programas}
    por_fila: dict[int, list[str]] = {}
    for a in avisos:
        if a.fila and a.nivel in NIVELES_QUE_FRENAN:
            por_fila.setdefault(a.fila - 1, []).append(a.mensaje)
    # Si una regla falló, ninguna fila nueva salió como se esperaba.
    de_reglas = [f"Regla con error: {i.error}" for i in informes if i.error]

    filas = []
    for i, estado in enumerate(estados):
        if estado != "nueva":
            filas.append({"grupo": "base", "motivos": []})
            continue
        motivos = list(de_reglas)
        if columna is None:
            motivos.append("No se encontró la columna de programa")
        else:
            programa = salida.iloc[i][columna] if columna in salida.columns else None
            if not isinstance(programa, str) or not programa.strip():
                motivos.append(f"{columna} vacío")
            elif normalizar(programa) not in conocidos:
                motivos.append(f"Programa nuevo: {' '.join(programa.split())}")
        motivos += por_fila.get(i, [])
        if extras and i in extras:
            motivos.append(extras[i])
        filas.append({"grupo": "revisar" if motivos else "nueva_lista", "motivos": motivos})
    return filas


def agrupar(clasificacion: list[dict], hashes: list[str], grupo: str) -> list[dict]:
    """Las filas de un grupo juntadas por pauta: un programa que sale 5 veces se revisa una vez."""
    por_hash: dict[str, dict] = {}
    for i, (c, h) in enumerate(zip(clasificacion, hashes)):
        if c["grupo"] != grupo:
            continue
        g = por_hash.setdefault(h, {"hash": h, "filas": [], "motivos": []})
        g["filas"].append(i)
        g["motivos"] += [x for x in c["motivos"] if x not in g["motivos"]]
    return list(por_hash.values())
