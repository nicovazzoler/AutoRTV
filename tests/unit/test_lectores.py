import datetime as dt
import io
import zlib

from app import inputs
from app.engine import model as m

XMLTV = b"""<?xml version="1.0"?>
<tv><channel id="c"><display-name>Canal</display-name></channel>
<programme channel="c" event_id="1" start="20261013171910 -0300" stop="20261013175401 -0300">
  <title lang="pt">Viajando com Luiz</title><sub-title>Ep 1</sub-title><episode-num system="onscreen">S1E1</episode-num>
</programme>
<programme channel="c" event_id="2" start="20261013175406 -0300" stop="20261013182337 -0300">
  <title lang="pt">Planeta Turismo</title><desc>Natureza</desc>
</programme></tv>"""

HTML = b"""<div class="sched">
""" + b"".join(
    f'<div class="sched__slot" data-eastern="2026-10-23 0{i}:00:00" data-duration="60">'
    f'<div class="sched__time">0{i}:00 AM</div><div class="sched__show">Show {i % 2}</div>'
    f'<div class="sched__episode">Ep {i}</div></div>'.encode() for i in range(6)) + b"</div>"


def test_detecta_el_formato_por_el_contenido():
    assert inputs.detectar(b"%PDF-1.4 ...").tipo == "pdf"
    assert inputs.detectar(XMLTV).tipo == "xml"
    assert inputs.detectar(HTML).tipo == "html"
    assert inputs.detectar("Lunes 2/11\n06:00 Noticiero".encode()).tipo == "texto"


def test_xmltv():
    df = inputs.leer(XMLTV, m.EntradaXml(tipo="xml"))
    assert list(df["title"]) == ["Viajando com Luiz", "Planeta Turismo"]
    assert df["start"][0] == dt.datetime(2026, 10, 13, 17, 19, 10)  # la hora como viene, sin cambiar de zona
    assert df["sub-title"][0] == "Ep 1" and df["episode-num system"][0] == "onscreen"
    assert df["desc"][1] == "Natureza"


def test_html_detecta_el_bloque_y_los_campos():
    df = inputs.leer(HTML, m.EntradaHtml(tipo="html"))
    assert len(df) == 6
    assert {"data-eastern", "data-duration", "time", "show", "episode"} <= set(df.columns)
    assert df["show"][1] == "Show 1" and df["data-eastern"][2] == "2026-10-23 02:00:00"


def test_html_con_selectores_propios():
    entrada = m.EntradaHtml(tipo="html", bloque=".sched__slot",
                            campos={"Inicio": m.CampoHtml(attr="data-eastern"), "Titulo": m.CampoHtml(css=".sched__show")})
    df = inputs.leer(HTML, entrada)
    assert list(df.columns) == ["Inicio", "Titulo"] and df["Titulo"][0] == "Show 0"


def test_texto_con_separador_y_encabezado():
    texto = "Fecha\tHora\tPrograma\n02/11/2026\t06:00\tNoticiero\n02/11/2026\t07:00\tAl despertar\n"
    df = inputs.leer(texto.encode(), m.EntradaTexto(tipo="texto"))
    assert list(df.columns) == ["Fecha", "Hora", "Programa"] and df["Programa"][1] == "Al despertar"


def test_texto_por_lineas_con_dias_y_medianoche():
    texto = ("Lunes 2/11\n06:00 Noticiero\n   (en vivo)\n23:30 - Cine de medianoche\n00:45 Música\n"
             "Martes\n06:00 Noticiero\n")
    df = inputs.leer(texto.encode("cp1252"), m.EntradaTexto(tipo="texto", fecha_inicio="2026-11-02"))
    assert list(df["Programa"]) == ["Noticiero", "Cine de medianoche", "Música", "Noticiero"]
    assert df["Detalle"][0] == "(en vivo)"
    assert [f.day for f in df["Fecha"]] == [2, 2, 3, 3]
    assert df["Hora"][2] == dt.time(0, 45)


