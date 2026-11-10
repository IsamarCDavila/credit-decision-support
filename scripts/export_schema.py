"""Export the reference SQL from the versioned migration sources."""

import runpy
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parts = [
    (root / "migrations" / name).read_text(encoding="utf-8")
    for name in ("0001_schema.sql", "0001_controls.sql")
]
parts.append(runpy.run_path(str(root / "migrations/versions/0002_ingestion.py"))["SQL"])
(root / "contracts/schema.sql").write_text(
    "-- Reference export through 0002_ingestion. Apply changes with Alembic.\n" + "\n".join(parts),
    encoding="utf-8",
)
