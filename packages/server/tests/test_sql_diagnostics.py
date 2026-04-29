from dbos_argus import main
from dbos_argus.main import app
from dbos_argus.sql_diagnostics import (
    DBOS_SCHEMA_EXPECTATIONS,
    SchemaIssue,
    collect_schema_issues,
)
from fastapi.testclient import TestClient


def _expected_schema() -> tuple[set[str], dict[tuple[str, str], str]]:
    tables: set[str] = set()
    columns: dict[tuple[str, str], str] = {}
    for table in DBOS_SCHEMA_EXPECTATIONS:
        tables.add(table.name)
        for column in table.columns:
            columns[(table.name, column.name)] = column.accepted_data_types[0]
    return tables, columns


def test_collect_schema_issues_accepts_expected_schema() -> None:
    tables, columns = _expected_schema()

    assert collect_schema_issues(tables, columns) == []


def test_collect_schema_issues_reports_missing_tables_columns_and_type_mismatches() -> None:
    tables, columns = _expected_schema()
    tables.remove("workflow_events_history")
    columns.pop(("notifications", "consumed"))
    columns[("workflow_status", "created_at")] = "integer"

    issues = collect_schema_issues(tables, columns)

    assert [
        (
            issue.kind,
            issue.table_name,
            issue.column_name,
            issue.expected_type,
            issue.actual_type,
        )
        for issue in issues
    ] == [
        ("wrong_type", "workflow_status", "created_at", "bigint", "integer"),
        (
            "missing_table",
            "workflow_events_history",
            None,
            None,
            None,
        ),
        (
            "missing_column",
            "notifications",
            "consumed",
            "boolean",
            None,
        ),
    ]


class _FakeConnectionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeEngine:
    def connect(self) -> _FakeConnectionContext:
        return _FakeConnectionContext()


def test_sql_diagnostics_endpoint_returns_schema_issues(monkeypatch) -> None:
    async def fake_inspect_dbos_schema(_conn: object) -> list[SchemaIssue]:
        return [
            SchemaIssue(
                kind="missing_table",
                table_name="workflow_schedules",
                column_name=None,
                expected_type=None,
                actual_type=None,
                detail="Missing required table dbos.workflow_schedules.",
            )
        ]

    monkeypatch.setattr(main, "engine", _FakeEngine())
    monkeypatch.setattr(main, "inspect_dbos_schema", fake_inspect_dbos_schema)

    with TestClient(app) as client:
        response = client.get("/api/sql-diagnostics")

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "issues": [
            {
                "kind": "missing_table",
                "table_name": "workflow_schedules",
                "column_name": None,
                "expected_type": None,
                "actual_type": None,
                "detail": "Missing required table dbos.workflow_schedules.",
            }
        ],
    }
