"""Upload a synthetic statement pair and inspect the asynchronous extraction."""

import json
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parent.parent
configuration = dotenv_values(root / ".env")
identities = json.loads(configuration["CDS_DEMO_IDENTITIES"] or "{}")
token = next(token for token, actor in identities.items() if actor["role"] == "analyst")
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30) as client:
    auth = {"Authorization": "Bearer " + token}
    created = client.post(
        "/v1/cases",
        headers={**auth, "Idempotency-Key": "ingestion-demo"},
        json={"segment": "SME", "currency": "USD", "cutoff": "2026-01-31"},
    )
    created.raise_for_status()
    case_id = created.json()["id"]
    for extension, media in (("csv", "text/csv"), ("pdf", "application/pdf")):
        source = root / f"data/synthetic/generated/case-001.{extension}"
        response = client.post(
            f"/v1/cases/{case_id}/documents",
            headers={**auth, "Idempotency-Key": "demo-" + extension},
            data={"synthetic": "true"},
            files={"file": (source.name, source.read_bytes(), media)},
        )
        response.raise_for_status()
    queued = client.post(
        f"/v1/cases/{case_id}/extract", headers={**auth, "Idempotency-Key": "demo-extract"}
    )
    queued.raise_for_status()
    evaluation = queued.json()["evaluation_id"]
    deadline = time.monotonic() + 30
    while True:
        response = client.get(f"/v1/cases/{case_id}/evaluations/{evaluation}", headers=auth)
        response.raise_for_status()
        result = response.json()
        if result["job_status"] == "SUCCEEDED":
            break
        if result["job_status"] == "FAILED_TERMINAL":
            raise RuntimeError("Extraction failed; inspect the authorized evaluation response")
        if time.monotonic() > deadline:
            raise TimeoutError("Extraction is not complete; check that the worker is running")
        time.sleep(0.2)
    print(
        json.dumps(
            {
                "case_id": case_id,
                "evaluation_id": evaluation,
                "simulation": True,
                "job_status": result["job_status"],
                "facts": result["facts"],
                "evidence_count": len(result["evidence"]),
            },
            indent=2,
        )
    )
