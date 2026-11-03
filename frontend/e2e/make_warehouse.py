"""Build the synthetic warehouse the Playwright walkthrough reads (story #136).

`uv run python frontend/e2e/make_warehouse.py <folder>` builds silver, gold and the
opportunity tables from the acceptance fixture of story #115 (one customer per engine, synthetic
data only) into <folder>/warehouse.duckdb, so the API serves it without touching data/.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "unit"))

from gold_helpers import variant  # noqa: E402
from silver_helpers import build  # noqa: E402
from test_opportunity_acceptance import SECTIONS, rows  # noqa: E402

from revint.config import load_settings  # noqa: E402
from revint.gold import run_gold  # noqa: E402
from revint.opportunities import run_opportunities  # noqa: E402


def main(folder: str) -> int:
    root = Path(folder).resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, rows())
    run_gold(settings)
    run_opportunities(variant(root, settings, **SECTIONS))
    print(root / "warehouse.duckdb")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
