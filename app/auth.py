"""Usuarios y sesiones en la base, con contraseñas hasheadas con scrypt."""
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from app import db

COOKIE = "autortv_sesion"
DURACION_SESION = 7 * 24 * 3600


@dataclass
class Usuario:
    id: int
    usuario: str
    admin: bool


def _hashear(clave: str, sal: bytes | None = None) -> str:
    sal = sal or os.urandom(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=2**14, r=8, p=1)
    return f"{sal.hex()}${h.hex()}"


def _clave_ok(clave: str, guardado: str) -> bool:
    sal, _ = guardado.split("$")
    return hmac.compare_digest(_hashear(clave, bytes.fromhex(sal)), guardado)


def crear_usuario(usuario: str, clave: str, admin: bool = False) -> None:
    if not usuario.strip() or len(clave) < 8:
        raise ValueError("Usuario vacío o clave de menos de 8 caracteres")
    try:
        with db.transaccion() as con:
            con.execute(insert(db.usuarios).values(usuario=usuario.strip(), hash=_hashear(clave), admin=admin))
    except IntegrityError:
        raise ValueError(f"Ya existe el usuario {usuario}")


def borrar_usuario(usuario_id: int) -> None:
    with db.transaccion() as con:
        con.execute(delete(db.sesiones).where(db.sesiones.c.usuario_id == usuario_id))
        con.execute(delete(db.usuarios).where(db.usuarios.c.id == usuario_id))


def cambiar_clave(usuario_id: int, actual: str, nueva: str, sesion_actual: str | None = None) -> None:
    """Cambia la clave propia. Cierra las otras sesiones del usuario y deja abierta la actual."""
    with db.transaccion() as con:
        guardado = con.execute(select(db.usuarios.c.hash).where(db.usuarios.c.id == usuario_id)).scalar()
        if guardado is None or not _clave_ok(actual, guardado):
            raise ValueError("La clave actual no es correcta")
        _poner_clave(con, usuario_id, nueva, conservar=sesion_actual)


def resetear_clave(usuario_id: int, nueva: str) -> None:
    """El admin le pone una clave nueva a alguien. Se cortan todas sus sesiones."""
    with db.transaccion() as con:
        if con.execute(select(db.usuarios.c.id).where(db.usuarios.c.id == usuario_id)).scalar() is None:
            raise LookupError(usuario_id)
        _poner_clave(con, usuario_id, nueva)


def _poner_clave(con, usuario_id: int, nueva: str, conservar: str | None = None) -> None:
    if len(nueva) < 8:
        raise ValueError("La clave nueva tiene que tener al menos 8 caracteres")
    con.execute(update(db.usuarios).where(db.usuarios.c.id == usuario_id).values(hash=_hashear(nueva)))
    # Con la clave vieja quizás entró alguien más: sus sesiones dejan de valer.
    filtro = db.sesiones.c.usuario_id == usuario_id
    if conservar:
        filtro &= db.sesiones.c.token != conservar
    con.execute(delete(db.sesiones).where(filtro))


def listar_usuarios() -> list[Usuario]:
    with db.transaccion() as con:
        filas = con.execute(select(db.usuarios.c.id, db.usuarios.c.usuario, db.usuarios.c.admin)
                            .order_by(db.usuarios.c.usuario)).all()
    return [Usuario(i, u, bool(a)) for i, u, a in filas]


def asegurar_admin_inicial() -> None:
    """Crea el admin de ADMIN_USUARIO/ADMIN_CLAVE si todavía no hay ningún usuario."""
    usuario, clave = os.environ.get("ADMIN_USUARIO"), os.environ.get("ADMIN_CLAVE")
    if usuario and clave and not listar_usuarios():
        try:
            crear_usuario(usuario, clave, admin=True)
        except ValueError:
            pass  # otra réplica lo creó al mismo tiempo


def iniciar_sesion(usuario: str, clave: str) -> str | None:
    with db.transaccion() as con:
        fila = con.execute(select(db.usuarios.c.id, db.usuarios.c.hash).where(db.usuarios.c.usuario == usuario)).first()
        if not fila or not _clave_ok(clave, fila.hash):
            return None
        token = secrets.token_urlsafe(32)
        con.execute(delete(db.sesiones).where(db.sesiones.c.vence < time.time()))
        con.execute(insert(db.sesiones).values(token=token, usuario_id=fila.id, vence=time.time() + DURACION_SESION))
        return token


def cerrar_sesion(token: str) -> None:
    with db.transaccion() as con:
        con.execute(delete(db.sesiones).where(db.sesiones.c.token == token))


def usuario_actual(autortv_sesion: str | None = Cookie(default=None)) -> Usuario:
    if autortv_sesion:
        with db.transaccion() as con:
            fila = con.execute(
                select(db.usuarios.c.id, db.usuarios.c.usuario, db.usuarios.c.admin)
                .join(db.sesiones, db.sesiones.c.usuario_id == db.usuarios.c.id)
                .where(db.sesiones.c.token == autortv_sesion, db.sesiones.c.vence > time.time())).first()
        if fila:
            return Usuario(fila.id, fila.usuario, bool(fila.admin))
    raise HTTPException(401, "Sesión no iniciada")


def solo_admin(u: Usuario = Depends(usuario_actual)) -> Usuario:
    if not u.admin:
        raise HTTPException(403, "Solo para admin")
    return u
