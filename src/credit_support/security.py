import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Connection, text

from credit_support.settings import Identity, get_settings

bearer = HTTPBearer(auto_error=False)


def identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    if credentials and credentials.scheme.lower() == "bearer":
        for token, actor in get_settings().demo_identities.items():
            if secrets.compare_digest(credentials.credentials.encode(), token.encode()):
                return actor
    raise HTTPException(
        401, "Invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"}
    )


def authorize(conn: Connection, case_id: UUID, actor: Identity) -> None:
    row = conn.execute(
        text("""
        SELECT 1 FROM case_members WHERE case_id=:id AND actor_id=:actor AND role=:role
    """),
        {"id": case_id, "actor": actor.actor_id, "role": actor.role},
    ).first()
    if row is None:
        raise HTTPException(404, "Case not found")
