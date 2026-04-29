"""Command-line entry point for `dbos-argus`.

Settings are loaded at module import time, so any env vars we want the running
app to see have to be in `os.environ` *before* uvicorn imports `dbos_argus.main`.
We pass the app as an import string for that reason.
"""

import os

import click
import uvicorn

from . import __version__


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="dbos-argus")
@click.option(
    "--db-url",
    envvar="ARGUS_DATABASE_URL",
    help=(
        "Postgres URL of the DBOS app's database "
        "(e.g. postgresql+asyncpg://user:pass@host:5432/db). "
        "Also reads ARGUS_DATABASE_URL."
    ),
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Interface to bind. Use 0.0.0.0 to expose on all interfaces.",
)
@click.option(
    "--port",
    default=8090,
    show_default=True,
    type=int,
    help="Port to bind.",
)
@click.option(
    "--log-level",
    default="info",
    show_default=True,
    type=click.Choice(["critical", "error", "warning", "info", "debug", "trace"]),
)
@click.option(
    "--cors-origins",
    envvar="ARGUS_CORS_ORIGINS",
    help="Comma-separated allowed CORS origins. Also reads ARGUS_CORS_ORIGINS.",
)
def main(
    db_url: str | None,
    host: str,
    port: int,
    log_level: str,
    cors_origins: str | None,
) -> None:
    """Run the dbos-argus management console (FastAPI + bundled SPA)."""
    if db_url:
        os.environ["ARGUS_DATABASE_URL"] = db_url
    if cors_origins:
        os.environ["ARGUS_CORS_ORIGINS"] = cors_origins
    os.environ["ARGUS_LOG_LEVEL"] = log_level.upper()

    uvicorn.run(
        "dbos_argus.main:app",
        host=host,
        port=port,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
