import datetime as dt
import difflib
import io
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Cookie, Depends, Header, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import (acciones, almacen, armados, arreglos, auth, catalogo, confianza, conversaciones, corridas, export, fechar,
                 historial, inputs, parecidas, pautas, semana, semanas, tablas, web)
from app.agent import asistente as asistente_ia
from app.agent import banco, cliente, controles, lectura, uso
from app.agent import parecidas as parecidas_ia
from app.caja import autoprueba
from app.engine import model as m
from app.engine import titulos
from app.engine.comparar import diferencias, porcentaje_igual, sugerir_correcciones
from app.engine.pipeline import DE_ESTRUCTURA, aplicar, armar_salida, correr, paso_final
from app.engine.tarjetas.estructura import a_fecha, a_hora
from app.inputs import epg as epg_crudo
from app.inputs import excel as inputs_excel
from app.inputs import varios as inputs_varios
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
    perfiles = auth.perfiles()
    return [asdict(u) | perfiles.get(u.usuario, {}) for u in auth.listar_usuarios()]


class Perfil(BaseModel):
    nombre: str = ""
    descripcion: str = ""


@api.put("/usuarios/{usuario_id}/perfil", dependencies=[Depends(auth.solo_admin)])
def guardar_perfil(usuario_id: int, datos: Perfil):
    """Quién es cada uno y qué hace: el agente lo lee para saber con quién habla."""
    try:
        auth.guardar_perfil(usuario_id, datos.nombre, datos.descripcion)
    except LookupError:
        raise HTTPException(404, "No existe ese usuario")
    return {"ok": True}


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


# --- Historial ---

