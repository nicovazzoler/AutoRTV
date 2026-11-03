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
    elif entrada.tipo == "word":
        from app.inputs import word

        tabla = word.leer(contenido, entrada)
    elif entrada.tipo == "varios":
        from app.inputs import varios

        tabla = varios.leer(contenido, entrada)
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


MAX_HOJAS_A_MIRAR = 30


def _hoja_con_la_grilla(contenido: bytes) -> m.EntradaExcel:
    """La grilla puede no estar en la primera hoja (portada, instructivo, otras señales): la primera que sea una
    cuadrícula o una tabla con fecha y hora. Si ninguna, la primera, como siempre."""
    from app.inputs import cuadricula, excel
    from app.pautas import tiene_horario

    try:
        nombres = pd.ExcelFile(io.BytesIO(contenido)).sheet_names
    except Exception:
        nombres = [0]
    for i in range(1, min(len(nombres), MAX_HOJAS_A_MIRAR)):
        if cuadricula.es_cuadricula(contenido, i):
            return m.EntradaExcel(tipo="excel", cuadricula=True, hoja=i)
    for i in range(min(len(nombres), MAX_HOJAS_A_MIRAR)):
        entrada = m.EntradaExcel(tipo="excel", hoja=i, fila_encabezado=excel.detectar_fila_encabezado(io.BytesIO(contenido), i))
        try:
            if tiene_horario(excel.leer(io.BytesIO(contenido), entrada)):
                return entrada
        except Exception:
            continue
    return m.EntradaExcel(tipo="excel", fila_encabezado=excel.detectar_fila_encabezado(io.BytesIO(contenido)))


def mismo_formato(a, b) -> bool:
    """Mismo tipo y, en Excel, la misma forma (tabla común o cuadrícula) en la misma hoja."""
    return (a.tipo == b.tipo and getattr(a, "cuadricula", False) == getattr(b, "cuadricula", False)
            and getattr(a, "hoja", 0) == getattr(b, "hoja", 0))


def detectar(contenido: bytes):
    """La entrada que corresponde al archivo, mirando su contenido y no la extensión."""
    from app.inputs import cuadricula, excel, texto, varios, word

    if contenido.startswith(b"Rar!"):
        raise ValueError("los .rar no se pueden abrir acá: comprimilo como .zip (clic derecho › Enviar a › Carpeta comprimida)")
    if contenido.startswith(b"%PDF"):
        return m.EntradaPdf(tipo="pdf")
    if varios.es_zip_suelto(contenido):
        return m.EntradaVarios(tipo="varios")
    if word.es_word(contenido):
        return m.EntradaWord(tipo="word")
    if contenido.startswith(b"PK") or contenido.startswith(b"\xd0\xcf\x11\xe0"):  # xlsx / xls
        if cuadricula.es_cuadricula(contenido):
            return m.EntradaExcel(tipo="excel", cuadricula=True)
        if varias := excel.hojas_de_programacion(contenido):
            return m.EntradaExcel(tipo="excel", fila_encabezado=varias[0], todas_las_hojas=True)
        return _hoja_con_la_grilla(contenido)
    inicio = texto.decodificar(contenido[:4000]).lstrip().lower()
    if inicio.startswith("<?xml") or "<programme" in inicio or inicio.startswith("<tv"):
        return m.EntradaXml(tipo="xml")
    if inicio.startswith("<") and any(t in inicio for t in ("<div", "<tr", "<table", "<html", "<li", "<section")):
        return m.EntradaHtml(tipo="html")
    return m.EntradaTexto(tipo="texto")
