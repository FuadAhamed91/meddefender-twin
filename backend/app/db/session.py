"""Engine and session factory construction."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, NullPool, create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_engine(database_url: str, *, echo: bool = False, serverless: bool = False) -> Engine:
    if serverless:
        # Short-lived function instances behind a transaction-mode pooler: no client-side pool,
        # and no server-side prepared statements (they do not survive connection hand-offs).
        return create_engine(
            database_url, echo=echo, poolclass=NullPool, connect_args={"prepare_threshold": None}
        )
    return create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One unit of work: commit on success, roll back on any exception."""
    with factory() as session, session.begin():
        yield session
