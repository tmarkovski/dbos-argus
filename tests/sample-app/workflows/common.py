"""Shared steps + helpers used across the demo workflows."""

from __future__ import annotations

import logging
import random
import time

from dbos import DBOS

LOG = logging.getLogger("demo")

DEFAULT_FAILURE_RATE = 0.30


def _pause(min_sec: float = 1.0, max_sec: float = 4.0) -> None:
    """Random sleep so steps take long enough to watch in the dashboard."""
    time.sleep(random.uniform(min_sec, max_sec))


@DBOS.step()
def audit(action: str) -> dict:
    _pause()
    return {"action": action, "ts": time.time()}


@DBOS.step()
def log_event(event: str) -> None:
    _pause(0.5, 2.0)
    LOG.info("event: %s", event)


@DBOS.step()
def maybe_fail(label: str, rate: float = DEFAULT_FAILURE_RATE) -> None:
    """Raise with probability `rate`. Used to give every use case a failure path."""
    _pause(0.5, 2.0)
    if random.random() < rate:
        raise RuntimeError(f"simulated failure: {label}")
