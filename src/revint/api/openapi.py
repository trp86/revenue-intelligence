"""Write the committed OpenAPI schema (story #134): `uv run python -m revint.api.openapi`.

A test fails when docs/openapi.json and the app's schema differ, so a change to the API is
reviewed together with its contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from revint.api.app import create_app
from revint.config import load_settings

OPENAPI_FILE = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


def schema_text() -> str:
    """The app's OpenAPI schema as stable JSON text."""
    schema = create_app(load_settings(env={})).openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    OPENAPI_FILE.write_text(schema_text(), encoding="utf-8")
    print(f"openapi: wrote {OPENAPI_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
