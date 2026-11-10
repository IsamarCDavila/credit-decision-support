import hashlib
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Connection, Engine, text

from credit_support.audit import append_event, canonical
from credit_support.financial import FORMULA_VERSION, FinancialFact, calculate_dscr
from credit_support.idempotency import remember, replay
from credit_support.ingestion import extract, require_case
from credit_support.parsers import PARSER_VERSION
from credit_support.policy_catalog import PolicyError, load_policy, select_policy
from credit_support.settings import Identity


def queue_policy_check(
    engine: Engine, case_id: UUID, source_id: UUID, actor: Identity, key: str
) -> dict[str, str]:
    if actor.role != "analyst":
        raise HTTPException(403, "Analyst role required")
    route = f"/v1/cases/{case_id}/evaluate"
    request_hash = hashlib.sha256(
        canonical({"source_evaluation_id": str(source_id)}).encode()
    ).hexdigest()
    with engine.begin() as conn:
        case = require_case(conn, case_id, actor, lock=True)
        cached = replay(conn, actor.actor_id, route, key, request_hash)
        if cached:
            return cached
        source = (
            conn.execute(
                text("""
          SELECT e.* FROM evaluations e JOIN jobs j ON j.evaluation_id=e.id
          WHERE e.id=:source AND e.case_id=:case AND j.step='extract_documents'
          AND j.status='SUCCEEDED'
        """),
                {"source": source_id, "case": case_id},
            )
            .mappings()
            .first()
        )
        if not source:
            raise HTTPException(409, "A successful extraction from this case is required")
        doc_ids: Sequence[UUID] = (
            conn.execute(
                text("SELECT id FROM documents WHERE case_id=:id ORDER BY id"), {"id": case_id}
            )
            .scalars()
            .all()
        )
        current_docs = [str(value) for value in doc_ids]
        if current_docs != [d["document_id"] for d in source["snapshot"]["documents"]]:
            raise HTTPException(409, "Extraction is stale; extract the current document set first")
        try:
            policy = select_policy(conn, case)
        except PolicyError as exc:
            raise HTTPException(409, str(exc)) from exc
        snapshot = {
            "purpose": "POLICY_CHECK_ONLY",
            "documents": source["snapshot"]["documents"],
            "source_evaluation_id": str(source_id),
            "policy": {
                "id": policy.specification.id,
                "content_sha256": policy.content_sha256,
                "template_version": policy.specification.template_version,
            },
            "formula_version": FORMULA_VERSION,
        }
        digest = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
        existing = (
            conn.execute(
                text("""
          SELECT e.id AS evaluation_id,j.id AS job_id FROM evaluations e JOIN jobs j
          ON j.evaluation_id=e.id AND j.step='evaluate_policy'
          WHERE e.case_id=:case AND e.input_hash=:hash
        """),
                {"case": case_id, "hash": digest},
            )
            .mappings()
            .first()
        )
        if existing:
            receipt = {name: str(value) for name, value in existing.items()}
        else:
            evaluation_id, job_id = uuid4(), uuid4()
            conn.execute(
                text("""
              INSERT INTO evaluations
              (id,case_id,prepared_by,policy_id,input_hash,snapshot,versions,processing_state)
              VALUES(:id,:case,:actor,:policy,:hash,CAST(:snapshot AS jsonb),
                     CAST(:versions AS jsonb),'DOCUMENTS_RECEIVED')
            """),
                {
                    "id": evaluation_id,
                    "case": case_id,
                    "actor": actor.actor_id,
                    "policy": policy.specification.id,
                    "hash": digest,
                    "snapshot": canonical(snapshot),
                    "versions": canonical(
                        {
                            "extraction": PARSER_VERSION,
                            "formula": FORMULA_VERSION,
                            "policy_template": policy.specification.template_version,
                        }
                    ),
                },
            )
            for doc in snapshot["documents"]:
                conn.execute(
                    text("INSERT INTO evaluation_documents VALUES(:eval,:doc)"),
                    {"eval": evaluation_id, "doc": doc["document_id"]},
                )
            conn.execute(
                text("""
              INSERT INTO jobs(id,evaluation_id,step,input_hash,status)
              VALUES(:id,:eval,'evaluate_policy',:hash,'READY')
            """),
                {"id": job_id, "eval": evaluation_id, "hash": digest},
            )
            receipt = {"evaluation_id": str(evaluation_id), "job_id": str(job_id)}
            append_event(
                conn,
                case_id,
                actor.actor_id,
                "POLICY_CHECK_QUEUED",
                {**receipt, "policy_version": policy.specification.id},
            )
        conn.execute(
            text("UPDATE cases SET current_evaluation_id=:eval WHERE id=:id"),
            {"eval": receipt["evaluation_id"], "id": case_id},
        )
        remember(conn, actor.actor_id, route, key, request_hash, receipt, 202)
        return receipt


