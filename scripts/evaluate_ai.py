"""Compare bounded generalist and specialized workflows on controlled synthetic statements."""

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from evaluate_baseline import reference


def wait(client, headers, case_id, evaluation_id):
    deadline = time.monotonic() + 240
    while True:
        response = client.get(f"/v1/cases/{case_id}/evaluations/{evaluation_id}", headers=headers)
        response.raise_for_status()
        value = response.json()
        if value["job_status"] in ("SUCCEEDED", "FAILED_TERMINAL"):
            return value
        if time.monotonic() > deadline:
            raise TimeoutError("AI workflow did not complete within 240 seconds")
        time.sleep(0.2)


def run(root, base_url, provider, repetitions, output):
    identities = json.loads(dotenv_values(root / ".env")["CDS_DEMO_IDENTITIES"] or "{}")
    token = next(t for t, actor in identities.items() if actor["role"] == "analyst")
    auth = {"Authorization": "Bearer " + token}
    corpus = root / "data/synthetic/generated"
    manifest = json.loads((corpus / "manifest.json").read_text())
    variants = ("complete", "ambiguous", "injection") if provider == "openai" else None
    records = [r for r in manifest["cases"] if variants is None or r["variant"] in variants]
    run_id = str(uuid4())
    report = {
        "evaluation": "bounded-ai-comparison-v1",
        "run_id": run_id,
        "run_at_utc": datetime.now(UTC).isoformat(),
        "provider": provider,
        "corpus_seed": manifest["seed"],
        "repetitions": repetitions,
        "campaign_status": "running",
        "planned_workflow_runs": len(records) * repetitions * 2,
        "pricing_usd_per_million_tokens": {"input": "2", "output": "12"},
        "limitations": [
            "Controlled synthetic CSVs, not narrative documents or real credit cases.",
            "Material wording is rendered by code; "
            "this is not a free-text hallucination benchmark.",
            "Generalist selects claim IDs before tools; "
            "specialized draft role sees verified claim cards.",
            "Equal total output-token cap (4096) does not equalize context or actual consumption.",
            "Mock results validate orchestration only; no model-quality or speedup claim.",
            "Small sample; no claim of superiority, statistical significance, "
            "or manual time savings.",
        ],
        "runs": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        runs = report["runs"]
        report["summary"] = {}
        for workflow in ("generalist", "multi_agent"):
            values = [r for r in runs if r["workflow"] == workflow]
            if not values:
                continue
            report["summary"][workflow] = {
                "runs": len(values),
                "successful": sum(r["succeeded"] for r in values),
                "ground_truth_matches": sum(r["matches_ground_truth"] for r in values),
                "fully_grounded_drafts": sum(r["grounded_complete_draft"] for r in values),
                "model_calls": sum(len(r["model_calls"]) for r in values),
                "input_tokens": sum(
                    c["input_tokens"] or 0 for r in values for c in r["model_calls"]
                ),
                "output_tokens": sum(
                    c["output_tokens"] or 0 for r in values for c in r["model_calls"]
                ),
                "charged_or_reserved_usd": str(
                    sum(
                        (Decimal(c["accounted_usd"]) for r in values for c in r["model_calls"]),
                        Decimal(0),
                    )
                ),
                "unknown_usage_calls": sum(
                    c["cost_status"] == "reserved" for r in values for c in r["model_calls"]
                ),
                "median_seconds": round(statistics.median(r["elapsed_seconds"] for r in values), 4),
            }
        output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:

        def post(route, key, **kwargs):
            response = client.post(
                route, headers={**auth, "Idempotency-Key": run_id + "-" + key}, **kwargs
            )
            response.raise_for_status()
            return response.json()

        for repeat in range(1, repetitions + 1):
            for record in records:
                case = post(
                    "/v1/cases",
                    f"{repeat}-{record['case_id']}",
                    json={"segment": "SME", "currency": "USD", "cutoff": "2026-01-31"},
                )
                case_id = case["id"]
                filename = record["case_id"] + ".csv"
                post(
                    f"/v1/cases/{case_id}/documents",
                    "document-" + case_id,
                    data={"synthetic": "true"},
                    files={"file": (filename, (corpus / filename).read_bytes(), "text/csv")},
                )
                source = post(f"/v1/cases/{case_id}/extract", "source-" + case_id)
                extracted = wait(client, auth, case_id, source["evaluation_id"])
                if extracted["job_status"] != "SUCCEEDED":
                    raise RuntimeError("Source extraction failed")
                # Alternate order to reduce systematic warm-up bias in this serial experiment.
                workflows = ["generalist", "multi_agent"]
                if repeat % 2 == 0:
                    workflows.reverse()
                for workflow in workflows:
                    started = time.perf_counter()
                    receipt = post(
                        f"/v1/cases/{case_id}/ai-evaluate",
                        workflow + case_id,
                        json={
                            "source_evaluation_id": source["evaluation_id"],
                            "provider": provider,
                            "workflow": workflow,
                        },
                    )
                    result = wait(client, auth, case_id, receipt["evaluation_id"])
                    actual = {
                        f["key"]: {"status": f["status"], "value": f["value"]}
                        for f in result["facts"]
                    }
                    draft = result["ai_draft"]
                    expected_ids = {"fact:" + k for k in record["expected"]} | {
                        "calculation:DSCR",
                        "rule:DSCR_MINIMUM",
                        "review:required",
                        "limitation:simulation",
                    }
                    observed = None
                    if result["calculations"] and result["policy_check"]:
                        metric, check = result["calculations"][0], result["policy_check"]
                        observed = {
                            "metric_status": metric["status"],
                            "display": metric["value"],
                            "outcome": check["outcome"],
                            "rule_status": check["rule_results"][0]["status"],
                        }
                    fact_ids = {f["id"] for f in result["facts"]}
                    evidence_ids = {e["id"] for e in result["evidence"]}
                    calculation_ids = {c["id"] for c in result["calculations"]}
                    grounded = bool(
                        draft
                        and draft["requires_human_review"]
                        and draft["simulation"]
                        and {c["id"] for c in draft["claims"]} == expected_ids
                        and all(
                            set(c["fact_ids"]) <= fact_ids
                            and set(c["evidence_ids"]) <= evidence_ids
                            and set(c["calculation_ids"]) <= calculation_ids
                            and set(c["policy_fragment_ids"])
                            <= {"dscr-definition", "DSCR_MINIMUM", "scope"}
                            for c in draft["claims"]
                        )
                    )
                    row = {
                        "variant": record["variant"],
                        "repetition": repeat,
                        "workflow": workflow,
                        "evaluation_id": receipt["evaluation_id"],
                        "succeeded": result["job_status"] == "SUCCEEDED",
                        "matches_ground_truth": actual == record["expected"]
                        and observed == reference(record["expected"]),
                        "grounded_complete_draft": grounded,
                        "elapsed_seconds": round(time.perf_counter() - started, 4),
                        "model_calls": result["model_calls"],
                        "error": (result["result"] or {}).get("error"),
                    }
                    report["runs"].append(row)
                    if not row["succeeded"] and provider == "openai":
                        report["campaign_status"] = "blocked"
                    save()
                    print(
                        json.dumps(
                            {k: row[k] for k in ("variant", "workflow", "succeeded", "error")}
                        ),
                        flush=True,
                    )
                    if not row["succeeded"] and provider == "openai":
                        # Stop on live failure to preserve the remaining allowance.
                        return report
    report["campaign_status"] = "completed"
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["mock", "openai"], default="mock")
    parser.add_argument("--repetitions", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path("storage/ai-comparison.json"))
    args = parser.parse_args()
    result = run(
        Path(__file__).resolve().parent.parent,
        args.base_url,
        args.provider,
        args.repetitions,
        args.output,
    )
    print(json.dumps(result["summary"], indent=2))
    if any(
        not r["succeeded"] or not r["matches_ground_truth"] or not r["grounded_complete_draft"]
        for r in result["runs"]
    ):
        raise SystemExit(1)
