"""CLI behavior that doesn't need a running server.

`main()` exports its flags to `os.environ`, so an autouse fixture snapshots the
environment and restores it afterwards. `monkeypatch.delenv` can't do this job:
on a variable that isn't set it registers nothing to undo, and the deliberately
bad value `main()` writes next would leak into the rest of the suite.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from click.testing import CliRunner
from dbos_argus import cli

_EXPORTED = ("ARGUS_DATABASE_URL", "ARGUS_DBOS_SYSTEM_SCHEMA", "ARGUS_CORS_ORIGINS")


@pytest.fixture(autouse=True)
def _isolated_env() -> Iterator[None]:
    saved = dict(os.environ)
    for name in _EXPORTED:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Stand in for `uvicorn.run`; records the calls instead of serving."""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: calls.append(kw))
    return calls


def test_invalid_schema_flag_is_a_usage_error_not_a_traceback(served: list) -> None:
    result = CliRunner().invoke(cli.main, ["--dbos-system-schema", "bad-name; drop"])
    assert result.exit_code == 2
    assert "Invalid configuration" in result.output
    assert "ARGUS_DBOS_SYSTEM_SCHEMA" in result.output
    assert "plain identifier" in result.output
    assert "Traceback" not in result.output
    assert served == [], "the server must not start with invalid settings"


def test_invalid_schema_from_the_environment_is_reported_the_same_way(
    served: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARGUS_DBOS_SYSTEM_SCHEMA", "1starts_with_digit")
    result = CliRunner().invoke(cli.main, [])
    assert result.exit_code == 2
    assert "ARGUS_DBOS_SYSTEM_SCHEMA" in result.output
    assert served == []


def test_usage_error_does_not_echo_the_database_password(
    served: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = CliRunner().invoke(
        cli.main,
        [
            "--db-url",
            "postgresql://user:hunter2@localhost:5432/db",
            "--dbos-system-schema",
            "bad-name",
        ],
    )
    assert result.exit_code == 2
    assert "hunter2" not in result.output


def test_other_invalid_settings_are_reported_too(
    served: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARGUS_REALTIME_INTERVAL_MS", "soon")
    result = CliRunner().invoke(cli.main, [])
    assert result.exit_code == 2
    assert "ARGUS_REALTIME_INTERVAL_MS" in result.output
    assert served == []


def test_valid_schema_flag_is_exported_and_the_server_starts(served: list) -> None:
    result = CliRunner().invoke(cli.main, ["--dbos-system-schema", "dbosify_default"])
    assert result.exit_code == 0, result.output
    assert os.environ["ARGUS_DBOS_SYSTEM_SCHEMA"] == "dbosify_default"
    assert len(served) == 1
