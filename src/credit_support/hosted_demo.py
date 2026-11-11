"""Supervise one API and one offline worker in a free, sleeping web-service container."""

import json
import os
import signal
import subprocess
import sys
import time
from typing import Any

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from credit_support.settings import Settings


class HostedSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def child_environment(source: dict[str, str]) -> tuple[dict[str, str], int]:
    database = source.get("CDS_DATABASE_URL", "")
    url = make_url(database)
    if (
        url.drivername != "postgresql+psycopg"
        or url.username != "cds_runtime"
        or url.query.get("sslmode") not in {"require", "verify-full"}
        or "-pooler" in (url.host or "")
    ):
        raise ValueError("Use the direct TLS connection for the restricted cds_runtime role")
    port = int(source.get("PORT", "10000"))
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid web-service port")
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "HOME",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    child = {key: value for key, value in source.items() if key in allowed}
    child.update(
        {
            "CDS_DATABASE_URL": database,
            "CDS_PUBLIC_DEMO": "true",
            "CDS_PUBLIC_ORIGIN": source.get("CDS_PUBLIC_ORIGIN")
            or source.get("RENDER_EXTERNAL_URL", ""),
            "CDS_GUIDED_DEMO_ENABLED": "true",
            "CDS_DEMO_IDENTITIES": "{}",
            "CDS_OPENAI_API_KEY": "",
            "CDS_LLM_LIVE_ENABLED": "false",
            "CDS_LLM_BUDGET_USD": "2.00",
            "PYTHONUNBUFFERED": "1",
        }
    )
    for name in (
        "CDS_DEMO_MAX_ACTIVE_SESSIONS",
        "CDS_DEMO_MAX_SESSIONS",
        "CDS_DEMO_REQUESTS_PER_MINUTE",
        "CDS_DEMO_SESSION_TTL_SECONDS",
    ):
        if name in source:
            child[name] = source[name]
    # Validate without reading any developer-local .env file.
    values: dict[str, Any] = {
        key.removeprefix("CDS_").lower(): value
        for key, value in child.items()
        if key.startswith("CDS_")
    }
    values.update(_env_file=None, demo_identities={})
    HostedSettings(**values)
    return child, port


def verify_database(database: str) -> None:
    engine = create_engine(database, connect_args={"connect_timeout": 10}, hide_parameters=True)
    try:
        with engine.connect() as conn:
            row = (
                conn.execute(
                    text("""
              SELECT current_user AS actor,rolsuper,rolcreaterole,rolcreatedb,rolbypassrls,
              EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) AS member,
              EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='public'
                     AND nspowner=pg_roles.oid) AS owns_schema,
              EXISTS(SELECT 1 FROM pg_database WHERE datname=current_database()
                     AND datdba=pg_roles.oid) AS owns_database,
              has_schema_privilege(current_user,'public','CREATE') AS can_create
              FROM pg_roles WHERE rolname=current_user
            """)
                )
                .mappings()
                .one()
            )
            if row["actor"] != "cds_runtime" or any(row[key] for key in row if key != "actor"):
                raise ValueError("Runtime database role must be restricted and own no schema")
            revision: str = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if revision != "0006_guided_demo":
                raise ValueError("Apply migrations privately before deploying")
            count: int = conn.execute(
                text("SELECT count(*) FROM policy_versions WHERE published_at IS NOT NULL")
            ).scalar_one()
            if not count:
                raise ValueError("Publish the synthetic policy before deploying")
    finally:
        engine.dispose()


def supervise(commands: list[list[str]], env: dict[str, str]) -> int:
    children: list[Any] = []
    stopping = False

    def stop(_signal: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    previous = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    code = 0
    try:
        for command in commands:
            children.append(subprocess.Popen(command, env=env))
        while not stopping:
            if any(child.poll() is not None for child in children):
                code = 1
                break
            time.sleep(0.2)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for s, handler in previous.items():
            signal.signal(s, handler)
    return code


def main() -> None:
    try:
        env, port = child_environment(dict(os.environ))
        verify_database(env["CDS_DATABASE_URL"])
        code = supervise(
            [
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "credit_support.api:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(port),
                    "--no-access-log",
                    "--no-proxy-headers",
                ],
                [sys.executable, "-m", "credit_support.worker"],
            ],
            env,
        )
    except Exception:
        # Provider/SQL exceptions may contain connection URLs. Never print their text.
        print(
            json.dumps(
                {
                    "event": "hosted_demo_start_failed",
                    "detail": "Verify restricted TLS connection, schema, policy, and HTTPS origin",
                }
            ),
            file=sys.stderr,
        )
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
