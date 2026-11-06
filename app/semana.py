"""La semana subida, fila por fila: de la base, nueva lista para entrar sola, o para revisar."""
import pandas as pd

from app.catalogo import clave
from app.engine import model as m
from app.engine import titulos
from app.pautas import normalizar

PROGRAMA_CATALOGO = ("tit orig", "tit princ", "tit prog", "tit programa", "tit ing", "programa")
NIVELES_QUE_FRENAN = {"error", "aviso"}
# Lo que identifica a un capítulo, en el orden en que se muestra en Revisar.
CLAVES_TITULO = ("tit orig", "tit princ", "tit prog", "tit ing", "tit port")
CLAVES_CAPITULO = ("nro temp", "nro cap", "tit cap orig", "tit cap princ", "tit cap", "tit cap ing", "tit cap port")
# Para señales sin las columnas del catálogo (Programa, Capitulo...).
CLAVES_SUELTAS = ("temporada", "capitulo", "episodio", "numero")
# Más corta que esto, una sinopsis repetida ("Concierto", "Música") no dice nada.
MIN_SINOPSIS = 20


# Con menos pautas que esto, mirar el contenido no dice nada: se va por el nombre.
MIN_PARES = 5
# Una columna cuyos valores son, en la mitad de las filas, más cortos que esto es un código (TV-14, ATP), no un título.
MIN_LARGO_TITULO = 6


def _texto_crudo(crudo: dict) -> str:
    return normalizar(" ".join(str(v) for v in crudo.values() if v not in (None, "")))


