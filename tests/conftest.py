"""Shared pytest setup.

- Skip `realdata` tests when the data/ folder is absent.
- Fail the run if a test wrote into the repository (code, SQL, config, docs or tests). Tests run
  in parallel, each in its own temporary folder; a write into the tree could break another
  worker, and the committed files must not change as a side effect of testing (story #65).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from repo_snapshot import differences, snapshot

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
_SNAPSHOT: dict[str, tuple[int, int]] = {}


def _is_controller(config: pytest.Config) -> bool:
    """True in the main process; xdist workers have `workerinput` and are skipped."""
    return not hasattr(config, "workerinput")


def pytest_sessionstart(session: pytest.Session) -> None:
    if _is_controller(session.config):
        _SNAPSHOT.update(snapshot(ROOT))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _is_controller(session.config) or not _SNAPSHOT:
        return
    changed = differences(_SNAPSHOT, snapshot(ROOT))
    if not changed:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line("")
        reporter.write_line("ERROR: the test run changed files in the repository:", red=True)
        for line in changed[:20]:
            reporter.write_line(f"  {line}", red=True)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if DATA_DIR.is_dir():
        return
    skip = pytest.mark.skip(reason="data/ not present; realdata tests need the client data")
    for item in items:
        if "realdata" in item.keywords:
            item.add_marker(skip)
