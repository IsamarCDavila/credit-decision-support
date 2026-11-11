import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import auth
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_policy_engine import catalog as catalog_fixture

from credit_support.db import get_engine
from credit_support.settings import get_settings
from credit_support.worker import claim, finish

catalog = catalog_fixture
MARKER = {"X-Demo-Request": "1"}


@pytest.fixture
def guided(client, catalog, monkeypatch):
    monkeypatch.setenv("CDS_GUIDED_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    yield client
    get_settings.cache_clear()


def create(api, role="analyst"):
    response = api.post("/v1/demo/sessions", headers=MARKER, json={"role": role})
    assert response.status_code == 201, response.status_code
    return response.json()


def finish_jobs():
    while job := claim(get_engine(), "guided-test", 30):
        assert finish(get_engine(), job)


@pytest.mark.parametrize("initial_role", ["analyst", "reviewer", "auditor"])
def test_prepared_case_and_three_scoped_roles(guided, initial_role):
    api, _ = guided
    session = create(api, initial_role)
    finish_jobs()
    assert session["role"] == initial_role and session["provider"] == "mock"
    assert set(session["role_tokens"]) == {"analyst", "reviewer", "auditor"}
    actors = []
    for role, token in session["role_tokens"].items():
        profile = api.get("/v1/me", headers=auth(token)).json()
        assert (
            profile["role"] == role and profile["guided_demo"] and not profile["live_model_enabled"]
        )
        actors.append(profile["actor_id"])
        cases = api.get("/v1/cases", headers=auth(token)).json()["cases"]
        assert [case["id"] for case in cases] == [session["case_id"]]
        evaluation = api.get(
            f"/v1/cases/{session['case_id']}/evaluations/{session['evaluation_id']}",
            headers=auth(token),
        ).json()
        assert evaluation["processing_state"] == "DRAFT_READY"
        assert evaluation["calculations"][0]["value"] == "1.5000"
        assert all(
            c["provider"] == "mock" and c["accounted_usd"] == "0" for c in evaluation["model_calls"]
        )
    assert len(set(actors)) == 3
    with get_engine().connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM model_calls WHERE provider='openai'")
            ).scalar_one()
            == 0
        )


def test_sessions_cannot_access_each_other_even_after_wrong_membership(guided, database):
    api, static = guided
    a, b = create(api), create(api)
    finish_jobs()
    ta = a["role_tokens"]["analyst"]
    actor = api.get("/v1/me", headers=auth(ta)).json()["actor_id"]
    with database.begin() as conn:
        conn.execute(
            text("INSERT INTO case_members VALUES(:case,:actor,'analyst')"),
            {"case": b["case_id"], "actor": actor},
        )
    assert [c["id"] for c in api.get("/v1/cases", headers=auth(ta)).json()["cases"]] == [
        a["case_id"]
    ]
    for suffix in ["", "/workspace", f"/evaluations/{b['evaluation_id']}/report.json"]:
        assert api.get("/v1/cases/" + b["case_id"] + suffix, headers=auth(ta)).status_code == 404
    assert api.get("/v1/cases/" + a["case_id"], headers=auth(static["admin"])).status_code == 404
    assert set(
        person["actor_id"]
        for person in api.get("/v1/assignment-directory", headers=auth(ta)).json()
    ) <= {api.get("/v1/me", headers=auth(t)).json()["actor_id"] for t in a["role_tokens"].values()}


def test_guided_capabilities_block_paid_calls_and_private_mutations(guided, monkeypatch):
    api, _ = guided
    session = create(api)
    finish_jobs()
    token = session["role_tokens"]["analyst"]
    headers = {**auth(token), "Idempotency-Key": "forbidden"}
    cid = session["case_id"]
    monkeypatch.setenv("CDS_LLM_LIVE_ENABLED", "true")
    get_settings.cache_clear()
    assert (
        api.post(
            "/v1/cases",
            headers=headers,
            json={"segment": "SME", "currency": "USD", "cutoff": "2026-01-31"},
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"/v1/cases/{cid}/members",
            headers=headers,
            json={"actor_id": "reviewer", "role": "reviewer"},
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"/v1/cases/{cid}/ai-evaluate",
            headers=headers,
            json={
                "source_evaluation_id": session["evaluation_id"],
                "provider": "openai",
                "workflow": "generalist",
            },
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"/v1/cases/{cid}/documents",
            headers=headers,
            data={"synthetic": "true"},
            files={"file": ("statement.csv", b"not a source", "text/csv")},
        ).status_code
        == 403
    )
    assert not api.get("/v1/me", headers=auth(token)).json()["live_model_enabled"]
    get_settings.cache_clear()


