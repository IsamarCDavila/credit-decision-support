import json
import os
import secrets
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from credit_support.api import app
from credit_support.db import get_engine
from credit_support.settings import get_settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def database():
    url = os.environ.get("CDS_TEST_ADMIN_URL")
    if not url:
        pytest.fail("Set CDS_TEST_ADMIN_URL to a dedicated PostgreSQL database ending in _test")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Integration tests require a dedicated database ending in _test")
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles "
                "WHERE rolname='cds_runtime') THEN CREATE ROLE cds_runtime; END IF; END $$"
            )
        )
    os.environ["CDS_DATABASE_URL"] = url
    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")

    def use_runtime_role(dbapi_connection, _record):
        dbapi_connection.execute("SET ROLE cds_runtime")
        dbapi_connection.commit()

    event.listen(get_engine(), "connect", use_runtime_role)
    yield admin
    admin.dispose()
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset(database):
    # Restricted to a disposable test database by the session fixture.
    with database.begin() as conn:
        conn.execute(text("TRUNCATE cases,policy_versions,idempotency_records CASCADE"))


@pytest.fixture
def client(database):
    tokens = {
        role: secrets.token_urlsafe(32) for role in ("analyst", "reviewer", "auditor", "admin")
    }
    tokens["other"] = secrets.token_urlsafe(32)
    identities = {
        token: {"actor_id": name, "role": "analyst" if name == "other" else name}
        for name, token in tokens.items()
    }
    os.environ["CDS_DEMO_IDENTITIES"] = json.dumps(identities)
    get_settings.cache_clear()
    with TestClient(app) as api:
        yield api, tokens


def auth(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def artifact_dir():
    root = (ROOT / "storage" / "test-artifacts").resolve()
    directory = root / str(uuid4())
    directory.mkdir(parents=True)
    yield directory
    if not directory.resolve().is_relative_to(root):
        raise RuntimeError("Unexpected test artifact path")
    shutil.rmtree(directory)
