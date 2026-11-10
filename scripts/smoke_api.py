"""Create and read a synthetic case using the local demo identity."""

import json
from pathlib import Path

import httpx
from dotenv import dotenv_values

configuration = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
identities = json.loads(configuration["CDS_DEMO_IDENTITIES"] or "{}")
token = next(token for token, actor in identities.items() if actor["role"] == "analyst")
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
    headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "quickstart-case"}
    created = client.post(
        "/v1/cases",
        headers=headers,
        json={
            "segment": "SME",
            "currency": "USD",
            "cutoff": "2026-01-31",
        },
    )
    created.raise_for_status()
    case_id = created.json()["id"]
    read = client.get(f"/v1/cases/{case_id}", headers=headers)
    read.raise_for_status()
    print(json.dumps(read.json(), indent=2))
