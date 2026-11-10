"""Bounded model roles around immutable evidence and deterministic financial tools."""

import hashlib
from collections import Counter
from threading import Event, Thread
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, text

from credit_support.ai_models import (
    AIDraft,
    AIRequest,
    ClaimCard,
    DraftSelection,
    ExtractionProposal,
    GeneralistProposal,
    Section,
)
from credit_support.ai_prompts import DRAFT, EXTRACT, GENERALIST, PROMPT_VERSION
from credit_support.audit import append_event, canonical
from credit_support.db import get_engine
from credit_support.ingestion_api import Actor, ExtractionReceipt, Key
from credit_support.llm import ModelError, call_model
from credit_support.parsers import FIELDS, IngestionError
from credit_support.policy_catalog import PolicyError
from credit_support.policy_engine import evaluate_policy, queue_policy_check
from credit_support.settings import get_settings

router = APIRouter()
SECTIONS = ["overview", "financials", "policy", "limitations"]
CLAIM_IDS = [
    *("fact:" + key for key in FIELDS),
    "calculation:DSCR",
    "rule:DSCR_MINIMUM",
    "review:required",
    "limitation:simulation",
]


@router.post("/v1/cases/{id}/ai-evaluate", status_code=202, response_model=ExtractionReceipt)
def start_ai(id: UUID, body: AIRequest, actor: Actor, key: Key) -> Any:
    settings = get_settings()
    if body.provider == "openai" and (not settings.llm_live_enabled or not settings.openai_api_key):
        raise HTTPException(409, "OpenAI is disabled or its API key is missing")
    return queue_policy_check(
        get_engine(),
        id,
        body.source_evaluation_id,
        actor,
        key,
        ai={
            "provider": body.provider,
            "workflow": body.workflow,
            "model": settings.llm_model
            if body.provider == "openai"
            else "deterministic-fixture-v1",
            "prompt_version": PROMPT_VERSION,
        },
    )


def source_units(engine: Engine, evaluation_id: UUID) -> list[dict[str, str]]:
    units: list[dict[str, str]] = []
    with engine.connect() as conn:
        docs = (
            conn.execute(
                text("""
          SELECT d.id,dc.parsed FROM evaluation_documents ed JOIN documents d
          ON d.id=ed.document_id JOIN document_contents dc ON dc.document_id=d.id
          WHERE ed.evaluation_id=:id ORDER BY d.id
        """),
                {"id": evaluation_id},
            )
            .mappings()
            .all()
        )
    for doc in docs:
        parsed = doc["parsed"]
        if parsed["rows"]:
            for row in parsed["rows"]:
                units.append(
                    {
                        "source_id": f"S{len(units) + 1:06}",
                        "text": f"{row['key']}: {row['value']}",
                        "key": row["key"],
                        "raw_value": row["value"],
                    }
                )
        else:
            for candidate in parsed["candidates"]:
                units.append(
                    {
                        "source_id": f"S{len(units) + 1:06}",
                        "text": f"{candidate['key']}: {candidate['raw']}",
                        "key": candidate["key"],
                        "raw_value": candidate["raw"],
                    }
                )
    return units


def extraction_schema(model: type[BaseModel], units: list[dict[str, str]]) -> dict[str, Any]:
    if not units or len(units) > 500:
        raise ModelError("MODEL_SOURCE_LIMIT")
    schema = model.model_json_schema()
    schema["$defs"]["Observation"]["properties"]["source_id"]["enum"] = [
        unit["source_id"] for unit in units
    ]
    return schema


def expected_extraction(units: list[dict[str, str]]) -> dict[str, Any]:
    observations = [
        {"key": u["key"], "source_id": u["source_id"], "raw_value": u["raw_value"]}
        for u in units
        if u["key"] in FIELDS and u["raw_value"].strip()
    ]
    present = {o["key"] for o in observations}
    return {"observations": observations, "missing_keys": [k for k in FIELDS if k not in present]}


def validate_extraction(proposal: ExtractionProposal, units: list[dict[str, str]]) -> None:
    expected = expected_extraction(units)
    actual = Counter((o.key, o.source_id, o.raw_value) for o in proposal.observations)
    supported = Counter(
        (o["key"], o["source_id"], o["raw_value"]) for o in expected["observations"]
    )
    if actual != supported or sorted(proposal.missing_keys) != sorted(expected["missing_keys"]):
        raise ModelError("EXTRACTION_NOT_FULLY_SOURCE_SUPPORTED")


def validate_selection(selection: DraftSelection) -> None:
    if Counter(selection.claim_ids) != Counter(CLAIM_IDS) or Counter(
        selection.section_order
    ) != Counter(SECTIONS):
        raise ModelError("DRAFT_CITATIONS_OR_COVERAGE_INVALID")


