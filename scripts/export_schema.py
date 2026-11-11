"""Export the reference SQL from the versioned migration sources."""

import runpy
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parts = [
    (root / "migrations" / name).read_text(encoding="utf-8")
    for name in ("0001_schema.sql", "0001_controls.sql")
]
for revision in (
    "0002_ingestion",
    "0003_policy_engine",
    "0004_ai_workflow",
    "0005_human_review",
    "0006_guided_demo",
):
    parts.append(runpy.run_path(str(root / f"migrations/versions/{revision}.py"))["SQL"])
(root / "contracts/schema.sql").write_text(
    "-- Reference export through 0006_guided_demo. Apply changes with Alembic.\n"
    + "\n".join(parts),
    encoding="utf-8",
)
