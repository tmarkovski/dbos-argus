"""Param normalization tests for the workflows + workflow channels.

These don't hit the DB — they only validate the input-coercion layer
so the channel rejects bad client input before it reaches SQL.
"""

from __future__ import annotations

import pytest
from dbos_argus.realtime.channels.workflow import WorkflowChannel
from dbos_argus.realtime.channels.workflows import WorkflowsChannel

# --- WorkflowsChannel.validate_params ---------------------------------------


def test_workflows_defaults_when_params_omitted() -> None:
    ch = WorkflowsChannel()
    out = ch.validate_params(None)
    assert out == {
        "limit": 50,
        "q": None,
        "started_after_ms": None,
        "started_before_ms": None,
        "statuses": None,
        "queue_name": None,
        "grouped": True,
        "hide_scheduled": False,
    }


def test_workflows_normalizes_iso_datetime_to_epoch_ms() -> None:
    ch = WorkflowsChannel()
    out = ch.validate_params(
        {"started_after": "2026-05-01T00:00:00+00:00", "started_before": 1_780_000_000_000}
    )
    assert out["started_after_ms"] == 1_777_593_600_000  # type: ignore[index]
    assert out["started_before_ms"] == 1_780_000_000_000  # type: ignore[index]


def test_workflows_strips_blank_q() -> None:
    ch = WorkflowsChannel()
    out = ch.validate_params({"q": "   "})
    assert out["q"] is None  # type: ignore[index]


def test_workflows_rejects_unknown_keys() -> None:
    ch = WorkflowsChannel()
    with pytest.raises(ValueError, match="unknown params"):
        ch.validate_params({"weird": True})


def test_workflows_rejects_bad_limit() -> None:
    ch = WorkflowsChannel()
    with pytest.raises(ValueError, match="limit"):
        ch.validate_params({"limit": 0})
    with pytest.raises(ValueError, match="limit"):
        ch.validate_params({"limit": 9999})


def test_workflows_rejects_non_list_status() -> None:
    ch = WorkflowsChannel()
    with pytest.raises(ValueError, match="status"):
        ch.validate_params({"status": "PENDING"})


def test_workflows_empty_status_list_becomes_none() -> None:
    """An empty list filter is semantically the same as no filter; the
    snapshot should treat both identically so the params_key dedupes them
    onto one poller."""
    ch = WorkflowsChannel()
    a = ch.validate_params({"status": []})
    b = ch.validate_params(None)
    assert a == b


def test_workflows_params_key_stable_across_key_order() -> None:
    """`grouped: true` then `limit: 10` should hash the same as the
    reverse — ensures clients don't accidentally double up pollers by
    reordering keys."""
    ch = WorkflowsChannel()
    a = ch.validate_params({"grouped": True, "limit": 10})
    b = ch.validate_params({"limit": 10, "grouped": True})
    assert ch.params_key(a) == ch.params_key(b)


# --- WorkflowChannel.validate_params ---------------------------------------


def test_workflow_requires_id() -> None:
    ch = WorkflowChannel()
    with pytest.raises(ValueError, match="id"):
        ch.validate_params(None)
    with pytest.raises(ValueError, match="id"):
        ch.validate_params({})
    with pytest.raises(ValueError, match="id"):
        ch.validate_params({"id": ""})
    with pytest.raises(ValueError, match="id"):
        ch.validate_params({"id": "   "})


def test_workflow_keeps_only_id() -> None:
    ch = WorkflowChannel()
    out = ch.validate_params({"id": "abc-123", "ignored": "yes"})
    # The channel discards extra keys so the params_key is stable.
    assert out == {"id": "abc-123"}


def test_workflow_distinct_ids_make_distinct_keys() -> None:
    ch = WorkflowChannel()
    a = ch.validate_params({"id": "a"})
    b = ch.validate_params({"id": "b"})
    assert ch.params_key(a) != ch.params_key(b)
