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


def _is_azure_postgres_host(hostname: str | None) -> bool:
    return bool(hostname) and hostname.endswith(".postgres.database.azure.com")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARGUS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://argus:argus@localhost:5432/argus"
    # Argus is an unauthenticated read-only dev tool, typically bound to
    # localhost. The default opens CORS / WebSocket origins so the bundled
    # console works on any port and any custom Vite dev port works without
    # extra config. Operators who expose Argus beyond localhost should
    # narrow this to their console origin(s).
    cors_origins: str = "*"
    log_level: str = "INFO"

    # Realtime (WebSocket) layer. The /ws endpoint runs server-side polling
    # tasks and broadcasts deltas to subscribed clients. Disable to fall back
    # to client-side REST polling.
    realtime_enabled: bool = True
    # Default tick interval for data channels (workflows, stats, schedules,
    # notifications). Health uses its own slower interval. Pollers gate the
    # heavy query behind a cheap "did anything change?" cursor query, so this
    # is roughly the upper bound on update latency, not query rate.
    realtime_interval_ms: int = 2000
    realtime_health_interval_ms: int = 5000
    # Cap subscriptions per client connection. A misbehaving (or compromised)
    # client otherwise could open one socket and spin up unlimited keyed
    # pollers by sending distinct param hashes.
    realtime_max_subs_per_conn: int = 64

    @field_validator("database_url")
    @classmethod
    def _force_async_driver(cls, v: str) -> str:
        # Argus ships asyncpg + aiosqlite. Rewrite bare scheme URLs so users
        # can paste a standard libpq / DBOS-style connection string without
        # hitting a sync-driver ImportError from SQLAlchemy's default pick.
        for prefix in ("postgresql://", "postgres://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix) :]
        if v.startswith("sqlite://") and not v.startswith("sqlite+"):
            return "sqlite+aiosqlite://" + v[len("sqlite://") :]
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
        elif _is_azure_postgres_host(parsed.hostname):
            # Azure Database for PostgreSQL requires TLS. Default to libpq's
            # common `sslmode=require` behavior so pasted Azure URLs work
            # without an extra query param, while still letting explicit
            # sslmode=... override this default.
            connect_args["ssl"] = "require"

        cleaned = urlunparse(parsed._replace(query=urlencode(params)))
        return cleaned, connect_args

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
