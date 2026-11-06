# La web se compila aparte: la imagen final no lleva Node.
FROM node:22-slim AS web
WORKDIR /front
COPY front/package.json front/package-lock.json ./
RUN npm ci
COPY front ./
RUN npm run build

# La caja (Deno + Pyodide) corre aislado el código que el agente escribe para una señal.
FROM node:22-slim AS caja
WORKDIR /caja
COPY caja/package.json caja/package-lock.json ./
# El binario de Deno queda copiado en node_modules/deno: el paquete de la plataforma sería el mismo archivo otra vez.
RUN npm ci --omit=dev --no-audit --no-fund && rm -rf node_modules/@deno && test -x node_modules/deno/deno
COPY caja/runner.mjs ./

FROM python:3.13-slim
WORKDIR /app
# numpy abre un hilo de cálculo por cada núcleo de la máquina (en Railway, decenas) y cada uno reserva
# memoria: acá no hacen falta.
ENV OPENBLAS_NUM_THREADS=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=caja /caja ./caja
COPY app ./app
COPY ejemplos ./ejemplos
COPY --from=web /front/dist ./front/dist
# Código hostil contra la caja: si alguno sale, el build falla y no se deploya.
RUN python -m app.caja
# Sin DATABASE_URL, los datos van a SQLite en /data.
ENV DATA_DIR=/data
# Railway define PORT; 8000 para correrlo local.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
