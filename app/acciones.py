"""Acciones de admin que el agente puede proponer. Solo las ejecuta el servidor, para una sesión de admin."""
import datetime as dt
import secrets
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import insert, select

from app import auth, catalogo, db
from app.agent import uso


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CrearUsuario(_Base):
    tipo: Literal["crear_usuario"]
    usuario: str
    admin: bool = False


class ResetearClave(_Base):
    tipo: Literal["resetear_clave"]
    usuario: str


class CambiarLimiteDiario(_Base):
    tipo: Literal["cambiar_limite_diario"]
    valor: int = Field(ge=1, le=1000)


class CambiarReglaCatalogo(_Base):
    tipo: Literal["cambiar_regla_catalogo"]
    columna: str
    regla: str


Accion = Annotated[Union[CrearUsuario, ResetearClave, CambiarLimiteDiario, CambiarReglaCatalogo],
                   Field(discriminator="tipo")]
LISTA = TypeAdapter(list[Accion])


def describir(a) -> str:
    return {
        "crear_usuario": lambda: f"Crear el usuario {a.usuario}" + (" (admin)" if getattr(a, "admin", False) else ""),
        "resetear_clave": lambda: f"Ponerle una clave nueva a {a.usuario}",
        "cambiar_limite_diario": lambda: f"Cambiar el tope del agente a {a.valor} pedidos por persona por día",
        "cambiar_regla_catalogo": lambda: f"Cambiar la regla de la columna {a.columna} a «{a.regla}»",
    }[a.tipo]()


def _clave_nueva() -> str:
    # La genera el servidor para que nunca pase por el agente; se muestra una sola vez.
    return secrets.token_urlsafe(9)


def _id_de(usuario: str) -> int:
    with db.transaccion() as con:
        i = con.execute(select(db.usuarios.c.id).where(db.usuarios.c.usuario == usuario.strip())).scalar()
    if i is None:
        raise LookupError(f"No existe el usuario {usuario}")
    return i


def ejecutar(a, quien: str) -> dict:
    """Corre una acción y la deja registrada. Devuelve la clave generada cuando hay una."""
    resultado = {"descripcion": describir(a), "ok": True}
    if a.tipo == "crear_usuario":
        resultado["clave"] = _clave_nueva()
        auth.crear_usuario(a.usuario, resultado["clave"], a.admin)
    elif a.tipo == "resetear_clave":
        resultado["clave"] = _clave_nueva()
        auth.resetear_clave(_id_de(a.usuario), resultado["clave"])
    elif a.tipo == "cambiar_limite_diario":
        uso.poner_limite_diario(a.valor)
    elif a.tipo == "cambiar_regla_catalogo":
        catalogo.cambiar_regla(a.columna, a.regla)
    with db.transaccion() as con:
        con.execute(insert(db.registro_acciones).values(usuario=quien, fecha=dt.datetime.now(),
                                                         descripcion=resultado["descripcion"]))
    return resultado
