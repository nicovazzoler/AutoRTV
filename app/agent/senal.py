"""El agente de la señal: deja la grilla de un ejemplo igual a su EPG terminado probando lecturas, reglas y código.

Ve la grilla cruda y lo que sale fila por fila, prueba lo que quiera y guarda solo lo que mejora el ejemplo. El código
que escribe corre en la caja (app.caja) y entra a la receta comprobado contra el ejemplo.
"""
import json
import logging
import typing
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pydantic import Field, TypeAdapter, ValidationError

from app import export, inputs
from app.agent import asistente, cliente, controles, herramientas, lectura, uso
from app.caja import datos as datos_caja
from app.caja import pasos
from app.engine import model as m
from app.engine.comparar import diferencias, porcentaje_igual
from app.engine.pipeline import aplicar, armar_salida, paso_final

MAX_PASOS = 24
TOPE_USD = 2.0
EFFORT = "medium"
MAX_TOKENS = 16000
FILAS_DE_MUESTRA = 8
MAX_VISTA = 8000
TARJETAS = TypeAdapter(list[m.Tarjeta])
# Las lecturas que hay, sin el lector en código: ese va aparte, en lector_codigo.
_LECTURAS = tuple(t for t in typing.get_args(typing.get_args(m.Entrada)[0]) if t is not m.EntradaCodigo)
ENTRADA = TypeAdapter(typing.Annotated[typing.Union[_LECTURAS], Field(discriminator="tipo")])


@dataclass
class EjemploCrudo:
    nombre: str
    contenido: bytes  # la grilla como vino
    esperado: pd.DataFrame  # el EPG terminado


@dataclass
class Trabajo:
    receta: m.Senal | None  # None = no guardó nada que mejore el ejemplo
    antes: float
    despues: float
    explicacion: str = ""
    codigo: list[str] = field(default_factory=list)  # "lector" y "paso final", si guardó código
    pasos: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    modelo: str = ""
    costo: float = 0.0
    final: str = ""  # lo último que dijo el agente
    resultado: str = ""  # cómo dio lo guardado contra el ejemplo


@dataclass
class Medida:
    porcentajes: dict[str, float] = field(default_factory=dict)
    lecturas: dict[str, dict] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)
    error_lectura: str = ""
    # Por ejemplo: la grilla leída, la salida, de qué fila de la grilla sale cada una y los pares con el ejemplo.
    tablas: dict[str, pd.DataFrame] = field(default_factory=dict)
    salidas: dict[str, pd.DataFrame] = field(default_factory=dict)
    origenes: dict[str, list[int | None]] = field(default_factory=dict)
    pares: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    # Filas del ejemplo, dentro de los días que cubre el EPG, que no tienen ninguna fila del EPG a esa hora.
    faltan: dict[str, list[int]] = field(default_factory=dict)

    def de(self, nombre: str) -> float:
        return self.porcentajes.get(nombre, 0.0)

    def cuantas_faltan(self, nombre: str) -> int:
        return len(self.faltan.get(nombre, []))


def _leer(e: EjemploCrudo, entrada) -> pd.DataFrame:
    # Un lector en código se mide solo: si falla, no tiene que caer en silencio a la lectura detectada.
    if entrada.tipo == "codigo":
        return inputs.leer(e.contenido, entrada)
    return inputs.leer_ejemplo(e.contenido, entrada, e.esperado)


def medir(receta: m.Senal, ejemplos: list[EjemploCrudo]) -> Medida:
    """La receta contra cada ejemplo: lectura, % de celdas iguales y lo que hace falta para mostrar las diferencias."""
    medida = Medida()
    for e in ejemplos:
        try:
            tabla = _leer(e, receta.entrada)
        except Exception as ex:
            medida.error_lectura = f"{e.nombre}: {ex}"[:600]
            medida.porcentajes[e.nombre] = 0.0
            continue
        r = aplicar(tabla, receta.tarjetas, receta.titulos_conocidos)
        salida, origen, informe = paso_final(armar_salida(r.tabla, receta.salida), receta)
        medida.errores += [f"{i.id}: {i.error}" for i in r.informes + ([informe] if informe else []) if i.error]
        ejemplo = asistente.Ejemplo(e.nombre, tabla, e.esperado)
        pares = ejemplo.pares_de(salida)
        medida.lecturas[e.nombre] = controles.lectura(tabla, e.esperado)
        medida.porcentajes[e.nombre] = round(porcentaje_igual(salida, e.esperado, pares), 2)
        medida.tablas[e.nombre], medida.salidas[e.nombre] = tabla, salida
        medida.origenes[e.nombre] = origen if origen is not None else list(range(len(salida)))
        medida.pares[e.nombre] = pares if pares is not None else [(i, i) for i in range(min(len(salida), len(e.esperado)))]
        medida.faltan[e.nombre] = _faltan(salida, e.esperado, medida.pares[e.nombre]) if pares is not None else []
    medida.errores = list(dict.fromkeys(medida.errores))[:10]
    return medida


