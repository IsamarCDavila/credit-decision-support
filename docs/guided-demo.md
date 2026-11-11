# Guided demonstration

**English** | [Español](es/guided-demo.md)

The guided demonstration provides a prepared synthetic SME/USD case without an account, terminal command, or manually entered token. All outputs are **SIMULATION**. The model provider is always `mock`; guided credentials cannot request paid OpenAI processing, even when live processing is enabled for other users.

## User journey

1. Open the running workspace and select **Try demo**.
2. Choose Analyst, Reviewer, or Auditor. A new isolated session prepares an annual CSV statement, source evidence, DSCR of `1.5000`, versioned policy checks, and an offline draft through the persistent worker.
3. Inspect findings and evidence as Analyst. Use the role selector to become Reviewer and record a decision with a reason. The three roles have distinct simulated actor IDs, but one visitor controls them. This demonstrates workflow permissions, not independent real human approval or production identity verification.
4. Switch to Auditor to inspect the event history and download English/Spanish JSON or PDF reports. PDF exports include a verifiable JSON snapshot.
5. **Restart demo** ends the current session and creates a fresh case. **End demo** revokes all three role credentials. Both retain the existing case and audit history.

Credentials remain in browser memory; reloading loses access. Only the language preference persists. Sessions expire after 30 minutes by default. Closing the browser does not revoke the server session immediately; expiry still applies. If the server is unreachable during sign-out, local credentials are cleared and server expiry remains the fallback.

## Configuration and boundaries

`CDS_GUIDED_DEMO_ENABLED=false` is the default. `scripts/configure_demo.py` enables it for a new local demo installation. Existing installations can opt in through `.env`; restart the API after configuration changes and apply migration `0006_guided_demo`. Do not overwrite existing credentials or billing records.

| Setting | Default | Purpose |
|---|---|---|
| `CDS_DEMO_SESSION_TTL_SECONDS` | `1800` | Server-enforced credential lifetime; 60–7200 seconds |
| `CDS_DEMO_MAX_ACTIVE_SESSIONS` | `20` | Maximum concurrent unexpired sessions |
| `CDS_DEMO_MAX_SESSIONS` | `200` | Maximum retained sessions, including expired or ended sessions |

The database serializes session admission and returns 429 at capacity. There is no automatic history purge. Operators must review retention and capacity before wider hosting; resetting the database would also erase the cumulative model-cost ledger and must not be used to replenish an allowance. This milestone does not provide public-production traffic protection or a production identity provider.

Session credentials are random bearer tokens stored as SHA-256 hashes on the server. All three are returned once on creation. Each credential is restricted to its own session's case, including case listings and document/evaluation access. Guided users cannot create additional cases, upload sources, assign identities, or invoke paid models. The advanced workspace retains its existing configured-token workflow.

`POST /v1/demo/sessions` requires `X-Demo-Request: 1`, a valid initial role, and same-origin browser requests. This prevents cross-origin browser creation; it is not bot authentication. `POST /v1/demo/session/end` requires an active guided credential. The prepared policy must be published before session creation.

## Verification

```sh
uv run pytest -q tests/test_guided_demo.py
uv run python scripts/smoke_guided_demo.py
```

The integration tests cover role entry, prepared evidence, session isolation even after an incorrect membership insert, restricted mutations, paid-provider denial, reviewer permissions, token hashing, expiry/revocation, same-origin checks, concurrent capacity, and unavailable-policy rollback. The smoke test requires a running API/worker, published synthetic policy, and guided mode enabled. It verifies two isolated sessions, bilingual report snapshots and hashes, and revocation without printing credentials. Capacity and test results do not establish production readiness.
