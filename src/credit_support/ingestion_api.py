from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text

from credit_support.db import get_engine
from credit_support.ingestion import queue_extraction, require_case, upload
from credit_support.parsers import MAX_FILE_BYTES, IngestionError
from credit_support.policy_models import CalculationView, PolicyCheckView
from credit_support.schemas import UTCTimestamp
from credit_support.security import identity
from credit_support.settings import Identity

router = APIRouter()
Actor = Annotated[Identity, Depends(identity)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


class DocumentReceipt(BaseModel):
    document_id: UUID
    sha256: str
    media_type: Literal["text/csv", "application/pdf"]
    byte_size: int
    synthetic: Literal[True]


class DocumentView(DocumentReceipt):
    metadata: dict[str, str]
    parser_version: str
    pages: list[str]
    rows: list[dict[str, str]]


class ExtractionReceipt(BaseModel):
    evaluation_id: UUID
    job_id: UUID


class FactView(BaseModel):
    id: UUID
    key: str
    value: str | None
    currency: str | None
    unit: str
    period_start: str
    period_end: str
    status: Literal["extracted", "missing", "ambiguous", "invalid"]
    evidence_ids: list[UUID]


class EvidenceView(BaseModel):
    id: UUID
    document_id: UUID
    sha256: str
    locator: dict[str, Any]
    excerpt: str
    parser_version: str


class ExtractionView(BaseModel):
    evaluation_id: UUID
    processing_state: str
    job_status: str
    current: bool
    simulation: Literal[True]
    snapshot: dict[str, Any]
    result: dict[str, Any] | None
    created_at: UTCTimestamp
    facts: list[FactView]
    evidence: list[EvidenceView]
    policy_id: str | None = None
    calculations: list[CalculationView] = []
    policy_check: PolicyCheckView | None = None


@router.post("/v1/cases/{id}/documents", status_code=202, response_model=DocumentReceipt)
def upload_document(
    id: UUID,
    actor: Actor,
    key: Key,
    file: Annotated[UploadFile, File()],
    synthetic: Annotated[bool, Form()],
) -> Any:
    if not synthetic:
        raise HTTPException(422, "Only declared synthetic documents are accepted")
    with get_engine().connect() as conn:
        require_case(conn, id, actor)
    if actor.role != "analyst":
        raise HTTPException(403, "Analyst role required")
    extension = PurePosixPath((file.filename or "").replace("\\", "/")).suffix.lower()
    expected = {".pdf": "application/pdf", ".csv": "text/csv"}.get(extension)
    if expected is None or file.content_type != expected:
        raise HTTPException(422, "Filename extension and media type must match PDF or CSV")
    try:
        data = file.file.read(MAX_FILE_BYTES + 1)
    finally:
        file.file.close()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Document exceeds 10 MiB")
    try:
        return upload(get_engine(), id, actor, key, data, expected)
    except IngestionError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/v1/cases/{id}/documents/{document_id}", response_model=DocumentView)
def document_detail(id: UUID, document_id: UUID, actor: Actor) -> Any:
    with get_engine().connect() as conn:
        require_case(conn, id, actor)
        row = (
            conn.execute(
                text("""
          SELECT d.*,dc.parsed FROM documents d JOIN document_contents dc ON dc.document_id=d.id
          WHERE d.id=:doc AND d.case_id=:case
        """),
                {"doc": document_id, "case": id},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Document not found")
        parsed = row["parsed"]
        return {
            "document_id": row["id"],
            "sha256": row["sha256"],
            "media_type": row["media_type"],
            "byte_size": row["byte_size"],
            "synthetic": True,
            "metadata": parsed["metadata"],
            "parser_version": parsed["parser_version"],
            "pages": parsed["pages"],
            "rows": parsed["rows"],
        }


@router.get("/v1/cases/{id}/documents/{document_id}/content")
def document_content(id: UUID, document_id: UUID, actor: Actor) -> Response:
    with get_engine().connect() as conn:
        require_case(conn, id, actor)
        row = (
            conn.execute(
                text("""
          SELECT d.media_type,d.sha256,dc.data FROM documents d
          JOIN document_contents dc ON dc.document_id=d.id WHERE d.id=:doc AND d.case_id=:case
        """),
                {"doc": document_id, "case": id},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Document not found")
        suffix = ".pdf" if row["media_type"] == "application/pdf" else ".csv"
        return Response(
            bytes(row["data"]),
            media_type=row["media_type"],
            headers={
                "Content-Disposition": f'attachment; filename="synthetic-{document_id}{suffix}"',
                "X-Content-Type-Options": "nosniff",
                "ETag": '"' + row["sha256"] + '"',
            },
        )


@router.post("/v1/cases/{id}/extract", status_code=202, response_model=ExtractionReceipt)
def start_extraction(id: UUID, actor: Actor, key: Key) -> Any:
    return queue_extraction(get_engine(), id, actor, key)


@router.get("/v1/cases/{id}/evaluations/{evaluation_id}", response_model=ExtractionView)
def extraction_detail(id: UUID, evaluation_id: UUID, actor: Actor) -> Any:
    with get_engine().connect() as conn:
        case = require_case(conn, id, actor)
        evaluation = (
            conn.execute(
                text("""
          SELECT e.*,j.status AS job_status,j.result FROM evaluations e JOIN jobs j
          ON j.evaluation_id=e.id AND j.step IN ('extract_documents','evaluate_policy')
          WHERE e.id=:eval AND e.case_id=:case
        """),
                {"eval": evaluation_id, "case": id},
            )
            .mappings()
            .first()
        )
        if not evaluation:
            raise HTTPException(404, "Evaluation not found")
        rows = (
            conn.execute(
                text("SELECT * FROM facts WHERE evaluation_id=:id ORDER BY key"),
                {"id": evaluation_id},
            )
            .mappings()
            .all()
        )
        facts = []
        for row in rows:
            links: Sequence[UUID] = (
                conn.execute(
                    text("SELECT evidence_id FROM fact_evidence WHERE fact_id=:id"),
                    {"id": row["id"]},
                )
                .scalars()
                .all()
            )
            facts.append(
                {
                    **row,
                    "value": format(row["value"], ".2f") if row["value"] is not None else None,
                    "period_start": row["period_start"].isoformat(),
                    "period_end": row["period_end"].isoformat(),
                    "evidence_ids": links,
                }
            )
        evidence = (
            conn.execute(
                text("""
          SELECT e.*,d.sha256 FROM evidence e JOIN documents d ON d.id=e.document_id
          WHERE e.evaluation_id=:id ORDER BY e.id
        """),
                {"id": evaluation_id},
            )
            .mappings()
            .all()
        )
        calculations = []
        for item in conn.execute(
            text("SELECT * FROM calculations WHERE evaluation_id=:id ORDER BY formula_id"),
            {"id": evaluation_id},
        ).mappings():
            calculations.append(
                {
                    **item,
                    "value": item["details"].get("display_value"),
                    "unrounded_value": str(item["result"]) if item["result"] is not None else None,
                }
            )
        policy_check: dict[str, Any] | None = conn.execute(
            text("SELECT result FROM policy_checks WHERE evaluation_id=:id"), {"id": evaluation_id}
        ).scalar_one_or_none()
        return {
            "evaluation_id": evaluation_id,
            "processing_state": evaluation["processing_state"],
            "job_status": evaluation["job_status"],
            "current": case["current_evaluation_id"] == evaluation_id,
            "simulation": True,
            "snapshot": evaluation["snapshot"],
            "result": evaluation["result"],
            "created_at": evaluation["created_at"],
            "facts": facts,
            "evidence": evidence,
            "policy_id": evaluation["policy_id"],
            "calculations": calculations,
            "policy_check": policy_check,
        }
