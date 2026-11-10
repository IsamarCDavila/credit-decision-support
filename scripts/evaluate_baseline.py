"""Compare the live deterministic pipeline with independent synthetic ground truth."""

import argparse
import hashlib
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values


def reference(expected):
    inputs = [expected[k] for k in ("available_cash_flow", "debt_service")]
    if any(f["status"] == "invalid" for f in inputs):
        status = "INVALID_INPUT"
    elif any(f["status"] != "extracted" for f in inputs):
        status = "MISSING_INPUT"
    elif Fraction(inputs[1]["value"]) < 0:
        status = "INVALID_INPUT"
    elif Fraction(inputs[1]["value"]) == 0:
        status = "NOT_APPLICABLE"
    else:
        status = "CALCULATED"
    passes = None
    display = None
    if status == "CALCULATED":
        ratio = Fraction(inputs[0]["value"]) / Fraction(inputs[1]["value"])
        passes = ratio >= Fraction("1.20")
        rounded, remainder = divmod(abs(ratio.numerator) * 10000, ratio.denominator)
        rounded += int(2 * remainder >= ratio.denominator)
        display = ("-" if ratio < 0 else "") + f"{rounded // 10000}.{rounded % 10000:04}"
    outcome = (
        "insufficient_evidence"
        if passes is None or any(f["status"] != "extracted" for f in expected.values())
        else "meets_rules"
        if passes
        else "exceptions"
    )
    return {
        "metric_status": status,
        "rule_status": "REQUIRES_REVIEW" if passes is None else "PASS" if passes else "FAIL",
        "outcome": outcome,
        "display": display,
    }


def wait(client, headers, case_id, evaluation_id):
    deadline = time.monotonic() + 30
    while True:
        response = client.get(f"/v1/cases/{case_id}/evaluations/{evaluation_id}", headers=headers)
        response.raise_for_status()
        value = response.json()
        if value["job_status"] == "SUCCEEDED":
            return value
        if value["job_status"] == "FAILED_TERMINAL":
            raise RuntimeError("Terminal baseline job")
        if time.monotonic() > deadline:
            raise TimeoutError("Baseline worker timeout")
        time.sleep(0.1)


def run(root, base_url):
    identities = json.loads(dotenv_values(root / ".env")["CDS_DEMO_IDENTITIES"] or "{}")
    token = next(token for token, actor in identities.items() if actor["role"] == "analyst")
    auth = {"Authorization": "Bearer " + token}
    corpus = root / "data/synthetic/generated"
    manifest = json.loads((corpus / "manifest.json").read_text())
    run_id = str(uuid4())
    cases = []
    with httpx.Client(base_url=base_url, timeout=30) as client:
        published = client.get("/v1/policies/SME-USD-DEMO-2026-01", headers=auth)
        published.raise_for_status()
        expected_citations = published.json()["fragments"]

        def post(route, key, **kwargs):
            response = client.post(
                route, headers={**auth, "Idempotency-Key": run_id + "-" + key}, **kwargs
            )
            response.raise_for_status()
            return response.json()

        for record in manifest["cases"]:
            start = time.perf_counter()
            case = post(
                "/v1/cases",
                record["case_id"],
                json={"segment": "SME", "currency": "USD", "cutoff": "2026-01-31"},
            )
            case_id = case["id"]
            for extension, media in (("csv", "text/csv"), ("pdf", "application/pdf")):
                name = record["case_id"] + "." + extension
                data = (corpus / name).read_bytes()
                assert hashlib.sha256(data).hexdigest() == record["sha256"][name]
                post(
                    f"/v1/cases/{case_id}/documents",
                    name,
                    data={"synthetic": "true"},
                    files={"file": (name, data, media)},
                )
            source = post(f"/v1/cases/{case_id}/extract", record["case_id"] + "-extract")
            wait(client, auth, case_id, source["evaluation_id"])
            queued = post(
                f"/v1/cases/{case_id}/evaluate",
                record["case_id"] + "-evaluate",
                json={"source_evaluation_id": source["evaluation_id"]},
            )
            result = wait(client, auth, case_id, queued["evaluation_id"])
            actual = {
                f["key"]: {"status": f["status"], "value": f["value"]} for f in result["facts"]
            }
            gold = reference(record["expected"])
            metric = result["calculations"][0]
            check = result["policy_check"]
            observed = {
                "metric_status": metric["status"],
                "rule_status": check["rule_results"][0]["status"],
                "outcome": check["outcome"],
                "display": metric["value"],
            }
            agreement = actual == record["expected"] and observed == gold
            citations_valid = (
                check["policy_version"] == "SME-USD-DEMO-2026-01"
                and all(c["policy_version"] == check["policy_version"] for c in check["citations"])
                and check["citations"] == expected_citations
                and check["rule_results"][0]["threshold"] == "1.20"
            )
            cases.append(
                {
                    "case_id": record["case_id"],
                    "variant": record["variant"],
                    "expected": gold,
                    "observed": observed,
                    "matches_ground_truth": agreement,
                    "policy_citations_valid": citations_valid,
                    "elapsed_seconds": round(time.perf_counter() - start, 4),
                }
            )
    times = sorted(c["elapsed_seconds"] for c in cases)
    return {
        "baseline": "deterministic-synthetic-v1",
        "run_at_utc": datetime.now(UTC).isoformat(),
        "environment": {"python": platform.python_version(), "platform": platform.system()},
        "corpus_seed": manifest["seed"],
        "case_count": len(cases),
        "matching_cases": sum(c["matches_ground_truth"] for c in cases),
        "valid_policy_citation_cases": sum(c["policy_citations_valid"] for c in cases),
        "median_seconds": round(statistics.median(times), 4),
        "p95_seconds": times[-1],
        "model_calls": 0,
        "model_tokens": 0,
        "infrastructure_cost_usd": None,
        "limitations": "Ten controlled synthetic cases; no real-world accuracy, service-level, "
        "manual time-saving, or statistical generalization claim.",
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--output", type=Path, default=Path("evaluations/reports/deterministic-baseline.json")
    )
    args = parser.parse_args()
    report = run(Path(__file__).resolve().parent.parent, args.base_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: report[k] for k in ("case_count", "matching_cases", "valid_policy_citation_cases")}
        )
    )
    if (
        report["matching_cases"] != report["case_count"]
        or report["valid_policy_citation_cases"] != report["case_count"]
    ):
        raise SystemExit("Baseline differs from the independent reference")
