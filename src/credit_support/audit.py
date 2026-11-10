import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def append_event(
    conn: Connection, case_id: UUID, actor_id: str, kind: str, payload: dict[str, Any]
) -> None:
    # Serialize per-case sequence allocation and hash-chain extension.
    conn.execute(text("SELECT id FROM cases WHERE id=:id FOR UPDATE"), {"id": case_id})
    previous = (
        conn.execute(
            text(
                "SELECT sequence,event_hash FROM audit_events WHERE case_id=:id "
                "ORDER BY sequence DESC LIMIT 1"
            ),
            {"id": case_id},
        )
        .mappings()
        .first()
    )
    event = {
        "id": str(uuid4()),
        "case_id": str(case_id),
        "sequence": previous["sequence"] + 1 if previous else 1,
        "actor_id": actor_id,
        "kind": kind,
        "payload": payload,
        "previous_hash": previous["event_hash"] if previous else None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    digest = hashlib.sha256(canonical(event).encode()).hexdigest()
    conn.execute(
        text("""
        INSERT INTO audit_events
          (id,case_id,sequence,actor_id,kind,payload,previous_hash,event_hash,created_at)
        VALUES (:id,:case_id,:sequence,:actor_id,:kind,CAST(:payload AS jsonb),
                :previous_hash,:event_hash,:created_at)
    """),
        {**event, "payload": canonical(payload), "event_hash": digest},
    )
