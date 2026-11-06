"""Story #137: AI brief generation (spec 05). All tests use a fake Gemini client.

The warehouse is the acceptance warehouse of story #115 (one customer per engine), with the
opportunity stage run once per module; each test gets its own app.duckdb. Customer codes carry
a SECRET- marker, so a test can prove no code or name ever reaches a package, a prompt, the
stored row or the output. The one live test is marked `live` and skipped without a key.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pytest
from silver_helpers import query
from test_opportunity_acceptance import built, copied  # noqa: F401
from typer.testing import CliRunner

from revint.ai import briefs, store
from revint.ai.client import AiUnavailableError, Reply, api_key
from revint.ai.evidence import EvidencePackage
from revint.ai.guardrails import GuardrailError, check
from revint.ai.prompts import PROMPTS_DIR, prompt_for
from revint.ai.schema import AiBrief
from revint.cli import app
from revint.config import Settings
from revint.opportunities import run_opportunities

runner = CliRunner()


@pytest.fixture(scope="module")
def ready(built: Settings, tmp_path_factory: pytest.TempPathFactory) -> Settings:  # noqa: F811
    settings = copied(built, tmp_path_factory.mktemp("ai"))
    run_opportunities(settings)
    return settings


@pytest.fixture
def work(ready: Settings, tmp_path: Path) -> Settings:
    """The ready warehouse (read only) with a fresh app.duckdb for this test."""
    return ready.model_copy(
        update={"paths": ready.paths.model_copy(update={"app_db": tmp_path / "app.duckdb"})}
    )


def identities(settings: Settings) -> list[tuple[str, str]]:
    """Every customer code and name of the warehouse (synthetic, with the SECRET- marker).
    Category names carry the marker too, but they are product data and may be sent."""
    return query(
        settings,
        "select customer_code, customer_name from dim_customer where customer_key <> -1",
    )


def opp(settings: Settings, engine: str) -> str:
    return query(
        settings, "select opp_id from opp_opportunities where type = ? order by rank", engine
    )[0][0]


def good_brief(package: EvidencePackage, **changes: object) -> dict:
    fact = package.facts[0]
    brief = {
        "headline": f"{package.entity} needs attention",
        "explanation": f"{fact.label} is {fact.value}.",
        "recommendation": "Call the customer this week.",
        "actions": [
            {
                "text": "Call the customer",
                "suggested_owner_role": "Sales rep",
                "evidence_ids": [fact.id],
            }
        ],
        "risks": [],
        "confidence_label": "Low",
        "evidence_ids_used": [fact.id],
    }
    brief.update(changes)
    return brief


@dataclass
class FakeClient:
    """Answers with the given texts in turn (the last repeats) and records every call."""

    answers: list[str]
    calls: list[dict] = field(default_factory=list)

    def generate(self, **kwargs: object) -> Reply:
        self.calls.append(kwargs)
        text = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        return Reply(text=text, token_in=100, token_out=50)


def fake_for(settings: Settings, opp_id: str, **changes: object) -> FakeClient:
    package = briefs.package_for(settings, opp_id)
    return FakeClient([json.dumps(good_brief(package, **changes))])


# AC1: the evidence package ------


@pytest.mark.parametrize("engine", ["dormancy", "recovery", "whitespace", "crosssell"])
def test_ac1_a_package_holds_no_customer_code_name_or_row(work: Settings, engine: str) -> None:
    package = briefs.package_for(work, opp(work, engine))
    text = package.to_json()
    for code, name in identities(work):  # no customer code or name
        assert code not in text and name not in text
    assert package.entity.startswith("Customer C-")
    for field_name in ("customer_key", "sales_line_id", "_source_row", "customer_code"):
        assert field_name not in text, field_name
    assert package.facts and all(f.definition for f in package.facts)
    assert package.estimate.kind == "Estimate"


def test_ac1_the_mask_is_stable_and_kept_in_app_db(work: Settings) -> None:
    one = briefs.package_for(work, opp(work, "dormancy")).entity
    assert briefs.package_for(work, opp(work, "dormancy")).entity == one
    ((n,),) = (
        duckdb.connect(str(work.paths.app_db), read_only=True)
        .execute("select count(*) from app_entity_masks")
        .fetchall()
    )
    assert n == 1


def test_ac1_max_facts_is_applied(work: Settings) -> None:
    settings = work.model_copy(update={"ai": work.ai.model_copy(update={"max_facts": 2})})
    assert len(briefs.package_for(settings, opp(work, "dormancy")).facts) == 2


def test_ac1_the_hash_follows_the_evidence(work: Settings) -> None:
    a = briefs.package_for(work, opp(work, "dormancy"))
    b = briefs.package_for(work, opp(work, "recovery"))
    assert a.evidence_hash() == briefs.package_for(work, opp(work, "dormancy")).evidence_hash()
    assert a.evidence_hash() != b.evidence_hash()


# AC2: the schema and the model settings ------


def test_ac2_gemini_is_called_with_the_configured_model_and_temperature(work: Settings) -> None:
    opp_id = opp(work, "recovery")
    client = fake_for(work, opp_id)
    briefs.generate(work, opp_id, client)
    (call,) = client.calls
    assert (call["model"], call["temperature"]) == (work.ai.model, 0.2)
    assert briefs.package_for(work, opp_id).to_json() in call["prompt"]


def test_ac2_the_schema_limits_the_fields() -> None:
    with pytest.raises(ValueError):
        AiBrief.model_validate(
            {
                "headline": "x" * 121,
                "explanation": "e",
                "recommendation": "r",
                "actions": [],
                "confidence_label": "Low",
            }
        )


# AC3: versioned prompts ------


def test_ac3_prompts_exist_for_every_engine_and_carry_a_version() -> None:
    names = {p.name for p in PROMPTS_DIR.glob("*.md")}
    assert {
        "system.v1.md",
        "dormancy.v1.md",
        "recovery.v1.md",
        "whitespace.v1.md",
        "crosssell.v1.md",
    } <= names
    version = prompt_for("dormancy").version
    assert re.match(r"system\.v\d+\+dormancy\.v1@", version)  # the newest system prompt
    assert prompt_for("dormancy").version != prompt_for("recovery").version


def test_ac3_a_newer_prompt_file_gives_a_new_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import revint.ai.prompts as prompts

    for path in PROMPTS_DIR.glob("*.md"):
        shutil.copy(path, tmp_path / path.name)
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    before = prompts.prompt_for("dormancy").version
    (tmp_path / "dormancy.v2.md").write_text("A new task text.\n", encoding="utf-8")
    after = prompts.prompt_for("dormancy").version
    assert re.match(r"system\.v\d+\+dormancy\.v2@", after) and after != before


# AC4: guardrails ------


def test_ac4_an_invented_number_is_rejected(work: Settings) -> None:
    package = briefs.package_for(work, opp(work, "dormancy"))
    brief = AiBrief.model_validate(good_brief(package, explanation="Sales could grow 987654."))
    with pytest.raises(GuardrailError, match="G2"):
        check(brief, package)


def test_ac4_numbers_from_the_evidence_pass_in_formatted_form(work: Settings) -> None:
    package = briefs.package_for(work, opp(work, "recovery"))
    amount = package.estimate.value_high
    brief = AiBrief.model_validate(
        good_brief(package, explanation=f"The estimate is up to {amount:,.0f} in net sales.")
    )
    check(brief, package)


# Story #158: the masked customer label is not a number --------


@pytest.mark.parametrize("label", ["Customer C-0017", "C-0042", "customer C-0001"])
def test_158_ac1_the_entity_label_is_not_read_as_a_number(work: Settings, label: str) -> None:
    package = briefs.package_for(work, opp(work, "dormancy"))
    brief = AiBrief.model_validate(
        good_brief(package, explanation=f"{label} has gone quiet.", recommendation=f"Call {label}.")
    )
    check(brief, package)


def test_158_ac2_an_invented_number_next_to_the_label_is_still_rejected(work: Settings) -> None:
    package = briefs.package_for(work, opp(work, "dormancy"))
    brief = AiBrief.model_validate(
        good_brief(package, explanation=f"{package.entity} could buy 987654 more.")
    )
    with pytest.raises(GuardrailError, match="G2: the number 987654"):
        check(brief, package)


def test_158_ac3_the_label_pattern_is_defined_once_in_the_store() -> None:
    found = store.ENTITY_LABEL.search(store.LABEL_FORMAT.format(n=17))
    assert found is not None and found.group() == "C-0017"
    source = Path("src/revint/ai/guardrails.py").read_text(encoding="utf-8")
    assert "store.ENTITY_LABEL" in source
    assert "C-" not in source  # no second copy of the label format


def test_ac4_an_unknown_evidence_id_is_rejected(work: Settings) -> None:
    package = briefs.package_for(work, opp(work, "dormancy"))
    brief = AiBrief.model_validate(good_brief(package, evidence_ids_used=["made_up"]))
    with pytest.raises(GuardrailError, match="G3"):
        check(brief, package)


@pytest.mark.parametrize(
    "phrase", ["Offer a discount.", "Protect the margin.", "Sales fell because of competitors."]
)
def test_ac4_a_banned_term_is_rejected(work: Settings, phrase: str) -> None:
    package = briefs.package_for(work, opp(work, "dormancy"))
    brief = AiBrief.model_validate(good_brief(package, recommendation=phrase))
    with pytest.raises(GuardrailError, match="G6"):
        check(brief, package)


def test_ac4_confidence_cannot_exceed_the_engine(work: Settings) -> None:
    package = briefs.package_for(work, opp(work, "dormancy"))
    higher = {"Low": "Medium", "Medium": "High"}.get(package.confidence)
    if higher is None:
        pytest.skip("the engine confidence is already High")
    brief = AiBrief.model_validate(good_brief(package, confidence_label=higher))
    with pytest.raises(GuardrailError, match="G5"):
        check(brief, package)


def test_ac4_invalid_json_is_retried_then_stored_as_failed(work: Settings) -> None:
    opp_id = opp(work, "dormancy")
    client = FakeClient(["not json", '{"headline": 1}'])
    result = briefs.generate(work, opp_id, client)
    assert len(client.calls) == work.ai.max_retries + 1
    assert result.output.validation_status == "failed"
    assert result.output.response is None  # never partial text


def test_ac4_a_retry_can_succeed(work: Settings) -> None:
    opp_id = opp(work, "dormancy")
    package = briefs.package_for(work, opp_id)
    client = FakeClient(["not json", json.dumps(good_brief(package))])
    result = briefs.generate(work, opp_id, client)
    assert (len(client.calls), result.output.validation_status) == (2, "valid")


# AC5: storage, cache and the daily limit ------


def test_ac5_a_valid_brief_is_stored_with_its_provenance(work: Settings) -> None:
    opp_id = opp(work, "whitespace")
    briefs.generate(work, opp_id, fake_for(work, opp_id))
    con = duckdb.connect(str(work.paths.app_db), read_only=True)
    ((evidence, digest, model, version, status, review, t_in, t_out, when),) = con.execute(
        "select evidence_json, evidence_hash, model, prompt_version, validation_status, "
        "review_status, token_in, token_out, generated_at from app_ai_outputs"
    ).fetchall()
    con.close()
    assert (model, status, review, t_in, t_out) == (work.ai.model, "valid", "Draft", 100, 50)
    assert digest == briefs.package_for(work, opp_id).evidence_hash() and when is not None
    assert version == prompt_for("whitespace").version
    for code, name in identities(work):
        assert code not in evidence and name not in evidence


def test_ac5_the_warehouse_is_never_written(work: Settings) -> None:
    before = work.paths.warehouse.stat().st_mtime_ns
    opp_id = opp(work, "crosssell")
    briefs.generate(work, opp_id, fake_for(work, opp_id))
    assert work.paths.warehouse.stat().st_mtime_ns == before
    tables = {t for (t,) in query(work, "select table_name from information_schema.tables")}
    assert not any(t.startswith("app_") for t in tables)


def test_ac5_the_same_evidence_hits_the_cache(work: Settings) -> None:
    opp_id = opp(work, "dormancy")
    client = fake_for(work, opp_id)
    first = briefs.generate(work, opp_id, client)
    second = briefs.generate(work, opp_id, client)
    assert (first.cached, second.cached, len(client.calls)) == (False, True, 1)
    assert second.output.output_id == first.output.output_id


def test_ac5_a_changed_model_misses_the_cache(work: Settings) -> None:
    opp_id = opp(work, "dormancy")
    client = fake_for(work, opp_id)
    briefs.generate(work, opp_id, client)
    other = work.model_copy(update={"ai": work.ai.model_copy(update={"model": "gemini-other"})})
    assert briefs.generate(other, opp_id, client).cached is False
    assert len(client.calls) == 2


def test_ac5_a_regeneration_adds_a_row_and_overwrites_nothing(work: Settings) -> None:
    opp_id = opp(work, "dormancy")
    client = fake_for(work, opp_id)
    briefs.generate(work, opp_id, client)
    briefs.generate(work, opp_id, client, force=True)
    con = duckdb.connect(str(work.paths.app_db), read_only=True)
    assert con.execute("select count(*) from app_ai_outputs").fetchall() == [(2,)]
    con.close()


def test_ac5_the_daily_call_limit_is_enforced(work: Settings) -> None:
    settings = work.model_copy(update={"ai": work.ai.model_copy(update={"daily_call_limit": 1})})
    first, second = opp(work, "dormancy"), opp(work, "recovery")
    briefs.generate(settings, first, fake_for(settings, first))
    with pytest.raises(AiUnavailableError, match="daily call limit"):
        briefs.generate(settings, second, fake_for(settings, second))


def test_ac5_ai_disabled_makes_no_call(work: Settings) -> None:
    settings = work.model_copy(update={"ai": work.ai.model_copy(update={"enabled": False})})
    client = FakeClient(["{}"])
    with pytest.raises(briefs.AiDisabledError):
        briefs.generate(settings, opp(work, "dormancy"), client)
    assert client.calls == []


# AC6: the commands ------


def use(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVINT_PATHS_WAREHOUSE", str(settings.paths.warehouse))
    monkeypatch.setenv("REVINT_PATHS_APP_DB", str(settings.paths.app_db))


def test_ac6_app_init_creates_the_app_db(work: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    use(work, monkeypatch)
    result = runner.invoke(app, ["app", "init"])
    assert result.exit_code == 0, result.output
    con = duckdb.connect(str(work.paths.app_db), read_only=True)
    tables = {
        t for (t,) in con.execute("select table_name from information_schema.tables").fetchall()
    }
    con.close()
    assert {"app_ai_outputs", "app_entity_masks"} <= tables


def test_ac6_ai_generate_prints_counts_only(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(work, monkeypatch)

    def client() -> FakeClient:
        # one good answer per call: the brief quotes only the entity, so it fits any package
        brief = {
            "headline": "Follow up",
            "explanation": "See the evidence.",
            "recommendation": "Call the customer.",
            "actions": [{"text": "Call", "suggested_owner_role": "Sales rep", "evidence_ids": []}],
            "risks": [],
            "confidence_label": "Low",
            "evidence_ids_used": [],
        }
        return FakeClient([json.dumps(brief)])

    monkeypatch.setattr(briefs, "default_client", client)
    result = runner.invoke(app, ["ai", "generate", "--top", "3"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "ai generate: 3 valid, 0 failed, 0 cached of 3"
    again = runner.invoke(app, ["ai", "generate", "--top", "3"])
    assert again.output.strip() == "ai generate: 0 valid, 0 failed, 3 cached of 3"


def test_ac6_opp_and_top_together_fail(work: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    use(work, monkeypatch)
    result = runner.invoke(app, ["ai", "generate", "--opp", "x", "--top", "2"])
    assert result.exit_code == 1


# AC7: the key ------


def test_ac7_no_key_is_a_clear_unavailable_error(
    work: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import revint.ai.client as client_module

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(client_module, "ENV_FILE", tmp_path / "no.env")
    monkeypatch.setattr(client_module.api_key, "__defaults__", (tmp_path / "no.env",))
    with pytest.raises(AiUnavailableError, match="GEMINI_API_KEY is not set"):
        briefs.generate(work, opp(work, "dormancy"))


def test_ac7_the_key_is_read_from_the_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nGEMINI_API_KEY=test-key-123\n", encoding="utf-8")
    assert api_key(env) == "test-key-123"


def test_ac7_the_key_never_appears_in_output_or_storage(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET-KEY-VALUE")
    opp_id = opp(work, "dormancy")
    briefs.generate(work, opp_id, fake_for(work, opp_id))
    con = duckdb.connect(str(work.paths.app_db), read_only=True)
    dump = repr(con.execute("select * from app_ai_outputs").fetchall())
    con.close()
    assert "SECRET-KEY-VALUE" not in dump


def test_ac7_the_env_file_is_git_ignored() -> None:
    root = Path(__file__).resolve().parents[2]
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [line.strip() for line in ignore]


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("REVINT_LIVE") != "1" or api_key() is None,
    reason="a real Gemini call: run with REVINT_LIVE=1 and GEMINI_API_KEY set",
)
def test_ac7_live_gemini_returns_a_valid_brief(work: Settings) -> None:
    """One real call (`REVINT_LIVE=1 uv run pytest -m live -n 0`); asserts the status only."""
    result = briefs.generate(work, opp(work, "dormancy"))
    assert result.output.validation_status in ("valid", "failed")


# AC8 ------


def test_ac8_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 8):
        assert f"def test_ac{ac}_" in text


def test_ac8_the_store_is_only_app_db() -> None:
    source = Path(store.__file__).read_text(encoding="utf-8")
    assert "paths.app_db" in source and "paths.warehouse" not in source


# Story #172: numbers in the brief look like the screens ------


@pytest.mark.parametrize(
    ("value", "unit", "shown"),
    [
        (47.0, "days", "47"),
        (14.0, "days", "14"),
        (3661650.0, "net sales", "3,661,650"),
        (915412.5, "net sales", "915,413"),
        (0.8503, "share", "85.03%"),
        (85.03, "percent", "85.03%"),
        (2.456, "ratio", "2.46"),
        (12.5, "orders", "12.5"),
        ("2020-01-13", "date", "2020-01-13"),
    ],
)
def test_172_ac1_display_matches_the_screen_format(value: object, unit: str, shown: str) -> None:
    from revint.ai.evidence import display_value

    assert display_value(value, unit) == shown


def test_172_ac1_the_package_carries_display_forms(work: Settings) -> None:
    package = briefs.package_for(work, opp(work, "dormancy"))
    assert all(f.display for f in package.facts)
    assert package.estimate.value_high_display is not None
    assert (
        "." not in package.estimate.value_high_display or "%" in package.estimate.value_high_display
    )


def test_172_ac1_the_newest_prompt_asks_for_the_display_form() -> None:
    prompt = prompt_for("dormancy")
    assert prompt.version.startswith("system.v2+")
    assert "display" in prompt.system


def test_172_ac2_display_forms_pass_g2_and_inventions_still_fail(work: Settings) -> None:
    package = briefs.package_for(work, opp(work, "dormancy"))
    shown = " and ".join(f.display for f in package.facts if f.unit != "date")
    brief = AiBrief.model_validate(
        good_brief(
            package, explanation=f"Facts: {shown}; up to {package.estimate.value_high_display}."
        )
    )
    check(brief, package)
    with pytest.raises(GuardrailError, match="G2"):
        check(
            AiBrief.model_validate(good_brief(package, explanation="It could add 7,777,777.")),
            package,
        )
