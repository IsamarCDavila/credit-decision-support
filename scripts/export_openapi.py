import json
from pathlib import Path

from credit_support.api import app

target = Path(__file__).resolve().parent.parent / "contracts/openapi.json"
target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
