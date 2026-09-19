import pytest
from dbos_argus.settings import Settings
from pydantic import ValidationError


def test_bare_postgresql_scheme_is_rewritten_to_asyncpg() -> None:
    s = Settings(database_url="postgresql://u:p@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_postgres_scheme_is_rewritten_to_asyncpg() -> None:
    s = Settings(database_url="postgres://u:p@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_explicit_asyncpg_scheme_is_preserved() -> None:
    s = Settings(database_url="postgresql+asyncpg://u:p@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_explicit_psycopg_scheme_is_preserved() -> None:
    # If a user explicitly opts into a sync driver, don't second-guess them.
    s = Settings(database_url="postgresql+psycopg2://u:p@host:5432/db")
    assert s.database_url == "postgresql+psycopg2://u:p@host:5432/db"


def test_asyncpg_engine_args_strips_libpq_options_into_server_settings() -> None:
    s = Settings(
        database_url=("postgresql://u:p@host:5432/db?options=-csearch_path%3Ddbos%2Caipows_core")
    )
    url, kwargs = s.asyncpg_engine_args()
    assert "options=" not in url
    assert kwargs["server_settings"] == {"search_path": "dbos,aipows_core"}


def test_asyncpg_engine_args_handles_multiple_c_flags_with_spaces() -> None:
    s = Settings(
        database_url=(
            "postgresql://u:p@host:5432/db"
            "?options=-c%20search_path%3Dfoo%20-c%20application_name%3Dargus"
        )
    )
    _url, kwargs = s.asyncpg_engine_args()
    assert kwargs["server_settings"] == {
        "search_path": "foo",
        "application_name": "argus",
    }


def test_asyncpg_engine_args_translates_sslmode() -> None:
    s = Settings(database_url="postgresql://u:p@host:5432/db?sslmode=require")
    url, kwargs = s.asyncpg_engine_args()
    assert "sslmode=" not in url
    assert kwargs["ssl"] == "require"


def test_asyncpg_engine_args_defaults_azure_hosts_to_require_ssl() -> None:
    s = Settings(
        database_url=(
            "postgresql://u:p@fmz-e-n-flex-pgsql-ailz-01.postgres.database.azure.com:5432/db"
        )
    )
    url, kwargs = s.asyncpg_engine_args()
    assert url == (
        "postgresql+asyncpg://u:p@fmz-e-n-flex-pgsql-ailz-01.postgres.database.azure.com:5432/db"
    )
    assert kwargs["ssl"] == "require"


def test_asyncpg_engine_args_keeps_explicit_sslmode_for_azure_hosts() -> None:
    s = Settings(
        database_url=(
            "postgresql://u:p@fmz-e-n-flex-pgsql-ailz-01.postgres.database.azure.com:5432/db"
            "?sslmode=disable"
        )
    )
    url, kwargs = s.asyncpg_engine_args()
    assert "sslmode=" not in url
    assert kwargs["ssl"] == "disable"


def test_asyncpg_engine_args_passthrough_when_no_libpq_params() -> None:
    s = Settings(database_url="postgresql+asyncpg://u:p@host:5432/db")
    url, kwargs = s.asyncpg_engine_args()
    assert url == "postgresql+asyncpg://u:p@host:5432/db"
    assert kwargs == {}


def test_dbos_system_schema_defaults_to_dbos(monkeypatch) -> None:
    # CI's custom-schema leg exports the variable for the whole test run.
    monkeypatch.delenv("ARGUS_DBOS_SYSTEM_SCHEMA", raising=False)
    s = Settings(database_url="postgresql+asyncpg://u:p@host:5432/db")
    assert s.dbos_system_schema == "dbos"
    assert s.quoted_dbos_system_schema == '"dbos"'


def test_dbos_system_schema_is_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("ARGUS_DBOS_SYSTEM_SCHEMA", "dbosify_default")
    assert Settings().dbos_system_schema == "dbosify_default"


def test_dbos_system_schema_preserves_case() -> None:
    # DBOS quotes the schema when creating it, so "MyApp" and "myapp" are
    # different schemas and Argus must not fold the case.
    s = Settings(dbos_system_schema="MyApp_dbos")
    assert s.quoted_dbos_system_schema == '"MyApp_dbos"'


@pytest.mark.parametrize(
    "value",
    [
        "",
        "1dbos",
        "my-schema",
        "my schema",
        "dbos.other",
        'dbos"; DROP SCHEMA dbos CASCADE; --',
        "dbos'",
        "a" * 64,
    ],
)
def test_dbos_system_schema_rejects_anything_but_a_plain_identifier(value: str) -> None:
    # The name is interpolated into SQL, so validation is the injection guard.
    with pytest.raises(ValidationError, match="plain identifier"):
        Settings(dbos_system_schema=value)


def test_dbos_system_schema_accepts_the_63_character_postgres_limit() -> None:
    assert Settings(dbos_system_schema="a" * 63).dbos_system_schema == "a" * 63
