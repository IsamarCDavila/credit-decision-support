import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from conftest import auth
from generate_synthetic_cases import build_case, encode_csv
from pypdf import PdfReader
from sqlalchemy import text
from test_ai_workflow import start
from test_ingestion import read_extraction, upload
from test_policy_engine import catalog as catalog_fixture
from test_policy_engine import extract_case

from credit_support.audit import canonical
from credit_support.db import get_engine
from credit_support.worker import claim, finish

catalog = catalog_fixture


def ready_case(api, token, variant="complete"):
    case_id, source = extract_case(api, token, key=str(uuid4()), variant=variant)
    receipt = start(api, token, case_id, source).json()
    assert finish(get_engine(), claim(get_engine(), "review-test", 30))
    assert read_extraction(api, token, case_id, receipt)["processing_state"] == "DRAFT_READY"
    return case_id, receipt["evaluation_id"]


def assign(api, token, cid, role="reviewer", actor=None, key=None):
    return api.post(
        f"/v1/cases/{cid}/members",
        headers={**auth(token), "Idempotency-Key": key or str(uuid4())},
        json={"actor_id": actor or role, "role": role},
    )


def decide(
    api, token, cid, eid, decision="APPROVED", reason="Sources and policy checked.", key=None
):
    return api.post(
        f"/v1/cases/{cid}/evaluations/{eid}/review",
        headers={**auth(token), "Idempotency-Key": key or str(uuid4())},
        json={"expected_review_state": "PENDING", "decision": decision, "reason": reason},
    )


def test_workspace_auth_case_visibility_and_assignment(client, catalog):
    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"])
    assert api.get("/v1/cases").status_code == 401
    assert api.get("/v1/cases", headers=auth(tokens["other"])).json()["cases"] == []
    assert api.get(f"/v1/cases/{cid}/workspace", headers=auth(tokens["admin"])).status_code == 404
    assert assign(api, tokens["other"], cid).status_code == 404
    assert assign(api, tokens["reviewer"], cid).status_code == 403
    assert assign(api, tokens["analyst"], cid, actor="unknown").status_code == 422
    assert assign(api, tokens["analyst"], cid, key="assign").status_code == 201
    assert assign(api, tokens["analyst"], cid, key="assign").status_code == 201
    assert len(api.get("/v1/cases", headers=auth(tokens["reviewer"])).json()["cases"]) == 1
    assert (
        len(
            api.get(f"/v1/cases/{cid}/workspace", headers=auth(tokens["reviewer"])).json()[
                "members"
            ]
        )
        == 2
    )
    assert api.get("/v1/assignment-directory", headers=auth(tokens["reviewer"])).status_code == 403
    assert "token" not in api.get("/v1/me", headers=auth(tokens["reviewer"])).json()
    with get_engine().connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE case_id=:id "
                    "AND kind='CASE_MEMBER_ASSIGNED'"
                ),
                {"id": cid},
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("decision", ["APPROVED", "REJECTED", "NEEDS_MORE_INFO"])
def test_review_terminal_decision_and_idempotency(client, catalog, decision):
    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"])
    assert assign(api, tokens["analyst"], cid).status_code == 201
    assert decide(api, tokens["analyst"], cid, eid).status_code == 403
    result = decide(
        api, tokens["reviewer"], cid, eid, decision, reason="  Valid assessment.  ", key="review"
    )
    assert result.status_code == 201, result.text
    assert result.json()["reason"] == "Valid assessment."
    assert (
        decide(
            api,
            tokens["reviewer"],
            cid,
            eid,
            decision,
            reason="  Valid assessment.  ",
            key="review",
        ).json()
        == result.json()
    )
    assert (
        decide(
            api, tokens["reviewer"], cid, eid, decision, reason="changed", key="review"
        ).status_code
        == 409
    )
    assert decide(api, tokens["reviewer"], cid, eid).status_code == 409
    read = api.get(
        f"/v1/cases/{cid}/evaluations/{eid}/review", headers=auth(tokens["reviewer"])
    ).json()
    assert read["state"] == decision and not read["can_review"]
    assert (
        read_extraction(api, tokens["analyst"], cid, {"evaluation_id": eid})["processing_state"]
        == "DRAFT_READY"
    )
    with get_engine().connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE case_id=:id "
                    "AND kind='HUMAN_REVIEW_RECORDED'"
                ),
                {"id": cid},
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("reason", ["", " \n\t ", "x" * 4001])
def test_mandatory_reason(client, catalog, reason):
    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"])
    assign(api, tokens["analyst"], cid)
    assert decide(api, tokens["reviewer"], cid, eid, reason=reason).status_code == 422


def test_stale_and_cross_case_reviews(client, catalog):
    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"])
    assign(api, tokens["analyst"], cid)
    other, _ = ready_case(api, tokens["analyst"])
    assign(api, tokens["analyst"], other)
    assert decide(api, tokens["reviewer"], other, eid).status_code == 404
    rows, _ = build_case(2)
    assert upload(api, tokens["analyst"], cid, encode_csv(rows), key="new-doc").status_code == 202
    assert decide(api, tokens["reviewer"], cid, eid).status_code == 409
    old = api.get(
        f"/v1/cases/{cid}/evaluations/{eid}/review", headers=auth(tokens["reviewer"])
    ).json()
    assert not old["current"] and not old["can_review"]


