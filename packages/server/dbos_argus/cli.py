"""Command-line entry point for `dbos-argus`.

Settings are loaded at module import time, so any env vars we want the running
app to see have to be in `os.environ` *before* uvicorn imports `dbos_argus.main`.
We pass the app as an import string for that reason.
"""

import asyncio
import json
import os
import sys

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
@click.option(
    "--dump-schema",
    is_flag=True,
    help=(
        "Connect to --db-url, print the live `dbos` schema as JSON to stdout, "
        "and exit. Use this to regenerate the snapshot at "
        "dbos_argus/data/expected_schema.json against a fresh DBOS DB."
    ),
)
@click.option(
    "--dump-schema-name",
    default="dbos",
    show_default=True,
    help="Schema to dump when --dump-schema is set.",
)
def main(
    db_url: str | None,
    host: str,
    port: int,
    log_level: str,
    cors_origins: str | None,
    dump_schema: bool,
    dump_schema_name: str,
) -> None:
    """Run the dbos-argus management console (FastAPI + bundled SPA)."""
    if db_url:
        os.environ["ARGUS_DATABASE_URL"] = db_url
    if cors_origins:
        os.environ["ARGUS_CORS_ORIGINS"] = cors_origins
    os.environ["ARGUS_LOG_LEVEL"] = log_level.upper()

    if dump_schema:
        _dump_schema_and_exit(dump_schema_name)
        return

    uvicorn.run(
        "dbos_argus.main:app",
        host=host,
        port=port,
        log_level=log_level,
    )


def _dump_schema_and_exit(schema_name: str) -> None:
    # Imported lazily so server-only deps don't load when the CLI just dumps.
    from .db import engine
    from .schema_dump import dump_live_schema, to_json

    async def _run() -> dict[str, object]:
        async with engine.connect() as conn:
            dump = await dump_live_schema(conn, schema=schema_name)
        await engine.dispose()
        return to_json(dump)

    payload = asyncio.run(_run())
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
