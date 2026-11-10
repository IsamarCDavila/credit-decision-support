from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, text

from credit_support.audit import canonical


def replay(
    conn: Connection, actor: str, route: str, key: str, digest: str
) -> dict[str, Any] | None:
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,0))"),
        {"scope": canonical([actor, route, key])},
    )
    row = (
        conn.execute(
            text("""
      SELECT payload_hash,response FROM idempotency_records WHERE actor_id=:actor
      AND route=:route AND key=:key AND expires_at>now()
    """),
            {"actor": actor, "route": route, "key": key},
        )
        .mappings()
        .first()
    )
    if row:
        if row["payload_hash"] != digest:
            raise HTTPException(409, "Idempotency key payload mismatch")
        return dict(row["response"])
    return None


def remember(
    conn: Connection,
    actor: str,
    route: str,
    key: str,
    digest: str,
    result: dict[str, Any],
    status: int,
) -> None:
    conn.execute(
        text("""
      INSERT INTO idempotency_records
      (actor_id,route,key,payload_hash,response,response_status,expires_at)
      VALUES(:actor,:route,:key,:hash,CAST(:response AS jsonb),:status,now()+interval '24 hours')
      ON CONFLICT(actor_id,route,key) DO UPDATE SET payload_hash=EXCLUDED.payload_hash,
      response=EXCLUDED.response,response_status=EXCLUDED.response_status,
      expires_at=EXCLUDED.expires_at
    """),
        {
            "actor": actor,
            "route": route,
            "key": key,
            "hash": digest,
            "response": canonical(result),
            "status": status,
        },
    )
