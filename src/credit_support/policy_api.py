from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from credit_support.db import get_engine
from credit_support.ingestion import require_case
from credit_support.ingestion_api import ExtractionReceipt, Key
from credit_support.policy_catalog import PolicyError, load_policy, select_policy
from credit_support.policy_engine import queue_policy_check
from credit_support.policy_models import EvaluateRequest, PolicyView, RetrievalHit
from credit_support.security import identity
from credit_support.settings import Identity

router = APIRouter()
Actor = Annotated[Identity, Depends(identity)]


@router.get("/v1/policies", response_model=list[str])
def policy_versions(_actor: Actor, limit: Annotated[int, Query(ge=1, le=100)] = 50) -> Any:
    with get_engine().connect() as conn:
        return (
            conn.execute(
                text("""
          SELECT p.id FROM policy_versions p JOIN policy_contents c ON c.policy_id=p.id
          WHERE p.published_at IS NOT NULL ORDER BY p.valid_from,p.id LIMIT :limit
        """),
                {"limit": limit},
            )
            .scalars()
            .all()
        )


@router.get("/v1/policies/{policy_version}", response_model=PolicyView)
def policy_detail(policy_version: str, _actor: Actor) -> PolicyView:
    with get_engine().connect() as conn:
        try:
            return load_policy(conn, policy_version)
        except PolicyError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.get("/v1/policies/{policy_version}/fragments", response_model=list[RetrievalHit])
def retrieve_fragments(
    policy_version: str,
    _actor: Actor,
    q: Annotated[str, Query(min_length=1, max_length=300)],
    locale: Literal["en", "es"] = "en",
    limit: Annotated[int, Query(ge=1, le=10)] = 3,
) -> Any:
    with get_engine().connect() as conn:
        try:
            load_policy(conn, policy_version)
        except PolicyError as exc:
            raise HTTPException(409, str(exc)) from exc
        language = "english" if locale == "en" else "spanish"
        # Column names are selected exclusively from the validated locale enum.
        query = f"""
          SELECT policy_id AS policy_version,id AS fragment_id,:locale AS locale,
          text_{locale} AS text,sha256,ts_rank(search_{locale},query) AS score
          FROM policy_fragments,websearch_to_tsquery('{language}',:q) query
          WHERE policy_id=:policy AND search_{locale} @@ query
          ORDER BY score DESC,ordinal LIMIT :limit
        """
        return (
            conn.execute(
                text(query), {"q": q, "policy": policy_version, "locale": locale, "limit": limit}
            )
            .mappings()
            .all()
        )


@router.get("/v1/cases/{id}/policy", response_model=PolicyView)
def applicable_policy(id: UUID, actor: Actor) -> PolicyView:
    with get_engine().connect() as conn:
        case = require_case(conn, id, actor)
        try:
            return select_policy(conn, case)
        except PolicyError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.post("/v1/cases/{id}/evaluate", response_model=ExtractionReceipt, status_code=202)
def evaluate(id: UUID, body: EvaluateRequest, actor: Actor, key: Key) -> Any:
    return queue_policy_check(get_engine(), id, body.source_evaluation_id, actor, key)
