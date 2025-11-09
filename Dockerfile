
# --- VoiceGuide AirLink — Dockerfile (staging/prod) ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1

# System deps (psycopg + tzdata)
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential libpq-dev tzdata  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install
# (Assumes a requirements.txt exists at repo root; adjust if needed)
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy project
COPY . .

EXPOSE 8000

# Start with Uvicorn (Gunicorn layer can be added later if needed)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
