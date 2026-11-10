import json
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from conftest import auth
from generate_synthetic_cases import VARIANTS, build_case, encode_csv
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_ingestion import read_extraction, upload
from test_policy_engine import catalog as policy_catalog_fixture
from test_policy_engine import extract_case

from credit_support import ai_workflow, llm
from credit_support.ai_models import DraftSelection, ExtractionProposal
from credit_support.ai_workflow import CLAIM_IDS, SECTIONS, validate_extraction, validate_selection
from credit_support.db import get_engine
from credit_support.llm import ModelError, budget, call_model
from credit_support.settings import get_settings
from credit_support.worker import claim, finish

catalog = policy_catalog_fixture


def start(api, token, case_id, source, workflow="multi_agent", provider="mock", key="ai"):
    return api.post(
        f"/v1/cases/{case_id}/ai-evaluate",
        headers={**auth(token), "Idempotency-Key": key},
        json={
            "source_evaluation_id": source["evaluation_id"],
            "provider": provider,
            "workflow": workflow,
        },
    )


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("workflow", ["multi_agent", "generalist"])
def test_grounded_workflow_matches_tools_and_has_complete_citations(
    client, catalog, variant, workflow
):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"], variant=variant)
    response = start(api, tokens["analyst"], case_id, source, workflow)
    assert response.status_code == 202, response.text
    assert start(api, tokens["analyst"], case_id, source, workflow).json() == response.json()
    job = claim(get_engine(), "ai", 30)
    assert finish(get_engine(), job)
    result = read_extraction(api, tokens["analyst"], case_id, response.json())
    assert result["job_status"] == "SUCCEEDED", result
    assert result["processing_state"] == "DRAFT_READY"
    draft = result["ai_draft"]
    assert draft["requires_human_review"] and draft["simulation"]
    assert {c["id"] for c in draft["claims"]} == set(CLAIM_IDS)
    facts = {f["id"]: f for f in result["facts"]}
    evidence = {e["id"] for e in result["evidence"]}
    for card in draft["claims"]:
        assert set(card["fact_ids"]) <= facts.keys()
        assert set(card["evidence_ids"]) <= evidence
    assert len(result["model_calls"]) == (2 if workflow == "multi_agent" else 1)
    assert all(Decimal(c["charged_usd"]) == 0 for c in result["model_calls"])
    assert read_extraction(api, tokens["analyst"], case_id, source)["current"] is False
    with pytest.raises(DBAPIError), get_engine().begin() as conn:
        conn.execute(text("UPDATE ai_drafts SET sha256=repeat('a',64)"))


@pytest.mark.parametrize(
    "bad", ["invented_source", "changed_value", "omitted_conflict", "missing_key"]
)
def test_extraction_guard_rejects_invented_or_incomplete_observations(bad):
    units = [
        {"key": "debt_service", "source_id": "a", "raw_value": "10"},
        {"key": "debt_service", "source_id": "b", "raw_value": "20"},
    ]
    data = ai_workflow.expected_extraction(units)
    if bad == "invented_source":
        data["observations"][0]["source_id"] = "invented"
    elif bad == "changed_value":
        data["observations"][0]["raw_value"] = "999"
    elif bad == "omitted_conflict":
        data["observations"].pop()
    else:
        data["missing_keys"].pop()
    with pytest.raises(ModelError):
        validate_extraction(ExtractionProposal.model_validate(data), units)


@pytest.mark.parametrize(
    "ids", [CLAIM_IDS[:-1], CLAIM_IDS + ["approve"], CLAIM_IDS + [CLAIM_IDS[0]]]
)
def test_draft_guard_rejects_unsupported_missing_or_duplicate_findings(ids):
    with pytest.raises(ModelError):
        validate_selection(DraftSelection(claim_ids=ids, section_order=SECTIONS))


