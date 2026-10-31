"""Forma de la receta de una señal: entrada, tarjetas, salida y validaciones.

Valida la receta, no la tabla: los nombres de columna son texto libre.
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condicion(Base):
    columna: str
    op: Literal["igual", "distinto", "contiene", "empieza", "termina", "vacio", "no_vacio", "regex"]
    # Acepta "{Otra columna}" para comparar contra el valor de otra columna de la misma fila.
    valor: str = ""


class TarjetaBase(Base):
    id: str
    activa: bool = True
    nota: str = ""
    si: Condicion | None = None


# --- Tarjetas de texto (admiten `si`) ---

class LimpiarEspacios(TarjetaBase):
    tipo: Literal["limpiar_espacios"]
    columnas: list[str] | Literal["*"] = "*"


class Reemplazar(TarjetaBase):
    tipo: Literal["reemplazar"]
    columnas: list[str] | Literal["*"]
    buscar: str
    por: str = ""
    # texto: reemplaza dentro de la celda; celda: solo si la celda entera es igual; regex: patrón.
    modo: Literal["texto", "celda", "regex"] = "texto"


class Quitar(TarjetaBase):
    tipo: Literal["quitar"]
    columnas: list[str] | Literal["*"]
    texto: str
    donde: Literal["todo", "inicio", "fin"] = "todo"
    regex: bool = False


class Separar(TarjetaBase):
    tipo: Literal["separar"]
    columna: str
    modo: Literal["separador", "min_mayus", "titulos_conocidos", "regex"]
    valor: str = ""  # el separador o el regex con 2 grupos
    destinos: tuple[str, str]
    titulos: list[str] = []  # para titulos_conocidos
    respaldo: Literal["ninguno", "min_mayus"] = "ninguno"


class Criterios(TarjetaBase):
    """Los criterios generales para leer un título (app/engine/tarjetas/criterios.py), con sus columnas de destino."""
    tipo: Literal["criterios"]
    columna: str  # el título como viene
    detalle: str | None = None  # columna con el capítulo aparte ("#1 León y Jalpa"), si la grilla la trae
    programa: str = "Programa"
    capitulo: str | None = None  # None = sin capítulo: el título entero es el programa
    temporada: str | None = None
    titulo_temporada: str | None = None  # temporada con nombre de año: "T2026"
    numero: str | None = None
    anio: str | None = None
    tt: str | None = None
    idioma: Literal["es", "en", "pt"] = "es"
    separadores: list[str] = [" - ", " – ", ": ", " | "]
    prefijos: list[str] = ["Cine:", "Película:", "Serie:", "Ciclo:"]
    titulos: list[str] = []  # programas conocidos; se suman los de la base


class Extraer(TarjetaBase):
    tipo: Literal["extraer"]
    columna: str
    preset: Literal["entre_parentesis", "numero", "anio"] | None = None
    patron: str = ""  # se usa si no hay preset; el grupo 1 (o el match entero) es lo extraído
    destino: str
    quitar_del_origen: bool = False


class MayusMinus(TarjetaBase):
    tipo: Literal["mayus_minus"]
    columnas: list[str]
    modo: Literal["MAYUS", "minus", "Titulo", "Oracion", "titulo_en"]


class Asignar(TarjetaBase):
    tipo: Literal["asignar"]
    columna: str
    valor: str  # fijo o con "{Otra}"


class Correcciones(TarjetaBase):
    tipo: Literal["correcciones"]
    columnas: list[str] | Literal["*"]
    # Celda entera tal como queda después de la limpieza -> texto corregido a mano.
    mapa: dict[str, str]


class ANumero(TarjetaBase):
    tipo: Literal["a_numero"]
    columnas: list[str]


# --- Tarjetas de estructura (trabajan sobre toda la tabla, no admiten `si`) ---

class Renombrar(TarjetaBase):
    tipo: Literal["renombrar"]
    mapa: dict[str, str]


class Numerar(TarjetaBase):
    tipo: Literal["numerar"]
    columna: str = "N"
    inicio: int = 1
    paso: int = 1


class RedondearHora(TarjetaBase):
    tipo: Literal["redondear_hora"]
    columna: str
    a_minutos: int = 1  # 1 = al minuto más cercano, 5 = a los 5 min, etc.
    destino: str | None = None  # None = en la misma columna


class DiaSemana(TarjetaBase):
    tipo: Literal["dia_semana"]
    columna: str  # columna con fecha
    destino: str = "Dia"
    idioma: Literal["es", "en"] = "es"
    mayusculas: bool = True


class Duracion(TarjetaBase):
    tipo: Literal["duracion"]
    modo: Literal["hasta_siguiente"]
    fecha: str
    hora: str
    destino: str = "Duracion"
    # Hora en que arranca la grilla del día siguiente; cierra la duración del último programa.
    ultimo_hasta: str | None = None


class ClasificarSinopsis(TarjetaBase):
    """Decide si la sinopsis es argumento del programa o del capítulo."""
    tipo: Literal["clasificar_sinopsis"]
    programa: str
    capitulo: str
    sinopsis: str
    destino_programa: str
    destino_capitulo: str
    # Va a capítulo si (sinopsis distintas / capítulos distintos) supera este valor.
    umbral: float = 0.5


class ConvertirZona(TarjetaBase):
    """Pasa la fecha y hora de una zona horaria a otra (ej. UTC → America/New_York), con horario de verano."""
    tipo: Literal["convertir_zona"]
    columna: str  # fecha y hora juntas, o solo la fecha si se indica `hora`
    hora: str | None = None
    desde: str = "UTC"
    hacia: str
    destino_fecha: str = "Fecha"
    destino_hora: str = "Hora"


Tarjeta = Annotated[
    Union[
        LimpiarEspacios, Reemplazar, Quitar, Separar, Extraer, MayusMinus, Asignar, ANumero, Correcciones, Criterios,
        Renombrar, Numerar, RedondearHora, DiaSemana, Duracion, ClasificarSinopsis, ConvertirZona,
    ],
    Field(discriminator="tipo"),
]



class Partir(Base):
    """Celdas con varios programas ("A / B") pasan a una fila por programa, repartiendo el horario en partes iguales."""
    columna: str = "Programa"
    separador: str = r"\s*/\s+"  # regex; "/" pegado al texto que sigue no corta ("Nacional /Himno")
    solo_si: str | None = None  # regex que tiene que aparecer en alguna parte, ej. una duración 7'43"
    inicio: str = "Inicio"
    fin: str = "Fin"
    a_minutos: int = 5  # cada parte se redondea a este paso


class EntradaComun(Base):
    partir: Partir | None = None


class EntradaExcel(EntradaComun):
    tipo: Literal["excel"]
    hoja: int | str = 0
    fila_encabezado: int = 1  # 1 = primera fila del Excel
    cuadricula: bool = False  # un día por columna y una franja por fila, con celdas combinadas (inputs.cuadricula)
    todas_las_hojas: bool = False  # una hoja por día (o por semana), todas con el mismo encabezado
    # Filas sueltas con la fecha ("MIÉRCOLES 30 SEPTIEMBRE 2026") que valen para las de abajo. None = detectar.
    filas_de_fecha: bool | None = None
    # Solo en cuadrícula, para cuando la detección sola no alcanza; None o vacío = detectar.
    fila_dias: int | None = None  # 1 = primera fila del Excel
    columnas_hora: list[str] = []  # letras de columna, ej. ["A", "G", "I"]
    doce_horas: bool | None = None  # horas de 12 h sin AM/PM (después de 12:30 viene 01:00)


class EntradaTexto(EntradaComun):
    """Texto pegado o .txt."""
    tipo: Literal["texto"]
    separador: str | None = None  # None = detectar (tab, ";" o "|"); "" = líneas "HH:MM programa"
    fecha_inicio: str | None = None  # AAAA-MM-DD, si el texto no trae la fecha


class EntradaXml(EntradaComun):
    tipo: Literal["xml"]
    elemento: str | None = None  # etiqueta de cada programa; None = XMLTV (<programme>)


class EntradaPdf(EntradaComun):
    tipo: Literal["pdf"]
    paginas: list[int] = []  # 1 = primera; vacío = todas (algunos PDF traen dos grillas distintas)
    fecha_inicio: str | None = None  # AAAA-MM-DD del primer día, si el PDF no la trae


class CampoHtml(Base):
    css: str | None = None  # selector dentro del bloque; None = el bloque mismo
    attr: str | None = None  # atributo a leer; None = el texto


class EntradaHtml(EntradaComun):
    tipo: Literal["html"]
    bloque: str | None = None  # selector de cada programa; None = detectar el bloque que más se repite
    campos: dict[str, CampoHtml] = {}  # vacío = una columna por cada clase y atributo del bloque
    # EPG crudo: columna fija (inputs.epg.COLUMNAS) → columna de la página. Vacío = la tabla tal como sale de la página.
    epg: dict[str, str] = {}


Entrada = Annotated[Union[EntradaExcel, EntradaTexto, EntradaXml, EntradaPdf, EntradaHtml],
                    Field(discriminator="tipo")]


class Salida(Base):
    columnas: list[str]


class Validaciones(Base):
    # Columnas de salida para validar horarios; None = detectarlas por nombre.
    fecha: str | None = None
    hora: str | None = None
    duracion: str | None = None
    dia_minutos: int | None = 1440
    max_duracion_min: int | None = 720
    tolerancia_min: int = 0
    huecos: bool = True
    superposiciones: bool = True
    filas_esperadas: int | None = None
    obligatorias: list[str] = []
    # Nota por cada programa que no está en los títulos conocidos de la señal.
    avisar_titulos_nuevos: bool = False
    programa: str | None = None  # None = detectar por nombre


class Senal(Base):
    schema_version: Literal[1] = 1
    id: str
    nombre: str
    entrada: Entrada
    tarjetas: list[Tarjeta]
    salida: Salida
    validaciones: Validaciones = Validaciones()
    # Idiomas que lleva el EPG de la señal: hacen obligatorios Tit ing / Tit port.
    idiomas: list[Literal["ing", "port"]] = []
    # Programas que la señal ya emitió; los usa `separar` en modo titulos_conocidos.
    titulos_conocidos: list[str] = []
