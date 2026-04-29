from dbos_argus.settings import Settings


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
