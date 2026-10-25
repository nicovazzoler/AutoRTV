FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY ejemplos ./ejemplos
COPY web ./web
# Sin DATABASE_URL, los datos van a SQLite en /data.
ENV DATA_DIR=/data
# Railway define PORT; 8000 para correrlo local.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
