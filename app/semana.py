"""La semana subida, fila por fila: de la base, nueva lista para entrar sola, o para revisar."""
import pandas as pd

from app.catalogo import clave
from app.engine import model as m
from app.engine import titulos
from app.pautas import normalizar

PROGRAMA_CATALOGO = ("tit orig", "tit princ", "tit ing")
NIVELES_QUE_FRENAN = {"error", "aviso"}


def columna_programa(columnas: list[str], v: m.Validaciones) -> str | None:
    if v.programa and v.programa in columnas:
        return v.programa
    por_clave = {clave(c): c for c in columnas}
    return titulos.detectar_columna(columnas) or next((por_clave[k] for k in PROGRAMA_CATALOGO if k in por_clave), None)


def programas_de_la_base(base: dict[str, dict], columna: str | None) -> list[str]:
    if not columna:
        return []
    vistos = {}
    for pauta in base.values():
        valor = pauta["salida"].get(columna)
        if isinstance(valor, str) and valor.strip():
            vistos.setdefault(normalizar(valor), " ".join(valor.split()))
    return sorted(vistos.values())


def clasificar(salida: pd.DataFrame, estados: list[str], avisos: list, informes: list,
               programas: list[str], columna: str | None) -> list[dict]:
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
