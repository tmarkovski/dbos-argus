# sample-app

Standalone DBOS Transact app used as a dev fixture for Argus. It ships **four** processes that talk to the same Postgres but run under **different DBOS executor IDs**, so DBOS recovery never crosses between them:

- `argus-runner` (executor_id `argus-runner`) — long-running. Hosts the example workflows and stays idle so recv-blocking workflows remain awaitable.
- `argus-ops` (executor_id `argus-ops`) — short-lived CLI. Sends notifications, cancels, resumes, and lists workflows. Cross-executor send/cancel/resume are plain DB ops, so they reach the runner's workflows just fine.
- `argus-scheduler` (executor_id `argus-scheduler`) — long-running. Owns the cron tick loop. Each tick **enqueues** a `heartbeat_check` workflow onto the `argus-heartbeats` queue rather than running it locally.
- `argus-heartbeat-runner` (executor_id `argus-heartbeat-runner`) — long-running. Subscribes as a worker for the `argus-heartbeats` queue and executes the workflow body. Stop it and heartbeats pile up in `ENQUEUED`; start it and DBOS drains them.

## Setup

This package is a uv workspace member, so a single root sync wires everything up:

```bash
uv sync                        # from the repo root
```

That installs `argus-runner`, `argus-ops`, `argus-scheduler`, and `argus-heartbeat-runner` into the root `.venv/bin`.

## Demo flow

In one shell, seed the demo workflow tree and idle:

```bash
uv run argus-runner            # same as `argus-runner seed`
```

It prints the generated `fulfill_order` id and the derived child ids, e.g.:

```
started fulfill_order: fulfill-d76077a9
  carrier child:    fulfill-d76077a9-carrier
  reconcile child:  fulfill-d76077a9-reconcile
  stock grandchild: fulfill-d76077a9-reconcile-stock
```

In another shell, drive the demo:

```bash
uv run argus-ops list --status PENDING
uv run argus-ops carrier-confirm fulfill-d76077a9   # unblocks dispatch_carrier
uv run argus-ops cancel-stock    fulfill-d76077a9   # cancels stock_check mid-sleep
uv run argus-ops ops-signoff     fulfill-d76077a9   # completes fulfill_order
```

## `argus-runner`

| Command | Purpose |
| --- | --- |
| `argus-runner` / `argus-runner seed` | Run process_order + send_campaign synchronously, spawn fulfill_order fire-and-forget, then idle. |
| `argus-runner start-order ORDER_ID` | Run a single `process_order` and idle. |
| `argus-runner start-campaign NAME [-n N]` | Run a single `send_campaign` and idle. |
| `argus-runner start-fulfill ORDER_ID` | Spawn one `fulfill_order` fire-and-forget and idle. |
| `argus-runner idle` | Launch DBOS without seeding — useful to recover prior runner workflows. |

## `argus-ops`

| Command | Purpose |
| --- | --- |
| `argus-ops list [--limit N] [--status S] [--executor E]` | List recent workflows. |
| `argus-ops send WF_ID [--topic T] [--message JSON]` | Generic `DBOS.send`. |
| `argus-ops cancel WF_ID` | Cancel a workflow. |
| `argus-ops resume WF_ID` | Resume a cancelled / pending workflow. |
| `argus-ops carrier-confirm FULFILL_ID` | Convenience: send the canonical carrier confirmation to `<FULFILL>-carrier`. |
| `argus-ops ops-signoff FULFILL_ID` | Convenience: post the trailing `ops-signoff` so `fulfill_order` completes. |
| `argus-ops cancel-stock FULFILL_ID` | Convenience: cancel `<FULFILL>-reconcile-stock`. |

## `argus-scheduler`

Long-running process that idles and ticks the heartbeat schedule defined in `scheduled.py` (`* * * * *` by default). The schedule row in `dbos.workflow_schedules` is persisted across restarts; this process just owns the in-memory tick loop. Stop it and ticks stop; start it and they resume.

```bash
uv run argus-scheduler
```

The schedule is registered with `queue_name="argus-heartbeats"`, so each tick writes an `ENQUEUED` workflow row instead of running it locally. The scheduler does **not** subscribe as a worker for that queue — execution happens in `argus-heartbeat-runner`. Run scheduler and heartbeat-runner independently of `argus-runner` so you can restart any of them without disturbing the others.

## `argus-heartbeat-runner`

Long-running queue worker for `argus-heartbeats`. Drains whatever the scheduler has enqueued.

```bash
uv run argus-heartbeat-runner
```

Run zero, one, or many of these. With zero, you can watch heartbeats accumulate in `ENQUEUED` in the dashboard; with one or more, DBOS distributes the work.

## Environment

Variables can be set in the shell or in a `tests/sample-app/.env` file (loaded automatically — see `.env.example`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DBOS_SYSTEM_DATABASE_URL` | `postgresql://argus:argus@localhost:5432/argus` | Postgres DBOS Transact writes its workflow tables to. All three processes read it. |