def test_role_review_and_revocation(guided):
    api, _ = guided
    session = create(api)
    finish_jobs()
    route = f"/v1/cases/{session['case_id']}/evaluations/{session['evaluation_id']}/review"
    body = {
        "expected_review_state": "PENDING",
        "decision": "NEEDS_MORE_INFO",
        "reason": "Synthetic follow-up requested.",
    }
    assert (
        api.post(
            route,
            headers={**auth(session["role_tokens"]["analyst"]), "Idempotency-Key": "a"},
            json=body,
        ).status_code
        == 403
    )
    reviewer = session["role_tokens"]["reviewer"]
    assert (
        api.post(route, headers={**auth(reviewer), "Idempotency-Key": "r"}, json=body).status_code
        == 201
    )
    report = api.get(
        route.removesuffix("/review") + "/report.json",
        headers=auth(session["role_tokens"]["auditor"]),
    )
    assert report.status_code == 200 and report.json()["review"]["state"] == "NEEDS_MORE_INFO"
    assert api.post("/v1/demo/session/end", headers=auth(reviewer)).status_code == 200
    for token in session["role_tokens"].values():
        assert api.get("/v1/me", headers=auth(token)).status_code == 401


def test_tokens_hashed_and_expiry_enforced(guided, database):
    api, _ = guided
    session = create(api)
    with database.begin() as conn:
        hashes = {
            r["role"]: r["token_hash"]
            for r in conn.execute(text("SELECT role,token_hash FROM demo_role_tokens")).mappings()
        }
        for role, token in session["role_tokens"].items():
            assert hashes[role] == hashlib.sha256(token.encode()).hexdigest()
            assert hashes[role] != token
        conn.exec_driver_sql("ALTER TABLE demo_sessions DISABLE TRIGGER USER")
        conn.exec_driver_sql(
            "UPDATE demo_sessions SET created_at=now()-interval '2 hours',"
            "expires_at=now()-interval '1 hour'"
        )
        conn.exec_driver_sql("ALTER TABLE demo_sessions ENABLE TRIGGER USER")
    assert api.get("/v1/me", headers=auth(session["role_tokens"]["analyst"])).status_code == 401
    with pytest.raises(DBAPIError), get_engine().begin() as conn:
        conn.exec_driver_sql("UPDATE demo_role_tokens SET actor_id='changed'")


def test_disabled_feature_and_origin_guard(client, catalog, monkeypatch):
    api, _ = client
    assert not api.get("/v1/demo/config").json()["enabled"]
    assert (
        api.post("/v1/demo/sessions", headers=MARKER, json={"role": "analyst"}).status_code == 404
    )
    monkeypatch.setenv("CDS_GUIDED_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    assert api.post("/v1/demo/sessions", json={"role": "analyst"}).status_code == 422
    assert api.post("/v1/demo/sessions", headers=MARKER, json={"role": "admin"}).status_code == 422
    assert (
        api.post(
            "/v1/demo/sessions",
            headers={**MARKER, "Origin": "https://unrelated.example"},
            json={"role": "analyst"},
        ).status_code
        == 403
    )
    session = create(api)
    monkeypatch.setenv("CDS_GUIDED_DEMO_ENABLED", "false")
    get_settings.cache_clear()
    assert api.get("/v1/me", headers=auth(session["role_tokens"]["analyst"])).status_code == 401
    get_settings.cache_clear()


def test_concurrent_capacity_and_retention_limit(guided, monkeypatch):
    api, _ = guided
    monkeypatch.setenv("CDS_DEMO_MAX_ACTIVE_SESSIONS", "1")
    monkeypatch.setenv("CDS_DEMO_MAX_SESSIONS", "1")
    get_settings.cache_clear()

    def attempt(_):
        return api.post("/v1/demo/sessions", headers=MARKER, json={"role": "analyst"})

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(r.status_code for r in results) == [201, 429]
    successful = next(r for r in results if r.status_code == 201).json()
    api.post("/v1/demo/session/end", headers=auth(successful["role_tokens"]["analyst"]))
    assert attempt(0).status_code == 429
    get_settings.cache_clear()


def test_unavailable_policy_leaves_no_session(client, monkeypatch, database):
    api, _ = client
    monkeypatch.setenv("CDS_GUIDED_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    assert (
        api.post("/v1/demo/sessions", headers=MARKER, json={"role": "analyst"}).status_code == 503
    )
    with database.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM demo_sessions")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM cases")).scalar_one() == 0
    get_settings.cache_clear()
