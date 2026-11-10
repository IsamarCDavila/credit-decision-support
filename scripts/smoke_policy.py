"""Run the synthetic DSCR policy check after the ingestion demo."""

import json
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parent.parent
identities = json.loads(dotenv_values(root / ".env")["CDS_DEMO_IDENTITIES"] or "{}")
token = next(token for token, actor in identities.items() if actor["role"] == "analyst")
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30) as client:
    auth = {"Authorization": "Bearer " + token}
    case = client.post(
        "/v1/cases",
        headers={**auth, "Idempotency-Key": "ingestion-demo"},
        json={"segment": "SME", "currency": "USD", "cutoff": "2026-01-31"},
    )
    case.raise_for_status()
    case_id = case.json()["id"]
    source = client.post(
        f"/v1/cases/{case_id}/extract", headers={**auth, "Idempotency-Key": "demo-extract"}
    )
    source.raise_for_status()
    response = client.post(
        f"/v1/cases/{case_id}/evaluate",
        headers={**auth, "Idempotency-Key": "demo-policy-check"},
        json={"source_evaluation_id": source.json()["evaluation_id"]},
    )
    response.raise_for_status()
    evaluation_id = response.json()["evaluation_id"]
    deadline = time.monotonic() + 30
    while True:
        response = client.get(f"/v1/cases/{case_id}/evaluations/{evaluation_id}", headers=auth)
        response.raise_for_status()
        result = response.json()
        if result["job_status"] == "SUCCEEDED":
            break
        if result["job_status"] == "FAILED_TERMINAL":
            raise RuntimeError("Policy check failed")
        if time.monotonic() > deadline:
            raise TimeoutError("Worker did not finish the policy check")
        time.sleep(0.2)
    assert result["policy_check"]["policy_version"] == "SME-USD-DEMO-2026-01"
    print(
        json.dumps(
            {
                "evaluation_id": evaluation_id,
                "simulation": True,
                "calculations": result["calculations"],
                "policy_check": result["policy_check"],
            },
            indent=2,
            ensure_ascii=True,
        )
    )
