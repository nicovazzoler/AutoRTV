"""Lectores de grillas: cada formato termina en la misma tabla cruda."""
import io

import pandas as pd

from app.engine import model as m


def leer(contenido: bytes, entrada) -> pd.DataFrame:
    from app.inputs import excel, html, partir, pdf, texto, xml

    if entrada.tipo == "excel":
        tabla = excel.leer(io.BytesIO(contenido), entrada)
    elif entrada.tipo == "pdf":
        tabla = pdf.leer(io.BytesIO(contenido), entrada)
    elif entrada.tipo == "xml":
        tabla = xml.leer(io.BytesIO(contenido), entrada)
    elif entrada.tipo == "html":
        tabla = html.leer(io.BytesIO(contenido), entrada)
    else:
        tabla = texto.leer(contenido, entrada)
    # Antes de las reglas: cada parte queda como fila cruda propia y la base la reconoce sola.
    return partir.partir_filas(tabla, entrada.partir) if entrada.partir else tabla


def detectar(contenido: bytes):
    """La entrada que corresponde al archivo, mirando su contenido y no la extensión."""
    from app.inputs import excel, texto

    if contenido.startswith(b"%PDF"):
        return m.EntradaPdf(tipo="pdf")
    if contenido.startswith(b"PK") or contenido.startswith(b"\xd0\xcf\x11\xe0"):  # xlsx / xls
        return m.EntradaExcel(tipo="excel", fila_encabezado=excel.detectar_fila_encabezado(io.BytesIO(contenido)))
    inicio = texto.decodificar(contenido[:4000]).lstrip().lower()
    if inicio.startswith("<?xml") or "<programme" in inicio or inicio.startswith("<tv"):
        return m.EntradaXml(tipo="xml")
    if inicio.startswith("<") and any(t in inicio for t in ("<div", "<tr", "<table", "<html", "<li", "<section")):
        return m.EntradaHtml(tipo="html")
    return m.EntradaTexto(tipo="texto")
