import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.engine import model as m
from app.engine.pipeline import correr
from app.inputs import excel

app = FastAPI(title="AutoRTV")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/preview")
async def preview(archivo: UploadFile = File(...), senal: str = Form(...), filas: int = Form(200)):
    """Corre la receta sobre el Excel subido y devuelve las primeras filas y el informe por tarjeta."""
    try:
        receta = m.Senal.model_validate(json.loads(senal))
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(422, str(e))
    tabla = excel.leer(archivo.file, receta.entrada)
    salida, informes = correr(receta, tabla)
    return {
        "columnas": list(salida.columns),
        "filas": json.loads(salida.head(filas).to_json(orient="records", date_format="iso")),
        "total_filas": len(salida),
        "tarjetas": [vars(i) for i in informes],
    }
