# Contributing to Argus

Thanks for your interest in the project. Argus is pre-alpha — everything moves fast and breaks fast. If you're planning anything non-trivial, file an issue or start a Discussion first so we can coordinate.

## Development setup

You need:

- Node.js 20 or newer
- pnpm 9 or newer (`npm i -g pnpm`)
- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker + Docker Compose (for the full dev stack)

Clone and install:

```bash
git clone https://github.com/tmarkovski/dbos-argus.git
cd dbos-argus
pnpm install
uv sync
```

Bring up the full dev stack (Postgres + server + console):

```bash
docker compose up
```

- Console: http://localhost:5173
- Server healthz: http://localhost:8090/healthz
- Postgres: localhost:5432 (user `argus`, password `argus`, db `argus`)

## Workspace layout

- `apps/console` — SvelteKit web UI
- `packages/server` — FastAPI backend (`dbos-argus` on PyPI)
- `packages/ui` — reusable Svelte 5 components (`@dbos-argus/ui`)
- `packages/client-ts` — TypeScript WS client (`@dbos-argus/client`)
- `examples/` — runnable DBOS apps that connect to Argus

## Common commands

```bash
pnpm run lint     # turbo run lint across all packages
pnpm run test     # turbo run test across all packages
pnpm run build    # turbo run build (console + libs)
pnpm run dev      # turbo run dev (all dev servers)
```

Python-only commands run through `uv`:

```bash
uv run ruff check packages/server
uv run pytest packages/server
uv run alembic -c packages/server/alembic.ini upgrade head
```

## Regenerating the WS protocol types

The WebSocket message schema lives in `packages/server/dbos_argus/protocol.py`. After editing it, regenerate the matching TypeScript types:

```bash
pnpm run gen:protocol
```

The generated file (`packages/client-ts/src/protocol.ts`) is checked in.

## Code style

- Python: `ruff` for both format and lint. Run `uv run ruff format` before pushing.
- TypeScript / Svelte: `prettier` + the SvelteKit project config. Run `pnpm run lint`.
- Commit messages: imperative mood ("add", "fix", "refactor"), scoped where helpful (`server:`, `console:`, `ui:`).

## Principles

1. Argus is out-of-band. No code path in this repo may require direct access to a DBOS app's database.
2. The console is a client. It talks only to the Argus backend, never to DBOS apps directly.
3. Typed contracts. The Pydantic models in `protocol.py` are the single source of truth.
4. Boring is good. Prefer standard, well-documented libraries.

See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) for community expectations.
