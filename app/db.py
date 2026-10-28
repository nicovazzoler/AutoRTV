"""Conexión y tablas. Postgres si hay DATABASE_URL; si no, SQLite en DATA_DIR (local y tests)."""
import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, MetaData,
                        String, Table, Text, create_engine, event, inspect, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.types import JSON

from app.config import data_dir

metadata = MetaData()
JSON_RECETA = JSON().with_variant(JSONB(), "postgresql")

usuarios = Table(
    "usuarios", metadata,
    Column("id", Integer, primary_key=True),
    Column("usuario", String(100), unique=True, nullable=False),
    Column("hash", String(200), nullable=False),
    Column("admin", Boolean, nullable=False, default=False),
)

sesiones = Table(
    "sesiones", metadata,
    Column("token", String(100), primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
    Column("vence", Float, nullable=False),
)

uso_agente = Table(
    "uso_agente", metadata,
    Column("id", Integer, primary_key=True),
    Column("usuario", String(100), nullable=False),
    Column("fecha", DateTime, nullable=False, index=True),
    Column("senal", String(64), nullable=False),
    Column("pedido", Text, nullable=False),
    Column("vueltas", Integer, nullable=False),
    Column("tokens_entrada", Integer, nullable=False),
    Column("tokens_salida", Integer, nullable=False),
    Column("logrado", Boolean, nullable=False),
    Column("costo_usd", Float),  # estimado con el precio del modelo que respondió; vacío en pedidos viejos
)

senales = Table(
    "senales", metadata,
    Column("id", String(64), primary_key=True),
    Column("nombre", String(200), nullable=False),
    Column("receta", JSON_RECETA, nullable=False),
    Column("version", String(32), nullable=False),
    Column("actualizado", DateTime, nullable=False),
    Column("actualizado_por", String(100), nullable=False),
)

senales_historial = Table(
    "senales_historial", metadata,
    Column("id", Integer, primary_key=True),
    Column("senal_id", String(64), nullable=False),
    Column("receta", JSON_RECETA, nullable=False),
    Column("usuario", String(100), nullable=False),
    Column("fecha", DateTime, nullable=False),
    Index("ix_historial_senal_fecha", "senal_id", "fecha"),
)

ejemplos = Table(
    "ejemplos", metadata,
    Column("senal_id", String(64), primary_key=True),
    Column("nombre", String(64), primary_key=True),
    Column("entrada", LargeBinary, nullable=False),
    Column("esperado", LargeBinary, nullable=False),
    Column("subido_por", String(100), nullable=False, default=""),
    Column("fecha", DateTime, nullable=False),
)

tablas_subidas = Table(
    "tablas_subidas", metadata,
    Column("id", String(32), primary_key=True),
    Column("contenido", LargeBinary, nullable=False),
    Column("creada", DateTime, nullable=False, index=True),
)

semanas = Table(
    "semanas", metadata,
    Column("senal_id", String(64), primary_key=True),
    Column("tabla_id", String(32), nullable=False),
    Column("contenido", LargeBinary, nullable=False),
    Column("nombre", String(200), nullable=False),
    Column("subida_por", String(100), nullable=False),
    Column("subida", DateTime, nullable=False),
    Column("resumen", JSON),  # grupos y fechas de la última vez que alguien la abrió, para el Inicio
    Column("confirmada_por", String(100)),
    Column("confirmada", DateTime),
    Column("version", Integer, nullable=False, default=1),
    # La versión anterior de esta misma semana, para mostrar qué cambió.
    Column("anterior_tabla_id", String(32)),
    Column("anterior_contenido", LargeBinary),
    Column("anterior_nombre", String(200)),
    Column("foto", JSON),  # las filas en corto (semana.COLUMNAS_FOTO), para ver todas las señales juntas
)

catalogo = Table(
    "catalogo", metadata,
    Column("orden", Integer, primary_key=True),
    Column("nombre", String(100), nullable=False),
    Column("regla", Text, nullable=False, default=""),  # tal como la escribió el admin
    Column("significado", Text, nullable=False, default=""),
    Column("tipo", String(20), nullable=False),  # texto | entero | anio | valores | fecha | hora
    Column("maximo", Integer),  # largo máximo (texto) o valor máximo (entero)
    Column("valores", JSON),  # para tipo "valores"
    Column("obligatoria", String(10), nullable=False, default="no"),  # no | si | ing | port
)

pautas = Table(
    "pautas", metadata,
    Column("senal_id", String(64), primary_key=True),
    Column("hash", String(16), primary_key=True),
    Column("crudo", JSON, nullable=False),  # la fila cruda sin horario, para mostrarla
    Column("salida", JSON, nullable=False),  # columnas de contenido del EPG
    Column("estado", String(10), nullable=False),  # revisada | editada
    Column("usuario", String(100), nullable=False),
    Column("actualizado", DateTime, nullable=False),
    Column("texto", Text, nullable=False, default=""),  # crudo + salida sin tildes ni mayúsculas, para buscar
)

ajustes = Table(
    "ajustes", metadata,
    Column("clave", String(64), primary_key=True),
    Column("valor", Text, nullable=False),
)

registro_acciones = Table(
    "registro_acciones", metadata,
    Column("id", Integer, primary_key=True),
    Column("usuario", String(100), nullable=False),
    Column("fecha", DateTime, nullable=False, index=True),
    Column("descripcion", Text, nullable=False),
)

_motores: dict[str, Engine] = {}


def url() -> str:
    """DATABASE_URL de Railway (postgres://…) adaptada al driver psycopg; si no hay, SQLite local."""
    propia = os.environ.get("DATABASE_URL")
    if not propia:
        # Otro nombre que el app.db viejo, para poder migrarlo sin pisarlo.
        return f"sqlite:///{data_dir() / 'autortv.db'}"
    for prefijo in ("postgres://", "postgresql://"):
        if propia.startswith(prefijo):
            return "postgresql+psycopg://" + propia[len(prefijo):]
    return propia


def motor() -> Engine:
    # Un motor por URL: los tests cambian DATA_DIR entre casos y cada uno tiene su base.
    direccion = url()
    if direccion not in _motores:
        if direccion.startswith("sqlite"):
            m = create_engine(direccion)
            event.listen(m, "connect", lambda con, _: con.execute("PRAGMA foreign_keys = ON"))
        else:
            # pre_ping: Railway corta conexiones inactivas y sin esto el primer pedido fallaría.
            m = create_engine(direccion, pool_size=5, max_overflow=5, pool_pre_ping=True)
        _motores[direccion] = m
        inicializar(m)
    return _motores[direccion]


def inicializar(m: Engine) -> None:
    """Crea las tablas y migra los datos del formato viejo (volumen) si la base está vacía."""
    from app import migrar, pautas

    with m.begin() as con:
        if m.dialect.name == "postgresql":
            # Si arrancan dos réplicas juntas, una espera a la otra en vez de crear/migrar dos veces.
            con.execute(text("SELECT pg_advisory_xact_lock(424242)"))
        metadata.create_all(con)
        _agregar_columnas(con)
        migrar.desde_volumen(con)
        pautas.migrar_hashes(con)


def _agregar_columnas(con: Connection) -> None:
    """create_all no toca tablas que ya existen: las columnas nuevas se agregan acá."""
    nuevas = {
        "uso_agente": {"costo_usd": "FLOAT"},
        "semanas": {"version": "INTEGER NOT NULL DEFAULT 1", "anterior_tabla_id": "VARCHAR(32)",
                    "anterior_contenido": "BYTEA" if con.dialect.name == "postgresql" else "BLOB",
                    "anterior_nombre": "VARCHAR(200)", "foto": "JSON"},
    }
    for tabla, columnas in nuevas.items():
        existentes = {c["name"] for c in inspect(con).get_columns(tabla)}
        for nombre, tipo in columnas.items():
            if nombre not in existentes:
                con.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}"))


@contextmanager
def transaccion() -> Iterator[Connection]:
    with motor().begin() as con:
        yield con
