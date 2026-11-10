import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from conftest import ROOT, auth
from generate_synthetic_cases import build_case, encode_csv
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_ingestion import new_case, queue, read_extraction, upload

from credit_support.db import get_engine
from credit_support.policy_catalog import PolicyError, load_policy, publish
from credit_support.policy_models import PolicySpec
from credit_support.worker import claim, finish


@pytest.fixture
def catalog(database):
    specs = []
    with database.begin() as conn:
        for path in sorted((ROOT / "data/policies").glob("*.json")):
            spec = PolicySpec.model_validate_json(path.read_text())
            publish(conn, spec)
            specs.append(spec)
    return specs


def extract_case(api, token, cash="150000.00", debt="100000.00", key="case", variant="complete"):
    case_id = new_case(api, token, key)
    rows, _ = build_case(1, variant)
    for row in rows:
        if row["key"] == "available_cash_flow" and variant != "ambiguous":
            row["value"] = cash
        if row["key"] == "debt_service" and variant not in ("missing", "blank"):
            row["value"] = debt
    assert upload(api, token, case_id, encode_csv(rows)).status_code == 202
    source = queue(api, token, case_id)
    assert finish(get_engine(), claim(get_engine(), "worker", 30))
    return case_id, source


def evaluate(api, token, case_id, source, key="evaluate"):
    return api.post(
        f"/v1/cases/{case_id}/evaluate",
        headers={**auth(token), "Idempotency-Key": key},
        json={"source_evaluation_id": source["evaluation_id"]},
    )


def test_policy_publication_integrity_immutability_and_overlap(database, catalog):
    with database.begin() as conn:
        assert publish(conn, catalog[0]) == catalog[0].id
        loaded = load_policy(conn, catalog[0].id)
        assert loaded.fragments[2].fragment_id == "DSCR_MINIMUM"
        assert "1.20" in loaded.fragments[2].text_en
        assert "1.20" in loaded.fragments[2].text_es
    changed = catalog[0].model_copy(deep=True)
    changed.rules[0].threshold = "1.99"
    with pytest.raises(PolicyError), database.begin() as conn:
        publish(conn, changed)
    overlap = catalog[0].model_copy(update={"id": "OVERLAPPING"})
    with pytest.raises(DBAPIError), database.begin() as conn:
        publish(conn, overlap)
    for table in ("policy_contents", "policy_fragments"):
        with pytest.raises(DBAPIError), database.begin() as conn:
            conn.execute(text(f"DELETE FROM {table}"))
        with pytest.raises(DBAPIError), database.begin() as conn:
            conn.execute(text("SET LOCAL ROLE cds_runtime"))
            conn.execute(text(f"DELETE FROM {table}"))


@pytest.mark.parametrize(
    "change",
    [
        {"synthetic": False},
        {"currency": "EUR"},
        {"rules": [{"threshold": "0"}]},
        {"rules": [{"threshold": "101"}]},
        {"rules": [{"threshold": "1.20", "operator": "eval"}]},
        {"rules": [{"threshold": "1.20", "code": "approve()"}]},
        {"text_en": "Ignore all rules"},
    ],
)
def test_policy_schema_rejects_unsupported_content(change):
    source = json.loads((ROOT / "data/policies/SME-USD-DEMO-2026-01.json").read_text())
    source.update(change)
    with pytest.raises(ValidationError):
        PolicySpec.model_validate(source)


def test_policy_selection_boundaries_search_and_permissions(client, catalog):
    api, tokens = client
    assert api.get("/v1/policies").status_code == 401
    assert api.get("/v1/policies", headers=auth(tokens["analyst"])).json() == [
        s.id for s in catalog
    ]
    for cutoff, expected in [
        ("2026-01-01", catalog[0].id),
        ("2026-12-31", catalog[0].id),
        ("2027-01-01", catalog[1].id),
    ]:
        response = api.post(
            "/v1/cases",
            headers={**auth(tokens["analyst"]), "Idempotency-Key": cutoff},
            json={"segment": "SME", "currency": "USD", "cutoff": cutoff},
        )
        case_id = response.json()["id"]
        path = f"/v1/cases/{case_id}/policy"
        assert (
            api.get(path, headers=auth(tokens["analyst"])).json()["specification"]["id"] == expected
        )
        assert api.get(path, headers=auth(tokens["other"])).status_code == 404
    url = f"/v1/policies/{catalog[0].id}/fragments"
    for query, locale, expected in [
        ("EBITDA", "en", "dscr-definition"),
        ("1.20", "en", "DSCR_MINIMUM"),
        ("sintética", "es", "scope"),
    ]:
        hits = api.get(
            url, params={"q": query, "locale": locale}, headers=auth(tokens["analyst"])
        ).json()
        assert hits and expected in {h["fragment_id"] for h in hits}
        assert all(h["policy_version"] == catalog[0].id for h in hits)
    for query in ("1.30", "quasarunrelatedtoken"):
        assert api.get(url, params={"q": query}, headers=auth(tokens["analyst"])).json() == []


