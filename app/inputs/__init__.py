"""Lectores de grillas: cada formato termina en la misma tabla cruda."""
import io

import pandas as pd

from app.engine import model as m


def leer(contenido: bytes, entrada) -> pd.DataFrame:
    from app.inputs import excel, html, partir, pdf, texto, xml

    if entrada.tipo == "excel" and entrada.cuadricula:
        from app.inputs import cuadricula

        tabla = cuadricula.leer(contenido, entrada.hoja)
    elif entrada.tipo == "excel":
        tabla = excel.leer(io.BytesIO(contenido), entrada)
    elif entrada.tipo == "pdf":
        tabla = pdf.leer(io.BytesIO(contenido), entrada)
    elif entrada.tipo == "xml":
        tabla = xml.leer(io.BytesIO(contenido), entrada)
    elif entrada.tipo == "html":
        from app.inputs import epg

        tabla = html.leer(io.BytesIO(contenido), entrada)
        if entrada.epg:
            tabla = epg.armar(tabla, entrada.epg)
    else:
        tabla = texto.leer(contenido, entrada)
    # Antes de las reglas: cada parte queda como fila cruda propia y la base la reconoce sola.
    return partir.partir_filas(tabla, entrada.partir) if entrada.partir else tabla


def leer_ejemplo(contenido: bytes, entrada) -> pd.DataFrame:
    """Un ejemplo se lee como la señal; si vino en otro formato (un HTML en una señal de Excel), como el suyo."""
    propia = detectar(contenido)
    return leer(contenido, entrada if mismo_formato(propia, entrada) else propia)


def mismo_formato(a, b) -> bool:
    """Mismo tipo y, en Excel, la misma forma (tabla común o cuadrícula)."""
    return a.tipo == b.tipo and getattr(a, "cuadricula", False) == getattr(b, "cuadricula", False)


def detectar(contenido: bytes):
    """La entrada que corresponde al archivo, mirando su contenido y no la extensión."""
    from app.inputs import cuadricula, excel, texto

    if contenido.startswith(b"%PDF"):
        return m.EntradaPdf(tipo="pdf")
    if contenido.startswith(b"PK") or contenido.startswith(b"\xd0\xcf\x11\xe0"):  # xlsx / xls
        if cuadricula.es_cuadricula(contenido):
            return m.EntradaExcel(tipo="excel", cuadricula=True)
        return m.EntradaExcel(tipo="excel", fila_encabezado=excel.detectar_fila_encabezado(io.BytesIO(contenido)))
    inicio = texto.decodificar(contenido[:4000]).lstrip().lower()
    if inicio.startswith("<?xml") or "<programme" in inicio or inicio.startswith("<tv"):
        return m.EntradaXml(tipo="xml")
    if inicio.startswith("<") and any(t in inicio for t in ("<div", "<tr", "<table", "<html", "<li", "<section")):
        return m.EntradaHtml(tipo="html")
    return m.EntradaTexto(tipo="texto")
