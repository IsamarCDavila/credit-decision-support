"""Case-scoped workspace reads, member assignment, and independent human review."""

import hashlib
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from credit_support.audit import append_event, canonical
from credit_support.db import get_engine
from credit_support.idempotency import remember, replay
from credit_support.ingestion import require_case
from credit_support.ingestion_api import Actor, Key
from credit_support.schemas import CaseView, UTCTimestamp
from credit_support.settings import get_settings

router = APIRouter()


class MemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str = Field(min_length=1, max_length=200)
    role: Literal["reviewer", "auditor"]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_review_state: Literal["PENDING"]
    decision: Literal["APPROVED", "REJECTED", "NEEDS_MORE_INFO"]
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A review reason is required")
        return value


class ReviewView(BaseModel):
    id: UUID
    evaluation_id: UUID
    reviewer_id: str
    decision: Literal["APPROVED", "REJECTED", "NEEDS_MORE_INFO"]
    reason: str
    created_at: UTCTimestamp


class MemberView(BaseModel):
    actor_id: str
    role: Literal["analyst", "reviewer", "auditor", "admin"]


class ProfileView(MemberView):
    live_model_enabled: bool
    simulation: Literal[True]
    guided_demo: bool = False
    demo_expires_at: UTCTimestamp | None = None


class CaseSummary(CaseView):
    processing_state: str | None
    review_decision: Literal["APPROVED", "REJECTED", "NEEDS_MORE_INFO"] | None


class CasePage(BaseModel):
    cases: list[CaseSummary]
    next_offset: int | None


class DocumentSummary(BaseModel):
    id: UUID
    sha256: str
    media_type: Literal["text/csv", "application/pdf"]
    byte_size: int
    created_at: UTCTimestamp


class EvaluationSummary(BaseModel):
    id: UUID
    processing_state: str
    prepared_by: str
    policy_id: str | None
    created_at: UTCTimestamp
    review_decision: Literal["APPROVED", "REJECTED", "NEEDS_MORE_INFO"] | None


class WorkspaceView(BaseModel):
    case: CaseView
    documents: list[DocumentSummary]
    evaluations: list[EvaluationSummary]
    history_truncated: bool
    members: list[MemberView]


class ReviewStateView(BaseModel):
    state: Literal["NOT_READY", "PENDING", "APPROVED", "REJECTED", "NEEDS_MORE_INFO"]
    current: bool
    review: ReviewView | None
    can_review: bool


@router.get("/v1/me", response_model=ProfileView)
def profile(actor: Actor) -> Any:
    return {
        **actor.model_dump(),
        "live_model_enabled": get_settings().llm_live_enabled and actor.demo_session_id is None,
        "simulation": True,
        "guided_demo": actor.demo_session_id is not None,
        "demo_expires_at": actor.demo_expires_at,
    }


@router.get("/v1/assignment-directory", response_model=list[MemberRequest])
def directory(actor: Actor) -> Any:
    if actor.role != "analyst":
        raise HTTPException(403, "Analyst role required")
    if actor.demo_session_id is not None:
        with get_engine().connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    text("""
              SELECT actor_id,role FROM demo_role_tokens WHERE session_id=:id
              AND role IN ('reviewer','auditor') ORDER BY role
            """),
                    {"id": actor.demo_session_id},
                ).mappings()
            ]
    people = {
        (a.actor_id, a.role)
        for a in get_settings().demo_identities.values()
        if a.role in ("reviewer", "auditor") and a.actor_id != actor.actor_id
    }
    return [{"actor_id": name, "role": role} for name, role in sorted(people)]


