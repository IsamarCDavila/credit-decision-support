"""Exercise assigned independent review and bilingual report exports using the offline model."""

import argparse
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from evaluate_ai import wait
from pypdf import PdfReader


def run(base_url, output):
    root = Path(__file__).resolve().parent.parent
    identities = json.loads(dotenv_values(root / ".env")["CDS_DEMO_IDENTITIES"] or "{}")
    selected = {
        role: next(
            (token, actor["actor_id"])
            for token, actor in identities.items()
            if actor["role"] == role
        )
        for role in ("analyst", "reviewer", "auditor")
    }
    run_id = str(uuid4())
    with httpx.Client(base_url=base_url, timeout=60, trust_env=False) as client:
        page = client.get("/")
        page.raise_for_status()
        assert "script-src 'self'" in page.headers["content-security-policy"]
        for asset, media in [
            ("workspace.js", "text/javascript"),
            ("guided-demo.js", "text/javascript"),
            ("workspace.css", "text/css"),
        ]:
            response = client.get("/assets/" + asset)
            response.raise_for_status()
            assert response.headers["content-type"].startswith(media)
            assert response.content == (root / "src/credit_support/web" / asset).read_bytes()

        def headers(role):
            return {"Authorization": "Bearer " + selected[role][0]}

        def post(route, key, role="analyst", **kwargs):
            response = client.post(
                route, headers={**headers(role), "Idempotency-Key": run_id + "-" + key}, **kwargs
            )
            response.raise_for_status()
            return response.json()

        case = post(
            "/v1/cases", "case", json={"segment": "SME", "currency": "USD", "cutoff": "2026-01-31"}
        )
        cid = case["id"]
        for ext, media in [("csv", "text/csv"), ("pdf", "application/pdf")]:
            name = "case-001." + ext
            post(
                f"/v1/cases/{cid}/documents",
                ext,
                data={"synthetic": "true"},
                files={
                    "file": (name, (root / "data/synthetic/generated" / name).read_bytes(), media)
                },
            )
        source = post(f"/v1/cases/{cid}/extract", "extract")
        assert (
            wait(client, headers("analyst"), cid, source["evaluation_id"])["job_status"]
            == "SUCCEEDED"
        )
        receipt = post(
            f"/v1/cases/{cid}/ai-evaluate",
            "draft",
            json={
                "source_evaluation_id": source["evaluation_id"],
                "provider": "mock",
                "workflow": "multi_agent",
            },
        )
        eid = receipt["evaluation_id"]
        assert wait(client, headers("analyst"), cid, eid)["job_status"] == "SUCCEEDED"
        for role in ["reviewer", "auditor"]:
            post(
                f"/v1/cases/{cid}/members", role, json={"actor_id": selected[role][1], "role": role}
            )
        body = {
            "expected_review_state": "PENDING",
            "decision": "NEEDS_MORE_INFO",
            "reason": "Synthetic demonstration: request an independent follow-up "
            "before any final assessment.",
        }
        route = f"/v1/cases/{cid}/evaluations/{eid}/review"
        reviewed = post(route, "review", role="reviewer", json=body)
        assert post(route, "review", role="reviewer", json=body) == reviewed
        assert (
            client.post(
                route, headers={**headers("reviewer"), "Idempotency-Key": str(uuid4())}, json=body
            ).status_code
            == 409
        )
        output.mkdir(parents=True, exist_ok=True)
        for locale in ["en", "es"]:
            for ext in ["json", "pdf"]:
                response = client.get(
                    f"/v1/cases/{cid}/evaluations/{eid}/report.{ext}",
                    headers=headers("auditor"),
                    params={"locale": locale},
                )
                response.raise_for_status()
                (output / f"review-report.{locale}.{ext}").write_bytes(response.content)
                if ext == "json":
                    report = response.json()
                    integrity = report.pop("integrity")
                    canonical = json.dumps(
                        report, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    )
                    assert (
                        hashlib.sha256(canonical.encode()).hexdigest()
                        == integrity["payload_sha256"]
                    )
                    assert report["review"]["state"] == "NEEDS_MORE_INFO"
                else:
                    reader = PdfReader(io.BytesIO(response.content))
                    embedded = json.loads(reader.attachments["report.json"][0])
                    proof = embedded.pop("integrity")
                    canonical = json.dumps(
                        embedded, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    )
                    assert hashlib.sha256(canonical.encode()).hexdigest() == proof["payload_sha256"]
                    assert embedded["review"]["state"] == "NEEDS_MORE_INFO"
                    text = "\n".join(p.extract_text() for p in reader.pages)
                    assert ("SIMULACIÓN" if locale == "es" else "SIMULATION") in text
                    assert "NEEDS_MORE_INFO" in text and eid in text
        summary = {
            "case_id": cid,
            "evaluation_id": eid,
            "review_state": reviewed["decision"],
            "provider": "mock",
            "paid_model_calls": 0,
            "report_locales": ["en", "es"],
            "report_formats": ["json", "pdf"],
            "idempotency_verified": True,
            "duplicate_review_blocked": True,
            "static_assets_verified": True,
            "embedded_pdf_snapshot_verified": True,
        }
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path("storage/review-demo"))
    args = parser.parse_args()
    run(args.base_url, args.output_dir)