def _faltan(salida: pd.DataFrame, esperado: pd.DataFrame, pares: list[tuple[int, int]]) -> list[int]:
    """Filas del ejemplo sin pareja en el EPG, de los días que el EPG cubre: el % no las ve, y son filas que faltan."""
    dias = {k[0] for k in controles.claves_de_horario(salida) if k}
    if not dias:
        return []
    desde, hasta, con_pareja = min(dias), max(dias), {i for i, _ in pares}
    return [i for i, k in enumerate(controles.claves_de_horario(esperado))
            if i not in con_pareja and k and desde <= k[0] <= hasta]


def _fila(df: pd.DataFrame, i: int | None) -> dict | None:
    if i is None or not 0 <= i < len(df):
        return None
    return {str(c): export.celda_json(v) for c, v in zip(df.columns, df.iloc[i])}


def _columna_excel(n: int) -> str:
    letras = ""
    n += 1
    while n:
        n, resto = divmod(n - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


HERRAMIENTAS = [
    {"name": "ver_archivo",
     "description": "La grilla de un ejemplo tal como vino. Excel: las celdas de una hoja, numeradas desde 1 como en "
                    "Excel, y las celdas combinadas. Texto, HTML, XML o Word: las líneas. PDF: el texto y las tablas de "
                    "las páginas. Zip: la lista de archivos o, con `archivo`, uno de ellos.",
     "input_schema": {"type": "object", "properties": {
         "ejemplo": {"type": "string", "description": "Nombre del ejemplo; vacío = el principal."},
         "archivo": {"type": "integer", "description": "En un zip, qué archivo (0 = el primero)."},
         "hoja": {"type": "string", "description": "En Excel, el nombre o el número de la hoja (0 = la primera)."},
         "desde": {"type": "integer", "description": "Primera fila, línea o página (desde 0)."},
         "hasta": {"type": "integer", "description": "Hasta qué fila, línea o página, sin incluirla."}},
         "additionalProperties": False}},
    {"name": "ver_resultado",
     "description": "Fila por fila del ejemplo: la fila de la grilla de la que sale, cómo queda en el EPG y cómo tenía "
                    "que quedar, con las columnas que no coinciden. Muestra lo último que probaste o la receta de hoy.",
     "input_schema": {"type": "object", "properties": {
         "ejemplo": {"type": "string", "description": "Nombre del ejemplo; vacío = el principal."},
         "solo_diferencias": {"type": "boolean", "description": "true (por defecto) = solo las filas que no coinciden."},
         "desde": {"type": "integer", "description": "Desde qué fila del ejemplo (desde 1)."},
         "cuantas": {"type": "integer", "description": "Cuántas filas mostrar (hasta 40)."}},
         "additionalProperties": False}},
    {"name": "probar",
     "description": "Aplica cambios sobre lo último que probaste (o la receta de hoy) y mide contra los ejemplos: cómo "
                    "lee la grilla, el % de celdas iguales y las primeras diferencias. No guarda nada. Mandá solo lo "
                    "que cambia; cada campo reemplaza entero al anterior.",
     "input_schema": {"type": "object", "properties": {
         "entrada": {"type": "object", "description": "La lectura completa, como en el schema de lecturas."},
         "tarjetas": {"type": "array", "items": {"type": "object"},
                      "description": "La lista completa de tarjetas, en orden, como en el schema de tarjetas."},
         "columnas_salida": {"type": "array", "items": {"type": "string"}},
         "lector_codigo": {"type": "string", "description": "Python con def leer(datos). Vacío = sin lector en código."},
         "final_codigo": {"type": "string", "description": "Python con def ajustar(filas). Vacío = sin paso final."}},
         "additionalProperties": False}},
    {"name": "guardar",
     "description": "Guarda lo último que probaste, si mejora el ejemplo principal sin empeorar los otros. Con esto "
                    "terminás.",
     "input_schema": {"type": "object", "properties": {
         "explicacion": {"type": "string", "description": "Para una persona que no programa: qué cambiaste y qué queda."},
         "explicacion_codigo": {"type": "string",
                                "description": "Si hay código nuevo: qué hace, en palabras simples. Si no, vacío."}},
         "required": ["explicacion"], "additionalProperties": False}},
]


def sistema() -> str:
    texto = (Path(__file__).parent / "prompts" / "senal.md").read_text(encoding="utf-8")
    return (texto + "\n\n## Schema de tarjetas\n" + json.dumps(TypeAdapter(m.Tarjeta).json_schema(), ensure_ascii=False)
            + "\n\n## Schema de lecturas\n"
            + json.dumps(ENTRADA.json_schema(), ensure_ascii=False))


class Estado:
    """Lo que el agente probó en esta corrida. Nada se guarda en la señal hasta que la corrida termina."""

    def __init__(self, receta: m.Senal, ejemplos: list[EjemploCrudo]):
        self.receta, self.ejemplos = receta, ejemplos
        self.principal = ejemplos[0].nombre
        self.inicial = medir(receta, ejemplos)
        self.probada: tuple[m.Senal, Medida] | None = None
        self.guardada: m.Senal | None = None
        self.explicacion = ""
        self.resultado = ""
        self.codigo: list[str] = []
        self._archivos: dict[str, dict] = {}

    def actual(self) -> tuple[m.Senal, Medida]:
        return self.probada or (self.receta, self.inicial)

    def usar(self, nombre: str, datos: dict) -> str:
        funcion = {"ver_archivo": self.ver_archivo, "ver_resultado": self.ver_resultado, "probar": self.probar,
                   "guardar": self.guardar}.get(nombre)
        if funcion is None:
            return f"No existe la herramienta {nombre}."
        try:
            return herramientas.a_texto(funcion(**datos))
        except TypeError as e:
            return f"Datos que no van en {nombre}: {e}"
        except Exception as e:  # el agente ve el error y sigue; acá queda para encontrarlo
            logging.getLogger("autortv").exception("Herramienta %s del agente de la señal", nombre)
            return f"Falló {nombre}: {type(e).__name__}: {e}"[:1500]

    def _ejemplo(self, nombre: str) -> EjemploCrudo:
        return next((e for e in self.ejemplos if e.nombre == nombre), self.ejemplos[0])

    def ver_archivo(self, ejemplo: str = "", archivo: int | None = None, hoja: str | None = None, desde: int = 0,
                    hasta: int | None = None):
        e = self._ejemplo(ejemplo)
        if e.nombre not in self._archivos:
            self._archivos[e.nombre] = datos_caja.del_archivo(e.contenido, e.nombre)
        d = self._archivos[e.nombre]
        if d["tipo"] == "varios":
            if archivo is None:
                return {"tipo": "varios", "nota": "Pedí uno con archivo=N.",
                        "archivos": [{"archivo": i, "nombre": a["nombre"], "tipo": a["tipo"]} for i, a in enumerate(d["archivos"])]}
            d = d["archivos"][archivo]
        if d["tipo"] == "excel":
            hojas = d["hojas"]
            h = next((x for x in hojas if x["nombre"] == hoja), None)
            if h is None:
                numero = int(hoja) if str(hoja or 0).isdigit() else 0
                if numero >= len(hojas):
                    return {"error": f"No hay hoja {hoja}. Las hojas son: {[x['nombre'] for x in hojas]}"}
                h = hojas[numero]
            hasta = desde + 60 if hasta is None else hasta
            combinadas = [f"{_columna_excel(c0)}{r0 + 1}:{_columna_excel(c1 - 1)}{r1}"
                          for r0, r1, c0, c1 in h["combinadas"] if r0 < hasta and r1 > desde]
            return {"tipo": "excel", "hojas": [x["nombre"] for x in hojas], "hoja": h["nombre"], "filas": len(h["celdas"]),
                    "combinadas": combinadas[:150],
                    "celdas": {str(desde + i + 1): fila for i, fila in enumerate(h["celdas"][desde:hasta])}}
        if d["tipo"] == "pdf":
            hasta = desde + 2 if hasta is None else hasta
            return {"tipo": "pdf", "paginas_total": len(d["paginas"]), "paginas": d["paginas"][desde:hasta]}
        if d["tipo"] == "word":
            hasta = desde + 80 if hasta is None else hasta
            return {"tipo": "word", "parrafos_total": len(d["parrafos"]), "parrafos": d["parrafos"][desde:hasta],
                    "tablas": [t[:40] for t in d["tablas"][:3]]}
        lineas = d["texto"].splitlines()
        hasta = desde + 80 if hasta is None else hasta
        return {"tipo": d["tipo"], "lineas_total": len(lineas), "lineas": {str(desde + i): x for i, x in enumerate(lineas[desde:hasta])}}

    def ver_resultado(self, ejemplo: str = "", solo_diferencias: bool = True, desde: int = 1, cuantas: int = 15):
        receta, medida = self.actual()
        e = self._ejemplo(ejemplo)
        if e.nombre not in medida.salidas:
            return {"error": medida.error_lectura or "Ese ejemplo no se pudo leer."}
        salida, tabla, origen = medida.salidas[e.nombre], medida.tablas[e.nombre], medida.origenes[e.nombre]
        pares = medida.pares[e.nombre]
        distintas: dict[int, list[str]] = {}
        for d in diferencias(salida, e.esperado, pares):
            distintas.setdefault(d["fila"], []).append(str(d["columna"]))
        pareja = dict(pares)
        filas = [i for i in sorted(pareja) if i >= desde - 1 and (not solo_diferencias or i in distintas)][:max(1, min(cuantas, 40))]
        vistas = [{"fila_ejemplo": i + 1, "fila_epg": pareja[i] + 1, "no_coinciden": distintas.get(i, []),
                   "grilla": _fila(tabla, origen[pareja[i]] if pareja[i] < len(origen) else None),
                   "queda": _fila(salida, pareja[i]), "tenia_que_quedar": _fila(e.esperado, i)} for i in filas]
        faltan = [{"fila_ejemplo": i + 1, "tenia_que_quedar": _fila(e.esperado, i)} for i in medida.faltan.get(e.nombre, [])]
        return {"ejemplo": e.nombre, "porcentaje": medida.de(e.nombre), "filas_ejemplo": len(e.esperado),
                "filas_epg": len(salida), "filas_con_diferencias": len(distintas), "filas": vistas,
                "faltan_en_el_epg": faltan[:20], "cuantas_faltan": len(faltan)}

    def _con_cambios(self, entrada, tarjetas, columnas_salida, lector_codigo, final_codigo) -> m.Senal:
        receta = self.actual()[0]
        cambios: dict = {}
        if entrada is not None:
            cambios["entrada"] = ENTRADA.validate_python(entrada)
            if inputs.con_codigo(cambios["entrada"]):
                raise ValueError("El lector en código va en lector_codigo, no adentro de entrada.")
        if lector_codigo is not None:
            if lector_codigo.strip():
                cambios["entrada"] = m.EntradaCodigo(tipo="codigo", lector=m.Codigo(codigo=lector_codigo, autor="agente"))
            elif receta.entrada.tipo == "codigo":
                previa = self.receta.entrada if self.receta.entrada.tipo != "codigo" else None
                cambios["entrada"] = previa or inputs.detectar(self.ejemplos[0].contenido)
        if tarjetas is not None:
            cambios["tarjetas"] = TARJETAS.validate_python(tarjetas)
        if columnas_salida is not None:
            cambios["salida"] = m.Salida(columnas=columnas_salida)
        if final_codigo is not None:
            cambios["final"] = m.Codigo(codigo=final_codigo, autor="agente") if final_codigo.strip() else None
        return receta.model_copy(update=cambios)

    def probar(self, entrada: dict | None = None, tarjetas: list | None = None, columnas_salida: list | None = None,
               lector_codigo: str | None = None, final_codigo: str | None = None):
        try:
            receta = self._con_cambios(entrada, tarjetas, columnas_salida, lector_codigo, final_codigo)
        except (ValidationError, ValueError) as e:
            return {"error": f"Cambios que no validan: {str(e)[:1500]}"}
        medida = medir(receta, self.ejemplos)
        self.probada = (receta, medida)
        principal = self.principal
        resumen = {"ejemplos": {n: {"hoy": self.inicial.de(n), "con_esto": medida.de(n),
                                    "filas_que_faltan_hoy": self.inicial.cuantas_faltan(n),
                                    "filas_que_faltan_con_esto": medida.cuantas_faltan(n)} for n in medida.porcentajes},
                   "lectura": medida.lecturas.get(principal), "errores": medida.errores}
        if medida.error_lectura:
            resumen["error_lectura"] = medida.error_lectura
        elif problemas := controles.problemas_de_lectura(medida.lecturas[principal]):
            resumen["problemas_de_la_grilla_cruda"] = problemas  # antes de reglas y paso final
        if principal in medida.salidas:
            difs = diferencias(medida.salidas[principal], self.ejemplos[0].esperado, medida.pares[principal])
            resumen["diferencias"] = len(difs)
            resumen["primeras"] = [{"fila_ejemplo": d["fila"] + 1, "columna": str(d["columna"]),
                                    "queda": export.celda_json(d["obtenido"]),
                                    "tenia_que_quedar": export.celda_json(d["esperado"])} for d in difs[:12]]
        return resumen

    def guardar(self, explicacion: str, explicacion_codigo: str = ""):
        if self.probada is None:
            return "Todavía no probaste nada: usá probar antes de guardar."
        receta, medida = self.probada
        principal, antes, despues = self.principal, self.inicial.de(self.principal), medida.de(self.principal)
        if medida.error_lectura:
            return f"No se guarda: la lectura falla ({medida.error_lectura})."
        menos_faltan = medida.cuantas_faltan(principal) < self.inicial.cuantas_faltan(principal)
        if not (despues > antes or (despues >= antes and menos_faltan)):
            return (f"No se guarda: el ejemplo {principal} da {despues:g} % y hoy da {antes:g} %, y le faltan "
                    f"{medida.cuantas_faltan(principal)} filas (hoy {self.inicial.cuantas_faltan(principal)}). "
                    "Tiene que mejorar.")
        if peores := [n for n, p in medida.porcentajes.items() if p < self.inicial.de(n) - 0.5]:
            return f"No se guarda: empeoran {', '.join(peores)}."
        lector_nuevo = receta.entrada.tipo == "codigo" and receta.entrada != self.receta.entrada
        final_nuevo = receta.final is not None and receta.final != self.receta.final
        if lector_nuevo and (problemas := controles.problemas_de_lectura(medida.lecturas[principal])):
            return "No se guarda: el lector en código no pasa los controles de lectura: " + " ".join(problemas)
        if (lector_nuevo or final_nuevo) and not explicacion_codigo.strip():
            return "Falta explicacion_codigo: contá qué hace el código, en palabras simples, para quien no lo lee."
        resultado = f"El ejemplo {principal} pasó de {antes:g} % a {despues:g} %."
        if menos_faltan:
            resultado += (f" Le faltaban {self.inicial.cuantas_faltan(principal)} filas y ahora "
                          f"{medida.cuantas_faltan(principal) or 'ninguna'}.")
        comprobado = {"explicacion": explicacion_codigo.strip(), "comprobado": True, "resultado": resultado}
        if lector_nuevo:
            lector = receta.entrada.lector.model_copy(update=comprobado)
            receta = receta.model_copy(update={"entrada": receta.entrada.model_copy(update={"lector": lector})})
            self.codigo.append("lector")
        if final_nuevo:
            receta = receta.model_copy(update={"final": receta.final.model_copy(update=comprobado)})
            self.codigo.append("paso final")
        self.guardada, self.explicacion, self.resultado = receta, explicacion.strip(), resultado
        return f"Guardado. {resultado}"


def _contexto(estado: Estado, pedido: str) -> str:
    receta, medida, e = estado.receta, estado.inicial, estado.ejemplos[0]
    partes = [f"## Señal: {receta.nombre} ({receta.id})"]
    if pedido.strip():
        partes += ["## Lo que pidió la persona", pedido.strip()]
    if motivo := pasos.apagada():
        partes.append(f"## Código\nEn este servidor el código no puede correr ({motivo}): usá solo lecturas y tarjetas.")
    partes += ["## Receta de hoy", json.dumps({"entrada": receta.entrada.model_dump(exclude_defaults=True),
                                               "tarjetas": [t.model_dump(exclude_none=True) for t in receta.tarjetas],
                                               "columnas_salida": receta.salida.columnas,
                                               "final_codigo": receta.final.codigo if receta.final else None},
                                              ensure_ascii=False)]
    partes += ["## Cómo da hoy", json.dumps({"ejemplos": medida.porcentajes,
                                             "filas_del_ejemplo_que_faltan": {n: medida.cuantas_faltan(n) for n in medida.faltan},
                                             "lectura": medida.lecturas.get(e.nombre),
                                             "error_lectura": medida.error_lectura or None, "errores": medida.errores},
                                            ensure_ascii=False, default=str)]
    partes += [f"## Ejemplos: {', '.join(x.nombre for x in estado.ejemplos)}. El principal es {e.nombre}: {len(e.esperado)} "
               f"filas, columnas {[str(c) for c in e.esperado.columns]}. Así arranca:",
               json.dumps([_fila(e.esperado, i) for i in range(min(FILAS_DE_MUESTRA, len(e.esperado)))], ensure_ascii=False)]
    partes += ["## La grilla del ejemplo principal, como vino (el comienzo)", lectura.vista_cruda(e.contenido)[:MAX_VISTA]]
    partes.append("Empezá mirando las diferencias con ver_resultado.")
    return "\n\n".join(partes)


def trabajar(receta: m.Senal, ejemplos: list[EjemploCrudo], proveedor, pedido: str = "",
             avisar=lambda texto: None) -> Trabajo:
    """Hasta MAX_PASOS vueltas con herramientas, o hasta gastar TOPE_USD. El primer ejemplo es el que tiene que quedar."""
    estado = Estado(receta, ejemplos)
    antes = estado.inicial.de(estado.principal)
    trabajo = Trabajo(None, antes, antes)
    mensajes = [{"role": "user", "content": _contexto(estado, pedido)}]
    texto = sistema()
    for paso in range(1, MAX_PASOS + 1):
        r = proveedor.con_herramientas(texto, mensajes, HERRAMIENTAS, modelo=cliente.MODELO_FUERTE, effort=EFFORT,
                                       max_tokens=MAX_TOKENS)
        trabajo.pasos = paso
        trabajo.tokens_entrada += r.tokens_entrada
        trabajo.tokens_salida += r.tokens_salida
        trabajo.modelo = r.modelo or trabajo.modelo
        trabajo.costo = uso.costo(trabajo.modelo, trabajo.tokens_entrada, trabajo.tokens_salida) or 0.0
        if r.rechazo:
            trabajo.final = f"El modelo no quiso seguir ({r.rechazo})."
            break
        usos = [b for b in r.bloques if b.get("type") == "tool_use"]
        if r.parar != "tool_use" or not usos:
            trabajo.final = r.texto
            break
        resultados = []
        for b in usos:
            resultados.append({"type": "tool_result", "tool_use_id": b["id"], "content": estado.usar(b["name"], b.get("input") or {})})
            avisar(_que_hizo(b["name"], estado))
        mensajes += [{"role": "assistant", "content": r.bloques}, {"role": "user", "content": resultados}]
        if estado.guardada is not None:
            break
        if trabajo.costo > TOPE_USD:
            trabajo.final = f"Paré al llegar al tope de US$ {TOPE_USD:g} para esta señal."
            break
    else:
        trabajo.final = f"Me quedé sin vueltas ({MAX_PASOS})."
    if estado.guardada is not None:
        trabajo.receta, trabajo.explicacion, trabajo.codigo = estado.guardada, estado.explicacion, estado.codigo
        trabajo.resultado = estado.resultado
        trabajo.despues = estado.probada[1].de(estado.principal)
    return trabajo


def _que_hizo(herramienta: str, estado: Estado) -> str:
    if herramienta == "probar" and estado.probada is not None:
        receta, medida = estado.probada
        con = ("un lector en código" if receta.entrada.tipo == "codigo" else "") or ("un paso final en código" if receta.final else "")
        return f"probó {con or 'cambios'}: el ejemplo da {medida.de(estado.principal):g} %"
    return {"ver_archivo": "mira la grilla", "ver_resultado": "compara fila por fila con el ejemplo",
            "guardar": "guarda lo que mejoró"}.get(herramienta, herramienta)
