# AutoRTV

Convierte grillas de programación de TV (Excel, PDF, XML, HTML o texto pegado) en un EPG
normalizado. Lo que ya pasó sale de una base; lo nuevo lo arman reglas que propone un agente, y
la web muestra solo lo que hay que mirar.

## Qué hace

- **Inicio:** todas las señales con su semana: cuántas filas hay para revisar, si se confirmó, quién la subió.
- **Subir grilla:** archivo, texto pegado o el HTML de una página. La semana queda guardada para todos.
- **Revisar:** cada fila cae en *de la base*, *nueva lista* (capítulo nuevo de un programa conocido) o
  *para revisar* (programa nuevo, celda fuera del catálogo, horario con error). Se confirma y exporta.
- **Grilla y Base:** la semana fila por fila y todas las pautas guardadas, con filtros. Doble clic
  corrige una celda; en la Base se cambian varias juntas.
- **Señal:** ejemplos "como vino → como quedó" con el % que aciertan las reglas, las reglas como
  frases, deshacer, y (admin) la configuración y exportar o importar la receta.
- **Agente:** panel a la derecha. Charla, propone reglas o correcciones en la base, el servidor las
  prueba y la persona aplica o descarta (ver abajo).
- **Nueva señal:** nombre, la grilla como vino y la macro hecha; la base se carga sola y el agente
  arma las reglas desde el ejemplo.
- **Admin:** usuarios (la clave la genera el servidor), catálogo de columnas y gasto del agente.

## Correr local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
ADMIN_USUARIO=admin ADMIN_CLAVE=una-clave-larga .venv/bin/uvicorn app.main:app --reload
```

Abrir http://127.0.0.1:8000. El admin se crea solo la primera vez (si no hay usuarios). Los demás
usuarios se crean desde la pestaña **Admin**.

### La web

La web está en `front/` (React + Vite).

```bash
cd front && npm ci
npm run build   # deja la web en front/dist, que es lo que sirve FastAPI
npm run dev     # o con recarga en vivo en http://127.0.0.1:5173, contra el uvicorn del 8000
```

## Tests

```bash
.venv/bin/python -m pytest                                    # SQLite temporal
DATABASE_URL=postgresql://usuario@host/base .venv/bin/python -m pytest   # Postgres real
CHROMIUM=/ruta/a/chrome .venv/bin/python -m pytest tests/e2e  # navegador real (Playwright)
```

- Contra Postgres, las tablas se vacían antes de cada test: usar una base solo para eso.
- El test golden de Concert Channel corre solo si existe `privado/`.
- El e2e compila `front/` si hace falta (necesita npm).

## Deploy en Railway

1. **New Project → Deploy from GitHub repo**, con este repo (usa el `Dockerfile`, que también
   compila la web).
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
| `AGENTE_MODELO` | Modelo de las propuestas (por defecto `claude-haiku-5-5`, el más barato). |
| `AGENTE_MODELO_FUERTE` | Modelo para cuando se pide "con el modelo fuerte" (por defecto `claude-sonnet-5-5`). |
| `AGENTE_MODELO_RAPIDO` | Modelo de la charla (por defecto `claude-haiku-5-5`). |
| `AGENTE_LIMITE_DIARIO` | Pedidos al asistente por persona por día (por defecto 50). |
| `COOKIE_SEGURA` | `1`/`0` fuerza la cookie solo-HTTPS. En Railway se activa sola. |
| `DATA_DIR` | Carpeta de SQLite y del formato anterior (por defecto `datos/`). |

## Asistente (IA)

- Cada mensaje va primero a Claude Haiku: si es una pregunta o charla, responde ahí mismo.
- Si pide cambiar reglas o columnas, el pedido pasa a armar una propuesta: también con Haiku, que
  propone tarjetas, el servidor las prueba contra la grilla y los ejemplos, y se corrige hasta 3
  veces. El botón **Proponer cambios** va directo a ese paso.
- Si Haiku no lo logra, se puede pedir de nuevo con el modelo fuerte (`fuerte` en `/api/asistente`,
  Sonnet por defecto), que cuesta unas 20 veces más.
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
