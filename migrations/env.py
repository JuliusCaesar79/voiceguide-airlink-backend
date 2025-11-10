from __future__ import annotations

import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

# ------------------------------------------------------------
# Configurazione Alembic
# ------------------------------------------------------------
config = context.config

# Carica file di configurazione del logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ------------------------------------------------------------
# Import dinamico di Base
# ------------------------------------------------------------
target_metadata = None
for _candidate in [
    "app.db.base:Base",
    "app.db.models:Base",
    "app.models:Base",
]:
    try:
        module_path, attr = _candidate.split(":")
        mod = __import__(module_path, fromlist=[attr])
        target_metadata = getattr(mod, attr)
        print(f"[alembic] Using metadata from {_candidate}")
        break
    except Exception:
        continue

if not target_metadata:
    print("[alembic] ⚠️ Nessun metadata trovato; migrazioni 'autogenerate' disabilitate.")

# ------------------------------------------------------------
# Normalizzazione URL database (Railway / locale)
# ------------------------------------------------------------
def _normalize_dsn(url: str | None) -> str | None:
    if not url:
        return url
    url = url.strip()
    # Railway può fornire postgres:// o postgresql:// senza driver
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url and "+psycopg2" not in url:
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


# Legge variabile d'ambiente DATABASE_URL (fallback)
db_url = _normalize_dsn(os.environ.get("DATABASE_URL"))
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)
else:
    print("[alembic] ⚠️ DATABASE_URL non impostato; verifica alembic.ini o env var.")

# ------------------------------------------------------------
# Modalità offline (solo generazione SQL)
# ------------------------------------------------------------
def run_migrations_offline() -> None:
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

# ------------------------------------------------------------
# Modalità online (connessione diretta al DB)
# ------------------------------------------------------------
def run_migrations_online() -> None:
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

# ------------------------------------------------------------
# Esecuzione principale
# ------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
