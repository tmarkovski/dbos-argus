"""DBOS 3 payload reads, including workflows retained from before the upgrade."""

from __future__ import annotations

import base64
import json
import pickle

import pytest
from dbos_argus.db.base import ArgusDB
from dbos_argus.decoding import decode_dbos_value
from dbos_argus.sql_diagnostics import inspect_dbos_schema
from sqlalchemy import text

from .conftest import DBOS_SYSTEM_SCHEMA


@pytest.mark.parametrize("workflow_id", ["wf-root", "wf-child-success", "wf-grandchild-error"])
@pytest.mark.parametrize("field", ["output", "error"])
@pytest.mark.parametrize("serialization", ["portable_json", "py_pickle"])
@pytest.mark.parametrize("legacy_payload", [None, "stale"])
async def test_split_payload_overrides_legacy_value(
    populated_db: tuple[ArgusDB, dict[str, object]],
    workflow_id: str,
    field: str,
    serialization: str,
    legacy_payload: str | None,
) -> None:
    db, _ = populated_db
    p = f'"{DBOS_SYSTEM_SCHEMA}".' if db.dialect == "postgres" else ""
    value = {"result": 42}
    raw = (
        json.dumps(value)
        if serialization == "portable_json"
        else base64.b64encode(pickle.dumps(value)).decode()
    )
    async with db.engine.begin() as conn:
        await conn.execute(
            text(f"DELETE FROM {p}workflow_output WHERE workflow_uuid = :id"),
            {"id": workflow_id},
        )
        await conn.execute(
            text(
                f"UPDATE {p}workflow_status SET output = NULL, error = NULL, "
                "serialization = :serialization WHERE workflow_uuid = :id"
            ),
            {"id": workflow_id, "serialization": serialization},
        )
        await conn.execute(
            text(f"UPDATE {p}workflow_status SET {field} = :legacy WHERE workflow_uuid = :id"),
            {"id": workflow_id, "legacy": legacy_payload},
        )
        await conn.execute(
            text(
                f"INSERT INTO {p}workflow_output (workflow_uuid, {field}, retention_timestamp) "
                "VALUES (:id, :raw, 1700000000000)"
            ),
            {"id": workflow_id, "raw": raw},
        )

    result = await db.get_workflow_result(workflow_id)
    assert result is not None
    assert getattr(result, field) == raw
    assert result.serialization == serialization
    assert json.loads(decode_dbos_value(raw, result.serialization)) == value
    family = (await db.get_workflow_detail("wf-root")).family
    row = next(r for r in family if r.workflow_uuid == workflow_id)
    assert row.has_output is (field == "output")
    assert row.has_error is (field == "error")


async def test_null_split_payload_falls_back_to_legacy_columns(
    populated_db: tuple[ArgusDB, dict[str, object]],
) -> None:
    db, _ = populated_db
    p = f'"{DBOS_SYSTEM_SCHEMA}".' if db.dialect == "postgres" else ""
    async with db.engine.begin() as conn:
        await conn.execute(
            text(
                f"INSERT INTO {p}workflow_output (workflow_uuid, retention_timestamp) "
                "VALUES ('wf-grandchild-error', 1700000000000)"
            )
        )
    result = await db.get_workflow_result("wf-grandchild-error")
    assert result is not None and result.error == '"boom"'
    row = next(
        r
        for r in (await db.get_workflow_detail("wf-root")).family
        if r.workflow_uuid == "wf-grandchild-error"
    )
    assert row.has_error and not row.has_output


async def test_pending_and_missing_workflows_have_no_payload(
    populated_db: tuple[ArgusDB, dict[str, object]],
) -> None:
    db, _ = populated_db
    pending = await db.get_workflow_result("wf-child-pending")
    assert pending is not None and pending.output is None and pending.error is None
    assert await db.get_workflow_result("missing") is None
    assert (await db.get_workflow_detail("missing")).family == []


async def test_diagnostics_requires_split_output_table(
    populated_db: tuple[ArgusDB, dict[str, object]],
) -> None:
    db, _ = populated_db
    p = f'"{DBOS_SYSTEM_SCHEMA}".' if db.dialect == "postgres" else ""
    async with db.engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {p}workflow_output"))
    report = await inspect_dbos_schema(db)
    assert any(
        i.kind == "missing_table" and i.table_name == "workflow_output" for i in report.issues
    )
