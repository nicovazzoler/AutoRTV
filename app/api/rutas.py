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
from fastapi import APIRouter, Cookie, Depends, Header, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import almacen, auth, catalogo, export, pautas, tablas
from app.agent import asistente as asistente_ia
from app.agent import cliente, uso
from app.engine import model as m
from app.engine import titulos
from app.engine.comparar import diferencias, porcentaje_igual, sugerir_correcciones
from app.engine.pipeline import DE_ESTRUCTURA, aplicar, armar_salida, correr
from app.inputs import excel
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
    return {"tabla_id": tablas.subir(await _leer_archivo(archivo)), "nombre": archivo.filename}


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


def _correr(p: Pedido) -> Corrida:
    """Reglas → base de pautas → columnas de salida → orden del catálogo."""
    try:
        tabla = tablas.tabla(p.tabla_id, p.senal.entrada)
    except KeyError:
        raise HTTPException(410, "El archivo ya no está en memoria: volvé a subirlo")
    except Exception as e:  # Excel roto o config de entrada que no corresponde
        raise HTTPException(422, f"No se pudo leer el Excel: {e}")
    r = aplicar(tabla, p.senal.tarjetas, p.senal.titulos_conocidos)
    df, estados, hashes = pautas.aplicar(tabla, r.tabla, pautas.base(p.senal.id))
    salida = armar_salida(df, p.senal.salida)
    cat = catalogo.leer()
    if cat and not p.senal.salida.columnas:  # sin columnas de salida elegidas, se ordenan como el catálogo
        salida = salida[catalogo.ordenar(list(salida.columns), cat)]
    return Corrida(salida, r.informes, cat, estados, hashes, pautas.crudas(tabla))


def _resumen_pautas(estados: list[str]) -> dict:
    return {e: estados.count(e) for e in ("conocida", "editada", "nueva")}


@api.post("/preview")
def preview(p: Pedido):
    c = _correr(p)
    salida = c.salida
    avisos = grilla.validar(salida, p.senal.validaciones, p.senal.titulos_conocidos, c.catalogo, p.senal.idiomas)
    indices = [i for i, e in enumerate(c.estados) if e == "nueva"] if p.solo_nuevas else list(range(len(salida)))
    indices = indices[:p.filas]
    return {
        "columnas": [str(x) for x in salida.columns],
        "filas": export.a_filas(salida.iloc[indices]),
        "indices": indices,
        "estados": [c.estados[i] for i in indices],
        "hashes": [c.hashes[i] for i in indices],
        "resumen_pautas": _resumen_pautas(c.estados),
        "contenido": pautas.columnas_de_contenido(list(salida.columns), p.senal.validaciones),
        "total_filas": len(salida),
        "tarjetas": [asdict(i) for i in c.informes],
        "validaciones": [asdict(a) for a in avisos],
        "resumen_validaciones": grilla.resumen(avisos),
        "columnas_validadas": grilla.detectar_columnas(list(salida.columns), p.senal.validaciones),
    }


class PedidoExport(Pedido):
    formato: str = "xlsx"


