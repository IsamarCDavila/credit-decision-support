"""Read an assigned local demo credential without exposing it by default."""

import argparse
import json
from pathlib import Path

from dotenv import dotenv_values

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--role", choices=["analyst", "reviewer", "auditor", "admin"], required=True)
parser.add_argument(
    "--show-token", action="store_true", help="Print the private local workspace token"
)
args = parser.parse_args()
try:
    config = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
    identities = json.loads(config.get("CDS_DEMO_IDENTITIES") or "{}")
    token, actor = next(
        (token, actor) for token, actor in identities.items() if actor["role"] == args.role
    )
except (ValueError, KeyError, StopIteration, AttributeError):
    raise SystemExit("A matching local demo identity is not configured.") from None
print(token if args.show_token else f"{actor['actor_id']} | {actor['role']} | token hidden")
