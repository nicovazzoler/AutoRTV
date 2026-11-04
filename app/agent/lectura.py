"""El agente decide cómo leer una grilla que llega: mira el comienzo del archivo y propone la configuración
del lector. El servidor la prueba con los controles y, si falla, le devuelve qué pasó."""
import datetime as dt
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pydantic import TypeAdapter, ValidationError

from app import inputs
from app.agent import cliente, controles
from app.agent.cliente import Proveedor
from app.engine import model as m

MAX_VUELTAS = 3
FILAS_MUESTRA = 8
FILAS_VISTA = 40
COLUMNAS_VISTA = 15
MAX_TEXTO = 6000
MAX_HOJAS_MAPA = 31
FILAS_MAPA = 5
FILAS_HOJA_PEDIDA = 120
ENTRADA = TypeAdapter(m.Entrada)
FORMATO = {
    "type": "object",
    "properties": {"explicacion": {"type": "string"}, "entrada_json": {"type": "string"},
                   "ver_hoja": {"type": "string"}, "aceptar": {"type": "boolean"}},
    "required": ["explicacion", "entrada_json"],
    "additionalProperties": False,
}


@dataclass
class PropuestaLectura:
    logrado: bool
    entrada: dict | None = None
    explicacion: str = ""
    medida: dict | None = None
    problemas: list[str] = field(default_factory=list)
    vueltas: int = 0
    acepto: bool = False  # dejó la lectura que había armado el código
    tokens_entrada: int = 0
    tokens_salida: int = 0
    modelo: str = ""


def sistema() -> str:
    return (Path(__file__).parent / "prompts" / "lectura.md").read_text(encoding="utf-8")


