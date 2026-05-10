# sample-app

Standalone DBOS Transact app used as a dev fixture for Argus. It runs as a continuous **simulation** of a small e-commerce / SaaS platform: workflows are enqueued on a steady cadence, and short-lived worker subprocesses spin up periodically to drain each queue. Net result: there's always activity in the dashboard, but the backlog never grows without bound.

## Processes

| Process | Role | Lifetime |
| --- | --- | --- |
| `argus-simulator` | The demo's orchestrator. Enqueues workflows on per-use-case schedules **and** spawns `argus-runner` subprocesses that drain specific queues. | Long-running |
| `argus-runner` | Generic queue worker. `--queue <name> --duration <sec>` subscribes to one queue, drains for N seconds, exits. | Short-lived (spawned by simulator) |
| `argus-scheduler` | Owns the cron tick loop. Each tick enqueues a `heartbeat_check` workflow onto the `heartbeats` queue. | Long-running |
| `argus-heartbeat-runner` | Worker for the `heartbeats` queue. | Long-running |
| `argus-ops` | Short-lived CLI: `send`, `cancel`, `resume`, `list`. | One-shot |

Every process picks its own `executor_id` so DBOS recovery never crosses between them. All instances of a queue worker share an executor_id (e.g. `orders-worker`) so a fresh worker recovers PENDING work abandoned by its predecessor.

## Setup

This package is a `uv` workspace member, so a single root sync wires everything up:

```bash
uv sync                        # from the repo root
```

That installs `argus-simulator`, `argus-runner`, `argus-ops`, `argus-scheduler`, and `argus-heartbeat-runner` into the root `.venv/bin`.

## Running the demo

One command from the repo root brings up the Argus dev server and all sample-app processes against a local SQLite file (no Docker, no Postgres):

```bash
pnpm demo
```

That sets `ARGUS_DATABASE_URL` and `DBOS_SYSTEM_DATABASE_URL` to the same `argus-demo.sqlite` file at the repo root, then `turbo run dev demo` fans out:

- `dev` on `@dbos-argus/server` and `console` (FastAPI + SvelteKit dev server)
- `demo` on `@dbos-argus/sample-app` (simulator + scheduler + heartbeat-runner)

Ctrl+C tears everything down together.

If you'd rather run the sample-app processes manually (e.g. against Postgres), each one has its own console script:

```bash
uv run argus-simulator        # drives all activity
uv run argus-scheduler        # owns the heartbeat cron tick
uv run argus-heartbeat-runner # drains the heartbeats queue
```

Open the Argus dashboard. You'll see:

- A steady stream of one-row `heartbeat_check` workflows every minute.
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
| `run_billing_cycle(account_id)` | `billing` | Sub-workflow `charge_card` enqueued onto `payments`. On failure: dunning state, recv waiting for retry, then second charge attempt or `mark_delinquent`. |
| `send_campaign(campaign_id)` | `emails` | Fan-out: enqueues 5–15 `deliver_message` children onto `emails` (concurrency=20), waits for all results. |
| `process_return(order_id)` | `returns` | recv with timeout for ops approval; auto-decides 50/50 on timeout. Sub-workflows `issue_refund` (via `payments`) + `restock_items`. |
| `generate_daily_report(date)` | `reports` | Long single-step job. `reports` queue has `worker_concurrency=1`, so multiple enqueues serialize visibly. |
| `heartbeat_check` | `heartbeats` | One-step cron tick, drained continuously. |

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
| `heartbeats` | 50 | continuous (`argus-heartbeat-runner`) | continuous |

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
```

The simulator spawns `argus-runner --queue ... --duration ...` automatically. Run it manually for ad-hoc draining or to recover prior work under a specific worker executor_id.

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

Long-running process that idles and ticks the heartbeat schedule defined in `scheduled.py` (`* * * * *` by default). The schedule row in `dbos.workflow_schedules` is persisted across restarts; this process just owns the in-memory tick loop. Stop it and ticks stop; start it again and they resume.

```bash
uv run argus-scheduler
```

The schedule is registered with `queue_name="heartbeats"`, so each tick enqueues rather than runs locally. Execution belongs to `argus-heartbeat-runner`.

## `argus-heartbeat-runner`

```bash
uv run argus-heartbeat-runner
```

Run zero, one, or many. With zero, you can watch heartbeats accumulate in `ENQUEUED`; with one or more, DBOS distributes the work.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `DBOS_SYSTEM_DATABASE_URL` | `postgresql://argus:argus@localhost:5432/argus` | Postgres DBOS Transact writes its workflow tables to. All processes read it. |

Variables can be set in the shell or in a `tests/sample-app/.env` file (loaded automatically — see `.env.example`).
