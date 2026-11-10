import argparse
import json
import time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from credit_support.audit import append_event
from credit_support.db import get_engine
from credit_support.settings import get_settings


def claim(engine: Engine, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    with engine.begin() as conn:
        # Expired jobs at the attempt limit are terminalized before selecting more work.
        conn.execute(
            text("""
            UPDATE jobs SET status='FAILED_TERMINAL',lease_until=NULL,lease_token=NULL
            WHERE attempts>=3 AND status='RUNNING' AND lease_until<now()
        """)
        )
        row = (
            conn.execute(
                text("""
            WITH candidate AS (
              SELECT id FROM jobs WHERE attempts<3 AND next_run_at<=now()
              AND (status='READY' OR (status='RUNNING' AND lease_until<now()))
              ORDER BY next_run_at,id FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE jobs j SET status='RUNNING',attempts=j.attempts+1,worker_id=:worker,
              lease_token=:token,lease_until=now()+make_interval(secs=>:seconds)
            FROM candidate c WHERE j.id=c.id RETURNING j.*
        """),
                {"worker": worker_id, "token": uuid4(), "seconds": lease_seconds},
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


def heartbeat(engine: Engine, job: dict[str, Any], lease_seconds: int) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text("""
            UPDATE jobs SET lease_until=now()+make_interval(secs=>:seconds)
            WHERE id=:id AND lease_token=:token AND status='RUNNING' AND lease_until>now()
            RETURNING id
        """),
            {"id": job["id"], "token": job["lease_token"], "seconds": lease_seconds},
        )
        return result.first() is not None


def finish(engine: Engine, job: dict[str, Any]) -> bool:
    with engine.begin() as conn:
        # Lock case before job to match audit/review ordering and avoid deadlocks.
        case_id: UUID = conn.execute(
            text("SELECT case_id FROM evaluations WHERE id=:id"), {"id": job["evaluation_id"]}
        ).scalar_one()
        conn.execute(text("SELECT id FROM cases WHERE id=:id FOR UPDATE"), {"id": case_id})
        current = (
            conn.execute(
                text("""
            SELECT * FROM jobs WHERE id=:id AND lease_token=:token AND status='RUNNING'
            AND lease_until>now() FOR UPDATE
        """),
                {"id": job["id"], "token": job["lease_token"]},
            )
            .mappings()
            .first()
        )
        if current is None:
            return False
        result: dict[str, Any]
        if current["step"] != "foundation_check":
            status = "FAILED_TERMINAL"
            result = {"error": "Unsupported foundation step"}
        else:
            status = "SUCCEEDED"
            result = {"snapshot_available": True, "simulation": True}
        conn.execute(
            text("""
            UPDATE jobs SET status=:status,result=CAST(:result AS jsonb),lease_until=NULL,
              lease_token=NULL WHERE id=:id
        """),
            {"id": job["id"], "status": status, "result": json.dumps(result)},
        )
        append_event(
            conn,
            UUID(str(case_id)),
            "worker",
            "JOB_" + status,
            {"job_id": str(job["id"]), "step": current["step"]},
        )
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the persistent foundation worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    worker_id = str(uuid4())
    while True:
        job = claim(get_engine(), worker_id, settings.worker_lease_seconds)
        if job:
            finish(get_engine(), job)
        if args.once:
            return
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
