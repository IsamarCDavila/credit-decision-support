import json
import os
import subprocess
import sys

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy.exc import ArgumentError
from test_policy_engine import catalog as catalog_fixture

from credit_support import hosted_demo
from credit_support.db import get_engine
from credit_support.settings import Settings, get_settings

catalog = catalog_fixture
URL = "postgresql+psycopg://cds_runtime:test-password@db.example/credit?sslmode=require"


def test_hosted_environment_excludes_secrets_and_forces_offline():
    env, port = hosted_demo.child_environment(
        {
            "CDS_DATABASE_URL": URL,
            "RENDER_EXTERNAL_URL": "https://demo.onrender.com",
            "PORT": "10000",
            "CDS_OPENAI_API_KEY": "private-provider-key",
            "CDS_LLM_LIVE_ENABLED": "true",
            "CDS_MIGRATION_DATABASE_URL": "private-owner-url",
            "GITHUB_TOKEN": "private-github-token",
            "PATH": os.environ.get("PATH", ""),
        }
    )
    assert port == 10000 and env["CDS_PUBLIC_ORIGIN"] == "https://demo.onrender.com"
    assert env["CDS_OPENAI_API_KEY"] == "" and env["CDS_LLM_LIVE_ENABLED"] == "false"
    assert env["CDS_DEMO_IDENTITIES"] == "{}"
    assert "private" not in json.dumps(env)
    assert "CDS_MIGRATION_DATABASE_URL" not in env and "GITHUB_TOKEN" not in env


@pytest.mark.parametrize(
    "url",
    [
        URL.replace("cds_runtime", "owner"),
        URL.replace("require", "disable"),
        URL.replace("db.example", "db-pooler.example"),
        "invalid",
    ],
)
def test_hosted_connection_requires_direct_restricted_tls(url):
    with pytest.raises((ValueError, ArgumentError)):
        hosted_demo.child_environment(
            {"CDS_DATABASE_URL": url, "RENDER_EXTERNAL_URL": "https://demo.onrender.com"}
        )


def test_public_mode_ignores_private_dotenv(client, monkeypatch, artifact_dir):
    (artifact_dir / ".env").write_text(
        "CDS_OPENAI_API_KEY=private-local-key\n"
        "CDS_DEMO_IDENTITIES='{\""
        + "x" * 32
        + '":{"actor_id":"private-admin","role":"admin"}}\'\n',
        encoding="utf-8",
    )
    previous = os.getcwd()
    monkeypatch.chdir(artifact_dir)
    monkeypatch.setenv("CDS_PUBLIC_DEMO", "true")
    monkeypatch.setenv("CDS_PUBLIC_ORIGIN", "https://demo.example")
    monkeypatch.setenv("CDS_DEMO_IDENTITIES", "{}")
    monkeypatch.setenv("CDS_OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert not settings.demo_identities
        assert not settings.openai_api_key or not settings.openai_api_key.get_secret_value()
    finally:
        get_settings.cache_clear()
        monkeypatch.chdir(previous)


def test_provisioning_never_overwrites_existing_credentials(artifact_dir):
    from provision_public_demo import provision

    output = artifact_dir / ".env.hosting.runtime"
    output.write_text("retained", encoding="utf-8")
    with pytest.raises(FileExistsError):
        provision(URL, output)
    assert output.read_text(encoding="utf-8") == "retained"
    with pytest.raises(ValueError, match="TLS"):
        provision(URL.replace("require", "disable"), artifact_dir / "not-created")
    assert not (artifact_dir / "not-created").exists()


@pytest.mark.parametrize(
    "origin",
    [
        "http://demo.example",
        "https://demo.example/path",
        "https://user:secret@demo.example",
        "https://demo.example?secret=yes",
        "",
    ],
)
def test_public_settings_reject_invalid_origin(origin):
    with pytest.raises(ValidationError):
        Settings(
            database_url=URL,
            public_demo=True,
            public_origin=origin,
            demo_identities={},
            openai_api_key=None,
            llm_live_enabled=False,
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"llm_live_enabled": True},
        {"openai_api_key": "private"},
        {"demo_identities": {"a" * 32: {"actor_id": "admin", "role": "admin"}}},
    ],
)
def test_public_settings_fail_closed_with_live_key_or_static_identity(extra):
    values = {
        "database_url": URL,
        "public_demo": True,
        "public_origin": "https://demo.example",
        "demo_identities": {},
        "openai_api_key": None,
        "llm_live_enabled": False,
        **extra,
    }
    with pytest.raises(ValidationError):
        Settings(**values)


def test_public_origin_works_behind_http_proxy_without_trusting_forwarded_headers(
    client, catalog, monkeypatch
):
    api, _ = client
    monkeypatch.setenv("CDS_PUBLIC_DEMO", "true")
    monkeypatch.setenv("CDS_PUBLIC_ORIGIN", "https://demo.example")
    monkeypatch.setenv("CDS_DEMO_IDENTITIES", "{}")
    monkeypatch.setenv("CDS_OPENAI_API_KEY", "")
    monkeypatch.setenv("CDS_GUIDED_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    try:
        assert api.get("/v1/demo/config").json()["public_demo"]
        bad = api.post(
            "/v1/demo/sessions",
            json={"role": "analyst"},
            headers={
                "X-Demo-Request": "1",
                "Origin": "https://attacker.example",
                "X-Forwarded-Host": "attacker.example",
                "X-Forwarded-Proto": "https",
            },
        )
        assert bad.status_code == 403
        session = api.post(
            "/v1/demo/sessions",
            json={"role": "analyst"},
            headers={"X-Demo-Request": "1", "Origin": "https://demo.example"},
        )
        assert session.status_code == 201
        assert session.json()["provider"] == "mock"
        token = session.json()["role_tokens"]["analyst"]
        profile = api.get("/v1/me", headers={"Authorization": "Bearer " + token}).json()
        assert profile["guided_demo"] and not profile["live_model_enabled"]
    finally:
        get_settings.cache_clear()


def test_hosted_database_preflight_checks_restricted_role_and_schema(
    client, catalog, database, monkeypatch
):
    monkeypatch.setattr(hosted_demo, "create_engine", lambda *_a, **_kw: get_engine())
    hosted_demo.verify_database("not printed")
    monkeypatch.setattr(hosted_demo, "create_engine", lambda *_a, **_kw: database)
    with pytest.raises(ValueError, match="restricted"):
        hosted_demo.verify_database("not printed")


def test_supervisor_stops_sibling_when_one_process_exits(monkeypatch):
    original = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(hosted_demo.subprocess, "Popen", spawn)
    result = hosted_demo.supervise(
        [
            [sys.executable, "-c", "import time; time.sleep(30)"],
            [sys.executable, "-c", "pass"],
        ],
        dict(os.environ),
    )
    assert result == 1 and len(children) == 2
    assert all(child.poll() is not None for child in children)


def test_migrations_can_use_an_existing_transaction(database):
    from sqlalchemy import text

    with database.connect() as conn:
        transaction = conn.begin()
        config = Config("alembic.ini")
        config.attributes["connection"] = conn
        command.downgrade(config, "0005_human_review")
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0005_human_review"
        )
        command.upgrade(config, "head")
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0006_guided_demo"
        )
        transaction.rollback()
    with database.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0006_guided_demo"
        )
