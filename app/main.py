from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import auth, db
from app.api.rutas import api, publico

RAIZ = Path(__file__).resolve().parents[1]
WEB_VIEJA = RAIZ / "web"
WEB = RAIZ / "front" / "dist"


@asynccontextmanager
async def arranque(_app):
    db.motor()  # crea las tablas y migra el volumen viejo antes de atender pedidos
    auth.asegurar_admin_inicial()
    yield


app = FastAPI(title="AutoRTV", lifespan=arranque)
app.include_router(publico)
app.include_router(api)


@app.get("/health")
def health():
    return {"ok": True}


# La web vieja queda en /viejo mientras la nueva no tenga todas las pantallas.
@app.get("/viejo")
def web_vieja():
    return FileResponse(WEB_VIEJA / "index.html")


@app.get("/viejo/login")
def login_viejo():
    return FileResponse(WEB_VIEJA / "login.html")


app.mount("/web", StaticFiles(directory=WEB_VIEJA), name="web")


# La web es estática; los datos los protege /api con la sesión.
@app.get("/{ruta:path}")
def web(ruta: str):
    if ruta == "api" or ruta.startswith("api/"):
        raise HTTPException(404, "No existe")
    if not (WEB / "index.html").exists():
        return HTMLResponse("Falta compilar la web: <code>cd front &amp;&amp; npm ci &amp;&amp; npm run build</code>", 503)
    archivo = (WEB / ruta).resolve()
    if ruta and archivo.is_file() and WEB.resolve() in archivo.parents:
        return FileResponse(archivo)
    # Las rutas de la web (/s/canal/revisar…) las resuelve la propia página.
    return FileResponse(WEB / "index.html")
