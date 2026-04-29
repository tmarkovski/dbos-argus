"""Bootstrap a DBOS Postgres schema.

Run a minimal `DBOS()` lifecycle against the target database so DBOS applies
its current Postgres migrations, then exit cleanly. This leaves the `dbos.*`
schema in the state DBOS would create for a fresh install of the installed
version.

Usage:
    python scripts/dbos_schema_bootstrap.py <database_url>

Where <database_url> is a libpq-style URL (e.g. postgres://user:pass@host/db).
"""

from __future__ import annotations

import sys

from dbos import DBOS, DBOSConfig


def main(database_url: str) -> None:
    config = DBOSConfig(name="argus-schema-watch", system_database_url=database_url)
    dbos = DBOS(config=config)
    DBOS.launch()
    DBOS.destroy()
    # silence unused-name
    del dbos


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write("usage: dbos_schema_bootstrap.py <database_url>\n")
        sys.exit(2)
    main(sys.argv[1])
