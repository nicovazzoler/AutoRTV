"""Cuánto se puede confiar en los criterios de una señal, y qué reglas conviene crear o revisar según lo que se corrigió."""
import datetime as dt
from collections import Counter

from sqlalchemy import delete, insert, select, update

from app import db, historial
from app.engine import model as m
from app.pautas import normalizar

# Semanas confirmadas sin correcciones para que un criterio deje de pedir revisión.
SEMANAS_CONFIABLE = 2
# Una misma corrección hecha estas veces ya merece una regla.
VECES_PARA_REGLA = 3
# Una regla corregida en estas semanas distintas conviene revisarla.
SEMANAS_PARA_REVISAR = 2


def _destinos(t: m.Criterios) -> set[str]:
    return {c for c in (t.programa, t.capitulo, t.temporada, t.titulo_temporada, t.numero, t.anio, t.tt) if c}


def columnas_de_tarjeta(t) -> set[str]:
    """Las columnas que escribe una tarjeta, para saber a quién culpar de una corrección."""
    if isinstance(t, m.Criterios):
        return _destinos(t)
    datos = t.model_dump()
    columnas = set()
    for clave in ("destino", "columna"):
        if isinstance(datos.get(clave), str):
            columnas.add(datos[clave])
    for clave in ("destinos", "columnas"):
        if isinstance(datos.get(clave), list):
            columnas |= set(datos[clave])
    return columnas


def leer(senal_id: str) -> dict[str, int]:
    with db.transaccion() as con:
        filas = con.execute(select(db.criterios_confianza.c.tarjeta_id, db.criterios_confianza.c.semanas)
                            .where(db.criterios_confianza.c.senal_id == senal_id)).all()
    return {t: n for t, n in filas}


def sin_confianza(receta: m.Senal) -> bool:
    """Si la señal lee títulos con criterios que todavía no se confirmaron las semanas que hacen falta."""
    confianza = leer(receta.id)
    return any(isinstance(t, m.Criterios) and t.activa and confianza.get(t.id, 0) < SEMANAS_CONFIABLE
               for t in receta.tarjetas)


def al_confirmar(receta: m.Senal, carga: str) -> None:
    """Cada criterio suma una semana si nadie corrigió sus columnas en esta carga; si se corrigieron, vuelve a 0."""
    corregidas = {d["columna"] for d in historial.detalle(receta.id, carga) if d["tipo"] == "corregida" and d["columna"]}
    actual = leer(receta.id)
    ahora = dt.datetime.now().replace(microsecond=0)
    with db.transaccion() as con:
        for t in receta.tarjetas:
            if not isinstance(t, m.Criterios):
                continue
            tocada = bool(_destinos(t) & corregidas)
            valores = {"semanas": 0 if tocada else actual.get(t.id, 0) + 1, **({"ultima_correccion": ahora} if tocada else {})}
            c = db.criterios_confianza.c
            if t.id in actual:
                con.execute(update(db.criterios_confianza).where(c.senal_id == receta.id, c.tarjeta_id == t.id).values(**valores))
            else:
                con.execute(insert(db.criterios_confianza).values(senal_id=receta.id, tarjeta_id=t.id, **valores))


def _descartadas(senal_id: str) -> set[str]:
    with db.transaccion() as con:
        return {f.clave for f in con.execute(select(db.propuestas_descartadas.c.clave)
                                             .where(db.propuestas_descartadas.c.senal_id == senal_id)).all()}


def descartar(senal_id: str, clave: str) -> None:
    with db.transaccion() as con:
        con.execute(delete(db.propuestas_descartadas).where(db.propuestas_descartadas.c.senal_id == senal_id,
                                                            db.propuestas_descartadas.c.clave == clave))
        con.execute(insert(db.propuestas_descartadas).values(senal_id=senal_id, clave=clave[:200]))


def propuestas(receta: m.Senal) -> list[dict]:
    """Reglas para crear (la misma corrección repetida) y para revisar (una regla corregida en varias semanas)."""
    correcciones = historial.correcciones(receta.id)
    descartadas = _descartadas(receta.id)
    lista = []
    reales = [c for c in correcciones if c["antes"] is not None and normalizar(c["antes"]) != normalizar(c["despues"])]
    repetidas = Counter((c["columna"], normalizar(c["antes"]), str(c["despues"])) for c in reales)
    ejemplo = {(c["columna"], normalizar(c["antes"]), str(c["despues"])): c for c in correcciones}
    for (columna, _, despues), veces in repetidas.most_common():
        if veces < VECES_PARA_REGLA:
            break
        antes = ejemplo[(columna, _, despues)]["antes"]
        clave = f"crear|{columna}|{normalizar(antes)}|{despues}"
        if clave not in descartadas:
            lista.append({"tipo": "crear", "clave": clave, "columna": columna, "antes": antes, "despues": despues, "veces": veces,
                          "pedido": f"En {receta.nombre} se corrigió {veces} veces «{antes}» → «{despues}» en la columna {columna}. "
                                    "Proponé una regla para que salga así sola, sin romper lo que ya está bien."})
    for t in receta.tarjetas:
        tocadas = [c for c in correcciones if c["columna"] in columnas_de_tarjeta(t)]
        semanas = {c["desde"] for c in tocadas if c["desde"]}
        clave = f"revisar|{t.id}|{len(tocadas)}"
        if len(semanas) >= SEMANAS_PARA_REVISAR and not any(d.startswith(f"revisar|{t.id}|") for d in descartadas):
            lista.append({"tipo": "revisar", "clave": clave, "tarjeta": t.id, "veces": len(tocadas), "semanas": len(semanas),
                          "pedido": f"La regla {t.id} ({t.tipo}) de {receta.nombre} se corrigió {len(tocadas)} veces en "
                                    f"{len(semanas)} semanas. Mirá las correcciones y proponé cambiarla o sacarla."})
    return lista
