"""Lectores de grillas: cada formato termina en la misma tabla cruda."""
import io

import pandas as pd

from app.engine import model as m


def leer(contenido: bytes, entrada) -> pd.DataFrame:
    from app.inputs import excel, html, partir, pdf, texto, xml

    if entrada.tipo == "excel" and entrada.cuadricula:
        from app.inputs import cuadricula

        tabla = cuadricula.leer(contenido, entrada.hoja, entrada.fila_dias, entrada.columnas_hora, entrada.doce_horas)
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
    """Un ejemplo se lee como la señal; si vino en otro formato (un HTML en una señal de Excel), como el suyo.

    Si la detección dice otro formato pero la lectura de la señal le encuentra fecha y hora, gana la de la señal:
    es la que eligió el agente para una grilla que la detección no entiende.
    """
    from app.pautas import tiene_horario
    propia = detectar(contenido)
    if mismo_formato(propia, entrada):
        return leer(contenido, con_todas_las_hojas(entrada, propia))
    try:
        tabla = leer(contenido, entrada)
        if tiene_horario(tabla):
            return tabla
    except Exception:
        pass
    return leer(contenido, propia)


def con_todas_las_hojas(entrada, detectada):
    """Si el libro trae varias hojas de programación y la lectura guardada lee una sola, pasa a leerlas todas."""
    if getattr(detectada, "todas_las_hojas", False) and not entrada.todas_las_hojas:
        return entrada.model_copy(update={"todas_las_hojas": True, "fila_encabezado": detectada.fila_encabezado})
    return entrada


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
        if varias := excel.hojas_de_programacion(contenido):
            return m.EntradaExcel(tipo="excel", fila_encabezado=varias[0], todas_las_hojas=True)
        return m.EntradaExcel(tipo="excel", fila_encabezado=excel.detectar_fila_encabezado(io.BytesIO(contenido)))
    inicio = texto.decodificar(contenido[:4000]).lstrip().lower()
    if inicio.startswith("<?xml") or "<programme" in inicio or inicio.startswith("<tv"):
        return m.EntradaXml(tipo="xml")
    if inicio.startswith("<") and any(t in inicio for t in ("<div", "<tr", "<table", "<html", "<li", "<section")):
        return m.EntradaHtml(tipo="html")
    return m.EntradaTexto(tipo="texto")
