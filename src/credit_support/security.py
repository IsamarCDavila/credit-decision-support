import hashlib
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Connection, text

from credit_support.db import get_engine
from credit_support.settings import Identity, get_settings

bearer = HTTPBearer(auto_error=False)


def identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    if credentials and credentials.scheme.lower() == "bearer":
        for token, actor in get_settings().demo_identities.items():
            if secrets.compare_digest(credentials.credentials.encode(), token.encode()):
                return actor
        if get_settings().guided_demo_enabled:
            digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
            with get_engine().connect() as conn:
                row = (
                    conn.execute(
                        text("""
                  SELECT t.actor_id,t.role,s.id AS session_id,s.expires_at
                  FROM demo_role_tokens t JOIN demo_sessions s ON s.id=t.session_id
                  WHERE t.token_hash=:hash AND s.revoked_at IS NULL
                  AND s.expires_at>clock_timestamp()
                """),
                        {"hash": digest},
                    )
                    .mappings()
                    .first()
                )
                if row:
                    return Identity(
                        actor_id=row["actor_id"],
                        role=row["role"],
                        demo_session_id=row["session_id"],
                        demo_expires_at=row["expires_at"],
                    )
    raise HTTPException(
        401, "Invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"}
    )


def authorize(conn: Connection, case_id: UUID, actor: Identity) -> None:
    if actor.demo_session_id is not None:
        scope = conn.execute(
            text("""
          SELECT 1 FROM demo_sessions WHERE id=:session AND case_id=:case
          AND revoked_at IS NULL AND expires_at>clock_timestamp()
        """),
            {"session": actor.demo_session_id, "case": case_id},
        ).first()
        if scope is None:
            raise HTTPException(404, "Case not found")
    row = conn.execute(
        text("""
        SELECT 1 FROM case_members WHERE case_id=:id AND actor_id=:actor AND role=:role
    """),
        {"id": case_id, "actor": actor.actor_id, "role": actor.role},
    ).first()
    if row is None:
        raise HTTPException(404, "Case not found")
