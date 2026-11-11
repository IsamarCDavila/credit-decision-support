"""Opt-in, isolated synthetic sessions with expiring, hashed role credentials."""

import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from credit_support.ai_prompts import PROMPT_VERSION
from credit_support.audit import append_event, canonical
from credit_support.db import get_engine
from credit_support.ingestion import extract
from credit_support.ingestion_api import Actor
from credit_support.parsers import PARSER_VERSION, parse_csv
from credit_support.policy_catalog import PolicyError, select_policy
from credit_support.policy_engine import queue_policy_check
from credit_support.schemas import UTCTimestamp
from credit_support.settings import Identity, get_settings

router = APIRouter()
DemoRole = Literal["analyst", "reviewer", "auditor"]
ROLES: tuple[DemoRole, ...] = ("analyst", "reviewer", "auditor")


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: DemoRole = "analyst"


class SessionView(BaseModel):
    session_id: UUID
    case_id: UUID
    evaluation_id: UUID
    expires_at: UTCTimestamp
    role: DemoRole
    role_tokens: dict[DemoRole, str]
    simulation: Literal[True] = True
    provider: Literal["mock"] = "mock"


@router.get("/v1/demo/config")
def demo_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.guided_demo_enabled,
        "public_demo": settings.public_demo,
        "session_ttl_seconds": settings.demo_session_ttl_seconds,
        "roles": list(ROLES),
    }


