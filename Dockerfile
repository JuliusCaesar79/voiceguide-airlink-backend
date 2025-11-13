# ---- VoiceGuide AirLink backend: Railway-ready Dockerfile ----
# syntax=docker/dockerfile:1

FROM python:3.11-slim

# Evita prompt interattivi (es. tzdata)
ENV DEBIAN_FRONTEND=noninteractive

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

# Impostazioni Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dipendenze Python (layer separato per cache)
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Codice applicazione
COPY . .

# Railway inietta $PORT, ma mettiamo un default
ENV PORT=8000
EXPOSE 8000

# Migrazioni + avvio app
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
