# sample-app

Standalone DBOS Transact app used as a dev fixture for Argus. It runs as a continuous **simulation** of a small e-commerce / SaaS platform: workflows are enqueued on a steady cadence, and short-lived worker subprocesses spin up periodically to drain each queue. Net result: there's always activity in the dashboard, but the backlog never grows without bound.

## Processes

| Process | Role | Lifetime |
| --- | --- | --- |
| `argus-simulator` | The demo's orchestrator. Enqueues workflows on per-use-case schedules **and** spawns `argus-runner` subprocesses that drain specific queues. | Long-running |
| `argus-runner` | Generic queue worker. `--queue <name> --duration <sec>` subscribes to one queue, drains for N seconds, exits. | Short-lived (spawned by simulator) |
| `argus-scheduler` | Owns the cron tick loop. Each tick enqueues a scheduled workflow (metrics rollup, cart sweep, inventory reconcile) onto the `metrics` queue. | Long-running |
| `argus-metrics-runner` | Worker for the `metrics` queue. | Long-running |
| `argus-ops` | Short-lived CLI: `send`, `cancel`, `resume`, `list`. | One-shot |

Every process picks its own `executor_id` so DBOS recovery never crosses between them. All instances of a queue worker share an executor_id (e.g. `orders-worker`) so a fresh worker recovers PENDING work abandoned by its predecessor.

## Setup

This package is a `uv` workspace member, so a single root sync wires everything up:

```bash
uv sync                        # from the repo root
```

That installs `argus-simulator`, `argus-runner`, `argus-ops`, `argus-scheduler`, and `argus-metrics-runner` into the root `.venv/bin`.

## Running the demo

One command from the repo root brings up the Argus dev server and all sample-app processes against a local SQLite file (no Docker, no Postgres):

```bash
pnpm demo
```

That sets `ARGUS_DATABASE_URL` and `DBOS_SYSTEM_DATABASE_URL` to the same `argus-demo.sqlite` file at the repo root, then `scripts/dev.mjs` brings up:

- the FastAPI backend (uvicorn on :8090) and the SvelteKit dev server (:5000)
- the sample-app workload via `scripts/demo-app.mjs` (one-shot `argus-runner prepare`, then simulator + scheduler + metrics-runner)

Ctrl+C tears everything down together.

If you'd rather run the sample-app processes manually (e.g. against Postgres), each one has its own console script:

```bash
uv run argus-runner prepare   # one-shot: run DBOS migrations + queue setup; only needed once
uv run argus-simulator        # drives all activity
uv run argus-scheduler        # owns the platform-ops cron ticks
uv run argus-metrics-runner   # drains the metrics queue
```

`argus-runner prepare` only matters on a fresh database — it serializes schema migration so the three long-running processes don't race CREATE TABLE on first boot. After it has run once, you can skip it.

Open the Argus dashboard. You'll see:

- Three scheduled workflows ticking on the `metrics` queue: `rollup_platform_metrics` and `sweep_abandoned_carts` every 5 minutes, `reconcile_inventory` every 15 minutes.
- Per-use-case queues oscillating between **growing ENQUEUED** (no worker live) and **draining** (worker spawned, dequeueing).
- A mix of `SUCCESS` and `ERROR` rows — each use case has a ~10–40% random failure path.
- Workflows blocking briefly on `recv` then continuing past their timeout.

Use `argus-ops` from a fourth shell to inspect or signal individual workflows (see below).

## Use cases

Six top-level workflows, each with sub-workflows, recv calls, set_event broadcasts, and at least one failure branch:

| Workflow | Queue | Demonstrates |
| --- | --- | --- |
| `onboard_user(email)` | `onboarding` | recv with timeout (email-verify click), sub-workflow `provision_account`, branch on timeout to `cleanup_unverified`. |
| `fulfill_order(order_id)` | `orders` | Multi-stage pipeline. `authorize_payment` is enqueued onto the rate-limited `payments` queue. recv with timeout for delivery confirmation. |
| `run_billing_cycle(account_id)` | `billing` | Sub-workflow `charge_card` started via `DBOS.start_workflow` (child on the parent's executor, no queue) and awaited with `handle.get_result()`. On failure: dunning state, recv waiting for retry, then second charge attempt or `mark_delinquent`. |
| `send_campaign(campaign_id)` | `emails` | Fan-out: enqueues 5–15 `deliver_message` children onto `emails` (concurrency=20), waits for all results. |
| `process_return(order_id)` | `returns` | recv with timeout for ops approval; auto-decides 50/50 on timeout. Sub-workflows `issue_refund` (via `payments`) + `restock_items`. |
| `generate_daily_report(date)` | `reports` | Long single-step job. `reports` queue has `worker_concurrency=1`, so multiple enqueues serialize visibly. |
| `rollup_platform_metrics` | `metrics` | Cron-driven (5m). Snapshots fake platform KPIs. |
| `sweep_abandoned_carts` | `metrics` | Cron-driven (5m). Finds stale carts and enqueues recovery `send_campaign` workflows onto the `emails` queue. |
| `reconcile_inventory` | `metrics` | Cron-driven (15m). Longer single-step job to diff inventory against the warehouse. |

## Queue topology

| Queue | Worker concurrency | Worker spawn cadence | Worker lifetime |
| --- | ---: | --- | --- |
| `onboarding` | 5 | every 4 min | 45 s |
| `orders` | 10 | every 3 min | 60 s |
| `billing` | 5 | every 5 min | 30 s |
| `emails` | 20 | every 2 min | 90 s |
| `payments` | 2 | every 6 min | 30 s |
| `returns` | 5 | every 7 min | 45 s |
| `reports` | 1 | every 10 min | 60 s |
| `metrics` | 50 | continuous (`argus-metrics-runner`) | continuous |

The simulator's enqueue cadences (45–300 s per use case, jittered) are tuned so total drain rate (worker spawn × duration × concurrency) stays comfortably above total enqueue rate. Tweak `WORKER_PROFILES` and `interval_sec` in `simulator.py` to change the demo balance.

## `argus-simulator`

```bash
argus-simulator             # run the continuous demo
argus-simulator --once      # enqueue one of each use case and exit
```

## `argus-runner`

```bash
argus-runner --queue orders --duration 60       # drain the orders queue for 60 s
argus-runner idle                               # launch DBOS, register workflows, idle (recovery only)
argus-runner prepare                            # one-shot: migrate schema + register queues, then exit
```

The simulator spawns `argus-runner --queue ... --duration ...` automatically. Run it manually for ad-hoc draining or to recover prior work under a specific worker executor_id. Use `prepare` once on a fresh database before launching multiple long-running processes in parallel.

## `argus-ops`

```bash
argus-ops list [--limit N] [--status S] [--executor E]   # list recent workflows
argus-ops send WF_ID [--topic T] [--message JSON]        # generic DBOS.send
argus-ops cancel WF_ID                                   # cancel a workflow
argus-ops resume WF_ID                                   # resume a cancelled / pending workflow
```

Topics the demo workflows wait on (each with a 60–120 s timeout — ops messaging is optional):

| Workflow | Topic | Payload |
| --- | --- | --- |
| `onboard_user` | `email-verify` | any non-null (e.g. `{"clicked": true}`) |
| `fulfill_order` | `delivery-confirmation` | `{"tracking": "TRK-…"}` |
| `run_billing_cycle` | `payment-retry` | any non-null (e.g. `{"retried": true}`) |
| `process_return` | `return-approval` | `{"approved": true}` or `{"approved": false}` |

Example:

```bash
argus-ops list --status PENDING
argus-ops send <onboard-wf-id> --topic email-verify --message '{"clicked": true}'
```

## `argus-scheduler`

Long-running process that idles and ticks the platform-ops schedules defined in `scheduled.py`:

| Schedule                  | Cron             | Workflow                  |
| ------------------------- | ---------------- | ------------------------- |
| `rollup-platform-metrics` | `*/5 * * * *`    | `rollup_platform_metrics` |
| `sweep-abandoned-carts`   | `*/5 * * * *`    | `sweep_abandoned_carts`   |
| `reconcile-inventory`     | `*/15 * * * *`   | `reconcile_inventory`     |

The rows in `dbos.workflow_schedules` are persisted across restarts; this process just owns the in-memory tick loop. Stop it and ticks stop; start it again and they resume.

```bash
uv run argus-scheduler
```

Each schedule is registered with `queue_name="metrics"`, so a tick enqueues rather than runs locally. Execution belongs to `argus-metrics-runner`.

## `argus-metrics-runner`

```bash
uv run argus-metrics-runner
```

Run zero, one, or many. With zero, you can watch scheduled workflows accumulate in `ENQUEUED`; with one or more, DBOS distributes the work.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `DBOS_SYSTEM_DATABASE_URL` | `postgresql://argus:argus@localhost:5432/argus` | Postgres DBOS Transact writes its workflow tables to. All processes read it. |

Variables can be set in the shell or in a `tests/sample-app/.env` file (loaded automatically — see `.env.example`).