def test_invalid_model_response_is_terminal_without_draft(client, catalog, monkeypatch):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    response = start(api, tokens["analyst"], case_id, source)

    def invalid(*args, **kwargs):
        return {"observations": [], "missing_keys": []}

    monkeypatch.setattr(ai_workflow, "call_model", invalid)
    assert finish(get_engine(), claim(get_engine(), "ai", 30))
    result = read_extraction(api, tokens["analyst"], case_id, response.json())
    assert result["job_status"] == "FAILED_TERMINAL"
    assert result["ai_draft"] is None and result["facts"] == []


def test_access_live_opt_in_and_stale_inputs(client, catalog):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    assert start(api, tokens["other"], case_id, source).status_code == 404
    assert start(api, tokens["analyst"], case_id, source, provider="openai").status_code == 409


@pytest.fixture
def gateway(client, catalog, monkeypatch):
    api, tokens = client
    _, source = extract_case(api, tokens["analyst"])
    monkeypatch.setenv("CDS_LLM_LIVE_ENABLED", "true")
    monkeypatch.setenv("CDS_OPENAI_API_KEY", "test-key-not-a-real-credential")
    get_settings.cache_clear()
    original = httpx.Client
    calls = []

    def install(handler):
        def wrapped(request):
            calls.append(request)
            return handler(request)

        monkeypatch.setattr(
            llm.httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(wrapped))
        )

    yield UUID(source["evaluation_id"]), install, calls
    get_settings.cache_clear()


def response(output=None, **overrides):
    return httpx.Response(
        200,
        json={
            "id": "response-fixture",
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": json.dumps(output or {"ok": True})}
                    ],
                }
            ],
            **overrides,
        },
    )


def invoke(eid, stage="test"):
    return call_model(
        get_engine(),
        eid,
        "openai",
        stage,
        "Test",
        {},
        {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        {"ok": True},
    )


def test_gateway_uses_responses_and_replays_without_second_charge(gateway):
    eid, install, calls = gateway
    install(lambda _: response())
    assert invoke(eid) == {"ok": True}
    assert invoke(eid) == {"ok": True}
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert str(calls[0].url) == "https://api.openai.com/v1/responses"
    assert body["store"] is False and body["text"]["format"]["strict"] is True
    assert Decimal(budget(get_engine())["committed_or_reserved_usd"]) == Decimal(".0008")


@pytest.mark.parametrize("failure", ["timeout", "refusal", "incomplete", "usage", "http"])
def test_gateway_failures_preserve_cost_and_never_retry(gateway, failure):
    eid, install, calls = gateway

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive provider details", request=request)
        if failure == "http":
            return httpx.Response(429, json={"error": "do not log this"})
        if failure == "refusal":
            return response(output=[{"content": [{"type": "refusal", "refusal": "no"}]}])
        if failure == "incomplete":
            return response(status="incomplete")
        return response(usage={})

    install(handler)
    with pytest.raises(ModelError):
        invoke(eid)
    with pytest.raises(ModelError, match="ALREADY_RESERVED_OR_FAILED"):
        invoke(eid)
    assert len(calls) == 1
    assert Decimal(budget(get_engine())["committed_or_reserved_usd"]) > 0


def test_concurrent_reservations_respect_global_budget(gateway, database):
    eid, install, calls = gateway
    install(lambda _: response())
    with database.begin() as conn:
        conn.execute(text("UPDATE llm_budgets SET limit_usd=.04"))
    try:

        def run(stage):
            try:
                invoke(eid, stage)
                return True
            except ModelError:
                return False

        # Unknown usage retains the reservation, even when HTTP failed.
        install(lambda _: httpx.Response(503))
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(run, [str(uuid4()) for _ in range(4)]))
        assert len(calls) == 1
        assert Decimal(budget(get_engine())["committed_or_reserved_usd"]) <= Decimal(".04")
    finally:
        with database.begin() as conn:
            conn.execute(text("UPDATE llm_budgets SET limit_usd=2"))


