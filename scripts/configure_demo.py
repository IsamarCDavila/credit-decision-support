"""Generate local-only credentials without printing tokens or overwriting existing configuration."""

import json
import secrets
from pathlib import Path

target = Path(__file__).resolve().parent.parent / ".env"
identities = {
    secrets.token_urlsafe(32): {"actor_id": actor, "role": role}
    for actor, role in (
        ("demo-analyst", "analyst"),
        ("demo-reviewer", "reviewer"),
        ("demo-auditor", "auditor"),
        ("demo-admin", "admin"),
    )
}
content = (
    "CDS_GUIDED_DEMO_ENABLED=true\n"
    f"CDS_DATABASE_PASSWORD={secrets.token_hex(24)}\n"
    f"CDS_RUNTIME_PASSWORD={secrets.token_hex(24)}\n"
    f"CDS_DEMO_IDENTITIES='{json.dumps(identities)}'\n"
)
with target.open("x", encoding="utf-8") as stream:
    stream.write(content)
print("Created .env. Keep this file private; do not commit it.")
