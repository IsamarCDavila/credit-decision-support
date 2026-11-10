"""Reconstruct export snapshots and verify retained sources and the audit chain."""

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy import text

from credit_support.ai_models import AIDraft
from credit_support.audit import canonical
from credit_support.db import get_engine
from credit_support.financial import FORMULA_VERSION, FinancialFact, calculate_dscr
from credit_support.ingestion import require_case
from credit_support.ingestion_api import Actor, extraction_detail
from credit_support.parsers import IngestionError, parse_document
from credit_support.policy_catalog import PolicyError, load_policy

router = APIRouter()


def verify_audit(rows: list[Any]) -> str | None:
    previous = None
    for sequence, row in enumerate(rows, 1):
        event = {
            "id": str(row["id"]),
            "case_id": str(row["case_id"]),
            "sequence": row["sequence"],
            "actor_id": row["actor_id"],
            "kind": row["kind"],
            "payload": row["payload"],
            "previous_hash": row["previous_hash"],
            "created_at": row["created_at"].astimezone(UTC).isoformat(),
        }
        digest = hashlib.sha256(canonical(event).encode()).hexdigest()
        if (
            sequence != row["sequence"]
            or previous != row["previous_hash"]
            or digest != row["event_hash"]
        ):
            raise HTTPException(409, "Audit chain integrity verification failed")
        previous = digest
    return previous


