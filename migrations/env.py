from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from credit_support.settings import get_settings


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    run(provided)
else:
    engine = create_engine(get_settings().database_url.get_secret_value(), hide_parameters=True)
    with engine.connect() as connection:
        run(connection)
