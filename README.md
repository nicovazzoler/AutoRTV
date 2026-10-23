# AutoRTV

Convierte grillas de programación de TV (Excel, HTML, PDF) en un EPG normalizado usando
**tarjetas**: reglas chicas y editables sin código (separar, reemplazar, quitar, duración…)
que se aplican en orden.

## Correr local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/uvicorn app.main:app --reload
```

`POST /api/preview` recibe un Excel (`archivo`) y una receta (`senal`, JSON) y devuelve la
tabla resultante con un informe por tarjeta. Ver `ejemplos/sintetica.json`.

## Datos privados

Las recetas y grillas del laburo van en `privado/` (ignorado por git). El test golden de
Concert Channel corre solo si existe `privado/concert/`.
