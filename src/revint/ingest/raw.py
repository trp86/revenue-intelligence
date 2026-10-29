"""The only way to open files under data/raw: read-only (CLAUDE.md rule 7).

The helper takes no mode argument, always opens binary read-only, and refuses
paths outside the raw folder. It logs sizes and counts, never file contents.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO

from revint import config

logger = logging.getLogger(__name__)


class RawAccessError(Exception):
    """A raw-file access was refused."""


def open_raw(path: Path, raw_dir: Path | None = None) -> BinaryIO:
    """Open a file under `raw_dir` (default `paths.raw` from settings) read-only.

    Relative paths resolve against `raw_dir`. A write to the returned handle
    raises `io.UnsupportedOperation`.
    """
    root = (raw_dir if raw_dir is not None else config.load_settings().paths.raw).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        logger.warning("refused 1 raw file outside the raw folder")
        raise RawAccessError(f"path is outside the raw folder: {path}")
    if not target.exists():
        raise FileNotFoundError(f"raw file not found: {target}")
    if not target.is_file():
        raise RawAccessError(f"not a file: {target}")
    handle = target.open("rb")
    logger.info("opened 1 raw file read-only (%d bytes)", target.stat().st_size)
    return handle
