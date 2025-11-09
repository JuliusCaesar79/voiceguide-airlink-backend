# scripts/seed_demo.py
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()  # carica .env dalla root
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL mancante")

# SQLAlchemy setup
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Modelli
from app.models.license import License

DEMO_LICENSES = [
    {"code": "TRIAL-10", "max_listeners": 10, "duration_minutes": 240, "is_active": False},
    {"code": "PRO-25",   "max_listeners": 25, "duration_minutes": 240, "is_active": False},
    {"code": "PLUS-35",  "max_listeners": 35, "duration_minutes": 240, "is_active": False},
    {"code": "MAX-100",  "max_listeners": 100, "duration_minutes": 240, "is_active": False},
]

def main():
    db = SessionLocal()
    try:
        existing = {lic.code for lic in db.query(License).all()}
        created = 0
        for data in DEMO_LICENSES:
            if data["code"] in existing:
                continue
            db.add(License(**data))
            created += 1
        db.commit()
        print(f"Seed completato. Licenze create: {created}. Totali: {db.query(License).count()}.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
