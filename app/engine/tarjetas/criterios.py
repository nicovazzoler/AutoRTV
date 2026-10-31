"""Criterios generales para leer un título: qué es programa, qué es capítulo, temporada, número, año y marcas.

Valen para todas las señales. Se aplican con la tarjeta `criterios`; lo propio de cada señal va en tarjetas aparte.
"""
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from app.engine import model as m
from app.engine.tarjetas.texto import titulo_en
from app.engine.util import ErrorTarjeta

# Basura del export: se limpia siempre.
BASURA = re.compile(r"_x000D_|[\r\n\t]+")
COMILLAS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "´": "'"})

# Marcas que se sacan del título; las que tienen valor van a TT.
REPETICION = re.compile(r"\(\s*(?:R|REP\.?|REPRISE|REPRISSE|REPETICI[OÓ]N)\s*\)|\bRepetici[oó]n\b|\bReprise\b|\bREPRISSE\b"
                        r"|\bRep\.|\bRTX\b|®", re.I)
VIVO = re.compile(r"\(\s*(?:V|EV)\s*\)|\bEn vivo\b|\bAo vivo\b|\bLive\b(?!\s+(?:at|from|in|on)\b)", re.I)
ESTRENO = re.compile(r"\bEstreno\b|\bPremiere\b|\bEstreia\b", re.I)
CALIDAD = re.compile(r"[(\[]\s*(?:HD|4K|SD|UHD)\s*[)\]]", re.I)
IDIOMA = re.compile(r"\(\s*(?:ING|ESP|POR|SUB|DOB|LEG)\s*\)", re.I)
ANIO = re.compile(r"[(\[]\s*((?:19|20)\d{2})\s*[)\]]")

# Temporada y capítulo juntos: S02E05, S2 E5, T2 E5, T2C5, T2 Ep 5, 2x05.
TEMP_Y_CAP = re.compile(r"\b[ST]\s?0*(\d{1,2})\s?(?:E|C|EP|Ep\.?|Cap\.?)\s?0*(\d{1,4})\b|\b0*(\d{1,2})x0*(\d{1,4})\b", re.I)
CAPITULO = re.compile(r"\b(?:Cap[ií]tulo|Cap\.?|Episodio|Episode|Epis[oó]dio|Epis\.?|Ep\.?)\s*0*(\d{1,4})\b"
                      r"|\b(?:C|E|EP)0*(\d{1,4})\b|\b0*(\d{1,4})\s*(?:/|de)\s*\d{1,4}\b", re.I)
# Va antes que TEMPORADA: "T2026" es la temporada de ese año, no la número 20.
TEMPORADA_ANIO = re.compile(r"\b(?:Temporada|Temp\.?|Season|[TS])\s*((?:19|20)\d{2})\b", re.I)
TEMPORADA = re.compile(r"\b(?:Temporada|Temp\.?|Season)\s*0*(\d{1,2})\b|\b[TS]0*(\d{1,2})\b", re.I)
NUMERAL = re.compile(r"#\s*0*(\d{1,4})\b")
PARTE = re.compile(r"\b(?:Parte|Part|Pt\.?)\s*(\d{1,3})\b", re.I)
NUMERO_FINAL = re.compile(r"^(.*\S)\s+0*(\d{1,3})$")
# Una R o una E sola al final, en mayúscula: repetición y estreno ("El Payaso PLIM PLIM R", "LA HORA PEQUE) E").
MARCA_FINAL = re.compile(r"\s([RE])$")
NOMBRE_CON_NUMERO = re.compile(r"\b(?:canal|channel|tv|tele)$", re.I)
SEPARADORES_PARTE = " -–:|/"


@dataclass
class Lectura:
    programa: str = ""
    capitulo: str = ""
    temporada: int | None = None
    numero: int | None = None
    anio: int | None = None
    tt: str = ""
    titulo_temporada: str = ""


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _clave(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _sin_tildes(texto))


def limpiar(texto: str) -> str:
    texto = " ".join(BASURA.sub(" ", texto).translate(COMILLAS).split())
    return re.sub(r"([¿¡])\s+", r"\1", re.sub(r"\s+([?!])", r"\1", texto))


def _sacar(patron: re.Pattern, texto: str) -> tuple[str, re.Match | None]:
    m_ = patron.search(texto)
    if not m_:
        return texto, None
    return limpiar(texto[:m_.start()] + " " + texto[m_.end():]), m_


def _recortar(texto: str) -> str:
    """Sin separadores sueltos en las puntas ("Programa -" → "Programa")."""
    return texto.strip(SEPARADORES_PARTE + " ,.").strip() if texto else ""


def _todo_mayusculas(texto: str) -> bool:
    letras = [c for c in texto if c.isalpha()]
    return len(letras) >= 3 and all(c.isupper() for c in letras)


