"""Generate the TypeScript mirror of the WS protocol from Pydantic models.

Run from the repo root:

    pnpm run gen:protocol

Writes packages/client-ts/src/protocol.ts. The generated file is checked in so
consumers do not need a Python toolchain to use the TS client.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "packages" / "client-ts" / "src" / "protocol.ts"


def main() -> None:
    try:
        from pydantic2ts import generate_typescript_defs
    except ImportError:
        print(
            "pydantic-to-typescript is not installed. Install dev deps with `uv sync`.",
            file=sys.stderr,
        )
        sys.exit(1)

    # pydantic2ts shells out to `json2ts` (json-schema-to-typescript). Ensure it's present.
    if subprocess.run(["npx", "--no-install", "json2ts", "--version"]).returncode != 0:
        print(
            "`json2ts` not found. Install with `pnpm add -Dw json-schema-to-typescript`.",
            file=sys.stderr,
        )
        sys.exit(1)

    generate_typescript_defs(
        "dbos_argus.protocol",
        str(TARGET),
        exclude=(),
        json2ts_cmd="npx json2ts",
    )
    print(f"wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
