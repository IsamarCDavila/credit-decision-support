# Security, resilience, and measured load

**English** | [Español](es/hardening.md)

Phase 6 adds bounded demo admission, redacted operational telemetry, database wait limits, worker recovery after database errors, and a reproducible offline load protocol. It does not establish production readiness, a service guarantee, or suitability for real credit decisions.

## Operational controls

The API issues a fresh `X-Request-ID` for each request; caller-supplied identifiers are not trusted. JSON logs contain only that identifier, the method, matched route template, status, and elapsed milliseconds. They omit raw URLs, query strings, bodies, credentials, peer addresses, and financial values. Unknown paths/methods use bounded labels. The packaged server disables access logs and proxy-header rewriting; custom Uvicorn commands must also use `--no-access-log --no-proxy-headers` to preserve these boundaries. Log collection, retention, and alert routing remain deployment responsibilities.

`GET /v1/operations` requires a configured administrator identity. It returns current-process HTTP counters, uptime, aggregate durations, persistent job counts by status, and the age of the oldest runnable job. It exposes no case contents, credentials, or raw exceptions. API counters reset on restart and are not aggregated across replicas. Readiness checks the database/migration; it does not prove worker progress. Rising queue age requires operator investigation.

Demo creation is limited to `CDS_DEMO_REQUESTS_PER_MINUTE=8` requests per peer per fixed 60-second window, including unsuccessful attempts. Rejection is 429 with `Retry-After`. No forwarded header is read by this limiter. At most 1,024 peer windows are retained; new peers are rejected when that table is full until a window expires. A lock serializes admission inside each API process. Existing database limits also serialize active and retained session counts across processes. The rate limit is per process, shared by visitors behind the same peer/proxy, and is not a distributed abuse-defense service. Broader hosting requires trusted proxy design and an upstream limiter.

Database connections use a five-second connect/pool wait, a default 15-second statement timeout, five-second lock timeout, and 30-second idle transaction timeout. `CDS_DB_STATEMENT_TIMEOUT_MS` and `CDS_DB_LOCK_TIMEOUT_MS` configure SQL timeouts for native launches; Compose uses the defaults. Timeout errors return a redacted 503. The local Windows PostgreSQL build did not interrupt a deliberately delayed query, so timer interruption is checked on Linux CI rather than claimed from the local run. Linux CI must pass this test before acceptance.

The worker catches database-layer failures, logs a fixed diagnostic without SQL/exception text, waits its configured poll interval, and continues. Committed jobs remain durable; unfinished leases are reclaimed with a new fencing token and at most three attempts. The recovery test runs a new worker process after lease expiry and verifies one committed effect. Unknown programming errors still surface and require investigation. Network/model retries remain bounded by the existing model-call ledger; no automatic paid retry is added. The US$2 cumulative allowance and existing reservations remain intact.

## Reproduce the measurements

Start the API, persistent worker, PostgreSQL 16, and published synthetic policy. Existing private `.env` configuration is retained. From the repository root:

```sh
uv run pytest -q
uv run python scripts/evaluate_hardening.py --output storage/hardening.json
```

The script runs all ten frozen corpus variants at concurrency 1, 2, 4, and 8, with one client per in-flight case, one API process, and one worker. Each case creates an SME/USD workspace, uploads checksum-verified PDF and CSV inputs, extracts evidence, prepares a mock specialized draft, checks independent financial ground truth, assigns a reviewer, records a reasoned simulated decision, and reconstructs a hash-verified JSON report. No client retries hide failures. It records every initiated case, bounded failure categories, sample sizes, nearest-rank p95, throughput, and Wilson 95% intervals. Induced faults belong to the separate integration-test cohort, not the successful-load denominator.

The versioned [measurement report](../evaluations/reports/hardening-load.json) records environment, corpus hash, every scenario, and aggregate results. CI repeats concurrency 1 and 4 in the packaged Compose environment and retains `hardening-measurements` as a workflow artifact. CI timings describe that runner; they do not replace local measurements.

The packaged admission check is `uv run python scripts/smoke_operations.py`. Run it last: it intentionally reaches the demo frequency limit without creating cases. Wait for `Retry-After` before manually starting another demo from that peer.

## Acceptance interpretation

| Design target | Result and scope |
|---|---|
| Field extraction ≥95% | 240/240 status/value pairs agree on the controlled corpus; 16 explicit field abstentions remain included in the denominator |
| Material evidence coverage ≥99% | 320/320 emitted financial/policy cards verified against independent values/rules and reconstructible sources; applies to deterministic mock cards, not open-ended LLM prose |
| Zero unsupported material claims | Zero observed disagreements in those 320 verified cards; adversarial tests separately reject invented observations/citations |
| Human intervention measured | **Unmet:** no timed independent human study; mandatory review is retained |
| Draft below 15 minutes | Met in this protocol: worst tested level (8) p95 16.18 s; aggregate p95 14.02 s |
| Successful execution ≥99% | 40/40 observed; Wilson 95% interval 91.24–100%, insufficient to establish 99% population reliability |
| Reconstruct retained test snapshots | 40/40 retained draft reports verified; no deletion cohort or historical production population tested |
| Cost per case including infrastructure | **Unmet in full:** mock model cost is zero; infrastructure allocation is unmeasured |

Throughput was approximately 0.32, 0.45, 0.44, and 0.45 successful cases/s at concurrency 1, 2, 4, and 8. Increasing concurrency mostly increased queue delay with one worker. Eight is the highest tested concurrency, not a discovered saturation limit or a hosting recommendation. No long-duration soak, large-file load, multi-replica topology, unseen templates, backup restoration, or independent penetration test is represented. Version 0.6.0 remains a synthetic demonstration; these open targets preclude a claim that all version 1.0 acceptance criteria are met.
