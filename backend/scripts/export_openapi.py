"""Write the OpenAPI schema to backend/openapi.json (source for generated TS types)."""

import json
from pathlib import Path

from app.main import create_app

out = Path(__file__).resolve().parents[1] / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {out}")
