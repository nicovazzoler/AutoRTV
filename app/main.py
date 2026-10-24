from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import auth, db
from app.api.rutas import api, publico

WEB = Path(__file__).resolve().parents[1] / "web"


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


# La web es estática; los datos los protege /api con la sesión.
@app.get("/")
def inicio():
    return FileResponse(WEB / "index.html")


@app.get("/login")
def pagina_login():
    return FileResponse(WEB / "login.html")


app.mount("/web", StaticFiles(directory=WEB), name="web")
