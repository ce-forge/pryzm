"""folder.id server-side default migration."""
from sqlalchemy import inspect, create_engine
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_folder_id_remains_not_null_after_migration(alembic_cfg):
    from alembic import command
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)
    id_col = next(c for c in inspector.get_columns("folders") if c["name"] == "id")
    assert id_col["nullable"] is False
    engine.dispose()