def mayusculas(texto: str, idioma: str) -> str:
    """Solo lo que viene todo en MAYÚSCULAS: inglés como título, castellano y portugués como oración."""
    if not _todo_mayusculas(texto):
        return texto
    if idioma == "en":
        return titulo_en(texto.lower())
    palabras = texto.lower().split(" ")
    # La primera palabra y la que abre un paréntesis van con mayúscula: "(LA HORA PEQUE)" → "(La hora peque)".
    return " ".join(p[:1].upper() + p[1:] if i == 0 else p[:2].upper() + p[2:] if p.startswith("(") else p
                    for i, p in enumerate(palabras))


def _parte(texto: str, idioma: str) -> str:
    return PARTE.sub(lambda x: f"{'Part' if idioma == 'en' else 'Parte'} {int(x[1])}", texto)


def _numeros(texto: str, lectura: Lectura, numeral: bool) -> tuple[str, str]:
    """Saca temporada y número de capítulo. Devuelve (lo de antes, lo de después): en "Friends S02E05 The One"
    lo que sigue al número es el capítulo."""
    despues = ""
    for patron in (TEMP_Y_CAP, CAPITULO, *((NUMERAL,) if numeral else ()), TEMPORADA):
        x = patron.search(texto)
        if not x:
            continue
        grupos = [int(g) for g in x.groups() if g]
        if patron is TEMP_Y_CAP:
            lectura.temporada = lectura.temporada or grupos[0]
            lectura.numero = lectura.numero or grupos[1]
        elif patron is TEMPORADA:
            lectura.temporada = lectura.temporada or grupos[0]
        elif lectura.numero is None:
            lectura.numero = grupos[0]
        texto, resto = limpiar(texto[:x.start()]), limpiar(texto[x.end():])
        despues = " ".join(p for p in (resto, despues) if p)
    return texto, despues


def _conocido(texto: str, titulos: list[str]) -> str | None:
    """El título conocido más largo con el que empieza el texto (sin tildes, mayúsculas ni signos)."""
    clave = _clave(texto)
    candidatos = [t for t in titulos if (k := _clave(t)) and clave.startswith(k)]
    return max(candidatos, key=lambda t: len(_clave(t)), default=None)


def _cortar_en(texto: str, cuantos: int) -> int:
    """La posición del texto original donde terminan `cuantos` letras y números."""
    vistos = 0
    for i, c in enumerate(texto):
        if c.isalnum():
            vistos += 1
            if vistos == cuantos:
                return i + 1
    return len(texto)


def leer(titulo: str, detalle: str, t: m.Criterios) -> Lectura:
    lectura = Lectura()
    texto = limpiar(titulo)
    for patron, valor in ((REPETICION, "(r)"), (VIVO, "(v)")):
        texto, x = _sacar(patron, texto)
        while x:
            lectura.tt = lectura.tt or valor
            texto, x = _sacar(patron, texto)
    for patron in (ESTRENO, CALIDAD, IDIOMA):
        texto = patron.sub(" ", texto)
    texto, x = _sacar(ANIO, texto)
    if x:
        lectura.anio = int(x[1])
    texto, x = _sacar(TEMPORADA_ANIO, texto)
    if x:
        lectura.titulo_temporada = x[1]
    texto = limpiar(re.sub(r"\(\s*\)", " ", texto))
    for prefijo in t.prefijos:
        if _sin_tildes(texto).startswith(_sin_tildes(prefijo)):
            texto = texto[len(prefijo):].strip()
    texto = _parte(texto, t.idioma)
    parte = PARTE.search(texto)
    texto, parte = (limpiar(texto[:parte.start()]), parte[0]) if parte else (texto, "")
    texto, tras_numero = _numeros(texto, lectura, numeral=False)
    while x := MARCA_FINAL.search(texto):
        lectura.tt = lectura.tt or ("(r)" if x[1] == "R" else "")
        texto = texto[:x.start()]

    # Programa y capítulo: primero un programa conocido de la base, después el primer separador.
    # Si la grilla trae el capítulo aparte (detalle), el título entero es el programa.
    conocido = _conocido(texto, t.titulos)
    posiciones = [(texto.find(s), s) for s in t.separadores if texto.find(s) > 0]
    if conocido:
        corte = _cortar_en(texto, len(_clave(conocido)))
        # El "?" de "¿Y tu que vas a hacer?" no cuenta como letra: va con el programa, no al capítulo.
        cola = re.search(r"[^\w\s]*$", conocido)[0]
        if cola and texto[corte:].lstrip().startswith(cola):
            corte = texto.index(cola, corte) + len(cola)
        programa, capitulo = texto[:corte], texto[corte:]
    elif posiciones and not detalle:
        pos, sep = min(posiciones)
        programa, capitulo = texto[:pos], texto[pos + len(sep):]
    else:
        programa, capitulo = texto, ""
    programa = _recortar(programa)
    capitulo = " ".join(p for p in (_recortar(capitulo), _recortar(tras_numero), parte) if p)

    if lectura.numero is None and not conocido and (x := NUMERO_FINAL.match(programa)) \
            and not NOMBRE_CON_NUMERO.search(x[1]):
        programa, lectura.numero = x[1], int(x[2])
    if detalle:
        resto, tras = _numeros(limpiar(detalle), lectura, numeral=True)
        capitulo = " / ".join(p for p in (capitulo, _recortar(" ".join(p for p in (resto, tras) if p))) if p)
    if _clave(capitulo) == _clave(programa):
        capitulo = ""
    lectura.programa = mayusculas(programa, t.idioma)
    lectura.capitulo = mayusculas(capitulo, t.idioma)
    return lectura