def programa_por_contenido(pares: list[tuple[dict, dict]], columnas: list[str]) -> str | None:
    """La columna del EPG que casi siempre aparece dentro de la fila cruda: el programa, se llame como se llame.

    Si varias empatan, gana la que el catálogo llama programa, después la que no es un código corto (un rating) y por
    último la que repite más (Tit orig contra el título entero): un programa tiene muchos capítulos.
    """
    if len(pares) < MIN_PARES:
        return None
    textos = [_texto_crudo(crudo) for crudo, _ in pares]
    puntajes = []
    for c in columnas:
        valores = [normalizar(salida.get(c)) for _, salida in pares]
        dentro = [v for v, t in zip(valores, textos) if sum(ch.isalpha() for ch in v) >= 3 and v in t]
        if dentro:
            mediana = sorted(len(v) for v in dentro)[len(dentro) // 2]
            puntajes.append((len(dentro) / len(pares), len(set(dentro)), mediana, c))
    if not puntajes:
        return None
    mejor = max(p for p, _, _, _ in puntajes)
    if mejor < 0.5:
        return None
    orden = {k: i for i, k in enumerate(PROGRAMA_CATALOGO)}
    return min((orden.get(clave(c), len(orden)), mediana < MIN_LARGO_TITULO, distintos, c)
               for p, distintos, mediana, c in puntajes if p >= mejor - 0.05)[3]


def pares_de_la_base(base: dict[str, dict]) -> list[tuple[dict, dict]]:
    return [(p.get("crudo") or {}, p["salida"]) for p in base.values()]


def columna_programa(columnas: list[str], v: m.Validaciones, pares: list[tuple[dict, dict]] = ()) -> str | None:
    if v.programa and v.programa in columnas:
        return v.programa
    if por_contenido := programa_por_contenido(list(pares), columnas):
        return por_contenido
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


# Un programa visto una sola vez no dice qué columnas son suyas: hace falta ver al menos dos capítulos.
MIN_CAPITULOS = 2


def _vacia(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def columnas_del_programa(base: dict[str, dict], programa: str) -> dict[str, dict[str, object]]:
    """Por programa (normalizado), las columnas que tienen el mismo valor en todos sus capítulos de la base."""
    por_programa: dict[str, list[dict]] = {}
    for pauta in base.values():
        nombre = normalizar(pauta["salida"].get(programa))
        if nombre:
            por_programa.setdefault(nombre, []).append(pauta["salida"])
    fichas = {}
    for nombre, salidas in por_programa.items():
        if len(salidas) < MIN_CAPITULOS:
            continue
        ficha = {}
        for col in {c for s in salidas for c in s} - {programa}:
            valores = {normalizar(s.get(col)) for s in salidas}
            if len(valores) == 1 and "" not in valores:
                ficha[col] = salidas[0][col]
        fichas[nombre] = ficha
    return fichas


def completar_del_programa(df: pd.DataFrame, estados: list[str], base: dict[str, dict],
                           programa: str | None) -> pd.DataFrame:
    """Un capítulo nuevo de un programa de la base completa lo que las reglas dejaron vacío con lo que es igual en
    todos sus capítulos (género, argumento...). Lo que armaron las reglas no se pisa."""
    if not programa or programa not in df.columns or "nueva" not in estados:
        return df
    fichas = columnas_del_programa(base, programa)
    df = df.copy()
    for i, estado in zip(df.index, estados):
        ficha = fichas.get(normalizar(df.at[i, programa])) if estado == "nueva" else None
        for col, valor in (ficha or {}).items():
            if col not in df.columns:
                df[col] = None
            if _vacia(df.at[i, col]):
                df.at[i, col] = valor
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


def codigo_de_aviso(a) -> str:
    """El código de un aviso de validación, para agrupar los motivos ("catalogo:Año", "vacia:Tit orig", "duracion")."""
    if a.regla == "catalogo" and a.columna:
        return f"{'vacia' if 'vacía' in a.mensaje else 'catalogo'}:{a.columna}"
    return f"{a.regla}:{a.columna}" if a.columna else a.regla


def clasificar(salida: pd.DataFrame, estados: list[str], avisos: list, informes: list,
               programas: list[str], columna: str | None, extras: dict[int, str] | None = None) -> list[dict]:
    """Grupo de cada fila (`base` | `nueva_lista` | `revisar`), por qué hay que revisarla y el código de cada motivo."""
    conocidos = {normalizar(p) for p in programas}
    por_fila: dict[int, list[tuple[str, str]]] = {}
    for a in avisos:
        if a.fila and a.nivel in NIVELES_QUE_FRENAN:
            por_fila.setdefault(a.fila - 1, []).append((codigo_de_aviso(a), a.mensaje))
    # Si una regla falló, ninguna fila nueva salió como se esperaba.
    de_reglas = [("regla_con_error", f"Regla con error: {i.error}") for i in informes if i.error]

    filas = []
    for i, estado in enumerate(estados):
        if estado == "generada":  # la agregó el paso final en código, que pasó el ejemplo
            filas.append({"grupo": "nueva_lista", "motivos": [], "codigos": []})
            continue
        if estado != "nueva":
            filas.append({"grupo": "base", "motivos": [], "codigos": []})
            continue
        motivos = list(de_reglas)
        if columna is None:
            motivos.append(("sin_programa", "No se encontró la columna de programa"))
        else:
            programa = salida.iloc[i][columna] if columna in salida.columns else None
            if not isinstance(programa, str) or not programa.strip():
                motivos.append((f"vacia:{columna}", f"{columna} vacío"))
            elif normalizar(programa) not in conocidos:
                motivos.append(("programa_nuevo", f"Programa nuevo: {' '.join(programa.split())}"))
        motivos += por_fila.get(i, [])
        if extras and i in extras:
            motivos.append(("sinopsis_repetida", extras[i]))
        filas.append({"grupo": "revisar" if motivos else "nueva_lista", "motivos": [t for _, t in motivos],
                      "codigos": [c for c, _ in motivos]})
    return filas


def agrupar(clasificacion: list[dict], hashes: list[str], grupo: str) -> list[dict]:
    """Las filas de un grupo juntadas por pauta: un programa que sale 5 veces se revisa una vez."""
    por_hash: dict[str, dict] = {}
    for i, (c, h) in enumerate(zip(clasificacion, hashes)):
        if c["grupo"] != grupo:
            continue
        g = por_hash.setdefault(h, {"hash": h, "filas": [], "motivos": [], "codigos": []})
        g["filas"].append(i)
        g["motivos"] += [x for x in c["motivos"] if x not in g["motivos"]]
        g["codigos"] += [x for x in c.get("codigos", []) if x not in g["codigos"]]
    return list(por_hash.values())
