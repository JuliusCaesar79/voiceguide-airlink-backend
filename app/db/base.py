# app/db/base.py
from sqlalchemy.orm import declarative_base

# ------------------------------------------------------------
# BASE DICHIARATIVA SQLALCHEMY
# ------------------------------------------------------------
Base = declarative_base()

# ------------------------------------------------------------
# IMPORT MODELLI PER REGISTRAZIONE ALEMBIC
# ------------------------------------------------------------
# NB: questi import servono solo a fare in modo che Alembic
# "veda" i modelli ed effettui correttamente le migrazioni.
# Se in futuro aggiungiamo nuovi modelli, vanno importati qui.

try:
    # Modelli principali (esistenti)
    from app.models import license, session

    # ✅ Nuovo modello EventLog per Event Store e Webhook
    from app.models import event_log

except ImportError:
    # Durante la fase di build iniziale o esecuzioni isolate,
    # questi import possono non essere ancora disponibili.
    # In tal caso, Alembic funzionerà comunque dopo la prima migrazione.
    pass
