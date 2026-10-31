import datetime as dt
import difflib
import io
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Cookie, Depends, Header, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import acciones, almacen, auth, catalogo, corridas, export, inputs, pautas, semana, semanas, tablas
from app.agent import asistente as asistente_ia
from app.agent import banco, cliente, controles, uso
from app.engine import model as m
from app.engine import titulos
from app.engine.comparar import diferencias, porcentaje_igual, sugerir_correcciones
from app.engine.pipeline import DE_ESTRUCTURA, aplicar, armar_salida, correr
from app.engine.tarjetas.estructura import a_fecha, a_hora
from app.inputs import epg as epg_crudo
from app.validate import grilla

publico = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(auth.usuario_actual)])

MAX_ARCHIVO = 20 * 1024 * 1024


# --- Sesión ---

class Login(BaseModel):
    usuario: str
    clave: str


@publico.post("/login")
def login(datos: Login, response: Response):
    token = auth.iniciar_sesion(datos.usuario, datos.clave)
    if not token:
        raise HTTPException(401, "Usuario o clave incorrectos")
    response.set_cookie(auth.COOKIE, token, max_age=auth.DURACION_SESION, httponly=True, samesite="lax",
                        secure=_es_produccion())
    return {"ok": True}


def _es_produccion() -> bool:
    """Si corre detrás de HTTPS: ahí la cookie de sesión se marca para viajar solo cifrada."""
    if os.environ.get("COOKIE_SEGURA") in ("0", "1"):
        return os.environ["COOKIE_SEGURA"] == "1"
    return any(os.environ.get(v) for v in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT_ID"))


@publico.post("/logout")
def logout(response: Response, autortv_sesion: str | None = Cookie(default=None)):
    if autortv_sesion:
        auth.cerrar_sesion(autortv_sesion)
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@api.get("/yo")
def yo(u: auth.Usuario = Depends(auth.usuario_actual)):
    return asdict(u)


class CambioClave(BaseModel):
    actual: str
    nueva: str


@api.post("/yo/clave")
def cambiar_mi_clave(datos: CambioClave, u: auth.Usuario = Depends(auth.usuario_actual),
                     autortv_sesion: str | None = Cookie(default=None)):
    try:
        auth.cambiar_clave(u.id, datos.actual, datos.nueva, sesion_actual=autortv_sesion)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


# --- Usuarios (admin) ---

class NuevoUsuario(BaseModel):
    usuario: str
    clave: str
    admin: bool = False


@api.get("/usuarios", dependencies=[Depends(auth.solo_admin)])
def usuarios():
    return [asdict(u) for u in auth.listar_usuarios()]


@api.post("/usuarios", dependencies=[Depends(auth.solo_admin)])
def crear_usuario(datos: NuevoUsuario):
    try:
        auth.crear_usuario(datos.usuario, datos.clave, datos.admin)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


class ClaveNueva(BaseModel):
    nueva: str


@api.post("/usuarios/{usuario_id}/clave", dependencies=[Depends(auth.solo_admin)])
def resetear_clave(usuario_id: int, datos: ClaveNueva):
    try:
        auth.resetear_clave(usuario_id, datos.nueva)
    except LookupError:
        raise HTTPException(404, "No existe ese usuario")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@api.delete("/usuarios/{usuario_id}")
def borrar_usuario(usuario_id: int, yo: auth.Usuario = Depends(auth.solo_admin)):
    if usuario_id == yo.id:
        raise HTTPException(422, "No podés borrar tu propio usuario")
    auth.borrar_usuario(usuario_id)
    return {"ok": True}


# --- Tarjetas y señales ---

@api.get("/tipos-tarjeta")
def tipos_tarjeta():
    """JSON Schema de las tarjetas: la web arma los formularios a partir de esto."""
    return {"schema": TypeAdapter(m.Tarjeta).json_schema(), "sin_condicion": sorted(DE_ESTRUCTURA)}


@api.get("/senales")
def senales():
    return almacen.listar()


@api.get("/senales/{senal_id}")
def senal(senal_id: str, response: Response):
    try:
        receta = almacen.leer(senal_id)
    except (almacen.NoExiste, ValueError):
        raise HTTPException(404, "No existe la señal")
    # La versión va en el ETag; al guardar vuelve en If-Match para no pisar a otro.
    response.headers["ETag"] = almacen.version(senal_id)
    return receta.model_dump(exclude_none=True)


@api.put("/senales/{senal_id}")
def guardar_senal(senal_id: str, receta: m.Senal, response: Response,
                  u: auth.Usuario = Depends(auth.usuario_actual), if_match: str | None = Header(default=None)):
    if receta.id != senal_id:
        raise HTTPException(422, "El id de la receta no coincide con la ruta")
    try:
        response.headers["ETag"] = almacen.guardar(receta, u.usuario, esperada=if_match)
    except almacen.Conflicto as c:
        raise HTTPException(409, f"{c.usuario} guardó cambios el {c.fecha:%d/%m a las %H:%M}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@api.get("/senales/{senal_id}/historial")
def historial_senal(senal_id: str):
    """Últimas versiones de la receta, la más nueva primero, con qué cambió cada una."""
    try:
        versiones = almacen.historial(senal_id, limite=51)
    except ValueError as e:
        raise HTTPException(422, str(e))
    lista = []
    for anterior, actual in zip([None, *versiones], versiones):
        cambios = (asistente_ia.cambios(m.Senal.model_validate(anterior["receta"]), m.Senal.model_validate(actual["receta"]))
                   if anterior else [])
        lista.append({"id": actual["id"], "usuario": actual["usuario"],
                      "fecha": actual["fecha"].isoformat(timespec="minutes"), "cambios": cambios})
    # La primera de las 51 solo sirve para calcular los cambios de la segunda.
    return lista[::-1][:50]


@api.post("/senales/{senal_id}/historial/{version_id}/restaurar")
def restaurar_version(senal_id: str, version_id: int, response: Response,
                      u: auth.Usuario = Depends(auth.usuario_actual), if_match: str | None = Header(default=None)):
    """Vuelve la receta a esa versión. Queda como un guardado más, así también se puede deshacer."""
    try:
        receta = almacen.leer_version(senal_id, version_id)
        response.headers["ETag"] = almacen.guardar(receta, u.usuario, esperada=if_match)
    except almacen.NoExiste:
        raise HTTPException(404, "No existe esa versión")
    except almacen.Conflicto as c:
        raise HTTPException(409, f"{c.usuario} guardó cambios el {c.fecha:%d/%m a las %H:%M}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return receta.model_dump(exclude_none=True)


@api.post("/senales/validar", dependencies=[Depends(auth.solo_admin)])
def validar_receta(receta: dict):
    """Valida una receta importada; devuelve los errores en castellano en vez de un 422 crudo."""
    try:
        return {"ok": True, "receta": m.Senal.model_validate(receta).model_dump(exclude_none=True)}
    except ValidationError as e:
        errores = [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:10]]
        return {"ok": False, "errores": errores}


@api.post("/senales/{senal_id}/titulos/aprender")
async def aprender_titulos(senal_id: str, columna: str = Form(""), usar_ejemplos: bool = Form(False),
                           conocidos: str = Form("[]"), archivos: list[UploadFile] = File(default=[])):
    """Cuenta los títulos de EPG terminados. No guarda: la web los agrega a la receta."""
    tablas = []
    try:
        if usar_ejemplos:
            for nombre in almacen.listar_ejemplos(senal_id):
                _, esperado = almacen.leer_ejemplo(senal_id, nombre)
                tablas.append(pd.read_excel(io.BytesIO(esperado), dtype=object))
        for archivo in archivos:
            tablas.append(pd.read_excel(io.BytesIO(await _leer_archivo(archivo)), dtype=object))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not tablas:
        raise HTTPException(422, "No hay de dónde aprender: subí archivos o agregá ejemplos a la señal")
    conteo, usada = titulos.aprender(tablas, columna.strip() or None)
    if usada is None:
        raise HTTPException(422, "No encontré la columna de programa: escribila a mano")
    ya = set(json.loads(conocidos))
    return {
        "columna_usada": usada,
        "titulos": [{"titulo": t, "apariciones": n, "nuevo": t not in ya} for t, n in conteo.most_common()],
    }


# --- Tablas, vista previa y export ---

async def _leer_archivo(archivo: UploadFile) -> bytes:
    contenido = await archivo.read()
    if len(contenido) > MAX_ARCHIVO:
        raise HTTPException(413, "El archivo pasa los 20 MB")
    return contenido


@api.post("/tablas")
async def subir_tabla(archivo: UploadFile = File(...)):
    """Guarda la grilla y dice qué formato parece, para que la señal sepa cómo leerla."""
    contenido = await _leer_archivo(archivo)
    return {"tabla_id": tablas.subir(contenido), "nombre": archivo.filename,
            "entrada": inputs.detectar(contenido).model_dump()}


class TextoPegado(BaseModel):
    texto: str
    fecha_inicio: str | None = None


@api.post("/tablas/texto")
def subir_texto(datos: TextoPegado):
    """Texto pegado de un mail o una web: se guarda como si fuera un .txt."""
    if not datos.texto.strip():
        raise HTTPException(422, "El texto está vacío")
    contenido = datos.texto.encode("utf-8")
    if len(contenido) > MAX_ARCHIVO:
        raise HTTPException(413, "El texto pasa los 20 MB")
    entrada = m.EntradaTexto(tipo="texto", fecha_inicio=datos.fecha_inicio)
    return {"tabla_id": tablas.subir(contenido), "nombre": "texto pegado", "entrada": entrada.model_dump()}


class Pedido(BaseModel):
    tabla_id: str
    senal: m.Senal
    filas: int = 200
    solo_nuevas: bool = False


@dataclass
class Corrida:
    salida: pd.DataFrame
    informes: list
    catalogo: list
    estados: list[str]
    hashes: list[str]
    crudas: list[dict]
    crudo: pd.DataFrame
    programas: list[str]
    base: dict[str, dict]


def _correr(p: Pedido) -> Corrida:
    """Reglas → base de pautas → columnas de salida → orden del catálogo."""
    try:
        tabla = tablas.tabla(p.tabla_id, p.senal.entrada)
    except KeyError:
        raise HTTPException(410, "El archivo ya no está en memoria: volvé a subirlo")
    except Exception as e:  # Excel roto o config de entrada que no corresponde
        raise HTTPException(422, f"No se pudo leer la grilla: {e}")
    base = pautas.base(p.senal.id)
    columnas_base = sorted({c for pauta in base.values() for c in pauta["salida"]})
    programas = semana.programas_de_la_base(base, semana.columna_programa(columnas_base, p.senal.validaciones))
    r = aplicar(tabla, p.senal.tarjetas, [*p.senal.titulos_conocidos, *programas])
    df, estados, hashes = pautas.aplicar(tabla, r.tabla, base)
    salida = semana.completar_titulos(armar_salida(df, p.senal.salida), crear=not p.senal.salida.columnas)
    cat = catalogo.leer()
    if cat and not p.senal.salida.columnas:
        salida = salida[catalogo.ordenar(list(salida.columns), cat)]
    return Corrida(salida, r.informes, cat, estados, hashes, pautas.crudas(tabla), tabla, programas, base)


def _validar(c: Corrida, receta: m.Senal) -> list:
    return grilla.validar(c.salida, receta.validaciones, receta.titulos_conocidos, c.catalogo, receta.idiomas)


def _clasificar(c: Corrida, receta: m.Senal, avisos: list) -> list[dict]:
    columnas = list(c.salida.columns)
    columna = semana.columna_programa(columnas, receta.validaciones)
    capitulo = [x for x in semana.campos_clave(columnas, columna) if x != columna]
    repetidas = semana.sinopsis_repetidas(c.salida, [p["salida"] for p in c.base.values()], columna, capitulo)
    return semana.clasificar(c.salida, c.estados, avisos, c.informes, c.programas, columna, repetidas)


def _resumen_pautas(estados: list[str]) -> dict:
    return {e: estados.count(e) for e in ("conocida", "editada", "nueva")}


@api.post("/preview")
def preview(p: Pedido):
    c = _correr(p)
    salida = c.salida
    avisos = _validar(c, p.senal)
    grupos = _clasificar(c, p.senal, avisos)
    indices = [i for i, e in enumerate(c.estados) if e == "nueva"] if p.solo_nuevas else list(range(len(salida)))
    indices = indices[:p.filas]
    return {
        "columnas": [str(x) for x in salida.columns],
        "filas": export.a_filas(salida.iloc[indices]),
        "indices": indices,
        "estados": [c.estados[i] for i in indices],
        "hashes": [c.hashes[i] for i in indices],
        "grupos": [grupos[i] for i in indices],
        "resumen_pautas": _resumen_pautas(c.estados),
        "contenido": pautas.columnas_de_contenido(salida, p.senal.validaciones),
        "total_filas": len(salida),
        "tarjetas": [asdict(i) for i in c.informes],
        "validaciones": [asdict(a) for a in avisos],
        "resumen_validaciones": grilla.resumen(avisos),
        "columnas_validadas": grilla.detectar_columnas(list(salida.columns), p.senal.validaciones),
    }


@api.post("/semana")
def ver_semana(p: Pedido):
    """La semana subida armada para revisar: cómo se leyó, cuántas filas hay en cada grupo y las pautas a mirar."""
    armado = _armar_semana(_correr(p), p.senal)
    armado.pop("_foto")
    return armado


def _armar_semana(c: Corrida, receta: m.Senal) -> dict:
    avisos = _validar(c, receta)
    grupos = _clasificar(c, receta, avisos)
    contenido = pautas.columnas_de_contenido(c.salida, receta.validaciones)

    def detalle(g: dict) -> dict:
        i = g["filas"][0]
        return {**g, "veces": len(g["filas"]), "crudo": c.crudas[i],
                "salida": {col: pautas.valor_json(c.salida.iloc[i][col]) for col in contenido}}

    revisar = [detalle(g) for g in semana.agrupar(grupos, c.hashes, "revisar")]
    nuevas = [detalle(g) for g in semana.agrupar(grupos, c.hashes, "nueva_lista")]
    cuenta = {k: sum(g["grupo"] == k for g in grupos) for k in ("base", "nueva_lista", "revisar")}
    return {
        "_foto": semana.foto(c.salida, grupos, receta.validaciones),
        "lectura": {"filas": len(c.crudo), "columnas": [str(x) for x in c.crudo.columns]},
        "resumen": {"filas": len(c.salida), **cuenta, "pautas_revisar": len(revisar)},
        "contenido": contenido,
        "programa": semana.columna_programa(contenido, receta.validaciones),
        "campos_clave": semana.campos_clave(contenido, semana.columna_programa(contenido, receta.validaciones)),
        "revisar": revisar,
        "nuevas": nuevas,
        "horarios": [asdict(a) for a in avisos if a.regla not in ("catalogo", "titulo_nuevo")],
    }


class PedidoExport(Pedido):
    formato: str = "xlsx"


@api.post("/export")
def exportar(p: PedidoExport):
    c = _correr(p)
    return _archivo(c.salida, p.senal.id, p.formato, c.estados.count("nueva"))


def _archivo(salida: pd.DataFrame, senal_id: str, formato: str, nuevas: int) -> Response:
    fecha = dt.date.today().isoformat()
    cabeceras = {"X-Pautas-Nuevas": str(nuevas)}
    if formato == "csv":
        return Response(export.a_csv(salida), media_type="text/csv", headers={
            **cabeceras, "Content-Disposition": f'attachment; filename="{senal_id}_{fecha}.csv"'})
    return Response(export.a_xlsx(salida),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={**cabeceras, "Content-Disposition": f'attachment; filename="{senal_id}_{fecha}.xlsx"'})


# --- Ejemplos antes/después ---

@api.get("/senales/{senal_id}/ejemplos")
def ejemplos(senal_id: str):
    try:
        return almacen.listar_ejemplos(senal_id)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.post("/senales/{senal_id}/ejemplos")
async def subir_ejemplo(senal_id: str, nombre: str = Form(...), entrada: UploadFile = File(...),
                        esperado: UploadFile = File(...), u: auth.Usuario = Depends(auth.usuario_actual)):
    crudo, terminado = await _leer_archivo(entrada), await _leer_archivo(esperado)
    try:
        almacen.guardar_ejemplo(senal_id, nombre, crudo, terminado, u.usuario)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "pautas": _cargar_pautas(senal_id, crudo, terminado, u.usuario)}


def _cargar_pautas(senal_id: str, crudo: bytes, terminado: bytes, usuario: str) -> dict | None:
    """Suma el ejemplo a la base de pautas. Si no se puede leer, el ejemplo queda igual y se informa."""
    try:
        return pautas.cargar_ejemplo(almacen.leer(senal_id), crudo, terminado, usuario)
    except almacen.NoExiste:
        return None  # ejemplo de una señal todavía sin guardar
    except Exception as e:
        return {"error": f"No se pudo cargar la base de pautas: {e}"}


@api.delete("/senales/{senal_id}/ejemplos/{nombre}")
def borrar_ejemplo(senal_id: str, nombre: str):
    try:
        almacen.borrar_ejemplo(senal_id, nombre)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@api.post("/senales/crear")
async def crear_senal(nombre: str = Form(""), grilla_cruda: UploadFile = File(...), ejemplo: UploadFile = File(...),
                      agregar_a: str | None = Form(None), confirmar: bool = Form(False),
                      u: auth.Usuario = Depends(auth.usuario_actual)):
    """Crea una señal a partir de la grilla como viene y el EPG terminado (macro hecha).

    Si ya hay señales con un nombre igual o parecido responde 409 con la lista, para que la persona
    confirme (`confirmar`) o sume el par como ejemplo de una de ellas (`agregar_a`).
    """
    nombre = " ".join(nombre.split())
    if not agregar_a and not nombre:
        raise HTTPException(422, "Escribí el nombre de la señal")
    crudo, terminado = await _leer_archivo(grilla_cruda), await _leer_archivo(ejemplo)
    senal_id = agregar_a or _slug(nombre)
    sello = dt.datetime.now().strftime("ejemplo-%Y%m%d-%H%M%S")
    try:
        if agregar_a:
            receta = almacen.leer(senal_id)
        else:
            parecidas = senales_parecidas(nombre, almacen.listar())
            identica = any(s["id"] == senal_id for s in parecidas)
            if parecidas and (identica or not confirmar):
                mensaje = (f'Ya existe la señal "{nombre}"' if identica
                           else f'Hay señales con un nombre parecido a "{nombre}"')
                raise HTTPException(409, {"mensaje": mensaje, "parecidas": parecidas, "identica": identica})
            receta = m.Senal(id=senal_id, nombre=nombre, entrada=_con_epg(_detectar(crudo), crudo),
                             tarjetas=[], salida=m.Salida(columnas=[]))
            almacen.guardar(receta, u.usuario)
        existentes, base, n = set(almacen.listar_ejemplos(senal_id)), sello, 2
        while sello in existentes:  # dos ejemplos subidos en el mismo segundo
            sello, n = f"{base}-{n}", n + 1
        almacen.guardar_ejemplo(senal_id, sello, crudo, terminado, u.usuario)
    except almacen.NoExiste:
        raise HTTPException(404, "No existe la señal")
    except ValueError as e:
        raise HTTPException(422, str(e))
    tabla_id = tablas.subir(crudo)
    resultado = {"id": senal_id, "nombre": receta.nombre, "ejemplo": sello, "tabla_id": tabla_id,
                 "pautas": _cargar_pautas(senal_id, crudo, terminado, u.usuario), "semana_abierta": False,
                 "aviso": SIN_HORARIO if _sin_horario(crudo, receta) else None}
    if not agregar_a and _es_de_ahora(terminado, receta):
        semanas.abrir(senal_id, tabla_id, crudo, grilla_cruda.filename or "grilla", u.usuario, es_version=False)
        resultado["semana_abierta"] = True
    return resultado


SIN_HORARIO = ("No encontré la fecha y la hora en la grilla: así no se puede emparejar con el ejemplo ni armar "
               "la semana. Pasame el archivo para sumar cómo se lee.")


def _sin_horario(crudo: bytes, receta: m.Senal) -> bool:
    try:
        tabla = inputs.leer(crudo, receta.entrada)
    except Exception:
        return True
    nombradas = grilla.detectar_columnas(list(tabla.columns), receta.validaciones)
    cols = pautas.columnas_por_tipo(tabla) | {k: v for k, v in nombradas.items() if v}
    return not (cols.get("fecha") in tabla.columns and cols.get("hora") in tabla.columns)


def _es_de_ahora(terminado: bytes, receta: m.Senal) -> bool:
    """Si el EPG del ejemplo llega hasta hoy o después: es la semana en curso, no una vieja."""
    try:
        hasta = _fechas(pd.read_excel(io.BytesIO(terminado), dtype=object), receta)["hasta"]
    except Exception:
        return False
    return hasta is not None and dt.date.fromisoformat(hasta) >= dt.date.today()


def _comparable(nombre: str) -> str:
    return _slug(nombre).replace("-", "")


# Por debajo de este largo, que un nombre esté dentro de otro no dice nada ("tv", "hd").
MIN_PARA_CONTENIDO = 6


def _se_parecen(a: str, b: str, umbral: float) -> bool:
    if difflib.SequenceMatcher(None, a, b).ratio() >= umbral:
        return True
    corto, largo = sorted((a, b), key=len)
    if len(corto) < MIN_PARA_CONTENIDO:
        return False
    # "Concert Chanel" contra "Concert Channel EPG OCTUBRE 2026": el corto se parece al comienzo del largo.
    return corto in largo or difflib.SequenceMatcher(None, corto, largo[:len(corto)]).ratio() >= 0.85


def senales_parecidas(nombre: str, senales: list[dict], umbral: float = 0.8) -> list[dict]:
    """Señales con el mismo nombre o uno parecido, sin contar mayúsculas, tildes ni signos."""
    buscado = _comparable(nombre)
    return [s for s in senales
            if s["id"] == _slug(nombre) or (buscado and _se_parecen(buscado, _comparable(s["nombre"]), umbral))]


@api.get("/senales-parecidas")
def ver_parecidas(nombre: str = ""):
    return senales_parecidas(" ".join(nombre.split()), almacen.listar()) if nombre.strip() else []


@api.delete("/senales/{senal_id}", dependencies=[Depends(auth.solo_admin)])
def borrar_senal(senal_id: str):
    try:
        almacen.borrar(senal_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except almacen.NoExiste:
        raise HTTPException(404, "No existe la señal")
    return {"ok": True}


def _slug(nombre: str) -> str:
    texto = unicodedata.normalize("NFD", nombre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:64] or "senal"


# --- Base de pautas ---

def _filtros(filtro: list[str]) -> dict[str, str]:
    """`columna=valor` de la URL, repetible."""
    pares = [f.split("=", 1) for f in filtro]
    if any(len(par) != 2 or not par[0] for par in pares):
        raise HTTPException(422, "Cada filtro va como columna=valor")
    return {col: valor for col, valor in pares}


@api.get("/senales/{senal_id}/pautas")
def listar_pautas(senal_id: str, estado: str | None = None, q: str = "", desde: int = 0,
                  filtro: list[str] = Query(default=[])):
    return pautas.listar(senal_id, estado or None, q, max(desde, 0), _filtros(filtro))


@api.get("/senales/{senal_id}/pautas/columnas")
def columnas_pautas(senal_id: str):
    """Las columnas que guarda la base, en el orden del catálogo, y cuál es la del programa."""
    receta = _receta(senal_id)
    vistas = list(dict.fromkeys(c for pauta in pautas.base(senal_id).values() for c in pauta["salida"]))
    cat = catalogo.leer()
    columnas = catalogo.ordenar(vistas, cat) if cat else vistas
    return {"columnas": columnas, "programa": semana.columna_programa(columnas, receta.validaciones)}


@api.get("/senales/{senal_id}/pautas/valores")
def valores_pautas(senal_id: str, columna: str):
    return pautas.valores(senal_id, columna)


class Seleccion(BaseModel):
    """Pautas elegidas a mano (`hashes`) o todas las que cumplen un filtro de la Base."""
    hashes: list[str] | None = None
    estado: str | None = None
    q: str = ""
    filtro: dict[str, str] = {}

    def resolver(self, senal_id: str) -> list[str]:
        if self.hashes is not None:
            return self.hashes
        if not (self.estado or self.q.strip() or self.filtro):
            raise HTTPException(422, "Elegí pautas o filtrá la base antes de cambiar todo junto")
        return pautas.hashes_filtrados(senal_id, self.estado or None, self.q, self.filtro)


class EdicionVarias(Seleccion):
    columna: str
    valor: str | None


@api.post("/senales/{senal_id}/pautas/editar-varias")
def editar_varias(senal_id: str, datos: EdicionVarias, u: auth.Usuario = Depends(auth.usuario_actual)):
    valor = _convertir(datos.valor, datos.columna, catalogo.leer())
    return {"editadas": pautas.editar_varias(senal_id, datos.resolver(senal_id), datos.columna, valor, u.usuario)}


@api.post("/senales/{senal_id}/pautas/olvidar-varias")
def olvidar_varias(senal_id: str, datos: Seleccion):
    return {"olvidadas": pautas.olvidar_varias(senal_id, datos.resolver(senal_id))}


class EdicionPauta(BaseModel):
    salida: dict


@api.put("/senales/{senal_id}/pautas/{h}")
def editar_pauta(senal_id: str, h: str, datos: EdicionPauta, u: auth.Usuario = Depends(auth.usuario_actual)):
    cat = catalogo.leer()
    salida = {c: _convertir(v, c, cat) if isinstance(v, str) else v for c, v in datos.salida.items()}
    if not pautas.editar(senal_id, h, salida, u.usuario):
        raise HTTPException(404, "No existe esa pauta")
    return {"ok": True}


@api.delete("/senales/{senal_id}/pautas/{h}")
def olvidar_pauta(senal_id: str, h: str):
    pautas.olvidar(senal_id, h)
    return {"ok": True}


class EdicionCelda(Pedido):
    fila: int  # índice en la salida completa
    columna: str
    valor: str | None


@api.post("/senales/{senal_id}/pautas/editar-celda")
def editar_celda(senal_id: str, p: EdicionCelda, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Edita una celda de la vista previa: la pauta de esa fila queda en la base como editada."""
    return {"ok": True, "hash": _editar_celda(senal_id, _correr(p), p.senal, p.fila, p.columna, p.valor, u.usuario)}


def _editar_celda(senal_id: str, c: Corrida, receta: m.Senal, fila: int, columna: str, valor: str | None,
                  usuario: str) -> str:
    contenido = pautas.columnas_de_contenido(c.salida, receta.validaciones)
    if columna not in contenido:
        raise HTTPException(422, "Esta columna sale de las reglas (horario o numeración) y no se edita en la base")
    if not 0 <= fila < len(c.salida):
        raise HTTPException(422, "Esa fila no existe")
    salida = {col: pautas.valor_json(c.salida.iloc[fila][col]) for col in contenido}
    salida[columna] = _convertir(valor, columna, c.catalogo)
    h = c.hashes[fila]
    pautas.guardar(senal_id, {h: {"crudo": c.crudas[fila], "salida": salida}}, "editada", usuario, pisar=True)
    return h


def _convertir(valor: str | None, columna: str, cat: list):
    """El texto escrito, como número si el catálogo dice que la columna es numérica."""
    valor = (valor or "").strip()
    if not valor:
        return None
    tipo = next((x.tipo for x in cat if catalogo.clave(x.nombre) == catalogo.clave(columna)), None)
    if tipo in ("entero", "anio") and re.fullmatch(r"-?\d+", valor):
        return int(valor)
    return valor


def _guardar_nuevas(senal_id: str, p: Pedido, usuario: str, solo: set[str] | None = None) -> int:
    """Pasa a la base, como revisadas, las pautas nuevas de la grilla tal como las arman hoy las reglas."""
    c = _correr(p)
    contenido = pautas.columnas_de_contenido(c.salida, p.senal.validaciones)
    nuevas = {}
    for i, estado in enumerate(c.estados):
        h = c.hashes[i]
        if estado == "nueva" and h not in nuevas and (solo is None or h in solo):
            nuevas[h] = {"crudo": c.crudas[i],
                         "salida": {col: pautas.valor_json(c.salida.iloc[i][col]) for col in contenido}}
    return pautas.guardar(senal_id, nuevas, "revisada", usuario)


@api.post("/senales/{senal_id}/pautas/revisar")
def revisar_pautas(senal_id: str, p: Pedido, u: auth.Usuario = Depends(auth.usuario_actual)):
    return {"revisadas": _guardar_nuevas(senal_id, p, u.usuario)}


@api.post("/senales/{senal_id}/semana/confirmar")
def confirmar_semana(senal_id: str, p: Pedido, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Las nuevas listas y las ya revisadas entran a la base: la semana que viene salen de ahí."""
    return {"guardadas": _guardar_nuevas(senal_id, p, u.usuario)}


class Aceptar(Pedido):
    hashes: list[str]


@api.post("/senales/{senal_id}/pautas/aceptar")
def aceptar_pautas(senal_id: str, p: Aceptar, u: auth.Usuario = Depends(auth.usuario_actual)):
    """"Está bien así" sobre pautas para revisar: entran a la base como están."""
    return {"aceptadas": _guardar_nuevas(senal_id, p, u.usuario, set(p.hashes))}


# --- Semana abierta de cada señal ---

def _receta(senal_id: str) -> m.Senal:
    try:
        return almacen.leer(senal_id)
    except (almacen.NoExiste, ValueError):
        raise HTTPException(404, "No existe la señal")


def _con_entrada(receta: m.Senal, detectada) -> m.Senal:
    """Si la grilla llegó en otro formato que la anterior, la señal pasa a leerla así."""
    entrada = receta.entrada
    if not inputs.mismo_formato(entrada, detectada):
        entrada = detectada
    elif entrada.tipo == "texto" and entrada.fecha_inicio != detectada.fecha_inicio:
        entrada = entrada.model_copy(update={"fecha_inicio": detectada.fecha_inicio})
    return receta if entrada is receta.entrada else receta.model_copy(update={"entrada": entrada})


def _con_epg(entrada, contenido: bytes):
    """Una grilla web nueva arranca con su EPG crudo propuesto. Si no se puede leer, queda sin él."""
    if entrada.tipo != "html" or entrada.epg:
        return entrada
    try:
        return entrada.model_copy(update={"epg": epg_crudo.proponer(inputs.leer(contenido, entrada))})
    except Exception:  # el error de lectura lo muestra quien la lea después
        return entrada


def _detectar(contenido: bytes):
    try:
        return inputs.detectar(contenido)
    except Exception as e:  # un Excel roto ya falla al buscar el encabezado
        raise HTTPException(422, f"No se pudo leer la grilla: {e}")


def _abrir(receta: m.Senal, contenido: bytes, detectada, nombre: str, usuario: str) -> dict:
    """Abre la semana con esta grilla. Si no se puede leer, la semana anterior queda como estaba."""
    nueva = _con_entrada(receta, detectada)
    if nueva.entrada.tipo == "html" and receta.entrada.tipo != "html":
        nueva = nueva.model_copy(update={"entrada": _con_epg(nueva.entrada, contenido)})
    try:
        inputs.leer(contenido, nueva.entrada)
    except Exception as e:
        raise HTTPException(422, f"No se pudo leer la grilla: {e}")
    tabla_id = tablas.subir(contenido)
    fechas = _fechas(_correr(Pedido(tabla_id=tabla_id, senal=nueva)).salida, nueva)
    version = semanas.es_version(fechas["desde"], fechas["hasta"], semanas.leer(receta.id))
    if nueva is not receta:
        almacen.guardar(nueva, usuario)
    semanas.abrir(receta.id, tabla_id, contenido, nombre, usuario, version)
    return _semana_abierta(receta.id, nueva)


def _fechas(salida: pd.DataFrame, receta: m.Senal) -> dict:
    col = (grilla.detectar_columnas(list(salida.columns), receta.validaciones).get("fecha")
           or pautas.columnas_por_tipo(salida).get("fecha"))
    if not col or col not in salida.columns:
        return {"desde": None, "hasta": None}
    fechas = pd.to_datetime(salida[col], errors="coerce", dayfirst=True).dropna()
    if fechas.empty:
        return {"desde": None, "hasta": None}
    return {"desde": fechas.min().date().isoformat(), "hasta": fechas.max().date().isoformat()}


def _semana_abierta(senal_id: str, receta: m.Senal) -> dict:
    """La semana abierta armada para revisar, con quién la subió. De paso deja el resumen al día para el Inicio."""
    meta = semanas.leer(senal_id)
    if meta is None:
        return {"semana": None}
    c = _correr(Pedido(tabla_id=meta["tabla_id"], senal=receta))
    armado = _armar_semana(c, receta)
    armado["resumen"] |= _fechas(c.salida, receta)
    armado["cambios"] = _cambios(senal_id, receta, c)
    if armado["cambios"] is not None:
        armado["resumen"]["cambios"] = len(armado["cambios"])
    semanas.guardar_resumen(senal_id, armado["resumen"], armado.pop("_foto"))
    return {"semana": {**meta, "resumen": armado["resumen"]}, **armado}


def _cambios(senal_id: str, receta: m.Senal, c: Corrida) -> list[dict] | None:
    """Qué cambió contra la versión anterior de la semana, o None si es la primera."""
    tabla_id = semanas.anterior(senal_id)
    cols = grilla.detectar_columnas(list(c.salida.columns), receta.validaciones)
    if not tabla_id or not cols.get("fecha") or not cols.get("hora"):
        return None
    try:
        antes = _correr(Pedido(tabla_id=tabla_id, senal=receta)).salida
    except Exception:  # la anterior pudo venir en otro formato y no leerse con la entrada de hoy
        return None
    if not {cols["fecha"], cols["hora"]} <= set(antes.columns) & set(c.salida.columns):
        return None
    columnas = [x for x in [cols.get("duracion")] if x] + pautas.columnas_de_contenido(c.salida, receta.validaciones)
    return semanas.comparar(antes, c.salida, cols["fecha"], cols["hora"], columnas)


def _pedido_abierta(senal_id: str) -> tuple[m.Senal, Pedido]:
    meta = semanas.leer(senal_id)
    if meta is None:
        raise HTTPException(404, "Esta señal no tiene una semana abierta: subí la grilla")
    receta = _receta(senal_id)
    return receta, Pedido(tabla_id=meta["tabla_id"], senal=receta)


@api.get("/inicio")
def inicio(u: auth.Usuario = Depends(auth.usuario_actual)):
    """Todas las señales con su semana abierta, y las últimas que tocó esta persona."""
    abiertas, formatos = semanas.todas(), almacen.formatos()
    lista = [{**s, "formato": formatos.get(s["id"], "excel"), "semana": abiertas.get(s["id"])} for s in almacen.listar()]
    mias = [s for s in lista if s["semana"] and u.usuario in (s["semana"]["subida_por"], s["semana"]["confirmada_por"])]
    mias.sort(key=lambda s: max(s["semana"]["subida"], s["semana"]["confirmada"] or ""), reverse=True)
    return {"senales": lista, "recientes": [s["id"] for s in mias[:3]]}


# --- EPG crudo de las señales web ---

def _muestra_web(receta: m.Senal) -> pd.DataFrame:
    """La tabla de la página sin pasar al EPG crudo: de la semana abierta o, si no hay, del último ejemplo."""
    if receta.entrada.tipo != "html":
        raise HTTPException(422, "El EPG crudo es solo para señales que vienen de una página web")
    contenido = semanas.contenido(receta.id)
    if contenido is None:
        ejemplos = almacen.listar_ejemplos(receta.id)
        if not ejemplos:
            raise HTTPException(404, "Subí una grilla o un ejemplo de esta señal para ver sus columnas")
        contenido = almacen.leer_ejemplo(receta.id, ejemplos[-1])[0]
    try:
        return inputs.leer(contenido, receta.entrada.model_copy(update={"epg": {}}))
    except Exception as e:
        raise HTTPException(422, f"No se pudo leer la página: {e}")


@api.get("/senales/{senal_id}/epg-crudo", dependencies=[Depends(auth.solo_admin)])
def ver_epg_crudo(senal_id: str):
    receta = _receta(senal_id)
    tabla = _muestra_web(receta)
    ejemplo = lambda c: next((" ".join(str(v).split())[:80] for v in tabla[c] if v not in (None, "")), "")
    return {"fijas": epg_crudo.COLUMNAS[:-1], "origen": [{"columna": str(c), "ejemplo": ejemplo(c)} for c in tabla.columns],
            "mapa": receta.entrada.epg or epg_crudo.proponer(tabla), "activo": bool(receta.entrada.epg)}


class MapaEpg(BaseModel):
    mapa: dict[str, str]


@api.post("/senales/{senal_id}/epg-crudo", dependencies=[Depends(auth.solo_admin)])
def guardar_epg_crudo(senal_id: str, datos: MapaEpg, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Pasa la señal al EPG crudo (o cambia de dónde sale cada columna) y recalcula la base con ese hash."""
    receta = _receta(senal_id)
    tabla = _muestra_web(receta)
    mapa = {k: v for k, v in datos.mapa.items() if v}
    malas = [k for k in mapa if k not in epg_crudo.COLUMNAS] + [v for v in mapa.values() if v not in tabla.columns]
    if malas:
        raise HTTPException(422, f"Columnas que no existen: {', '.join(malas)}")
    if not {"Fecha", "Hora", "Título"} <= set(mapa):
        raise HTTPException(422, "Fecha, Hora y Título tienen que salir de alguna columna de la página")
    nueva = receta.model_copy(update={"entrada": receta.entrada.model_copy(update={"epg": mapa})})
    almacen.guardar(nueva, u.usuario)
    base, aviso = {"antes": None, "despues": None}, ""
    if not receta.entrada.epg:
        base = pautas.pasar_a_epg(senal_id, mapa)
    elif any(receta.entrada.epg.get(k) != mapa.get(k) for k in epg_crudo.COLUMNAS if k not in ("Fecha", "Hora", "Duración")):
        aviso = "Cambió de dónde sale el contenido: las pautas que cambien de texto van a aparecer como nuevas."
    # Las reglas que nombraban columnas de la página ahora fallan: se avisan para que el agente las ajuste.
    r = aplicar(epg_crudo.armar(tabla, mapa), nueva.tarjetas, nueva.titulos_conocidos)
    errores = [f"Regla {i + 1}: {inf.error}" for i, inf in enumerate(r.informes) if inf.error]
    return {"pautas": base, "reglas_con_error": errores, "aviso": aviso}


POR_PAGINA_TODAS = 300
# Cuántas semanas sin foto se arman por pedido: cada una corre las reglas, y así ninguno tarda demasiado.
FOTOS_POR_PEDIDO = 20


@api.get("/todas")
def todas_las_senales(estado: str = "", filtro: list[str] = Query(default=[]), desde: int = 0):
    """Las semanas abiertas de todas las señales juntas, con una columna Señal. Filtra por columna = texto."""
    nombres = {s["id"]: s["nombre"] for s in almacen.listar()}
    filtros = {col: _normalizar_texto(valor) for col, valor in _filtros(filtro).items() if valor.strip()}
    columnas = ["Señal", *semana.COLUMNAS_FOTO]
    filas, cuentas, sin_foto = [], {"base": 0, "nueva_lista": 0, "revisar": 0}, []
    for senal_id, foto in sorted(semanas.fotos().items(), key=lambda x: nombres.get(x[0], x[0]).lower()):
        if foto is None:
            sin_foto.append(senal_id)
            continue
        nombre = nombres.get(senal_id, senal_id)
        for fila in foto:
            completa = [nombre, *fila]
            if not all(b in _normalizar_texto(completa[columnas.index(col)]) for col, b in filtros.items() if col in columnas):
                continue
            cuentas[fila[0]] = cuentas.get(fila[0], 0) + 1
            if not estado or fila[0] == estado:
                filas.append([senal_id, *completa])
    return {"columnas": columnas, "filas": filas[desde:desde + POR_PAGINA_TODAS], "total": len(filas),
            "cuentas": cuentas, "sin_foto": len(sin_foto)}


def _normalizar_texto(texto) -> str:
    return unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode().lower()


@api.post("/todas/actualizar")
def actualizar_fotos():
    """Arma la foto de las semanas abiertas que todavía no tienen, de a FOTOS_POR_PEDIDO."""
    faltan = [s for s, foto in semanas.fotos().items() if foto is None]
    errores = []
    for senal_id in faltan[:FOTOS_POR_PEDIDO]:
        try:
            _semana_abierta(senal_id, _receta(senal_id))
        except Exception as e:  # una grilla que ya no se lee no frena a las demás
            errores.append(f"{senal_id}: {e}")
            semanas.guardar_resumen(senal_id, semanas.leer(senal_id)["resumen"] or {}, [])
    return {"quedan": max(len(faltan) - FOTOS_POR_PEDIDO, 0), "errores": errores}


@api.get("/senales/{senal_id}/abierta")
def ver_semana_abierta(senal_id: str):
    return _semana_abierta(senal_id, _receta(senal_id))


@api.post("/senales/{senal_id}/abierta")
async def abrir_semana(senal_id: str, archivo: UploadFile = File(...), u: auth.Usuario = Depends(auth.usuario_actual)):
    receta = _receta(senal_id)
    contenido = await _leer_archivo(archivo)
    return _abrir(receta, contenido, _detectar(contenido), archivo.filename or "grilla", u.usuario)


@api.post("/senales/{senal_id}/abierta/texto")
def abrir_semana_texto(senal_id: str, datos: TextoPegado, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Texto o HTML pegado. Se detecta qué es igual que con un archivo."""
    receta = _receta(senal_id)
    if not datos.texto.strip():
        raise HTTPException(422, "El texto está vacío")
    contenido = datos.texto.encode("utf-8")
    if len(contenido) > MAX_ARCHIVO:
        raise HTTPException(413, "El texto pasa los 20 MB")
    detectada = _detectar(contenido)
    if detectada.tipo == "texto":
        detectada = detectada.model_copy(update={"fecha_inicio": datos.fecha_inicio or None})
    return _abrir(receta, contenido, detectada, "HTML pegado" if detectada.tipo == "html" else "texto pegado",
                  u.usuario)


class Hashes(BaseModel):
    hashes: list[str]


@api.post("/senales/{senal_id}/abierta/aceptar")
def aceptar_abierta(senal_id: str, datos: Hashes, u: auth.Usuario = Depends(auth.usuario_actual)):
    receta, p = _pedido_abierta(senal_id)
    _guardar_nuevas(senal_id, p, u.usuario, set(datos.hashes))
    return _semana_abierta(senal_id, receta)


@api.post("/senales/{senal_id}/abierta/confirmar")
def confirmar_abierta(senal_id: str, u: auth.Usuario = Depends(auth.usuario_actual)):
    receta, p = _pedido_abierta(senal_id)
    _guardar_nuevas(senal_id, p, u.usuario)
    semanas.confirmar(senal_id, u.usuario)
    return _semana_abierta(senal_id, receta)


MAX_FILAS_GRILLA = 5000


def _grilla_abierta(senal_id: str) -> dict:
    """La semana abierta fila por fila, con el grupo y los avisos de cada una. De paso actualiza el resumen."""
    receta, p = _pedido_abierta(senal_id)
    c = _correr(p)
    armado = _armar_semana(c, receta)
    resumen = armado["resumen"] | _fechas(c.salida, receta)
    semanas.guardar_resumen(senal_id, resumen, armado["_foto"])
    avisos = _validar(c, receta)
    grupos = _clasificar(c, receta, avisos)
    n = min(len(c.salida), MAX_FILAS_GRILLA)
    return {
        "semana": {**semanas.leer(senal_id), "resumen": resumen},
        "columnas": [str(x) for x in c.salida.columns],
        "filas": export.a_filas(c.salida, n),
        "grupos": grupos[:n],
        "hashes": c.hashes[:n],
        "contenido": armado["contenido"],
        "programa": armado["programa"],
        "campos_clave": armado["campos_clave"],
        "validaciones": [asdict(a) for a in avisos if a.fila and a.fila <= n],
        "total_filas": len(c.salida),
    }


@api.get("/senales/{senal_id}/abierta/grilla")
def grilla_abierta(senal_id: str):
    return _grilla_abierta(senal_id)


class Celda(BaseModel):
    fila: int  # índice en la salida completa
    columna: str
    valor: str | None


@api.post("/senales/{senal_id}/abierta/celda")
def editar_celda_abierta(senal_id: str, datos: Celda, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Corrige una celda de la semana: la pauta de esa fila queda así en la base para todas las semanas."""
    receta, p = _pedido_abierta(senal_id)
    _editar_celda(senal_id, _correr(p), receta, datos.fila, datos.columna, datos.valor, u.usuario)
    return _grilla_abierta(senal_id)


# Hasta qué mes se repite la última semana: el de su último día, o también el siguiente.
REPETIR = {"mes": 0, "dos_meses": 1}


@api.get("/senales/{senal_id}/abierta/export")
def exportar_abierta(senal_id: str, formato: str = "xlsx", desde: str | None = None, hasta: str | None = None,
                     repetir: str | None = None):
    """`desde` y `hasta` (2026-11-02 o 2026-11-02T06:00) recortan lo que sale, con las dos puntas adentro.

    `repetir` copia la última semana hasta fin de mes ("mes") o del mes siguiente ("dos_meses"), antes del recorte.
    """
    receta, p = _pedido_abierta(senal_id)
    c = _correr(p)
    salida = _repetir(c.salida, receta, repetir) if repetir else c.salida
    salida = _recortar(salida, receta, desde, hasta) if desde or hasta else salida
    if salida is not c.salida:
        salida = _numerar(salida)
    return _archivo(salida, receta.id, formato, c.estados.count("nueva"))


def _columnas_de_fecha(salida: pd.DataFrame, receta: m.Senal, para: str) -> dict:
    cols = grilla.detectar_columnas(list(salida.columns), receta.validaciones)
    if not cols.get("fecha") or cols["fecha"] not in salida.columns:
        raise HTTPException(422, f"Esta grilla no tiene una columna de fecha para {para}")
    return cols


def _repetir(salida: pd.DataFrame, receta: m.Senal, repetir: str) -> pd.DataFrame:
    if repetir not in REPETIR:
        raise HTTPException(422, f"repetir tiene que ser {' o '.join(REPETIR)}")
    cols = _columnas_de_fecha(salida, receta, "repetir la semana")
    dias = [d for f in salida[cols["fecha"]] if (d := a_fecha(f))]
    if not dias:
        raise HTTPException(422, "La grilla no tiene fechas que se puedan leer")
    try:
        return semanas.repetir_ultima(salida, cols["fecha"], cols.get("hora"), semanas.fin_de_mes(max(dias), REPETIR[repetir]))
    except ValueError as e:
        raise HTTPException(422, str(e))


def _numerar(salida: pd.DataFrame) -> pd.DataFrame:
    numero = next((x for x in salida.columns if catalogo.clave(x) == "n"), None)
    if numero:
        salida[numero] = range(1, len(salida) + 1)
    return salida


def _momento(texto: str | None, fin: bool) -> dt.datetime | None:
    if not texto:
        return None
    try:
        momento = dt.datetime.fromisoformat(texto)
    except ValueError:
        raise HTTPException(422, f"Fecha inválida: {texto}")
    # Una fecha sola como "hasta" incluye todo ese día.
    return momento.replace(hour=23, minute=59, second=59) if fin and "T" not in texto else momento


def _recortar(salida: pd.DataFrame, receta: m.Senal, desde: str | None, hasta: str | None) -> pd.DataFrame:
    cols = _columnas_de_fecha(salida, receta, "recortar")
    inicio, fin = _momento(desde, False), _momento(hasta, True)
    horas = salida[cols["hora"]] if cols.get("hora") in salida.columns else [None] * len(salida)
    dentro = []
    for f, h in zip(salida[cols["fecha"]], horas):
        dia = a_fecha(f)
        cuando = dt.datetime.combine(dia, a_hora(h) or dt.time(0)) if dia else None
        dentro.append(cuando is not None and (inicio is None or cuando >= inicio) and (fin is None or cuando <= fin))
    return salida[dentro].reset_index(drop=True)


@api.post("/senales/{senal_id}/pautas/limpiar", dependencies=[Depends(auth.solo_admin)])
def limpiar_pautas(senal_id: str):
    """Saca de la base columnas que en realidad son horario (una hora con AM/PM, por ejemplo)."""
    _receta(senal_id)
    return pautas.limpiar(senal_id)


@api.post("/senales/{senal_id}/pautas/desde-ejemplos")
def pautas_desde_ejemplos(senal_id: str, u: auth.Usuario = Depends(auth.usuario_actual)):
    try:
        receta = almacen.leer(senal_id)
        nombres = almacen.listar_ejemplos(senal_id)
    except (almacen.NoExiste, ValueError):
        raise HTTPException(404, "No existe la señal")
    total = {"agregadas": 0, "conflictos": 0, "errores": []}
    for nombre in nombres:
        try:
            r = pautas.cargar_ejemplo(receta, *almacen.leer_ejemplo(senal_id, nombre), u.usuario)
        except Exception as e:
            total["errores"].append(f"{nombre}: {e}")
            continue
        total["agregadas"] += r["agregadas"]
        total["conflictos"] += r["conflictos"]
    return total


# --- Catálogo de columnas ---

@api.get("/catalogo")
def ver_catalogo():
    return [asdict(c) for c in catalogo.leer()]


@api.post("/catalogo", dependencies=[Depends(auth.solo_admin)])
async def cargar_catalogo(archivo: UploadFile = File(...)):
    try:
        columnas = catalogo.desde_excel(await _leer_archivo(archivo))
    except Exception as e:
        raise HTTPException(422, f"No se pudo leer el catálogo: {e}")
    if not columnas:
        raise HTTPException(422, "El Excel no tiene columnas")
    catalogo.guardar(columnas)
    return [asdict(c) for c in columnas]


@api.post("/senales/{senal_id}/ejemplos/evaluar")
def evaluar_ejemplos(senal_id: str, receta: m.Senal):
    """Corre la receta (aunque no esté guardada) contra cada ejemplo de la señal."""
    try:
        nombres = almacen.listar_ejemplos(senal_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    resultados = []
    for nombre in nombres:
        entrada, esperado_xlsx = almacen.leer_ejemplo(senal_id, nombre)
        try:
            tabla = inputs.leer_ejemplo(entrada, receta.entrada)
            salida, _ = correr(receta, tabla)
            esperado = pd.read_excel(io.BytesIO(esperado_xlsx), dtype=object)
        except Exception as e:
            resultados.append({"nombre": nombre, "error": f"No se pudo correr: {e}"})
            continue
        pares = controles.pares_con_ejemplo(tabla, esperado)
        difs = diferencias(salida, esperado, pares)
        texto = [c for c in esperado.columns if esperado[c].map(lambda v: isinstance(v, str)).any()]
        resultados.append({
            "nombre": nombre,
            "porcentaje": round(porcentaje_igual(salida, esperado, pares), 2),
            "filas": [len(salida), len(esperado)],
            "total_diferencias": len(difs),
            "diferencias": [{**d, "obtenido": export.celda_json(d["obtenido"]),
                             "esperado": export.celda_json(d["esperado"])} for d in difs[:100]],
            "correcciones": sugerir_correcciones(salida, esperado, texto, pares),
            "resumen_validaciones": grilla.resumen(grilla.validar(salida, receta.validaciones, receta.titulos_conocidos)),
        })
    return resultados


# --- Asistente ---

class MensajeHilo(BaseModel):
    rol: str  # persona | asistente
    texto: str


class PedidoAsistente(BaseModel):
    senal: m.Senal
    pedido: str
    tabla_id: str | None = None
    ejemplo: str | None = None  # "armar desde este ejemplo": la grilla es la entrada del ejemplo
    historial: list[MensajeHilo] = []
    fuerte: bool = False  # modelo más caro, solo para lo que el barato no resolvió
    contexto: str = ""  # qué está mirando la persona en la web ("Canal Demo · Para revisar · 3 marcadas")

    def pedido_con_contexto(self) -> str:
        return f"(La persona está mirando: {self.contexto[:300]})\n{self.pedido}" if self.contexto.strip() else self.pedido


def _proveedor_disponible(u: auth.Usuario, pedido: str):
    proveedor = cliente.proveedor_configurado()
    if proveedor is None:
        raise HTTPException(503, "El asistente no está configurado: falta la variable ANTHROPIC_API_KEY en el servidor")
    if uso.pedidos_de_hoy(u.usuario) >= uso.limite_diario():
        raise HTTPException(429, f"Llegaste al tope de {uso.limite_diario()} pedidos al asistente por hoy")
    if not pedido.strip():
        raise HTTPException(422, "Escribí qué querés que haga el asistente")
    return proveedor


@api.post("/asistente/charla")
def charla_asistente(p: PedidoAsistente, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Primer paso de cada mensaje: responde rápido o avisa que hay que armar una propuesta."""
    proveedor = _proveedor_disponible(u, p.pedido)
    tabla = _correr_tabla(p.tabla_id, p.senal) if p.tabla_id else None
    try:
        c = asistente_ia.charlar(p.senal, tabla, [h.model_dump() for h in p.historial], p.pedido_con_contexto(), proveedor)
    except cliente.ErrorAgente as e:
        raise HTTPException(502, str(e))
    uso.registrar(u.usuario, p.senal.id, "[charla] " + p.pedido, 1, c.tokens_entrada, c.tokens_salida, True, c.modelo)
    return asdict(c)


@api.post("/asistente")
def asistente(p: PedidoAsistente, u: auth.Usuario = Depends(auth.usuario_actual)):
    proveedor = _proveedor_disponible(u, p.pedido)

    try:
        # Hasta 3 ejemplos, siempre incluido el de "armar desde este ejemplo": más contexto encarece sin mejorar mucho.
        nombres = almacen.listar_ejemplos(p.senal.id)
        nombres = ([p.ejemplo] if p.ejemplo in nombres else []) + [n for n in nombres if n != p.ejemplo][:3 - bool(p.ejemplo)]
        ejemplos = [_leer_ejemplo(p.senal, n) for n in nombres]
    except ValueError as e:
        raise HTTPException(422, str(e))
    semana_antes = None
    if p.ejemplo:
        objetivo = next((e for e in ejemplos if e.nombre == p.ejemplo), None)
        if objetivo is None:
            raise HTTPException(404, "No existe ese ejemplo")
        tabla = objetivo.entrada
    elif p.tabla_id:
        tabla = _correr_tabla(p.tabla_id, p.senal)
        semana_antes = _semana_de(Pedido(tabla_id=p.tabla_id, senal=p.senal))
    else:
        tabla = pd.DataFrame()  # pedidos sobre la base o de admin no necesitan grilla

    cat = catalogo.leer()
    entorno = asistente_ia.Entorno(
        foco=[i for i, g in enumerate(semana_antes[1]) if g["grupo"] == "revisar"] if semana_antes else [],
        es_admin=u.admin, reglas_catalogo=[f"{c.nombre}: {c.regla or c.tipo}" for c in cat])
    try:
        propuesta = asistente_ia.pedir(p.senal, tabla, p.pedido_con_contexto(), proveedor, ejemplos, objetivo=p.ejemplo,
                                       orden_columnas=[c.nombre for c in cat],
                                       historial=[h.model_dump() for h in p.historial], entorno=entorno,
                                       fuerte=p.fuerte)
    except cliente.ErrorAgente as e:
        raise HTTPException(502, str(e))
    uso.registrar(u.usuario, p.senal.id, p.pedido, propuesta.vueltas, propuesta.tokens_entrada,
                  propuesta.tokens_salida, propuesta.logrado, propuesta.modelo)
    respuesta = asdict(propuesta)
    for c in respuesta["correcciones_base"]:
        c["pautas"] = len(pautas.hashes_filtrados(p.senal.id, filtros=c["filtro"]))
        c["descripcion"] = (f"En las pautas con {', '.join(f'{k} = {v}' for k, v in c['filtro'].items())}, "
                            f"poner {c['columna']} = {c['valor'] if c['valor'] is not None else '(vacío)'}")
    for a in respuesta["acciones_admin"]:
        a["descripcion"] = acciones.describir(acciones.LISTA.validate_python([a])[0])
    if semana_antes and propuesta.receta:
        respuesta["efecto"] = _efecto(semana_antes, Pedido(tabla_id=p.tabla_id, senal=m.Senal(**propuesta.receta)))
    return respuesta


MAX_EJEMPLOS_EFECTO = 5


def _semana_de(p: Pedido) -> tuple[Corrida, list[dict]]:
    c = _correr(p)
    return c, _clasificar(c, p.senal, _validar(c, p.senal))


def _efecto(antes: tuple[Corrida, list[dict]], p: Pedido) -> dict:
    """Qué le hace la propuesta a la semana abierta: celdas que cambian, algunas de muestra y cuántas ⚠ quedan."""
    c_antes, grupos_antes = antes
    c_despues, grupos_despues = _semana_de(p)
    difs = diferencias(c_despues.salida, c_antes.salida)
    return {
        "celdas": len(difs),
        "ejemplos": [{"fila": d["fila"], "columna": d["columna"], "antes": export.celda_json(d["esperado"]),
                      "despues": export.celda_json(d["obtenido"])} for d in difs[:MAX_EJEMPLOS_EFECTO]],
        "revisar_antes": sum(g["grupo"] == "revisar" for g in grupos_antes),
        "revisar_despues": sum(g["grupo"] == "revisar" for g in grupos_despues),
    }


@api.get("/asistente/limites")
def limites_asistente(u: auth.Usuario = Depends(auth.usuario_actual)):
    usados, limite = uso.pedidos_de_hoy(u.usuario), uso.limite_diario()
    return {"limite_diario": limite, "usados_hoy": usados, "quedan": max(limite - usados, 0)}


class PedidoBanco(BaseModel):
    senales: list[str]
    tope: float = 5.0
    pasos: list[str] = list(banco.PASOS)


@api.get("/admin/banco/senales", dependencies=[Depends(auth.solo_admin)])
def senales_para_banco():
    """Las señales que tienen al menos un ejemplo, con la fecha del más reciente: las que el banco puede probar."""
    con_ejemplos = []
    for s in almacen.listar():
        nombres = almacen.listar_ejemplos(s["id"])
        if nombres:
            con_ejemplos.append({"id": s["id"], "nombre": s["nombre"], "ejemplos": len(nombres), "ultimo": nombres[-1]})
    return sorted(con_ejemplos, key=lambda s: s["ultimo"], reverse=True)


@api.post("/admin/banco")
def lanzar_banco(p: PedidoBanco, u: auth.Usuario = Depends(auth.solo_admin)):
    """Arranca una corrida del banco de agentes en segundo plano; gasta API de verdad hasta `tope` dólares."""
    if not p.senales:
        raise HTTPException(422, "Elegí al menos una señal")
    if not 0 < p.tope <= 50:
        raise HTTPException(422, "El tope tiene que ser de más de 0 y hasta 50 dólares")
    pasos = [x for x in p.pasos if x in banco.PASOS]
    if not pasos:
        raise HTTPException(422, f"Los pasos posibles son {', '.join(banco.PASOS)}")
    proveedor = cliente.proveedor_configurado()
    if proveedor is None:
        raise HTTPException(503, "El asistente no está configurado: falta la variable ANTHROPIC_API_KEY en el servidor")
    try:
        return {"id": corridas.lanzar(u.usuario, p.senales, p.tope, pasos, proveedor)}
    except corridas.YaCorriendo as e:
        raise HTTPException(409, str(e))


@api.get("/admin/banco", dependencies=[Depends(auth.solo_admin)])
def corridas_del_banco():
    return corridas.listar()


@api.get("/admin/banco/{corrida_id}", dependencies=[Depends(auth.solo_admin)])
def corrida_del_banco(corrida_id: int):
    c = corridas.leer(corrida_id)
    if c is None:
        raise HTTPException(404, "No existe esa corrida")
    return c


class AccionesAdmin(BaseModel):
    acciones: list[dict]


@api.post("/admin/acciones", dependencies=[Depends(auth.solo_admin)])
def aplicar_acciones(datos: AccionesAdmin, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Ejecuta acciones de admin propuestas por el agente. La clave de un usuario nuevo se muestra una sola vez."""
    try:
        # La web devuelve las acciones tal como las mostró, con su descripción.
        lista = acciones.LISTA.validate_python([{k: v for k, v in a.items() if k != "descripcion"}
                                                for a in datos.acciones])
    except ValidationError as e:
        raise HTTPException(422, f"Acción inválida: {e.errors()[0]['msg']}")
    resultados = []
    for a in lista:
        try:
            resultados.append(acciones.ejecutar(a, u.usuario))
        except (ValueError, LookupError) as e:
            resultados.append({"descripcion": acciones.describir(a), "ok": False, "error": str(e).strip("'")})
    return resultados


@api.get("/asistente/uso", dependencies=[Depends(auth.solo_admin)])
def uso_asistente():
    return {"configurado": cliente.proveedor_configurado() is not None, "limite_diario": uso.limite_diario(),
            "usuarios": uso.resumen_del_mes()}


def _leer_ejemplo(receta: m.Senal, nombre: str) -> asistente_ia.Ejemplo:
    entrada, esperado = almacen.leer_ejemplo(receta.id, nombre)
    return asistente_ia.Ejemplo(nombre, inputs.leer_ejemplo(entrada, receta.entrada),
                                pd.read_excel(io.BytesIO(esperado), dtype=object))


def _correr_tabla(tabla_id: str | None, receta: m.Senal) -> pd.DataFrame:
    if not tabla_id:
        raise HTTPException(422, "Subí una grilla antes de pedirle algo al asistente")
    try:
        return tablas.tabla(tabla_id, receta.entrada)
    except KeyError:
        raise HTTPException(410, "El archivo ya no está en memoria: volvé a subirlo")
