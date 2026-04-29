from dbos_argus import main
from dbos_argus.main import app
from dbos_argus.schema_diff import SchemaIssue, diff_schemas
from dbos_argus.schema_dump import ColumnInfo, SchemaDump, TableInfo, load_expected_dump
from fastapi.testclient import TestClient


def _dump(*tables: tuple[str, list[tuple[str, str]]]) -> SchemaDump:
    return SchemaDump(
        schema="dbos",
        tables=tuple(
            TableInfo(name=t, columns=tuple(ColumnInfo(name=n, data_type=dt) for n, dt in cols))
            for t, cols in tables
        ),
    )


def test_diff_accepts_identical_dumps() -> None:
    expected = _dump(
        ("workflow_status", [("workflow_uuid", "text"), ("created_at", "bigint")]),
    )
    assert diff_schemas(expected, expected) == []


def test_diff_reports_missing_table_column_and_type_mismatch() -> None:
    expected = _dump(
        ("workflow_status", [("workflow_uuid", "text"), ("created_at", "bigint")]),
        ("notifications", [("consumed", "boolean")]),
        ("workflow_events_history", [("key", "text")]),
    )
    actual = _dump(
        ("workflow_status", [("workflow_uuid", "text"), ("created_at", "integer")]),
        ("notifications", []),
    )

    issues = diff_schemas(expected, actual)

    assert [
        (i.kind, i.table_name, i.column_name, i.expected_type, i.actual_type) for i in issues
    ] == [
        ("wrong_type", "workflow_status", "created_at", "bigint", "integer"),
        ("missing_column", "notifications", "consumed", "boolean", None),
        ("missing_table", "workflow_events_history", None, None, None),
    ]


def test_diff_treats_pg_string_synonyms_as_equivalent() -> None:
    expected = _dump(("t", [("c", "text")]))
    actual = _dump(("t", [("c", "character varying")]))
    assert diff_schemas(expected, actual) == []


def test_diff_ignores_extra_tables_and_columns_in_actual() -> None:
    expected = _dump(("t", [("c", "text")]))
    actual = _dump(
        ("t", [("c", "text"), ("extra_col", "text")]),
        ("extra_table", [("x", "text")]),
    )
    assert diff_schemas(expected, actual) == []


def test_load_expected_dump_matches_itself() -> None:
    expected = load_expected_dump()
    assert expected.schema == "dbos"
    assert {t.name for t in expected.tables}, "snapshot should describe at least one table"
    # The snapshot must be self-consistent — diffing it against itself yields no issues.
    assert diff_schemas(expected, expected) == []


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
