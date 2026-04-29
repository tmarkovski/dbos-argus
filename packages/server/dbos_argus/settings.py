import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_libpq_options(opts: str) -> dict[str, str]:
    # libpq's `options` flag is a string like `-c key=value -c key2=value2`
    # (the `-c` may also be glued to the key, e.g. `-csearch_path=...`).
    # asyncpg has no equivalent, so we lift each `-c` pair into server_settings.
    return dict(re.findall(r"-c\s*([^=\s]+)=(\S+)", opts))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARGUS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://argus:argus@localhost:5432/argus"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg_driver(cls, v: str) -> str:
        # Argus only ships asyncpg. Rewrite bare postgres URLs so users can
        # paste a standard libpq connection string without hitting a psycopg2
        # ImportError from SQLAlchemy's default driver pick.
        for prefix in ("postgresql://", "postgres://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix) :]
        return v

    def asyncpg_engine_args(self) -> tuple[str, dict[str, Any]]:
        # Translate libpq-style query params on the URL into asyncpg connect
        # kwargs, since asyncpg.connect() rejects unknown kwargs (e.g. it has
        # no `options=` and uses `ssl=` instead of `sslmode=`).
        parsed = urlparse(self.database_url)
        params = dict(parse_qsl(parsed.query))
        connect_args: dict[str, Any] = {}

        if "options" in params:
            server_settings = _parse_libpq_options(params.pop("options"))
            if server_settings:
                connect_args["server_settings"] = server_settings

        if "sslmode" in params:
            connect_args["ssl"] = params.pop("sslmode")

        cleaned = urlunparse(parsed._replace(query=urlencode(params)))
        return cleaned, connect_args

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
