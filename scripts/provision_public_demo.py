"""Privately provision a new hosted database and write restricted runtime credentials once."""

import argparse
import json
import os
import secrets
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from credit_support.policy_catalog import PolicySpec, publish


def provision(owner_url, output):
    url = make_url(owner_url)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Use the SQLAlchemy psycopg connection format")
    if url.query.get("sslmode") not in {"require", "verify-full"} or "-pooler" in (url.host or ""):
        raise ValueError("Use a direct TLS owner connection")
    root = Path(__file__).resolve().parent.parent
    password = secrets.token_urlsafe(36)
    runtime_url = url.set(username="cds_runtime", password=password).render_as_string(
        hide_password=False
    )
    engine = create_engine(owner_url, hide_parameters=True, connect_args={"connect_timeout": 10})
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    written = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            with engine.begin() as conn:
                if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='cds_runtime'")).first():
                    raise ValueError(
                        "Use a fresh isolated project; the runtime role already exists"
                    )
                if conn.execute(text("SELECT to_regclass('public.cases')")).scalar_one():
                    raise ValueError("Use a fresh isolated database")
                role_sql = (
                    sql.SQL(
                        "CREATE ROLE cds_runtime LOGIN NOINHERIT NOCREATEDB NOCREATEROLE "
                        "NOBYPASSRLS PASSWORD {}"
                    )
                    .format(sql.Literal(password))
                    .as_string(conn.connection.driver_connection)
                )
                conn.exec_driver_sql(role_sql)
                config = Config(str(root / "alembic.ini"))
                config.set_main_option("script_location", str(root / "migrations"))
                config.attributes["connection"] = conn
                command.upgrade(config, "head")
                for path in sorted((root / "data/policies").glob("*.json")):
                    publish(conn, PolicySpec.model_validate_json(path.read_text(encoding="utf-8")))
                # Retain the private credentials if commit delivery becomes uncertain.
                stream.write("CDS_DATABASE_URL=" + json.dumps(runtime_url) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                written = True
    except Exception:
        if not written:
            Path(output).unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()
    print("Hosted database prepared. Restricted connection saved privately to:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.hosting"))
    parser.add_argument("--output", type=Path, default=Path(".env.hosting.runtime"))
    args = parser.parse_args()
    try:
        value = dotenv_values(args.env_file).get("CDS_MIGRATION_DATABASE_URL")
        if not value:
            raise ValueError("Missing private migration connection")
        provision(value, args.output)
    except Exception:
        raise SystemExit(
            "Provisioning failed. Retain any private runtime file for recovery. "
            "No credentials were printed."
        ) from None
