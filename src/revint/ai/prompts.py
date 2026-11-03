"""The versioned prompts (spec 05 section 6, story #137).

The files are src/revint/ai/prompts/<name>.v<N>.md: a system prompt and one per engine. The
newest version of each name is used. `prompt_version` is the two file stems and a hash of their
text, so any change to a prompt gives a new version (and a new cache key); a changed prompt
must be a new version file, never an edit of an old one.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_FILE = re.compile(r"^(?P<name>[a-z]+)\.v(?P<version>\d+)\.md$")


@dataclass(frozen=True)
class Prompt:
    system: str
    task: str
    version: str


def _latest(name: str) -> Path:
    found = [
        (int(m["version"]), p)
        for p in PROMPTS_DIR.iterdir()
        if (m := _FILE.match(p.name)) and m["name"] == name
    ]
    if not found:
        raise FileNotFoundError(f"no prompt file for {name} in {PROMPTS_DIR}")
    return max(found)[1]


def prompt_for(opportunity_type: str) -> Prompt:
    system_file, task_file = _latest("system"), _latest(opportunity_type)
    system = system_file.read_text(encoding="utf-8")
    task = task_file.read_text(encoding="utf-8")
    digest = hashlib.sha256((system + "\n---\n" + task).encode("utf-8")).hexdigest()[:12]
    stems = f"{system_file.name.removesuffix('.md')}+{task_file.name.removesuffix('.md')}"
    return Prompt(system=system, task=task, version=f"{stems}@{digest}")
