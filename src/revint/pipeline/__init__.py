"""Pipeline runner: numbered SQL files, one DuckDB transaction per stage."""

from revint.pipeline.runner import (
    EXIT_STAGE_FAILED,
    EXIT_WAREHOUSE_LOCKED,
    PipelineError,
    StageError,
    StageResult,
    WarehouseLockedError,
    execute_stage,
    flatten_parameters,
    run_stage,
    settings_parameters,
)

__all__ = [
    "EXIT_STAGE_FAILED",
    "EXIT_WAREHOUSE_LOCKED",
    "PipelineError",
    "StageError",
    "StageResult",
    "WarehouseLockedError",
    "execute_stage",
    "flatten_parameters",
    "run_stage",
    "settings_parameters",
]
