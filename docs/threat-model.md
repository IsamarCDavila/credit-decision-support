# Threat model and verification

**English** | [Español](es/threat-model.md)

| Threat | Planned control | Acceptance scenario |
|---|---|---|
| Malicious PDF/policy instructions | Treat content as data; allowlisted tools; no shell; output validation | A PDF requests policy bypass; tools and rules remain unchanged |
| Fabricated amount or citation | Verify hash, excerpt, and value; reject unsupported conclusions | Altered value or nonexistent citation blocks the finding |
| Cross-case access | Server-side identity and case authorization on every route | Unrelated actor receives 404 without metadata |
| Self-approval or model decision | Reviewer differs from preparer; separate human endpoint | Analyst and worker cannot resolve the case |
| Stale review | Case lock, evaluation ID, and expected state | Upload/review race returns 409 for the stale snapshot |
| Duplicate execution | Idempotency and unique step/snapshot | Concurrent duplicate requests produce one job and result |
| Resource-exhausting PDF or manipulated path | Limits; isolated parser with timeout; server-generated storage key | Oversized file or path traversal is rejected |
| Credential theft | Ignored local environment files; redacted logs; minimal CI secrets | Secret scan and redaction checks |
| Altered audit history | Runtime role cannot UPDATE/DELETE; hash chain and backups | Tampering is detected, with administrator limitations documented |
| Mixed policy versions | Exact selection before RAG; filters and citation checks | Fragment from another version is rejected |
| Dependency/provider outage | Timeout; three attempts; lease; CI mock | Restart preserves committed steps without duplicate effects |

Trust boundaries are user→API, file→parser, content→LLM, LLM→tools, API/worker→database and storage, and runtime→provider. Real data is excluded. The provider can be disabled, and CI runs without external model calls. Demo identity is not production-grade authentication.
