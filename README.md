# Argus

**A self-hosted, open-source management console for DBOS Transact applications.**

Argus is a web dashboard for observing, pausing, resuming, restarting, and auditing durable workflows built with [DBOS Transact](https://github.com/dbos-inc/dbos-transact-py). Your DBOS apps connect to Argus over an outbound WebSocket; Argus never touches your application database.

> **Status:** Pre-alpha. Everything will change. Not production-ready. If you're here early, welcome — the issue tracker and Discussions are the best place to have a say in where this goes.

---

## Why Argus exists

DBOS Transact is a great open-source library for durable execution. Operating it in production — multiple app instances, distributed queues, long-running workflows — benefits from a management plane for observability and intervention.

DBOS Inc. offers exactly that product, [DBOS Conductor](https://www.dbos.dev/blog/introducing-dbos-conductor), and it's a good product. But Conductor is released under a [proprietary license](https://www.dbos.dev/conductor-license) and requires a paid key for commercial or production use.

Argus is for teams and individuals who want a fully open-source, MIT-licensed alternative they can self-host without a license key. It aims for feature parity with the essentials — workflow observability, queue management, manual intervention — and nothing more.

Argus is not affiliated with, endorsed by, or sponsored by DBOS Inc.

## What Argus does (and doesn't)

**Does:**
- Live and historical view of every durable workflow, its steps, inputs, outputs, and status
- Visual step-by-step workflow graphs powered by [Svelte Flow](https://svelteflow.dev)
- Inspect and manage DBOS distributed queues
- Cancel, resume, restart, and fork workflows from the dashboard
- Multi-application registry — one Argus deployment manages many DBOS apps
- Alerts for failed workflows and queue backlogs *(planned)*

**Doesn't:**
- Does not execute your workflows. Argus is strictly out-of-band observability and control.
- Does not read or write your application database.
- Does not replace DBOS Transact. You still install the library in your app the normal way.

## Architecture

```
┌──────────────┐                         ┌────────────────────────┐
│  DBOS app    │───── outbound WS ──────▶│  Argus                 │
│  (Py / TS)   │◀──── commands ──────────│  FastAPI + console SPA │
└──────┬───────┘                         └────────┬───────────────┘
       │                                          │
       ▼                                          ▼
  ┌─────────┐                                ┌──────────┐
  │ app DB  │                                │ Argus DB │
  │  (PG)   │                                │   (PG)   │
  └─────────┘                                └──────────┘
```

The console is built as a static SPA and served by the FastAPI process on the same port — one image, one container, no CORS.

The design mirrors Conductor's out-of-band model: your app initiates the WebSocket connection outward, so Argus never needs inbound network access to your application servers and never sees your application data.

## Quick start

### Run from Docker Hub

One image — FastAPI backend with the SvelteKit console baked in as static assets, served from the same port. Multi-arch: linux/amd64 + linux/arm64.

- [`tmarkovski/dbos-argus`](https://hub.docker.com/r/tmarkovski/dbos-argus)

Fastest path (brings up Postgres + Argus):

```bash
curl -O https://raw.githubusercontent.com/tmarkovski/dbos-argus/main/docker-compose.prod.yml
docker compose -f docker-compose.prod.yml up
```

Then open http://localhost:8090 — that's both the console and the API.

Point at your own Postgres:

```bash
docker run --rm -p 8090:8090 \
  -e ARGUS_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/argus \
  tmarkovski/dbos-argus:edge
```

Tags: `:edge` (every `main` push), `:vX.Y.Z` / `:X.Y` / `:X` (release tags), `:sha-<short>` (per-commit).

Runtime env vars:

| Var | Purpose |
|---|---|
| `ARGUS_DATABASE_URL` | SQLAlchemy async URL to the Argus Postgres |
| `ARGUS_CORS_ORIGINS` | Comma-separated allowed origins (only needed if the console is served from a different host than the API) |

### Connect your DBOS app

*Not yet. Targeting v0.1.0.* When it exists, it will look roughly like:

```python
# Python
from dbos import DBOS
DBOS(argus_url="ws://localhost:8090", argus_api_key=os.environ["ARGUS_API_KEY"])
```

```typescript
// TypeScript
import { connectArgus } from "@dbos-argus/client";
connectArgus({ url: "ws://localhost:8090", apiKey: process.env.ARGUS_API_KEY });
```

## Project layout

This is a pnpm + uv monorepo orchestrated with Turborepo.

| Path | Package | Purpose |
|---|---|---|
| `apps/console` | — | SvelteKit console (the web UI) |
| `packages/server` | `dbos-argus` (PyPI) | FastAPI backend |
| `packages/ui` | `@dbos-argus/ui` (npm) | Reusable Svelte components — workflow graph, status pills, event timeline |
| `packages/client-ts` | `@dbos-argus/client` (npm) | WebSocket client for DBOS TS apps |
| `examples/` | — | Runnable example DBOS apps connected to Argus |

## Contributing

Early contributors very welcome — especially people already running DBOS Transact in production who have opinions on what this console should look like. Before starting work on anything non-trivial, please file an issue or drop by Discussions so we can coordinate.

Principles that will guide code review:

1. **Argus is out-of-band.** Nothing in this repo may require direct access to a DBOS app's database.
2. **The console is a client.** It talks only to the Argus backend, never to DBOS apps directly.
3. **Boring is good.** FastAPI, Postgres, SvelteKit, Svelte Flow. No clever infrastructure until there is a concrete need.
4. **Typed contracts.** Backend ↔ frontend messages have a single source of truth.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup.

## License

[MIT](./LICENSE).

## Disclaimer

Argus is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by DBOS Inc. "DBOS Transact," "DBOS Conductor," and "DBOS Cloud" are products of DBOS Inc.