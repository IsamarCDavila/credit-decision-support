import argparse
import json
import time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from credit_support.audit import append_event
from credit_support.db import get_engine
from credit_support.ingestion import extract
from credit_support.parsers import IngestionError
from credit_support.policy_catalog import PolicyError
from credit_support.policy_engine import evaluate_policy
from credit_support.settings import get_settings


def claim(engine: Engine, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    expire_exhausted(engine)
    with engine.begin() as conn:
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


def expire_exhausted(engine: Engine) -> None:
    with engine.begin() as conn:
        candidate = (
            conn.execute(
                text("""
          SELECT j.id,j.evaluation_id,j.step,e.case_id FROM jobs j
          JOIN evaluations e ON e.id=j.evaluation_id WHERE j.attempts>=3
          AND j.status='RUNNING' AND j.lease_until<clock_timestamp() ORDER BY j.id LIMIT 1
        """)
            )
            .mappings()
            .first()
        )
        if not candidate:
            return
        conn.execute(
            text("SELECT id FROM cases WHERE id=:id FOR UPDATE"), {"id": candidate["case_id"]}
        )
        expired = conn.execute(
            text("""
          UPDATE jobs SET status='FAILED_TERMINAL',lease_until=NULL,lease_token=NULL,
          result='{"error":"Lease attempts exhausted"}' WHERE id=:id AND attempts>=3
          AND status='RUNNING' AND lease_until<clock_timestamp() RETURNING id
        """),
            {"id": candidate["id"]},
        ).first()
        if expired:
            if candidate["step"] in ("extract_documents", "evaluate_policy", "ai_workflow"):
                conn.execute(
                    text("UPDATE evaluations SET processing_state='FAILED_TERMINAL' WHERE id=:id"),
                    {"id": candidate["evaluation_id"]},
                )
            append_event(
                conn,
                candidate["case_id"],
                "worker",
                "JOB_FAILED_TERMINAL",
                {"job_id": str(candidate["id"]), "reason": "LEASE_ATTEMPTS_EXHAUSTED"},
            )


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
    if job["step"] == "ai_workflow":
        from credit_support.ai_workflow import finish_ai

        return finish_ai(engine, job)
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
        if current["step"] in ("extract_documents", "evaluate_policy"):
            try:
                with conn.begin_nested():
                    handler = extract if current["step"] == "extract_documents" else evaluate_policy
                    result = handler(conn, UUID(str(job["evaluation_id"])))
                status = "SUCCEEDED"
            except (IngestionError, PolicyError) as exc:
                status, result = "FAILED_TERMINAL", {"error": str(exc)}
                conn.execute(
                    text("UPDATE evaluations SET processing_state='FAILED_TERMINAL' WHERE id=:id"),
                    {"id": job["evaluation_id"]},
                )
        elif current["step"] != "foundation_check":
            status = "FAILED_TERMINAL"
            result = {"error": "Unsupported foundation step"}
        else:
            status = "SUCCEEDED"
            result = {"snapshot_available": True, "simulation": True}
        active: bool = conn.execute(
            text("SELECT lease_until>clock_timestamp() FROM jobs WHERE id=:id"), {"id": job["id"]}
        ).scalar_one()
        if not active:
            conn.rollback()
            return False
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
