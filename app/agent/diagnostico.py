"""Qué le falta al lector de hoy en cada señal: un paso del Banco sin agente ni costo.

Lee la grilla del ejemplo como la lee la señal y como la detecta el código, la compara con el ejemplo y busca en
el archivo de dónde salen los datos del ejemplo. Cada hallazgo trae su evidencia, para poder revisarlo a mano.
"""
import io
import re
from pathlib import PurePosixPath

import pandas as pd

from app import fechar, inputs, pautas
from app.agent import controles, lectura
from app.engine import model as m

# Lo que necesita cada hallazgo, del más fuerte al más liviano.
NECESITA = {"no_lee": "codigo", "pdf_sin_texto": "ocr", "elegir_hoja": "opcion", "hoja_de_datos": "opcion",
            "fecha_por_archivo": "opcion", "lectura_guardada_mala": "actualizar", "zona_horaria": "reglas",
            "falta_en_el_archivo": "base", "lectura_guardada_vieja": "nada", "elige_el_lunes": "nada", "lee_bien": "nada"}
ORDEN = list(NECESITA)
MAX_HOJAS = 31
MIN_LARGO_VALOR = 5  # valores más cortos aparecen en cualquier lado ("cine", "1")
MAX_VALORES = 150
# Un dato del ejemplo "está" en una hoja si aparece ahí al menos esta parte de sus valores.
ESTA = 0.6
NO_ESTA = 0.3
LEIDO = "(lo que se lee)"
DIAS = {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", "segunda", "terca", "quarta",
        "quinta", "sexta", "segundafeira", "tercafeira", "quartafeira", "quintafeira", "sextafeira", "monday",
        "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


def _pasa(medida: dict | None) -> bool:
    return bool(medida) and not controles.problemas_de_lectura(medida)


def _puntaje(medida: dict | None) -> float:
    if not medida:
        return -1.0
    return medida["con_horario"] + (medida["empareja"] or 0)


def _leer(contenido: bytes, entrada, esperado) -> tuple[pd.DataFrame | None, dict | None, str]:
    try:
        tabla = inputs.leer(contenido, entrada)
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"[:300]
    return tabla, controles.lectura(tabla, esperado), ""


def _es_excel(contenido: bytes) -> bool:
    return lectura._es_excel(contenido)


def _por_hoja(contenido: bytes, esperado) -> list[dict]:
    """Cada hoja leída sola (como tabla y, si lo parece, como cuadrícula), con lo que da contra el ejemplo."""
    from app.inputs import cuadricula, excel

    nombres = pd.ExcelFile(io.BytesIO(contenido)).sheet_names[:MAX_HOJAS]
    hojas = []
    for i, nombre in enumerate(nombres):
        entradas = []
        try:
            if cuadricula.es_cuadricula(contenido, i):
                entradas.append(m.EntradaExcel(tipo="excel", cuadricula=True, hoja=i))
            entradas.append(m.EntradaExcel(tipo="excel", hoja=i,
                                           fila_encabezado=excel.detectar_fila_encabezado(io.BytesIO(contenido), i)))
        except Exception:
            pass
        mejor = {"hoja": i, "nombre": nombre, "filas": 0, "medida": None, "entrada": None}
        for entrada in entradas:
            tabla, medida, _ = _leer(contenido, entrada, esperado)
            if tabla is not None and _puntaje(medida) > _puntaje(mejor["medida"]):
                mejor.update(filas=len(tabla), medida=medida, entrada=entrada.model_dump(exclude_defaults=True))
        hojas.append(mejor)
    return hojas


def _textos(contenido: bytes, tabla: pd.DataFrame | None) -> dict[str, str]:
    """El texto normalizado de cada hoja del archivo (o del archivo entero), para buscar los datos del ejemplo."""
    if _es_excel(contenido):
        from app.inputs import cuadricula

        return {nombre: "|".join(pautas.normalizar(v) for fila in celdas for v in fila if v not in (None, ""))
                for nombre, celdas, _ in cuadricula.todas_las_celdas(contenido, MAX_HOJAS)}
    if contenido.startswith(b"%PDF"):
        import pdfplumber

        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            return {"archivo": "|".join(pautas.normalizar(p.extract_text() or "") for p in pdf.pages[:20])}
    if tabla is not None and not contenido[:4000].lstrip().startswith(b"<"):
        return {"archivo": "|".join(pautas.normalizar(v) for v in tabla.to_numpy().ravel())}
    from app.inputs import texto

    return {"archivo": pautas.normalizar(texto.decodificar(contenido))}


def _hojas_leidas(tabla: pd.DataFrame, nombres: list[str]) -> list[str]:
    """Los nombres de las hojas que leyó una lectura de Excel (el lector las anota; una hoja pedida por número, también)."""
    return [nombres[h] if isinstance(h, int) and h < len(nombres) else str(h) for h in tabla.attrs.get("nombres_hojas", [0])]


def _donde_estan(esperado: pd.DataFrame, textos: dict[str, str]) -> dict[str, dict[str, float]]:
    """Para cada columna de texto del ejemplo, qué parte de sus valores aparece en cada grupo de texto."""
    horario = set(pautas.columnas_de_horario(esperado))
    donde = {}
    for c in esperado.columns:
        textuales = [pautas.normalizar(v) for v in esperado[c] if isinstance(v, str)]
        # El día de la semana se arma desde la fecha: no tiene por qué estar en el archivo.
        if c in horario or (textuales and sum(t in DIAS for t in textuales) > len(textuales) / 2):
            continue
        valores = list(dict.fromkeys(n for n in textuales if len(n) >= MIN_LARGO_VALOR and not n.isdigit()))
        if len(valores) < 3:
            continue
        valores = valores[:MAX_VALORES]
        donde[str(c)] = {h: round(sum(v in t for v in valores) / len(valores), 2) for h, t in textos.items()}
    return donde


def _corrimiento(tabla: pd.DataFrame, esperado: pd.DataFrame) -> tuple[int, float, float]:
    """(horas que va corrido el ejemplo, % que empareja sin correrlo, % con el mejor corrimiento)."""
    del_ejemplo = {k for k in controles.claves_de_horario(esperado) if k}
    claves = controles.claves_de_horario(tabla, del_ejemplo)
    por_hora = controles.por_corrimiento(claves, del_ejemplo)
    if not por_hora:
        return 0, 0.0, 0.0
    horas = max(por_hora, key=lambda h: (por_hora[h], -abs(h)))
    return horas, por_hora.get(0, 0.0), por_hora[horas]


def _al_subir(guardada, detectada, contenido: bytes, esperado: pd.DataFrame | None):
    """La lectura con que la app lee esta grilla al recibirla: la guardada, corregida como la corrige al subir una nueva
    (otro formato, varias hojas). Sin agente: lo que haga el agente lo mide el paso de lectura del Banco."""
    if guardada is None or detectada is None:
        return guardada or detectada
    from app.api import rutas

    receta = m.Senal(id="diagnostico", nombre="diagnostico", entrada=guardada, tarjetas=[], salida=m.Salida(columnas=[]))
    return rutas._con_entrada(receta, detectada, contenido, esperado).entrada


FECHA_EN_NOMBRE = re.compile(r"(?<!\d)(\d{1,2}[-_. ]\d{1,2}([-_. ]\d{2,4})?|\d{4}[-_.]\d{1,2}[-_.]\d{1,2})(?!\d)")


def _fecha_en_nombre(nombre: str) -> bool:
    raiz = PurePosixPath(nombre).stem
    return bool(FECHA_EN_NOMBRE.search(raiz)) or any(d in pautas.normalizar(raiz) for d in DIAS)


def _con_el_lunes(tabla: pd.DataFrame, esperado: pd.DataFrame | None) -> dict | None:
    """Una semanal sin fechas, con el lunes del ejemplo: lo que da después de que la persona elige el lunes en la web."""
    if esperado is None or fechar.columna_de_dia(tabla) is None:
        return None
    dias = [k[0] for k in controles.claves_de_horario(esperado) if k]
    if not dias:
        return None
    return controles.lectura(fechar.fechar(tabla, fechar.lunes_de(min(dias))), esperado)


def diagnosticar(contenido: bytes, esperado: pd.DataFrame | None, guardada: dict | None = None) -> dict:
    """Qué le falta al lector para esta grilla: el hallazgo principal, lo que necesita y la evidencia.

    Se diagnostica la lectura que la app usa al subir esta grilla; la guardada y la que detecta el código van de evidencia.
    """
    hallazgos: list[dict] = []
    lecturas = {}
    try:
        detectada = inputs.detectar(contenido)
    except Exception as e:
        detectada = None
        lecturas["detectada"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    guardada_e = lectura.ENTRADA.validate_python(guardada) if guardada else None
    leidas_por = {}
    for nombre, entrada in (("guardada", guardada_e), ("al_subir", _al_subir(guardada_e, detectada, contenido, esperado)),
                            ("detectada", detectada)):
        if entrada is None:
            continue
        tabla, medida, error = _leer(contenido, entrada, esperado)
        lecturas[nombre] = {"entrada": entrada.model_dump(exclude_defaults=True), "medida": medida, "error": error or None}
        if tabla is not None:
            leidas_por[nombre] = (entrada, tabla, medida)
    mejor = leidas_por.get("al_subir")
    hojas = _por_hoja(contenido, esperado) if _es_excel(contenido) else []
    sola = max((h for h in hojas if _pasa(h["medida"])), key=lambda h: _puntaje(h["medida"]), default=None)

    if mejor is not None and not _pasa(mejor[2]) and (lunes := _con_el_lunes(mejor[1], esperado)) and _pasa(lunes):
        hallazgos.append({"tipo": "elige_el_lunes", "detalle": f"La grilla trae los días sin fecha: al subirla la web "
                                                                f"pregunta desde qué lunes, y con el del ejemplo da {lunes}."})
        mejor = (mejor[0], mejor[1], lunes)
    if guardada_e is not None and "guardada" in lecturas and mejor is not None and _pasa(mejor[2]) \
            and not _pasa(lecturas["guardada"]["medida"]):
        hallazgos.append({"tipo": "lectura_guardada_vieja",
                          "detalle": f"La lectura guardada da {lecturas['guardada']['medida']}; al subir esta grilla la "
                                     f"app la corrige sola y da {mejor[2]}."})

    if mejor is None or not _pasa(mejor[2]):
        detecta = leidas_por.get("detectada")
        if detecta and _pasa(detecta[2]):
            hallazgos.append({"tipo": "lectura_guardada_mala",
                              "detalle": f"La lectura guardada no anda con esta grilla y al subirla no se corrige sola "
                                         f"({mejor[2] if mejor else 'no se pudo leer'}); la que detecta hoy el código "
                                         f"da {detecta[2]}: hay que actualizarla."})
        elif sola:
            hallazgos.append({"tipo": "elegir_hoja", "hoja": sola["nombre"],
                              "detalle": f"La hoja «{sola['nombre']}» sola da {sola['medida']}; la lectura de hoy no pasa."})
        elif contenido.startswith(b"%PDF") and not any(_textos(contenido, None).values()):
            hallazgos.append({"tipo": "pdf_sin_texto", "detalle": "El PDF no tiene texto: es una imagen escaneada."})
        elif (nombres := _nombres_si_son_varios(contenido)) and len(nombres) >= 2 \
                and sum(map(_fecha_en_nombre, nombres)) >= 0.8 * len(nombres):
            hallazgos.append({"tipo": "fecha_por_archivo", "archivos": len(nombres),
                              "detalle": f"Son {len(nombres)} archivos sin fecha adentro y el nombre trae la fecha sin "
                                         f"año o el día de la semana («{nombres[0]}», «{nombres[-1]}»): el lector solo "
                                         "toma del nombre una fecha completa (20261102 o 02-11-2026)."})
        else:
            if nombres := _nombres_si_son_varios(contenido):
                lecturas["archivos"] = nombres[:40]
            hallazgos.append({"tipo": "no_lee", "detalle": "Ninguna lectura de hoy da fecha y hora en casi todas las filas: "
                                                           + str(mejor[2] if mejor else lecturas)})
    else:
        entrada, tabla, medida = mejor
        varias = [h for h in hojas if h["medida"] and h["medida"]["con_horario"] >= controles.UMBRAL_HORARIO]
        if len(varias) >= 2 and sola and len(tabla) > 1.5 * sola["filas"] and (tabla.attrs.get("hojas") or 1) > 1:
            hallazgos.append({"tipo": "elegir_hoja", "hoja": sola["nombre"],
                              "detalle": f"Lee {tabla.attrs.get('hojas')} hojas con horario ({len(tabla)} filas) y el "
                                         f"ejemplo sale de «{sola['nombre']}» sola ({sola['filas']} filas)."})
        if esperado is not None:
            horas, en_cero, con_corrimiento = _corrimiento(tabla, esperado)
            if horas and en_cero < 0.5 and con_corrimiento >= controles.UMBRAL_EMPAREJA:
                hallazgos.append({"tipo": "zona_horaria", "horas": horas,
                                  "detalle": f"El ejemplo va {horas:+d} h: sin correrlo empareja el {en_cero:.0%} y "
                                             f"corrido el {con_corrimiento:.0%}."})

    if esperado is not None:
        textos = _textos(contenido, mejor[1] if mejor else None)
        leidas = set(_hojas_leidas(mejor[1], list(textos)) if mejor and _es_excel(contenido) else textos)
        # Lo que se lee va junto (con todas las hojas, cada una trae un solo día); las otras hojas, cada una aparte.
        grupos = {LEIDO: "|".join(t for h, t in textos.items() if h in leidas),
                  **{h: t for h, t in textos.items() if h not in leidas}}
        for columna, en in _donde_estan(esperado, grupos).items():
            en_lectura = en[LEIDO]
            otra = max(((h, x) for h, x in en.items() if h != LEIDO), key=lambda x: x[1], default=None)
            if en_lectura < NO_ESTA and otra and otra[1] >= ESTA:
                hallazgos.append({"tipo": "hoja_de_datos", "columna": columna, "hoja": otra[0],
                                  "detalle": f"«{columna}» del ejemplo está en la hoja «{otra[0]}» ({otra[1]:.0%}) y no en "
                                             f"lo que se lee ({en_lectura:.0%})."})
            elif max(en.values(), default=0.0) < NO_ESTA:
                hallazgos.append({"tipo": "falta_en_el_archivo", "columna": columna,
                                  "detalle": f"«{columna}» del ejemplo no está tal cual en el archivo "
                                             f"({max(en.values(), default=0.0):.0%} de sus valores): sale de la base, "
                                             "a mano o muy cambiada."})

    tipos = [h["tipo"] for h in hallazgos] or ["lee_bien"]
    principal = min(tipos, key=ORDEN.index)
    return {"principal": principal, "necesita": NECESITA[principal], "hallazgos": hallazgos, "lecturas": lecturas,
            "hojas": [{k: v for k, v in h.items() if k != "entrada"} for h in hojas]}


def _nombres_si_son_varios(contenido: bytes) -> list[str]:
    from app.inputs import varios

    if not varios.es_zip_suelto(contenido):
        return []
    try:
        return [n for n, _ in varios.archivos(contenido)]
    except Exception:
        return []


def resumen(diagnosticos: list[dict]) -> dict:
    """Cuántas señales hay por lo que necesitan y por hallazgo principal."""
    necesita: dict[str, int] = {}
    principal: dict[str, int] = {}
    for d in diagnosticos:
        necesita[d["necesita"]] = necesita.get(d["necesita"], 0) + 1
        principal[d["principal"]] = principal.get(d["principal"], 0) + 1
    return {"senales": len(diagnosticos), "necesita": necesita, "principal": principal}
