from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from conftest import auth
from openapi_spec_validator import validate
from sqlalchemy import text

from credit_support.api import app

BODY = {"segment": "SME", "currency": "USD", "cutoff": "2026-01-31"}


def create(api, token, key="case-1", body=None):
    return api.post("/v1/cases", json=body or BODY, headers={**auth(token), "Idempotency-Key": key})


def test_health_readiness_and_openapi(client):
    api, _ = client
    assert api.get("/healthz").json() == {"status": "ok"}
    assert api.get("/readyz").json() == {"status": "ready"}
    validate(app.openapi())


def test_creation_authorization_and_validation(client):
    api, tokens = client
    assert api.post("/v1/cases", json=BODY).status_code == 401
    assert create(api, tokens["reviewer"]).status_code == 403
    assert create(api, tokens["analyst"], body={**BODY, "currency": "EUR"}).status_code == 422
    assert api.post("/v1/cases", json=BODY, headers=auth(tokens["analyst"])).status_code == 422
    response = create(api, tokens["analyst"])
    assert response.status_code == 201
    path = "/v1/cases/" + response.json()["id"]
    assert api.get(path, headers=auth(tokens["analyst"])).status_code == 200
    assert api.get(path, headers=auth(tokens["other"])).status_code == 404
    assert api.get(path, headers=auth(tokens["admin"])).status_code == 404
    assert api.get("/v1/cases/" + str(uuid4()), headers=auth(tokens["other"])).status_code == 404


def test_concurrent_idempotency_and_expiration(client, database):
    api, tokens = client
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: create(api, tokens["analyst"]), range(6)))
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert create(api, tokens["analyst"], body={**BODY, "cutoff": "2026-02-01"}).status_code == 409
    with database.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM cases")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 1
        conn.execute(text("UPDATE idempotency_records SET expires_at=now()-interval '1 second'"))
    assert create(api, tokens["analyst"]).json()["id"] != responses[0].json()["id"]


def test_audit_permissions_pagination_and_hash(client, database):
    import hashlib
    from uuid import UUID

    from credit_support.audit import append_event, canonical

    api, tokens = client
    case_id = create(api, tokens["analyst"]).json()["id"]
    with database.begin() as conn:
        conn.execute(
            text("INSERT INTO case_members VALUES(:id,'auditor','auditor')"), {"id": case_id}
        )
        append_event(conn, UUID(case_id), "analyst", "TEST_EVENT", {})
    path = f"/v1/cases/{case_id}/audit-events"
    assert api.get(path, headers=auth(tokens["other"])).status_code == 404
    first = api.get(path + "?limit=1", headers=auth(tokens["auditor"])).json()
    assert first["next_after_sequence"] == 1
    second = api.get(path + "?after_sequence=1&limit=1", headers=auth(tokens["auditor"])).json()
    assert second["events"][0]["previous_hash"] == first["events"][0]["event_hash"]
    event = first["events"][0]
    digest = event.pop("event_hash")
    event["case_id"] = case_id
    # API serializes UTC as Z; canonical audit encoding uses +00:00.
    event["created_at"] = event["created_at"].replace("Z", "+00:00")
    assert hashlib.sha256(canonical(event).encode()).hexdigest() == digest


def test_database_failure_is_redacted(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    import credit_support.api as module

    def unavailable():
        raise OperationalError("private database address", {}, Exception("secret"))

    api, _ = client
    monkeypatch.setattr(module, "get_engine", unavailable)
    response = api.get("/readyz")
    assert response.status_code == 503
    assert "secret" not in response.text
    assert "private" not in response.text
