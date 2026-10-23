# AutoRTV

Convierte grillas de programación de TV (Excel, HTML, PDF) en un EPG normalizado usando
**tarjetas**: reglas chicas y editables sin código (separar, reemplazar, quitar, duración…)
que se aplican en orden, con vista previa en vivo en la web.

## Correr local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
ADMIN_USUARIO=admin ADMIN_CLAVE=una-clave-larga .venv/bin/uvicorn app.main:app --reload
```

Abrir http://127.0.0.1:8000. El admin se crea solo la primera vez (si no hay usuarios);
los demás usuarios se crean desde la pestaña **Usuarios**.

## Tests

```bash
.venv/bin/python -m pytest
# Prueba en navegador real (necesita `pip install playwright` y un Chromium):
CHROMIUM=/ruta/a/chrome .venv/bin/python -m pytest tests/e2e
```

## Deploy en Railway

1. Crear el servicio desde este repo (usa el `Dockerfile`).
2. Agregar un **volumen** montado en `/data`: ahí quedan usuarios, señales, historial y ejemplos.
3. Variables: `ADMIN_USUARIO` y `ADMIN_CLAVE` (solo se usan si todavía no hay usuarios).

## Datos

- `DATA_DIR` (por defecto `datos/`): `app.db` (usuarios y sesiones) y `senales/<id>/`
  con la receta, su historial y los ejemplos antes/después.
- `privado/` y `datos/` están en `.gitignore`: las grillas y recetas del laburo no van al repo.
