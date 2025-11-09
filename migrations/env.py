from __future__ import annotations
import os
import sys
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool, MetaData
from dotenv import load_dotenv
from configparser import RawConfigParser  # Evita conflitti con '%'

# ============================================================
#  VoiceGuide.it AirLink — Alembic Environment
# ============================================================

# Carica variabili dal file .env nella root del progetto
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Aggiunge la root del progetto al path per permettere gli import di app/*
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Importa i modelli principali (serve per autogenerate)
from app.db.base import Base
from app.models import license, session, listener, event  # 👈 incluso anche event

# ------------------------------------------------------------
# Configurazione Alembic
# ------------------------------------------------------------
config = context.config
config.file_config = RawConfigParser()  # Disattiva l’interpolazione di '%'

# Recupera DATABASE_URL dall'ambiente
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL non trovata nel file .env")

# Imposta la URL nel file di configurazione Alembic
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Logger Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadati target per autogenerate
target_metadata = Base.metadata or MetaData()

# ============================================================
#  MIGRAZIONI OFFLINE
# ============================================================
def run_migrations_offline() -> None:
    """Esegue le migrazioni senza connessione DB."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()

# ============================================================
#  MIGRAZIONI ONLINE
# ============================================================
def run_migrations_online() -> None:
    """Esegue le migrazioni con connessione DB attiva."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

# ============================================================
#  ESECUZIONE
# ============================================================
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