@api.post("/export")
def exportar(p: PedidoExport):
    c = _correr(p)
    fecha = dt.date.today().isoformat()
    cabeceras = {"X-Pautas-Nuevas": str(c.estados.count("nueva"))}
    if p.formato == "csv":
        return Response(export.a_csv(c.salida), media_type="text/csv", headers={
            **cabeceras, "Content-Disposition": f'attachment; filename="{p.senal.id}_{fecha}.csv"'})
    return Response(export.a_xlsx(c.salida),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={**cabeceras, "Content-Disposition": f'attachment; filename="{p.senal.id}_{fecha}.xlsx"'})


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
            fila = excel.detectar_fila_encabezado(io.BytesIO(crudo))
            receta = m.Senal(id=senal_id, nombre=nombre, entrada=m.EntradaExcel(tipo="excel", fila_encabezado=fila),
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
    return {"id": senal_id, "nombre": receta.nombre, "ejemplo": sello, "tabla_id": tablas.subir(crudo),
            "pautas": _cargar_pautas(senal_id, crudo, terminado, u.usuario)}


def _comparable(nombre: str) -> str:
    return _slug(nombre).replace("-", "")


def senales_parecidas(nombre: str, senales: list[dict], umbral: float = 0.8) -> list[dict]:
    """Señales con el mismo nombre o uno parecido, sin contar mayúsculas, tildes ni signos."""
    buscado = _comparable(nombre)
    return [s for s in senales
            if s["id"] == _slug(nombre)
            or difflib.SequenceMatcher(None, buscado, _comparable(s["nombre"])).ratio() >= umbral]


def _slug(nombre: str) -> str:
    texto = unicodedata.normalize("NFD", nombre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:64] or "senal"


# --- Base de pautas ---

@api.get("/senales/{senal_id}/pautas")
def listar_pautas(senal_id: str, estado: str | None = None, q: str = "", desde: int = 0):
    return pautas.listar(senal_id, estado or None, q, max(desde, 0))


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
    c = _correr(p)
    contenido = pautas.columnas_de_contenido(list(c.salida.columns), p.senal.validaciones)
    if p.columna not in contenido:
        raise HTTPException(422, "Esta columna sale de las reglas (horario o numeración) y no se edita en la base")
    if not 0 <= p.fila < len(c.salida):
        raise HTTPException(422, "Esa fila no existe")
    salida = {col: pautas.valor_json(c.salida.iloc[p.fila][col]) for col in contenido}
    salida[p.columna] = _convertir(p.valor, p.columna, c.catalogo)
    h = c.hashes[p.fila]
    pautas.guardar(senal_id, {h: {"crudo": c.crudas[p.fila], "salida": salida}}, "editada", u.usuario, pisar=True)
    return {"ok": True, "hash": h}


def _convertir(valor: str | None, columna: str, cat: list):
    """El texto escrito, como número si el catálogo dice que la columna es numérica."""
    valor = (valor or "").strip()
    if not valor:
        return None
    tipo = next((x.tipo for x in cat if catalogo.clave(x.nombre) == catalogo.clave(columna)), None)
    if tipo in ("entero", "anio") and re.fullmatch(r"-?\d+", valor):
        return int(valor)
    return valor


@api.post("/senales/{senal_id}/pautas/revisar")
def revisar_pautas(senal_id: str, p: Pedido, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Guarda como revisadas las pautas nuevas de esta grilla, tal como las arman hoy las reglas."""
    c = _correr(p)
    contenido = pautas.columnas_de_contenido(list(c.salida.columns), p.senal.validaciones)
    nuevas = {}
    for i, estado in enumerate(c.estados):
        if estado == "nueva" and c.hashes[i] not in nuevas:
            nuevas[c.hashes[i]] = {"crudo": c.crudas[i],
                                   "salida": {col: pautas.valor_json(c.salida.iloc[i][col]) for col in contenido}}
    return {"revisadas": pautas.guardar(senal_id, nuevas, "revisada", u.usuario)}


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
            salida, _ = correr(receta, excel.leer(io.BytesIO(entrada), receta.entrada))
            esperado = pd.read_excel(io.BytesIO(esperado_xlsx), dtype=object)
        except Exception as e:
            resultados.append({"nombre": nombre, "error": f"No se pudo correr: {e}"})
            continue
        difs = diferencias(salida, esperado)
        texto = [c for c in esperado.columns if esperado[c].map(lambda v: isinstance(v, str)).any()]
        resultados.append({
            "nombre": nombre,
            "porcentaje": round(porcentaje_igual(salida, esperado), 2),
            "filas": [len(salida), len(esperado)],
            "total_diferencias": len(difs),
            "diferencias": [{**d, "obtenido": export.celda_json(d["obtenido"]),
                             "esperado": export.celda_json(d["esperado"])} for d in difs[:100]],
            "correcciones": sugerir_correcciones(salida, esperado, texto),
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
    c = asistente_ia.charlar(p.senal, tabla, [h.model_dump() for h in p.historial], p.pedido, proveedor)
    uso.registrar(u.usuario, p.senal.id, "[charla] " + p.pedido, 1, c.tokens_entrada, c.tokens_salida, True)
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
    if p.ejemplo:
        objetivo = next((e for e in ejemplos if e.nombre == p.ejemplo), None)
        if objetivo is None:
            raise HTTPException(404, "No existe ese ejemplo")
        tabla = objetivo.entrada
    else:
        tabla = _correr_tabla(p.tabla_id, p.senal)

    orden = [c.nombre for c in catalogo.leer()]
    propuesta = asistente_ia.pedir(p.senal, tabla, p.pedido, proveedor, ejemplos, objetivo=p.ejemplo,
                                   orden_columnas=orden, historial=[h.model_dump() for h in p.historial])
    uso.registrar(u.usuario, p.senal.id, p.pedido, propuesta.vueltas, propuesta.tokens_entrada,
                  propuesta.tokens_salida, propuesta.logrado)
    return asdict(propuesta)


@api.get("/asistente/uso", dependencies=[Depends(auth.solo_admin)])
def uso_asistente():
    return {"configurado": cliente.proveedor_configurado() is not None, "limite_diario": uso.limite_diario(),
            "usuarios": uso.resumen_del_mes()}


def _leer_ejemplo(receta: m.Senal, nombre: str) -> asistente_ia.Ejemplo:
    entrada, esperado = almacen.leer_ejemplo(receta.id, nombre)
    return asistente_ia.Ejemplo(nombre, excel.leer(io.BytesIO(entrada), receta.entrada),
                                pd.read_excel(io.BytesIO(esperado), dtype=object))


def _correr_tabla(tabla_id: str | None, receta: m.Senal) -> pd.DataFrame:
    if not tabla_id:
        raise HTTPException(422, "Subí una grilla antes de pedirle algo al asistente")
    try:
        return tablas.tabla(tabla_id, receta.entrada)
    except KeyError:
        raise HTTPException(410, "El archivo ya no está en memoria: volvé a subirlo")