def _texto(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def criterios(df: pd.DataFrame, t: m.Criterios, mascara) -> pd.DataFrame:
    if t.columna not in df.columns:
        raise ErrorTarjeta(f"No existe la columna {t.columna}")
    destinos = {"programa": t.programa, "capitulo": t.capitulo, "temporada": t.temporada,
                "titulo_temporada": t.titulo_temporada, "numero": t.numero, "anio": t.anio, "tt": t.tt}
    for campo, columna in destinos.items():
        if columna and columna not in df.columns:
            df[columna] = None
    for i in df.index[mascara]:
        detalle = _texto(df.at[i, t.detalle]) if t.detalle and t.detalle in df.columns else ""
        lectura = leer(_texto(df.at[i, t.columna]), detalle, t)
        for campo, columna in destinos.items():
            if not columna:
                continue
            valor = getattr(lectura, campo)
            # Lo que el criterio no encontró no pisa lo que la columna ya tenía (otra tarjeta, o la grilla misma).
            if valor in ("", None) and campo not in ("programa", "capitulo"):
                continue
            df.at[i, columna] = valor if valor != "" else None
    return df


# --- Configurar la tarjeta sola, mirando la grilla y las columnas del EPG ---

TITULO_CRUDO = ("titulo", "title", "programa", "program", "program title", "show", "nombre", "p", "tit")
DETALLE_CRUDO = ("detalle", "episode", "episodio", "capitulo", "episode title", "subtitulo")


def _clave_columna(nombre) -> str:
    return " ".join(_sin_tildes(str(nombre)).replace("_", " ").replace("-", " ").split())


def _columna_de_texto(tabla: pd.DataFrame) -> str | None:
    """La columna con más textos distintos y largos: casi siempre es el título."""
    mejor, puntos = None, 0.0
    for c in tabla.columns:
        textos = [v for v in tabla[c] if isinstance(v, str) and v.strip()]
        if len(textos) < len(tabla) / 2:
            continue
        valor = len(set(textos)) * sum(len(v) for v in textos) / len(textos)
        if valor > puntos:
            mejor, puntos = c, valor
    return mejor


def _destino(salida: list[str], prueba) -> str | None:
    return next((c for c in salida if prueba(_clave_columna(c))), None)


def configurar(tabla: pd.DataFrame, salida: list[str], programa: str | None) -> m.Criterios | None:
    """Una tarjeta de criterios generales para esta grilla, con destinos en las columnas del EPG (o nombres comunes)."""
    por_clave = {_clave_columna(c): c for c in tabla.columns}
    titulo = next((por_clave[k] for k in TITULO_CRUDO if k in por_clave), None) or _columna_de_texto(tabla)
    if titulo is None:
        return None
    detalle = next((por_clave[k] for k in DETALLE_CRUDO if k in por_clave and por_clave[k] != titulo), None)
    if not salida:
        return m.Criterios(id="criterios", tipo="criterios", columna=titulo, detalle=detalle)
    clave_prog = _clave_columna(programa or "")
    idioma = "en" if "ing" in clave_prog.split() else "pt" if "port" in clave_prog.split() else "es"
    capitulo = _destino(salida, lambda k: "cap" in k and "tit" in k or k in ("capitulo", "tit cap"))
    return m.Criterios(
        id="criterios", tipo="criterios", columna=titulo, detalle=detalle, idioma=idioma,
        programa=programa or _destino(salida, lambda k: k in ("programa", "p", "tit prog")) or "Programa",
        capitulo=capitulo,
        numero=_destino(salida, lambda k: "cap" in k and ("nro" in k or "num" in k or k.startswith("n "))),
        temporada=_destino(salida, lambda k: "temp" in k and "tit" not in k),
        titulo_temporada=_destino(salida, lambda k: "temp" in k and "tit" in k),
        anio=_destino(salida, lambda k: k in ("ano", "anio", "year", "a o")),
        tt=_destino(salida, lambda k: k == "tt"),
    )
