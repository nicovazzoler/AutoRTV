# AutoRTV

Convierte grillas de programación de TV (Excel, HTML, PDF) en un EPG normalizado usando
**tarjetas**: reglas chicas y editables sin código (separar, reemplazar, quitar, duración…)
que se aplican en orden, con vista previa en vivo en la web.

## Qué hace

- **Señales:** cada una tiene su receta de tarjetas, su vista previa y validaciones de grilla
  (huecos, superposiciones, días de 24 h, duraciones de más de 720 min).
- **Nueva señal:** se crea con nombre, la grilla cruda y la macro hecha (el EPG terminado). Si ya
  hay una señal con un nombre igual o parecido, pide confirmación.
- **Base de pautas:** cada fila cruda sin fecha, hora ni duración se reconoce cuando vuelve. Lo que
  se corrigió a mano (doble clic en la tabla o en la pestaña Base) queda corregido las próximas
  semanas. La base se carga sola con los ejemplos.
- **Catálogo de columnas:** el admin sube el Excel con el orden y las reglas de cada columna (largo
  máximo, números, valores permitidos, obligatorias según los idiomas de la señal).
- **Reglas:** la receta se lee como frases, con un interruptor por regla.
- **Ejemplos:** pares "como vino → como quedó". La receta se prueba contra ellos y sugiere
  correcciones.
- **Asistente:** se le pide en castellano y propone cambios en las tarjetas (ver abajo).

### Roles

- **Admin:** pestaña Admin (usuarios, catálogo, uso del asistente), editor de tarjetas,
  validaciones y exportar/importar receta.
- **Resto:** trabaja con el asistente y las pestañas Tabla, Reglas, Base y Ejemplos.

## Correr local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
ADMIN_USUARIO=admin ADMIN_CLAVE=una-clave-larga .venv/bin/uvicorn app.main:app --reload
```

Abrir http://127.0.0.1:8000. El admin se crea solo la primera vez (si no hay usuarios). Los demás
usuarios se crean desde la pestaña **Admin**.

## Tests

```bash
.venv/bin/python -m pytest                                    # SQLite temporal
DATABASE_URL=postgresql://usuario@host/base .venv/bin/python -m pytest   # Postgres real
CHROMIUM=/ruta/a/chrome .venv/bin/python -m pytest tests/e2e  # navegador real (Playwright)
```

- Contra Postgres, las tablas se vacían antes de cada test: usar una base solo para eso.
- El test golden de Concert Channel corre solo si existe `privado/`.

## Deploy en Railway

1. **New Project → Deploy from GitHub repo**, con este repo (usa el `Dockerfile`).
2. **New → Database → Add PostgreSQL**. En el servicio de la app → **Variables**:
   `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`.
3. Variables `ADMIN_USUARIO` y `ADMIN_CLAVE` (solo se usan si todavía no hay usuarios) y
   `ANTHROPIC_API_KEY` para el asistente.
4. **Settings → Networking → Generate Domain**.

Un volumen en `/data` solo hace falta para migrar datos del formato anterior (ver Datos).

### Variables

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | Postgres. Sin ella, SQLite en `DATA_DIR`. |
| `ADMIN_USUARIO`, `ADMIN_CLAVE` | Primer admin, si no hay usuarios. |
| `ANTHROPIC_API_KEY` | Activa el asistente. Conviene un workspace aparte con límite de gasto. |
| `AGENTE_MODELO` | Modelo de las propuestas (por defecto `claude-opus-5-5`). |
| `AGENTE_MODELO_RAPIDO` | Modelo de la charla (por defecto `claude-haiku-5-5`). |
| `AGENTE_LIMITE_DIARIO` | Pedidos al asistente por persona por día (por defecto 50). |
| `COOKIE_SEGURA` | `1`/`0` fuerza la cookie solo-HTTPS. En Railway se activa sola. |
| `DATA_DIR` | Carpeta de SQLite y del formato anterior (por defecto `datos/`). |

## Asistente (IA)

- Cada mensaje va primero a Claude Haiku: si es una pregunta o charla, responde ahí mismo.
- Si pide cambiar reglas o columnas, el pedido pasa a Claude Opus, que propone tarjetas, las prueba
  contra la grilla y los ejemplos, y corrige hasta 3 veces. El botón **Proponer cambios** va
  directo a Opus.
- Nunca aplica nada solo: la persona ve los cambios y el % de los ejemplos, y decide.
- Se reenvían los últimos 10 mensajes de la conversación. A Claude le llega solo la señal abierta,
  15 filas de muestra y esa conversación.
- Las charlas cuentan en el tope diario.
- Sin key, el asistente aparece como "no configurado". Los tests usan respuestas grabadas
  (`AGENTE_FALSO`) y no gastan.

## Datos

- Con `DATABASE_URL` todo vive en la base: usuarios, sesiones, recetas con su historial,
  ejemplos, base de pautas, catálogo, grillas subidas y uso del asistente.
  - Las grillas subidas se borran a las 24 h.
  - La app no guarda nada propio, así que se puede correr con más de una réplica.
- Sin `DATABASE_URL`, usa SQLite en `DATA_DIR/autortv.db`: para uso local y tests.
- **Migración automática:** al arrancar con la base vacía, copia lo que haya en `DATA_DIR` con el
  formato anterior (`app.db` + `senales/<id>/`). Los usuarios conservan su clave. La primera vez,
  el log muestra "Migradas desde el volumen: N usuarios y M señales".
- Las tablas se crean solas al arrancar. Si más adelante cambian columnas, se suma Alembic.
- `privado/` y `datos/` están en `.gitignore`: las grillas, recetas y el catálogo del laburo no van
  al repo.