@router.get("/v1/cases", response_model=CasePage)
def list_cases(
    actor: Actor,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> Any:
    with get_engine().connect() as conn:
        rows = (
            conn.execute(
                text("""
          SELECT c.*,e.processing_state,r.decision AS review_decision FROM cases c
          JOIN case_members m ON m.case_id=c.id AND m.actor_id=:actor AND m.role=:role
          LEFT JOIN evaluations e ON e.id=c.current_evaluation_id
          LEFT JOIN reviews r ON r.evaluation_id=e.id
          WHERE (CAST(:session AS uuid) IS NULL OR c.id IN
            (SELECT case_id FROM demo_sessions WHERE id=CAST(:session AS uuid)
             AND revoked_at IS NULL AND expires_at>clock_timestamp()))
          ORDER BY c.created_at DESC,c.id DESC LIMIT :limit OFFSET :offset
        """),
                {
                    "actor": actor.actor_id,
                    "role": actor.role,
                    "limit": limit + 1,
                    "offset": offset,
                    "session": actor.demo_session_id,
                },
            )
            .mappings()
            .all()
        )
        return {
            "cases": [dict(r) for r in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None,
        }


@router.get("/v1/cases/{id}/workspace", response_model=WorkspaceView)
def workspace(id: UUID, actor: Actor) -> Any:
    with get_engine().begin() as conn:
        case = require_case(conn, id, actor, lock=True)
        docs = (
            conn.execute(
                text("""
          SELECT id,sha256,media_type,byte_size,created_at FROM documents WHERE case_id=:id
          ORDER BY created_at,id
        """),
                {"id": id},
            )
            .mappings()
            .all()
        )
        evaluations = (
            conn.execute(
                text("""
          SELECT e.id,e.processing_state,e.prepared_by,e.policy_id,e.created_at,
          r.decision AS review_decision FROM evaluations e LEFT JOIN reviews r
          ON r.evaluation_id=e.id WHERE e.case_id=:id
          ORDER BY (e.id=:current) DESC NULLS LAST,e.created_at DESC,e.id DESC LIMIT 51
        """),
                {"id": id, "current": case["current_evaluation_id"]},
            )
            .mappings()
            .all()
        )
        members = (
            conn.execute(
                text(
                    "SELECT actor_id,role FROM case_members WHERE case_id=:id "
                    "ORDER BY role,actor_id"
                ),
                {"id": id},
            )
            .mappings()
            .all()
        )
        return {
            "case": dict(case),
            "documents": [dict(d) for d in docs],
            "evaluations": [dict(e) for e in evaluations[:50]],
            "history_truncated": len(evaluations) > 50,
            "members": [dict(m) for m in members],
        }


@router.post("/v1/cases/{id}/members", status_code=201, response_model=MemberRequest)
def assign_member(id: UUID, body: MemberRequest, actor: Actor, key: Key) -> Any:
    if actor.demo_session_id is not None:
        raise HTTPException(403, "Guided demo roles are assigned only within their own session")
    if actor.role != "analyst":
        raise HTTPException(403, "Analyst role required")
    if (
        not any(
            a.actor_id == body.actor_id and a.role == body.role
            for a in get_settings().demo_identities.values()
        )
        or body.actor_id == actor.actor_id
    ):
        raise HTTPException(422, "Select an independent configured reviewer or auditor")
    route = f"/v1/cases/{id}/members"
    payload = body.model_dump()
    digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
    with get_engine().begin() as conn:
        require_case(conn, id, actor, lock=True)
        cached = replay(conn, actor.actor_id, route, key, digest)
        if cached:
            return cached
        inserted = conn.execute(
            text("""
          INSERT INTO case_members(case_id,actor_id,role) VALUES(:case,:actor_id,:role)
          ON CONFLICT DO NOTHING RETURNING actor_id
        """),
            {"case": id, **payload},
        ).first()
        if inserted:
            append_event(conn, id, actor.actor_id, "CASE_MEMBER_ASSIGNED", payload)
        remember(conn, actor.actor_id, route, key, digest, payload, 201)
        return payload


@router.get("/v1/cases/{id}/evaluations/{evaluation_id}/review", response_model=ReviewStateView)
def read_review(id: UUID, evaluation_id: UUID, actor: Actor) -> Any:
    with get_engine().connect() as conn:
        case = require_case(conn, id, actor)
        evaluation = (
            conn.execute(
                text("SELECT * FROM evaluations WHERE id=:id AND case_id=:case"),
                {"id": evaluation_id, "case": id},
            )
            .mappings()
            .first()
        )
        if not evaluation:
            raise HTTPException(404, "Evaluation not found")
        review = (
            conn.execute(
                text("SELECT * FROM reviews WHERE evaluation_id=:id"), {"id": evaluation_id}
            )
            .mappings()
            .first()
        )
        current = case["current_evaluation_id"] == evaluation_id
        state = (
            review["decision"]
            if review
            else ("PENDING" if evaluation["processing_state"] == "DRAFT_READY" else "NOT_READY")
        )
        return {
            "state": state,
            "current": current,
            "review": dict(review) if review else None,
            "can_review": bool(
                actor.role == "reviewer"
                and current
                and state == "PENDING"
                and evaluation["prepared_by"] != actor.actor_id
            ),
        }


@router.post(
    "/v1/cases/{id}/evaluations/{evaluation_id}/review", status_code=201, response_model=ReviewView
)
def submit_review(
    id: UUID, evaluation_id: UUID, body: ReviewRequest, actor: Actor, key: Key
) -> Any:
    if actor.role != "reviewer":
        raise HTTPException(403, "Independent reviewer role required")
    route = f"/v1/cases/{id}/evaluations/{evaluation_id}/review"
    digest = hashlib.sha256(canonical(body.model_dump()).encode()).hexdigest()
    with get_engine().begin() as conn:
        case = require_case(conn, id, actor, lock=True)
        cached = replay(conn, actor.actor_id, route, key, digest)
        if cached:
            return cached
        evaluation = (
            conn.execute(
                text("""
          SELECT e.*,d.evaluation_id AS draft_id FROM evaluations e
          LEFT JOIN ai_drafts d ON d.evaluation_id=e.id WHERE e.id=:id AND e.case_id=:case
        """),
                {"id": evaluation_id, "case": id},
            )
            .mappings()
            .first()
        )
        if not evaluation:
            raise HTTPException(404, "Evaluation not found")
        if evaluation["prepared_by"] == actor.actor_id:
            raise HTTPException(403, "The preparer cannot review the same evaluation")
        reviewed = conn.execute(
            text("SELECT 1 FROM reviews WHERE evaluation_id=:id"), {"id": evaluation_id}
        ).first()
        if (
            case["current_evaluation_id"] != evaluation_id
            or evaluation["processing_state"] != "DRAFT_READY"
            or not evaluation["draft_id"]
            or reviewed
        ):
            raise HTTPException(409, "Review requires the current unreviewed ready draft")
        row = (
            conn.execute(
                text("""
          INSERT INTO reviews(id,evaluation_id,reviewer_id,decision,reason)
          VALUES(:id,:eval,:actor,:decision,:reason) RETURNING *
        """),
                {
                    "id": uuid4(),
                    "eval": evaluation_id,
                    "actor": actor.actor_id,
                    "decision": body.decision,
                    "reason": body.reason,
                },
            )
            .mappings()
            .one()
        )
        result = ReviewView.model_validate(row).model_dump(mode="json")
        append_event(conn, id, actor.actor_id, "HUMAN_REVIEW_RECORDED", result)
        remember(conn, actor.actor_id, route, key, digest, result, 201)
        return result