@api.get("/historial")
def ver_historial(usuario: str | None = None, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Las cargas de semana con lo que se cambió en cada una. Cada uno ve lo suyo; el admin, lo de todos o de quien elija."""
    return historial.cargas(usuario if u.admin else u.usuario)


@api.get("/historial/{senal_id}")
def detalle_historial(senal_id: str, carga: str = "", usuario: str | None = None,
                      u: auth.Usuario = Depends(auth.usuario_actual)):
    return historial.detalle(senal_id, carga, usuario if u.admin else u.usuario)


# --- Avisos al admin ---

@api.get("/admin/avisos", dependencies=[Depends(auth.solo_admin)])
def listar_avisos(sin_ver: bool = False):
    return conversaciones.avisos(sin_ver)


@api.post("/admin/avisos/{aviso_id}/visto", dependencies=[Depends(auth.solo_admin)])
def aviso_visto(aviso_id: int):
    conversaciones.marcar_visto(aviso_id)
    return {"ok": True}


# --- Chats con el agente: cada persona los suyos ---

class MensajeNuevo(BaseModel):
    conversacion_id: int | None = None
    rol: Literal["persona", "asistente"]
    texto: str
    senal_id: str | None = None


@api.get("/agente/conversaciones")
def mis_conversaciones(u: auth.Usuario = Depends(auth.usuario_actual)):
    return conversaciones.listar(u.usuario)


@api.get("/agente/conversaciones/{conversacion_id}")
def una_conversacion(conversacion_id: int, u: auth.Usuario = Depends(auth.usuario_actual)):
    lista = conversaciones.mensajes(u.usuario, conversacion_id)
    if lista is None:
        raise HTTPException(404, "No existe ese chat")
    return lista


@api.delete("/agente/conversaciones/{conversacion_id}")
def borrar_conversacion(conversacion_id: int, u: auth.Usuario = Depends(auth.usuario_actual)):
    conversaciones.borrar(u.usuario, conversacion_id)
    return {"ok": True}


@api.post("/agente/mensajes")
def guardar_mensaje(datos: MensajeNuevo, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Suma un mensaje al chat (o abre uno nuevo) y devuelve el id del chat."""
    if not datos.texto.strip():
        raise HTTPException(422, "Mensaje vacío")
    cid = conversaciones.agregar(u.usuario, datos.conversacion_id, datos.rol, datos.texto[:8000], datos.senal_id)
    if cid is None:
        raise HTTPException(404, "No existe ese chat")
    return {"conversacion_id": cid}


def _avisar_del_agente(u: auth.Usuario, senal_id: str, detalle: str) -> None:
    """Lo que un usuario común hizo con «Hacerlo» en el agente le llega al admin, una vez por pedido."""
    if not u.admin and historial.ORIGEN.get() == "agente":
        conversaciones.avisar(u.usuario, senal_id, "agente", detalle)


@api.get("/agente/notas")
def mis_notas(u: auth.Usuario = Depends(auth.usuario_actual)):
    return conversaciones.notas(u.usuario)


@api.delete("/agente/notas/{nota_id}")
def olvidar_nota(nota_id: int, u: auth.Usuario = Depends(auth.usuario_actual)):
    conversaciones.olvidar_nota(u.usuario, nota_id)
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
        antes = almacen.leer(senal_id)
    except almacen.NoExiste:
        antes = None
    receta = _con_el_codigo_de_antes(receta, antes, u)
    try:
        response.headers["ETag"] = almacen.guardar(receta, u.usuario, esperada=if_match)
    except almacen.Conflicto as c:
        raise HTTPException(409, f"{c.usuario} guardó cambios el {c.fecha:%d/%m a las %H:%M}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    cambios = asistente_ia.cambios(antes, receta) if antes is not None else []
    if cambios:
        historial.anotar(senal_id, u.usuario, "reglas", [{"programa": _frase_cambio(c)} for c in cambios])
    if cambios and not u.admin:
        conversaciones.avisar(u.usuario, senal_id, "reglas", "; ".join(_frase_cambio(c) for c in cambios[:10]))
    return {"ok": True}


def _codigos(receta: m.Senal | None) -> dict:
    if receta is None:
        return {}
    lector = receta.entrada.lector if receta.entrada.tipo == "codigo" else None
    return {k: c for k, c in (("lector", lector), ("final", receta.final)) if c is not None}


def _solo_codigo_guardado(receta: m.Senal) -> m.Senal:
    """Una receta que llega en un pedido (vista previa, asistente) corre con el código guardado de la señal, no con
    el que traiga: código nuevo solo lo escribe el agente, que lo comprueba contra el ejemplo."""
    codigos = _codigos(receta)
    if not codigos:
        return receta
    try:
        guardada = almacen.leer(receta.id)
    except (almacen.NoExiste, ValueError):
        guardada = None
    previos, cambios = _codigos(guardada), {}
    if "lector" in codigos and previos.get("lector") != codigos["lector"]:
        if guardada is None or guardada.entrada.tipo != "codigo":
            raise HTTPException(422, "El lector en código lo escribe el agente de la señal")
        cambios["entrada"] = guardada.entrada
    if "final" in codigos and previos.get("final") != codigos["final"]:
        cambios["final"] = guardada.final if guardada is not None else None
    return receta.model_copy(update=cambios) if cambios else receta


def _con_el_codigo_de_antes(receta: m.Senal, antes: m.Senal | None, u: auth.Usuario) -> m.Senal:
    """El código de una señal lo escribe el agente, que lo comprueba contra el ejemplo y avisa al admin.

    Un guardado común puede sacarlo, no traer código nuevo. Si un admin lo cambia a mano, queda sin comprobar.
    """
    previos = _codigos(antes)
    for donde, codigo in _codigos(receta).items():
        if donde in previos and previos[donde].codigo == codigo.codigo:
            continue
        if not u.admin:
            raise HTTPException(403, "El código de la señal lo escribe el agente: pedíselo en el chat o en Configuración")
        sin_comprobar = codigo.model_copy(update={"comprobado": False, "resultado": "", "autor": u.usuario})
        if donde == "lector":
            receta = receta.model_copy(update={"entrada": receta.entrada.model_copy(update={"lector": sin_comprobar})})
        else:
            receta = receta.model_copy(update={"final": sin_comprobar})
    return receta


def _frase_cambio(c: dict) -> str:
    tarjeta = c.get("tarjeta", {})
    que = f"{tarjeta.get('tipo', '')} {tarjeta.get('columna') or tarjeta.get('columnas') or ''}".strip()
    return {"agregada": f"agregó {que}", "modificada": f"cambió {que} ({', '.join(c.get('campos', []))})",
            "borrada": f"sacó {que}", "salida": "cambió las columnas de salida", "orden": "reordenó las reglas"}[c["tipo"]]


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
    programa: str | None  # la columna del programa en la salida


def _correr(p: Pedido) -> Corrida:
    """Reglas → base de pautas → columnas de salida → orden del catálogo."""
    p = p.model_copy(update={"senal": _solo_codigo_guardado(p.senal)})
    try:
        tabla = tablas.tabla(p.tabla_id, p.senal.entrada)
    except KeyError:
        raise HTTPException(410, "El archivo ya no está en memoria: volvé a subirlo")
    except Exception as e:  # Excel roto o config de entrada que no corresponde
        raise HTTPException(422, f"No se pudo leer la grilla: {e}")
    base = pautas.base(p.senal.id)
    columnas_base = sorted({c for pauta in base.values() for c in pauta["salida"]})
    del_programa = semana.columna_programa(columnas_base, p.senal.validaciones, semana.pares_de_la_base(base))
    programas = semana.programas_de_la_base(base, del_programa)
    r = aplicar(tabla, p.senal.tarjetas, [*p.senal.titulos_conocidos, *programas])
    df, estados, hashes = pautas.aplicar(tabla, r.tabla, base)
    if del_programa not in df.columns:
        del_programa = semana.columna_programa(list(df.columns), p.senal.validaciones)
    df = semana.completar_del_programa(df, estados, base, del_programa)
    salida = semana.completar_titulos(armar_salida(df, p.senal.salida), crear=not p.senal.salida.columnas)
    cat = catalogo.leer()
    if cat and not p.senal.salida.columnas:
        salida = salida[catalogo.ordenar(list(salida.columns), cat)]
    crudas = pautas.crudas(tabla)
    salida, origen, informe = paso_final(salida, p.senal)
    if origen is not None:
        contenido = pautas.columnas_de_contenido(salida, p.senal.validaciones)
        agregadas = {i: pautas.de_paso_final({c: pautas.valor_json(salida.iloc[i][c]) for c in contenido})
                     for i, o in enumerate(origen) if o is None}
        estados = [estados[o] if o is not None else "generada" for o in origen]
        hashes = [hashes[o] if o is not None else agregadas[i] for i, o in enumerate(origen)]
        crudas = [crudas[o] if o is not None else {} for o in origen]
    return Corrida(salida, r.informes + ([informe] if informe else []), cat, estados, hashes, crudas, tabla, programas,
                   base, del_programa if del_programa in salida.columns else None)


def _validar(c: Corrida, receta: m.Senal) -> list:
    return grilla.validar(c.salida, receta.validaciones, receta.titulos_conocidos, c.catalogo, receta.idiomas)


def _clasificar(c: Corrida, receta: m.Senal, avisos: list) -> list[dict]:
    columnas = list(c.salida.columns)
    columna = c.programa
    capitulo = [x for x in semana.campos_clave(columnas, columna) if x != columna]
    repetidas = semana.sinopsis_repetidas(c.salida, [p["salida"] for p in c.base.values()], columna, capitulo)
    grupos = semana.clasificar(c.salida, c.estados, avisos, c.informes, c.programas, columna, repetidas)
    if motivo := codigo_sin_comprobar(receta):
        for g in grupos:
            g.update(grupo="revisar", motivos=[motivo, *g["motivos"]], codigos=["codigo_sin_comprobar", *g["codigos"]])
    return grupos


def codigo_sin_comprobar(receta: m.Senal) -> str | None:
    """El código de la señal que todavía no pasó un ejemplo: hasta que lo pase, la semana entera queda para revisar."""
    if receta.entrada.tipo == "codigo" and receta.entrada.lector.activo and not receta.entrada.lector.comprobado:
        return "El lector en código todavía no se comprobó con un ejemplo de la señal"
    if receta.final is not None and receta.final.activo and not receta.final.comprobado:
        return "El paso final en código todavía no se comprobó con un ejemplo de la señal"
    return None


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
        "_foto": semana.foto(c.salida, grupos, receta.validaciones, c.programa),
        "lectura": {"filas": len(c.crudo), "columnas": [str(x) for x in c.crudo.columns],
                    "hojas": c.crudo.attrs.get("hojas", 1)},
        "resumen": {"filas": len(c.salida), **cuenta, "pautas_revisar": len(revisar)},
        "contenido": contenido,
        "programa": c.programa,
        "criterios_en_prueba": confianza.sin_confianza(receta),
        "faltan_horario": _faltan_horario(c.salida, receta),
        "sin_reglas": not receta.tarjetas,
        "campos_clave": semana.campos_clave(contenido, c.programa),
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
    base = _cargar_pautas(senal_id, crudo, terminado, u.usuario)
    return {"ok": True, "pautas": base, "armando_reglas": _armar_si_no_tiene(senal_id, u.usuario)}


def _armar_si_no_tiene(senal_id: str, usuario: str) -> bool:
    """Una señal sin reglas que recibe un ejemplo: el agente las arma solo."""
    try:
        sin_reglas = not almacen.leer(senal_id).tarjetas
    except almacen.NoExiste:
        return False
    return sin_reglas and armados.lanzar(senal_id, usuario)


@api.get("/senales/{senal_id}/reglas/confianza")
def confianza_de_reglas(senal_id: str):
    """Semanas confirmadas sin correcciones de cada criterio, y cuántas hacen falta para confiar."""
    _receta(senal_id)
    return {"semanas": confianza.leer(senal_id), "hacen_falta": confianza.SEMANAS_CONFIABLE}


@api.get("/senales/{senal_id}/reglas/propuestas")
def propuestas_de_reglas(senal_id: str):
    """Reglas para crear o revisar según lo que se corrigió; cada una trae el pedido para el agente."""
    return confianza.propuestas(_receta(senal_id))


class Clave(BaseModel):
    clave: str


@api.post("/senales/{senal_id}/reglas/propuestas/descartar")
def descartar_propuesta(senal_id: str, datos: Clave):
    _receta(senal_id)
    confianza.descartar(senal_id, datos.clave)
    return {"ok": True}


@api.get("/senales/{senal_id}/reglas/armado")
def estado_del_armado(senal_id: str):
    """El último armado automático de reglas de la señal (o null si nunca hubo)."""
    return armados.leer(senal_id)


class EstadoCodigo(BaseModel):
    donde: Literal["lector", "final"]
    activo: bool


@api.post("/senales/{senal_id}/codigo", dependencies=[Depends(auth.solo_admin)])
def prender_o_apagar_codigo(senal_id: str, datos: EstadoCodigo, u: auth.Usuario = Depends(auth.usuario_actual)):
    """El admin apaga (o vuelve a prender) el código que escribió el agente para la señal."""
    receta = _receta(senal_id)
    if datos.donde == "lector":
        if receta.entrada.tipo != "codigo":
            raise HTTPException(404, "La señal no tiene lector en código")
        lector = receta.entrada.lector.model_copy(update={"activo": datos.activo})
        receta = receta.model_copy(update={"entrada": receta.entrada.model_copy(update={"lector": lector})})
    else:
        if receta.final is None:
            raise HTTPException(404, "La señal no tiene paso final en código")
        receta = receta.model_copy(update={"final": receta.final.model_copy(update={"activo": datos.activo})})
    almacen.guardar(receta, u.usuario)
    return {"ok": True, "activo": datos.activo}


class PedidoArmado(BaseModel):
    pedido: str = ""  # qué le falta a la señal, si la persona lo dijo


@api.post("/senales/{senal_id}/reglas/armar")
def armar_reglas(senal_id: str, datos: PedidoArmado | None = None, u: auth.Usuario = Depends(auth.usuario_actual)):
    """El agente deja la señal igual a sus ejemplos, en segundo plano; el estado se consulta en /reglas/armado."""
    _receta(senal_id)
    if cliente.proveedor_configurado() is None:
        raise HTTPException(503, "El asistente no está configurado: falta la variable ANTHROPIC_API_KEY en el servidor")
    if not almacen.listar_ejemplos(senal_id):
        raise HTTPException(422, "La señal no tiene ejemplos para armar las reglas")
    pedido = (datos.pedido if datos else "").strip()
    armados.lanzar(senal_id, u.usuario, pedido)
    _avisar_del_agente(u, senal_id, f"le pidió al agente: {pedido}" if pedido else "pidió armar las reglas desde los ejemplos")
    return armados.leer(senal_id)


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
async def crear_senal(nombre: str = Form(""), grilla_cruda: UploadFile | None = File(None),
                      grillas: list[UploadFile] | None = File(None), url: str = Form(""), ejemplo: UploadFile | None = File(None),
                      agregar_a: str | None = Form(None), confirmar: bool = Form(False),
                      u: auth.Usuario = Depends(auth.usuario_actual)):
    """Crea una señal a partir de la grilla como viene y el EPG terminado (macro hecha), si lo hay.

    Sin ejemplo, la grilla queda como semana abierta y el agente pregunta lo que necesita. Si ya hay señales con un nombre igual o parecido responde 409 con la lista, para que la persona
    confirme (`confirmar`) o sume el par como ejemplo de una de ellas (`agregar_a`).
    """
    nombre = " ".join(nombre.split())
    if not agregar_a and not nombre:
        raise HTTPException(422, "Escribí el nombre de la señal")
    crudo, nombre_grilla = await _grilla_que_vino(grilla_cruda, grillas or [], url)
    terminado = await _leer_archivo(ejemplo) if ejemplo else None
    if terminado is None and agregar_a:
        raise HTTPException(422, "Para sumar un ejemplo a una señal hace falta el EPG terminado")
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
            entrada = _con_epg(_detectar(crudo), crudo)
            if entrada.tipo == "html" and url.strip():
                entrada = entrada.model_copy(update={"url": url.strip()})
            receta = m.Senal(id=senal_id, nombre=nombre, entrada=entrada,
                             tarjetas=[], salida=m.Salida(columnas=[]))
            almacen.guardar(receta, u.usuario)
        existentes, base, n = set(almacen.listar_ejemplos(senal_id)), sello, 2
        while sello in existentes:  # dos ejemplos subidos en el mismo segundo
            sello, n = f"{base}-{n}", n + 1
        if terminado is not None:
            almacen.guardar_ejemplo(senal_id, sello, crudo, terminado, u.usuario)
    except almacen.NoExiste:
        raise HTTPException(404, "No existe la señal")
    except ValueError as e:
        raise HTTPException(422, str(e))
    try:
        esperado = pd.read_excel(io.BytesIO(terminado), dtype=object) if terminado else None
    except Exception:
        esperado = None
    leida, agente = _leer_con_agente(receta, crudo, esperado, u.usuario,
                                     motivo=None if agregar_a else "es una señal nueva")
    if leida is not receta:
        almacen.guardar(leida, "agente")
        receta = leida
    tabla_id = tablas.subir(crudo)
    resultado = {"id": senal_id, "nombre": receta.nombre, "ejemplo": sello if terminado else None, "tabla_id": tabla_id,
                 "pautas": _cargar_pautas(senal_id, crudo, terminado, u.usuario) if terminado else None,
                 "semana_abierta": False, "sin_ejemplo": terminado is None,
                 "aviso": _aviso_sin_horario(agente) if _sin_horario(crudo, receta) else None,
                 "lectura_agente": agente}
    if not agregar_a and (terminado is None or _es_de_ahora(terminado, receta)):
        semanas.abrir(senal_id, tabla_id, crudo, nombre_grilla, u.usuario, es_version=False)
        resultado["semana_abierta"] = True
    resultado["armando_reglas"] = _armar_si_no_tiene(senal_id, u.usuario)
    return resultado


async def _grilla_que_vino(una: UploadFile | None, varias: list[UploadFile], url: str) -> tuple[bytes, str]:
    """La grilla de una señal nueva: un archivo, varios que se leen juntos (o un zip), o la página bajada del link."""
    if una is not None:
        return await _leer_archivo(una), una.filename or "grilla"
    if len(varias) == 1:
        return await _leer_archivo(varias[0]), varias[0].filename or "grilla"
    if varias:
        contenido = inputs_varios.empaquetar([(a.filename or "archivo", await _leer_archivo(a)) for a in varias])
        return contenido, f"{len(varias)} archivos ({', '.join(a.filename or '' for a in varias)})"[:200]
    if url.strip():
        try:
            return web.bajar(url), url.strip()[:200]
        except web.NoSePudo as e:
            raise HTTPException(422, str(e))
    raise HTTPException(422, "Subí la grilla como vino, o pegá su link")


def _aviso_sin_horario(agente: dict | None) -> str:
    motivo = " ".join((agente or {}).get("problemas") or ["El agente no está configurado."])
    return (f"No encontré la fecha y la hora en la grilla, y el agente tampoco: {motivo} Así no se puede emparejar "
            "con el ejemplo ni armar la semana. Pasame el archivo para sumar cómo se lee.")


def _leer_con_agente(receta: m.Senal, contenido: bytes, esperado: pd.DataFrame | None, usuario: str,
                     motivo: str | None = None, anterior: bytes | None = None) -> tuple[m.Senal, dict | None]:
    """El agente revisa cómo leyó el código la grilla y la deja o la cambia; None si no hizo falta mirarla.

    Se le pide con `motivo` (una señal nueva, otro formato) o si la lectura se ve mal (`_motivo_para_revisar`).
    """
    if receta.entrada.tipo == "codigo" and receta.entrada.lector.activo:
        return receta, None  # el lector en código lo cambia el agente de la señal, contra un ejemplo
    motivo = motivo or _motivo_para_revisar(receta, contenido, anterior)
    if motivo is None:
        return receta, None
    proveedor = cliente.proveedor_configurado()
    if proveedor is None:
        if not _sin_horario(contenido, receta):
            return receta, None  # se lee bien y no hay quién la revise: nada que contar
        return receta, {"logrado": False, "motivo": motivo,
                        "problemas": ["El agente no está configurado (falta ANTHROPIC_API_KEY)."]}
    try:
        intentos = lectura.buscar(contenido, proveedor, esperado, codigo=receta.entrada, motivo=motivo)
    except cliente.ErrorAgente as e:
        return receta, {"logrado": False, "motivo": motivo, "problemas": [str(e)]}
    for p in intentos:
        uso.registrar(usuario, receta.id, "[lectura]", p.vueltas, p.tokens_entrada, p.tokens_salida, p.logrado,
                      p.modelo)
    final = intentos[-1]
    info = {"logrado": final.logrado, "acepto": final.acepto, "motivo": motivo, "modelo": final.modelo,
            "explicacion": final.explicacion, "problemas": final.problemas[:3]}
    if final.logrado and not final.acepto:
        receta = receta.model_copy(update={"entrada": lectura.ENTRADA.validate_python(final.entrada)})
    return receta, info


def _otro_formato(anterior: bytes | None, detectada) -> bool:
    """Si la detección ve este archivo distinto que el de la semana anterior (la lectura guardada puede ser del agente)."""
    if anterior is None:
        return False
    try:
        return not inputs.mismo_formato(inputs.detectar(anterior), detectada)
    except Exception:
        return False


# Menos de esta parte de las filas de la semana anterior hace sospechar que la lectura dejó algo afuera.
FILAS_SOSPECHOSAS = 0.5


def _motivo_para_revisar(receta: m.Senal, contenido: bytes, anterior: bytes | None) -> str | None:
    """Por qué la lectura del código merece que la mire el agente, o None si se ve bien."""
    try:
        tabla = inputs.leer(contenido, receta.entrada)
    except Exception:
        return "el código no pudo leer el archivo"
    if not pautas.tiene_horario(tabla, receta.validaciones):
        if fechar.columna_de_dia(tabla) is not None:
            return None  # semanal con días y sin fechas: se arregla eligiendo el lunes, no con otra lectura
        return "el código no encontró la fecha y la hora"
    e = receta.entrada
    if e.tipo == "excel" and not e.cuadricula:
        try:
            varias = inputs_excel.hojas_de_programacion(contenido)
        except Exception:
            varias = None
        leidas = (tabla.attrs.get("hojas") or 1) + len(tabla.attrs.get("salteadas") or [])
        if varias and leidas < varias[1]:
            return f"leyó {leidas} de las {varias[1]} hojas que parecen programación"
    if anterior is not None:
        try:
            antes = len(inputs.leer(anterior, receta.entrada))
        except Exception:
            antes = 0
        if antes and len(tabla) < antes * FILAS_SOSPECHOSAS:
            return f"salieron {len(tabla)} filas y la semana anterior tenía {antes}"
    return None


def _sin_horario(crudo: bytes, receta: m.Senal) -> bool:
    try:
        return not pautas.tiene_horario(inputs.leer(crudo, receta.entrada), receta.validaciones)
    except Exception:
        return True


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
    base = pautas.base(senal_id)
    vistas = list(dict.fromkeys(c for pauta in base.values() for c in pauta["salida"]))
    cat = catalogo.leer()
    columnas = catalogo.ordenar(vistas, cat) if cat else vistas
    return {"columnas": columnas,
            "programa": semana.columna_programa(columnas, receta.validaciones, semana.pares_de_la_base(base))}


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
    hashes, base = datos.resolver(senal_id), pautas.base(senal_id)
    editadas = pautas.editar_varias(senal_id, hashes, datos.columna, valor, u.usuario)
    historial.anotar(senal_id, u.usuario, "base", [
        {"pauta": h, "programa": _programa_de_pauta(base.get(h)), "columna": datos.columna,
         "antes": base[h]["salida"].get(datos.columna), "despues": valor} for h in hashes if h in base])
    if not _avisar_si_son_muchas(u, senal_id, editadas, f"cambió {datos.columna} en"):
        _avisar_del_agente(u, senal_id, f"cambió {datos.columna} a «{valor}» en "
                                        + ("1 pauta" if editadas == 1 else f"{editadas} pautas"))
    return {"editadas": editadas}


@api.post("/senales/{senal_id}/pautas/olvidar-varias")
def olvidar_varias(senal_id: str, datos: Seleccion):
    return {"olvidadas": pautas.olvidar_varias(senal_id, datos.resolver(senal_id))}


class EdicionPauta(BaseModel):
    salida: dict


@api.put("/senales/{senal_id}/pautas/{h}")
def editar_pauta(senal_id: str, h: str, datos: EdicionPauta, u: auth.Usuario = Depends(auth.usuario_actual)):
    cat = catalogo.leer()
    salida = {c: _convertir(v, c, cat) if isinstance(v, str) else v for c, v in datos.salida.items()}
    antes = pautas.leer(senal_id, h)
    if antes is None or not pautas.editar(senal_id, h, salida, u.usuario):
        raise HTTPException(404, "No existe esa pauta")
    historial.anotar(senal_id, u.usuario, "base", [
        {"pauta": h, "programa": _programa_de_pauta({"salida": salida}), "columna": col,
         "antes": antes["salida"].get(col), "despues": v}
        for col, v in salida.items() if pautas.normalizar(v) != pautas.normalizar(antes["salida"].get(col))])
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
    h = c.hashes[fila]
    if h.startswith(pautas.GENERADA):
        raise HTTPException(422, "Esta fila la agrega el paso final en código: no viene de la grilla y no se corrige en la base")
    salida = {col: pautas.valor_json(c.salida.iloc[fila][col]) for col in contenido}
    antes = salida.get(columna)
    salida[columna] = _convertir(valor, columna, c.catalogo)
    pautas.guardar(senal_id, {h: {"crudo": c.crudas[fila], "salida": salida}}, "editada", usuario, pisar=True)
    historial.anotar(senal_id, usuario, "corregida", [{"pauta": h, "programa": salida.get(c.programa), "columna": columna,
                                                       "antes": antes, "despues": salida[columna]}])
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


def _guardar_nuevas(senal_id: str, p: Pedido, usuario: str, solo: set[str] | None = None,
                    tipo: str | None = None) -> int:
    """Pasa a la base, como revisadas, las pautas nuevas de la grilla tal como las arman hoy las reglas.

    Con `tipo` ("aceptada" o "confirmada"), cada una queda en el historial.
    """
    c = _correr(p)
    contenido = pautas.columnas_de_contenido(c.salida, p.senal.validaciones)
    nuevas = {}
    for i, estado in enumerate(c.estados):
        h = c.hashes[i]
        if estado == "nueva" and h not in nuevas and (solo is None or h in solo):
            nuevas[h] = {"crudo": c.crudas[i],
                         "salida": {col: pautas.valor_json(c.salida.iloc[i][col]) for col in contenido}}
    guardadas = pautas.guardar(senal_id, nuevas, "revisada", usuario)
    if tipo:
        historial.anotar(senal_id, usuario, tipo, [{"pauta": h, "programa": x["salida"].get(c.programa)}
                                                   for h, x in nuevas.items()])
    return guardadas


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


def _con_entrada(receta: m.Senal, detectada, contenido: bytes, esperado=None) -> m.Senal:
    """Si la grilla llegó en otro formato que la anterior, la señal pasa a leerla así.

    Salvo que la lectura guardada ya le encuentre fecha y hora: puede ser la del agente, que la detección no ve.
    Si el libro trae la misma grilla en varias zonas horarias, se queda con la del último ejemplo de la señal
    (o con `esperado`, si se lo pasan).
    """
    entrada = receta.entrada
    if entrada.tipo == "codigo" and entrada.lector.activo:
        return receta  # si no puede con la grilla, que se vea el error: lo cambia el agente o lo apaga el admin
    if not inputs.mismo_formato(entrada, detectada) and _sin_horario(contenido, receta):
        entrada = detectada
    elif entrada.tipo == "texto" and entrada.fecha_inicio != detectada.fecha_inicio:
        entrada = entrada.model_copy(update={"fecha_inicio": detectada.fecha_inicio})
    elif entrada.tipo == "excel" and not entrada.cuadricula:
        sola = inputs.con_alternativa(contenido, entrada,
                                      esperado if esperado is not None else lambda: _ultimo_esperado(receta.id))
        entrada = sola if sola is not entrada else inputs.con_todas_las_hojas(entrada, detectada)
    return receta if entrada is receta.entrada else receta.model_copy(update={"entrada": entrada})


def _ultimo_esperado(senal_id: str) -> bytes | None:
    """El EPG terminado del ejemplo más reciente de la señal, si tiene."""
    try:
        nombres = almacen.listar_ejemplos(senal_id)
        return almacen.leer_ejemplo(senal_id, nombres[-1])[1] if nombres else None
    except (almacen.NoExiste, ValueError):
        return None


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
    nueva = _con_entrada(receta, detectada, contenido)
    if nueva.entrada.tipo == "html" and receta.entrada.tipo != "html":
        nueva = nueva.model_copy(update={"entrada": _con_epg(nueva.entrada, contenido)})
    anterior = semanas.contenido(receta.id)
    nueva, agente = _leer_con_agente(nueva, contenido, None, usuario, anterior=anterior,
                                     motivo="llegó en otro formato que la semana anterior"
                                     if _otro_formato(anterior, detectada) else None)
    try:
        inputs.leer(contenido, nueva.entrada)
    except Exception as e:
        motivo = f" El agente tampoco pudo: {' '.join(agente['problemas'])}" if agente else ""
        if nueva.entrada.tipo == "codigo":
            motivo = (" Si cambió el formato, pedile al agente que actualice el lector con un ejemplo de esta semana, "
                      "o que el admin lo apague en Configuración › Lectura.")
        raise HTTPException(422, f"No se pudo leer la grilla: {e}.{motivo}")
    tabla_id = tablas.subir(contenido)
    fechas = _fechas(_correr(Pedido(tabla_id=tabla_id, senal=nueva)).salida, nueva)
    version = semanas.es_version(fechas["desde"], fechas["hasta"], semanas.leer(receta.id))
    if nueva is not receta:
        almacen.guardar(nueva, usuario)
    semanas.abrir(receta.id, tabla_id, contenido, nombre, usuario, version)
    abierta = _semana_abierta(receta.id, nueva)
    aviso = fechar.aviso(inputs.leer(contenido, nueva.entrada), fechas["desde"], fechas["hasta"])
    return {**abierta, "armando_reglas": _armar_si_no_tiene(receta.id, usuario), "lectura_agente": agente,
            "aviso_fechas": aviso}


NOMBRES_HORARIO = {"fecha": "fecha", "hora": "hora", "duracion": "duración"}


def _faltan_horario(salida: pd.DataFrame, receta: m.Senal) -> list[str]:
    """Qué le falta al EPG para validar horarios (fecha, hora, duración): lo tienen que armar las reglas."""
    cols = grilla.detectar_columnas(list(salida.columns), receta.validaciones)
    cols = {**pautas.columnas_por_tipo(salida), **{k: v for k, v in cols.items() if v}}
    return [NOMBRES_HORARIO[k] for k in NOMBRES_HORARIO if not cols.get(k) or cols[k] not in salida.columns]


def _fechas(salida: pd.DataFrame, receta: m.Senal) -> dict:
    col = (grilla.detectar_columnas(list(salida.columns), receta.validaciones).get("fecha")
           or pautas.columnas_por_tipo(salida).get("fecha"))
    if not col or col not in salida.columns:
        return {"desde": None, "hasta": None}
    fechas = [f for v in salida[col] if (f := a_fecha(v))]
    if not fechas:
        return {"desde": None, "hasta": None}
    return {"desde": min(fechas).isoformat(), "hasta": max(fechas).isoformat()}


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
async def abrir_semana(senal_id: str, archivo: UploadFile | None = File(None), archivos: list[UploadFile] | None = File(None),
                       u: auth.Usuario = Depends(auth.usuario_actual)):
    """La grilla de la semana: un archivo, o varios que se leen juntos como una sola semana."""
    receta = _receta(senal_id)
    subidos = [archivo] if archivo else (archivos or [])
    if not subidos:
        raise HTTPException(422, "Subí la grilla")
    if len(subidos) == 1:
        contenido, nombre = await _leer_archivo(subidos[0]), subidos[0].filename or "grilla"
    else:
        contenido = inputs_varios.empaquetar([(a.filename or "archivo", await _leer_archivo(a)) for a in subidos])
        nombre = f"{len(subidos)} archivos ({', '.join(a.filename or '' for a in subidos)})"[:200]
    return _abrir(receta, contenido, _detectar(contenido), nombre, u.usuario)


class Link(BaseModel):
    url: str


@api.post("/senales/{senal_id}/abierta/url")
def abrir_semana_url(senal_id: str, datos: Link, u: auth.Usuario = Depends(auth.usuario_actual)):
    """La página de la señal bajada desde su link; el link queda en la señal para la semana siguiente."""
    receta = _receta(senal_id)
    try:
        contenido = web.bajar(datos.url)
    except web.NoSePudo as e:
        raise HTTPException(422, str(e))
    detectada = _detectar(contenido)
    if detectada.tipo == "html":
        detectada = detectada.model_copy(update={"url": datos.url.strip()})
        if receta.entrada.tipo == "html" and receta.entrada.url != detectada.url:
            receta = receta.model_copy(update={"entrada": receta.entrada.model_copy(update={"url": detectada.url})})
            almacen.guardar(receta, u.usuario)
    return _abrir(receta, contenido, detectada, datos.url.strip()[:200], u.usuario)


class Lunes(BaseModel):
    lunes: dt.date | None  # None = las fechas como vinieron


@api.post("/senales/{senal_id}/abierta/fechar")
def fechar_abierta(senal_id: str, datos: Lunes):
    """Pasa la semana abierta (semanal sin fechas, o con fechas viejas) a la semana de ese lunes."""
    receta = _receta(senal_id)
    if semanas.leer(senal_id) is None:
        raise HTTPException(404, "Esta señal no tiene una semana abierta: subí la grilla")
    semanas.fijar_lunes(senal_id, datos.lunes)
    return _semana_abierta(senal_id, receta)


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
    _guardar_nuevas(senal_id, p, u.usuario, set(datos.hashes), tipo="aceptada")
    return _semana_abierta(senal_id, receta)


@api.delete("/senales/{senal_id}/abierta")
def borrar_abierta(senal_id: str):
    """La grilla subida por error: vuelve la versión anterior de la semana, o la señal queda sin grilla."""
    receta = _receta(senal_id)
    semanas.borrar(senal_id)
    return _semana_abierta(senal_id, receta)


@api.post("/senales/{senal_id}/abierta/confirmar")
def confirmar_abierta(senal_id: str, u: auth.Usuario = Depends(auth.usuario_actual)):
    receta, p = _pedido_abierta(senal_id)
    if not _guardar_nuevas(senal_id, p, u.usuario, tipo="confirmada"):
        historial.anotar(senal_id, u.usuario, "confirmada", [{"programa": "Semana confirmada sin pautas nuevas"}])
    semanas.confirmar(senal_id, u.usuario)
    _avisar_del_agente(u, senal_id, "confirmó la semana")
    confianza.al_confirmar(receta, p.tabla_id)
    return {**_semana_abierta(senal_id, receta), "propuestas_reglas": len(confianza.propuestas(receta))}


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


# --- Después de corregir: las otras filas donde vale el mismo arreglo ---

class Correccion(BaseModel):
    columna: str
    antes: object = None
    despues: object = None


class CorreccionEnSemana(Correccion):
    fila: int


class CambioPauta(BaseModel):
    hash: str
    columna: str
    valor: object = None


class CambioFila(BaseModel):
    fila: int
    columna: str
    valor: object = None


def _filtrar_parecidas(senal_id: str, datos: Correccion, candidatas: list, u: auth.Usuario) -> list[dict]:
    r = parecidas_ia.filtrar(datos.columna, datos.antes, datos.despues, candidatas, cliente.proveedor_configurado())
    if r is not None:
        uso.registrar(u.usuario, senal_id, "[parecidas]", 1, r.tokens_entrada, r.tokens_salida, True, r.modelo)
    return [p.json() for p in candidatas]


@api.post("/senales/{senal_id}/pautas/{h}/parecidas")
def parecidas_en_base(senal_id: str, h: str, datos: Correccion, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Otras pautas de la base donde se puede hacer el mismo arreglo que se le hizo a `h`."""
    receta, base = _receta(senal_id), pautas.base(senal_id)
    columnas = sorted({c for p in base.values() for c in p["salida"]})
    programa = semana.columna_programa(columnas, receta.validaciones, semana.pares_de_la_base(base))
    filas = [(clave, p["salida"]) for clave, p in base.items()]
    return _filtrar_parecidas(senal_id, datos, parecidas.buscar(filas, datos.columna, datos.antes, datos.despues,
                                                                programa, h), u)


@api.post("/senales/{senal_id}/pautas/aplicar")
def aplicar_en_base(senal_id: str, cambios: list[CambioPauta], u: auth.Usuario = Depends(auth.usuario_actual)):
    cat = catalogo.leer()
    lista = [(c.hash, c.columna, _convertir(c.valor, c.columna, cat) if isinstance(c.valor, str) else c.valor)
             for c in cambios]
    base = pautas.base(senal_id)
    aplicadas = pautas.editar_celdas(senal_id, lista, u.usuario)
    historial.anotar(senal_id, u.usuario, "base", [
        {"pauta": h, "programa": _programa_de_pauta(base.get(h)), "columna": col,
         "antes": (base.get(h) or {}).get("salida", {}).get(col), "despues": v} for h, col, v in lista if h in base])
    _avisar_si_son_muchas(u, senal_id, aplicadas, "corrigió de una vez en la Base")
    return {"aplicadas": aplicadas}


def _programa_de_pauta(pauta: dict | None):
    """Para mostrar en el historial: el primer texto de la pauta (casi siempre el programa)."""
    salida = (pauta or {}).get("salida", {})
    return next((v for v in salida.values() if isinstance(v, str) and v.strip()), None)


@api.post("/senales/{senal_id}/abierta/parecidas")
def parecidas_en_semana(senal_id: str, datos: CorreccionEnSemana, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Otras filas de la semana (una por pauta) donde se puede hacer el mismo arreglo que en `fila`."""
    receta, p = _pedido_abierta(senal_id)
    c = _correr(p)
    contenido = pautas.columnas_de_contenido(c.salida, receta.validaciones)
    vistas, filas = {c.hashes[datos.fila] if 0 <= datos.fila < len(c.hashes) else None}, []
    for i, h in enumerate(c.hashes):
        if h not in vistas:
            vistas.add(h)
            filas.append((str(i), {col: pautas.valor_json(c.salida.iloc[i][col]) for col in contenido}))
    return _filtrar_parecidas(senal_id, datos, parecidas.buscar(filas, datos.columna, datos.antes, datos.despues,
                                                                c.programa, str(datos.fila)), u)


@api.post("/senales/{senal_id}/abierta/aplicar")
def aplicar_en_semana(senal_id: str, cambios: list[CambioFila], u: auth.Usuario = Depends(auth.usuario_actual)):
    """Corrige varias celdas de la semana de una vez: cada pauta queda así en la base."""
    receta, p = _pedido_abierta(senal_id)
    c = _correr(p)
    contenido = pautas.columnas_de_contenido(c.salida, receta.validaciones)
    por_fila: dict[int, dict] = {}
    for x in cambios:
        if x.columna not in contenido or not 0 <= x.fila < len(c.salida) or c.hashes[x.fila].startswith(pautas.GENERADA):
            raise HTTPException(422, f"No se puede corregir {x.columna} en la fila {x.fila + 1}")
        valor = _convertir(x.valor, x.columna, c.catalogo) if isinstance(x.valor, str) else x.valor
        por_fila.setdefault(x.fila, {})[x.columna] = valor
    nuevas, anotadas = {}, []
    for fila, valores in por_fila.items():
        antes = {col: pautas.valor_json(c.salida.iloc[fila][col]) for col in contenido}
        salida = antes | valores
        nuevas[c.hashes[fila]] = {"crudo": c.crudas[fila], "salida": salida}
        anotadas += [{"pauta": c.hashes[fila], "programa": salida.get(c.programa), "columna": col, "antes": antes.get(col),
                      "despues": v} for col, v in valores.items()]
    pautas.guardar(senal_id, nuevas, "editada", u.usuario, pisar=True)
    historial.anotar(senal_id, u.usuario, "corregida", anotadas)
    _avisar_si_son_muchas(u, senal_id, len(nuevas), "corrigió de una vez")
    return {"aplicadas": len(nuevas)}


# Más pautas que esto cambiadas de una sola vez por alguien que no es admin: le llega un aviso al admin.
MUCHAS_PAUTAS = 20


def _avisar_si_son_muchas(u: auth.Usuario, senal_id: str, cuantas: int, que: str) -> bool:
    if u.admin or cuantas <= MUCHAS_PAUTAS:
        return False
    conversaciones.avisar(u.usuario, senal_id, "base", f"{que} {cuantas} pautas")
    return True


class PedidoArreglo(BaseModel):
    codigo: str  # catalogo:<columna> | vacia:<columna> | sinopsis_repetida
    hashes: list[str]
    valor: str | None = None  # para completar una columna vacía


@api.post("/senales/{senal_id}/abierta/arreglo")
def arreglo_rapido(senal_id: str, datos: PedidoArreglo):
    """Lo que haría el arreglo rápido de un grupo de motivos, pauta por pauta, para confirmarlo en el recorrido."""
    receta, p = _pedido_abierta(senal_id)
    c = _correr(p)
    contenido = pautas.columnas_de_contenido(c.salida, receta.validaciones)
    elegidas, filas = set(datos.hashes), []
    for i, h in enumerate(c.hashes):
        if h in elegidas:
            elegidas.discard(h)
            filas.append((str(i), {col: pautas.valor_json(c.salida.iloc[i][col]) for col in contenido}))
    tipo, _, columna = datos.codigo.partition(":")
    if tipo == "catalogo":
        col = next((x for x in c.catalogo if catalogo.clave(x.nombre) == catalogo.clave(columna)), None)
        if col is None:
            raise HTTPException(422, f"{columna} no está en el catálogo")
        lista = arreglos.del_catalogo(filas, columna, col, c.programa)
    elif tipo == "vacia":
        if not (datos.valor or "").strip():
            raise HTTPException(422, f"Escribí con qué completar {columna}")
        lista = arreglos.completar(filas, columna, _convertir(datos.valor, columna, c.catalogo), c.programa)
    elif tipo == "sinopsis_repetida":
        sinopsis = next((x for x in contenido if catalogo.clave(x).startswith("sin")), None)
        argumento = next((x for x in contenido if catalogo.clave(x).startswith("arg")), None)
        if not sinopsis or not argumento:
            raise HTTPException(422, "No hay una columna de argumento de programa (ARG) adonde pasar la sinopsis")
        lista = arreglos.a_argumento(filas, sinopsis, argumento, c.programa)
    else:
        raise HTTPException(422, "Ese motivo no tiene arreglo rápido")
    return [x.json() for x in lista]


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


@api.post("/senales/{senal_id}/reglas/criterios")
def sumar_criterios(senal_id: str, u: auth.Usuario = Depends(auth.usuario_actual)):
    """Pone los criterios generales al principio de las reglas, configurados con el ejemplo más reciente.

    Se guarda solo si ningún ejemplo empeora; si no, se devuelve cuánto daba para que la persona decida.
    """
    receta = _receta(senal_id)
    if any(t.tipo == "criterios" for t in receta.tarjetas):
        raise HTTPException(409, "La señal ya usa los criterios generales")
    nombres = list(reversed(almacen.listar_ejemplos(senal_id)))[:3]
    if not nombres:
        raise HTTPException(422, "Hace falta un ejemplo para saber a qué columnas va cada cosa")
    ejemplos = [_leer_ejemplo(receta, n) for n in nombres]
    nueva = asistente_ia.con_criterios(receta, ejemplos[0].entrada, ejemplos, ejemplos[0].nombre)
    if nueva is None:
        raise HTTPException(422, "No encontré la columna del título en la grilla del ejemplo")
    antes, _ = asistente_ia.medir(receta, ejemplos[0].entrada, ejemplos)
    despues, _ = asistente_ia.medir(nueva, ejemplos[0].entrada, ejemplos)
    empeora = [n for n in antes.ejemplos if despues.ejemplos[n] < antes.ejemplos[n]]
    if not empeora:
        almacen.guardar(nueva, u.usuario)
    return {"aplicado": not empeora, "antes": antes.ejemplos, "despues": despues.ejemplos,
            "tarjeta": nueva.tarjetas[0].model_dump(exclude_none=True)}


@api.post("/senales/{senal_id}/ejemplos/evaluar")
def evaluar_ejemplos(senal_id: str, receta: m.Senal):
    """Corre la receta (aunque no esté guardada) contra cada ejemplo de la señal."""
    receta = _solo_codigo_guardado(receta)
    try:
        nombres = almacen.listar_ejemplos(senal_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    resultados = []
    for nombre in nombres:
        entrada, esperado_xlsx = almacen.leer_ejemplo(senal_id, nombre)
        try:
            tabla = inputs.leer_ejemplo(entrada, receta.entrada, esperado_xlsx)
            salida, _ = correr(receta, tabla)
            esperado = pd.read_excel(io.BytesIO(esperado_xlsx), dtype=object)
        except Exception as e:
            resultados.append({"nombre": nombre, "error": f"No se pudo correr: {e}"})
            continue
        pares = controles.pares_con_ejemplo(tabla if len(salida) == len(tabla) else salida, esperado)
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
    senal: m.Senal | None = None  # sin señal abierta, el agente solo charla y propone acciones en la página
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
    if p.senal is not None:
        p.senal = _solo_codigo_guardado(p.senal)
    tabla = _correr_tabla(p.tabla_id, p.senal) if p.tabla_id and p.senal else None
    try:
        c = asistente_ia.charlar(p.senal, tabla, [h.model_dump() for h in p.historial], p.pedido_con_contexto(),
                                 proveedor, _persona(u))
    except cliente.ErrorAgente as e:
        raise HTTPException(502, str(e))
    if c.recordar:
        conversaciones.anotar(u.usuario, c.recordar)
    uso.registrar(u.usuario, p.senal.id if p.senal else "", "[charla] " + p.pedido, c.pasos, c.tokens_entrada,
                  c.tokens_salida, True, c.modelo)
    return asdict(c)


def _persona(u: auth.Usuario) -> asistente_ia.Persona:
    ficha = auth.perfiles().get(u.usuario, {})
    return asistente_ia.Persona(u.usuario, u.admin, ficha.get("nombre", ""), ficha.get("descripcion", ""),
                                [n["texto"] for n in conversaciones.notas(u.usuario)],
                                [(s["id"], s["nombre"]) for s in almacen.listar()])


@api.post("/asistente")
def asistente(p: PedidoAsistente, u: auth.Usuario = Depends(auth.usuario_actual)):
    if p.senal is None:
        raise HTTPException(422, "Abrí una señal para que el agente arme cambios sobre ella")
    proveedor = _proveedor_disponible(u, p.pedido)
    p.senal = _solo_codigo_guardado(p.senal)

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
    elif p.tabla_id or (abierta := semanas.leer(p.senal.id)):
        # Sin tabla_id (una propuesta para otra señal que la de la pantalla), la de su semana abierta.
        p.tabla_id = p.tabla_id or abierta["tabla_id"]
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
    pasos: list[str] = list(banco.POR_DEFECTO)


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
    if proveedor is None and not set(pasos) <= banco.SIN_AGENTE:
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


@api.get("/admin/caja", dependencies=[Depends(auth.solo_admin)])
def estado_de_la_caja():
    """La última autoprueba de la caja en este servidor: si el código de las señales puede correr y por qué."""
    return autoprueba.estado()


@api.post("/admin/caja/probar", dependencies=[Depends(auth.solo_admin)])
def probar_la_caja():
    autoprueba.en_segundo_plano()
    return autoprueba.estado()


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
    return asistente_ia.Ejemplo(nombre, inputs.leer_ejemplo(entrada, receta.entrada, esperado),
                                pd.read_excel(io.BytesIO(esperado), dtype=object))


def _correr_tabla(tabla_id: str | None, receta: m.Senal) -> pd.DataFrame:
    if not tabla_id:
        raise HTTPException(422, "Subí una grilla antes de pedirle algo al asistente")
    try:
        return tablas.tabla(tabla_id, receta.entrada)
    except KeyError:
        raise HTTPException(410, "El archivo ya no está en memoria: volvé a subirlo")
