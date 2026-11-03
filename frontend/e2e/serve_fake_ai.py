"""Start the API for the Playwright walkthrough with a fake Gemini (story #138).

`uv run python frontend/e2e/serve_fake_ai.py` serves the app like `revint serve`, but every brief
comes from a fixed, valid answer, so the walkthrough never calls Gemini and needs no key. Test
use only: the production code has no switch for this.
"""

from __future__ import annotations

import json
import os

import uvicorn

from revint.ai import briefs
from revint.ai.client import Reply
from revint.api.app import create_app
from revint.config import load_settings

ANSWER = {
    "headline": "Win back this customer",
    "explanation": "The measured facts show the customer has gone quiet.",
    "recommendation": "Call the customer this week.",
    "actions": [
        {"text": "Call the buyer", "suggested_owner_role": "Sales rep", "evidence_ids": []}
    ],
    "risks": [],
    "confidence_label": "Low",
    "evidence_ids_used": [],
}


class FakeGemini:
    def generate(self, **_kwargs: object) -> Reply:
        return Reply(text=json.dumps(ANSWER), token_in=1, token_out=1)


def main() -> None:
    briefs.default_client = FakeGemini  # type: ignore[assignment]
    settings = load_settings()
    # the walkthrough's own port and origin, so a server the user runs on 8000 is left alone
    port = int(os.environ.get("REVINT_E2E_PORT", settings.api.port))
    origin = os.environ.get("REVINT_E2E_ORIGIN")
    if origin:
        api = settings.api.model_copy(update={"port": port, "cors_origins": [origin]})
        settings = settings.model_copy(update={"api": api})
    uvicorn.run(create_app(settings), host=settings.api.host, port=port)


if __name__ == "__main__":
    main()