def test_concurrent_review_submissions_have_one_winner(client, catalog, database):
    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"])
    assign(api, tokens["analyst"], cid)

    def submit(i):
        return decide(
            api, tokens["reviewer"], cid, eid, decision="APPROVED" if i == 0 else "REJECTED"
        ).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(submit, range(2))) == [201, 409]
    with database.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM reviews WHERE evaluation_id=:id"), {"id": eid}
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("locale", ["en", "es"])
@pytest.mark.parametrize("variant", ["complete", "missing", "ambiguous", "zero_debt"])
def test_reports_reconstruct_sources_review_and_chain(client, catalog, locale, variant):
    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"], variant)
    assign(api, tokens["analyst"], cid)
    route = f"/v1/cases/{cid}/evaluations/{eid}/report"
    before = api.get(route + ".json", headers=auth(tokens["reviewer"]), params={"locale": locale})
    assert before.status_code == 200, before.text
    assert before.json()["review"]["state"] == "PENDING"
    reason = "Análisis revisado <b>sin ejecutar marcado</b> & evidencia validada."
    assert decide(api, tokens["reviewer"], cid, eid, reason=reason).status_code == 201
    response = api.get(route + ".json", headers=auth(tokens["reviewer"]), params={"locale": locale})
    assert response.status_code == 200, response.text
    value = response.json()
    integrity = value.pop("integrity")
    assert hashlib.sha256(canonical(value).encode()).hexdigest() == integrity["payload_sha256"]
    assert integrity["audit_chain_verified"] and value["review"]["state"] == "APPROVED"
    assert all(e["created_at"].endswith("+00:00") for e in value["audit_events"])
    assert value["review"]["record"]["reason"] == reason
    assert api.get(route + ".pdf", headers=auth(tokens["other"])).status_code == 404
    pdf = api.get(route + ".pdf", headers=auth(tokens["reviewer"]), params={"locale": locale})
    assert pdf.status_code == 200, pdf.text[:100] if pdf.status_code != 200 else ""
    reader = PdfReader(io.BytesIO(pdf.content))
    attached = json.loads(reader.attachments["report.json"][0])
    proof = attached.pop("integrity")
    assert hashlib.sha256(canonical(attached).encode()).hexdigest() == proof["payload_sha256"]
    assert attached["evaluation"]["evaluation_id"] == eid
    assert attached["evaluation"]["ai_draft"] == value["evaluation"]["ai_draft"]
    extracted = "\n".join(page.extract_text() for page in reader.pages)
    assert ("SIMULACIÓN" if locale == "es" else "SIMULATION") in extracted
    assert "APPROVED" in extracted and eid in extracted and reason in extracted
    assert "payload_sha256" not in extracted
    presentation = extracted.split("Códigos técnicos" if locale == "es" else "Technical codes")[0]
    assert ("Simulación aprobada" if locale == "es" else "Simulation approved") in presentation
    assert ("Evaluación actual\nSí" if locale == "es" else "Current snapshot\nYes") in presentation
    assert "True" not in presentation
    assert "estado de evidencia: extracted" not in presentation
    assert "evidence status: extracted" not in presentation


def test_not_ready_report_and_static_security_headers(client, catalog):
    api, tokens = client
    cid, source = extract_case(api, tokens["analyst"])
    assert (
        api.get(
            f"/v1/cases/{cid}/evaluations/{source['evaluation_id']}/report.json",
            headers=auth(tokens["analyst"]),
        ).status_code
        == 409
    )
    page = api.get("/")
    assert (
        page.status_code == 200 and "script-src 'self'" in page.headers["content-security-policy"]
    )
    assert page.headers["cache-control"] == "no-store"
    assert api.get("/assets/workspace.js").headers["content-type"].startswith("text/javascript")
    assert 'localStorage.setItem("cds-language"' in api.get("/assets/workspace.js").text
    assert 'localStorage.setItem("token"' not in api.get("/assets/workspace.js").text


def test_tampered_source_blocks_report(client, catalog, database):
    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"])
    with database.begin() as conn:
        # Simulate owner-level corruption outside the runtime role's immutable-table permissions.
        conn.exec_driver_sql("ALTER TABLE document_contents DISABLE TRIGGER USER")
        conn.execute(text("UPDATE document_contents SET data='tampered'::bytea"))
        conn.exec_driver_sql("ALTER TABLE document_contents ENABLE TRIGGER USER")
    response = api.get(
        f"/v1/cases/{cid}/evaluations/{eid}/report.json", headers=auth(tokens["analyst"])
    )
    assert response.status_code == 409 and "checksum" in response.text


def test_self_review_is_blocked_even_with_another_role_token(
    client, catalog, database, monkeypatch
):
    import os

    from credit_support.settings import get_settings

    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"])
    identities = json.loads(os.environ["CDS_DEMO_IDENTITIES"])
    identities[tokens["reviewer"]]["actor_id"] = "analyst"
    monkeypatch.setenv("CDS_DEMO_IDENTITIES", json.dumps(identities))
    get_settings.cache_clear()
    with database.begin() as conn:
        conn.execute(text("INSERT INTO case_members VALUES(:id,'analyst','reviewer')"), {"id": cid})
    try:
        assert decide(api, tokens["reviewer"], cid, eid).status_code == 403
    finally:
        get_settings.cache_clear()


def test_corrupt_audit_chain_blocks_export(client, catalog, database):
    api, tokens = client
    cid, eid = ready_case(api, tokens["analyst"])
    with database.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE audit_events DISABLE TRIGGER USER")
        conn.execute(
            text("UPDATE audit_events SET payload='{}' WHERE case_id=:id AND sequence=1"),
            {"id": cid},
        )
        conn.exec_driver_sql("ALTER TABLE audit_events ENABLE TRIGGER USER")
    response = api.get(
        f"/v1/cases/{cid}/evaluations/{eid}/report.json", headers=auth(tokens["analyst"])
    )
    assert response.status_code == 409 and "Audit chain" in response.text
