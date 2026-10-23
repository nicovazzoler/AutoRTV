"""Usuarios y sesiones en SQLite, con contraseñas hasheadas con scrypt."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException

from app.config import data_dir

COOKIE = "autortv_sesion"
DURACION_SESION = 7 * 24 * 3600


@dataclass
class Usuario:
    id: int
    usuario: str
    admin: bool


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(data_dir() / "app.db")
    con.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY, usuario TEXT UNIQUE NOT NULL, hash TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sesiones (
        token TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        vence REAL NOT NULL)""")
    con.execute("PRAGMA foreign_keys = ON")
    return con


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
    with _db() as con:
        try:
            con.execute("INSERT INTO usuarios (usuario, hash, admin) VALUES (?, ?, ?)",
                        (usuario.strip(), _hashear(clave), int(admin)))
        except sqlite3.IntegrityError:
            raise ValueError(f"Ya existe el usuario {usuario}")


def borrar_usuario(usuario_id: int) -> None:
    with _db() as con:
        con.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))


def listar_usuarios() -> list[Usuario]:
    with _db() as con:
        return [Usuario(i, u, bool(a)) for i, u, a in con.execute("SELECT id, usuario, admin FROM usuarios ORDER BY usuario")]


def asegurar_admin_inicial() -> None:
    """Crea el admin de ADMIN_USUARIO/ADMIN_CLAVE si todavía no hay ningún usuario."""
    usuario, clave = os.environ.get("ADMIN_USUARIO"), os.environ.get("ADMIN_CLAVE")
    if usuario and clave and not listar_usuarios():
        crear_usuario(usuario, clave, admin=True)


def iniciar_sesion(usuario: str, clave: str) -> str | None:
    with _db() as con:
        fila = con.execute("SELECT id, hash FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
        if not fila or not _clave_ok(clave, fila[1]):
            return None
        token = secrets.token_urlsafe(32)
        con.execute("DELETE FROM sesiones WHERE vence < ?", (time.time(),))
        con.execute("INSERT INTO sesiones VALUES (?, ?, ?)", (token, fila[0], time.time() + DURACION_SESION))
        return token


def cerrar_sesion(token: str) -> None:
    with _db() as con:
        con.execute("DELETE FROM sesiones WHERE token = ?", (token,))


def usuario_actual(autortv_sesion: str | None = Cookie(default=None)) -> Usuario:
    if autortv_sesion:
        with _db() as con:
            fila = con.execute(
                "SELECT u.id, u.usuario, u.admin FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id "
                "WHERE s.token = ? AND s.vence > ?", (autortv_sesion, time.time())).fetchone()
        if fila:
            return Usuario(fila[0], fila[1], bool(fila[2]))
    raise HTTPException(401, "Sesión no iniciada")


def solo_admin(u: Usuario = Depends(usuario_actual)) -> Usuario:
    if not u.admin:
        raise HTTPException(403, "Solo para admin")
    return u
