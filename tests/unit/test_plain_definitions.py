"""Story #169: every definition a screen shows has a plain-language text for sales managers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from revint.api.app import create_app
from revint.config import load_settings
from revint.data_dictionary import load_definitions, load_evidence_definitions

SERVICE = Path("src/revint/api/service.py")


def _screen_ids() -> set[str]:
    """The definition ids the API attaches to numbers, plus every evidence fact."""
    source = SERVICE.read_text(encoding="utf-8")
    used = set(re.findall(r'"(opp_[a-z_]+)"\)', source))  # metric(..., "<definition id>")
    return used | {item.id for item in load_evidence_definitions()}


def _all() -> dict[str, object]:
    return {item.id: item for item in [*load_definitions(), *load_evidence_definitions()]}


def test_ac1_the_screen_ids_are_found() -> None:
    ids = _screen_ids()
    assert {"opp_id", "opp_customer_key", "opp_score", "opp_value_low", "opp_value_high"} <= ids
    assert len(ids) >= 20


@pytest.mark.parametrize("definition_id", sorted(_screen_ids()))
def test_ac1_ac3_every_screen_definition_has_a_plain_text(definition_id: str) -> None:
    plain = _all()[definition_id].plain
    assert plain, f"{definition_id} has no plain text"
    assert len(re.findall(r"[.!?](\s|$)", plain)) <= 2, "at most 2 sentences"
    for token in ("_", "dim", "md5", "value.", "config", "as-of"):
        assert token not in plain.lower(), f"{definition_id}: technical term {token!r}"


def test_ac2_definitions_returns_the_plain_text_and_keeps_the_technical_one() -> None:
    body = TestClient(create_app(load_settings(env={}))).get("/api/v1/definitions").json()
    items = {d["id"]: d for d in body["definitions"]}
    assert items["opp_score"]["plain"].startswith("How strongly we recommend acting")
    assert "weighted sum" in items["opp_score"]["text"]  # the data dictionary text is unchanged
