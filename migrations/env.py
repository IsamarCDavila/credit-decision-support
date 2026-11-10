from alembic import context
from sqlalchemy import create_engine

from credit_support.settings import get_settings

engine = create_engine(get_settings().database_url.get_secret_value(), hide_parameters=True)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
