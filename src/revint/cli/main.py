"""The `revint` command line (spec 10 section 5).

Every command loads and validates the settings first. A command whose epic has not been
built yet is a stub: it exits with code 3 and a "not implemented" message without doing any
work. Later epics replace the stubs one by one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from revint import config

EXIT_CONFIG_ERROR = 1
EXIT_NOT_IMPLEMENTED = 3

app = typer.Typer(
    name="revint",
    help="Revenue intelligence POC: build the data layers, run engines, serve the API.",
    no_args_is_help=True,
    add_completion=False,
)
build_app = typer.Typer(help="Build data layers.", no_args_is_help=True)
report_app = typer.Typer(help="Write reports.", no_args_is_help=True)
opportunities_app = typer.Typer(help="Opportunity engines.", no_args_is_help=True)
backtest_app = typer.Typer(help="As-of replay backtest.", no_args_is_help=True)
ai_app = typer.Typer(help="AI briefs.", no_args_is_help=True)
app_state_app = typer.Typer(help="App state database.", no_args_is_help=True)

app.add_typer(build_app, name="build")
app.add_typer(report_app, name="report")
app.add_typer(opportunities_app, name="opportunities")
app.add_typer(backtest_app, name="backtest")
app.add_typer(ai_app, name="ai")
app.add_typer(app_state_app, name="app")


def _fail(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _load_settings() -> config.Settings:
    """Load the settings once per invocation; invalid settings end the command."""
    try:
        return config.load_settings(config.DEFAULT_SETTINGS_FILE)
    except config.ConfigError as exc:
        _fail(f"revint: {exc}", EXIT_CONFIG_ERROR)


def _stub(command: str) -> NoReturn:
    """Validate the settings once, then report that the command is a stub."""
    _load_settings()
    _fail(f"revint {command}: not implemented yet", EXIT_NOT_IMPLEMENTED)


@build_app.command("bronze")
def build_bronze() -> None:
    """Build bronze Parquet from the raw workbook."""
    settings = _load_settings()
    from revint.build import execute_bronze_stage  # imported here to keep --help fast

    code = execute_bronze_stage(settings)
    if code:
        raise typer.Exit(code=code)


@build_app.command("silver")
def build_silver() -> None:
    """Build the silver layer from the bronze files."""
    settings = _load_settings()
    from revint.silver import execute_silver  # imported here to keep --help fast

    code = execute_silver(settings)
    if code:
        raise typer.Exit(code=code)


@build_app.command("gold")
def build_gold() -> None:
    """Build the gold layer (the star schema and marts) from silver."""
    settings = _load_settings()
    from revint.build import execute_gold  # imported here to keep --help fast

    code = execute_gold(settings)
    if code:
        raise typer.Exit(code=code)


@build_app.command("all")
def build_all() -> None:
    """Build every layer: bronze, then silver, then gold."""
    settings = _load_settings()
    from revint.build import execute_build_all  # imported here to keep --help fast

    code = execute_build_all(settings)
    if code:
        raise typer.Exit(code=code)


@app.command("check")
def check() -> None:
    """Run SQL checks and reconciliation (R1 to R4); exit 7 if a check fails."""
    settings = _load_settings()
    from revint.recon import execute_recon  # imported here to keep --help fast

    code = execute_recon(settings)
    if code:
        raise typer.Exit(code=code)


@report_app.command("dq")
def report_dq() -> None:
    """Write the data quality report to reports/data_quality.md."""
    settings = _load_settings()
    from revint.report import execute_report  # imported here to keep --help fast

    code = execute_report(settings)
    if code:
        raise typer.Exit(code=code)


@report_app.command("dictionary")
def report_dictionary(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Where to write it; default docs/data_dictionary.md."),
    ] = None,
) -> None:
    """Write the data dictionary of the gold layer (docs/data_dictionary.md)."""
    settings = _load_settings()
    from revint.data_dictionary import execute_dictionary  # imported here to keep --help fast

    code = execute_dictionary(settings, output)
    if code:
        raise typer.Exit(code=code)


@opportunities_app.command("build")
def opportunities_build(
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="As-of date (YYYY-MM-DD); default from settings.")
    ] = None,
) -> None:
    """Build the opportunity tables for the as-of date (asof.date, or --as-of for this run)."""
    settings = _load_settings()
    from datetime import date

    from revint.opportunities import execute_opportunities, with_asof  # keeps --help fast

    if as_of is not None:
        try:
            settings = with_asof(settings, date.fromisoformat(as_of))
        except ValueError:
            _fail(
                f"revint opportunities build: --as-of must be a date as YYYY-MM-DD, not {as_of!r}",
                EXIT_CONFIG_ERROR,
            )
    code = execute_opportunities(settings)
    if code:
        raise typer.Exit(code=code)


@backtest_app.command("run")
def backtest_run() -> None:
    """Run the as-of replay backtest."""
    _stub("backtest run")


@backtest_app.command("report")
def backtest_report() -> None:
    """Write the backtest report."""
    _stub("backtest report")


@ai_app.command("generate")
def ai_generate(
    opp: Annotated[str | None, typer.Option("--opp", help="One opportunity id.")] = None,
    top: Annotated[
        int | None, typer.Option("--top", min=1, help="The n best-ranked opportunities.")
    ] = None,
) -> None:
    """Generate AI briefs (default: the ai.precompute_top_n best-ranked); prints counts only."""
    settings = _load_settings()
    if opp is not None and top is not None:
        _fail("revint ai generate: use --opp or --top, not both", EXIT_CONFIG_ERROR)
    from revint.ai.briefs import execute_generate  # imported here to keep --help fast

    code = execute_generate(settings, opp, top)
    if code:
        raise typer.Exit(code=code)


@app_state_app.command("init")
def app_init() -> None:
    """Create the app state database (data/app.duckdb) and its tables."""
    settings = _load_settings()
    from revint.ai import store  # imported here to keep --help fast

    try:
        store.init(settings)
    except store.StoreError as exc:
        _fail(f"app init failed: {exc}", 4)
    typer.echo(f"app init: {settings.paths.app_db} ready")


@app.command("serve")
def serve() -> None:
    """Start the API on api.host and api.port (localhost by default)."""
    settings = _load_settings()
    import uvicorn  # imported here to keep --help fast

    from revint.api.app import create_app

    typer.echo(f"serving the API on http://{settings.api.host}:{settings.api.port}/api/v1")
    uvicorn.run(create_app(settings), host=settings.api.host, port=settings.api.port)
