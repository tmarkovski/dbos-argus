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
