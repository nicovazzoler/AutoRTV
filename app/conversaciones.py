"""Los chats de cada persona con el agente y lo que el agente decidió recordar de ella."""
import datetime as dt

from sqlalchemy import delete, desc, insert, select, update

from app import db

MAX_TITULO = 80
MAX_NOTAS = 30
# Lo que se manda al agente de un chat largo: los últimos mensajes; el resto ya quedó resumido en las notas.
MAX_MENSAJES_AL_AGENTE = 30


def _ahora() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def listar(usuario: str) -> list[dict]:
    with db.transaccion() as con:
        filas = con.execute(select(db.conversaciones).where(db.conversaciones.c.usuario == usuario)
                            .order_by(desc(db.conversaciones.c.actualizada)).limit(50)).all()
    return [{"id": f.id, "titulo": f.titulo, "actualizada": f.actualizada.isoformat()} for f in filas]


def _de(con, usuario: str, conversacion_id: int):
    return con.execute(select(db.conversaciones).where(db.conversaciones.c.id == conversacion_id,
                                                       db.conversaciones.c.usuario == usuario)).first()


def mensajes(usuario: str, conversacion_id: int) -> list[dict] | None:
    """Los mensajes del chat, o None si no existe o es de otra persona."""
    with db.transaccion() as con:
        if _de(con, usuario, conversacion_id) is None:
            return None
        filas = con.execute(select(db.mensajes).where(db.mensajes.c.conversacion_id == conversacion_id)
                            .order_by(db.mensajes.c.id)).all()
    return [{"rol": f.rol, "texto": f.texto, "senal_id": f.senal_id, "fecha": f.fecha.isoformat()} for f in filas]


def agregar(usuario: str, conversacion_id: int | None, rol: str, texto: str, senal_id: str | None) -> int | None:
    """Suma un mensaje; sin chat, abre uno nuevo con el mensaje como título. Devuelve el id, o None si no es suyo."""
    ahora = _ahora()
    with db.transaccion() as con:
        if conversacion_id is None:
            titulo = " ".join(texto.split())[:MAX_TITULO] or "Chat"
            conversacion_id = con.execute(insert(db.conversaciones).values(
                usuario=usuario, titulo=titulo, creada=ahora, actualizada=ahora)).inserted_primary_key[0]
        elif _de(con, usuario, conversacion_id) is None:
            return None
        con.execute(insert(db.mensajes).values(conversacion_id=conversacion_id, rol=rol, texto=texto,
                                               senal_id=senal_id, fecha=ahora))
        con.execute(update(db.conversaciones).where(db.conversaciones.c.id == conversacion_id).values(actualizada=ahora))
    return conversacion_id


def borrar(usuario: str, conversacion_id: int) -> None:
    with db.transaccion() as con:
        if _de(con, usuario, conversacion_id) is None:
            return
        con.execute(delete(db.mensajes).where(db.mensajes.c.conversacion_id == conversacion_id))
        con.execute(delete(db.conversaciones).where(db.conversaciones.c.id == conversacion_id))


def notas(usuario: str) -> list[dict]:
    with db.transaccion() as con:
        filas = con.execute(select(db.notas_agente).where(db.notas_agente.c.usuario == usuario)
                            .order_by(db.notas_agente.c.id)).all()
    return [{"id": f.id, "texto": f.texto, "fecha": f.fecha.isoformat()} for f in filas]


def anotar(usuario: str, texto: str) -> None:
    """Guarda algo para recordar de la persona; si ya hay muchas notas, se va la más vieja."""
    texto = " ".join(texto.split())[:300]
    if not texto:
        return
    with db.transaccion() as con:
        ids = [f.id for f in con.execute(select(db.notas_agente.c.id).where(db.notas_agente.c.usuario == usuario)
                                         .order_by(db.notas_agente.c.id)).all()]
        if len(ids) >= MAX_NOTAS:
            con.execute(delete(db.notas_agente).where(db.notas_agente.c.id.in_(ids[:len(ids) - MAX_NOTAS + 1])))
        con.execute(insert(db.notas_agente).values(usuario=usuario, texto=texto, fecha=_ahora()))


def olvidar_nota(usuario: str, nota_id: int) -> None:
    with db.transaccion() as con:
        con.execute(delete(db.notas_agente).where(db.notas_agente.c.id == nota_id, db.notas_agente.c.usuario == usuario))


# --- Avisos al admin ---

def avisar(usuario: str, senal_id: str, tipo: str, detalle: str) -> None:
    from app.historial import ORIGEN

    if ORIGEN.get() == "agente" and tipo != "agente":
        detalle = "Con el agente: " + detalle
    with db.transaccion() as con:
        con.execute(insert(db.avisos).values(usuario=usuario, senal_id=senal_id, tipo=tipo, detalle=detalle[:2000],
                                             fecha=_ahora(), visto=False))


def avisos(solo_sin_ver: bool = False) -> list[dict]:
    consulta = select(db.avisos).order_by(desc(db.avisos.c.id)).limit(200)
    if solo_sin_ver:
        consulta = consulta.where(db.avisos.c.visto.is_(False))
    with db.transaccion() as con:
        filas = con.execute(consulta).all()
    return [{"id": f.id, "usuario": f.usuario, "senal_id": f.senal_id, "tipo": f.tipo, "detalle": f.detalle,
             "fecha": f.fecha.isoformat(), "visto": bool(f.visto)} for f in filas]


def marcar_visto(aviso_id: int) -> None:
    with db.transaccion() as con:
        con.execute(update(db.avisos).where(db.avisos.c.id == aviso_id).values(visto=True))
