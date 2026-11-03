"""The Gemini client (spec 05, story #137) behind a small interface, so tests use a fake.

The key is GEMINI_API_KEY, from the environment or the git-ignored .env file in the project
root. It is passed to the SDK only: it is never logged, printed, stored or returned.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from revint.ai.schema import AiBrief

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
KEY_NAME = "GEMINI_API_KEY"


class AiUnavailableError(Exception):
    """No key, or Gemini could not be reached (timeout, quota, network)."""


@dataclass(frozen=True)
class Reply:
    text: str
    token_in: int | None
    token_out: int | None


class BriefClient(Protocol):
    def generate(
        self, *, model: str, system: str, prompt: str, temperature: float, timeout_s: int
    ) -> Reply: ...


def api_key(env_file: Path = ENV_FILE) -> str | None:
    """The key from the environment, or else from .env; None when there is none."""
    value = os.environ.get(KEY_NAME)
    if value:
        return value
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, rest = line.partition("=")
            if name.strip() == KEY_NAME and rest.strip():
                return rest.strip().strip("'\"")
    return None


class GeminiClient:
    """The real client: google-genai with a JSON response schema."""

    def __init__(self, key: str) -> None:
        from google import genai  # imported here so the tests need no SDK set-up

        self._client = genai.Client(api_key=key)

    def generate(
        self, *, model: str, system: str, prompt: str, temperature: float, timeout_s: int
    ) -> Reply:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=AiBrief,
            http_options=types.HttpOptions(timeout=timeout_s * 1000),
        )
        try:
            response = self._client.models.generate_content(
                model=model, contents=prompt, config=config
            )
        except errors.APIError as exc:
            raise AiUnavailableError(f"Gemini error {exc.code}") from None
        except Exception as exc:  # network and timeout errors of the HTTP layer
            raise AiUnavailableError(
                f"Gemini could not be reached ({type(exc).__name__})"
            ) from None
        usage = response.usage_metadata
        return Reply(
            text=response.text or "",
            token_in=getattr(usage, "prompt_token_count", None),
            token_out=getattr(usage, "candidates_token_count", None),
        )


def default_client() -> BriefClient:
    key = api_key()
    if not key:
        raise AiUnavailableError(f"{KEY_NAME} is not set (put it in .env)")
    return GeminiClient(key)
