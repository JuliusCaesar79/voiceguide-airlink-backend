
# VoiceGuide.it AirLink — Backend Starter

This is a minimal, production‑ready FastAPI + SQLAlchemy + Alembic scaffold to implement the core endpoints:

- `POST /activate-license`
- `POST /start-session`
- `POST /join-pin`
- `POST /end-session`
- `GET /health`

## Prerequisites (dev)
- Python 3.11+
- Git
- PostgreSQL 14+ (or Docker)
- (Optional) Redis 6+
- VS Code
- pgAdmin 4

## Quickstart (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
copy .env.example .env
# edit .env with your DB URL
alembic upgrade head
uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000/docs

## Quickstart (macOS/Linux)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
# edit .env with your DB URL
alembic upgrade head
uvicorn app.main:app --reload
```

## Docker (optional)
```bash
docker compose up -d
# wait a few seconds, then
uvicorn app.main:app --reload
```

## Notes
- Start simple without Redis; add it when implementing rate limiting / PIN TTLs.
- Alembic is configured to use SQLAlchemy models from `app.models`.
- The initial migration creates tables for `users`, `licenses`, `sessions`, `listeners` aligned with the alignment file.
