"""Argus dev simulator — the demo's continuous activity engine.

What it does:

1. Periodically enqueues new workflows on each use-case queue, jittered around
   a configured interval. Workflows land in ENQUEUED.
2. Periodically spawns `argus-runner --queue NAME --duration N` subprocesses
   that drain a specific queue and exit. Multiple workers per queue may overlap.
3. Reaps exited subprocesses; SIGTERMs survivors on shutdown.

Cadences are tuned so total drain-rate (worker_concurrency × duration / spawn_period)
exceeds total enqueue-rate, so the backlog doesn't grow without bound. Tweak
the `USE_CASES` and `WORKER_PROFILES` tables below to change the demo balance.

Run:

    argus-simulator                       # the demo
    argus-simulator --once                # enqueue one of each, no workers spawned
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import click
from _dbos_setup import init_dbos
from dbos import DBOS

LOG = logging.getLogger("simulator")
EXECUTOR_ID = "simulator"


@dataclass
class UseCase:
    """One enqueue cadence: every `interval_sec` (jittered ±jitter), enqueue a workflow."""

    name: str
    queue: str
    interval_sec: float
    jitter_sec: float
    enqueue_fn: Callable[[], object]


@dataclass
class WorkerProfile:
    """One worker-spawn cadence — fork a worker every `spawn_period_sec`, runs `duration_sec`."""

    queue: str
    spawn_period_sec: float
    duration_sec: int


WORKER_PROFILES: list[WorkerProfile] = [
    WorkerProfile(queue="onboarding", spawn_period_sec=240, duration_sec=45),
    WorkerProfile(queue="orders", spawn_period_sec=180, duration_sec=60),
    WorkerProfile(queue="billing", spawn_period_sec=300, duration_sec=30),
    WorkerProfile(queue="emails", spawn_period_sec=120, duration_sec=90),
    WorkerProfile(queue="payments", spawn_period_sec=360, duration_sec=30),
    WorkerProfile(queue="returns", spawn_period_sec=420, duration_sec=45),
    WorkerProfile(queue="reports", spawn_period_sec=600, duration_sec=60),
]


def _rand_email() -> str:
    return f"sim+{uuid.uuid4().hex[:8]}@demo.example"


def _rand_order_id() -> str:
    return f"ord-{uuid.uuid4().hex[:8]}"


def _rand_account_id() -> str:
    return f"acct-{random.randint(1000, 9999)}"


def _rand_campaign_id() -> str:
    return f"camp-{uuid.uuid4().hex[:6]}"


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def _build_use_cases() -> list[UseCase]:
    """Build the enqueue plan. Imports workflow refs so DBOS can serialize them."""
    from _dbos_setup import QUEUES
    from workflows import (
        fulfill_order,
        generate_daily_report,
        onboard_user,
        process_return,
        run_billing_cycle,
        send_campaign,
    )

    return [
        UseCase(
            name="onboard_user",
            queue="onboarding",
            interval_sec=60,
            jitter_sec=20,
            enqueue_fn=lambda: QUEUES["onboarding"].enqueue(onboard_user, _rand_email()),
        ),
        UseCase(
            name="fulfill_order",
            queue="orders",
            interval_sec=45,
            jitter_sec=15,
            enqueue_fn=lambda: QUEUES["orders"].enqueue(fulfill_order, _rand_order_id()),
        ),
        UseCase(
            name="run_billing_cycle",
            queue="billing",
            interval_sec=90,
            jitter_sec=30,
            enqueue_fn=lambda: QUEUES["billing"].enqueue(run_billing_cycle, _rand_account_id()),
        ),
        UseCase(
            name="send_campaign",
            queue="emails",
            interval_sec=120,
            jitter_sec=30,
            enqueue_fn=lambda: QUEUES["emails"].enqueue(send_campaign, _rand_campaign_id()),
        ),
        UseCase(
            name="process_return",
            queue="returns",
            interval_sec=180,
            jitter_sec=60,
            enqueue_fn=lambda: QUEUES["returns"].enqueue(process_return, _rand_order_id()),
        ),
        UseCase(
            name="generate_daily_report",
            queue="reports",
            interval_sec=300,
            jitter_sec=60,
            enqueue_fn=lambda: QUEUES["reports"].enqueue(generate_daily_report, _today_iso()),
        ),
    ]


@dataclass
class WorkerHandle:
    queue: str
    process: subprocess.Popen
    started_at: float


@dataclass
class _State:
    stop: bool = False
    workers: list[WorkerHandle] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


def _resolve_runner_cmd() -> list[str]:
    """Find the argus-runner entry point. Falls back to `python -m runner`."""
    runner = shutil.which("argus-runner")
    if runner:
        return [runner]
    return [sys.executable, "-m", "runner"]


def _spawn_worker(state: _State, queue: str, duration_sec: int) -> None:
    cmd = _resolve_runner_cmd() + ["--queue", queue, "--duration", str(duration_sec)]
    proc = subprocess.Popen(cmd, env=os.environ.copy())
    handle = WorkerHandle(queue=queue, process=proc, started_at=time.monotonic())
    with state.lock:
        state.workers.append(handle)
    LOG.info("spawned worker queue=%s pid=%d duration=%ds", queue, proc.pid, duration_sec)


def _reap_workers(state: _State) -> None:
    with state.lock:
        live: list[WorkerHandle] = []
        for w in state.workers:
            ret = w.process.poll()
            if ret is None:
                live.append(w)
            else:
                LOG.info("worker exited queue=%s pid=%d rc=%d", w.queue, w.process.pid, ret)
        state.workers = live


def _enqueue_loop(state: _State, use_case: UseCase) -> None:
    # First fire is jittered by half the interval so all use cases don't fire at t=0.
    time.sleep(random.uniform(0, use_case.interval_sec / 2))
    while not state.stop:
        try:
            handle = use_case.enqueue_fn()
            wf_id = getattr(handle, "workflow_id", "?")
            LOG.info("enqueued %s → %s (%s)", use_case.name, use_case.queue, wf_id)
        except Exception as e:
            LOG.warning("enqueue failed %s: %s", use_case.name, e)
        delay = max(1.0, random.gauss(use_case.interval_sec, use_case.jitter_sec / 2))
        _sleep_or_stop(state, delay)


def _spawn_loop(state: _State, profile: WorkerProfile) -> None:
    # Stagger initial spawns so we don't fork seven subprocesses simultaneously.
    time.sleep(random.uniform(5, profile.spawn_period_sec / 2))
    while not state.stop:
        _spawn_worker(state, profile.queue, profile.duration_sec)
        _sleep_or_stop(state, profile.spawn_period_sec)


def _sleep_or_stop(state: _State, seconds: float) -> None:
    end = time.monotonic() + seconds
    while not state.stop and time.monotonic() < end:
        time.sleep(min(0.5, end - time.monotonic()))


def _reaper_loop(state: _State) -> None:
    while not state.stop:
        _reap_workers(state)
        time.sleep(2)


def _shutdown_workers(state: _State, grace_sec: float = 5.0) -> None:
    with state.lock:
        live = list(state.workers)
    for w in live:
        if w.process.poll() is None:
            LOG.info("SIGTERM worker queue=%s pid=%d", w.queue, w.process.pid)
            try:
                w.process.terminate()
            except Exception:
                pass
    deadline = time.monotonic() + grace_sec
    for w in live:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            w.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            LOG.warning("SIGKILL worker queue=%s pid=%d (timed out)", w.queue, w.process.pid)
            try:
                w.process.kill()
            except Exception:
                pass


@click.command()
@click.option(
    "--once",
    is_flag=True,
    help="Enqueue one workflow per use case and exit. No workers spawned.",
)
def main(once: bool) -> None:
    """Long-running orchestrator that drives the Argus demo."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    init_dbos(EXECUTOR_ID, worker_queue=None)

    # Import workflows BEFORE launching so the simulator's app_version hash
    # matches the workers'. DBOS only dequeues rows whose app_version matches
    # the live process — if the imports happen after launch, the hash differs
    # and enqueued workflows stick in ENQUEUED forever.
    import workflows  # noqa: F401

    DBOS.launch()
    use_cases = _build_use_cases()

    if once:
        LOG.info("--once: enqueueing one of each use case")
        for uc in use_cases:
            try:
                handle = uc.enqueue_fn()
                wf_id = getattr(handle, "workflow_id", "?")
                LOG.info("enqueued %s → %s (%s)", uc.name, uc.queue, wf_id)
            except Exception as e:
                LOG.warning("enqueue failed %s: %s", uc.name, e)
        DBOS.destroy()
        return

    state = _State()

    def _on_signal(_signum, _frame):
        if state.stop:
            LOG.warning("force exit (second signal)")
            os._exit(130)
        LOG.info("shutdown requested — second signal forces exit")
        state.stop = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    threads: list[threading.Thread] = []
    for uc in use_cases:
        t = threading.Thread(
            target=_enqueue_loop,
            args=(state, uc),
            name=f"enq-{uc.queue}",
            daemon=True,
        )
        t.start()
        threads.append(t)
    for prof in WORKER_PROFILES:
        t = threading.Thread(
            target=_spawn_loop,
            args=(state, prof),
            name=f"spawn-{prof.queue}",
            daemon=True,
        )
        t.start()
        threads.append(t)
    reaper = threading.Thread(target=_reaper_loop, args=(state,), name="reaper", daemon=True)
    reaper.start()

    LOG.info(
        "simulator up — %d enqueue loops, %d worker pools",
        len(use_cases),
        len(WORKER_PROFILES),
    )

    while not state.stop:
        time.sleep(1)

    LOG.info("shutting down workers")
    _shutdown_workers(state)
    LOG.info("destroying DBOS")
    DBOS.destroy()


if __name__ == "__main__":
    main()
