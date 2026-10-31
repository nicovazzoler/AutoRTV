import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from app import auth, corridas, db
from app.api.rutas import api, publico

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "front" / "dist"


@asynccontextmanager
async def arranque(_app):
    db.motor()  # crea las tablas y migra el volumen viejo antes de atender pedidos
    auth.asegurar_admin_inicial()
    corridas.cortar_colgadas()
    yield


app = FastAPI(title="AutoRTV", lifespan=arranque)
app.include_router(publico)
app.include_router(api)


@app.exception_handler(Exception)
async def error_inesperado(pedido: Request, e: Exception):
    """Un bug: la web muestra qué falló, y con el código se encuentra el detalle completo en los logs."""
    codigo = "E-" + secrets.token_hex(2)
    logging.getLogger("autortv").exception("%s en %s %s", codigo, pedido.method, pedido.url.path)
    return JSONResponse({"detail": f"Error interno {codigo}: {type(e).__name__}: {e}"[:500]}, status_code=500)


@app.get("/health")
def health():
    return {"ok": True}


def _con_sesion(token: str | None) -> bool:
    try:
        auth.usuario_actual(token)
        return True
    except HTTPException:
        return False


# La web es estática; los datos los protege /api con la sesión.
@app.get("/{ruta:path}")
def web(ruta: str, autortv_sesion: str | None = Cookie(default=None)):
    if ruta == "api" or ruta.startswith("api/"):
        raise HTTPException(404, "No existe")
    archivo = (WEB / ruta).resolve()
    if ruta and archivo.is_file() and WEB.resolve() in archivo.parents:
        return FileResponse(archivo)  # los archivos de la web (scripts, logo) los necesita también el login
    # Sin sesión no se entrega ninguna pantalla: los datos ya los frena /api, pero así ni se ve el armazón.
    adentro = _con_sesion(autortv_sesion)
    if ruta != "login" and not adentro:
        return RedirectResponse("/login")
    if ruta == "login" and adentro:
        return RedirectResponse("/")
    if not (WEB / "index.html").exists():
        return HTMLResponse("Falta compilar la web: <code>cd front &amp;&amp; npm ci &amp;&amp; npm run build</code>", 503)
    # Las rutas de la web (/s/canal/revisar…) las resuelve la propia página.
    return FileResponse(WEB / "index.html")
