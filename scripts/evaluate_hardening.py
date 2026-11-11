"""Measure ten synthetic scenarios under bounded concurrency using only the mock provider."""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from evaluate_ai import wait
from evaluate_baseline import reference


def wilson(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [round(center - half, 6), round(center + half, 6)]


def timings(values):
    ordered = sorted(values)
    return {
        "median_seconds": round(statistics.median(ordered), 4) if ordered else None,
        "p95_seconds": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 4) if ordered else None,
    }


def run(base_url, levels, output):
    root = Path(__file__).resolve().parent.parent
    configured = json.loads(dotenv_values(root / ".env")["CDS_DEMO_IDENTITIES"] or "{}")
    actors = {
        role: next(
            (token, actor["actor_id"])
            for token, actor in configured.items()
            if actor["role"] == role
        )
        for role in ("analyst", "reviewer", "admin")
    }
    corpus = root / "data/synthetic/generated"
    manifest_bytes = (corpus / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    records = manifest["cases"]
    assert len(records) >= 10
    campaign = str(uuid4())

    def headers(role):
        return {"Authorization": "Bearer " + actors[role][0]}

    def scenario(record, level):
        row = {"variant": record["variant"], "concurrency": level, "succeeded": False}
        started = time.perf_counter()
        try:
            with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:

                def post(path, payload=None, **kwargs):
                    response = client.post(
                        path,
                        headers={**headers("analyst"), "Idempotency-Key": str(uuid4())},
                        json=payload,
                        **kwargs,
                    )
                    response.raise_for_status()
                    return response.json()

                case = post(
                    "/v1/cases", {"segment": "SME", "currency": "USD", "cutoff": "2026-01-31"}
                )
                cid = case["id"]
                for ext, media in (("csv", "text/csv"), ("pdf", "application/pdf")):
                    name = record["case_id"] + "." + ext
                    data = (corpus / name).read_bytes()
                    assert hashlib.sha256(data).hexdigest() == record["sha256"][name]
                    post(
                        f"/v1/cases/{cid}/documents",
                        data={"synthetic": "true"},
                        files={"file": (name, data, media)},
                    )
                uploaded = time.perf_counter()
                source = post(f"/v1/cases/{cid}/extract")
                assert (
                    wait(client, headers("analyst"), cid, source["evaluation_id"])["job_status"]
                    == "SUCCEEDED"
                )
                receipt = post(
                    f"/v1/cases/{cid}/ai-evaluate",
                    {
                        "source_evaluation_id": source["evaluation_id"],
                        "provider": "mock",
                        "workflow": "multi_agent",
                    },
                )
                eid = receipt["evaluation_id"]
                result = wait(client, headers("analyst"), cid, eid)
                row["upload_to_draft_seconds"] = round(time.perf_counter() - uploaded, 4)
                row["emitted_material_claims"] = sum(
                    c["section"] in {"financials", "policy"}
                    for c in (result.get("ai_draft") or {}).get("claims", [])
                )
                assert result["processing_state"] == "DRAFT_READY"
                observed = {
                    f["key"]: {"status": f["status"], "value": f["value"]} for f in result["facts"]
                }
                expected = record["expected"]
                row["fields"] = len(expected)
                row["correct_fields"] = sum(observed.get(k) == v for k, v in expected.items())
                row["abstained_fields"] = sum(f["status"] != "extracted" for f in observed.values())
                assert observed == expected
                metric, check = result["calculations"][0], result["policy_check"]
                assert {
                    "metric_status": metric["status"],
                    "display": metric["value"],
                    "rule_status": check["rule_results"][0]["status"],
                    "outcome": check["outcome"],
                } == reference(expected)
                assert all(
                    c["provider"] == "mock" and c["accounted_usd"] == "0"
                    for c in result["model_calls"]
                )
                post(
                    f"/v1/cases/{cid}/members",
                    {"actor_id": actors["reviewer"][1], "role": "reviewer"},
                )
                review = client.post(
                    f"/v1/cases/{cid}/evaluations/{eid}/review",
                    headers={**headers("reviewer"), "Idempotency-Key": str(uuid4())},
                    json={
                        "expected_review_state": "PENDING",
                        "decision": "NEEDS_MORE_INFO",
                        "reason": "Synthetic acceptance assessment; no real credit decision.",
                    },
                )
                review.raise_for_status()
                report = client.get(
                    f"/v1/cases/{cid}/evaluations/{eid}/report.json", headers=headers("reviewer")
                )
                report.raise_for_status()
                payload = report.json()
                proof = payload.pop("integrity")
                canonical = json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
                assert hashlib.sha256(canonical.encode()).hexdigest() == proof["payload_sha256"]
                assert payload["review"]["state"] == "NEEDS_MORE_INFO"
                assert payload["evaluation"]["ai_draft"] == result["ai_draft"]
                row.update(
                    succeeded=True,
                    reconstructed=True,
                    evaluation_id=eid,
                    material_claims=sum(
                        c["section"] in {"financials", "policy"}
                        for c in result["ai_draft"]["claims"]
                    ),
                )
        except Exception as exc:
            # Exception text can contain URLs or request data. Record only a bounded category.
            row["error_type"] = type(exc).__name__
        row["total_seconds"] = round(time.perf_counter() - started, 4)
        return row

    report = {
        "protocol": "synthetic-hardening-v1",
        "campaign_id": campaign,
        "run_at_utc": datetime.now(UTC).isoformat(),
        "provider": "mock",
        "paid_model_calls": 0,
        "environment": {
            "os": platform.system(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "worker_processes": 1,
            "api_processes": 1,
            "postgres_major": 16,
        },
        "corpus_seed": manifest["seed"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "scenarios_per_level": len(records),
        "levels": [],
        "runs": [],
        "limitations": (
            "Closed-loop, small synthetic fixtures, one API/worker and PostgreSQL. "
            "No OpenAI, production traffic, sustained soak, real-human timing, "
            "infrastructure allocation, or unseen-template generalization. "
            "Highest tested concurrency is not a saturation limit. "
            "Fields/claims concern deterministic verified mock drafts. "
            "Failures are retained; no client retries."
        ),
    }

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    for level in levels:
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=level) as pool:
            rows = list(pool.map(lambda record, current=level: scenario(record, current), records))
        elapsed = time.perf_counter() - started
        valid = [r for r in rows if r["succeeded"]]
        summary = {
            "concurrency": level,
            "initiated": len(rows),
            "succeeded": len(valid),
            "wilson95": wilson(len(valid), len(rows)),
            "elapsed_seconds": round(elapsed, 4),
            "successful_cases_per_second": round(len(valid) / elapsed, 4),
            **timings([r["upload_to_draft_seconds"] for r in valid]),
        }
        report["levels"].append(summary)
        report["runs"].extend(rows)
        save()
        print(json.dumps(summary), flush=True)
    rows = report["runs"]
    successes = sum(r["succeeded"] for r in rows)
    report["summary"] = {
        "initiated": len(rows),
        "succeeded": successes,
        "wilson95": wilson(successes, len(rows)),
        "correct_fields": sum(r.get("correct_fields", 0) for r in rows),
        "expected_fields": len(rows) * len(records[0]["expected"]),
        "abstained_fields": sum(r.get("abstained_fields", 0) for r in rows),
        "reconstructed_snapshots": sum(r.get("reconstructed", False) for r in rows),
        "verified_material_claims": sum(r.get("material_claims", 0) for r in rows),
        "emitted_material_claims": sum(r.get("emitted_material_claims", 0) for r in rows),
        "highest_tested_concurrency": max(levels),
        **timings([r["upload_to_draft_seconds"] for r in rows if r["succeeded"]]),
    }
    with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:
        ops = client.get("/v1/operations", headers=headers("admin"))
        ops.raise_for_status()
        report["operations_after"] = ops.json()
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--concurrency", type=int, nargs="+", choices=[1, 2, 4, 8], default=[1, 2, 4, 8]
    )
    parser.add_argument("--output", type=Path, default=Path("storage/hardening.json"))
    args = parser.parse_args()
    result = run(args.base_url, args.concurrency, args.output)
    if result["summary"]["succeeded"] != result["summary"]["initiated"]:
        raise SystemExit(1)
