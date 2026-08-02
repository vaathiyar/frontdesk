"""What Alembic connects to, and what it compares against.

The URL comes from `settings.database_url` rather than from `alembic.ini`, so there is
one place the database is named and no password in a tracked file. `cockroachdb+psycopg`
needs no rewriting to run here: psycopg 3 is both sync and async, which is why it is the
driver — Alembic gets a plain sync engine from the same URL the app opens asynchronously.

Offline mode (`alembic upgrade --sql`) is kept because it is how you read the DDL before
letting it near a real cluster.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from receptionist.core.db.engine import require_database
from receptionist.core.db.tables import Base
from receptionist.settings import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

require_database()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Everything `--autogenerate` diffs the live database against.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