def claim_cards(engine: Engine, evaluation_id: UUID) -> list[ClaimCard]:
    cards = []
    with engine.connect() as conn:
        facts = (
            conn.execute(
                text("SELECT * FROM facts WHERE evaluation_id=:id ORDER BY key"),
                {"id": evaluation_id},
            )
            .mappings()
            .all()
        )
        for fact in facts:
            evidence: list[UUID] = list(
                conn.execute(
                    text("SELECT evidence_id FROM fact_evidence WHERE fact_id=:id"),
                    {"id": fact["id"]},
                ).scalars()
            )
            value = format(fact["value"], ".2f") + " USD" if fact["status"] == "extracted" else "—"
            cards.append(
                ClaimCard(
                    id="fact:" + fact["key"],
                    section="financials",
                    text_en=f"{fact['key']}: {value}; evidence status: {fact['status']}.",
                    text_es=f"{fact['key']}: {value}; estado de evidencia: {fact['status']}.",
                    fact_ids=[fact["id"]],
                    evidence_ids=evidence,
                    calculation_ids=[],
                    policy_fragment_ids=[],
                )
            )
        calc = (
            conn.execute(
                text("SELECT * FROM calculations WHERE evaluation_id=:id"), {"id": evaluation_id}
            )
            .mappings()
            .one()
        )
        check: dict[str, Any] = conn.execute(
            text("SELECT result FROM policy_checks WHERE evaluation_id=:id"), {"id": evaluation_id}
        ).scalar_one()
        refs = {
            "fact_ids": calc["input_fact_ids"],
            "evidence_ids": [],
            "calculation_ids": [calc["id"]],
            "policy_fragment_ids": ["dscr-definition"],
        }
        display = calc["details"].get("display_value") or "—"
        cards.append(
            ClaimCard(
                id="calculation:DSCR",
                section="financials",
                text_en=f"DSCR: {display}; calculation status: {calc['status']}.",
                text_es=f"DSCR: {display}; estado del cálculo: {calc['status']}.",
                **refs,
            )
        )
        rule = check["rule_results"][0]
        cards.append(
            ClaimCard(
                id="rule:DSCR_MINIMUM",
                section="policy",
                text_en=(
                    f"{check['policy_version']}: DSCR >= {rule['threshold']}; "
                    f"{rule['status']}. Overall outcome: {check['outcome']}."
                ),
                text_es=(
                    f"{check['policy_version']}: DSCR >= {rule['threshold']}; "
                    f"{rule['status']}. Resultado global: {check['outcome']}."
                ),
                **{**refs, "policy_fragment_ids": ["DSCR_MINIMUM"]},
            )
        )
    for cid, section, en, es in [
        (
            "review:required",
            "overview",
            "Independent human review is required; this draft is not a credit decision.",
            "Se requiere revisión humana independiente; "
            "este borrador no constituye una decisión crediticia.",
        ),
        (
            "limitation:simulation",
            "limitations",
            "SIMULATION. Synthetic statements and a demonstration policy only.",
            "SIMULACIÓN. Solo estados sintéticos y una política de demostración.",
        ),
    ]:
        cards.append(
            ClaimCard(
                id=cid,
                section=cast(Section, section),
                text_en=en,
                text_es=es,
                fact_ids=[],
                evidence_ids=[],
                calculation_ids=[],
                policy_fragment_ids=[],
            )
        )
    return cards


def locked_job(conn: Any, job: dict[str, Any]) -> Any:
    case_id = conn.execute(
        text("SELECT case_id FROM evaluations WHERE id=:id"), {"id": job["evaluation_id"]}
    ).scalar_one()
    conn.execute(text("SELECT id FROM cases WHERE id=:id FOR UPDATE"), {"id": case_id})
    active = conn.execute(
        text("""
      SELECT id FROM jobs WHERE id=:id AND lease_token=:token AND status='RUNNING'
      AND lease_until>clock_timestamp() FOR UPDATE
    """),
        {"id": job["id"], "token": job["lease_token"]},
    ).first()
    if not active:
        raise ModelError("WORKER_LEASE_LOST")
    return case_id


