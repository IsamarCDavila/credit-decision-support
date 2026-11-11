from functools import lru_cache

from sqlalchemy import Engine, create_engine

from credit_support.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={
            "connect_timeout": 5,
            "options": (
                f"-c statement_timeout={settings.db_statement_timeout_ms} "
                f"-c lock_timeout={settings.db_lock_timeout_ms} "
                "-c idle_in_transaction_session_timeout=30000"
            ),
        },
        hide_parameters=True,
    )
