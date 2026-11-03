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
ENTRADA = TypeAdapter(m.Entrada)
FORMATO = {
    "type": "object",
    "properties": {"explicacion": {"type": "string"}, "entrada_json": {"type": "string"}},
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


def _vista_hoja(contenido: bytes, hoja, filas_max: int) -> str:
    from app.inputs import cuadricula

    celdas, combinadas = cuadricula._celdas(contenido, hoja)
    filas = []
    for r, fila in enumerate(celdas[:filas_max]):
        valores = [f"{_letra(c)}={_celda(v)}" for c, v in enumerate(fila[:COLUMNAS_VISTA]) if v not in (None, "")]
        if valores:
            filas.append(f"Fila {r + 1}: " + " | ".join(valores))
    rangos = [f"{_letra(c0)}{r0 + 1}:{_letra(c1 - 1)}{r1}" for r0, r1, c0, c1 in combinadas if r0 < filas_max]
    return "\n".join(filas) + "\nCeldas combinadas: " + (", ".join(rangos[:120]) or "ninguna")


def _vista_excel(contenido: bytes) -> str:
    """La primera hoja y, si hay varias, la última: suelen diferir en lo que rompe (fechas, portadas, totales)."""
    hojas = pd.ExcelFile(io.BytesIO(contenido)).sheet_names
    vista = (f"Excel con {len(hojas)} hojas: {', '.join(hojas[:60])}.\n"
             f"Hoja 0 ({hojas[0]}). Celdas con valor (columna=valor):\n" + _vista_hoja(contenido, 0, FILAS_VISTA))
    if len(hojas) > 1:
        vista += f"\n\nÚltima hoja ({hojas[-1]}), comienzo:\n" + _vista_hoja(contenido, len(hojas) - 1, FILAS_VISTA // 2)
    return vista


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
    if contenido.startswith(b"PK") or contenido.startswith(b"\xd0\xcf\x11\xe0"):
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


def proponer(contenido: bytes, proveedor: Proveedor, modelo: str, esperado: pd.DataFrame | None = None,
             previa: PropuestaLectura | None = None) -> PropuestaLectura:
    """Pide al agente cómo leer el archivo y lo prueba. `previa` es lo que intentó otro modelo, para partir de ahí."""
    pedido = vista_cruda(contenido)
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
        entrada, medida, problemas = _probar(contenido, r.datos, esperado)
        resultado.entrada, resultado.medida, resultado.problemas = entrada, medida, problemas
        resultado.explicacion = (r.datos or {}).get("explicacion", "")
        if not problemas:
            resultado.logrado = True
            return resultado
        mensajes += [
            {"role": "assistant", "content": r.texto or "(respuesta vacía)"},
            {"role": "user", "content": "Probé esa lectura y pasó esto:\n- " + "\n- ".join(problemas)
                                        + "\n\nCorregí y devolvé la configuración completa otra vez."},
        ]
    return resultado


def buscar(contenido: bytes, proveedor: Proveedor, esperado: pd.DataFrame | None = None) -> list[PropuestaLectura]:
    """Haiku y, si no pasa los controles, Sonnet arrancando de lo de Haiku. La última propuesta es la que vale."""
    haiku = proponer(contenido, proveedor, cliente.MODELO, esperado)
    if haiku.logrado:
        return [haiku]
    return [haiku, proponer(contenido, proveedor, cliente.MODELO_FUERTE, esperado, previa=haiku)]