@router.post("/v1/demo/sessions", status_code=201, response_model=SessionView)
def create_session(
    body: SessionRequest,
    request: Request,
    marker: Annotated[Literal["1"], Header(alias="X-Demo-Request")],
) -> Any:
    settings = get_settings()
    if not settings.guided_demo_enabled:
        raise HTTPException(404, "Guided demo is disabled")
    origin = request.headers.get("origin")
    expected_origin = (
        settings.public_origin if settings.public_demo else str(request.base_url).rstrip("/")
    )
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin and origin != expected_origin
    ):
        raise HTTPException(403, "Use the same-origin demonstration page")
    session_id, case_id, document_id, source_id, source_job = [uuid4() for _ in range(5)]
    actors = {role: f"guided:{session_id}:{role}" for role in ROLES}
    tokens = {role: secrets.token_urlsafe(32) for role in ROLES}
    data = (Path(__file__).parent / "demo_data/annual-statement.csv").read_bytes()
    parsed = parse_csv(data)
    digest = hashlib.sha256(data).hexdigest()
    snapshot = {
        "purpose": "EXTRACTION_ONLY",
        "documents": [
            {"document_id": str(document_id), "sha256": digest, "parser_version": PARSER_VERSION}
        ],
    }
    with get_engine().begin() as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('guided-demo-capacity',0))")
        )
        counts = (
            conn.execute(
                text("""
          SELECT count(*) AS total,count(*) FILTER(WHERE revoked_at IS NULL
          AND expires_at>clock_timestamp()) AS active FROM demo_sessions
        """)
            )
            .mappings()
            .one()
        )
        if (
            counts["active"] >= settings.demo_max_active_sessions
            or counts["total"] >= settings.demo_max_sessions
        ):
            raise HTTPException(429, "Guided demo capacity reached")
        case = (
            conn.execute(
                text("""
          INSERT INTO cases(id,segment,currency,cutoff) VALUES(:id,'SME','USD','2026-01-31')
          RETURNING *
        """),
                {"id": case_id},
            )
            .mappings()
            .one()
        )
        try:
            select_policy(conn, case)
        except PolicyError as exc:
            raise HTTPException(503, "The synthetic demo policy is not available") from exc
        expires_at: datetime = conn.execute(
            text("""
          INSERT INTO demo_sessions(id,case_id,expires_at)
          VALUES(:id,:case,now()+make_interval(secs=>:ttl)) RETURNING expires_at
        """),
            {"id": session_id, "case": case_id, "ttl": settings.demo_session_ttl_seconds},
        ).scalar_one()
        for role in ROLES:
            conn.execute(
                text("INSERT INTO case_members VALUES(:case,:actor,:role)"),
                {"case": case_id, "actor": actors[role], "role": role},
            )
            conn.execute(
                text("""
              INSERT INTO demo_role_tokens(token_hash,session_id,actor_id,role)
              VALUES(:hash,:session,:actor,:role)
            """),
                {
                    "hash": hashlib.sha256(tokens[role].encode()).hexdigest(),
                    "session": session_id,
                    "actor": actors[role],
                    "role": role,
                },
            )
        append_event(
            conn,
            case_id,
            actors["analyst"],
            "CASE_CREATED",
            {"segment": "SME", "currency": "USD", "cutoff": "2026-01-31", "synthetic": True},
        )
        append_event(
            conn,
            case_id,
            actors["analyst"],
            "GUIDED_DEMO_CREATED",
            {"session_id": str(session_id), "roles": list(ROLES), "model_provider": "mock"},
        )
        conn.execute(
            text("""
          INSERT INTO documents(id,case_id,sha256,media_type,byte_size,storage_key)
          VALUES(:id,:case,:hash,'text/csv',:size,:key)
        """),
            {
                "id": document_id,
                "case": case_id,
                "hash": digest,
                "size": len(data),
                "key": "db://" + str(document_id),
            },
        )
        conn.execute(
            text("""
          INSERT INTO document_contents(document_id,data,parsed)
          VALUES(:id,:data,CAST(:parsed AS jsonb))
        """),
            {"id": document_id, "data": data, "parsed": canonical(parsed)},
        )
        append_event(
            conn,
            case_id,
            actors["analyst"],
            "DOCUMENT_RECEIVED",
            {"document_id": str(document_id), "sha256": digest, "synthetic": True},
        )
        input_hash = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
        conn.execute(
            text("""
          INSERT INTO evaluations
          (id,case_id,prepared_by,input_hash,snapshot,versions,processing_state)
          VALUES(:id,:case,:actor,:hash,CAST(:snapshot AS jsonb),CAST(:versions AS jsonb),
                 'DOCUMENTS_RECEIVED')
        """),
            {
                "id": source_id,
                "case": case_id,
                "actor": actors["analyst"],
                "hash": input_hash,
                "snapshot": canonical(snapshot),
                "versions": canonical({"extraction": PARSER_VERSION}),
            },
        )
        conn.execute(
            text("INSERT INTO evaluation_documents VALUES(:eval,:doc)"),
            {"eval": source_id, "doc": document_id},
        )
        result = extract(conn, source_id)
        conn.execute(
            text("""
          INSERT INTO jobs(id,evaluation_id,step,input_hash,status,result)
          VALUES(:id,:eval,'extract_documents',:hash,'SUCCEEDED',CAST(:result AS jsonb))
        """),
            {"id": source_job, "eval": source_id, "hash": input_hash, "result": canonical(result)},
        )
        append_event(
            conn,
            case_id,
            actors["analyst"],
            "DEMO_SOURCE_EXTRACTED",
            {"evaluation_id": str(source_id), "job_id": str(source_job)},
        )
    analyst = Identity(
        actor_id=actors["analyst"],
        role="analyst",
        demo_session_id=session_id,
        demo_expires_at=expires_at,
    )
    try:
        receipt = queue_policy_check(
            get_engine(),
            case_id,
            source_id,
            analyst,
            str(session_id),
            ai={
                "provider": "mock",
                "workflow": "multi_agent",
                "model": "deterministic-fixture-v1",
                "prompt_version": PROMPT_VERSION,
            },
        )
    except Exception:
        with get_engine().begin() as conn:
            conn.execute(
                text("UPDATE demo_sessions SET revoked_at=clock_timestamp() WHERE id=:id"),
                {"id": session_id},
            )
        raise
    return {
        "session_id": session_id,
        "case_id": case_id,
        "evaluation_id": receipt["evaluation_id"],
        "expires_at": expires_at,
        "role": body.role,
        "role_tokens": tokens,
        "simulation": True,
        "provider": "mock",
    }


@router.post("/v1/demo/session/end")
def end_session(actor: Actor) -> dict[str, bool]:
    if actor.demo_session_id is None:
        raise HTTPException(403, "A guided demo session is required")
    with get_engine().begin() as conn:
        case_id: UUID = conn.execute(
            text("SELECT case_id FROM demo_sessions WHERE id=:id"), {"id": actor.demo_session_id}
        ).scalar_one()
        conn.execute(text("SELECT id FROM cases WHERE id=:id FOR UPDATE"), {"id": case_id})
        changed = conn.execute(
            text("""
          UPDATE demo_sessions SET revoked_at=clock_timestamp()
          WHERE id=:id AND revoked_at IS NULL RETURNING id
        """),
            {"id": actor.demo_session_id},
        ).first()
        if changed:
            append_event(
                conn,
                case_id,
                actor.actor_id,
                "GUIDED_DEMO_ENDED",
                {"session_id": str(actor.demo_session_id)},
            )
    return {"ended": True}
