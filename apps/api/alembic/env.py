import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  registers tables on Base.metadata
from app.config import settings
from app.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# Tests point migrations at the test database through this variable.
url = os.environ.get("TRACKER_MIGRATE_URL") or settings.database_url


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
