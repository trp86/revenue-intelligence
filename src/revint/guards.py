"""Repository guards: no data and no secrets under version control (spec 10 section 8).

Pure functions over file lists and text, so they can be tested against a
temporary repo and run against the real one without touching either.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath

# `NAME=value`, optionally prefixed with `export`; whitespace around `=` allowed.
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$")


def tracked_file_violations(paths: Iterable[str]) -> list[str]:
    """Return tracked paths that must never be committed.

    A path violates the rule if it is under a top-level `data/` folder or is
    a `.env` file (`.env.example` is allowed). Paths use forward slashes, as
    printed by `git ls-files`.
    """
    violations = []
    for path in paths:
        parts = PurePosixPath(path).parts
        if parts and parts[0] == "data":
            violations.append(path)
        elif parts and parts[-1] == ".env":
            violations.append(path)
    return violations


def env_example_violations(text: str) -> list[str]:
    """Return the names of variables in `.env.example` that carry a value.

    Only names are returned, never values, so the result is safe to print.
    Empty values, whitespace and empty quotes (`""`, `''`) count as empty.
    """
    names = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if match is None:
            continue
        value = match.group("value").strip()
        if value not in ("", '""', "''"):
            names.append(match.group("name"))
    return names
