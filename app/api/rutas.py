import datetime as dt
import io
import json
import os
from dataclasses import asdict

import pandas as pd
from fastapi import APIRouter, Cookie, Depends, Header, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import almacen, auth, export, tablas
from app.agent import asistente as asistente_ia
from app.agent import cliente, uso
from app.engine import model as m
from app.engine import titulos
from app.engine.comparar import diferencias, porcentaje_igual, sugerir_correcciones
from app.engine.pipeline import DE_ESTRUCTURA, correr
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
        actual = almacen.version(senal_id)
        if if_match is not None and actual is not None and if_match != actual:
            quien = almacen.ultimo_guardado(senal_id)
            detalle = f"{quien[0]} guardó cambios el {quien[1]:%d/%m a las %H:%M}" if quien else "Alguien guardó cambios"
            raise HTTPException(409, detalle)
        almacen.guardar(receta, u.usuario)
    except ValueError as e:
        raise HTTPException(422, str(e))
    response.headers["ETag"] = almacen.version(senal_id)
    return {"ok": True}


@api.post("/senales/validar")
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
                _, esperado = almacen.rutas_ejemplo(senal_id, nombre)
                tablas.append(pd.read_excel(esperado, dtype=object))
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


def _correr(p: Pedido):
    try:
        tabla = tablas.tabla(p.tabla_id, p.senal.entrada)
    except KeyError:
        raise HTTPException(410, "El archivo ya no está en memoria: volvé a subirlo")
    except Exception as e:  # Excel roto o config de entrada que no corresponde
        raise HTTPException(422, f"No se pudo leer el Excel: {e}")
    return correr(p.senal, tabla)


@api.post("/preview")
def preview(p: Pedido):
    salida, informes = _correr(p)
    avisos = grilla.validar(salida, p.senal.validaciones, p.senal.titulos_conocidos)
    return {
        "columnas": [str(c) for c in salida.columns],
        "filas": export.a_filas(salida, p.filas),
        "total_filas": len(salida),
        "tarjetas": [asdict(i) for i in informes],
        "validaciones": [asdict(a) for a in avisos],
        "resumen_validaciones": grilla.resumen(avisos),
        "columnas_validadas": grilla.detectar_columnas(list(salida.columns), p.senal.validaciones),
    }


class PedidoExport(Pedido):
    formato: str = "xlsx"


@api.post("/export")
def exportar(p: PedidoExport):
    salida, _ = _correr(p)
    fecha = dt.date.today().isoformat()
    if p.formato == "csv":
        return Response(export.a_csv(salida), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{p.senal.id}_{fecha}.csv"'})
    return Response(export.a_xlsx(salida),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{p.senal.id}_{fecha}.xlsx"'})


# --- Ejemplos antes/después ---

@api.get("/senales/{senal_id}/ejemplos")
def ejemplos(senal_id: str):
    try:
        return almacen.listar_ejemplos(senal_id)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.post("/senales/{senal_id}/ejemplos")
async def subir_ejemplo(senal_id: str, nombre: str = Form(...),
                        entrada: UploadFile = File(...), esperado: UploadFile = File(...)):
    try:
        almacen.guardar_ejemplo(senal_id, nombre, await _leer_archivo(entrada), await _leer_archivo(esperado))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@api.delete("/senales/{senal_id}/ejemplos/{nombre}")
def borrar_ejemplo(senal_id: str, nombre: str):
    try:
        almacen.borrar_ejemplo(senal_id, nombre)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@api.post("/senales/{senal_id}/ejemplos/evaluar")
def evaluar_ejemplos(senal_id: str, receta: m.Senal):
    """Corre la receta (aunque no esté guardada) contra cada ejemplo de la señal."""
    try:
        nombres = almacen.listar_ejemplos(senal_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    resultados = []
    for nombre in nombres:
        ruta_entrada, ruta_esperado = almacen.rutas_ejemplo(senal_id, nombre)
        try:
            salida, _ = correr(receta, excel.leer(ruta_entrada, receta.entrada))
            esperado = pd.read_excel(ruta_esperado, dtype=object)
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

class PedidoAsistente(BaseModel):
    senal: m.Senal
    pedido: str
    tabla_id: str | None = None
    ejemplo: str | None = None  # "armar desde este ejemplo": la grilla es la entrada del ejemplo


@api.post("/asistente")
def asistente(p: PedidoAsistente, u: auth.Usuario = Depends(auth.usuario_actual)):
    proveedor = cliente.proveedor_configurado()
    if proveedor is None:
        raise HTTPException(503, "El asistente no está configurado: falta la variable ANTHROPIC_API_KEY en el servidor")
    if uso.pedidos_de_hoy(u.usuario) >= uso.limite_diario():
        raise HTTPException(429, f"Llegaste al tope de {uso.limite_diario()} pedidos al asistente por hoy")
    if not p.pedido.strip():
        raise HTTPException(422, "Escribí qué querés que haga el asistente")

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

    propuesta = asistente_ia.pedir(p.senal, tabla, p.pedido, proveedor, ejemplos, objetivo=p.ejemplo)
    uso.registrar(u.usuario, p.senal.id, p.pedido, propuesta.vueltas, propuesta.tokens_entrada,
                  propuesta.tokens_salida, propuesta.logrado)
    return asdict(propuesta)


@api.get("/asistente/uso", dependencies=[Depends(auth.solo_admin)])
def uso_asistente():
    return {"configurado": cliente.proveedor_configurado() is not None, "limite_diario": uso.limite_diario(),
            "usuarios": uso.resumen_del_mes()}


def _leer_ejemplo(receta: m.Senal, nombre: str) -> asistente_ia.Ejemplo:
    ruta_entrada, ruta_esperado = almacen.rutas_ejemplo(receta.id, nombre)
    return asistente_ia.Ejemplo(nombre, excel.leer(ruta_entrada, receta.entrada), pd.read_excel(ruta_esperado, dtype=object))


def _correr_tabla(tabla_id: str | None, receta: m.Senal) -> pd.DataFrame:
    if not tabla_id:
        raise HTTPException(422, "Subí una grilla antes de pedirle algo al asistente")
    try:
        return tablas.tabla(tabla_id, receta.entrada)
    except KeyError:
        raise HTTPException(410, "El archivo ya no está en memoria: volvé a subirlo")
