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


class RawFileInUseError(RawAccessError):
    """A raw file is locked by another process, for example open in Excel."""


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
    try:
        handle = target.open("rb")
    except PermissionError as exc:
        logger.warning("refused 1 raw file: locked by another process or not readable")
        raise RawFileInUseError(
            f"raw file {target.name} is locked by another process or not readable; "
            "close it (for example in Excel) and run the build again"
        ) from exc
    logger.info("opened 1 raw file read-only (%d bytes)", target.stat().st_size)
    return handle
