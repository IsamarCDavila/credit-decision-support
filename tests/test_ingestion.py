import hashlib
import io
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import ROOT, auth
from generate_synthetic_cases import VARIANTS, build_case, encode_csv, encode_pdf, generate
from pypdf import PdfWriter
from sqlalchemy import text

from credit_support.db import get_engine
from credit_support.parsers import MAX_FILE_BYTES, IngestionError, parse_document
from credit_support.worker import claim, finish


def new_case(api, token, key="case"):
    response = api.post(
        "/v1/cases",
        headers={**auth(token), "Idempotency-Key": key},
        json={
            "segment": "SME",
            "currency": "USD",
            "cutoff": "2026-01-31",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(api, token, case_id, data, extension="csv", key="doc", synthetic="true", mime=None):
    media = mime or ("text/csv" if extension == "csv" else "application/pdf")
    return api.post(
        f"/v1/cases/{case_id}/documents",
        headers={**auth(token), "Idempotency-Key": key},
        data={"synthetic": synthetic},
        files={"file": ("statement." + extension, data, media)},
    )


def queue(api, token, case_id, key="extract"):
    response = api.post(
        f"/v1/cases/{case_id}/extract", headers={**auth(token), "Idempotency-Key": key}
    )
    assert response.status_code == 202, response.text
    return response.json()


def read_extraction(api, token, case_id, receipt):
    response = api.get(
        f"/v1/cases/{case_id}/evaluations/{receipt['evaluation_id']}", headers=auth(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("extension", ["csv", "pdf"])
def test_synthetic_corpus_with_verified_locators(client, variant, extension):
    api, tokens = client
    case_id = new_case(api, tokens["analyst"])
    rows, expected = build_case(100, variant)
    data = encode_csv(rows) if extension == "csv" else encode_pdf(rows)
    uploaded = upload(api, tokens["analyst"], case_id, data, extension)
    assert uploaded.status_code == 202, uploaded.text
    document = uploaded.json()
    assert document["sha256"] == hashlib.sha256(data).hexdigest()
    detail = api.get(
        f"/v1/cases/{case_id}/documents/{document['document_id']}", headers=auth(tokens["analyst"])
    ).json()
    content = api.get(
        f"/v1/cases/{case_id}/documents/{document['document_id']}/content",
        headers=auth(tokens["analyst"]),
    )
    assert content.content == data
    assert content.headers["x-content-type-options"] == "nosniff"
    receipt = queue(api, tokens["analyst"], case_id)
    job = claim(get_engine(), "worker", 30)
    assert job and finish(get_engine(), job)
    result = read_extraction(api, tokens["analyst"], case_id, receipt)
    assert result["job_status"] == "SUCCEEDED"
    assert result["processing_state"] == "VALIDATING"
    actual = {f["key"]: {"status": f["status"], "value": f["value"]} for f in result["facts"]}
    assert actual == expected
    for evidence in result["evidence"]:
        loc = evidence["locator"]
        if extension == "csv":
            original = detail["rows"][loc["row"] - 2][loc["column"]]
        else:
            original = detail["pages"][loc["page"] - 1][loc["start"] : loc["end"]]
        assert original == evidence["excerpt"]
        assert evidence["sha256"] == document["sha256"]


@pytest.mark.parametrize(
    "kind", ["empty", "bad_pdf", "bad_utf8", "bad_header", "encrypted", "scanned", "too_many_pages"]
)
def test_reject_unreadable_documents(client, kind):
    api, tokens = client
    case_id = new_case(api, tokens["analyst"])
    data, extension = b"", "csv"
    if kind == "bad_pdf":
        data, extension = b"%PDF-1.7 broken", "pdf"
    elif kind == "bad_utf8":
        data = b"\xff\xfe"
    elif kind == "bad_header":
        data = b"key,value\nrevenue,100\n"
    elif kind in ("encrypted", "scanned", "too_many_pages"):
        writer = PdfWriter()
        for _ in range(101 if kind == "too_many_pages" else 1):
            writer.add_blank_page(width=612, height=792)
        if kind == "encrypted":
            writer.encrypt("private-test-document")
        stream = io.BytesIO()
        writer.write(stream)
        data, extension = stream.getvalue(), "pdf"
    response = upload(api, tokens["analyst"], case_id, data, extension)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "change",
    [
        {"currency": "EUR"},
        {"basis": "consolidated"},
        {"synthetic": "false"},
        {"period_start": "2025-02-01"},
        {"period_end": "2026-12-31"},
    ],
)
def test_reject_unsupported_scope(client, change):
    api, tokens = client
    case_id = new_case(api, tokens["analyst"])
    rows, _ = build_case()
    for row in rows:
        row.update(change)
    assert upload(api, tokens["analyst"], case_id, encode_csv(rows)).status_code == 422


def test_permissions_synthetic_declaration_and_size(client):
    api, tokens = client
    case_id = new_case(api, tokens["analyst"])
    data = encode_csv(build_case()[0])
    assert upload(api, tokens["other"], case_id, data).status_code == 404
    assert upload(api, tokens["analyst"], case_id, data, synthetic="false").status_code == 422
    assert upload(api, tokens["analyst"], case_id, data, mime="application/pdf").status_code == 422
    assert upload(api, tokens["analyst"], case_id, b"x" * (MAX_FILE_BYTES + 1)).status_code == 413
    response = api.post(
        "/v1/cases",
        headers={**auth(tokens["analyst"]), "Content-Type": "application/json"},
        content=iter([b'"', b"x" * (MAX_FILE_BYTES + 70_000), b'"']),
    )
    assert response.status_code == 413
    uploaded = upload(api, tokens["analyst"], case_id, data).json()
    path = f"/v1/cases/{case_id}/documents/{uploaded['document_id']}"
    assert api.get(path, headers=auth(tokens["other"])).status_code == 404
    assert api.get(path + "/content", headers=auth(tokens["other"])).status_code == 404


def test_concurrent_upload_idempotency_and_extraction_deduplication(client, database):
    api, tokens = client
    case_id = new_case(api, tokens["analyst"])
    data = encode_csv(build_case()[0])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: upload(api, tokens["analyst"], case_id, data), range(4)))
    assert {r.status_code for r in results} == {202}
    assert len({r.json()["document_id"] for r in results}) == 1
    assert upload(api, tokens["analyst"], case_id, encode_csv(build_case(2)[0])).status_code == 409
    first = queue(api, tokens["analyst"], case_id)
    assert queue(api, tokens["analyst"], case_id, "different-key") == first
    with database.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 1


def test_new_upload_preserves_history_and_conflicting_sources(client):
    api, tokens = client
    case_id = new_case(api, tokens["analyst"])
    rows, _ = build_case()
    assert upload(api, tokens["analyst"], case_id, encode_csv(rows)).status_code == 202
    old = queue(api, tokens["analyst"], case_id)
    assert finish(get_engine(), claim(get_engine(), "worker", 30))
    first = read_extraction(api, tokens["analyst"], case_id, old)
    rows[0]["value"] = "123.00"
    assert (
        upload(api, tokens["analyst"], case_id, encode_pdf(rows), "pdf", "new").status_code == 202
    )
    historical = read_extraction(api, tokens["analyst"], case_id, old)
    assert not historical["current"]
    assert historical["facts"] == first["facts"]
    new = queue(api, tokens["analyst"], case_id, "new-snapshot")
    assert new != old
    assert finish(get_engine(), claim(get_engine(), "worker", 30))
    current = read_extraction(api, tokens["analyst"], case_id, new)
    assert current["current"]
    revenue = next(f for f in current["facts"] if f["key"] == "annual_revenue")
    assert revenue["status"] == "ambiguous" and revenue["value"] is None


def test_checksum_failure_has_no_partial_facts(client, database):
    api, tokens = client
    case_id = new_case(api, tokens["analyst"])
    upload(api, tokens["analyst"], case_id, encode_csv(build_case()[0]))
    receipt = queue(api, tokens["analyst"], case_id)
    with database.begin() as conn:
        conn.execute(text("ALTER TABLE document_contents DISABLE TRIGGER contents_immutable"))
        conn.execute(text("UPDATE document_contents SET data='tampered'::bytea"))
        conn.execute(text("ALTER TABLE document_contents ENABLE TRIGGER contents_immutable"))
    assert finish(get_engine(), claim(get_engine(), "worker", 30))
    result = read_extraction(api, tokens["analyst"], case_id, receipt)
    assert result["job_status"] == "FAILED_TERMINAL"
    assert result["processing_state"] == "FAILED_TERMINAL"
    assert not result["facts"] and not result["evidence"]


def test_pdf_blank_page_and_parser_timeout(monkeypatch):
    rows, _ = build_case()
    parsed = parse_document(encode_pdf(rows, blank_first_page=True), "application/pdf")
    assert parsed["candidates"][0]["locator"]["page"] == 2

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("parser", 0.01)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(IngestionError, match="time limit"):
        parse_document(encode_csv(rows), "text/csv")


def test_document_limit_and_mixed_period(client):
    api, tokens = client
    case_id = new_case(api, tokens["analyst"])
    for n in range(20):
        assert (
            upload(
                api, tokens["analyst"], case_id, encode_csv(build_case(n)[0]), key=str(n)
            ).status_code
            == 202
        )
    assert (
        upload(
            api, tokens["analyst"], case_id, encode_csv(build_case(99)[0]), key="overflow"
        ).status_code
        == 413
    )
    other = new_case(api, tokens["analyst"], "other-case")
    rows, _ = build_case()
    upload(api, tokens["analyst"], other, encode_csv(rows))
    for row in rows:
        row.update(period_start="2024-01-01", period_end="2024-12-31")
    assert (
        upload(api, tokens["analyst"], other, encode_csv(rows), key="old-period").status_code == 422
    )


def test_generator_is_reproducible(artifact_dir):
    manifest = generate(artifact_dir, 100)
    for case in manifest["cases"]:
        for filename, digest in case["sha256"].items():
            assert hashlib.sha256((artifact_dir / filename).read_bytes()).hexdigest() == digest
    again = generate(artifact_dir, 100)
    assert manifest == again
    committed = json.loads((ROOT / "data/synthetic/generated/manifest.json").read_text())
    assert committed == manifest
