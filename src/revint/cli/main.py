"""The `revint` command line (spec 10 section 5).

Every command is a stub for now: it loads and validates the settings, then
exits with code 3 and a "not implemented" message without doing any work.
Later epics replace the stubs one by one.
"""

from __future__ import annotations

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
    from revint.ingest.bronze import execute_bronze  # imported here to keep --help fast

    code = execute_bronze(settings)
    if code:
        raise typer.Exit(code=code)


@build_app.command("silver")
def build_silver() -> None:
    """Build the silver layer."""
    _stub("build silver")


@build_app.command("gold")
def build_gold() -> None:
    """Build the gold layer."""
    _stub("build gold")


@build_app.command("all")
def build_all() -> None:
    """Build every layer, raw to gold."""
    _stub("build all")


@app.command("check")
def check() -> None:
    """Run SQL checks and reconciliation."""
    _stub("check")


@report_app.command("dq")
def report_dq() -> None:
    """Write the data quality report."""
    _stub("report dq")


@opportunities_app.command("build")
def opportunities_build(
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="As-of date (YYYY-MM-DD); default from settings.")
    ] = None,
) -> None:
    """Build the opportunity tables."""
    _stub("opportunities build")


@backtest_app.command("run")
def backtest_run() -> None:
    """Run the as-of replay backtest."""
    _stub("backtest run")


@backtest_app.command("report")
def backtest_report() -> None:
    """Write the backtest report."""
    _stub("backtest report")


@ai_app.command("generate")
def ai_generate() -> None:
    """Generate AI briefs."""
    _stub("ai generate")


@app_state_app.command("init")
def app_init() -> None:
    """Create the app state database."""
    _stub("app init")


@app.command("serve")
def serve() -> None:
    """Start the API."""
    _stub("serve")