def reconstruct(case_id: UUID, evaluation_id: UUID, actor: Any, locale: str) -> dict[str, Any]:
    with get_engine().begin() as conn:
        case = require_case(conn, case_id, actor, lock=True)
        value = extraction_detail(case_id, evaluation_id, actor)
        if value["processing_state"] != "DRAFT_READY" or not value["ai_draft"]:
            raise HTTPException(409, "A ready draft is required for report export")
        stored = (
            conn.execute(
                text("SELECT * FROM ai_drafts WHERE evaluation_id=:id"), {"id": evaluation_id}
            )
            .mappings()
            .one()
        )
        if hashlib.sha256(canonical(stored["draft"]).encode()).hexdigest() != stored["sha256"]:
            raise HTTPException(409, "Draft integrity verification failed")
        AIDraft.model_validate(stored["draft"])
        docs = (
            conn.execute(
                text("""
          SELECT d.*,dc.data,dc.parsed FROM evaluation_documents ed JOIN documents d
          ON d.id=ed.document_id JOIN document_contents dc ON dc.document_id=d.id
          WHERE ed.evaluation_id=:id ORDER BY d.id
        """),
                {"id": evaluation_id},
            )
            .mappings()
            .all()
        )
        bindings = [
            {
                "document_id": str(d["id"]),
                "sha256": d["sha256"],
                "parser_version": d["parsed"]["parser_version"],
            }
            for d in docs
        ]
        if bindings != value["snapshot"]["documents"]:
            raise HTTPException(409, "Pinned document bindings failed verification")
        by_doc = {d["id"]: d for d in docs}
        for doc in docs:
            if hashlib.sha256(bytes(doc["data"])).hexdigest() != doc["sha256"]:
                raise HTTPException(409, "Document checksum verification failed")
            try:
                if parse_document(bytes(doc["data"]), doc["media_type"]) != doc["parsed"]:
                    raise IngestionError("Retained parser output mismatch")
            except IngestionError as exc:
                raise HTTPException(409, "Document reconstruction verification failed") from exc
        try:
            for evidence in value["evidence"]:
                doc = by_doc[evidence["document_id"]]
                loc, parsed = evidence["locator"], doc["parsed"]
                excerpt = (
                    parsed["rows"][loc["row"] - 2][loc["column"]]
                    if doc["media_type"] == "text/csv"
                    else parsed["pages"][loc["page"] - 1][loc["start"] : loc["end"]]
                )
                if excerpt != evidence["excerpt"]:
                    raise ValueError("Source locator mismatch")
            policy = load_policy(conn, value["policy_id"])
            if policy.content_sha256 != value["snapshot"]["policy"]["content_sha256"]:
                raise ValueError("Policy hash mismatch")
        except (KeyError, IndexError, ValueError, PolicyError) as exc:
            raise HTTPException(409, "Source or policy integrity verification failed") from exc
        facts = [
            FinancialFact(
                id=f["id"],
                key=f["key"],
                value=Decimal(f["value"]) if f["value"] is not None else None,
                status=f["status"],
                currency=f["currency"],
                unit=f["unit"],
                period_start=date.fromisoformat(f["period_start"]),
                period_end=date.fromisoformat(f["period_end"]),
            )
            for f in value["facts"]
        ]
        metric = calculate_dscr(facts)
        calculation = value["calculations"][0]
        inputs = {f.id for f in facts if f.key in ("available_cash_flow", "debt_service")}
        check = value["policy_check"]
        rule = check["rule_results"][0]
        passes = metric.meets(Decimal(policy.specification.rules[0].threshold))
        rule_status = "REQUIRES_REVIEW" if passes is None else "PASS" if passes else "FAIL"
        if (
            metric.status != calculation["status"]
            or metric.display != calculation["value"]
            or calculation["formula_version"] != FORMULA_VERSION
            or value["snapshot"]["formula_version"] != FORMULA_VERSION
            or set(calculation["input_fact_ids"]) != inputs
            or (
                Decimal(calculation["unrounded_value"])
                if calculation["unrounded_value"] is not None
                else None
            )
            != metric.ratio
            or rule["status"] != rule_status
            or rule["threshold"] != policy.specification.rules[0].threshold
            or check["citations"] != [c.model_dump() for c in policy.fragments]
        ):
            raise HTTPException(409, "Financial reconstruction verification failed")
        review = (
            conn.execute(
                text("SELECT * FROM reviews WHERE evaluation_id=:id"), {"id": evaluation_id}
            )
            .mappings()
            .first()
        )
        events = (
            conn.execute(
                text("""
          SELECT * FROM audit_events WHERE case_id=:id ORDER BY sequence LIMIT 2001
        """),
                {"id": case_id},
            )
            .mappings()
            .all()
        )
        if len(events) > 2000:
            raise HTTPException(413, "Report audit-event limit exceeded")
        head = verify_audit(list(events))
        document_views = [
            {
                "id": d["id"],
                "sha256": d["sha256"],
                "media_type": d["media_type"],
                "byte_size": d["byte_size"],
                "metadata": d["parsed"]["metadata"],
            }
            for d in docs
        ]
        body: dict[str, Any] = jsonable_encoder(
            {
                "report_version": "review-report-v1",
                "generated_at": datetime.now(UTC).isoformat(),
                "locale": locale,
                "simulation": True,
                "marker": "SIMULATION" if locale == "en" else "SIMULACIÓN",
                "case": dict(case),
                "evaluation": value,
                "documents": document_views,
                "review": {
                    "state": review["decision"] if review else "PENDING",
                    "record": dict(review) if review else None,
                },
                "policy": policy.model_dump(mode="json"),
                "audit_events": [dict(e) for e in events],
                "notice": (
                    "Synthetic analysis and human review only; no real credit authorization."
                    if locale == "en"
                    else "Análisis y revisión humana sintéticos; no autoriza créditos reales."
                ),
            },
            custom_encoder={datetime: lambda value: value.astimezone(UTC).isoformat()},
        )
        if len(canonical(body).encode()) > 2_000_000:
            raise HTTPException(413, "Report exceeds the 2 MB export limit")
        body["integrity"] = {
            "payload_sha256": hashlib.sha256(canonical(body).encode()).hexdigest(),
            "audit_chain_verified": True,
            "audit_head": head,
            "document_hashes_verified": True,
            "source_locators_verified": True,
            "draft_hash_verified": True,
            "policy_hash_verified": True,
            "financial_reconstruction_verified": True,
        }
        return body


@router.get(
    "/v1/cases/{id}/evaluations/{evaluation_id}/report.json",
    response_class=Response,
    responses={
        200: {
            "description": "Verified simulation snapshot",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    },
)
def json_report(
    id: UUID, evaluation_id: UUID, actor: Actor, locale: Literal["en", "es"] = "en"
) -> Response:
    body = reconstruct(id, evaluation_id, actor, locale)
    return Response(
        canonical(body),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="simulation-{evaluation_id}-{locale}.json"'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/v1/cases/{id}/evaluations/{evaluation_id}/report.pdf",
    response_class=Response,
    responses={
        200: {
            "description": "Simulation PDF with embedded JSON snapshot",
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def pdf_report(
    id: UUID, evaluation_id: UUID, actor: Actor, locale: Literal["en", "es"] = "en"
) -> Response:
    from credit_support.report_pdf import render_pdf

    return Response(
        render_pdf(reconstruct(id, evaluation_id, actor, locale)),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="simulation-{evaluation_id}-{locale}.pdf"'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