def _pdf_de_grilla() -> bytes:
    """PDF mínimo: columna de horas, Lunes y Martes; el lunes de 06:00 a 07:00 es una sola celda."""
    x = [40, 90, 200, 310]
    y = [700, 680, 660, 640, 620]  # encabezado + 3 filas de media hora
    trazos = [f"{x[0]} {yy} m {x[-1]} {yy} l S" for yy in (y[0], y[1], y[4])]
    trazos += [f"{x[0]} {y[2]} m {x[1]} {y[2]} l S", f"{x[2]} {y[2]} m {x[3]} {y[2]} l S"]  # el lunes no se corta
    trazos += [f"{x[0]} {y[3]} m {x[-1]} {y[3]} l S"]
    trazos += [f"{xx} {y[0]} m {xx} {y[4]} l S" for xx in x]
    textos = [(x[1] + 4, y[0] - 14, "Lunes 26/10/2026"), (x[2] + 4, y[0] - 14, "Martes 27/10/2026"),
              (x[0] + 4, y[1] - 14, "06:00"), (x[0] + 4, y[2] - 14, "06:30"), (x[0] + 4, y[3] - 14, "07:00"),
              (x[1] + 4, y[1] - 14, "Noticiero"), (x[2] + 4, y[1] - 14, "Cocina"), (x[2] + 4, y[2] - 14, "Deportes"),
              (x[1] + 4, y[3] - 14, "Cine"), (x[2] + 4, y[3] - 14, "Cine")]
    flujo = "0 G 1 w\n" + "\n".join(trazos) + "\n" + "\n".join(
        f"BT /F1 8 Tf {a} {b} Td ({t}) Tj ET" for a, b, t in textos)
    datos = zlib.compress(flujo.encode())
    objetos = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(datos) + datos + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    salida, posiciones = io.BytesIO(), []
    salida.write(b"%PDF-1.4\n")
    for i, obj in enumerate(objetos, start=1):
        posiciones.append(salida.tell())
        salida.write(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref = salida.tell()
    salida.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1))
    salida.write(b"".join(b"%010d 00000 n \n" % p for p in posiciones))
    salida.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%EOF\n" % (len(objetos) + 1, xref))
    return salida.getvalue()


def test_pdf_grilla_semanal_con_celdas_unidas():
    contenido = _pdf_de_grilla()
    assert inputs.detectar(contenido).tipo == "pdf"
    df = inputs.leer(contenido, m.EntradaPdf(tipo="pdf"))
    filas = [(f.day, i.strftime("%H:%M"), fin.strftime("%H:%M") if fin else None, p)
             for f, i, fin, p in zip(df["Fecha"], df["Inicio"], df["Fin"], df["Programa"])]
    assert filas == [(26, "06:00", "07:00", "Noticiero"), (26, "07:00", None, "Cine"),
                     (27, "06:00", "06:30", "Cocina"), (27, "06:30", "07:00", "Deportes"), (27, "07:00", None, "Cine")]


def test_subir_grilla_dice_el_formato_y_texto_pegado(cliente):
    r = cliente.post("/api/tablas", files={"archivo": ("g.xml", XMLTV)}).json()
    assert r["entrada"] == {"tipo": "xml", "elemento": None, "partir": None}
    receta = {"id": "x", "nombre": "x", "entrada": r["entrada"], "tarjetas": [], "salida": {"columnas": []}}
    assert cliente.post("/api/preview", json={"tabla_id": r["tabla_id"], "senal": receta}).json()["total_filas"] == 2

    pegado = cliente.post("/api/tablas/texto", json={"texto": "Lunes\n06:00 Noticiero\n07:00 Cine",
                                                     "fecha_inicio": "2026-11-02"}).json()
    receta["entrada"] = pegado["entrada"]
    preview = cliente.post("/api/preview", json={"tabla_id": pegado["tabla_id"], "senal": receta}).json()
    assert preview["total_filas"] == 2 and preview["filas"][0][:2] == ["02/11/2026", "06:00"]
    assert cliente.post("/api/tablas/texto", json={"texto": "  "}).status_code == 422


def test_partir_celdas_con_varios_programas():
    from app.inputs.partir import partir_filas

    tabla = __import__("pandas").DataFrame({
        "Fecha": [dt.datetime(2026, 10, 27)] * 3,
        "Inicio": [dt.time(17), dt.time(18), dt.time(23, 30)],
        "Fin": [dt.time(18), dt.time(18, 10), dt.time(0, 30)],
        "Programa": ["HONORES Ep. 22 / GATIPEDIA. Ep. 9, 7'43\"", "Himno Nacional /Himno del Estado",
                     "Cine 90'00\" / Noticias"],
    }, dtype=object)
    df = partir_filas(tabla, m.Partir(solo_si=r"\d+'\d+\""))
    assert list(df["Programa"]) == ["HONORES Ep. 22", "GATIPEDIA. Ep. 9, 7'43\"", "Himno Nacional /Himno del Estado",
                                    "Cine 90'00\"", "Noticias"]
    assert [(i.strftime("%H:%M"), f.strftime("%H:%M")) for i, f in zip(df["Inicio"], df["Fin"])] == [
        ("17:00", "17:30"), ("17:30", "18:00"), ("18:00", "18:10"), ("23:30", "00:00"), ("00:00", "00:30")]
    assert df["Fecha"][4] == dt.datetime(2026, 10, 28)  # la segunda parte ya es del día siguiente
