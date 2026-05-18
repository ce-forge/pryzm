"""must_change_password column added to users."""
from sqlalchemy import inspect


def test_must_change_password_column(db_at_revision, alembic_cfg):
    from alembic import command

    engine = db_at_revision("5f645f0d5313")
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "must_change_password" not in cols
    engine.dispose()

    command.upgrade(alembic_cfg, "head")

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from tests.conftest import _test_database_url
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "must_change_password" in cols
    engine.dispose()

    command.downgrade(alembic_cfg, "5f645f0d5313")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "must_change_password" not in cols
    engine.dispose()
