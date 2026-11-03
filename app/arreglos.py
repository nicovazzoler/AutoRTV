"""Arreglos rápidos para un grupo de motivos de "Para revisar": qué valor sugerir en cada pauta."""
import difflib
import re

from app.parecidas import Parecida

ANIO = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")  # "20255" no tiene un año seguro adentro


def _texto(v) -> str:
    return "" if v is None else str(v).strip()


def sugerencia(valor, col) -> object:
    """Lo más parecido que cumple la regla del catálogo para esa celda, o None si no hay nada razonable."""
    t = _texto(valor)
    if col.tipo == "texto" and col.maximo and len(t) > col.maximo:
        corte = t[:col.maximo].rsplit(" ", 1)[0] if " " in t[:col.maximo] else t[:col.maximo]
        return corte.rstrip(" ,.;:-")
    if col.tipo == "anio":
        return int(m[0]) if (m := ANIO.search(t)) else None
    if col.tipo == "entero":
        digitos = re.sub(r"\D", "", t.split(",")[0].split(".")[0])
        if not digitos:
            return None
        n = int(digitos)
        return min(n, col.maximo) if col.maximo else n
    if col.tipo == "valores" and col.valores:
        # Sin signos: "rep" se parece a "(r)" aunque los paréntesis no estén.
        plano = {re.sub(r"\W", "", v.lower()): v for v in col.valores}
        parecidos = difflib.get_close_matches(re.sub(r"\W", "", t.lower()), list(plano), n=1, cutoff=0.4)
        return plano[parecidos[0]] if parecidos else None
    return None


def del_catalogo(filas: list[tuple[str, dict]], columna: str, col, programa: str | None) -> list[Parecida]:
    """`filas`: (clave, salida) de las pautas del grupo. Solo las que tienen una sugerencia distinta de lo que hay."""
    lista = []
    for clave, salida in filas:
        antes = salida.get(columna)
        despues = sugerencia(antes, col)
        if despues is not None and _texto(despues) != _texto(antes):
            lista.append(Parecida(clave, _texto(salida.get(programa)), columna, antes, despues, "mismo_valor",
                                  porque="Arreglo sugerido por la regla del catálogo"))
    return lista


def completar(filas: list[tuple[str, dict]], columna: str, valor, programa: str | None) -> list[Parecida]:
    return [Parecida(clave, _texto(s.get(programa)), columna, s.get(columna), valor, "mismo_valor")
            for clave, s in filas if _texto(s.get(columna)) != _texto(valor)]


def a_argumento(filas: list[tuple[str, dict]], sinopsis: str, argumento: str, programa: str | None) -> list[Parecida]:
    """La sinopsis que se repite entre capítulos pasa al argumento del programa, y la del capítulo queda vacía."""
    lista = []
    for clave, s in filas:
        texto = s.get(sinopsis)
        if _texto(texto):
            nombre = _texto(s.get(programa))
            lista += [Parecida(clave, nombre, argumento, s.get(argumento), texto, "mismo_valor", porque="Pasa al argumento"),
                      Parecida(clave, nombre, sinopsis, texto, None, "mismo_valor", porque="Queda vacía en el capítulo")]
    return lista
