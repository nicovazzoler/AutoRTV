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


Tarjeta = Annotated[
    Union[
        LimpiarEspacios, Reemplazar, Quitar, Separar, Extraer, MayusMinus, Asignar, ANumero, Correcciones,
        Renombrar, Numerar, RedondearHora, DiaSemana, Duracion, ClasificarSinopsis,
    ],
    Field(discriminator="tipo"),
]



class EntradaExcel(Base):
    tipo: Literal["excel"]
    hoja: int | str = 0
    fila_encabezado: int = 1  # 1 = primera fila del Excel


class Salida(Base):
    columnas: list[str]


class Validaciones(Base):
    dia_minutos: int | None = 1440
    huecos: bool = True
    superposiciones: bool = True
    filas_esperadas: int | None = None


class Senal(Base):
    schema_version: Literal[1] = 1
    id: str
    nombre: str
    entrada: EntradaExcel
    tarjetas: list[Tarjeta]
    salida: Salida
    validaciones: Validaciones = Validaciones()
