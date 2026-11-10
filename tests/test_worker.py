from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import text
from test_database import seed

from credit_support.worker import claim, finish, heartbeat


def add_job(database, step="foundation_check"):
    with database.begin() as conn:
        case, evaluation, _ = seed(conn)
        job = uuid4()
        conn.execute(
            text(
                "INSERT INTO jobs(id,evaluation_id,step,input_hash,status) "
                "VALUES(:id,:eval,:step,:hash,'READY')"
            ),
            {"id": job, "eval": evaluation, "hash": "d" * 64, "step": step},
        )
    return job, case


def test_concurrent_workers_claim_once_and_atomic_audit(database):
    job_id, case = add_job(database)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: claim(database, str(n), 30), range(4)))
    jobs = [x for x in results if x]
    assert len(jobs) == 1
    assert heartbeat(database, jobs[0], 30)
    assert finish(database, jobs[0])
    assert not finish(database, jobs[0])
    with database.connect() as conn:
        assert (
            conn.execute(text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id}).scalar_one()
            == "SUCCEEDED"
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM audit_events WHERE case_id=:id"), {"id": case}
            ).scalar_one()
            == 1
        )


def test_expired_lease_fences_old_worker_and_reclaims(database):
    job_id, _ = add_job(database)
    old = claim(database, "old", 30)
    with database.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": job_id},
        )
    new = claim(database, "new", 30)
    assert new and new["attempts"] == 2
    assert not heartbeat(database, old, 30)
    assert not finish(database, old)
    assert finish(database, new)


def test_retry_limit_and_unknown_step(database):
    job_id, _ = add_job(database)
    for _ in range(3):
        assert claim(database, "worker", 30)
        with database.begin() as conn:
            conn.execute(
                text("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=:id"),
                {"id": job_id},
            )
    assert claim(database, "worker", 30) is None
    with database.connect() as conn:
        assert (
            conn.execute(text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id}).scalar_one()
            == "FAILED_TERMINAL"
        )
    job_id, _ = add_job(database, "unknown")
    assert finish(database, claim(database, "worker", 30))
    with database.connect() as conn:
        assert (
            conn.execute(text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id}).scalar_one()
            == "FAILED_TERMINAL"
        )
