"""Verify tokenless demo entry, isolated roles, offline processing, exports, and revocation."""

import argparse
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
from evaluate_ai import wait
from pypdf import PdfReader


def run(base_url, output):
    with httpx.Client(base_url=base_url, timeout=60, trust_env=False) as client:
        assert client.get("/v1/demo/config").json()["enabled"]
        sessions = []
        try:
            for role in ("analyst", "auditor"):
                response = client.post(
                    "/v1/demo/sessions", headers={"X-Demo-Request": "1"}, json={"role": role}
                )
                response.raise_for_status()
                sessions.append(response.json())
            first, second = sessions

            def auth(role, session=first):
                return {"Authorization": "Bearer " + session["role_tokens"][role]}

            cid, eid = first["case_id"], first["evaluation_id"]
            evaluation = wait(client, auth("analyst"), cid, eid)
            assert evaluation["processing_state"] == "DRAFT_READY"
            assert evaluation["calculations"][0]["value"] == "1.5000"
            assert all(
                call["provider"] == "mock" and call["accounted_usd"] == "0"
                for call in evaluation["model_calls"]
            )
            for role in first["role_tokens"]:
                profile = client.get("/v1/me", headers=auth(role)).json()
                assert profile["role"] == role and profile["guided_demo"]
                assert not profile["live_model_enabled"]
                listed = client.get("/v1/cases", headers=auth(role)).json()["cases"]
                assert [case["id"] for case in listed] == [cid]
                assert (
                    client.get(f"/v1/cases/{second['case_id']}", headers=auth(role)).status_code
                    == 404
                )
            route = f"/v1/cases/{cid}/evaluations/{eid}"
            decision = {
                "expected_review_state": "PENDING",
                "decision": "NEEDS_MORE_INFO",
                "reason": "Additional synthetic evidence requested.",
            }
            reviewed = client.post(
                route + "/review",
                headers={**auth("reviewer"), "Idempotency-Key": str(uuid4())},
                json=decision,
            )
            reviewed.raise_for_status()
            for locale in ("en", "es"):
                report = client.get(
                    route + "/report.json", headers=auth("auditor"), params={"locale": locale}
                )
                report.raise_for_status()
                assert report.json()["review"]["state"] == "NEEDS_MORE_INFO"
                pdf = client.get(
                    route + "/report.pdf", headers=auth("auditor"), params={"locale": locale}
                )
                pdf.raise_for_status()
                snapshot = json.loads(
                    PdfReader(io.BytesIO(pdf.content)).attachments["report.json"][0]
                )
                expected = report.json()
                for payload in (snapshot, expected):
                    proof = payload.pop("integrity")
                    canonical = json.dumps(
                        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    )
                    assert hashlib.sha256(canonical.encode()).hexdigest() == proof["payload_sha256"]
                    payload.pop("generated_at")
                assert snapshot == expected
            asset = client.get("/assets/guided-demo.js")
            asset.raise_for_status()
            assert asset.headers["content-type"].startswith("text/javascript")
            assert (
                asset.content
                == (
                    Path(__file__).resolve().parent.parent / "src/credit_support/web/guided-demo.js"
                ).read_bytes()
            )
        finally:
            for session in sessions:
                token = session["role_tokens"]["analyst"]
                ended = client.post(
                    "/v1/demo/session/end", headers={"Authorization": "Bearer " + token}
                )
                ended.raise_for_status()
                for token in session["role_tokens"].values():
                    assert (
                        client.get(
                            "/v1/me", headers={"Authorization": "Bearer " + token}
                        ).status_code
                        == 401
                    )
    summary = {
        "provider": "mock",
        "paid_model_calls": 0,
        "prepared_dscr": "1.5000",
        "isolated_sessions_verified": 2,
        "roles_verified": ["analyst", "reviewer", "auditor"],
        "review_state": "NEEDS_MORE_INFO",
        "report_locales": ["en", "es"],
        "embedded_pdf_snapshot_verified": True,
        "session_revocation_verified": True,
        "static_asset_verified": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path("storage/guided-demo/summary.json"))
    args = parser.parse_args()
    run(args.base_url, args.output)
