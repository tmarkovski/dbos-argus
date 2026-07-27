"""`DBOS.sleep` rows store their wakeup time in `output`, but the unit differs
by SDK: the Python SDK records `time.time() + seconds` (unix seconds) while the
TS SDK records `endTimeMs` (unix milliseconds). Reading a TS row as seconds
inflated the duration ~1000x — a 14-day sleep rendered as ~56550 years.
"""

from __future__ import annotations

from dbos_argus.db.rows import StepRow
from dbos_argus.main import _sleep_requested_ms

# 2026-07-27T11:27:16Z — a plausible `started_at_epoch_ms` for both cases.
START_MS = 1_785_151_636_819
FOURTEEN_DAYS_MS = 14 * 24 * 60 * 60 * 1000


def step(sleep_output_raw: str | None, started_at_epoch_ms: int | None = START_MS) -> StepRow:
    return StepRow(
        workflow_uuid="wf-1",
        function_id=18,
        function_name="DBOS.sleep",
        has_output=True,
        has_error=False,
        child_workflow_id=None,
        started_at_epoch_ms=started_at_epoch_ms,
        completed_at_epoch_ms=started_at_epoch_ms,
        event_key=None,
        sleep_output_raw=sleep_output_raw,
    )


def test_typescript_sdk_millisecond_wakeup() -> None:
    """TS SDK: `output` is already ms. Read as seconds this returned
    ~1.786e15 ms (~56550 years) instead of 14 days."""
    wake_ms = START_MS + FOURTEEN_DAYS_MS
    assert _sleep_requested_ms(step(str(wake_ms))) == FOURTEEN_DAYS_MS


def test_python_sdk_second_wakeup() -> None:
    """Python SDK: `output` is unix seconds, as a float string."""
    wake_seconds = (START_MS + 500) / 1000
    assert _sleep_requested_ms(step(str(wake_seconds))) == 500


def test_python_sdk_integral_second_wakeup() -> None:
    """Seconds without a fractional part must not be mistaken for ms. START_MS
    isn't a whole second, so the result lands within 1s of the requested 30s."""
    wake_seconds = START_MS // 1000 + 30
    got = _sleep_requested_ms(step(str(wake_seconds)))
    assert got is not None
    assert abs(got - 30_000) < 1000


def test_zero_duration_sleep() -> None:
    """DBOS records `DBOS.sleep` with start == wakeup for a 0s sleep."""
    assert _sleep_requested_ms(step(str(START_MS))) == 0


def test_wakeup_before_start_returns_none() -> None:
    """Neither interpretation is non-negative — don't invent a duration."""
    assert _sleep_requested_ms(step("1")) is None


def test_non_sleep_step_returns_none() -> None:
    row = StepRow(
        workflow_uuid="wf-1",
        function_id=3,
        function_name="checkout",
        has_output=True,
        has_error=False,
        child_workflow_id=None,
        started_at_epoch_ms=START_MS,
        completed_at_epoch_ms=START_MS,
        event_key=None,
        sleep_output_raw=str(START_MS),
    )
    assert _sleep_requested_ms(row) is None


def test_unparseable_output_returns_none() -> None:
    assert _sleep_requested_ms(step("not-a-number")) is None


def test_missing_output_returns_none() -> None:
    assert _sleep_requested_ms(step(None)) is None


def test_missing_start_returns_none() -> None:
    assert _sleep_requested_ms(step(str(START_MS), started_at_epoch_ms=None)) is None