def evaluate_policy(conn: Connection, evaluation_id: UUID) -> dict[str, Any]:
    evaluation = (
        conn.execute(text("SELECT * FROM evaluations WHERE id=:id"), {"id": evaluation_id})
        .mappings()
        .one()
    )
    case = (
        conn.execute(text("SELECT * FROM cases WHERE id=:id"), {"id": evaluation["case_id"]})
        .mappings()
        .one()
    )
    policy = load_policy(conn, evaluation["policy_id"])
    if (
        evaluation["snapshot"]["policy"]["content_sha256"] != policy.content_sha256
        or select_policy(conn, case).specification.id != policy.specification.id
        or evaluation["snapshot"]["formula_version"] != FORMULA_VERSION
    ):
        raise PolicyError("Pinned policy or formula does not match the evaluation snapshot")
    extraction = extract(conn, evaluation_id)
    facts = (
        conn.execute(
            text("SELECT * FROM facts WHERE evaluation_id=:id ORDER BY key"), {"id": evaluation_id}
        )
        .mappings()
        .all()
    )
    typed = [
        FinancialFact(
            id=f["id"],
            key=f["key"],
            value=f["value"],
            status=f["status"],
            currency=f["currency"],
            unit=f["unit"],
            period_start=f["period_start"],
            period_end=f["period_end"],
        )
        for f in facts
    ]
    metric = calculate_dscr(typed)
    input_ids = [f.id for f in typed if f.key in ("available_cash_flow", "debt_service")]
    calculation_id = uuid4()
    details = {
        "reason": metric.reason,
        "display_value": metric.display,
        "numerator": str(metric.numerator) if metric.numerator is not None else None,
        "denominator": str(metric.denominator) if metric.denominator is not None else None,
        "comparison": "exact_cross_multiplication",
        "decimal_precision": 80,
    }
    conn.execute(
        text("""
      INSERT INTO calculations
      (id,evaluation_id,formula_id,formula_version,input_fact_ids,result,status,details)
      VALUES(:id,:eval,'DSCR',:version,:inputs,:result,:status,CAST(:details AS jsonb))
    """),
        {
            "id": calculation_id,
            "eval": evaluation_id,
            "version": FORMULA_VERSION,
            "inputs": input_ids,
            "result": metric.ratio,
            "status": metric.status,
            "details": canonical(details),
        },
    )
    rule = policy.specification.rules[0]
    passes = metric.meets(Decimal(rule.threshold))
    rule_status = "REQUIRES_REVIEW" if passes is None else "PASS" if passes else "FAIL"
    quality = extraction["exceptions"]
    outcome = (
        "insufficient_evidence"
        if passes is None or quality
        else "meets_rules"
        if passes
        else "exceptions"
    )
    result = {
        "policy_version": policy.specification.id,
        "simulation": True,
        "outcome": outcome,
        "rule_results": [
            {
                "rule_id": rule.id,
                "formula_id": rule.formula,
                "operator": rule.operator,
                "threshold": rule.threshold,
                "status": rule_status,
                "calculation_id": str(calculation_id),
                "policy_fragment_id": rule.id,
            }
        ],
        "data_quality_exceptions": quality,
        "citations": [f.model_dump() for f in policy.fragments],
    }
    conn.execute(
        text("UPDATE evaluations SET processing_state='POLICY_CHECK' WHERE id=:id"),
        {"id": evaluation_id},
    )
    conn.execute(
        text("""
      INSERT INTO policy_checks(evaluation_id,policy_id,result)
      VALUES(:id,:policy,CAST(:result AS jsonb))
    """),
        {"id": evaluation_id, "policy": policy.specification.id, "result": canonical(result)},
    )
    for fragment in policy.fragments:
        conn.execute(
            text("INSERT INTO policy_check_citations VALUES(:eval,:policy,:fragment)"),
            {
                "eval": evaluation_id,
                "policy": policy.specification.id,
                "fragment": fragment.fragment_id,
            },
        )
    return {
        "simulation": True,
        "purpose": "POLICY_CHECK_ONLY",
        "outcome": outcome,
        "policy_version": policy.specification.id,
        "calculation_id": str(calculation_id),
    }
