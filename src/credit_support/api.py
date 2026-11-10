import hashlib
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from credit_support.audit import append_event, canonical
from credit_support.db import get_engine
from credit_support.ingestion_api import router as ingestion_router
from credit_support.limits import RequestSizeLimit
from credit_support.schemas import AuditPage, CaseView, CreateCase, Error, Health
from credit_support.security import authorize, identity
from credit_support.settings import Identity

app = FastAPI(
    title="Credit Decision Support",
    version="0.2.0",
    description=(
        "Synthetic document ingestion and evidence extraction. Financial evaluation, "
        "and human review are subsequent milestones."
    ),
)
app.add_middleware(RequestSizeLimit)
app.include_router(ingestion_router)
errors: dict[int | str, dict[str, Any]] = {
    code: {"model": Error} for code in (401, 403, 404, 409, 503)
}


@app.exception_handler(SQLAlchemyError)
async def database_error(_request: object, _exc: SQLAlchemyError) -> object:
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})


@app.get("/healthz", response_model=Health)
def health() -> Health:
    return Health(status="ok")


@app.get("/readyz", response_model=Health, responses={503: {"model": Error}})
def ready() -> Health:
    with get_engine().connect() as conn:
        revision: str = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != "0002_ingestion":
            raise HTTPException(503, "Database migration required")
    return Health(status="ready")


@app.post("/v1/cases", status_code=201, response_model=CaseView, responses=errors)
def create_case(
    body: CreateCase,
    actor: Annotated[Identity, Depends(identity)],
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> CaseView:
    if actor.role != "analyst":
        raise HTTPException(403, "Analyst role required")
    payload = body.model_dump(mode="json")
    digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
    params = {"actor": actor.actor_id, "key": key, "route": "/v1/cases"}
    with get_engine().begin() as conn:
        # All concurrent requests for this idempotency scope share the same DB lock.
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,0))"),
            {"scope": canonical([actor.actor_id, params["route"], key])},
        )
        previous = (
            conn.execute(
                text("""
            SELECT payload_hash,response FROM idempotency_records
            WHERE actor_id=:actor AND route=:route AND key=:key AND expires_at > now()
        """),
                params,
            )
            .mappings()
            .first()
        )
        if previous:
            if previous["payload_hash"] != digest:
                raise HTTPException(409, "Idempotency key payload mismatch")
            return CaseView.model_validate(previous["response"])
        case_id = uuid4()
        row = (
            conn.execute(
                text("""
            INSERT INTO cases(id,segment,currency,cutoff) VALUES(:id,:segment,:currency,:cutoff)
            RETURNING *
        """),
                {"id": case_id, **payload},
            )
            .mappings()
            .one()
        )
        conn.execute(
            text("""
            INSERT INTO case_members(case_id,actor_id,role) VALUES(:id,:actor,'analyst')
        """),
            {"id": case_id, "actor": actor.actor_id},
        )
        result = CaseView.model_validate(row)
        append_event(conn, case_id, actor.actor_id, "CASE_CREATED", payload)
        conn.execute(
            text("""
            INSERT INTO idempotency_records
              (actor_id,route,key,payload_hash,response,response_status,expires_at)
            VALUES(:actor,:route,:key,:hash,CAST(:response AS jsonb),201,now()+interval '24 hours')
            ON CONFLICT(actor_id,route,key) DO UPDATE SET payload_hash=EXCLUDED.payload_hash,
              response=EXCLUDED.response,expires_at=EXCLUDED.expires_at,response_status=201
        """),
            {**params, "hash": digest, "response": result.model_dump_json()},
        )
        return result


@app.get("/v1/cases/{id}", response_model=CaseView, responses=errors)
def get_case(id: UUID, actor: Annotated[Identity, Depends(identity)]) -> CaseView:
    with get_engine().connect() as conn:
        authorize(conn, id, actor)
        row = conn.execute(text("SELECT * FROM cases WHERE id=:id"), {"id": id}).mappings().one()
        return CaseView.model_validate(row)


@app.get("/v1/cases/{id}/audit-events", response_model=AuditPage, responses=errors)
def audit_events(
    id: UUID,
    actor: Annotated[Identity, Depends(identity)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditPage:
    with get_engine().connect() as conn:
        authorize(conn, id, actor)
        rows = (
            conn.execute(
                text("""
            SELECT * FROM audit_events WHERE case_id=:id AND sequence>:after
            ORDER BY sequence LIMIT :limit
        """),
                {"id": id, "after": after_sequence, "limit": limit + 1},
            )
            .mappings()
            .all()
        )
        return AuditPage.model_validate(
            {
                "events": rows[:limit],
                "next_after_sequence": rows[limit - 1]["sequence"] if len(rows) > limit else None,
            }
        )