def _letra(c: int) -> str:
    letras = ""
    c += 1
    while c:
        c, resto = divmod(c - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


def _celda(v) -> str:
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M") if v.time() != dt.time() else v.strftime("%Y-%m-%d")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, dt.time):
        return v.strftime("%H:%M")
    return " ".join(str(v).split())[:80]


def _filas(celdas: list[list], filas_max: int, ancho_max: int = 0) -> list[str]:
    filas = []
    for r, fila in enumerate(celdas):
        valores = [f"{_letra(c)}={_celda(v)}" for c, v in enumerate(fila[:COLUMNAS_VISTA]) if v not in (None, "")]
        if valores:
            texto = f"Fila {r + 1}: " + " | ".join(valores)
            filas.append(texto[:ancho_max] if ancho_max else texto)
        if len(filas) == filas_max:
            break
    return filas


def _vista_hoja(celdas: list[list], combinadas: list[tuple], filas_max: int) -> str:
    rangos = [f"{_letra(c0)}{r0 + 1}:{_letra(c1 - 1)}{r1}" for r0, r1, c0, c1 in combinadas if r0 < filas_max]
    return ("\n".join(_filas(celdas[:filas_max], filas_max))
            + "\nCeldas combinadas: " + (", ".join(rangos[:120]) or "ninguna"))


def _hoja_detectada(contenido: bytes) -> int:
    try:
        hoja = getattr(inputs.detectar(contenido), "hoja", 0)
    except Exception:
        return 0
    return hoja if isinstance(hoja, int) else 0


def _vista_excel(contenido: bytes) -> str:
    """Un mapa de todas las hojas y, completa, la que el código cree que es la grilla."""
    from app.inputs import cuadricula

    nombres = pd.ExcelFile(io.BytesIO(contenido)).sheet_names
    hojas = cuadricula.todas_las_celdas(contenido, MAX_HOJAS_MAPA)
    mapa = []
    for i, (nombre, celdas, _) in enumerate(hojas):
        ancho = max((len(f) for f in celdas), default=0)
        comienzo = _filas(celdas, FILAS_MAPA, ancho_max=300)
        mapa.append(f"[{i}] {nombre} ({len(celdas)} filas × {ancho} columnas)\n  "
                    + ("\n  ".join(comienzo) or "(vacía)"))
    if len(nombres) > MAX_HOJAS_MAPA:
        mapa.append(f"…y {len(nombres) - MAX_HOJAS_MAPA} hojas más: {', '.join(nombres[MAX_HOJAS_MAPA:][:60])}")
    elegida = min(_hoja_detectada(contenido), len(hojas) - 1)
    nombre, celdas, combinadas = hojas[elegida]
    return (f"Excel con {len(nombres)} hojas. Mapa (número, nombre, tamaño y primeras filas con valor):\n"
            + "\n".join(mapa)
            + f"\n\nLa hoja [{elegida}] {nombre} parece la grilla. Celdas con valor (columna=valor):\n"
            + _vista_hoja(celdas, combinadas, FILAS_VISTA)
            + "\n\nSi la grilla está en otra hoja, pedila con ver_hoja.")


def _hoja_pedida(contenido: bytes, pedida: str) -> str:
    """La hoja entera (hasta FILAS_HOJA_PEDIDA filas) que pidió el agente, por número o por nombre."""
    from app.inputs import cuadricula

    nombres = pd.ExcelFile(io.BytesIO(contenido)).sheet_names
    pedida = pedida.strip()
    if pedida.isdigit() and int(pedida) < len(nombres):
        i = int(pedida)
    else:
        coinciden = [i for i, n in enumerate(nombres) if n.strip().lower() == pedida.lower()]
        if not coinciden:
            return f"No hay una hoja «{pedida}». Las hojas son: " + ", ".join(f"[{i}] {n}" for i, n in enumerate(nombres[:60]))
        i = coinciden[0]
    celdas, combinadas = cuadricula._celdas(contenido, i)
    return (f"Hoja [{i}] {nombres[i]} ({len(celdas)} filas). Celdas con valor (columna=valor):\n"
            + _vista_hoja(celdas, combinadas, FILAS_HOJA_PEDIDA)
            + "\n\nAhora devolvé la configuración completa en entrada_json (o pedí otra hoja con ver_hoja).")


def _vista_pdf(contenido: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        textos = [f"--- Página {i + 1} ---\n{p.extract_text() or ''}" for i, p in enumerate(pdf.pages[:2])]
        return f"PDF de {len(pdf.pages)} páginas. Texto de las primeras:\n" + "\n".join(textos)[:MAX_TEXTO]


def _vista_texto(contenido: bytes) -> str:
    from app.inputs import texto as lector_texto

    texto = lector_texto.decodificar(contenido)
    if "<" in texto[:2000]:
        texto = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", texto)
        inicio = max(texto.lower().find("<body"), 0)
        texto = texto[inicio:]
    return re.sub(r"\s+", " ", texto)[:MAX_TEXTO]


def _es_excel(contenido: bytes) -> bool:
    from app.inputs import varios, word

    return (contenido.startswith(b"PK") and not varios.es_zip_suelto(contenido) and not word.es_word(contenido)) \
        or contenido.startswith(b"\xd0\xcf\x11\xe0")


def vista_cruda(contenido: bytes) -> str:
    """El comienzo del archivo tal como vino, en texto, para que el agente vea su forma."""
    from app.inputs import varios, word

    if varios.es_zip_suelto(contenido):
        lista = varios.archivos(contenido)
        nombres = ", ".join(n for n, _ in lista[:40])
        return (f"Varios archivos ({len(lista)}): {nombres}. Se leen uno abajo del otro con "
                f'{{"tipo": "varios", "cada_uno": <entrada para cada archivo>}}.\nEl primero:\n'
                + (vista_cruda(lista[0][1]) if lista else "(vacío)"))
    if word.es_word(contenido):
        return "Word (.docx), sus tablas o su texto:\n" + word.leer(contenido, m.EntradaWord(tipo="word")).head(FILAS_VISTA).to_string()[:MAX_TEXTO]
    if _es_excel(contenido):
        return _vista_excel(contenido)
    if contenido.startswith(b"%PDF"):
        return _vista_pdf(contenido)
    return "Texto (HTML, XML o texto pegado):\n" + _vista_texto(contenido)


def _probar(contenido: bytes, datos: dict | None, esperado: pd.DataFrame | None) -> tuple[dict | None, dict | None, list[str]]:
    """(entrada, medida, problemas) de lo que propuso el agente."""
    if not datos:
        return None, None, ["La respuesta no fue un JSON válido."]
    try:
        entrada = ENTRADA.validate_python(json.loads(datos.get("entrada_json") or "{}"))
    except (json.JSONDecodeError, ValidationError) as e:
        return None, None, [f"La configuración no es válida: {str(e)[:500]}"]
    if inputs.con_codigo(entrada):  # lo escribe el agente de la señal, que lo comprueba contra el ejemplo y avisa al admin
        return None, None, ["Acá no se escribe código: elegí una de las lecturas que hay."]
    try:
        tabla = inputs.leer(contenido, entrada)
    except Exception as e:
        return entrada.model_dump(exclude_defaults=True), None, [f"El lector falló con esa configuración: {e}"]
    medida = controles.lectura(tabla, esperado)
    problemas = controles.problemas_de_lectura(medida)
    if problemas:
        # Con el % solo no se sabe qué corregir: el agente ve lo que salió de verdad con su configuración.
        problemas.append(f"Así salieron las primeras filas ({len(tabla)} en total, columnas {list(map(str, tabla.columns))}):\n"
                         + tabla.head(FILAS_MUESTRA).to_string(max_colwidth=40)[:2500])
        if salteadas := tabla.attrs.get("salteadas"):
            problemas.append("Hojas que no se pudieron leer y se saltearon: " + "; ".join(salteadas)[:800])
    return entrada.model_dump(exclude_defaults=True), medida, problemas


def lo_del_codigo(contenido: bytes, entrada, motivo: str) -> str:
    """Cómo leyó el archivo la detección del código, para que el agente decida si se queda con eso."""
    texto = (f"## Lo que leyó el código\nTe lo muestro porque {motivo}.\n"
             f"Configuración: {json.dumps(entrada.model_dump(exclude_defaults=True), ensure_ascii=False)}\n")
    try:
        tabla = inputs.leer(contenido, entrada)
    except Exception as e:
        return texto + f"Con esa configuración el lector falló: {e}"
    medida = controles.lectura(tabla)
    texto += (f"Salieron {len(tabla)} filas, columnas {list(map(str, tabla.columns))}, "
              f"con fecha y hora en el {medida['con_horario']:.0%}.")
    if hojas := tabla.attrs.get("hojas"):
        texto += f" Leyó {hojas} hojas."
    if salteadas := tabla.attrs.get("salteadas"):
        texto += " Salteó: " + "; ".join(salteadas)[:500] + "."
    return texto + "\nPrimeras filas:\n" + tabla.head(FILAS_MUESTRA).to_string(max_colwidth=40)[:2500]


def proponer(contenido: bytes, proveedor: Proveedor, modelo: str, esperado: pd.DataFrame | None = None,
             previa: PropuestaLectura | None = None, codigo=None, motivo: str = "") -> PropuestaLectura:
    """Pide al agente cómo leer el archivo y lo prueba.

    `codigo` es la lectura que armó la detección: el agente puede aceptarla o cambiarla. `previa` es lo que
    intentó otro modelo, para partir de ahí.
    """
    pedido = vista_cruda(contenido)
    if codigo is not None:
        pedido += "\n\n" + lo_del_codigo(contenido, codigo, motivo or "es una lectura nueva")
    if previa and previa.entrada:
        pedido += (f"\n\nOtro intento propuso {json.dumps(previa.entrada, ensure_ascii=False)} y falló:\n- "
                   + "\n- ".join(previa.problemas))
    mensajes = [{"role": "user", "content": pedido}]
    resultado = PropuestaLectura(logrado=False)
    for vuelta in range(1, MAX_VUELTAS + 1):
        r = proveedor.pedir_json(sistema(), mensajes, FORMATO, modelo, "low")
        resultado.vueltas = vuelta
        resultado.tokens_entrada += r.tokens_entrada
        resultado.tokens_salida += r.tokens_salida
        resultado.modelo = r.modelo or modelo
        if r.rechazo:
            resultado.problemas = [f"El agente no quiso responder ({r.rechazo})."]
            return resultado
        if (pedida := str((r.datos or {}).get("ver_hoja") or "").strip()) and _es_excel(contenido):
            resultado.problemas = [f"Pidió ver la hoja {pedida} y no llegó a proponer una lectura."]
            mensajes += [{"role": "assistant", "content": r.texto or "(respuesta vacía)"},
                         {"role": "user", "content": _hoja_pedida(contenido, pedida)}]
            continue
        acepta = bool((r.datos or {}).get("aceptar")) and codigo is not None
        datos = {"entrada_json": codigo.model_dump_json()} if acepta else r.datos
        entrada, medida, problemas = _probar(contenido, datos, esperado)
        if acepta and problemas:
            problemas.insert(0, "Aceptaste la lectura del código, pero no pasa los controles.")
        resultado.entrada, resultado.medida, resultado.problemas = entrada, medida, problemas
        resultado.explicacion = (r.datos or {}).get("explicacion", "")
        if not problemas:
            resultado.logrado, resultado.acepto = True, acepta
            return resultado
        mensajes += [
            {"role": "assistant", "content": r.texto or "(respuesta vacía)"},
            {"role": "user", "content": "Probé esa lectura y pasó esto:\n- " + "\n- ".join(problemas)
                                        + "\n\nCorregí y devolvé la configuración completa otra vez."},
        ]
    return resultado


def buscar(contenido: bytes, proveedor: Proveedor, esperado: pd.DataFrame | None = None, codigo=None,
           motivo: str = "") -> list[PropuestaLectura]:
    """Haiku y, si no pasa los controles, Sonnet arrancando de lo de Haiku. La última propuesta es la que vale."""
    haiku = proponer(contenido, proveedor, cliente.MODELO, esperado, codigo=codigo, motivo=motivo)
    if haiku.logrado:
        return [haiku]
    return [haiku, proponer(contenido, proveedor, cliente.MODELO_FUERTE, esperado, previa=haiku, codigo=codigo,
                            motivo=motivo)]
