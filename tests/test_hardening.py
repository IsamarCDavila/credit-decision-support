import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from conftest import auth
from evaluate_hardening import timings, wilson
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from test_worker import add_job

from credit_support.db import get_engine
from credit_support.operations import DemoAdmission, telemetry
from credit_support.settings import get_settings
from credit_support.worker import claim, run_once


def test_measurement_statistics_preserve_small_sample_uncertainty():
    assert wilson(0, 0) is None
    assert wilson(40, 40) == [0.912378, 1.0]
    assert wilson(0, 10) == [0.0, 0.277533]
    assert timings(list(range(1, 21))) == {"median_seconds": 10.5, "p95_seconds": 19}


def test_rate_limit_concurrent_boundary_and_memory():
    limiter = DemoAdmission()
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: limiter.allow("peer", 8, now=1)[0], range(32)))
    assert sum(outcomes) == 8
    assert limiter.allow("peer", 8, now=60) == (False, 2)
    assert limiter.allow("peer", 8, now=61) == (True, 0)
    for n in range(1023):
        assert limiter.allow(str(n), 8, now=61)[0]
    assert not limiter.allow("overflow", 8, now=61)[0]
    assert len(limiter.peers) == 1024
    assert limiter.allow("new", 8, now=121)[0]
    assert len(limiter.peers) == 1


def test_http_throttle_ignores_forwarded_peer_and_redacts(client, monkeypatch, caplog):
    api, tokens = client
    monkeypatch.setenv("CDS_DEMO_REQUESTS_PER_MINUTE", "1")
    get_settings.cache_clear()
    caplog.set_level(logging.INFO, logger="credit_support.operations")
    secret = "private-query-and-header"
    first = api.post(
        "/v1/demo/sessions?private=" + secret,
        headers={"Authorization": "Bearer " + secret, "X-Request-ID": secret},
        json={"private": secret},
    )
    second = api.post("/v1/demo/sessions", headers={"X-Forwarded-For": "new-peer"})
    assert second.status_code == 429 and int(second.headers["Retry-After"]) > 0
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    UUID(first.headers["X-Request-ID"])
    entries = [r.message for r in caplog.records if r.name == "credit_support.operations"]
    assert secret not in "".join(entries)
    assert all(json.loads(entry)["event"] == "http_request" for entry in entries)
    assert secret not in json.dumps(telemetry.snapshot())
    for role in ("analyst", "reviewer", "auditor"):
        assert api.get("/v1/operations", headers=auth(tokens[role])).status_code == 403
    response = api.get("/v1/operations", headers=auth(tokens["admin"]))
    assert response.status_code == 200 and response.json()["api"]["scope"] == "current_api_process"
    assert api.get("/v1/operations").status_code == 401
    get_settings.cache_clear()


def test_statement_and_lock_timeouts_are_effective(database):
    engine = get_engine()
    with engine.begin() as conn:
        assert int(conn.execute(text("SHOW statement_timeout")).scalar_one().removesuffix("s")) > 0
        assert conn.execute(text("SHOW lock_timeout")).scalar_one() == "5s"
        if os.name == "nt":
            pytest.skip("Local query timers did not interrupt; enforcement is verified in Linux CI")
        conn.execute(text("SET LOCAL statement_timeout='50ms'"))
        with pytest.raises(DBAPIError):
            conn.execute(text("SELECT pg_sleep(1)"))
    with database.begin() as holder:
        holder.execute(text("SELECT pg_advisory_xact_lock(978621)"))
        with engine.begin() as contender:
            contender.execute(text("SET LOCAL lock_timeout='50ms'"))
            with pytest.raises(DBAPIError):
                contender.execute(text("SELECT pg_advisory_xact_lock(978621)"))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1


def test_worker_recovers_after_database_outage_without_leaking(client, monkeypatch, caplog):
    import credit_support.worker as worker

    api, _ = client
    original = worker.claim

    def unavailable(*_args):
        raise OperationalError("private SQL", {}, Exception("private credentials"))

    monkeypatch.setattr(worker, "claim", unavailable)
    caplog.set_level(logging.WARNING, logger="credit_support.operations")
    assert not run_once(get_engine(), "restart-test", 30)
    assert "private" not in caplog.text
    assert "worker_database_unavailable" in caplog.text
    monkeypatch.setattr(worker, "claim", original)
    job, _ = add_job(get_engine())
    assert run_once(get_engine(), "restart-test", 30)
    with get_engine().connect() as conn:
        assert (
            conn.execute(text("SELECT status FROM jobs WHERE id=:id"), {"id": job}).scalar_one()
            == "SUCCEEDED"
        )
    assert api.get("/readyz").status_code == 200


def test_worker_restarts_in_new_process_without_duplicate_effects(database):
    job, case = add_job(database)
    old = claim(get_engine(), "terminated-worker", 30)
    assert old
    with database.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=:id"), {"id": job}
        )
    env = {**os.environ, "CDS_DATABASE_URL": os.environ["CDS_TEST_ADMIN_URL"]}
    # Test clusters intentionally use a NOLOGIN runtime role. Match the fixture's
    # SET ROLE connection hook rather than granting new login privileges.
    bootstrap = """
from sqlalchemy import event
from credit_support.db import get_engine
from credit_support.worker import main
def runtime_connection(connection, _record):
    connection.execute('SET ROLE cds_runtime')
    connection.commit()
event.listen(get_engine(), 'connect', runtime_connection)
main()
"""
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, "-c", bootstrap, "--once"],
            env=env,
            capture_output=True,
            timeout=20,
        )
        assert completed.returncode == 0, "Worker subprocess failed"
        assert b"worker_database_unavailable" not in completed.stderr
    with database.connect() as conn:
        row = conn.execute(text("SELECT status,attempts FROM jobs WHERE id=:id"), {"id": job}).one()
        assert tuple(row) == ("SUCCEEDED", 2)
        assert (
            conn.execute(
                text("SELECT count(*) FROM audit_events WHERE case_id=:id"), {"id": case}
            ).scalar_one()
            == 1
        )


def test_database_outage_response_can_recover(client, monkeypatch):
    import credit_support.api as module

    api, _ = client
    original = module.get_engine

    def unavailable():
        raise OperationalError("private SQL", {}, Exception("private secret"))

    monkeypatch.setattr(module, "get_engine", unavailable)
    response = api.get("/readyz")
    assert response.status_code == 503 and "private" not in response.text
    assert response.headers["X-Request-ID"]
    monkeypatch.setattr(module, "get_engine", original)
    assert api.get("/readyz").status_code == 200
