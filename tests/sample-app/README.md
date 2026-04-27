# sample-app

Standalone DBOS Transact app used as a dev fixture for Argus. It ships **two** processes that talk to the same Postgres but run under **different DBOS executor IDs**, so DBOS recovery never crosses between them:

- `argus-runner` (executor_id `argus-runner`) — long-running. Hosts the example workflows and stays idle so recv-blocking workflows remain awaitable.
- `argus-ops` (executor_id `argus-ops`) — short-lived CLI. Sends notifications, cancels, resumes, and lists workflows. Cross-executor send/cancel/resume are plain DB ops, so they reach the runner's workflows just fine.

## Setup

This package is a uv workspace member, so a single root sync wires everything up:

```bash
uv sync                        # from the repo root
```

That installs both `argus-runner` and `argus-ops` into the root `.venv/bin`.

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

## Environment

Variables can be set in the shell or in a `tests/sample-app/.env` file (loaded automatically — see `.env.example`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DBOS_SYSTEM_DATABASE_URL` | `postgresql://argus:argus@localhost:5432/argus` | Postgres DBOS Transact writes its workflow tables to. Both processes read it. |
| `DBOS_CONDUCTOR_KEY` | unset | If set, both processes connect to DBOS Conductor. **Note:** when this is set, DBOS overrides the literal `argus-runner` / `argus-ops` executor IDs with generated UUIDs at launch — isolation between the two processes still holds (different UUIDs), but the literal IDs won't appear in the DB. |