def run_ai(engine: Engine, job: dict[str, Any], lost: Event) -> dict[str, Any]:
    evaluation_id = UUID(str(job["evaluation_id"]))
    with engine.connect() as conn:
        snapshot: dict[str, Any] = conn.execute(
            text("SELECT snapshot FROM evaluations WHERE id=:id"), {"id": evaluation_id}
        ).scalar_one()
    config = snapshot["ai"]
    if config["prompt_version"] != PROMPT_VERSION or (
        config["provider"] == "openai" and config["model"] != get_settings().llm_model
    ):
        raise ModelError("PINNED_MODEL_OR_PROMPT_MISMATCH")
    units = source_units(engine, evaluation_id)
    payload = {
        "source_units": [{"source_id": u["source_id"], "text": u["text"]} for u in units],
        "supported_keys": list(FIELDS),
        "policy": snapshot["policy"],
    }
    fixture = expected_extraction(units)
    selection = {"claim_ids": CLAIM_IDS, "section_order": SECTIONS}
    if lost.is_set():
        raise ModelError("WORKER_LEASE_LOST")
    if config["workflow"] == "generalist":
        output = call_model(
            engine,
            evaluation_id,
            config["provider"],
            "generalist",
            GENERALIST,
            payload,
            extraction_schema(GeneralistProposal, units),
            {"extraction": fixture, "draft": selection},
            4096,
        )
        combined = GeneralistProposal.model_validate(output)
        proposal, selected = combined.extraction, combined.draft
        validate_selection(selected)
    else:
        output = call_model(
            engine,
            evaluation_id,
            config["provider"],
            "extractor",
            EXTRACT,
            payload,
            extraction_schema(ExtractionProposal, units),
            fixture,
        )
        proposal = ExtractionProposal.model_validate(output)
    validate_extraction(proposal, units)
    if lost.is_set():
        raise ModelError("WORKER_LEASE_LOST")
    # Commit deterministic tools before drafting; recovery reuses this sealed result.
    with engine.begin() as conn:
        locked_job(conn, job)
        exists = conn.execute(
            text("SELECT 1 FROM policy_checks WHERE evaluation_id=:id"), {"id": evaluation_id}
        ).first()
        if not exists:
            evaluate_policy(conn, evaluation_id)
    cards = claim_cards(engine, evaluation_id)
    if config["workflow"] == "multi_agent":
        if lost.is_set():
            raise ModelError("WORKER_LEASE_LOST")
        selected = DraftSelection.model_validate(
            call_model(
                engine,
                evaluation_id,
                config["provider"],
                "draft",
                DRAFT,
                {"claim_cards": [c.model_dump(mode="json") for c in cards]},
                DraftSelection.model_json_schema(),
                selection,
            )
        )
        validate_selection(selected)
    by_id = {c.id: c for c in cards}
    draft = AIDraft(
        status="DRAFT_ONLY",
        simulation=True,
        requires_human_review=True,
        marker_en="SIMULATION",
        marker_es="SIMULACIÓN",
        provider=config["provider"],
        model=config["model"],
        workflow=config["workflow"],
        section_order=selected.section_order,
        claims=[by_id[cid] for cid in selected.claim_ids],
        tool_trace=[
            "source_observations_verified",
            "deterministic_extraction",
            "calculate_dscr",
            "pinned_policy_check",
            "grounded_claim_renderer",
        ],
        limitations_en=[
            "Constrained synthetic CSV/text PDF format; no OCR or narrative extraction.",
            "The model selects and orders verified claims; material wording is rendered by code.",
        ],
        limitations_es=[
            "Formato sintético restringido CSV/PDF de texto; sin OCR ni extracción narrativa.",
            "El modelo selecciona y ordena afirmaciones verificadas; "
            "el código genera el texto material.",
        ],
    )
    return draft.model_dump(mode="json")


def finish_ai(engine: Engine, job: dict[str, Any]) -> bool:
    from credit_support.worker import heartbeat

    stop, lost = Event(), Event()
    lease = get_settings().worker_lease_seconds

    def keep_alive() -> None:
        while not stop.wait(max(1, lease / 3)):
            try:
                if not heartbeat(engine, job, lease):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    if not heartbeat(engine, job, lease):
        return False
    thread = Thread(target=keep_alive, daemon=True)
    thread.start()
    try:
        result: dict[str, Any]
        try:
            draft = run_ai(engine, job, lost)
            status, result = "SUCCEEDED", {"simulation": True, "draft_available": True}
        except (ModelError, ValidationError, IngestionError, PolicyError) as exc:
            status = "FAILED_TERMINAL"
            result = {"error": str(exc) if isinstance(exc, ModelError) else "AI_VALIDATION_FAILED"}
            draft = None
        with engine.begin() as conn:
            try:
                case_id = locked_job(conn, job)
            except ModelError:
                return False
            if lost.is_set():
                return False
            if draft is not None:
                body = canonical(draft)
                conn.execute(
                    text("""
                  INSERT INTO ai_drafts(evaluation_id,draft,sha256)
                  VALUES(:id,CAST(:draft AS jsonb),:hash)
                """),
                    {
                        "id": job["evaluation_id"],
                        "draft": body,
                        "hash": hashlib.sha256(body.encode()).hexdigest(),
                    },
                )
            conn.execute(
                text("UPDATE evaluations SET processing_state=:state WHERE id=:id"),
                {
                    "id": job["evaluation_id"],
                    "state": "DRAFT_READY" if draft else "FAILED_TERMINAL",
                },
            )
            active: bool = conn.execute(
                text("SELECT lease_until>clock_timestamp() FROM jobs WHERE id=:id"),
                {"id": job["id"]},
            ).scalar_one()
            if not active:
                conn.rollback()
                return False
            conn.execute(
                text("""
              UPDATE jobs SET status=:status,result=CAST(:result AS jsonb),
              lease_until=NULL,lease_token=NULL WHERE id=:id
            """),
                {"id": job["id"], "status": status, "result": canonical(result)},
            )
            append_event(
                conn,
                case_id,
                "worker",
                "JOB_" + status,
                {"job_id": str(job["id"]), "step": "ai_workflow"},
            )
        return True
    finally:
        stop.set()
        thread.join(timeout=5)
