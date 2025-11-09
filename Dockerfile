# --- VoiceGuide AirLink — Dockerfile (staging/prod) ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps (psycopg + tzdata)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev tzdata \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

EXPOSE 8000

# ✅ Avvia l'app corretta (main.py in root)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
