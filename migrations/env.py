from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Config Alembic
config = context.config

# Leggi logging da alembic.ini (se configurato)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Prova a importare la Base metadata (per autogenerate). Fallback a None.
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
        break
    except Exception:
        pass

# Imposta sqlalchemy.url da env se presente (es. Railway)
db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Alembic usa questa opzione per creare l'engine
    config.set_main_option("sqlalchemy.url", db_url)

def run_migrations_offline() -> None:
    """Esegue migrazioni in modalità 'offline'."""
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

def run_migrations_online() -> None:
    """Esegue migrazioni in modalità 'online'."""
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

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
