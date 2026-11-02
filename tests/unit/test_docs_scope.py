"""Story #133: the POC scope cut and the faster process are written down (docs only)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def doc(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def test_ac1_decisions_record_the_scope_cut() -> None:
    text = doc("decisions.md")
    section = text[text.index("## 11. Scope cut for the POC (2026-11-02)") :]
    assert "3 days" in section
    for kept in ("E5 AI layer", "E6 API", "E7 Frontend"):
        assert kept in section, kept
    for dropped in ("E4 Backtest", "E8 Explore and Assistant", "E9 Action tracking"):
        assert dropped in section, dropped
    assert "#9, #13, #14" in section


def test_ac2_success_criteria_3_and_6_are_dropped_and_5_has_no_approval() -> None:
    text = doc("requirements.md")
    criteria = text[text.index("## 8. Success criteria") :]
    lines = criteria.split("\n4.")[0], criteria.split("\n6.")[1]
    assert "3. Dropped for the POC (2026-11-02" in criteria
    assert "Dropped for the POC (2026-11-02" in lines[1]
    five = criteria[criteria.index("\n5.") : criteria.index("\n6.")]
    assert "read the\n   evidence and the AI recommendation." in five
    assert "Approve or assign was dropped" in five


def test_ac3_specs_06_and_07_mark_the_dropped_parts() -> None:
    api = doc("specs/06-api.md")
    assert "**POC scope (2026-11-02" in api
    for path in ("/customers", "/explore/*", "/assistant/chat", "/backtest/*", "/actions"):
        assert path in api.split("**POC scope")[1].split("\n\n")[0], path
    frontend = doc("specs/07-frontend.md")
    note = frontend.split("**POC scope (2026-11-02")[1].split("\n\n")[0]
    for screen in ("Customer 360", "Explore", "Assistant", "Proof", "Approve"):
        assert screen in note, screen


def test_ac4_process_records_the_faster_loop() -> None:
    text = doc("process.md")
    section = text[text.index("## Faster loop for the POC deadline") :]
    section = section[: section.index("## Real-file checks")]
    assert "uv run revint-gate` once a day" in section
    assert "provisional" in section
    assert "never merge" in section
