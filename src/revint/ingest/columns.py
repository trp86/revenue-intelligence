"""Final column names for a sheet header (spec 01 B3, decided on issue #31).

Rule, applied in this order:
1. Trim whitespace at both ends of the source name.
2. Replace each remaining space with an underscore. Other characters are kept.
3. Names that are equal ignoring case (which includes exact repeats) get `_1`, `_2`, ...
   in source order, each keeping its own capitalisation. DuckDB treats column names
   case-insensitively, so names that differ only by case would otherwise collide.

Names that are unique ignoring case stay unsuffixed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence


def normalise_name(raw: str) -> str:
    """Steps 1 and 2: trim the ends, then each inner space becomes an underscore."""
    return raw.strip().replace(" ", "_")


def final_column_names(raw_names: Sequence[str]) -> list[str]:
    """The final name for every header cell, in source order (step 3 applied).

    Raises `ValueError` for an empty header cell, naming its 1-based position.
    """
    normalised = []
    for position, raw in enumerate(raw_names, start=1):
        name = normalise_name(raw)
        if not name:
            raise ValueError(f"empty column name at column {position}")
        normalised.append(name)

    total = Counter(name.casefold() for name in normalised)
    taken = {name.casefold() for name in normalised if total[name.casefold()] == 1}
    seen: Counter[str] = Counter()
    result: list[str] = []
    for name in normalised:
        key = name.casefold()
        if total[key] == 1:
            result.append(name)
            continue
        seen[key] += 1
        suffix = seen[key]
        candidate = f"{name}_{suffix}"
        while candidate.casefold() in taken:  # never collide with an existing name
            suffix += 1
            candidate = f"{name}_{suffix}"
        taken.add(candidate.casefold())
        result.append(candidate)
    return result