def test_stale_lease_cannot_call_provider_or_commit_draft(client, catalog, monkeypatch):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    receipt = start(api, tokens["analyst"], case_id, source).json()
    job = claim(get_engine(), "expired", 30)
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": job["id"]},
        )
    assert finish(get_engine(), job) is False
    result = read_extraction(api, tokens["analyst"], case_id, receipt)
    assert result["model_calls"] == [] and result["ai_draft"] is None


def test_upload_during_drafting_keeps_historical_result_out_of_current_pointer(
    client, catalog, monkeypatch
):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    receipt = start(api, tokens["analyst"], case_id, source).json()
    original = ai_workflow.call_model

    def changed(*args, **kwargs):
        if args[3] == "draft":
            rows, _ = build_case(99)
            assert (
                upload(api, tokens["analyst"], case_id, encode_csv(rows), key="new").status_code
                == 202
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(ai_workflow, "call_model", changed)
    assert finish(get_engine(), claim(get_engine(), "ai", 30))
    result = read_extraction(api, tokens["analyst"], case_id, receipt)
    assert result["processing_state"] == "DRAFT_READY" and not result["current"]
    assert start(api, tokens["analyst"], case_id, source, key="stale").status_code == 409


def test_draft_failure_preserves_tool_trace_but_never_publishes_draft(client, catalog, monkeypatch):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    receipt = start(api, tokens["analyst"], case_id, source).json()
    original = ai_workflow.call_model

    def invalid(*args, **kwargs):
        if args[3] == "draft":
            return {"claim_ids": ["approve"], "section_order": SECTIONS}
        return original(*args, **kwargs)

    monkeypatch.setattr(ai_workflow, "call_model", invalid)
    assert finish(get_engine(), claim(get_engine(), "ai", 30))
    result = read_extraction(api, tokens["analyst"], case_id, receipt)
    assert result["job_status"] == "FAILED_TERMINAL" and result["ai_draft"] is None
    assert len(result["facts"]) == 6 and result["policy_check"]


def test_heartbeat_maintains_lease_during_slow_model_call(client, catalog, monkeypatch):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    receipt = start(api, tokens["analyst"], case_id, source).json()
    monkeypatch.setenv("CDS_WORKER_LEASE_SECONDS", "5")
    get_settings.cache_clear()
    original = ai_workflow.call_model

    def slow(*args, **kwargs):
        if args[3] == "extractor":
            time.sleep(6)
            assert claim(get_engine(), "competitor", 5) is None
        return original(*args, **kwargs)

    monkeypatch.setattr(ai_workflow, "call_model", slow)
    try:
        assert finish(get_engine(), claim(get_engine(), "ai", 5))
        assert (
            read_extraction(api, tokens["analyst"], case_id, receipt)["job_status"] == "SUCCEEDED"
        )
    finally:
        get_settings.cache_clear()


def test_completed_call_records_cannot_be_rewritten_or_deleted(gateway, database):
    eid, install, _ = gateway
    install(lambda _: response())
    invoke(eid)
    for statement in ("UPDATE model_calls SET charged_usd=0", "DELETE FROM model_calls"):
        with pytest.raises(DBAPIError), database.begin() as conn:
            conn.execute(text(statement))


def test_http_diagnostic_does_not_store_raw_provider_error(gateway):
    eid, install, _ = gateway
    install(
        lambda _: httpx.Response(
            429,
            json={"error": {"code": "insufficient_quota", "message": "private provider details"}},
        )
    )
    with pytest.raises(ModelError, match="OPENAI_HTTP_429_INSUFFICIENT_QUOTA"):
        invoke(eid)


def test_request_limit_prevents_network_and_reservation(gateway):
    eid, install, calls = gateway
    install(lambda _: response())
    with pytest.raises(ModelError, match="MODEL_INPUT_LIMIT"):
        call_model(get_engine(), eid, "openai", "large", "test", {"large": "x" * 60000}, {}, {})
    assert calls == [] and budget(get_engine())["openai_calls"] == 0
