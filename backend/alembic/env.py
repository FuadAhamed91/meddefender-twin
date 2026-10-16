"""Alembic environment. The database URL is taken from DATABASE_URL (or -x dburl=...)."""

from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import engine_from_config, pool

from alembic import context
from app.db.base import Base
import app.models  # noqa: F401  (registers all tables)

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

class _MigrationSettings(BaseSettings):
    """Only the database URL: migrations must not require application secrets."""

    model_config = SettingsConfigDict(
        env_file=(str(Path(__file__).resolve().parents[2] / ".env"), ".env"), extra="ignore"
    )
    database_url: str | None = None


url = (
    context.get_x_argument(as_dictionary=True).get("dburl")
    or config.get_main_option("sqlalchemy.url")
    or _MigrationSettings().database_url
)
if not url:
    raise RuntimeError("Set DATABASE_URL (env or .env) or pass -x dburl=... before running migrations")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(
            connection=connectable, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