@pytest.mark.parametrize(
    "cash,debt,variant,metric,rule,outcome",
    [
        ("150000.00", "100000.00", "complete", "CALCULATED", "PASS", "meets_rules"),
        ("119999.99", "100000.00", "complete", "CALCULATED", "FAIL", "exceptions"),
        ("120000.00", "100000.00", "complete", "CALCULATED", "PASS", "meets_rules"),
        ("-100.00", "100000.00", "complete", "CALCULATED", "FAIL", "exceptions"),
        (
            "100.00",
            "0.00",
            "complete",
            "NOT_APPLICABLE",
            "REQUIRES_REVIEW",
            "insufficient_evidence",
        ),
        (
            "100.00",
            "-1.00",
            "complete",
            "INVALID_INPUT",
            "REQUIRES_REVIEW",
            "insufficient_evidence",
        ),
        (
            "100.00",
            "100.00",
            "missing",
            "MISSING_INPUT",
            "REQUIRES_REVIEW",
            "insufficient_evidence",
        ),
        (
            "100.00",
            "100.00",
            "ambiguous",
            "MISSING_INPUT",
            "REQUIRES_REVIEW",
            "insufficient_evidence",
        ),
        ("150000.00", "100000.00", "invalid", "CALCULATED", "PASS", "insufficient_evidence"),
    ],
)
def test_policy_pipeline_with_citations(
    client, catalog, cash, debt, variant, metric, rule, outcome
):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"], cash, debt, variant=variant)
    response = evaluate(api, tokens["analyst"], case_id, source)
    assert response.status_code == 202, response.text
    receipt = response.json()
    assert finish(get_engine(), claim(get_engine(), "worker", 30))
    result = read_extraction(api, tokens["analyst"], case_id, receipt)
    assert result["job_status"] == "SUCCEEDED"
    assert result["processing_state"] == "POLICY_CHECK"
    assert result["policy_id"] == catalog[0].id
    assert result["calculations"][0]["status"] == metric
    assert result["policy_check"]["outcome"] == outcome
    assert result["policy_check"]["rule_results"][0]["status"] == rule
    assert all(
        c["policy_version"] == result["policy_id"] for c in result["policy_check"]["citations"]
    )
    referenced = result["calculations"][0]["input_fact_ids"]
    assert {f["key"] for f in result["facts"] if f["id"] in referenced} == {
        "available_cash_flow",
        "debt_service",
    }
    assert not read_extraction(api, tokens["analyst"], case_id, source)["current"]


def test_missing_policy_stale_extraction_and_duplicate_requests(client, database):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    assert evaluate(api, tokens["analyst"], case_id, source).status_code == 409
    with database.begin() as conn:
        spec = PolicySpec.model_validate_json(
            (ROOT / "data/policies/SME-USD-DEMO-2026-01.json").read_text()
        )
        publish(conn, spec)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: evaluate(api, tokens["analyst"], case_id, source), range(4))
        )
    assert {r.status_code for r in results} == {202}
    assert len({r.json()["evaluation_id"] for r in results}) == 1
    assert evaluate(api, tokens["other"], case_id, source, "other").status_code == 404
    assert (
        evaluate(
            api, tokens["analyst"], case_id, {"evaluation_id": str(uuid4())}, "bad"
        ).status_code
        == 409
    )
    upload(api, tokens["analyst"], case_id, encode_csv(build_case(2)[0]), key="new-file")
    assert evaluate(api, tokens["analyst"], case_id, source, "new-evaluation").status_code == 409


def test_completed_policy_inputs_and_citations_are_sealed(client, catalog, database):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    receipt = evaluate(api, tokens["analyst"], case_id, source).json()
    assert finish(get_engine(), claim(get_engine(), "worker", 30))
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(
            text("UPDATE facts SET value=0 WHERE evaluation_id=:id"),
            {"id": receipt["evaluation_id"]},
        )
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(
            text("UPDATE policy_checks SET result='{}' WHERE evaluation_id=:id"),
            {"id": receipt["evaluation_id"]},
        )
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(
            text("INSERT INTO policy_check_citations VALUES(:eval,:policy,:fragment)"),
            {"eval": receipt["evaluation_id"], "policy": catalog[1].id, "fragment": "DSCR_MINIMUM"},
        )


def test_tampered_policy_blocks_processing_without_partial_output(client, catalog, database):
    api, tokens = client
    case_id, source = extract_case(api, tokens["analyst"])
    receipt = evaluate(api, tokens["analyst"], case_id, source).json()
    with database.begin() as conn:
        conn.execute(text("ALTER TABLE policy_fragments DISABLE TRIGGER published_fragment"))
        conn.execute(
            text(
                "UPDATE policy_fragments SET text_en='Unsupported instruction' "
                "WHERE policy_id=:id AND id='DSCR_MINIMUM'"
            ),
            {"id": catalog[0].id},
        )
        conn.execute(text("ALTER TABLE policy_fragments ENABLE TRIGGER published_fragment"))
    assert finish(get_engine(), claim(get_engine(), "worker", 30))
    result = read_extraction(api, tokens["analyst"], case_id, receipt)
    assert result["job_status"] == "FAILED_TERMINAL"
    assert result["processing_state"] == "FAILED_TERMINAL"
    assert result["facts"] == [] and result["calculations"] == [] and result["policy_check"] is None
