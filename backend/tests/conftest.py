"""Shared pytest fixtures for migration and DB-integration tests.

Uses a separate Postgres database `pryzm_test` in the same pryzm_db Docker
container. The fixture drops + recreates the database at session start so each
test run begins from a known empty state.
"""
import os
import urllib.parse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from config import settings


TEST_DB_NAME = "pryzm_test"


def _test_database_url() -> str:
    """Build a DATABASE_URL for the test DB, reusing dev credentials."""
    safe_password = urllib.parse.quote_plus(settings.DB_PASSWORD)
    return (
        f"postgresql://{settings.DB_USER}:{safe_password}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{TEST_DB_NAME}"
    )


def _admin_url() -> str:
    """Build a DATABASE_URL for the postgres admin DB (used to CREATE/DROP)."""
    safe_password = urllib.parse.quote_plus(settings.DB_PASSWORD)
    return (
        f"postgresql://{settings.DB_USER}:{safe_password}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
    )


@pytest.fixture(scope="session")
def reset_test_db():
    """Drop + recreate the test DB once per pytest session. Yields the URL."""
    admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()

    test_engine = create_engine(_test_database_url(), isolation_level="AUTOCOMMIT")
    with test_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    test_engine.dispose()

    yield _test_database_url()


@pytest.fixture
def alembic_cfg(reset_test_db):
    """Alembic config pointed at the test DB. Re-created per test."""
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", reset_test_db)
    cfg.set_main_option(
        "script_location",
        os.path.join(os.path.dirname(__file__), "..", "alembic"),
    )
    return cfg


@pytest.fixture
def db_at_revision(alembic_cfg, reset_test_db):
    """Return a function that resets the DB to a specific revision."""
    def _go(revision: str):
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, revision)
        engine = create_engine(reset_test_db, poolclass=NullPool)
        return engine

    return _go


@pytest.fixture
def db_at_head(db_at_revision):
    """DB migrated to head."""
    return db_at_revision("head")


@pytest.fixture
def db_session(db_at_head):
    """A SQLAlchemy Session attached to the migrated test DB.

    Yields a fresh session bound to the test DB at head. Closes the session
    and disposes the engine on teardown to avoid connection leaks.
    """
    engine = db_at_head
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
